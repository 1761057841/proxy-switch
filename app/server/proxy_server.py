#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy-switch 应用主程序 —— NAS 全局代理开关

功能：
1. 管理页面填写代理服务器地址（IP:端口，可选认证）
2. 开启：以 root 写入系统全局代理配置，整个 NAS 新启动的进程走代理
   - /etc/environment
   - /etc/profile.d/proxy-switch.sh
   - /etc/systemd/system.conf.d/10-proxy-switch.conf（systemd 全局环境，重启服务后生效）
3. 关闭：精确移除上述配置，恢复直连
4. 状态持久化到 STATE_FILE（TRIM_PKGVAR 下），应用重启后恢复

环境变量：
- SOCKET_PATH  统一网关 Unix Socket 路径（由 cmd/main 传入 ${TRIM_APPDEST}/app.sock）
- STATE_FILE   状态文件路径（由 cmd/main 传入 ${TRIM_PKGVAR}/state.json）
- WWW_DIR      前端静态页面目录（由 cmd/main 传入 ${TRIM_APPDEST}/www）
"""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingUnixStreamServer

SOCKET_PATH = os.environ.get("SOCKET_PATH", "/tmp/proxy-switch.sock")
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/proxy-switch-state.json")
WWW_DIR = os.environ.get("WWW_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))
# fnOS 统一网关前缀：网关转发时保留完整路径（/app/proxy-switch/...），
# 应用需自行剥离后再匹配路由
GATEWAY_PREFIX = os.environ.get("GATEWAY_PREFIX", "/app/proxy-switch")

# 系统代理配置文件（需 root）
ENV_FILE = "/etc/environment"
PROFILE_SH = "/etc/profile.d/proxy-switch.sh"
SYSTEMD_CONF = "/etc/systemd/system.conf.d/10-proxy-switch.conf"

# 内网直连白名单（NO_PROXY），避免代理影响局域网访问
NO_PROXY_DEFAULT = "localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.local"

_lock = None
try:
    import threading
    _lock = threading.Lock()
except Exception:
    pass

_state = {"enabled": False, "proxy": "", "auth_user": "", "auth_pass": ""}


# ---------------------------------------------------------------- 状态持久化

def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            _state = json.load(f)
    except Exception:
        _state = {"enabled": False, "proxy": "", "auth_user": "", "auth_pass": ""}
    _state.setdefault("enabled", False)
    _state.setdefault("proxy", "")
    _state.setdefault("auth_user", "")
    _state.setdefault("auth_pass", "")


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception:
        pass


def proxy_url():
    """拼出代理 URL：http://[user:pass@]host:port"""
    proxy = (_state.get("proxy") or "").strip()
    if not proxy:
        return ""
    auth = ""
    if _state.get("auth_user"):
        import urllib.parse
        user = urllib.parse.quote(_state.get("auth_user", ""), safe="")
        pw = urllib.parse.quote(_state.get("auth_pass", ""), safe="")
        auth = "%s:%s@" % (user, pw)
    return "http://%s%s" % (auth, proxy)


# ---------------------------------------------------------------- 系统代理配置

def _env_lines(prefix):
    url = proxy_url()
    lines = []
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        lines.append("%s%s=%s" % (prefix, name, url))
    lines.append("%sNO_PROXY=%s" % (prefix, NO_PROXY_DEFAULT))
    lines.append("%sno_proxy=%s" % (prefix, NO_PROXY_DEFAULT))
    return lines


def _marker_lines():
    return ["# BEGIN proxy-switch (managed by proxy-switch app, do not edit)",
            "# END proxy-switch"]


