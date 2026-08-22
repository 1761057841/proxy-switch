# proxy-switch（代理开关）

一个简单、轻量的 HTTP 代理服务 fnOS 应用。可在管理页面随时开启或关闭代理，支持普通 HTTP 请求与 HTTPS 隧道（CONNECT）。

## 功能特性

- ⚡ **纯标准库实现**：HTTP 代理服务基于 Python 标准库 `http.server` + `socketserver`，无第三方依赖
- 🔌 **HTTP + HTTPS CONNECT 隧道**：普通 HTTP 请求直转，HTTPS 走 CONNECT 隧道
- 🎚️ **随时开关**：通过管理页面一键开启 / 关闭代理，无需重启应用
- 💾 **状态持久化**：开关状态保存到 `TRIM_PKGVAR/state.json`，应用重启后自动恢复
- 🖥️ **fnOS 统一网关**：管理页面通过 Unix Socket + `/app/proxy-switch` 网关前缀访问，不占用额外 TCP 端口
- 🐍 **依赖 python312**：fnOS 应用中心安装 `python312` 后即可使用

## 快速开始

### 1. 构建 fpk 包

```bash
# 项目根目录执行
fnpack build
```

产物：`proxy-switch.fpk`

### 2. 安装到 fnOS

通过 fnOS 应用中心手动安装，或使用 appcenter-cli：

```bash
appcenter-cli install-fpk proxy-switch.fpk
```

### 3. 使用

1. 打开应用「代理开关」，页面显示当前代理状态
2. 点击开关即可开启 / 关闭代理
3. 代理监听端口：`8888`（`service_port`，可在 manifest 中修改）

## 目录结构

```
proxy-switch/
├── manifest              # fnOS 应用清单（appname/version/端口等）
├── cmd/                  # 生命周期脚本（install/upgrade/config/main）
│   └── main              # 启动/停止/状态 控制脚本
├── app/
│   ├── server/
│   │   └── proxy_server.py   # 主程序：代理服务 + 管理 API + 静态页面
│   ├── ui/
│   │   ├── config        # 桌面入口配置（网关前缀 + socket）
│   │   └── images/       # 图标
│   └── www/
│       └── index.html    # 管理页面
├── config/
│   ├── resource          # API Scope 声明
│   └── privilege         # 运行用户/权限配置
├── ICON.PNG / ICON_256.PNG  # 应用图标
└── gen_icons.py          # 图标生成脚本（纯标准库手写 PNG）
```

## 工作原理

- `cmd/main` 启动时注入环境变量（`SOCKET_PATH` / `PROXY_PORT` / `STATE_FILE` / `WWW_DIR`）并拉起 `proxy_server.py`
- `proxy_server.py` 同时运行两个服务：
  - **代理服务**：监听 `PROXY_PORT`（默认 8888），处理 HTTP 请求与 HTTPS CONNECT
  - **管理服务**：监听 Unix Socket（`app.sock`），通过 fnOS 统一网关暴露管理 API 与静态页面
- 开关状态存于 `state.json`，重启自动恢复；关闭状态下代理端口拒绝连接

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SOCKET_PATH` | 统一网关 Unix Socket 路径 | `/tmp/proxy-switch.sock` |
| `PROXY_PORT` | 代理监听端口 | `8888` |
| `STATE_FILE` | 状态文件路径 | `/tmp/proxy-switch-state.json` |
| `WWW_DIR` | 前端静态页面目录 | 同目录 `www/` |

## License

[MIT](LICENSE)
