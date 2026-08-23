# proxy-switch（NAS 全局代理开关）

填写代理服务器地址（IP:端口），开启后**整个 NAS 上网走代理**，关闭恢复直连。支持可选认证，内网地址自动直连。

## 功能特性

- 🌐 **NAS 全局代理**：填写代理服务器地址（如 `192.168.1.100:7890`），开启后 NAS 新启动的程序全部走代理
- 🔌 **支持认证**：代理服务器需要用户名/密码时可填写
- 🚫 **内网直连**：自动排除局域网地址（192.168.x / 10.x / 172.16-31.x / localhost），不影响 NAS 局域网功能
- 🎚️ **随时开关**：管理页面一键开启 / 关闭，无需重启应用
- 💾 **配置持久化**：保存到 `TRIM_PKGVAR/state.json`，应用重启后自动恢复
- 🔒 **系统级生效**：写入 `/etc/environment` + `/etc/profile.d/proxy-switch.sh` + systemd 全局环境（以 root 运行）
- 🖥️ **fnOS 统一网关**：管理页面通过 Unix Socket + `/app/proxy-switch` 网关前缀访问
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
appcenter-cli install-fpk proxy-switch.fpk --volume-id <id> --yes
```

### 3. 使用

1. 打开应用「NAS全局代理」
2. 填写代理服务器地址（`IP:端口`），如 `192.168.1.100:7890`
3. 需要认证时填写用户名/密码
4. 点击保存，然后打开开关
5. 整个 NAS 新启动的程序（curl、下载、Docker 拉镜像等）走代理
6. 已运行的服务需重启才生效；关闭开关即恢复直连

## 目录结构

```
proxy-switch/
├── manifest              # fnOS 应用清单（appname/version/端口等）
├── cmd/                  # 生命周期脚本（install/upgrade/config/main）
│   └── main              # 启动/停止/状态 控制脚本
├── app/
│   ├── server/
│   │   └── proxy_server.py   # 主程序：管理 API + 系统代理配置 + 静态页面
│   ├── ui/
│   │   ├── config        # 桌面入口配置（网关前缀 + socket）
│   │   └── images/       # 图标
│   └── www/
│       └── index.html    # 管理页面
├── config/
│   ├── resource          # API Scope 声明
│   └── privilege         # 运行用户/权限配置（root 模式）
├── ICON.PNG / ICON_256.PNG  # 应用图标
└── gen_icons.py          # 图标生成脚本
```

## 工作原理

- `cmd/main` 启动时注入环境变量（`SOCKET_PATH` / `STATE_FILE` / `WWW_DIR`）并拉起 `proxy_server.py`
- `proxy_server.py` 以 **root** 运行（`config/privilege` 声明 `run-as: root`），提供管理 API 与静态页面
- 开启代理时写入三处系统配置：
  - `/etc/environment`：全局环境变量（标记块管理，不影响原有内容）
  - `/etc/profile.d/proxy-switch.sh`：登录 shell 生效
  - `/etc/systemd/system.conf.d/10-proxy-switch.conf`：systemd 服务全局环境（重启服务后生效）
- 关闭代理时精确移除上述配置，恢复直连

## 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 查询开关状态、代理地址 |
| POST | `/api/proxy/on` | 开启全局代理 |
| POST | `/api/proxy/off` | 关闭全局代理 |
| POST | `/api/config` | 保存配置 `{"proxy": "ip:port", "auth_user": "", "auth_pass": ""}` |
| POST | `/api/test` | 测试代理连通性 `{"proxy": "ip:port", ...}`（空则用已保存配置） |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SOCKET_PATH` | 统一网关 Unix Socket 路径 | `/tmp/proxy-switch.sock` |
| `STATE_FILE` | 状态/配置文件路径 | `/tmp/proxy-switch-state.json` |
| `WWW_DIR` | 前端静态页面目录 | 同目录 `www/` |

## License

[MIT](LICENSE)