def _write_environment():
    """写 /etc/environment：保留原有内容，用标记块替换代理配置。"""
    content = ""
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        pass
    lines = content.splitlines()

    # 删除旧的标记块
    out = []
    skip = False
    for ln in lines:
        if ln.strip() == "# BEGIN proxy-switch (managed by proxy-switch app, do not edit)":
            skip = True
            continue
        if ln.strip() == "# END proxy-switch":
            skip = False
            continue
        if not skip:
            out.append(ln)
    # 去掉末尾空行
    while out and out[-1].strip() == "":
        out.pop()

    out += [""] + ["# BEGIN proxy-switch (managed by proxy-switch app, do not edit)"] \
          + _env_lines("") \
          + ["# END proxy-switch"]
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def _remove_environment():
    """移除 /etc/environment 中的代理标记块。"""
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return
    lines = content.splitlines()
    out = []
    skip = False
    for ln in lines:
        if ln.strip() == "# BEGIN proxy-switch (managed by proxy-switch app, do not edit)":
            skip = True
            continue
        if ln.strip() == "# END proxy-switch":
            skip = False
            continue
        if not skip:
            out.append(ln)
    while out and out[-1].strip() == "":
        out.pop()
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + ("\n" if out else ""))


def _write_profile_sh():
    """写 /etc/profile.d/proxy-switch.sh（登录 shell 生效）。"""
    body = _env_lines("export ")
    with open(PROFILE_SH, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")


def _remove_profile_sh():
    try:
        os.remove(PROFILE_SH)
    except Exception:
        pass


def _write_systemd_conf():
    """写 systemd 全局环境：影响之后启动的 systemd 服务（含 Docker 等）。"""
    url = proxy_url()
    lines = ["[Manager]", "DefaultEnvironment="]
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        lines.append('    "%s=%s"' % (name, url))
    lines.append('    "NO_PROXY=%s"' % NO_PROXY_DEFAULT)
    lines.append('    "no_proxy=%s"' % NO_PROXY_DEFAULT)
    try:
        os.makedirs(os.path.dirname(SYSTEMD_CONF), exist_ok=True)
        with open(SYSTEMD_CONF, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.system("systemctl daemon-reload >/dev/null 2>&1")
    except Exception:
        pass


def _remove_systemd_conf():
    try:
        os.remove(SYSTEMD_CONF)
        os.system("systemctl daemon-reload >/dev/null 2>&1")
    except Exception:
        pass


def apply_proxy():
    """开启：写入全部系统代理配置。"""
    _write_environment()
    _write_profile_sh()
    _write_systemd_conf()
    _state["enabled"] = True
    save_state()


def remove_proxy():
    """关闭：移除全部系统代理配置。"""
    _remove_environment()
    _remove_profile_sh()
    _remove_systemd_conf()
    _state["enabled"] = False
    save_state()


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
            self.send_json({
                "enabled": bool(_state.get("enabled")),
                "proxy": _state.get("proxy", ""),
                "hasAuth": bool(_state.get("auth_user")),
            })
        elif path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.route_path()
        if path == "/api/proxy/on":
            apply_proxy()
            self.send_json({"enabled": True, "proxy": _state.get("proxy", "")})
        elif path == "/api/proxy/off":
            remove_proxy()
            self.send_json({"enabled": False, "proxy": ""})
        elif path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b"{}"
                cfg = json.loads(body.decode("utf-8"))
                proxy = (cfg.get("proxy") or "").strip()
                # 校验格式 host:port
                if proxy:
                    host, _, port = proxy.rpartition(":")
                    if not host or not port:
                        raise ValueError("bad proxy")
                    port = int(port)
                    if not (1 <= port <= 65535):
                        raise ValueError("bad port")
                _state["proxy"] = proxy
                _state["auth_user"] = (cfg.get("auth_user") or "").strip()
                _state["auth_pass"] = cfg.get("auth_pass") or ""
                save_state()
                # 若代理正在开启状态，立即应用新配置
                if _state.get("enabled"):
                    apply_proxy()
                self.send_json({"ok": True, "enabled": bool(_state.get("enabled")), "proxy": proxy})
            except Exception:
                self.send_json({"ok": False, "error": "代理地址格式应为 IP:端口，如 192.168.1.100:7890"})
        else:
            self.send_error(404)

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
