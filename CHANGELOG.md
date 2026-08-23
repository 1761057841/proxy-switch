# Changelog

## v2.12.2 (2026-08-23)

**新功能：🔌 端口管理面板（订阅机场上方）**

- 新增「端口管理」面板，展示应用使用的 4 个端口，可独立开关：
  - **7890 混合代理**：HTTP/SOCKS5 代理，其他设备手动设置代理时使用
  - **7893 透明代理**：本机流量重定向入口（iptables 劫持后进入）
  - **9090 管理 API**：mihomo 控制接口（面板/节点/连接数据来源）
  - **53 DNS 服务**：域名解析（透明代理使用）
- 2×2 四方格卡片布局，每张卡片显示端口号 + 名称 + 作用 + 开关
- 开关切换：修改 tp-config.yaml 对应行（关闭 = 端口置 0 / 改本机监听）+ mihomo 热重载即时生效
  - 7890/7893 关闭 → 端口置 0
  - 9090 关闭 → 仅 127.0.0.1 监听（外网不可访问）
  - 53 关闭 → 改 127.0.0.1:0（禁外部 DNS，保留 internal 解析）
- 状态存 state.json（`ports` 字段），gen_config.py 重新生成配置时保持端口开关状态
- 新增 API：`GET /api/ports`（读状态）、`POST /api/ports/set`（切换，body `{"port":"mixed|redir|controller|dns","on":true|false}`）
- 提示：关闭「透明代理」或「DNS 服务」会导致本机代理失效（其他设备仍可用 7890）；关闭「管理 API」后仅本机可访问

## v2.12.1 (2026-08-23)

**新功能：实时统计卡片（上传/下载速度 + 总量 + 内存）**

- 实时连接面板顶部新增 5 张统计卡片：
  - ⬆ 上传速度（实时，B/s）
  - ⬇ 下载速度（实时，B/s）
  - 📤 上传总量（累计）
  - 📥 下载总量（累计）
  - 🧠 内存占用（mihomo 进程 MB）
- 数据源：mihomo `/traffic`（速率+总量）、`/memory`（内存）
- 实时连接面板高度动态同步左栏控制台（等高双栏，连接列表内部滚动）

**技术细节**
- 新增后端 API `GET /api/stats`（非流式聚合）：socket 直连 mihomo 读 `/memory` 流多条取最后非零 inuse + `/connections` 汇总每条连接 upload/download 字节算速率
- fnOS 网关（trim_http_cgi）会缓冲流式响应，浏览器无法直连 `/traffic` `/memory` SSE 流 → 改后端聚合 + 前端 2 秒轮询
- proxy_mihomo 增加流式端点支持（socket 原生 + chunked 解码），解决 urllib/http.client 缓冲 SSE 流挂起问题

## v2.12.0 (2026-08-23)

**新功能：代理模式切换（方案B）**

- 代理状态区新增模式切换按钮组：🔧 手动 / ⚡ 自动选择 / 🔁 故障转移
  - **手动**：流量走 PROXY 组，点哪个节点用哪个（默认）
  - **自动选择**：url-test 自动测速，始终用延迟最低的节点，无需手动管
  - **故障转移**：fallback 按顺序用节点，挂了自动切下一个
- 实现机制：修改 tp-config.yaml 的 `MATCH` 规则行指向目标组 + mihomo API 热重载（`PUT /configs?force=true`，不重启进程，规则即时生效）
- 新增 API：`GET /api/mode`（读当前模式）、`POST /api/mode`（切换，body `{"mode":"manual|auto|fallback"}`）
- 模式存 state.json（`mode` 字段），/api/status 返回当前模式
- 前端：三按钮胶囊高亮当前模式 + 模式说明文字；切换成功/失败提示

**技术细节**
- 热重载：`PUT http://127.0.0.1:9090/configs?force=true` + body `{"path": "tp-config.yaml路径"}` → 204
- 自动选择/故障转移组在 gen_config.py 中已生成（url-test/fallback，use 全部 provider），模式切换只改 MATCH 行指向
- 实测：auto 模式 URLTest 自动选台湾专线（当时最低延迟），PROXY 组手动选择不受影响；YouTube 200

