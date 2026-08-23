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
