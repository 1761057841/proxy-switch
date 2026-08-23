# proxy-switch（飞牛 fnOS 全局透明代理开关）

> 🚀 一键开启/关闭 NAS **全局透明代理**（mihomo + iptables），全机实时生效，无需配置任何程序。
>
> 适用于飞牛 fnOS (fnOS) NAS 应用中心安装。支持 x86_64。

[![fnOS](https://img.shields.io/badge/fnOS-1.1.31xx+-orange.svg)](https://developer.fnnas.com/docs/guide)
[![Arch](https://img.shields.io/badge/Arch-x86__64-lightgrey.svg)]()
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![mihomo](https://img.shields.io/badge/mihomo-GPLv3-blueviolet.svg)](https://github.com/MetaCubeX/mihomo)

## 这是什么？

在飞牛 NAS 上实现**像电脑 Clash 一样实时生效的透明代理开关**：

- **开** = 全机立即走代理，Chrome/任意程序**无需设置、无需重启**，刷新即用
- **关** = 立即恢复直连
- **卸载** = 彻底清理，系统零残留

## 功能特性

- 🌐 **全机透明代理**：网络层劫持（iptables REDIRECT），Chrome、下载、Docker 等**所有程序**实时生效
- ⚡ **实时开关**：开启 = 秒级走代理，关闭 = 立即直连，无需重启任何程序
- 🛡️ **解决 DNS 污染**：mihomo fake-ip DNS（监听 53），国外域名正确解析（YouTube 不再拿到污染 IP）
- 📡 **订阅管理**：管理页填写机场订阅链接，自动生成 proxy-providers 配置，**每小时自动更新节点**
- 🏠 **内网/国内直连**：内网地址 + 国内网站自动直连，不影响 NAS 局域网功能、不拖慢国内访问
- 📶 **可作局域网代理**：7890 混合端口 + 9090 控制面板，局域网设备可直接使用
- 🔌 **端口管理**：管理页 2×2 面板展示 4 个端口（7890 混合/7893 透明/9090 管理 API/53 DNS），可独立开关
- 📊 **实时监控**：实时连接面板（目标/节点/规则/流量）+ 上传下载速度/总量/内存统计卡片
- 🗑️ **卸载彻底清理**：删除 iptables 规则、恢复 DNS、停止 mihomo、删除应用数据目录，无任何残留
- 📦 **开箱即用**：应用包内置 mihomo 内核 + geoip/geosite 数据，安装后填订阅链接即可
- 🐍 **零依赖**：使用系统自带 python3（纯标准库），无需 python312

## 工作原理

```
应用流量(Chrome/任意程序)
    │
    ▼
iptables TP_OUT 链 (OUTPUT 挂钩)
    │  TCP → REDIRECT 7893
    ▼
mihomo (root, redir-port 7893)
    │  DNS 53 → fake-ip 解析
    ▼
机场节点 → 外网
```

- **开启**：启动 mihomo + 添加 iptables 规则 + resolv.conf 指向 127.0.0.1
- **关闭**：删除 iptables 规则 + 恢复 resolv.conf + 停止 mihomo
- **分流**：内网地址（192.168.x / 10.x / 172.16-31.x / localhost）iptables 直接放行；国内网站 mihomo 规则直连；只有国外被墙网站走机场

## 为什么用透明代理？

| | 环境变量代理 | 透明代理（本方案） |
|---|---|---|
| Chrome / 不读 env 的程序 | ❌ 不生效 | ✅ 网络层强制生效 |
| 已运行的程序 | ❌ 需重启 | ✅ 刷新即生效 |
| DNS 污染 | ❌ 无法解决 | ✅ fake-ip 解决 |
| Docker / 系统服务 | ❌ 大多不走 | ✅ 全部走 |

## 目录结构

```
/vol1/@appdata/proxy-switch/          ← 应用数据（卸载时自动清除）
├── state.json                        ← 开关状态 + 订阅链接
└── transparent-proxy/
    ├── tp.sh                         ← 开关脚本 (start|stop|status|restart|purge)
    ├── gen_config.py                 ← 订阅配置生成器（有订阅→providers；无→静态节点）
    ├── mihomo                        ← 代理内核（内置）
    ├── geoip.metadb / geosite.dat    ← 分流数据（内置）
    ├── tp-base.yaml                  ← 配置模板（头部 + rules，含 fnnas 直连规则）
    ├── tp-static.yaml                ← 静态节点（无订阅时使用，用户自备）
    └── tp-config.yaml                ← 最终配置（由 gen_config.py 生成）
```

## 端口

| 端口 | 用途 |
|------|------|
| 7890 | mixed 混合代理（HTTP/SOCKS，局域网可用） |
| 7893 | redir 透明代理端口（iptables 劫持目标） |
| 9090 | external-controller 控制面板 |
| 53 | DNS（fake-ip 解析，覆盖系统 DNS） |

## 快速开始

### 1. 获取安装包

从 [Releases](../../releases) 下载 `proxy-switch.fpk`（已内置 mihomo 内核，开箱即用）。

### 2. 安装

在 fnOS 桌面 → 应用中心 → 手动安装，选择 `proxy-switch.fpk`。

### 3. 配置订阅

打开应用管理页：
1. 在「订阅设置」粘贴你的机场订阅链接（如 `https://xxx.com/api/v1/client/subscribe?token=***`）
2. 点保存 → 自动生成节点配置并重启代理
3. 点「开启」→ 全机走代理

### 4. 手动管理（无应用时）

```bash
sudo /vol1/@appdata/proxy-switch/transparent-proxy/tp.sh start|stop|status|restart|purge
```

## 卸载

fnOS 卸载应用时自动：
- 停止 mihomo、删除 iptables 规则、恢复 resolv.conf
- 删除 `/vol1/@appdata/proxy-switch/` 全部内容（含代理目录）
- 无任何系统残留

## 从源码构建

```bash
# 依赖：fnOS 开发环境 fnpack
cd proxy-switch
fnpack build
# 产物：proxy-switch.fpk
```

## 技术要点

- **应用以 root 运行**（`config/privilege` 声明 `run-as: root`），直接操作 iptables / resolv.conf，无需 sudo
- **mihomo redir 需 root**：iptables REDIRECT 到 7893，`-m owner --uid-owner 0 -j RETURN` 防止死循环
- **DNS 方案**：mihomo 直接监听 `0.0.0.0:53` + resolv.conf 指向 127.0.0.1（比 UDP 53 劫持更可靠）
- **fnnas 直连**：`fnnas.com`/`fnnas.net` 规则直连，避免应用中心被代理劫持导致转圈

## License

- 本项目代码：[GPL-3.0](LICENSE)
- mihomo：[GPLv3](https://github.com/MetaCubeX/mihomo)（MetaCubeX）
- geoip.metadb / geosite.dat：来自 [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 与 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)
