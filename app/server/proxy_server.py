#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proxy-switch 应用主程序

功能：
1. HTTP 代理服务（标准库实现，支持普通 HTTP 与 HTTPS CONNECT 隧道），监听 PROXY_PORT
2. 管理 API + 静态页面服务，监听 Unix Socket（配合 fnOS 统一网关 /app/proxy-switch）
3. 代理开关状态持久化到 STATE_FILE（TRIM_PKGVAR 下，应用重启后恢复）

环境变量：
- SOCKET_PATH  统一网关 Unix Socket 路径（由 cmd/main 传入 ${TRIM_APPDEST}/app.sock）
- PROXY_PORT   代理监听端口（由 cmd/main 传入 ${TRIM_SERVICE_PORT}）
- STATE_FILE   状态文件路径（由 cmd/main 传入 ${TRIM_PKGVAR}/state.json）
- WWW_DIR      前端静态页面目录（由 cmd/main 传入 ${TRIM_APPDEST}/www）
"""
import json
import math
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingUnixStreamServer

SOCKET_PATH = os.environ.get("SOCKET_PATH", "/tmp/proxy-switch.sock")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8888"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/proxy-switch-state.json")
WWW_DIR = os.environ.get("WWW_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "www"))

_lock = threading.Lock()
_state = {"enabled": False}
_proxy_sock = None
_proxy_thread = None

# ---------------------------------------------------------------- 状态持久化

def load_state():
    global _state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            _state = json.load(f)
    except Exception:
        _state = {"enabled": True}  # 首次运行默认开启代理


def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_state, f)
    except Exception:
        pass

# ---------------------------------------------------------------- 代理服务

def start_proxy():
    """开启代理：绑定 TCP 端口并启动接受线程。"""
    global _proxy_sock, _proxy_thread
    with _lock:
        if _proxy_sock is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", PROXY_PORT))
        s.listen(128)
        _proxy_sock = s
        t = threading.Thread(target=proxy_accept_loop, args=(s,), daemon=True)
        _proxy_thread = t
        t.start()
        _state["enabled"] = True
        save_state()


def stop_proxy():
    """关闭代理：关闭监听 socket，接受线程随之退出。"""
    global _proxy_sock, _proxy_thread
    with _lock:
        if _proxy_sock is None:
            return
        # 必须先用 shutdown() 唤醒阻塞在 accept() 的线程，再 close()
        # （仅 close() 不会中断其他线程的 accept()，端口会残留监听）
        try:
            _proxy_sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            _proxy_sock.close()
        except Exception:
            pass
        _proxy_sock = None
        _proxy_thread = None
        _state["enabled"] = False
        save_state()


def proxy_accept_loop(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return  # socket 已关闭（代理被关）
        threading.Thread(target=handle_proxy_client, args=(conn,), daemon=True).start()


def handle_proxy_client(conn):
    try:
        conn.settimeout(60)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
            if len(data) > 1_000_000:
                return
        request_line, rest = data.split(b"\r\n", 1)
        parts = request_line.split(b" ")
        if len(parts) < 3:
            return
        method, target, version = parts[0], parts[1], parts[2]

        if method == b"CONNECT":
            handle_connect(conn, target)
        else:
            handle_http(conn, method, target, version, rest, data)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def handle_connect(conn, target):
    """HTTPS 隧道：与目标建立 TCP 连接后双向转发。"""
    host, _, port = target.partition(b":")
    try:
        port = int(port or 443)
        remote = socket.create_connection((host.decode("utf-8", "replace"), port), timeout=30)
    except Exception:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
        return
    try:
        conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    except Exception:
        remote.close()
        return
    conn.settimeout(None)
    remote.settimeout(None)
    pipe(conn, remote)
    remote.close()


def handle_http(conn, method, target, version, header_block, full_data):
    """普通 HTTP 代理：解析目标，重组请求并转发。"""
    target_str = target.decode("utf-8", "replace")
    host = None
    port = 80
    path = target_str

    if target_str.startswith("http://"):
        from urllib.parse import urlsplit
        u = urlsplit(target_str)
        host = u.hostname
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
    else:
        # 相对路径形式：从 Host 头取目标
        for line in header_block.split(b"\r\n"):
            if line.lower().startswith(b"host:"):
                host = line[5:].strip().decode("utf-8", "replace")
                break
        if not host:
            return
        if not host.startswith("[") and host.count(":") == 1:
            h, _, p = host.rpartition(":")
            try:
                port = int(p)
                host = h
            except ValueError:
                port = 80

    try:
        remote = socket.create_connection((host, port), timeout=30)
    except Exception:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except Exception:
            pass
        return

    new_request_line = b"%s %s %s" % (method, path.encode("utf-8", "replace"), version)
    headers_out = []
    for line in header_block.split(b"\r\n"):
        low = line.lower()
        if low.startswith(b"proxy-connection") or low.startswith(b"connection:"):
            continue
        headers_out.append(line)
    header_block_out = b"\r\n".join(headers_out)
    body = full_data.partition(b"\r\n\r\n")[2]
    request = new_request_line + b"\r\n" + header_block_out + b"\r\nConnection: close\r\n\r\n" + body

    try:
        remote.sendall(request)
    except Exception:
        remote.close()
        return

    conn.settimeout(None)
    remote.settimeout(None)
    while True:
        chunk = remote.recv(65536)
        if not chunk:
            break
        conn.sendall(chunk)
    remote.close()


def pipe(a, b):
    """双向转发（用于 CONNECT 隧道）。"""
    def fwd(src, dst):
        try:
            while True:
                chunk = src.recv(65536)
                if not chunk:
                    break
                dst.sendall(chunk)
        except Exception:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    t1 = threading.Thread(target=fwd, args=(a, b), daemon=True)
    t2 = threading.Thread(target=fwd, args=(b, a), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

# ---------------------------------------------------------------- 管理 API + 静态页面

class AdminHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            self.send_json({
                "enabled": bool(_state.get("enabled")),
                "port": PROXY_PORT,
            })
        elif path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/proxy/on":
            start_proxy()
            self.send_json({"enabled": True, "port": PROXY_PORT})
        elif path == "/api/proxy/off":
            stop_proxy()
            self.send_json({"enabled": False, "port": PROXY_PORT})
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
    if _state.get("enabled"):
        start_proxy()
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    server = UnixHTTPServer(SOCKET_PATH, AdminHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
