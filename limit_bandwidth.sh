#!/bin/bash

LOG_FILE="/tmp/lxc_net_debug.log"
echo "=== $(date) Container Start-Host Hook ===" >> $LOG_FILE

# 1. 直接获取与当前容器关联的 veth 网卡
# 通过 ip link 找出 master 关联在 lxcbr0 且名为 veth* 的接口
# 结合容器配置中的 mac 地址或直接通过 ip link 过滤最新创建的接口
HOST_IFACE=$(ip -o link show master lxcbr0 2>/dev/null | grep -oE "veth[A-Za-z0-9_]+" | tail -n 1)

echo "Detected HOST_IFACE: $HOST_IFACE" >> $LOG_FILE

if [ -z "$HOST_IFACE" ]; then
    echo "ERROR: Failed to detect veth interface on lxcbr0" >> $LOG_FILE
    exit 0
fi

# 限速参数 (10Mbps)
DOWNLINK="10mbit"
UPLINK="10mbit"

# 2. 清理旧规则
tc qdisc del dev "$HOST_IFACE" root 2>/dev/null
tc qdisc del dev "$HOST_IFACE" ingress 2>/dev/null

# 3. 挂载限速规则
# 下载限速 (Egress: 宿主机 -> 容器)
tc qdisc add dev "$HOST_IFACE" root tbf rate $DOWNLINK burst 100k latency 50ms 2>&1 >> $LOG_FILE

# 上传限速 (Ingress: 容器 -> 宿主机)
tc qdisc add dev "$HOST_IFACE" handle ffff: ingress 2>&1 >> $LOG_FILE
tc filter add dev "$HOST_IFACE" parent ffff: protocol ip prio 50 u32 \
   match ip src 0.0.0.0/0 \
   police rate $UPLINK burst 100k drop flowid :1 2>&1 >> $LOG_FILE

echo "SUCCESS: Applied tc limit on $HOST_IFACE" >> $LOG_FILE
exit 0
