#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_config.py — 根据订阅链接生成 tp-config.yaml
用法:
    gen_config.py                 # 从 state.json 读取 subscription（空则用静态节点）
    gen_config.py <订阅URL>        # 显式传入订阅链接
    gen_config.py --clear          # 清除订阅，回退静态节点

生成结果:
    有订阅: tp-base.yaml + proxy-providers(airport) + proxy-groups(use airport)
    无订阅: tp-base.yaml + tp-static.yaml(原静态节点)
"""
import json
import os
import sys

BASE = "/vol1/@appdata/proxy-switch/transparent-proxy"
STATE_FILE = os.environ.get("STATE_FILE", "/vol1/@appdata/proxy-switch/state.json")
BASE_FILE = os.path.join(BASE, "tp-base.yaml")
STATIC_FILE = os.path.join(BASE, "tp-static.yaml")
OUT_FILE = os.path.join(BASE, "tp-config.yaml")

PROVIDER_BLOCK = """proxy-providers:
    airport:
        type: http
        url: "{url}"
        interval: 3600
        path: ./providers/airport.yaml
        health-check:
            enable: true
            url: http://www.gstatic.com/generate_204
            interval: 300

proxy-groups:
    - {{ name: PROXY, type: select, use: [airport] }}
    - {{ name: 自动选择, type: url-test, use: [airport], url: 'http://www.gstatic.com/generate_204', interval: 300 }}
    - {{ name: 故障转移, type: fallback, use: [airport], url: 'http://www.gstatic.com/generate_204', interval: 300 }}
"""


def load_state_sub():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
        return (st.get("subscription") or "").strip()
    except Exception:
        return ""


def save_state_sub(url):
    try:
        st = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
        st["subscription"] = url
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("WARN: 保存 state.json 失败: %s" % e)


def main():
    sub = ""
    if len(sys.argv) > 1:
        if sys.argv[1] == "--clear":
            sub = ""
            save_state_sub("")
        else:
            sub = sys.argv[1].strip()
    if not sub:
        sub = load_state_sub()

    if not os.path.exists(BASE_FILE):
        print("ERROR: 缺少 %s（配置模板），请先部署或从应用包复制" % BASE_FILE)
        sys.exit(1)

    with open(BASE_FILE, "r", encoding="utf-8") as f:
        base = f.read()

    if sub:
        block = PROVIDER_BLOCK.format(url=sub)
        out = base.rstrip() + "\n\n" + block
        mode = "subscription"
    else:
        if not os.path.exists(STATIC_FILE):
            print("ERROR: 缺少 %s（静态节点），请填入订阅链接或部署静态节点" % STATIC_FILE)
            sys.exit(1)
        with open(STATIC_FILE, "r", encoding="utf-8") as f:
            static = f.read()
        out = base.rstrip() + "\n\n" + static
        mode = "static"

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK mode=%s bytes=%d sub=%s" % (mode, len(out), sub[:40] + "..." if sub else ""))


if __name__ == "__main__":
    main()
