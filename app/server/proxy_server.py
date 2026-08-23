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
import time
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
TP_DIR = os.path.dirname(TP_SCRIPT)
TP_CONFIG = os.path.join(TP_DIR, "tp-config.yaml")

# 代理模式：规则 MATCH 行指向的组名
# manual → PROXY（手动选节点）; auto → 自动选择（url-test 最低延迟）; fallback → 故障转移
MODE_GROUPS = {"manual": "PROXY", "auto": "自动选择", "fallback": "故障转移"}

_state = {"enabled": False, "subscriptions": [], "mode": "manual", "local_enabled": False}


def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            _state = json.load(f)
    except Exception:
        _state = {"enabled": False, "subscriptions": []}
    _state.setdefault("enabled", False)
    _state.setdefault("local_enabled", False)
    _state.setdefault("mode", "manual")
    if _state.get("mode") not in MODE_GROUPS:
        _state["mode"] = "manual"
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
import time as _time

# 订阅 userinfo 缓存：{url: (timestamp, {total/used/expire})}，避免频繁请求机场被限流
# 成功数据保留 30 分钟；失败时保留旧数据兜底 + 60 秒内不重试打机场
_userinfo_cache = {}
_userinfo_fail_ts = {}   # url -> 最近失败时间
_USERINFO_TTL = 1800  # 30 分钟（成功数据）
_USERINFO_FAIL_TTL = 60  # 失败后 60 秒内不重试


def fetch_userinfo(url):
    """请求订阅 URL 响应头 subscription-userinfo，带缓存（成功 30 分钟 / 失败 60 秒不重试）"""
    now = _time.time()
    # 失败后 60 秒内不重试，直接返回旧数据（或 None）
    if url in _userinfo_fail_ts and now - _userinfo_fail_ts[url] < _USERINFO_FAIL_TTL:
        return _userinfo_cache.get(url, (0, None))[1]
    # 成功缓存 30 分钟内直接用
    if url in _userinfo_cache and now - _userinfo_cache[url][0] < _USERINFO_TTL:
        return _userinfo_cache[url][1]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "clash-verge/v2.0.0"})
        # 先试空代理直连（对部分机场更快）；root 下直连可能被墙（透明代理不劫持 root）
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            resp = opener.open(req, timeout=6)
        except Exception:
            # 直连失败 → 改走 mihomo 本地代理（127.0.0.1:7890 mixed）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            }))
            resp = opener.open(req, timeout=10)
        hdr = resp.headers.get("subscription-userinfo") or ""
        info = {}
        for part in hdr.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                info[k.strip().lower()] = v.strip()
        data = {
            "total": int(info.get("total") or 0),
            "upload": int(info.get("upload") or 0),
            "download": int(info.get("download") or 0),
            "expire": int(info.get("expire") or 0),
        }
        _userinfo_cache[url] = (now, data)
        _userinfo_fail_ts.pop(url, None)
        return data
    except Exception:
        # 失败：记录失败时间避免连续打机场，但保留旧数据兜底
        _userinfo_fail_ts[url] = now
        if url in _userinfo_cache:
            return _userinfo_cache[url][1]
        return None


def get_provider_status():
    """返回每个订阅的完整状态：节点数 / 流量(已用/总量) / 到期 / 更新时间 / 重置
    数据来源：
      - 节点数、updatedAt：mihomo API /providers/proxies/{name}
      - 流量、到期、重置：订阅响应头 subscription-userinfo（标准字段）+ provider 文件伪节点名兜底
    """
    subs = get_subscriptions()
    tp_dir = os.path.dirname(GEN_SCRIPT)
    providers_dir = os.path.join(tp_dir, "providers")
    out = []
    for i, s in enumerate(subs, 1):
        pname = "airport%d" % i
        st = {"name": s["name"], "provider": pname, "url": s["url"],
              "nodeCount": 0, "updatedAt": "", "traffic": "", "expire": "", "reset": "",
              "trafficUsed": "", "trafficTotal": "", "usedPct": 0}
        # 节点数 + 更新时间（mihomo API）
        try:
            req = urllib.request.Request(MIHOMO_API + "/providers/proxies/" + pname)
            resp = urllib.request.urlopen(req, timeout=5)
            d = json.loads(resp.read().decode("utf-8"))
            st["nodeCount"] = len(d.get("proxies", []))
            st["updatedAt"] = (d.get("updatedAt") or "")[:19].replace("T", " ")
        except Exception:
            pass
        # 订阅响应头 subscription-userinfo（总量/已用/到期，带缓存）
        info = fetch_userinfo(s["url"])
        if info and info.get("total"):
            used = info["upload"] + info["download"]
            st["trafficTotal"] = fmt_bytes(info["total"])
            st["trafficUsed"] = fmt_bytes(used)
            st["usedPct"] = round(used / info["total"] * 100, 1)
            st["traffic"] = fmt_bytes(info["total"] - used)  # 剩余 = 总量 - 已用
            if info.get("expire"):
                import datetime
                st["expire"] = datetime.datetime.fromtimestamp(info["expire"]).strftime("%Y-%m-%d")
        # 兜底：解析 provider 文件伪节点名（机场无 userinfo 头时）
        if not st["traffic"] and not st["trafficTotal"]:
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


