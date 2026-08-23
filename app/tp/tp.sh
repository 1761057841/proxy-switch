#!/bin/bash
# NAS 透明代理实时开关（proxy-switch v2.2+）
# 开启：启动 mihomo(redir 7893 + dns 53) + iptables 规则 + resolv.conf 指向本机
# 关闭：删除 iptables 规则 + 恢复 resolv.conf + 停止 mihomo
# 用法: tp.sh start|stop|status|purge
# 权限：以 root 运行（fnOS 应用进程默认 root，无需 sudo）；mihomo redir 也需要 root(CAP_NET_ADMIN)

BASE=/vol1/1000/transparent-proxy
MIHOMO=$BASE/mihomo
CONF=$BASE/tp-config.yaml
PIDFILE=/tmp/tp-mihomo.pid
REDIR_PORT=7893
RESOLV_CONF=/etc/resolv.conf
RESOLV_BAK=/etc/resolv.conf.bak-tproxy
# 默认 DNS（未备份时恢复用；可通过环境变量 TP_DNS 覆盖）
DNS_SERVER="${TP_DNS:-192.168.3.1}"

ipt() { /usr/sbin/iptables "$@"; }

add_rules() {
    ipt -t nat -N TP_OUT 2>/dev/null || ipt -t nat -F TP_OUT
    for net in 0.0.0.0/8 10.0.0.0/8 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
        ipt -t nat -A TP_OUT -d $net -j RETURN
    done
    # root 流量绕过（mihomo 自身，防死循环）
    ipt -t nat -A TP_OUT -m owner --uid-owner 0 -j RETURN
    # TCP 全部重定向到 mihomo redir（DNS 已直接指向本机 53，无需劫持 UDP 53）
    ipt -t nat -A TP_OUT -p tcp -j REDIRECT --to-ports $REDIR_PORT
    ipt -t nat -A OUTPUT -j TP_OUT 2>/dev/null || true
}

del_rules() {
    ipt -t nat -D OUTPUT -j TP_OUT 2>/dev/null
    ipt -t nat -F TP_OUT 2>/dev/null
    ipt -t nat -X TP_OUT 2>/dev/null
}

mihomo_running() {
    pgrep -f "mihomo -d $BASE" >/dev/null 2>&1
}

start() {
    if mihomo_running; then
        echo "mihomo 已在运行"
    else
        rm -f $PIDFILE
        cd $BASE
        bash -c "cd $BASE && exec $MIHOMO -d $BASE -f $CONF" > $BASE/mihomo.log 2>&1 &
        sleep 3
        if ! mihomo_running; then
            echo "mihomo 启动失败，日志："
            tail -8 $BASE/mihomo.log
            exit 1
        fi
        pgrep -f "mihomo -d $BASE" | head -1 > $PIDFILE
        echo "mihomo 已启动 (pid $(cat $PIDFILE), root)"
    fi
    add_rules
    # DNS 指向本机 mihomo
    if [ ! -f "$RESOLV_BAK" ]; then
        cp "$RESOLV_CONF" "$RESOLV_BAK"
    fi
    bash -c "echo 'nameserver 127.0.0.1' > $RESOLV_CONF"
    echo "iptables 规则已添加 + DNS 已指向本机 → 全机走代理（实时生效）"
}

stop() {
    del_rules
    echo "iptables 规则已删除 → 立即直连"
    # 恢复 DNS
    if [ -f "$RESOLV_BAK" ]; then
        cp "$RESOLV_BAK" "$RESOLV_CONF"
    else
        bash -c "echo 'nameserver $DNS_SERVER' > $RESOLV_CONF"
    fi
    echo "DNS 已恢复"
    if mihomo_running; then
        pkill -f "mihomo -d $BASE" 2>/dev/null
        sleep 1
        rm -f $PIDFILE
        echo "mihomo 已停止"
    fi
}

purge() {
    # 彻底清理：关代理 + 删 systemd 服务 + 删配置备份 + 删代理目录
    stop
    # 移除 systemd 自启服务
    if [ -f /etc/systemd/system/transparent-proxy.service ]; then
        systemctl disable transparent-proxy.service >/dev/null 2>&1 || true
        rm -f /etc/systemd/system/transparent-proxy.service
        systemctl daemon-reload >/dev/null 2>&1 || true
        echo "systemd 自启服务已移除"
    fi
    # 删除 DNS 备份
    rm -f "$RESOLV_BAK"
    # 删除代理目录（mihomo/配置/节点）
    rm -rf "$BASE"
    echo "透明代理目录已删除（$BASE）"
}

status() {
    echo "--- iptables ---"
    ipt -t nat -L TP_OUT -n 2>/dev/null | head -12 || echo "(无 TP_OUT 链 → 代理未开启)"
    echo "--- mihomo ---"
    mihomo_running && echo "mihomo 运行中 (pid $(pgrep -f "mihomo -d $BASE" | head -1))" || echo "mihomo 未运行"
    echo "--- 端口 ---"
    ss -tlnp 2>/dev/null | grep -E "7893|7890" || echo "(无 7893/7890 监听)"
    ss -ulnp 2>/dev/null | grep -E ":53\b" || echo "(无 53 DNS 监听)"
    echo "--- resolv.conf ---"
    cat "$RESOLV_CONF" 2>/dev/null | grep nameserver
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    status) status ;;
    purge) purge ;;
    *) echo "用法: $0 start|stop|status|purge"; exit 1 ;;
esac