## v2.11.1 (2026-08-23)

**修复：页面一直「加载中…」崩溃**

- 根因：v2.10.0 删除独立节点区块时残留了 `setTimeout(() => setPxMsg(''), 1500); });` 两行代码，`setPxMsg` 已不存在且多出一个闭合括号，导致整个 script 块解析失败，所有 JS 不执行，页面永远停在「加载中…」
- 此前验证只测了 API 层，未检查前端 JS 语法（浏览器工具当时不可用无法截图），bug 潜伏至 v2.11.0 发布
- 修复：删除残留两行，`node --check` 语法通过
- 实测（远程 Chrome）：订阅卡片完整渲染、▼展开 59 节点当前✓高亮、⚡测速 59 个延迟徽章全部正常

## v2.11.0 (2026-08-23)

**UI 重构：订阅卡片 + 节点一体化**
- 节点信息合并进订阅卡片：卡片右下角 ▼ 箭头，点击向下展开该订阅的节点列表
- ⚡ 全部测速移到卡片右上角（图标按钮）：一键测全部节点延迟（绿<200 / 黄200-500 / 红>500ms）
- 展开的节点列表：点击节点立即切换（实时生效），当前节点高亮 ✓，显示延迟徽章
- 流量区保留：进度条在上（已用百分比），已用/总量小字在下（如 14.86 GB / 102.00 GB）
- 到期时间 / 重置 / 更新时间保留在卡片底部
- 移除独立「代理节点」区块，整体更紧凑

**技术细节**
- 展开时调 /api/mihomo/providers/proxies/{provider} 拿订阅节点 + /proxies/PROXY 拿当前选中
- 切换节点：PUT /proxies/PROXY {"name":"节点名"}（204）
- 测速：GET /group/PROXY/delay?url=...&timeout=5000（mihomo 组测速返回全部节点延迟）

## v2.10.0 (2026-08-23)

**新功能**
- 🌐 代理节点页（MetaCubeXD 代理页移植）：管理页内嵌节点选择器
  - 策略组标签页（PROXY / 自动选择 / 故障转移），显示当前选中节点
  - 节点网格卡片：点击即切换（实时生效），当前节点高亮 ✓
  - ⚡ 全部测速：一键测试组内全部节点延迟（绿<200 / 黄200-500 / 红>500ms）
  - 🔄 刷新节点
- 技术：调 mihomo API（/proxies 组列表、PUT 切换、group/{name}/delay 组测速），经应用网关 /api/mihomo/ 代理

## v2.9.0 (2026-08-23)


**新功能**
- 🌐 代理节点页（MetaCubeXD 代理页移植）：管理页内嵌节点选择器
  - 策略组标签页（PROXY / 自动选择 / 故障转移），显示当前选中节点
  - 节点网格卡片：点击即切换（实时生效），当前节点高亮 ✓
  - ⚡ 全部测速：一键测试组内全部节点延迟（绿<200 / 黄200-500 / 红>500ms）
  - 🔄 刷新节点
- 技术：调 mihomo API（/proxies 组列表、PUT 切换、group/{name}/delay 组测速），经应用网关 /api/mihomo/ 代理

## v2.9.0 (2026-08-23)

**新功能**
- 订阅信息卡片：每个订阅显示节点数、已用/总流量、剩余流量、到期时间、更新时间
- 总流量从订阅响应头 subscription-userinfo 解析（upload/download/total/expire 标准字段）
- 流量进度条显示已用百分比（如 14.6%）
- 订阅刷新按钮：手动刷新单个订阅（⟳），无需重启代理
- 卡片式布局：编辑（✏️）/ 删除（🗑）按钮，编辑展开内联表单

**技术细节**
- 新增 /api/subscriptions/status（节点数/流量/到期/更新）与 /api/subscriptions/refresh（刷新 provider）
- userinfo 带 5 分钟缓存，避免频繁请求机场被 Cloudflare 限流（429）；空代理直连绕过 mihomo 代理
- 无 userinfo 头时兜底从机场订阅伪节点名解析（剩余流量/套餐到期/距离下次重置）

