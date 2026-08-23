# proxy-switch（NAS 透明代理开关）

一键开启/关闭 NAS **全局透明代理**（mihomo + iptables），全机实时生效，Chrome/任何程序无需配置。

## 功能特性

- 🌐 **全机透明代理**：网络层劫持（iptables REDIRECT），Chrome、下载、Docker 等**所有程序**实时生效，无需设置代理
- ⚡ **实时开关**：开启 = 秒级走代理，关闭 = 立即直连，无需重启任何程序
- 🛡️ **解决 DNS 污染**：mihomo fake-ip DNS（监听 53），国外域名正确解析
- 📡 **订阅管理**：前台填写机场订阅链接，自动生成 proxy-providers 配置，每小时自动更新节点
- 📶 **可作局域网代理**：7890 混合端口 + 9090 控制面板，局域网设备可直接使用
- 🗑️ **卸载彻底清理**：删除 iptables 规则、恢复 DNS、停止 mihomo、删除代理目录，无任何残留
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

- 开启：启动 mihomo + 添加 iptables 规则 + resolv.conf 指向 127.0.0.1
- 关闭：删除 iptables 规则 + 恢复 resolv.conf + 停止 mihomo
- 内网地址（192.168.x / 10.x / 172.16-31.x / localhost）自动直连，不劫持

## 目录结构

```
/vol1/@appdata/proxy-switch/          ← 应用数据（卸载时自动清除）
├── state.json                        ← 开关状态 + 订阅链接
├── transparent-proxy/
│   ├── tp.sh                         ← 开关脚本 (start|stop|status|purge)
│   ├── gen_config.py                 ← 订阅配置生成器
│   ├── mihomo                        ← 代理内核（需自行放置）
│   ├── tp-config.yaml                ← 代理配置（生成）
│   ├── tp-base.yaml                  ← 配置模板（头部+rules）
│   └── tp-static.yaml                ← 静态节点（无订阅时用）
```

> mihomo 二进制与机场节点配置不属于应用包（用户资产），首次安装后需从已有机器复制到 `transparent-proxy/` 目录，或直接在前台填写订阅链接。

## 端口

| 端口 | 用途 |
|------|------|
| 7890 | mixed 混合代理（HTTP/SOCKS，局域网可用） |
| 7893 | redir 透明代理端口（iptables 劫持目标） |
| 9090 | external-controller 控制面板 |
| 53 | DNS（fake-ip 解析，覆盖系统 DNS） |

## 快速开始

### 1. 构建 fpk 包

```bash
cd /vol1/1000/OpenClaw项目/proxy-switch
fnpack build
```

### 2. 安装

在 fnOS 应用中心安装 `proxy-switch.fpk`（v2.4+）。安装后：

1. 将 mihomo 二进制、geoip.metadb、geosite.dat 复制到 `/vol1/@appdata/proxy-switch/transparent-proxy/`
2. 从已有机器复制 `tp-config.yaml`（或在前台填订阅链接）
3. 打开管理页面，点开关即可

### 3. 手动管理（无应用时）

```bash
sudo /vol1/@appdata/proxy-switch/transparent-proxy/tp.sh start|stop|status|purge
```

## 卸载

fnOS 卸载应用时自动：
- 停止 mihomo、删除 iptables 规则、恢复 DNS
- 删除 `/vol1/@appdata/proxy-switch/` 全部内容（含代理目录）
- 无任何系统残留
