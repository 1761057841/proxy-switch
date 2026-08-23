#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy-switch 应用主程序 —— NAS 透明代理开关（v2.1）

功能：
1. 管理页面开关：开启 = 启动 mihomo 透明代理 + iptables 规则 + DNS 指向本机（实时生效）
                    关闭 = 删除 iptables 规则 + 恢复 DNS + 停止 mihomo（立即直连）
2. 订阅链接管理：保存订阅 URL → 生成 proxy-providers 配置 → 重启代理生效
3. 状态持久化到 STATE_FILE
4. 测试连接：通过代理访问外网验证

透明代理原理（与 Clash TUN 同级别，Chrome/任何程序无需配置）：
   应用流量 → iptables REDIRECT → mihomo(redir 7893 + dns 53) → 机场节点

依赖（部署在 NAS 上）：
   - /vol1/1000/transparent-proxy/tp.sh         开关脚本
   - /vol1/1000/transparent-proxy/mihomo        二进制
   - /vol1/1000/transparent-proxy/tp-config.yaml 配置（含节点）
   - /vol1/1000/transparent-proxy/gen_config.py  配置生成器（订阅/静态）

环境变量：
- SOCKET_PATH  统一网关 Unix Socket 路径（由 cmd/main 传入 ${TRIM_APPDEST}/app.sock）
- STATE_FILE   状态文件路径（由 cmd/main 传入 ${TRIM_PKGVAR}/state.json）
- WWW_DIR      前端静态页面目录（由 cmd/main 传入 ${TRIM_APPDEST}/www）
"""
import json
import os
import socket
import subprocess
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingUnixStreamServer

SOCKET_PATH = os.environ.get("SOCKET_PATH", "/tmp/proxy-switch.sock")
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/proxy-switch-state.json")
WWW_DIR = os.environ.get("WWW_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))
GATEWAY_PREFIX = os.environ.get("GATEWAY_PREFIX", "/app/proxy-switch")

# 透明代理脚本
TP_SCRIPT = os.environ.get("TP_SCRIPT", "/vol1/1000/transparent-proxy/tp.sh")
GEN_SCRIPT = os.environ.get("GEN_SCRIPT", "/vol1/1000/transparent-proxy/gen_config.py")

_state = {"enabled": False, "subscription": ""}


def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            _state = json.load(f)
    except Exception:
        _state = {"enabled": False, "subscription": ""}
    _state.setdefault("enabled", False)
    _state.setdefault("subscription", "")


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception:
        pass


def get_subscription():
    return _state.get("subscription", "")


def run_tp(action):
    """调用 tp.sh，返回 (ok, output)"""
    try:
        p = subprocess.run(["bash", TP_SCRIPT, action],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0, (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return False, str(e)


def tp_status():
    """解析 tp.sh status 输出，判断代理是否开启"""
    try:
        p = subprocess.run(["bash", TP_SCRIPT, "status"],
                           capture_output=True, text=True, timeout=15)
        out = (p.stdout or "") + (p.stderr or "")
        enabled = "mihomo 运行中" in out and "TP_OUT" in out
        return enabled, out
    except Exception:
        return False, ""


# ---------------------------------------------------------------- 代理连通性测试

def test_proxy_connectivity(proxy="", user="", pw=""):
    """通过 mihomo 的 7890 混合端口测试外网连通性（透明代理模式下本机 7890 即代理出口）"""
    import time
    import urllib.request

    proxy_url = "http://127.0.0.1:7890"
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    targets = [
        ("https://www.gstatic.com/generate_204", "GStatic"),
        ("https://cp.cloudflare.com/generate_204", "Cloudflare"),
    ]
    last_err = ""
    for url, name in targets:
        start = time.time()
        try:
            resp = opener.open(url, timeout=8)
            ms = int((time.time() - start) * 1000)
            return {"ok": True, "via": name, "status": resp.getcode(),
                    "latency_ms": ms,
                    "detail": "代理可用，%s 响应 %d，耗时 %dms" % (name, resp.getcode(), ms)}
        except Exception as e:
            last_err = str(e)
    return {"ok": False, "error": last_err[:200],
            "detail": "代理连接失败：%s" % last_err[:150]}


# ---------------------------------------------------------------- 管理 API + 静态页面

class AdminHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def route_path(self):
        path = self.path.split("?", 1)[0]
        if path.startswith(GATEWAY_PREFIX):
            path = path[len(GATEWAY_PREFIX):]
            if not path:
                path = "/"
        return path

    def do_GET(self):
        path = self.route_path()
        if path == "/api/status":
            enabled, _ = tp_status()
            _state["enabled"] = enabled
            save_state()
            self.send_json({
                "enabled": enabled,
                "proxy": "mihomo 透明代理",
            })
        elif path == "/api/config":
            self.send_json({
                "ok": True,
                "enabled": bool(_state.get("enabled")),
                "proxy": "mihomo 透明代理",
                "subscription": get_subscription(),
            })
        elif path == "/api/subscription":
            self.send_json({"ok": True, "subscription": get_subscription()})
        elif path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.route_path()
        if path == "/api/proxy/on":
            ok, out = run_tp("start")
            enabled, _ = tp_status()
            _state["enabled"] = enabled
            save_state()
            if ok and enabled:
                self.send_json({"enabled": True, "proxy": "mihomo 透明代理", "msg": out})
            else:
                self.send_json({"enabled": False, "proxy": "", "error": out or "启动失败"})
        elif path == "/api/proxy/off":
            ok, out = run_tp("stop")
            _state["enabled"] = False
            save_state()
            self.send_json({"enabled": False, "proxy": "", "msg": out or "已关闭"})
        elif path == "/api/config":
            # 兼容旧版
            self.send_json({
                "ok": True,
                "enabled": bool(_state.get("enabled")),
                "proxy": "mihomo 透明代理",
                "subscription": get_subscription(),
            })
        elif path == "/api/test":
            self.send_json(test_proxy_connectivity())
        elif path == "/api/subscription":
            self.handle_subscription()
        else:
            self.send_error(404)

    def handle_subscription(self):
        """保存订阅链接 → 重新生成配置 → 重启代理"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                body = json.loads(raw) if raw.strip() else {}
            except Exception:
                body = {}
            sub = (body.get("subscription") or "").strip()
            _state["subscription"] = sub
            save_state()
            # 重新生成配置
            if sub:
                p = subprocess.run(["python3", GEN_SCRIPT, sub],
                                   capture_output=True, text=True, timeout=30)
            else:
                p = subprocess.run(["python3", GEN_SCRIPT, "--clear"],
                                   capture_output=True, text=True, timeout=30)
            if p.returncode != 0:
                self.send_json({"ok": False, "error": (p.stderr or p.stdout or "生成配置失败").strip()})
                return
            # 重启代理（无论开关状态都重载配置）
            run_tp("stop")
            run_tp("start")
            enabled, _ = tp_status()
            _state["enabled"] = enabled
            save_state()
            mode = "订阅模式" if sub else "静态节点模式"
            self.send_json({
                "ok": True,
                "enabled": enabled,
                "subscription": sub,
                "msg": "%s，代理已重启生效" % mode,
            })
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, name, ctype):
        path = os.path.join(WWW_DIR, name)
        if not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class UnixHTTPServer(ThreadingUnixStreamServer):
    def get_request(self):
        request, _ = super().get_request()
        return request, ("unix", 0)


def main():
    load_state()
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = UnixHTTPServer(SOCKET_PATH, AdminHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