## v2.8.0 (2026-08-23)


**新功能**
- 订阅信息卡片：每个订阅显示节点数、已用/总流量、剩余流量、到期时间、更新时间
- 总流量从订阅响应头 subscription-userinfo 解析（upload/download/total/expire 标准字段）
- 流量进度条显示已用百分比（如 14.6%）
- 订阅刷新按钮：手动刷新单个订阅（⟳），无需重启代理
- 卡片式布局：编辑（✏️）/ 删除（🗑）按钮，编辑展开内联表单

**技术细节**
- 新增 /api/subscriptions/status（节点数/流量/到期/更新）与 /api/subscriptions/refresh（刷新 provider）
- userinfo 带 5 分钟缓存，避免频繁请求机场被 Cloudflare 限流（429）；空代理直连绕过 mihomo 代理
- 无 userinfo 头时兜底从机场订阅伪节点名解析（剩余流量/套餐到期/距离下次重置）

## v2.8.0 (2026-08-23)


**新功能**
- 支持多订阅：可同时配置多个机场订阅，节点合并到同一策略组（PROXY / 自动选择 / 故障转移）
- 每个订阅支持自定义名称（如「主力机场」「备用机场」），方便区分管理

**技术细节**
- state.json 升级为 subscriptions 数组（兼容旧版单 subscription 字段，自动迁移）
- gen_config.py 循环生成 airport1..N provider，PROXY 组 use 合并全部
- 前端订阅区改为列表式管理：添加 / 删除 / 重命名

## v2.7.3 (2026-08-23)


**修复**
- 应用中心停用应用时，透明代理残留（mihomo/iptables/DNS 未清理）：cmd/main stop 现在会调用 tp.sh stop 彻底停止代理

## v2.7.2 (2026-08-23)


**修复**
- 应用中心无法访问：DNS fake-ip-filter 排除 `*.fnnas.com` / `*.fnnas.net`，DIRECT 直连解析真实 IP
- 代理不通：过滤机场订阅中的流量信息伪节点（剩余流量/重置/到期），PROXY 组默认选中真实节点

## v2.7.1 (2026-08-23)


**修复**
- 面板黑屏问题（多个根因）：
  - API 代理路径从 `/panel/*` 改为 `/api/mihomo/*`（网关对 `/api/` 前缀带登录 cookie 正常放行）
  - 禁用 MetaCubeXD service worker 缓存（sw.js 空壳 + 静态资源 no-store），避免浏览器加载旧版页面
  - 修复后端 proxy_mihomo URL 拼接缺 `/` 的问题
- 面板改回新窗口打开（window.open），不再内嵌 iframe

## v2.7.0 (2026-08-23)

