#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy-switch 应用主程序 —— NAS 透明代理开关（v2.6）

功能：
1. 管理页面开关：开启 = 启动 mihomo 透明代理 + iptables 规则 + DNS 指向本机（实时生效）
                    关闭 = 删除 iptables 规则 + 恢复 DNS + 停止 mihomo（立即直连）
2. 订阅链接管理：保存订阅 URL → 生成 proxy-providers 配置 → 重启代理生效
3. 状态持久化到 STATE_FILE
4. 测试连接：通过代理访问外网验证
5. MetaCubeXD 面板：静态页面 + /api/mihomo/* 代理到 mihomo external-controller(9090)

透明代理原理（与 Clash TUN 同级别，Chrome/任何程序无需配置）：
   应用流量 → iptables REDIRECT → mihomo(redir 7893 + dns 53) → 机场节点

依赖（部署在 NAS 上）：
   - /vol1/@appdata/proxy-switch/transparent-proxy/tp.sh         开关脚本
   - /vol1/@appdata/proxy-switch/transparent-proxy/mihomo        二进制
   - /vol1/@appdata/proxy-switch/transparent-proxy/tp-config.yaml 配置（含节点）
   - /vol1/@appdata/proxy-switch/transparent-proxy/gen_config.py  配置生成器（订阅/静态）

环境变量：
- SOCKET_PATH  统一网关 Unix Socket 路径（由 cmd/main 传入 ${TRIM_APPDEST}/app.sock）
- STATE_FILE   状态文件路径（由 cmd/main 传入 ${TRIM_PKGVAR}/state.json）
- WWW_DIR      前端静态页面目录（由 cmd/main 传入 ${TRIM_APPDEST}/www）
- GATEWAY_PREFIX 网关前缀（默认 /app/proxy-switch）
"""
import json
import os
import socket
import subprocess
import urllib.request
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingUnixStreamServer

SOCKET_PATH = os.environ.get("SOCKET_PATH", "/tmp/proxy-switch.sock")
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/proxy-switch-state.json")
WWW_DIR = os.environ.get("WWW_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))
GATEWAY_PREFIX = os.environ.get("GATEWAY_PREFIX", "/app/proxy-switch")

# mihomo external-controller 地址（MetaCubeXD 面板数据源）
MIHOMO_API = "http://127.0.0.1:9090"

# 透明代理脚本
TP_SCRIPT = os.environ.get("TP_SCRIPT", "/vol1/@appdata/proxy-switch/transparent-proxy/tp.sh")
GEN_SCRIPT = os.environ.get("GEN_SCRIPT", "/vol1/@appdata/proxy-switch/transparent-proxy/gen_config.py")

_state = {"enabled": False, "subscriptions": []}


def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            _state = json.load(f)
    except Exception:
        _state = {"enabled": False, "subscriptions": []}
    _state.setdefault("enabled", False)
    # 多订阅支持：优先 subscriptions 数组，兼容旧 subscription 字符串
    if "subscriptions" not in _state:
        _state["subscriptions"] = []
    if not isinstance(_state["subscriptions"], list):
        _state["subscriptions"] = []
    old = _state.get("subscription") or ""
    if old and not _state["subscriptions"]:
        _state["subscriptions"] = [{"name": "订阅1", "url": old}]
    if not _state["subscriptions"]:
        _state["subscription"] = ""
    else:
        _state["subscription"] = _state["subscriptions"][0]["url"]


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception:
        pass


def get_subscription():
    """兼容旧接口：返回第一个订阅 URL 或空"""
    subs = _state.get("subscriptions") or []
    if subs:
        return subs[0].get("url", "") if isinstance(subs[0], dict) else str(subs[0])
    return _state.get("subscription", "")


def get_subscriptions():
    """返回订阅列表 [{"name":..., "url":...}]"""
    out = []
    for s in _state.get("subscriptions") or []:
        if isinstance(s, dict):
            url = (s.get("url") or "").strip()
            if url:
                out.append({"name": (s.get("name") or "").strip() or "订阅%d" % (len(out) + 1),
                             "url": url})
        elif isinstance(s, str) and s.strip():
            out.append({"name": "订阅%d" % (len(out) + 1), "url": s.strip()})
    return out


# ---------------------------------------------------------------- 订阅状态（卡片展示）

import re


def get_provider_status():
    """返回每个订阅的完整状态：节点数 / 流量 / 到期 / 更新时间 / 重置
    数据来源：
      - 节点数、updatedAt：mihomo API /providers/proxies/{name}
      - 流量、到期、重置：解析 provider 文件里的伪节点名（机场自带信息）
    """
    subs = get_subscriptions()
    tp_dir = os.path.dirname(GEN_SCRIPT)
    providers_dir = os.path.join(tp_dir, "providers")
    out = []
    for i, s in enumerate(subs, 1):
        pname = "airport%d" % i
        st = {"name": s["name"], "provider": pname, "url": s["url"],
              "nodeCount": 0, "updatedAt": "", "traffic": "", "expire": "", "reset": ""}
        # 节点数 + 更新时间（mihomo API）
        try:
            req = urllib.request.Request(MIHOMO_API + "/providers/proxies/" + pname)
            resp = urllib.request.urlopen(req, timeout=5)
            d = json.loads(resp.read().decode("utf-8"))
            st["nodeCount"] = len(d.get("proxies", []))
            st["updatedAt"] = (d.get("updatedAt") or "")[:19].replace("T", " ")
        except Exception:
            pass
        # 流量 / 到期 / 重置（解析 provider 文件伪节点名）
        pfile = os.path.join(providers_dir, pname + ".yaml")
        try:
            with open(pfile, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            m = re.search(r"剩余流量[：:]\s*([0-9.]+\s*[A-Za-z]+)", content)
            if m:
                st["traffic"] = m.group(1).strip()
            m = re.search(r"套餐到期[：:]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", content)
            if m:
                st["expire"] = m.group(1)
            m = re.search(r"距离下次重置剩余[：:]\s*([0-9]+\s*天)", content)
            if m:
                st["reset"] = m.group(1)
        except Exception:
            pass
        out.append(st)
    return out


def refresh_provider(pname):
    """调用 mihomo 刷新指定 provider，返回 (ok, msg)"""
    try:
        req = urllib.request.Request(MIHOMO_API + "/providers/proxies/" + pname, method="PUT")
        resp = urllib.request.urlopen(req, timeout=30)
        resp.read()
        return True, "刷新成功"
    except urllib.error.HTTPError as e:
        return False, "刷新失败（HTTP %d），可能是机场限流或网络问题" % e.code
    except Exception as e:
        return False, "刷新失败：%s" % str(e)[:100]


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
        if path.startswith("/api/mihomo/"):
            self.proxy_mihomo()
        elif path == "/api/status":
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
                "subscriptions": get_subscriptions(),
            })
        elif path == "/api/subscription":
            self.send_json({"ok": True, "subscriptions": get_subscriptions()})
        elif path == "/api/subscriptions/status":
            self.send_json({"ok": True, "subscriptions": get_provider_status()})
        elif path == "/api/subscriptions/refresh":
            self.send_json({"ok": False, "error": "请使用 POST"}, status=405)
        elif path.startswith("/metacubexd"):
            self.serve_metacubexd(path)
        elif path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.route_path()
        if path.startswith("/api/mihomo/"):
            self.proxy_mihomo()
        elif path == "/api/proxy/on":
            # 先确保配置已生成（有订阅拉取 / 无订阅静态），再启动
            subs = get_subscriptions()
            if subs:
                # 生成多订阅配置：写入临时 state 供 gen_config 读取
                args = ["python3", GEN_SCRIPT]
            else:
                args = ["python3", GEN_SCRIPT, "--clear"]
            try:
                g = subprocess.run(args, capture_output=True, text=True, timeout=60)
                if g.returncode != 0:
                    self.send_json({"enabled": False, "proxy": "", "error": (g.stderr or g.stdout or "生成配置失败").strip()})
                    return
            except Exception as e:
                self.send_json({"enabled": False, "proxy": "", "error": str(e)})
                return
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
                "subscriptions": get_subscriptions(),
            })
        elif path == "/api/test":
            self.send_json(test_proxy_connectivity())
        elif path == "/api/subscriptions/refresh":
            # 刷新单个订阅（provider）
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                body = json.loads(raw) if raw.strip() else {}
            except Exception:
                body = {}
            pname = (body.get("provider") or "").strip()
            if not pname:
                self.send_json({"ok": False, "error": "缺少 provider 参数"})
                return
            ok, msg = refresh_provider(pname)
            self.send_json({"ok": ok, "msg": msg})
        elif path == "/api/subscription":
            self.handle_subscription()
        else:
            self.send_error(404)

    def do_PUT(self):
        path = self.route_path()
        if path.startswith("/api/mihomo/"):
            self.proxy_mihomo()
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = self.route_path()
        if path.startswith("/api/mihomo/"):
            self.proxy_mihomo()
        else:
            self.send_error(404)

    def do_PATCH(self):
        path = self.route_path()
        if path.startswith("/api/mihomo/"):
            self.proxy_mihomo()
        else:
            self.send_error(404)

    # ------------------------------------------------------------ MetaCubeXD

    def proxy_mihomo(self):
        """将 /api/mihomo/* 请求代理到 mihomo external-controller(127.0.0.1:9090)"""
        path = self.path.split("?", 1)[0]
        if path.startswith(GATEWAY_PREFIX):
            path = path[len(GATEWAY_PREFIX):]
        if path.startswith("/api/mihomo/"):
            target = MIHOMO_API + "/" + path[len("/api/mihomo/"):]
            if "?" in self.path:
                target += "?" + self.path.split("?", 1)[1]
        else:
            target = MIHOMO_API + path
        try:
            # 读取请求体
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else None
            # 构造上游请求
            req = urllib.request.Request(target, data=body, method=self.command)
            # 转发关键请求头（排除 hop-by-hop）
            for k, v in self.headers.items():
                if k.lower() in ("content-length", "transfer-encoding", "connection", "host", "accept-encoding"):
                    continue
                req.add_header(k, v)
            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
            resp = urllib.request.urlopen(req, timeout=15)
            resp_body = resp.read()
            ctype = resp.headers.get("Content-Type", "application/json")
            self.send_response(resp.getcode())
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(resp_body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            # 上游返回非 2xx（如 400/404），透传状态码和 body
            try:
                err_body = e.read()
            except Exception:
                err_body = b""
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            if err_body:
                self.wfile.write(err_body)
        except Exception as e:
            self.send_json({"ok": False, "error": "mihomo API 不可用：%s" % str(e)[:120]}, status=502)

    def serve_metacubexd(self, path):
        """提供 MetaCubeXD 静态页面（/metacubexd/*）"""
        rel = path[len("/metacubexd"):].lstrip("/") or "index.html"
        # 防路径穿越
        if ".." in rel:
            self.send_error(403)
            return
        full = os.path.join(WWW_DIR, "metacubexd", rel)
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self.send_error(404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".webmanifest": "application/manifest+json",
        }.get(os.path.splitext(rel)[1].lower(), "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_subscription(self):
        """保存订阅列表 → 重新生成配置 → 重启代理
        支持格式：
            {"subscriptions": [{"name": "机场A", "url": "https://..."}, ...]}
            {"subscription": "https://..."}（兼容旧版单订阅）
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                body = json.loads(raw) if raw.strip() else {}
            except Exception:
                body = {}

            if "subscriptions" in body and isinstance(body["subscriptions"], list):
                new_subs = []
                for i, s in enumerate(body["subscriptions"]):
                    if isinstance(s, dict):
                        url = (s.get("url") or "").strip()
                        if url:
                            new_subs.append({"name": (s.get("name") or "").strip() or "订阅%d" % (i + 1),
                                             "url": url})
                    elif isinstance(s, str) and s.strip():
                        new_subs.append({"name": "订阅%d" % (i + 1), "url": s.strip()})
                _state["subscriptions"] = new_subs
                _state["subscription"] = new_subs[0]["url"] if new_subs else ""
                save_state()
            else:
                # 兼容旧版单订阅
                sub = (body.get("subscription") or "").strip()
                if sub:
                    _state["subscriptions"] = [{"name": "订阅1", "url": sub}]
                else:
                    _state["subscriptions"] = []
                _state["subscription"] = sub
                save_state()

            subs = get_subscriptions()
            # 重新生成配置
            if subs:
                p = subprocess.run(["python3", GEN_SCRIPT],
                                   capture_output=True, text=True, timeout=60)
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
            mode = "订阅模式(%d)" % len(subs) if subs else "静态节点模式"
            self.send_json({
                "ok": True,
                "enabled": enabled,
                "subscriptions": subs,
                "msg": "%s，代理已重启生效" % mode,
            })
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)})

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
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
        # 记录每个请求到 access.log（排查网关转发问题）
        try:
            import datetime
            with open(os.path.join(os.path.dirname(STATE_FILE), "access.log"), "a") as f:
                f.write("%s %s %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), self.command, self.path))
        except Exception:
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
