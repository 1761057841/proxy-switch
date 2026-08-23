# Changelog

## v2.9.0 (2026-08-23)

**新功能**
- 订阅信息卡片：每个订阅显示节点数、剩余流量、到期时间、重置时间、更新时间
- 订阅刷新按钮：手动刷新单个订阅（⟳），无需重启代理
- 卡片式布局：编辑（✏️）/ 删除（🗑）按钮，编辑展开内联表单

**技术细节**
- 新增 /api/subscriptions/status（节点数/流量/到期/更新）与 /api/subscriptions/refresh（刷新 provider）
- 流量/到期/重置信息从机场订阅自带的伪节点名解析（剩余流量/套餐到期/距离下次重置）

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