**新功能**
- 集成 MetaCubeXD（mihomo 官方 Web 面板）：查看节点/测延迟/切换策略组
- 面板内嵌应用管理页（iframe 视图），不再新开窗口
- 后端新增 /panel/* 代理路由，无缝对接 mihomo external-controller

## v2.6.0 (2026-08-23)

**新功能**
- 重新设计应用图标：渐变蓝底 + 白色拨动开关（开启状态），4x 超采样抗锯齿

**修复**
- 修复应用图标不显示问题（旧版 fpk 图标缺失）

# Changelog

## v2.12.2 (2026-08-23)

**新功能：🔌 端口管理面板（订阅机场上方）**

- 新增「端口管理」面板，展示应用使用的 4 个端口，可独立开关：
  - **7890 混合代理**：HTTP/SOCKS5 代理，其他设备手动设置代理时使用
  - **7893 透明代理**：本机流量重定向入口（iptables 劫持后进入）
  - **9090 管理 API**：mihomo 控制接口（面板/节点/连接数据来源）
  - **53 DNS 服务**：域名解析（透明代理使用）
- 2×2 四方格卡片布局，每张卡片显示端口号 + 名称 + 作用 + 开关
- 开关切换：修改 tp-config.yaml 对应行（关闭 = 端口置 0 / 改本机监听）+ mihomo 热重载即时生效
  - 7890/7893 关闭 → 端口置 0
  - 9090 关闭 → 仅 127.0.0.1 监听（外网不可访问）
  - 53 关闭 → 改 127.0.0.1:0（禁外部 DNS，保留 internal 解析）
- 状态存 state.json（`ports` 字段），gen_config.py 重新生成配置时保持端口开关状态
- 新增 API：`GET /api/ports`（读状态）、`POST /api/ports/set`（切换，body `{"port":"mixed|redir|controller|dns","on":true|false}`）
- 提示：关闭「透明代理」或「DNS 服务」会导致本机代理失效（其他设备仍可用 7890）；关闭「管理 API」后仅本机可访问

## v2.12.1 (2026-08-23)

**新功能：实时统计卡片（上传/下载速度 + 总量 + 内存）**

- 实时连接面板顶部新增 5 张统计卡片：
  - ⬆ 上传速度（实时，B/s）
  - ⬇ 下载速度（实时，B/s）
  - 📤 上传总量（累计）
  - 📥 下载总量（累计）
  - 🧠 内存占用（mihomo 进程 MB）
- 数据源：mihomo `/traffic`（速率+总量）、`/memory`（内存）
- 实时连接面板高度动态同步左栏控制台（等高双栏，连接列表内部滚动）

**技术细节**
- 新增后端 API `GET /api/stats`（非流式聚合）：socket 直连 mihomo 读 `/memory` 流多条取最后非零 inuse + `/connections` 汇总每条连接 upload/download 字节算速率
- fnOS 网关（trim_http_cgi）会缓冲流式响应，浏览器无法直连 `/traffic` `/memory` SSE 流 → 改后端聚合 + 前端 2 秒轮询
- proxy_mihomo 增加流式端点支持（socket 原生 + chunked 解码），解决 urllib/http.client 缓冲 SSE 流挂起问题

## v2.5.2 (2026-08-23)

**修复**
- gen_config.py 缺文件时明确报错（`sys.exit(1)`），不再生成空配置覆盖正常配置
- tp-base.yaml 模板纳入应用包，安装时自动部署（含 fnnas 直连规则）

## v2.5.1 (2026-08-23)

**修复**
- 应用中心转圈：`fnnas.com`/`fnnas.net` 域名误走代理导致超时，新增直连规则
- tp.sh 新增 `restart` 选项
- install_callback 自动修补 tp-base.yaml（缺 fnnas 规则时插入并重启）

## v2.5.0 (2026-08-23)

**新功能**
- 应用包内置 mihomo 内核 + geoip.metadb + geosite.dat（23MB fpk），安装开箱即用
- install_callback 自动部署全部组件（只复制缺失文件，保留用户配置）

## v2.4.0 (2026-08-23)

**重构**
- 透明代理目录从 `/vol1/1000/transparent-proxy/` 迁移到应用数据目录 `/vol1/@appdata/proxy-switch/transparent-proxy/`，卸载时自动清除
- 应用包内置 tp.sh + gen_config.py，安装自动部署

## v2.3.0 (2026-08-23)

**修复**
- 去除 sudo 密码依赖（应用以 root 运行，直接操作系统）
- 卸载改为彻底清理（tp.sh purge：删规则、恢复 DNS、删目录、删 systemd 服务）

## v2.2.0 (2026-08-23)

**重构**
- 移除 python312 依赖，改用系统自带 python3（纯标准库）

## v2.1 (2026-08-23)

**新功能**
- 订阅链接管理：前台可填写机场订阅 URL，保存自动生成 proxy-providers 配置并重启生效
- 清除订阅回退静态节点模式

## v2.0 (2026-08-23)

**新功能**
- 透明代理模式（mihomo + iptables），全机实时开关，卸载自动清理
- 后端重写：/api/status、/api/proxy/on|off、/api/test、/api/config

## v1.x (2026-08-22)

- 初版：基于环境变量（/etc/environment + profile.d + systemd）的全局代理开关
