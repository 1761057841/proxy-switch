#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_config.py — 根据订阅列表生成 tp-config.yaml
用法:
    gen_config.py                 # 从 state.json 读取 subscriptions（空则用静态节点）
    gen_config.py <订阅URL>        # 显式传入单个订阅链接（兼容旧用法）
    gen_config.py --clear          # 清除订阅，回退静态节点

生成结果:
    有订阅: tp-base.yaml + proxy-providers(airport1..N) + proxy-groups(use 全部)
    无订阅: tp-base.yaml + tp-static.yaml(原静态节点)

state.json 支持两种格式：
    新版（多订阅）:
        {"enabled": true, "subscriptions": [{"name": "机场A", "url": "https://..."}, ...]}
    旧版（单订阅，自动迁移）:
        {"enabled": true, "subscription": "https://..."}
"""
import json
import os
import re
import sys

BASE = os.environ.get("TP_BASE", "/vol1/@appdata/proxy-switch/transparent-proxy")
STATE_FILE = os.environ.get("STATE_FILE", "/vol1/@appdata/proxy-switch/state.json")
BASE_FILE = os.path.join(BASE, "tp-base.yaml")
STATIC_FILE = os.path.join(BASE, "tp-static.yaml")
OUT_FILE = os.path.join(BASE, "tp-config.yaml")

# 保留真实节点的过滤正则（排除机场订阅里的流量信息伪节点）
NODE_FILTER = r"(?i)(🇯🇵|🇭🇰|🇺🇸|🇸🇬|🇹🇼|🇰🇷|🇩🇪|🇯p|日本|香港|新加坡|美国|台湾|韩国|德国|英国|法国|澳大利亚)"

PROVIDER_TMPL = """proxy-providers:
{providers}
proxy-groups:
    - {{ name: PROXY, type: select, use: [{use_list}] }}
    - {{ name: 自动选择, type: url-test, use: [{use_list}], url: 'http://www.gstatic.com/generate_204', interval: 300 }}
    - {{ name: 故障转移, type: fallback, use: [{use_list}], url: 'http://www.gstatic.com/generate_204', interval: 300 }}
"""


def sanitize_name(name, idx):
    """将自定义名称转成合法的 mihomo provider 名（字母数字下划线，不能以数字开头）"""
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", str(name or ""))
    if not s:
        return "airport%d" % idx
    # 中文转拼音不可行，用 airport+序号 保证唯一且合法；名称作为注释保留
    return "airport%d" % idx


def load_subscriptions():
    """从 state.json 读取订阅列表，返回 [{"name":..., "url":...}]"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return []
    subs = st.get("subscriptions")
    if isinstance(subs, list):
        out = []
        for s in subs:
            if isinstance(s, dict):
                url = (s.get("url") or "").strip()
                if url:
                    out.append({"name": (s.get("name") or "").strip() or "订阅%d" % (len(out) + 1),
                                "url": url})
            elif isinstance(s, str) and s.strip():
                out.append({"name": "订阅%d" % (len(out) + 1), "url": s.strip()})
        return out
    # 旧版单订阅
    sub = (st.get("subscription") or "").strip()
    if sub:
        return [{"name": "订阅1", "url": sub}]
    return []


def save_state_subscriptions(subs):
    """保存订阅列表到 state.json（同时迁移旧字段）"""
    try:
        st = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
        st["subscriptions"] = subs
        # 兼容：保留 subscription 字段为第一个订阅（旧逻辑用）
        st["subscription"] = subs[0]["url"] if subs else ""
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("WARN: 保存 state.json 失败: %s" % e)


def main():
    subs = []
    if len(sys.argv) > 1:
        if sys.argv[1] == "--clear":
            save_state_subscriptions([])
        else:
            url = sys.argv[1].strip()
            if url:
                subs = [{"name": "订阅1", "url": url}]
    if not subs:
        subs = load_subscriptions()

    if not os.path.exists(BASE_FILE):
        print("ERROR: 缺少 %s（配置模板），请先部署或从应用包复制" % BASE_FILE)
        sys.exit(1)

    with open(BASE_FILE, "r", encoding="utf-8") as f:
        base = f.read()

    if subs:
        provider_lines = []
        use_list = []
        for idx, s in enumerate(subs, 1):
            pname = sanitize_name(s.get("name", ""), idx)
            pfile = "./providers/%s.yaml" % pname
            use_list.append(pname)
            provider_lines.append(
                "    %s:\n"
                "        type: http\n"
                "        url: \"%s\"\n"
                "        interval: 3600\n"
                "        path: %s\n"
                "        filter: \"%s\"\n"
                "        health-check:\n"
                "            enable: true\n"
                "            url: http://www.gstatic.com/generate_204\n"
                "            interval: 300"
                % (pname, s["url"], pfile, NODE_FILTER)
            )
        block = PROVIDER_TMPL.format(
            providers="\n".join(provider_lines),
            use_list=", ".join(use_list),
        )
        out = base.rstrip() + "\n\n" + block
        mode = "subscription(%d)" % len(subs)
        sub_desc = ", ".join("%s=%s" % (s["name"], s["url"][:25] + "...") for s in subs)
    else:
        if not os.path.exists(STATIC_FILE):
            print("ERROR: 缺少 %s（静态节点），请填入订阅链接或部署静态节点" % STATIC_FILE)
            sys.exit(1)
        with open(STATIC_FILE, "r", encoding="utf-8") as f:
            static = f.read()
        out = base.rstrip() + "\n\n" + static
        mode = "static"
        sub_desc = ""

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK mode=%s bytes=%d %s" % (mode, len(out), sub_desc))


if __name__ == "__main__":
    main()