def fmt_bytes(n):
    """字节数转可读字符串"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.2f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024


def refresh_provider(pname):
    """调用 mihomo 刷新指定 provider，返回 (ok, msg)"""
    # 刷新后清 userinfo 缓存，重新拉取最新流量
    _userinfo_cache.clear()
    _userinfo_fail_ts.clear()
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
    """解析 tp.sh status 输出，判断代理是否开启
    返回 (enabled, local_enabled, output)
      enabled: 总开关 = mihomo 是否在运行（7890 供其他设备用）
      local_enabled: 本机透明代理（TP_OUT 规则存在）
    """
    try:
        p = subprocess.run(["bash", TP_SCRIPT, "status"],
                           capture_output=True, text=True, timeout=15)
        out = (p.stdout or "") + (p.stderr or "")
        local_enabled = "TP_OUT" in out
        enabled = "mihomo 运行中" in out
        return enabled, local_enabled, out
    except Exception:
        return False, False, ""


def set_local_proxy(on):
    """只开关本机透明代理（iptables+DNS），不影响 mihomo 进程
    on=True  → tp.sh start-local（mihomo 必须已在运行）
    on=False → tp.sh stop-local（保留 mihomo 7890 给其他设备）
    返回 (ok, msg)
    """
    action = "start-local" if on else "stop-local"
    ok, out = run_tp(action)
    if not ok:
        return False, out
    return True, out


def get_mode():
    """读取当前代理模式（manual/auto/fallback）"""
    mode = _state.get("mode") or "manual"
    if mode not in MODE_GROUPS:
        mode = "manual"
    return mode


def set_mode(mode):
    """切换代理模式：改 tp-config.yaml 的 MATCH 行 → mihomo 热重载
    返回 (ok, msg)
    """
    if mode not in MODE_GROUPS:
        return False, "未知模式: %s" % mode
    if not os.path.exists(TP_CONFIG):
        return False, "配置文件不存在: %s" % TP_CONFIG
    try:
        with open(TP_CONFIG, "r", encoding="utf-8") as f:
            cfg = f.read()
    except Exception as e:
        return False, "读取配置失败: %s" % e
    import re
    # 替换 MATCH 行（最后一个规则）指向目标组
    new_cfg, n = re.subn(r"(?m)^(\s*-\s*'MATCH,)[^']*'",
                         r"\g<1>%s'" % MODE_GROUPS[mode],
                         cfg)
    if n == 0:
        return False, "配置中未找到 MATCH 规则行"
    try:
        with open(TP_CONFIG, "w", encoding="utf-8") as f:
            f.write(new_cfg)
    except Exception as e:
        return False, "写入配置失败: %s" % e
    # mihomo 热重载（不重启进程，规则即时生效）
    ok, out = reload_mihomo()
    if not ok:
        return False, "配置已写入但重载失败: %s" % out
    _state["mode"] = mode
    save_state()
    return True, "已切换为 %s 模式（%s）" % (mode, MODE_GROUPS[mode])


def reload_mihomo():
    """通过 mihomo API 热重载配置，返回 (ok, msg)"""
    import json as _json
    try:
        body = _json.dumps({"path": TP_CONFIG}).encode()
        req = urllib.request.Request(MIHOMO_API + "/configs?force=true",
                                     data=body, method="PUT",
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 204, "HTTP %d" % resp.status
    except Exception as e:
        return False, str(e)


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
    _stats_prev = None  # 实时速率计算用（上一次快照 (ts, upTotal, downTotal)）

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
        elif path == "/api/stats":
            self.send_json(self.get_live_stats())
        elif path == "/api/status":
            enabled, local_enabled, _ = tp_status()
            _state["enabled"] = enabled
            _state["local_enabled"] = local_enabled
            save_state()
            self.send_json({
                "enabled": enabled,
                "localEnabled": local_enabled,
                "proxy": "mihomo 透明代理",
                "mode": get_mode(),
            })
        elif path == "/api/mode":
            self.send_json({"ok": True, "mode": get_mode(), "groups": MODE_GROUPS})
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
        elif path == "/api/mode":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                body = json.loads(raw) if raw.strip() else {}
            except Exception:
                body = {}
            mode = (body.get("mode") or "").strip().lower()
            if not mode:
                self.send_json({"ok": False, "error": "缺少 mode 参数（manual/auto/fallback）"})
                return
            ok, msg = set_mode(mode)
            self.send_json({"ok": ok, "mode": get_mode(), "msg": msg})
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
            enabled, local_enabled, _ = tp_status()
            _state["enabled"] = enabled
            _state["local_enabled"] = local_enabled
            save_state()
            if ok and enabled:
                self.send_json({"enabled": True, "localEnabled": local_enabled, "proxy": "mihomo 透明代理", "msg": out})
            else:
                self.send_json({"enabled": False, "proxy": "", "error": out or "启动失败"})
        elif path == "/api/proxy/off":
            ok, out = run_tp("stop")
            _state["enabled"] = False
            _state["local_enabled"] = False
            save_state()
            self.send_json({"enabled": False, "localEnabled": False, "proxy": "", "msg": out or "已关闭"})
        elif path == "/api/local/on":
            # 只开本机透明代理（mihomo 需已在运行）
            ok, out = set_local_proxy(True)
            enabled, local_enabled, _ = tp_status()
            _state["enabled"] = enabled
            _state["local_enabled"] = local_enabled
            save_state()
            if ok:
                self.send_json({"ok": True, "enabled": enabled, "localEnabled": local_enabled, "msg": out})
            else:
                self.send_json({"ok": False, "enabled": enabled, "localEnabled": local_enabled, "error": out or "开启失败（mihomo 未运行？）"})
        elif path == "/api/local/off":
            # 只关本机透明代理：删规则+恢复 DNS，mihomo 保留（其他设备继续用 7890）
            ok, out = set_local_proxy(False)
            enabled, local_enabled, _ = tp_status()
            _state["enabled"] = enabled
            _state["local_enabled"] = local_enabled
            save_state()
            if ok:
                self.send_json({"ok": True, "enabled": enabled, "localEnabled": local_enabled, "msg": out})
            else:
                self.send_json({"ok": False, "enabled": enabled, "localEnabled": local_enabled, "error": out or "关闭失败"})
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
        """将 /api/mihomo/* 请求代理到 mihomo external-controller(127.0.0.1:9090)
        支持流式端点（/traffic /memory）：用 http.client 逐块转发
        """
        path = self.path.split("?", 1)[0]
        if path.startswith(GATEWAY_PREFIX):
            path = path[len(GATEWAY_PREFIX):]
        if path.startswith("/api/mihomo/"):
            target = MIHOMO_API + "/" + path[len("/api/mihomo/"):]
            if "?" in self.path:
                target += "?" + self.path.split("?", 1)[1]
        else:
            target = MIHOMO_API + path
        # 流式端点：traffic / memory（SSE，长连接）
        stream_endpoint = target.rstrip("/").endswith(("/traffic", "/memory"))
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else None
            if stream_endpoint:
                self._proxy_stream(target, body)
                return
            req = urllib.request.Request(target, data=body, method=self.command)
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

    def get_live_stats(self):
        """非流式实时统计：内存 + 连接汇总总量/速率
        绕开 fnOS 网关对流式响应的缓冲问题
        """
        import json as _json
        import socket as _sock
        from urllib.parse import urlparse
        u = urlparse(MIHOMO_API)
        out = {"memInuse": 0, "upTotal": 0, "downTotal": 0, "connCount": 0,
               "upSpeed": 0, "downSpeed": 0, "ok": False}
        # 1. 内存：socket 直连读 /memory 第一条
        try:
            s = _sock.create_connection((u.hostname, u.port), timeout=3)
            s.sendall(b"GET /memory HTTP/1.1\r\nHost: %s:%s\r\nAccept: */*\r\nConnection: close\r\n\r\n" % (u.hostname.encode(), str(u.port).encode()))
            buf = b""
            while b"\r\n\r\n" not in buf:
                c = s.recv(4096)
                if not c:
                    break
                buf += c
            head, _, rest = buf.partition(b"\r\n\r\n")
            chunked = b"transfer-encoding: chunked" in head.lower()
            data = rest
            s.settimeout(2)
            # 读多个 chunk，取最后一个非零 inuse（第一条总是 0，统计未就绪）
            last_inuse = 0
            for _ in range(8):
                # 读 chunk 大小行
                while b"\r\n" not in data:
                    try:
                        more = s.recv(4096)
                    except _sock.timeout:
                        break
                    if not more:
                        break
                    data += more
                if b"\r\n" not in data:
                    break
                size_line, _, data = data.partition(b"\r\n")
                try:
                    size = int(size_line.split(b";")[0].strip(), 16)
                except Exception:
                    break
                if size == 0:
                    break
                while len(data) < size + 2:
                    try:
                        more = s.recv(4096)
                    except _sock.timeout:
                        break
                    if not more:
                        break
                    data += more
                if len(data) < size + 2:
                    break
                payload = data[:size]
                data = data[size + 2:]
                try:
                    m = _json.loads(payload)
                    v = int(m.get("inuse", 0))
                    if v > 0:
                        last_inuse = v
                except Exception:
                    pass
            out["memInuse"] = last_inuse
            s.close()
        except Exception:
            pass
        # 2. 连接汇总：GET /connections 普通 JSON
        try:
            req = urllib.request.Request(MIHOMO_API + "/connections")
            resp = urllib.request.urlopen(req, timeout=5)
            d = _json.loads(resp.read().decode("utf-8"))
            cs = d.get("connections", [])
            out["connCount"] = len(cs)
            out["upTotal"] = sum(int(c.get("upload", 0) or 0) for c in cs)
            out["downTotal"] = sum(int(c.get("download", 0) or 0) for c in cs)
            out["ok"] = True
        except Exception:
            pass
        # 3. 速率：基于上次快照
        now = time.time()
        prev = self._stats_prev
        if prev:
            dt = now - prev[0]
            if dt > 0:
                out["upSpeed"] = max(0, (out["upTotal"] - prev[1]) / dt)
                out["downSpeed"] = max(0, (out["downTotal"] - prev[2]) / dt)
        self._stats_prev = (now, out["upTotal"], out["downTotal"])
        return out

    def _proxy_stream(self, target, body=None):
        """流式转发：socket 直连上游，解码 chunked，只转发纯 JSON 行
        （mihomo /traffic /memory 是 chunked SSE 流）
        """
        import socket as _sock
        from urllib.parse import urlparse
        u = urlparse(target)
        try:
            s = _sock.create_connection((u.hostname, u.port), timeout=5)
        except Exception as e:
            self.send_json({"ok": False, "error": "连接 mihomo 失败：%s" % str(e)[:120]}, status=502)
            return
        try:
            path = u.path + (("?" + u.query) if u.query else "")
            req = "%s %s HTTP/1.1\r\nHost: %s:%s\r\nAccept: */*\r\nConnection: close\r\n\r\n" % (
                self.command, path, u.hostname, u.port)
            s.sendall(req.encode())
            # 读响应头
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            try:
                status = int(head.split(b" ")[1])
            except Exception:
                status = 200
            chunked = b"transfer-encoding: chunked" in head.lower()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            if not chunked:
                # 非 chunked：直接转发剩余数据
                if rest:
                    try:
                        self.wfile.write(rest)
                        self.wfile.flush()
                    except Exception:
                        pass
                s.settimeout(1.0)
                while True:
                    try:
                        data = s.recv(4096)
                    except _sock.timeout:
                        continue
                    if not data:
                        break
                    try:
                        self.wfile.write(data)
                        self.wfile.flush()
                    except Exception:
                        break
                return
            # chunked：解码后转发纯数据（去掉大小行）
            data = rest
            s.settimeout(1.0)
            while True:
                # 读 chunk 大小行
                while b"\r\n" not in data:
                    try:
                        more = s.recv(4096)
                    except _sock.timeout:
                        continue
                    if not more:
                        break
                    data += more
                if b"\r\n" not in data:
                    break
                size_line, _, data = data.partition(b"\r\n")
                try:
                    size = int(size_line.split(b";")[0].strip(), 16)
                except Exception:
                    break
                if size == 0:
                    break  # 结束 chunk
                # 读满 size 字节 + 结尾 CRLF
                while len(data) < size + 2:
                    try:
                        more = s.recv(4096)
                    except _sock.timeout:
                        continue
                    if not more:
                        break
                    data += more
                if len(data) < size + 2:
                    break
                payload = data[:size]
                data = data[size + 2:]  # 跳过 chunk 数据和结尾 CRLF
                try:
                    self.wfile.write(payload)
                    self.wfile.flush()
                except Exception:
                    break
        finally:
            try:
                s.close()
            except Exception:
                pass

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
            enabled, local_enabled, _ = tp_status()
            _state["enabled"] = enabled
            _state["local_enabled"] = local_enabled
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
