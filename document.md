[toc]


# 前奏
```shell
rambo@debian137:~$ cat /etc/debian_version
13.7
rambo@debian137:~$ uname -a
Linux debian137 6.12.107+deb13-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.107-1 (2026-08-29) x86_64 GNU/Linux


rambo@debian137:~$ grep -v ^# /etc/apt/sources.list | grep -v ^$
deb http://deb.debian.org/debian/ trixie main non-free-firmware
deb-src http://deb.debian.org/debian/ trixie main non-free-firmware
deb http://security.debian.org/debian-security trixie-security main non-free-firmware
deb-src http://security.debian.org/debian-security trixie-security main non-free-firmware
deb http://deb.debian.org/debian/ trixie-updates main non-free-firmware
deb-src http://deb.debian.org/debian/ trixie-updates main non-free-firmware


rambo@debian137:~$ sudo apt update && sudo apt install -y vim wget curl net-tools openssh-server
 

```



# 安装传统(原生)LXC
```shell
rambo@debian137:~$ sudo apt install -y \
lxc lxc-templates \
debootstrap bridge-utils \
uidmap apparmor \
apparmor-utils dnsmasq-base
 
Debian 文档列出的基本 LXC 安装方式就是安装 lxc
debootstrap 和 bridge-utils 用于创建容器和网络配置，非特权容器还需要uidmap等组件


判断自己装的是lxd还是lxd方式：
有 /usr/bin/lxc-create、/usr/bin/lxc-start等   => 传统 LXC
有 lxd 命令，并且 lxc list 能正常连接 daemon      => LXD
有 incus 命令，并且 incus list 能正常工作         => Incus

LXC  = 底层容器运行时和工具
LXD  = 构建在LXC之上的容器管理器


检查宿主机内核是否具备 LXC 所需功能：
rambo@debian137:~$ sudo lxc-checkconfig

重点观察是否有 enabled、available 或类似正常状态。检查AppArmor：
rambo@debian137:~$ sudo systemctl enable --now apparmor
rambo@debian137:~$ sudo aa-status
如果 lxc-checkconfig 中出现某些功能缺失，先不要创建生产容器，应先解决内核或相关软件包问题
 

# 查看IP
rambo@debian137:~$ ip a sh lxcbr0
3: lxcbr0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default qlen 1000
    link/ether 10:66:6a:00:00:00 brd ff:ff:ff:ff:ff:ff
    inet 10.0.3.1/24 brd 10.0.3.255 scope global lxcbr0       ===> 自带的是3.1
       valid_lft forever preferred_lft forever
    inet6 fc42:5009:ba4b:5ab0::1/64 scope global 
       valid_lft forever preferred_lft forever


# 如需修改lxcbr0的IP
rambo@debian137:~$ sudo vim /etc/default/lxc-net
USE_LXC_BRIDGE="true"           # 这一行是自带的
LXC_BRIDGE="lxcbr0"
LXC_ADDR="10.0.3.10"            # 默认是3.1(不改也可)
LXC_NETWORK="10.0.3.0/24"
LXC_DHCP_RANGE="10.0.3.11,10.0.3.254"     # 也修改了ip从3.11开始(不改也可)
LXC_DHCP_MAX="243"                        # ip最多数量(不改也可)

启动网络服务：
rambo@debian137:~$ sudo systemctl enable --now lxc-net
rambo@debian137:~$ sudo systemctl restart lxc-net
rambo@debian137:~$ systemctl status lxc-net
如果能看到 lxcbr0，说明宿主机的 LXC NAT 网桥基本建立成功。LXC 默认的独立网桥通常使用私有网段，并通过宿主机进行 NAT；这种方式适合先学习和运行普通服务

如果希望容器直接获得局域网IP，需要配置 Linux bridge，例如br0，并把物理网卡接入网桥。这种配置与Debian的网络管理方式有关，而且远程操作时配置错误可能导致宿主机断网，所以建议先用NAT，确认LXC正常后再改桥接网络


检查网桥：
rambo@debian137:~$ ip a sh lxcbr0
4: lxcbr0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue state DOWN group default qlen 1000
    link/ether 10:66:6a:00:00:00 brd ff:ff:ff:ff:ff:ff
    inet 10.0.3.10/24 brd 10.0.3.255 scope global lxcbr0
       valid_lft forever preferred_lft forever
    inet6 fc42:5009:ba4b:5ab0::1/64 scope global 
       valid_lft forever preferred_lft forever




# 把3.10又改回了3.1，就是把lxcbr0的IP固定下来
rambo@debian137:~$ sudo vim /etc/default/lxc-net
USE_LXC_BRIDGE="true"           # 这一行是自带的
LXC_BRIDGE="lxcbr0"
LXC_ADDR="10.0.3.1"            # 默认是3.1(不改也可)
LXC_NETWORK="10.0.3.0/24"
LXC_DHCP_RANGE="10.0.3.2,10.0.3.254"     # 也修改了ip从3.11开始(不改也可)
LXC_DHCP_MAX="253"                        # ip最多数量(不改也可)

rambo@debian137:~$ sudo systemctl restart lxc-net

```



# 关于安全

```shell
# 强制开启"非特权容器(Unprivileged Containers)"
在全局默认配置或创建参数中强制写入 UID/GID 映射，确保所有新创建的容器均为非特权容器
rambo@debian137:~$ sudo vim /etc/lxc/default.conf          # 增加lxc.idmap的两项
lxc.idmap = u 0 100000 65536
lxc.idmap = g 0 100000 65536
lxc.net.0.type = veth
lxc.net.0.linkname = lxcbr0
lxc.net.0.flags = up


# 网络防火墙策略：防止租户间内网横向攻击
文件路径：/etc/nftables.conf 或你的宿主机初始化脚本
在宿主机上通过 nftables（Debian 13 默认网络过滤框架）隔离各个 veth 接口，禁止容器内互相访问内网，只允许访问网关和外网：
rambo@debian137:~$ sudo vim /etc/nftables.conf
....
	....
table inet lxc_isolation {
    chain forward {
        type filter hook forward priority 0; policy accept;
        # 阻止不同 lxc 容器网段之间的直接通信
        iifname "lxcbr0" oifname "lxcbr0" drop
    }
}


```




# 创建容器
```shell
创建一个 Debian 13 容器：
rambo@debian137:~$ sudo lxc-create \
--name debian01 --template download \
-- \
--dist debian \
--release trixie \
--arch amd64

# 查看镜像
rambo@debian137:~$ sudo lxc-ls
debian01 

# 启动容器
rambo@debian137:~$ sudo lxc-start -n debian01

# 查看传统LXC容器列表
rambo@debian137:~$ sudo lxc-ls -f
NAME     STATE   AUTOSTART GROUPS IPV4       IPV6                                    UNPRIVILEGED 
debian01 RUNNING 0         -      10.0.3.172 fc42:5009:ba4b:5ab0:3808:8aff:fe03:5697 false        

# 查看容器目录
rambo@debian137:~$ sudo ls -lh /var/lib/lxc/
drwxrwx--- 4 root root 4.0K Sep 22 04:19 debian01

# 查看状态
rambo@debian137:~$ sudo lxc-info -n debian01
Name:           debian01
State:          RUNNING
PID:            7645
IP:             10.0.3.172
IP:             fc42:5009:ba4b:5ab0:3808:8aff:fe03:5697
Link:           vethoIu04c
 TX bytes:      2.41 KiB
 RX bytes:      1.99 KiB
 Total bytes:   4.39 KiB


# 进入容器
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- /bin/bash
root@debian01:/# 
apt update && apt install -y ca-certificates curl vim sudo wget curl systemd
echo "root:aaaaaa" | chpasswd
exit

查看容器 IP：
rambo@debian137:~$ sudo lxc-info -n debian01 -iH
10.0.3.172
fc42:5009:ba4b:5ab0:3808:8aff:fe03:5697

或者：
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- ip a sh eth0
2: eth0@if6: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether 3a:08:8a:03:56:97 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.0.3.172/24 metric 1024 brd 10.0.3.255 scope global dynamic eth0
       valid_lft 3360sec preferred_lft 3360sec
    inet6 fc42:5009:ba4b:5ab0:3808:8aff:fe03:5697/64 scope global mngtmpaddr noprefixroute 
       valid_lft forever preferred_lft forever
    inet6 fe80::3808:8aff:fe03:5697/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever



# 启停容器
sudo lxc-{start|stop|restart} -n debian01

# 进入容器
sudo lxc-attach -n debian01 --clear-env -- /bin/bash
注：--clear-env 比直接执行 lxc-attach 更稳妥，因为它可以避免把宿主机的环境变量，尤其是HOME等，错误地带入容器。Debian文档也特别提醒了这一点

# 查看信息
sudo lxc-info -n debian01

# 删除容器
sudo lxc-destroy -n debian01


# 设置容器开机自动启动
rambo@debian137:~$ sudo vim /var/lib/lxc/debian01/config        # 加入
lxc.start.auto = 1 
lxc.start.delay = 5    # 表示该容器启动后，自动启动流程可以等待5秒再继续处理后续容器。它对单个容器没有明显影响

# 测试
rambo@debian137:~$ sudo systemctl restart lxc
rambo@debian137:~$ sudo lxc-info -n debian01
Name:           debian01
State:          RUNNING
PID:            8066
IP:             10.0.3.201
IP:             fc42:5009:ba4b:5ab0:80a0:5bff:fe19:2f30
Link:           vethGQEznc
 TX bytes:      2.21 KiB
 RX bytes:      1.32 KiB
 Total bytes:   3.53 KiB

# 验证
rambo@debian137:~$ sudo lxc-ls -f
NAME     STATE   AUTOSTART GROUPS IPV4       IPV6                                    UNPRIVILEGED 
debian01 RUNNING 1         -      10.0.3.201 fc42:5009:ba4b:5ab0:80a0:5bff:fe19:2f30 fals  
注：AUTOSTART列已经成了1，它表示debian01已经被配置为宿主机启动时自动启动

# 检查LXC自动启动服务
rambo@debian137:~$ systemctl list-unit-files | grep -E '^lxc'

# 查看相关服务
rambo@debian137:~$ sudo systemctl status lxc.service
如服务没有启用：
sudo systemctl enable lxc.service
sudo systemctl start lxc.service
systemctl is-enabled lxc.service



# 固定容器IP
rambo@debian137:~$ sudo lxc-stop -n debian01
rambo@debian137:~$ sudo lxc-info -n debian01
Name:           debian01
State:          STOPPED
rambo@debian137:~$ sudo lxc-autostart -a
rambo@debian137:~$ sudo lxc-ls -f
NAME     STATE   AUTOSTART GROUPS IPV4      IPV6                                    UNPRIVILEGED 
debian01 RUNNING 1         -      10.0.3.15 fc42:5009:ba4b:5ab0:f8cb:4dff:fe78:8a84 false  
注：
现在ip已经变了，如果需要固定下来容器的ip则需要以下步骤
rambo@debian137:~$ sudo lxc-attach -n debian01 -- bash
root@debian01:/# mkdir -p /etc/systemd/network
root@debian01:/# vim /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
Address=10.0.3.20/24
Gateway=10.0.3.1            # 这里的Gateway和DNS是宿机上lxcbr0的IP
DNS=10.0.3.1
DHCP=no

root@debian01:/# systemctl enable systemd-networkd && systemctl restart systemd-networkd

root@debian01:/# ip a sh eth0
2: eth0@if8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether fa:cb:4d:78:8a:84 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.0.3.20/24 brd 10.0.3.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fc42:5009:ba4b:5ab0:f8cb:4dff:fe78:8a84/64 scope global mngtmpaddr noprefixroute 
       valid_lft forever preferred_lft forever
    inet6 fe80::f8cb:4dff:fe78:8a84/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever


root@debian01:/# exit


rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- ip a sh eth0
2: eth0@if8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether fa:cb:4d:78:8a:84 brd ff:ff:ff:ff:ff:ff link-netnsid 0
    inet 10.0.3.20/24 brd 10.0.3.255 scope global eth0
       valid_lft forever preferred_lft forever
    inet6 fc42:5009:ba4b:5ab0:f8cb:4dff:fe78:8a84/64 scope global mngtmpaddr noprefixroute 
       valid_lft forever preferred_lft forever
    inet6 fe80::f8cb:4dff:fe78:8a84/64 scope link proto kernel_ll 
       valid_lft forever preferred_lft forever


# 重启
# rambo@debian137:~$ sudo lxc-stop -n debian01 && sudo lxc-start -n debian01

# 检查
rambo@debian137:~$ sudo lxc-info -n debian01
Name:           debian01
State:          RUNNING
PID:            4800
IP:             10.0.3.20            # 已经改过来了
IP:             fc42:5009:ba4b:5ab0:25:c8ff:feb7:3d66
Link:           vethoxnI4J
 TX bytes:      1.72 KiB
 RX bytes:      686 bytes
 Total bytes:   2.39 KiB






# 在容器内部部署服务
以 Nginx 为例：
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- bash -c '
apt update && DEBIAN_FRONTEND=noninteractive &&
apt install -y nginx &&
systemctl enable nginx && systemctl restart nginx'

查看服务：
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- systemctl status nginx

查看监听端口：
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- netstat -anpt|grep 80
tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      954/nginx: master p 
tcp        0      0 10.0.3.20:49146         151.101.66.132:80       TIME_WAIT   -                   
tcp        0      0 10.0.3.20:46490         151.101.130.132:80      TIME_WAIT   -                   
tcp6       0      0 :::80                   :::*                    LISTEN      954/nginx: master p 

如果容器使用 NAT 网络，宿主机或局域网其他机器通常不能直接通过容器私有 IP 访问。可在宿主机测试：
rambo@debian137:~$ curl -I 10.0.3.20
HTTP/1.1 200 OK
Server: nginx
Date: Sun, 20 Sep 2026 00:36:37 GMT
Content-Type: text/html
Content-Length: 615
Last-Modified: Sun, 20 Sep 2026 00:26:49 GMT
Connection: keep-alive
ETag: "6aaf2849-267"
Accept-Ranges: bytes


# 宿主机目录和容器数据
不要把重要数据只放在容器根文件系统中。可以在宿主机创建独立数据目录：
rambo@debian137:~$ 
sudo mkdir -p /srv/lxc/debian01-data
sudo chown root:root /srv/lxc/debian01-data
sudo chmod 0750 /srv/lxc/debian01-data

rambo@debian137:~$ sudo ls -ldn /srv/lxc/debian01-data
drwxr-x--- 2 0 0 4096 Sep 20 08:42 /srv/lxc/debian01-data
注：0 0就是宿主机上的 root 用户和 root 组

然后在容器配置中加入挂载：
rambo@debian137:~$ sudo vim /var/lib/lxc/debian01/config
lxc.mount.entry = /srv/lxc/debian01-data  mnt/data none bind,create=dir 0 0            # 挂载选项


rambo@debian137:~$ sudo lxc-stop -n debian01 && sudo lxc-start -n debian01

容器重启后，宿主机的/srv/lxc/debian01-data 会对应到容器内的/mnt/data
数据库、上传文件、媒体文件等重要数据建议放在这种独立目录中，方便备份和迁移
rambo@debian137:~$ echo "5555" | sudo tee /srv/lxc/debian01-data/1.txt
5555

# 查看容器内的1.txt
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- cat /mnt/data/1.txt
5555


```





# 2026年实际运营中的风险拦截与风控方案
```shell
# 封锁危险出口端口
在Debian宿主机上通过 nftables 规则直接禁绝所有容器对外发起25端口（防Spam垃圾邮件发信）、22端口（防对外SSH爆破扫描）以及常见的木马端口
黑铲租用容器最常干的三件事：发垃圾邮件 (Spam)、对外 SSH 爆破扫描、参与 DDoS 攻击。我们需要在宿主机网桥（通常为lxcbr0）上拦截容器发出的危险流量
1. 创建并编辑 nftables 防火墙规则
编辑 /etc/nftables.conf，在文件末尾或合适位置添加以下规则（假设LXC虚拟网桥名称为lxcbr0）：
rambo@debian137:~$ sudo vim /etc/nftables.conf
# 保留默认的系统过滤表，方便日后扩展宿主机本机防护
#!/usr/sbin/nft -f

flush ruleset
table inet filter {
	chain input {
		type filter hook input priority filter; 
        policy accept;            # 在最后都另外加了policy accept;
	}
	chain forward {
		type filter hook forward priority filter; 
        policy accept;
	}
	chain output {
		type filter hook output priority filter; 
        policy accept;
	}
}

# LXC 容器专属出口安全拦截表
table inet lxc_security {
	chain forward {
		type filter hook forward priority filter; policy accept;

		# 1. 拦截 SMTP 邮件服务端口 (防发垃圾邮件)
		iifname "lxcbr0" oifname != "lxcbr0" tcp dport { 25, 465, 587 } counter drop

		# 2. 拦截常见出站爆破/扫描端口 (22: SSH, 3389: RDP, 445/139: SMB, 1433/3306: DB)
		iifname "lxcbr0" oifname != "lxcbr0" tcp dport { 22, 135, 139, 445, 1433, 3306, 3389 } counter drop

		# 3. 拦截 NTP 反弹放大攻击端口 (UDP 123)
		iifname "lxcbr0" oifname != "lxcbr0" udp dport 123 counter drop
	}
}

# LXC 容器 NAT 地址伪装表 (补全丢失的NAT功能)
table ip lxc_nat {
	chain postrouting {
		type nat hook postrouting priority srcnat; policy accept;
		# 将从 lxcbr0 出来发往外网的数据包进行源地址伪装 (MASQUERADE)
		ip saddr 10.0.3.0/24 oifname != "lxcbr0" counter masquerade
	}
}


# 加载并设置开机自启
# 检查语法是否正确
rambo@debian137:~$ sudo nft -f /etc/nftables.conf

重启 lxc-net 服务以重新生成 NAT 规则
rambo@debian137:~$ sudo systemctl restart lxc-net
rambo@debian137:~$ sudo nft list ruleset
应该能看到除了 filter 和 lxc_security 表外，还多出了由lxc-net自动创建的nat表（包含 masquerade 规则）

# 启动并设置 nftables 开机自启
rambo@debian137:~$ sudo systemctl enable --now nftables



# 连接数与带宽硬限制
在LXC配置文件中，lxc.net.0.script.up会在容器网卡启动并在宿主机上生成虚拟网卡（通常命名为 vethXXXXXX）后自动调用该脚本
我们可以通过 Linux 系统的 tc (Traffic Control) 工具，对每个容器对应的虚拟网卡限制上传与下载带宽

rambo@debian137:~$ sudo vim /etc/lxc/limit_bandwidth.sh
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




# 少了这一步下面重启容器时会报错
rambo@debian137:~$ sudo chmod +x /etc/lxc/limit_bandwidth.sh


在cgroup v2（Debian 13 默认开启）或LXC config 配置文件中设定流量限制：
rambo@debian137:~$ sudo vim /var/lib/lxc/debian01/config
# 限制网络出入带宽
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.hook.start-host = /etc/lxc/limit_bandwidth.sh       # 当容器网络启动时，自动调用限速脚本
# 限制CPU与内存(Cgroup限制)
lxc.cgroup2.memory.max = 1G
lxc.cgroup2.cpu.max = 100000 200000


# 验证端口封锁
在容器内部尝试连接外网的22/25端口：
# 在容器内部执行，应该会被直接拒绝或超时
rambo@debian137:~$ sudo lxc-attach -n debian01 -- bash
root@debian01:/# apt install netcat-openbsd telnet -y
# 测试 25 (SMTP) 端口
root@debian01:/# nc -zv -w 3 1.1.1.1 25   或  telnet 1.1.1.1 25
nc: connect to 1.1.1.1 port 25 (tcp) timed out: Operation now in progress

# 测试 22(SSH) /3306(MySQL)端口
root@debian01:/# for i in 22 3306;do nc -zv -w 3 1.1.1.1 $i;done
nc: connect to 1.1.1.1 port 22 (tcp) timed out: Operation now in progress
nc: connect to 1.1.1.1 port 3306 (tcp) timed out: Operation now in progress

拦截生效的现象：命令卡住几秒后提示 Connection timed out（超时）


对比验证（未拦截端口）：测试 80 (HTTP) 或 443 (HTTPS) 端口，应提示 open 或 Connected：
root@debian01:/# for i in 80 443;do nc -zv -w 3 1.1.1.1 $i;done
Connection to 1.1.1.1 80 port [tcp/http] succeeded!
Connection to 1.1.1.1 443 port [tcp/https] succeeded!


验证UDP 123 (NTP) 端口
UDP是无连接协议，建议使用 nping 或 nc 测试
root@debian01:/# nc -zuv -w 3 1.1.1.1 123
Connection to 1.1.1.1 123 port [udp/ntp] succeeded!
这里需要注意：
为什么 nc -zuv 会误报成功？
UDP 没有三次握手：
与 TCP 不同，UDP 发送数据包时不需要和服务端建立连接。它把数据包投递出去后，根本不需要等待对方确认。
nc 的判断逻辑：
当你执行 nc -zuv -w 3 1.1.1.1 123 时，nc 只是向 1.1.1.1:123 发送了一个空 UDP 包：
因为你的 nftables 规则是 drop（直接静默丢弃包），宿主机直接把包丢掉，没有任何 ICMP 错误包回传给容器
nc 发出包后，在 3 秒超时时间内没有收到任何拒绝/报错信息（如 ICMP Port Unreachable）
nc 便“盲目”地认为：既然没有收到拒绝消息，那连接就是成功了，于是输出 succeeded!


# 在宿主机实时查看匹配计数（最直观）
如果在容器内发起测试后，对应规则末尾的 packets 和 bytes 计数在增加，说明规则已被准确匹配并执行了 drop
rambo@debian137:~$ sudo nft -a list table inet lxc_security
table inet lxc_security { # handle 27
	chain forward { # handle 1
		type filter hook forward priority filter; policy accept;
		iifname "lxcbr0" oifname != "lxcbr0" tcp dport { 25, 465, 587 } counter packets 0 bytes 0 drop # handle 3
		iifname "lxcbr0" oifname != "lxcbr0" tcp dport { 22, 135, 139, 445, 1433, 3306, 3389 } counter packets 0 bytes 0 drop # handle 5
		iifname "lxcbr0" oifname != "lxcbr0" udp dport 123 counter packets 5 bytes 145 drop # handle 6
	}                                                              # 上一行这里有统计,数值变则代表已经阻止
}



# 清空所有规则（临时生效）
rambo@debian137:~$ sudo nft flush ruleset

# 临时备份当前状态
sudo nft list ruleset > /tmp/nft_backup.nft

# 验证是否清空成功
rambo@debian137:~$ sudo nft list ruleset

恢复所有规则
rambo@debian137:~$ sudo nft -f /etc/nftables.conf




# 验证CPU与内存限制已生效
# 1. 在宿主机安装 lxcfs
rambo@debian137:~$ sudo apt install -y lxcfs

# 2. 确保 lxcfs 服务已运行
rambo@debian137:~$ sudo systemctl enable --now lxcfs
rambo@debian137:~$ sudo systemctl status lxcfs

# 3. 重启容器
rambo@debian137:~$ sudo lxc-stop -n debian01 && sudo lxc-start -n debian01

# 4. 进来容器中查看
rambo@debian137:~$ sudo lxc-attach -n debian01 -- bash
root@debian01:/# free -h
               total        used        free      shared  buff/cache   available
Mem:           1.0Gi        21Mi       1.0Gi        84Ki       697Ki       1.0Gi
Swap:          3.7Gi          0B       3.7Gi





# tc/script带宽控制
1、在宿主机和容器内安装 iperf3
宿主机：
rambo@debian137:~$ sudo apt install -y iperf3              # 选yes
                              ┌───────────────────────────────────┤ Configuring iperf3 ├────────────────────────────────────┐
                              │                                                                                             │ 
                              │ Choose this option if Iperf3 should start automatically as a daemon, now and at boot time.  │ 
                              │                                                                                             │ 
                              │ Start Iperf3 as a daemon automatically?                                                     │ 
                              │                                                                                             │ 
                              │                          <Yes>                             <No>                             │ 
                              │                                                                                             │ 
                              └─────────────────────────────────────────────────────────────────────────────────────────────┘ 
                                                                                                                              


容器debian01内：
root@debian01:/# apt install -y iperf3            # 同样选yes

2、测试容器出站带宽（Egress/上行限制）
在宿主机启动 iperf3 服务端
rambo@debian137:~$ iperf3 -s -p 5202        # 默认端口是5201，现在修改成5202

容器内部连接时指定相同的端口：
root@debian01:/# iperf3 -c 10.0.3.1 -p 5202 -t 10                  # 3.1是debian13宿机的IP
Connecting to host 10.0.3.1, port 5202
[  5] local 10.0.3.20 port 49408 connected to 10.0.3.1 port 5202
[ ID] Interval           Transfer     Bitrate         Retr  Cwnd
[  5]   0.00-1.02   sec  1.19 GBytes  10.0 Gbits/sec    0   2.57 MBytes       
[  5]   1.02-2.00   sec  1.18 GBytes  10.3 Gbits/sec    0   3.99 MBytes       
[  5]   2.00-3.02   sec   689 MBytes  5.68 Gbits/sec    0   3.99 MBytes       
[  5]   3.02-4.00   sec  1.25 GBytes  10.9 Gbits/sec    0   3.99 MBytes       
[  5]   4.00-5.00   sec   872 MBytes  7.32 Gbits/sec    0   3.99 MBytes 

结果观察：查看输出的Bandwidth（带宽数值）。由于tc限制了10Mbps，测出的平均速率会严格被控制在10Mbps 左右，无法突破设定的阈值


测试容器入站带宽（Ingress / 下行限制）
在容器内部增加 -R 参数（反向打流，由宿主机发往容器）：
root@debian01:/# iperf3 -c 10.0.3.1 -t 10 -R
Connecting to host 10.0.3.1, port 5201
Reverse mode, remote host 10.0.3.1 is sending
[  5] local 10.0.3.20 port 49858 connected to 10.0.3.1 port 5201
[ ID] Interval           Transfer     Bitrate
[  5]   0.00-1.00   sec  1.79 GBytes  15.4 Gbits/sec                  
[  5]   1.00-2.00   sec  1.75 GBytes  15.0 Gbits/sec                  
[  5]   2.00-3.00   sec  1.63 GBytes  14.0 Gbits/sec                  
[  5]   3.00-4.00   sec  1.36 GBytes  11.7 Gbits/sec



# 使用 speedtest-cli 测试公网真实速率
如果容器有外网连接权限，可以直接测公网上下行速率：
在容器内部安装并运行 speedtest-cli：
root@debian01:/# apt install -y speedtest-cli
root@debian01:/# speedtest-cli
结果观察：比较输出中的 Download（下载）和 Upload（上传）速率，验证是否与你的 limit_bandwidth.sh 脚本中的限速参数一致
Retrieving speedtest.net configuration...
Retrieving speedtest.net server list...
Selecting best server based on ping...
Hosted by Chief Telecom (New Taipei) [802.14 km]: 77.331 ms
Testing download speed.............................                # 上传和下载都被限制在10M内，因为我们定义的就是不超10M
Download: 5.43 Mbit/s
Testing upload speed...............................
Upload: 4.67 Mbit/s


```









# 安装/配置web端控制容器
```shell
# debian13需要安装incus
rambo@debian137:~$ sudo apt install -y incus
rambo@debian137:~$ sudo incus admin init --auto       # 初始化incus

如果使用普通用户而不是每次都加 sudo：
rambo@debian137:~$ sudo usermod -aG incus-admin "$USER"

检查incus：
rambo@debian137:~$ sudo incus list
+------+-------+------+------+------+-----------+
| NAME | STATE | IPV4 | IPV6 | TYPE | SNAPSHOTS |
+------+-------+------+------+------+-----------+
rambo@debian137:~$ sudo incus storage list
+---------+--------+-------------+---------+---------+
|  NAME   | DRIVER | DESCRIPTION | USED BY |  STATE  |
+---------+--------+-------------+---------+---------+
| default | dir    |             | 1       | CREATED |
+---------+--------+-------------+---------+---------+
rambo@debian137:~$ sudo incus network list
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+
|   NAME   |   TYPE   | MANAGED |      IPV4       |           IPV6            | DESCRIPTION | USED BY |  STATE  |
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+
| ens33    | physical | NO      |                 |                           |             | 0       |         |
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+
| incusbr0 | bridge   | YES     | 10.229.250.1/24 | fd42:b59f:f393:4f6d::1/64 |             | 1       | CREATED |
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+
| lo       | loopback | NO      |                 |                           |             | 0       |         |
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+
| lxcbr0   | bridge   | NO      |                 |                           |             | 0       |         |
+----------+----------+---------+-----------------+---------------------------+-------------+---------+---------+


因为传统 LXC 和 Incus 使用不同的管理数据库。现有容器仍然可以通过以下命令查看：
rambo@debian137:~$ sudo lxc-ls -f
NAME     STATE   AUTOSTART GROUPS IPV4      IPV6                                   UNPRIVILEGED 
debian01 RUNNING 1         -      10.0.3.20 fc42:5009:ba4b:5ab0:e8cc:aff:fe27:7757 false       





生成容器并绑定Web终端
最后在宿机终端里运行调用脚本创建容器
rambo@debian137:~$ sudo vim /usr/local/bin/create_lxd.sh
#!/usr/bin/env bash
set -e

TENANT_NAME="$1"
OS_TYPE="$2"
TENANT_ID="$3"
MEM_LIMIT="${4:-1GiB}"
DISK_LIMIT="${5:-10GiB}"

SSH_USER="admin"

if [ -z "${TENANT_NAME}" ] || [ -z "${TENANT_ID}" ]; then
    echo "用法: $0 <自定义容器名> <操作系统> <租户ID> [内存限制] [磁盘限制]"
    exit 1
fi

# 容器名称完全支持自定义（只做基础的安全正则校验）
if [[ ! "${TENANT_NAME}" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "错误: 容器名称包含非法字符: ${TENANT_NAME}"
    exit 1
fi

# 镜像映射
case "${OS_TYPE}" in
    alpine*|Alpine*)
        IMAGE="images:alpine/3.24"
        ;;
    ubuntu24*|ub24)
        IMAGE="images:ubuntu/24.04"
        ;;
    ubuntu*|ubuntu22)
        IMAGE="images:ubuntu/22.04"
        ;;
    debian*|debian12)
        IMAGE="images:debian/12"
        ;;
    centos*|centos9)
        IMAGE="images:centos/9-Stream"
        ;;
    rocky*|rocky9)
        IMAGE="images:rockylinux/9"
        ;;
    alma*|almalinux*)
        IMAGE="images:almalinux/9"
        ;;
    *)
        IMAGE="images:ubuntu/22.04"
        ;;
esac

echo "==> 正在创建容器 ${TENANT_NAME} (镜像: ${IMAGE})..."
incus launch "${IMAGE}" "${TENANT_NAME}"

# 3. 配置资源限制
incus config set "${TENANT_NAME}" limits.memory "${MEM_LIMIT}"
incus config device override "${TENANT_NAME}" root size="${DISK_LIMIT}" 2>/dev/null || \
incus config device add "${TENANT_NAME}" root disk path=/ pool=default size="${DISK_LIMIT}"

# 4. 生成安全随机密码（剔除容易引起歧义的特殊符号）
ROOT_PASS=$(tr -dc 'A-Za-z0-9!@#*-_+=' < /dev/urandom | head -c 16)

# 5. 循环等待容器网络和 DNS 彻底就绪
echo "==> 等待容器网络初始化..."
for i in {1..15}; do
    if incus exec "${TENANT_NAME}" -- ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# 6. 各发行版统一配置 SSH、密码与管理用户
if [[ "${IMAGE}" =~ alpine ]]; then
    echo "==> 配置 Alpine 容器 SSH 与管理用户..."
    incus exec "${TENANT_NAME}" -- sh -c "apk update && apk add openssh sudo bash && ssh-keygen -A"
    incus exec "${TENANT_NAME}" -- sh -c "sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config"
    incus exec "${TENANT_NAME}" -- sh -c "sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config"
    incus exec "${TENANT_NAME}" -- sh -c "/usr/sbin/sshd"
    SSH_USER="root"
    # 创建管理用户
    #incus exec "${TENANT_NAME}" -- adduser -D -s /bin/bash "${SSH_USER}" 2>/dev/null || true
    #printf '%s:%s' "${SSH_USER}" "${ROOT_PASS}" | incus exec "${TENANT_NAME}" -- chpasswd
    #incus exec "${TENANT_NAME}" -- sh -c "echo '${SSH_USER} ALL=(ALL:ALL) NOPASSWD:ALL' > /etc/sudoers.d/${SSH_USER}"
    
    #incus exec "${TENANT_NAME}" -- sh -c "/usr/sbin/sshd"

elif [[ "${IMAGE}" =~ centos|rocky|almalinux|centos7 ]]; then
    echo "==> 配置 RedHat 系容器 SSH 与管理用户..."
    incus exec "${TENANT_NAME}" -- bash -c "dnf install -y openssh-server sudo || yum install -y openssh-server sudo"
    incus exec "${TENANT_NAME}" -- bash -c "ssh-keygen -A"
    incus exec "${TENANT_NAME}" -- bash -c "sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config"
    incus exec "${TENANT_NAME}" -- bash -c "sed -i 's/#PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config; sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/g' /etc/ssh/sshd_config"
    incus exec "${TENANT_NAME}" -- bash -c "systemctl enable --now sshd || /usr/sbin/sshd"
    SSH_USER="root"
    # 创建管理用户
    #incus exec "${TENANT_NAME}" -- useradd -m -s /bin/bash "${SSH_USER}" 2>/dev/null || true
    #printf '%s:%s' "${SSH_USER}" "${ROOT_PASS}" | incus exec "${TENANT_NAME}" -- chpasswd
    #incus exec "${TENANT_NAME}" -- usermod -aG wheel "${SSH_USER}"
    #incus exec "${TENANT_NAME}" -- bash -c "echo '${SSH_USER} ALL=(ALL:ALL) NOPASSWD:ALL' > /etc/sudoers.d/${SSH_USER}"
    #incus exec "${TENANT_NAME}" -- bash -c "systemctl enable --now sshd || /usr/sbin/sshd"

elif [[ "${IMAGE}" =~ debian|ubuntu ]]; then
    echo "==> 配置 Debian/Ubuntu 系容器 SSH、密码与管理用户..."
    incus exec "${TENANT_NAME}" -- bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -o Acquire::Check-Valid-Until=false && \
        apt-get install -y openssh-server sudo && \
        mkdir -p /etc/ssh/sshd_config.d && \
        echo -e 'PermitRootLogin yes\nPasswordAuthentication yes\nKbdInteractiveAuthentication yes' > /etc/ssh/sshd_config.d/99-custom-auth.conf && \
        systemctl enable --now ssh || /usr/sbin/sshd"
        
    # 创建管理用户
    incus exec "${TENANT_NAME}" -- useradd -m -s /bin/bash "${SSH_USER}" 2>/dev/null || true
    printf '%s:%s' "${SSH_USER}" "${ROOT_PASS}" | incus exec "${TENANT_NAME}" -- chpasswd
    incus exec "${TENANT_NAME}" -- usermod -aG sudo "${SSH_USER}"
    incus exec "${TENANT_NAME}" -- bash -c "echo 'admin ALL=(ALL:ALL) NOPASSWD:ALL' > /etc/sudoers.d/admin"
    SSH_USER="admin"
else
    echo "暂不支持该 Linux 系统..."
    exit 1
fi

# 同步设置 root 密码（双保险，如果用户需要 su 的话）
printf 'root:%s' "${ROOT_PASS}" | incus exec "${TENANT_NAME}" -- chpasswd

# 7. 获取容器分配到的真实 IP 地址
CONTAINER_IP=$(incus list "${TENANT_NAME}" -c 4 --format csv | awk '{print $1}')
if [ -z "${CONTAINER_IP}" ]; then
    CONTAINER_IP=$(incus exec "${TENANT_NAME}" -- hostname -I | awk '{print $1}')
fi

# 8. 智能端口探测
SSH_HOST_PORT=$((20000 + TENANT_ID))
while ss -Htlun | grep -qE ":${SSH_HOST_PORT}\b"; do
    SSH_HOST_PORT=$((SSH_HOST_PORT + 1))
done

# 9. 绑定 Proxy 到宿主机
incus config device add "${TENANT_NAME}" ssh-port proxy listen=tcp:0.0.0.0:${SSH_HOST_PORT} connect=tcp:${CONTAINER_IP}:22 2>/dev/null || true

# 关键输出：明确告知用户登录账号、密码、端口以及连接命令
echo "=========================================="
echo "容器创建成功!"
echo "容器名称 : ${TENANT_NAME}"
echo "登录用户 : ${SSH_USER}"
echo "登录密码 : ${ROOT_PASS}"
echo "SSH 端口 : ${SSH_HOST_PORT}"
echo "连接命令 : ssh ${SSH_USER}@<宿主机IP> -p ${SSH_HOST_PORT}"
echo "=========================================="




rambo@debian137:~$ sudo chmod +x /usr/local/bin/create_lxd.sh





rambo@debian137:~$ sudo vim /etc/lxc/destroy_and_rebuild.sh
#!/bin/bash
# ==============================================================================
# 脚本名称: destroy_and_rebuild.sh
# 功能描述: 安全销毁指定 LXC 容器并基于母本模板瞬间重建恢复
# 使用方法: sudo ./destroy_and_rebuild.sh <目标容器名> [模板容器名]
# ==============================================================================

# 严谨模式：遇到未定义变量报错并退出，管线失败则整体失败
set -euo pipefail

# 1. 参数检查与默认值设置
TARGET_CONTAINER="${1:-}"
TEMPLATE_CONTAINER="${2:-tpl-debian13}"

if [ -z "$TARGET_CONTAINER" ]; then
    echo -e "\033[31m[ERROR] 错误：必须指定要重建的目标容器名称！\033[0m"
    echo -e "用法: $0 <目标容器名> [模板容器名]"
    echo -e "示例: $0 debian01 tpl-debian13"
    exit 1
fi

# 检查是否以 root / sudo 权限运行
if [ "$(id -u)" -ne 0 ]; then
    echo -e "\033[31m[ERROR] 错误：该脚本必须使用 root 或 sudo 权限执行！\033[0m"
    exit 1
fi

echo -e "\033[32m[1/5] 检查母本模板是否存在...\033[0m"
if ! lxc-info -n "$TEMPLATE_CONTAINER" >/dev/null 2>&1; then
    echo -e "\033[31m[ERROR] 错误：母本模板容器 '$TEMPLATE_CONTAINER' 不存在，请先创建！\033[0m"
    exit 1
fi

# 确认模板容器已停止（防止模板被占用或误修改）
TEMPLATE_STATE=$(lxc-info -n "$TEMPLATE_CONTAINER" -s 2>/dev/null | awk '{print $2}')
if [ "$TEMPLATE_STATE" != "STOPPED" ]; then
    echo -e "\033[33m[WARN] 警告：模板容器 '$TEMPLATE_CONTAINER' 正在运行，强行停止模板...\033[0m"
    lxc-stop -n "$TEMPLATE_CONTAINER" -k || true
fi

# 2. 销毁旧容器流程
echo -e "\033[32m[2/5] 检查并销毁旧容器 '$TARGET_CONTAINER'...\033[0m"
if lxc-info -n "$TARGET_CONTAINER" >/dev/null 2>&1; then
    # 获取旧容器当前状态
    CURRENT_STATE=$(lxc-info -n "$TARGET_CONTAINER" -s 2>/dev/null | awk '{print $2}')
    if [ "$CURRENT_STATE" = "RUNNING" ]; then
        echo " -> 正在强行停止运行中的容器 '$TARGET_CONTAINER'..."
        lxc-stop -n "$TARGET_CONTAINER" -k
    fi
    
    echo " -> 正在彻底删除旧容器及关联文件..."
    lxc-destroy -n "$TARGET_CONTAINER" -f
    echo " -> 旧容器销毁成功。"
else
    echo " -> 目标容器 '$TARGET_CONTAINER' 当前不存在，跳过销毁步骤。"
fi

# 3. 从模板克隆重建容器
echo -e "\033[32m[3/5] 从模板 '$TEMPLATE_CONTAINER' 克隆全新容器 '$TARGET_CONTAINER'...\033[0m"
# 使用 lxc-copy 进行快照/深拷贝
lxc-copy -n "$TEMPLATE_CONTAINER" -N "$TARGET_CONTAINER"

# 4. 启动新容器
echo -e "\033[32m[4/5] 启动全新容器 '$TARGET_CONTAINER'...\033[0m"
lxc-start -n "$TARGET_CONTAINER"

# 5. 验证是否启动成功与网络初始化
echo -e "\033[32m[5/5] 验证重建状态...\033[0m"
# 循环等待最多 10 秒，验证容器状态变为 RUNNING 且获取到 IP
RETRY=0
MAX_RETRY=10
SUCCESS=false

while [ $RETRY -lt $MAX_RETRY ]; do
    STATE=$(lxc-info -n "$TARGET_CONTAINER" -s 2>/dev/null | awk '{print $2}')
    IP_ADDR=$(lxc-info -n "$TARGET_CONTAINER" -i 2>/dev/null | awk '{print $2}' | head -n 1)
    
    if [ "$STATE" = "RUNNING" ] && [ -n "$IP_ADDR" ]; then
        SUCCESS=true
        break
    fi
    sleep 1
    RETRY=$((RETRY + 1))
done

if [ "$SUCCESS" = true ]; then
    echo -e "\033[32m==================================================\033[0m"
    echo -e "\033[32m[✓] 容器 '$TARGET_CONTAINER' 重建成功！\033[0m"
    echo -e "    - 当前状态: $STATE"
    echo -e "    - 分配 IP  : $IP_ADDR"
    echo -e "\033[32m==================================================\033[0m"
    exit 0
else
    echo -e "\033[31m[ERROR] 警告：容器已启动，但超时未获取到 IP 地址，请检查 lxc-net 服务！\033[0m"
    exit 1
fi



rambo@debian137:~$ sudo chmod +x /etc/lxc/destroy_and_rebuild.sh


# 验证步骤
# 先停止目标容器
rambo@debian137:~$ sudo lxc-stop -n debian01 -k 2>/dev/null

# 复制出一个专门的母本模板容器 (tpl-debian13)
rambo@debian137:~$ sudo lxc-copy -n debian01 -N tpl-debian13

# 确认 tpl-debian13 存在且处于 STOPPED 状态
rambo@debian137:~$ sudo lxc-info -n tpl-debian13
Name:           tpl-debian13
State:          STOPPED

# 运行重建脚本
rambo@debian137:~$ sudo /etc/lxc/destroy_and_rebuild.sh debian01  tpl-debian13
[1/5] 检查母本模板是否存在...
[2/5] 检查并销毁旧容器 'debian01'...
 -> 正在彻底删除旧容器及关联文件...
 -> 旧容器销毁成功。
[3/5] 从模板 'tpl-debian13' 克隆全新容器 'debian01'...
[4/5] 启动全新容器 'debian01'...
[5/5] 验证重建状态...
==================================================
[✓] 容器 'debian01' 重建成功！
    - 当前状态: RUNNING
    - 分配 IP  : fc42:5009:ba4b:5ab0:a4e4:75ff:fe66:19ae
==================================================



# 验证步骤是否成功的关键指令
# 检查 lxc.net.0.script.up 带宽限制脚本和配置依然完好保留在配置文件中
rambo@debian137:~$ sudo grep "lxc.hook.start-host" /var/lib/lxc/debian01/config
lxc.hook.start-host = /etc/lxc/limit_bandwidth.sh

# 检查容器进程
rambo@debian137:~$ sudo lxc-info -n debian01
Name:           debian01
State:          RUNNING
PID:            18505
IP:             10.0.3.20
IP:             fc42:5009:ba4b:5ab0:a4e4:75ff:fe66:19ae
Link:           vethK2dNMg
 TX bytes:      2.07 KiB
 RX bytes:      930 bytes
 Total bytes:   2.98 KiB


```







# 自定义web端
```shell
整体架构采用 Flask (后端) + Single File HTML/Bootstrap5 (前端)，占用内存仅约 20MB。它通过受限的 sudo 权限调用你写好的 /etc/lxc/destroy_and_rebuild.sh 脚本，实现了身份鉴权、状态监控、电源控制、密码重置以及带二次确认的系统重置功能


一、 宿主机权限与环境准备
为了确保 Web 后端（用低权限用户运行）能够安全执行系统级别的 LXC 管理命令，且不泄露宿主机的 root 完整权限，我们需要配置精准的 sudoers 提权规则。

1. 创建专用低权限运行用户
在宿主机运行：
rambo@debian137:~$ sudo useradd -m -s /bin/bash lxcweb

2. 配置 /etc/sudoers.d/lxcweb 提权规则
rambo@debian137:~$ sudo vim /etc/sudoers.d/lxcweb
# 允许 lxcweb 用户免密以 root 身份执行 Incus 和管理脚本
lxcweb ALL=(ALL) NOPASSWD: /usr/bin/incus, /usr/local/bin/create_lxd.sh, /usr/local/bin/limit_bandwidth.sh

rambo@debian137:~$ sudo vim /etc/sudoers.d/incus
rambo ALL=(ALL) NOPASSWD: /usr/bin/incus

rambo@debian137:~$ sudo chmod 0440 /etc/sudoers.d/{lxcweb,incus}

3. 安装后端依赖 
rambo@debian137:~$ sudo apt update && sudo apt install -y python3-flask python3-flask-login python3-waitress gunicorn python3-gunicorn




二、 后端核心代码 (/home/lxcweb/app.py)
在宿主机创建文件 /home/lxcweb/app.py，写入以下代码：
rambo@debian137:~$ sudo vim /home/lxcweb/app.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = 'super_secret_lxd_key_change_me'
DB_FILE = 'users.db'

# 系统代号与显示名称的映射关系
OS_NAME_MAP = {
    "ub24": "Ubuntu 24.04",
    "alpine": "Alpine 3.24",
    "debian13": "Debian 13",
    "centos9": "CentOS Stream 9",
    "rocky9": "Rocky Linux 9"
}

def get_display_os(os_code):
    return OS_NAME_MAP.get(os_code, os_code)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        tenant_id INTEGER UNIQUE
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS container_records (
        container_name TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        tenant_id INTEGER NOT NULL,
        root_pass TEXT NOT NULL DEFAULT '123456',
        os_type TEXT NOT NULL DEFAULT 'Linux',
        ssh_port INTEGER
    )
    ''')
    try:
        cursor.execute("ALTER TABLE container_records ADD COLUMN os_type TEXT NOT NULL DEFAULT 'Linux'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE container_records ADD COLUMN ssh_port INTEGER")
    except Exception:
        pass

    default_users = [
        ('admin', 'AdminPass123', 'admin', 1),
        ('zhangsan', 'Zhang123456', 'user', 10),
        ('lisi', 'Lisi123456', 'user', 11)
    ]
    for u, p, r, tid in default_users:
        cursor.execute("SELECT id FROM users WHERE username = ?", (u,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (username, password, role, tenant_id) VALUES (?, ?, ?, ?)",
                (u, p, r, tid)
            )
    conn.commit()
    conn.close()

init_db()

def get_next_available_tenant_id():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(tenant_id) FROM users")
    max_id = cursor.fetchone()[0]
    conn.close()
    return (max_id + 1) if (max_id and max_id >= 10) else 10

def get_next_ssh_port():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(ssh_port) FROM container_records")
    row = cursor.fetchone()
    conn.close()
    max_port = row[0] if (row and row[0] and row[0] >= 2302) else 2301
    return max_port + 1

def get_db_user(username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, role, tenant_id FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "password": row[1], "role": row[2], "tenant_id": row[3]}
    return None

def get_all_users_detail():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, role, tenant_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "password": r[2], "role": r[3], "tenant_id": r[4]} for r in rows]

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_host_ip():
    try:
        cmd = "hostname -I | awk '{print $1}'"
        host_ip = subprocess.check_output(cmd, shell=True, text=True).strip()
        return host_ip if host_ip else "172.16.186.141"
    except Exception:
        return "172.16.186.141"

def get_incus_bin():
    for path in ["/usr/bin/incus", "/usr/sbin/incus", "/usr/local/bin/incus", "/snap/bin/incus"]:
        if os.path.exists(path):
            return path
    incus_path = shutil.which("incus")
    if incus_path:
        return incus_path
    return "incus"

def run_incus(args, check=True, timeout=10):
    bin_path = get_incus_bin()
    try:
        res = subprocess.run([bin_path] + args, capture_output=True, text=True, check=check, timeout=timeout)
        if res.returncode == 0:
            return res
    except Exception:
        pass
    return subprocess.run(["sudo", bin_path] + args, capture_output=True, text=True, check=check, timeout=timeout)

def get_db_container_records():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT container_name, owner, tenant_id, root_pass, os_type, ssh_port FROM container_records")
    rows = cursor.fetchall()
    conn.close()
    res = {}
    for r in rows:
        port = r[5] if r[5] else (2302 + r[0].__hash__() % 100)
        res[r[0]] = {"owner": r[1], "tenant_id": r[2], "root_pass": r[3], "os_type": r[4], "ssh_port": port}
    return res

def get_user_incus_containers(current_user):
    containers_list = []
    host_ip = get_host_ip()
    db_records = get_db_container_records()
    
    user_db_records = {}
    for c_name, info in db_records.items():
        if current_user == "admin" or info["owner"] == current_user:
            user_db_records[c_name] = info
            
    if not user_db_records:
        return []

    incus_data_map = {}
    try:
        res = run_incus(["list", "--format", "json"], check=False, timeout=5)
        if res and res.stdout and res.stdout.strip().startswith("["):
            items = json.loads(res.stdout)
            for item in items:
                incus_data_map[item.get("name")] = item
    except Exception:
        pass

    for c_name, info in user_db_records.items():
        owner = info["owner"]
        tenant_id = str(info["tenant_id"])
        root_pass = info["root_pass"]
        db_os_type = info["os_type"]
        ssh_port = str(info["ssh_port"])
        
        ssh_user = "admin" if db_os_type in ["ub24", "debian13"] else "root"
        
        item = incus_data_map.get(c_name, {})
        raw_status = item.get("status", "Stopped")
        status = "运行中" if raw_status.lower() == "running" else "已停止"

        state = item.get("state") or {}
        ip_addr = "未分配IP"
        networks = state.get("network") or {}
        if isinstance(networks, dict):
            for iface, details in networks.items():
                if iface == "lo" or not details:
                    continue
                for addr in details.get("addresses", []):
                    if addr.get("family") == "inet" and addr.get("scope") == "global":
                        ip_addr = addr.get("address")
                        break
                if ip_addr != "未分配IP":
                    break
            
        containers_list.append({
            "tenant_name": c_name,
            "os_type": get_display_os(db_os_type),
            "tenant_id": tenant_id,
            "container_ip": ip_addr,
            "ssh_port": ssh_port,
            "root_pass": root_pass,
            "ssh_user": ssh_user,
            "host_ip": host_ip,
            "owner": owner,
            "status": status
        })
        
    return containers_list

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>登录容器控制台</title>
<style>
body { font-family: Arial, sans-serif; background: #f4f6f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
.login-card { background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); width: 320px; }
h3 { text-align: center; margin-bottom: 20px; color: #333; }
.form-group { margin-bottom: 15px; }
label { display: block; margin-bottom: 5px; font-weight: bold; }
input { width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }
button { width: 100%; padding: 10px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-top: 10px; }
button:hover { background-color: #0056b3; }
.alert { color: red; font-size: 14px; margin-bottom: 10px; text-align: center; }
</style>
</head>
<body>
<div class="login-card">
<h3>🔒 平台登录</h3>
{% with messages = get_flashed_messages() %}
{% if messages %}
{% for message in messages %}
<div class="alert">{{ message }}</div>
{% endfor %}
{% endif %}
{% endwith %}
<form action="/login" method="post">
<div class="form-group">
<label>用户名</label>
<input type="text" name="username" placeholder="请输入用户名" required>
</div>
<div class="form-group">
<label>密码</label>
<input type="password" name="password" placeholder="请输入密码" required>
</div>
<button type="submit">登录系统</button>
</form>
</div>
</body>
</html>
"""

INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>容器自动化创建平台</title>
<style>
body { font-family: Arial, sans-serif; margin: 30px; background-color: #f4f6f9; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.container { background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 20px; }
.create-form { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; max-width: 650px; margin-top: 15px; }
label { font-weight: bold; margin-bottom: 5px; display: block; }
input, select { width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; height: 38px; }
input[readonly] { background-color: #e9ecef; cursor: not-allowed; color: #495057; font-weight: bold; }
.full-width { grid-column: span 2; }
button { background-color: #007bff; color: white; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-size: 14px; }
button:hover { background-color: #0056b3; }
.add-user-grid { display: grid; grid-template-columns: 1fr 1.2fr 110px 110px; gap: 15px; align-items: end; max-width: 780px; margin-top: 15px; }
.btn-gen { background-color: #17a2b8; border: none; color: white; border-radius: 4px; cursor: pointer; font-size: 13px; height: 38px; width: 100%; white-space: nowrap; }
.btn-add { background-color: #28a745; border: none; color: white; border-radius: 4px; cursor: pointer; font-size: 14px; height: 38px; width: 100%; font-weight: bold; white-space: nowrap; }
.btn-logout { background-color: #dc3545; padding: 6px 12px; font-size: 14px; text-decoration: none; color: white; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
table, th, td { border: 1px solid #ddd; }
th, td { padding: 10px; text-align: left; }
th { background-color: #f8f9fa; }
.flash { padding: 10px; background-color: #d4edda; color: #155724; border-radius: 4px; margin-bottom: 15px; }
.badge-admin { background: #dc3545; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.badge-user { background: #007bff; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.pass-tag { background: #e0f2fe; color: #0369a1; padding: 3px 8px; border-radius: 4px; font-family: monospace; font-weight: bold; }
details summary { cursor: pointer; outline: none; font-weight: bold; font-size: 16px; user-select: none; }
details summary:hover { color: #0056b3; }
.action-bar { margin-top: 15px; display: flex; gap: 10px; align-items: center; }
.btn-restart { background-color: #ffc107; color: #212529; font-weight: bold; }
.btn-stop { background-color: #fd7e14; color: white; font-weight: bold; }
.btn-delete { background-color: #dc3545; color: white; font-weight: bold; }
.status-running { color: #28a745; font-weight: bold; }
.status-stopped { color: #6c757d; font-weight: bold; }

.dropdown { position: relative; display: inline-block; }
.dropbtn { background-color: #6c757d; color: white; padding: 5px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
.dropdown-content { display: none; position: absolute; right: 0; background-color: #ffffff; min-width: 160px; box-shadow: 0px 8px 16px 0px rgba(0,0,0,0.2); z-index: 100; border-radius: 4px; overflow: hidden; }
.dropdown-content form, .dropdown-content a { display: block; }
.dropdown-content button, .dropdown-content a { color: black; padding: 8px 12px; text-decoration: none; display: block; text-align: left; width: 100%; background: none; border: none; font-size: 13px; box-sizing: border-box; cursor: pointer; }
.dropdown-content button:hover, .dropdown-content a:hover { background-color: #f1f1f1; }
.dropdown:hover .dropdown-content { display: block; }

.modal { display: none; position: fixed; z-index: 200; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5); }
.modal-content { background-color: #fff; margin: 10% auto; padding: 20px; border-radius: 8px; width: 450px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
.close-btn { color: #aaa; float: right; font-size: 24px; font-weight: bold; cursor: pointer; }
.close-btn:hover { color: #000; }
</style>
<script>
function generatePassword() {
    const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*";
    let pass = "";
    for (let i = 0; i < 12; i++) {
        pass += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    document.getElementById("new_password").value = pass;
}
function updateTenantIdByOwner(selectObj) {
    const selectedOption = selectObj.options[selectObj.selectedIndex];
    const tenantId = selectedOption.getAttribute('data-tenant-id');
    const tenantInput = document.getElementById('tenant_id_input');
    if (tenantInput && tenantId) {
        tenantInput.value = tenantId;
    }
}
function toggleSelectAll(source) {
    checkboxes = document.getElementsByName('selected_containers');
    for(var i=0, n=checkboxes.length; i<n; i++) {
        checkboxes[i].checked = source.checked;
    }
}
function confirmContainerAction(actionName) {
    const checkboxes = document.querySelectorAll('input[name="selected_containers"]:checked');
    if (checkboxes.length === 0) {
        alert("请先勾选需要操作的容器!");
        return false;
    }
    if (actionName === 'delete') {
        return confirm("警告: 确定要物理删除选中的 " + checkboxes.length + " 个容器吗? 数据将不可恢复!");
    }
    return confirm("确定要对选中的 " + checkboxes.length + " 个容器执行 [" + actionName + "] 操作吗?");
}
function openMountModal(cName) {
    document.getElementById('mount_cname').value = cName;
    document.getElementById('mountModal').style.display = 'block';
}
function closeMountModal() {
    document.getElementById('mountModal').style.display = 'none';
}
function openReinstallModal(cName) {
    document.getElementById('reinstall_cname').value = cName;
    document.getElementById('reinstallModal').style.display = 'block';
}
function closeReinstallModal() {
    document.getElementById('reinstallModal').style.display = 'none';
}
</script>
</head>
<body>
<div class="header">
<h2>容器控制台</h2>
<div>
当前用户: <b>{{ session['user'] }}</b>
{% if session['user'] == 'admin' %}
<span class="badge-admin">超级管理员</span>
{% else %}
<span class="badge-user">租户账号</span>
{% endif %}
| <a href="/logout" class="btn-logout">退出登录</a>
</div>
</div>
{% with messages = get_flashed_messages() %}
{% if messages %}
{% for message in messages %}
<div class="flash">{{ message }}</div>
{% endfor %}
{% endif %}
{% endwith %}

{% if session['user'] == 'admin' %}
<div class="container" style="border-left: 4px solid #dc3545; background-color: #fff;">
<details>
<summary style="color: #dc3545;">管理员工具: 在线添加新租户 (点击展开/隐藏)</summary>
<form action="/add_user" method="post" class="add-user-grid">
<div>
<label>新租户用户名:</label>
<input type="text" name="new_username" placeholder="例如: wangwu" required>
</div>
<div>
<label>新租户密码:</label>
<input type="text" id="new_password" name="new_password" placeholder="请输入或一键生成" required>
</div>
<div>
<button type="button" class="btn-gen" onclick="generatePassword()">生成密码</button>
</div>
<div>
<button type="submit" class="btn-add">添加账号</button>
</div>
</form>
</details>
</div>

<div class="container" style="border-left: 4px solid #17a2b8; background-color: #fff;">
<details>
<summary style="color: #17a2b8;">租户账号及登录密码汇总列表 (点击展开/隐藏)</summary>
<div style="margin-top: 15px;">
<table>
<thead>
<tr>
<th>ID</th>
<th>用户名</th>
<th>系统密码(已持久化)</th>
<th>角色类型</th>
<th>固定租户 ID</th>
</tr>
</thead>
<tbody>
{% for u in all_users_info %}
<tr>
<td>{{ u.id }}</td>
<td><b>{{ u.username }}</b></td>
<td><span class="pass-tag">{{ u.password }}</span></td>
<td>
{% if u.role == 'admin' %}
<span class="badge-admin">管理员</span>
{% else %}
<span class="badge-user">普通租户</span>
{% endif %}
</td>
<td><b>{{ u.tenant_id }}</b></td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</details>
</div>
{% endif %}

<div class="container" style="border-left: 4px solid #007bff;">
<details>
<summary style="color: #007bff;">➕ 创建新容器 (点击展开/隐藏表单)</summary>
<form action="/create" method="post" class="create-form">
{% if session['user'] == 'admin' %}
<div class="full-width" style="background: #fff3cd; padding: 12px; border-radius: 4px; border: 1px solid #ffeeba;">
<label style="color: #856404; margin-bottom: 6px;">👑 容器归属账号 (管理员专属设置):</label>
<select name="assign_owner" onchange="updateTenantIdByOwner(this)" style="font-weight: bold; border-color: #ffeeba; background-color: #fff;">
{% for u in all_users_info %}
<option value="{{ u.username }}" data-tenant-id="{{ u.tenant_id }}" {% if u.username == session['user'] %}selected{% endif %}>
{% if u.role == 'admin' %}管理员: {{ u.username }}{% else %}租户帐号: {{ u.username }}{% endif %} (ID: {{ u.tenant_id }})
</option>
{% endfor %}
</select>
</div>
{% endif %}
<div>
<label>容器名称 (TENANT_NAME):</label>
<input type="text" name="tenant_name" placeholder="例如: my-node-01" required>
</div>
<div>
<label>系统镜像 (OS_TYPE):</label>
<select name="os_type">
<option value="ub24">Ubuntu 24.04</option>
<option value="alpine">Alpine 3.24</option>
<option value="debian13">Debian 13</option>
<option value="centos9">CentOS Stream 9</option>
<option value="rocky9">Rocky Linux 9</option>
</select>
</div>
<div>
<label>租户 ID (系统自动锁定匹配):</label>
<input type="number" id="tenant_id_input" name="tenant_id" value="{{ current_tenant_id }}" readonly required>
</div>
<div>
<label>内存限制 (MEM_LIMIT):</label>
<input type="text" name="mem_limit" value="512MB" required>
</div>
<div>
<label>磁盘限制 (DISK_LIMIT):</label>
<input type="text" name="disk_limit" value="5GB" required>
</div>
<div class="full-width">
<button type="submit" style="padding: 10px 15px; font-size: 16px;">立即创建容器</button>
</div>
</form>
</details>
</div>

<div class="container">
<h3 style="margin-top: 0;">已创建容器列表 {% if session['user'] == 'admin' %}(全局监控模式){% else %}(名下容器面板){% endif %}</h3>
<form action="/containers/action" method="post">
<table>
<thead>
<tr>
<th style="width: 40px; text-align: center;">
<input type="checkbox" onclick="toggleSelectAll(this)" title="全选 / 取消全选">
</th>
<th>容器名称</th>
<th>状态</th>
<th>所有者</th>
<th>系统</th>
<th>租户ID</th>
<th>真实容器 IP</th>
<th>SSH 端口</th>
<th>Root 密码</th>
<th>SSH 连接命令</th>
<th style="text-align: center; width: 90px;">高级操作</th>
</tr>
</thead>
<tbody>
{% for c in containers %}
<tr>
<td style="text-align: center;">
<input type="checkbox" name="selected_containers" value="{{ c.tenant_name }}">
</td>
<td><b>{{ c.tenant_name }}</b></td>
<td>
{% if c.status == '运行中' %}
<span class="status-running">{{ c.status }}</span>
{% else %}
<span class="status-stopped">{{ c.status }}</span>
{% endif %}
</td>
<td><span style="background: #e2e3e5; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{{ c.owner }}</span></td>
<td>{{ c.os_type }}</td>
<td>{{ c.tenant_id }}</td>
<td><span style="color: green; font-weight: bold;">{{ c.container_ip }}</span></td>
<td>{{ c.ssh_port }}</td>
<td><span class="pass-tag">{{ c.root_pass }}</span></td>
<td><code>ssh {{ c.ssh_user }}@{{ c.host_ip }} -p {{ c.ssh_port }}</code></td>
<td style="text-align: center;">
  <div class="dropdown">
    <button type="button" class="dropbtn">管理 ⚙️</button>
    <div class="dropdown-content">
      {% if c.status == '运行中' %}
      <a href="/container/single_action?name={{ c.tenant_name }}&act=stop">⏹️ 停止容器</a>
      {% else %}
      <a href="/container/single_action?name={{ c.tenant_name }}&act=start">▶️ 启动容器</a>
      {% endif %}
      <a href="/container/single_action?name={{ c.tenant_name }}&act=restart">🔄 重启容器</a>
      <a href="javascript:void(0);" onclick="openReinstallModal('{{ c.tenant_name }}')">⚡ 重装系统</a>
      <a href="javascript:void(0);" onclick="openMountModal('{{ c.tenant_name }}')">📁 挂载目录</a>
      <a href="/container/single_action?name={{ c.tenant_name }}&act=unmount">❌ 取消挂载</a>
    </div>
  </div>
</td>
</tr>
{% else %}
<tr>
<td colspan="11" style="text-align: center; color: #888;">暂无容器记录，请展开上方【➕ 创建新容器】创建。</td>
</tr>
{% endfor %}
</tbody>
</table>
{% if containers %}
<div class="action-bar">
<span style="font-weight: bold;">对选中容器执行物理操作：</span>
<button type="submit" name="action" value="restart" class="btn-restart" onclick="return confirmContainerAction('重启/启动')">🔄 智能重启</button>
<button type="submit" name="action" value="stop" class="btn-stop" onclick="return confirmContainerAction('停止')">⏹️ 批量停止</button>
<button type="submit" name="action" value="delete" class="btn-delete" onclick="return confirmContainerAction('delete')">🗑️ 批量删除</button>
</div>
{% endif %}
</form>
</div>

<div id="mountModal" class="modal">
  <div class="modal-content">
    <span class="close-btn" onclick="closeMountModal()">&times;</span>
    <h3 style="margin-top:0;">📂 挂载宿主机目录</h3>
    <form action="/container/mount" method="post">
      <input type="hidden" id="mount_cname" name="container_name">
      <div style="margin-bottom:12px;">
        <label>宿主机真实目录路径 (Host Path):</label>
        <input type="text" name="host_path" placeholder="例如: /data/share" required>
      </div>
      <div style="margin-bottom:12px;">
        <label>容器内挂载点 (Container Path):</label>
        <input type="text" name="container_path" placeholder="例如: /mnt/data" required>
      </div>
      <button type="submit" style="width:100%; background-color:#28a745;">确认挂载</button>
    </form>
  </div>
</div>

<div id="reinstallModal" class="modal">
  <div class="modal-content">
    <span class="close-btn" onclick="closeReinstallModal()">&times;</span>
    <h3 style="margin-top:0; color:#dc3545;">⚡ 重新安装容器系统</h3>
    <p style="font-size:13px; color:#666;">注意：重装系统将清空当前容器存储的所有内容并重新初始化镜像！</p>
    <form action="/container/reinstall" method="post">
      <input type="hidden" id="reinstall_cname" name="container_name">
      <div style="margin-bottom:12px;">
        <label>目标操作系统 (OS_TYPE):</label>
        <select name="os_type">
          <option value="ub24">Ubuntu 24.04</option>
          <option value="alpine">Alpine 3.24</option>
          <option value="debian13">Debian 13</option>
          <option value="centos9">CentOS Stream 9</option>
          <option value="rocky9">Rocky Linux 9</option>
        </select>
      </div>
      <button type="submit" style="width:100%; background-color:#dc3545;" onclick="return confirm('数据无价！确定重装该容器吗？')">确认重装</button>
    </form>
  </div>
</div>

</body>
</html>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = get_db_user(username)
        if user and user['password'] == password:
            session['user'] = username
            return redirect(url_for('index'))
        else:
            flash("用户名或密码错误！")
            return render_template_string(LOGIN_TEMPLATE)
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user_info = get_db_user(session['user'])
    containers = get_user_incus_containers(session['user'])
    all_users_info = get_all_users_detail() if session['user'] == 'admin' else []
    current_tenant_id = user_info['tenant_id'] if user_info else 10
    return render_template_string(
        INDEX_TEMPLATE,
        containers=containers,
        all_users_info=all_users_info,
        current_tenant_id=current_tenant_id
    )

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    if session['user'] != 'admin':
        flash("❌ 只有超级管理员可以添加用户！")
        return redirect(url_for('index'))
    new_username = request.form.get('new_username', '').strip()
    new_password = request.form.get('new_password', '').strip()
    if new_username and new_password:
        try:
            auto_tid = get_next_available_tenant_id()
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password, role, tenant_id) VALUES (?, ?, 'user', ?)",
                (new_username, new_password, auto_tid)
            )
            conn.commit()
            conn.close()
            flash(f"🎉 成功添加新租户 [{new_username}]（密码: {new_password}，租户 ID: {auto_tid}）！数据已持久化。")
        except sqlite3.IntegrityError:
            flash(f"❌ 添加失败：用户名 [{new_username}] 已存在！")
    return redirect(url_for('index'))

@app.route('/create', methods=['POST'])
@login_required
def create_container():
    tenant_name = request.form.get('tenant_name', '').strip()
    os_type = request.form.get('os_type', '').strip()
    tenant_id = request.form.get('tenant_id', '').strip()
    mem_limit = request.form.get('mem_limit', '').strip()
    disk_limit = request.form.get('disk_limit', '').strip()
    assign_owner = request.form.get('assign_owner', '').strip()
    
    if session['user'] == 'admin' and assign_owner:
        target_owner = assign_owner
    else:
        target_owner = session['user']
        
    if not all([tenant_name, os_type, tenant_id, mem_limit, disk_limit]):
        flash("❌ 错误：所有表单字段均不能为空！")
        return redirect(url_for('index'))
    
    cmd = [
        "create_lxd.sh",
        tenant_name,
        os_type,
        tenant_id,
        mem_limit,
        disk_limit
    ]
    
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = process.stdout + process.stderr
        
        # 兼容处理：即使脚本返回码非 0（例如主键冲突但容器已实际在系统中存在），只要能检查到容器存在或存活则允许正常注册
        container_exists_in_incus = False
        check_running = run_incus(["info", tenant_name], check=False)
        if check_running and check_running.returncode == 0:
            container_exists_in_incus = True

        if process.returncode != 0 and not container_exists_in_incus:
            flash(f"❌ 容器创建失败! 日志:\n{output}")
        else:
            run_incus(["start", tenant_name], check=False, timeout=30)
            
            ssh_user = "admin" if os_type in ["ub24", "debian13"] else "root"
            user_match = re.search(r"登录用户\s*[:：]\s*([A-Za-z0-9_-]+)", output, re.IGNORECASE)
            if user_match:
                ssh_user = user_match.group(1)
                
            parsed_root_pass = "root123456"
            pass_match = re.search(r"(?:Root\s*密码|登录密码)\s*:\s*([^\s]+)", output, re.IGNORECASE)
            if pass_match:
                parsed_root_pass = pass_match.group(1)
            else:
                print(f"DEBUG OUTPUT: {output}")
                parsed_root_pass = "123456"

            run_incus(["config", "set", tenant_name, f"user.owner={target_owner}"], check=False)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT ssh_port FROM container_records WHERE container_name = ?", (tenant_name,))
            row = cursor.fetchone()
            
            if row and row[0]:
                assigned_port = row[0]
            else:
                assigned_port = get_next_ssh_port()
                run_incus([
                    "config", "device", "add",
                    tenant_name, "ssh_proxy", "proxy",
                    f"listen=tcp:0.0.0.0:{assigned_port}",
                    "connect=tcp:127.0.0.1:22"
                ], check=False)
            
            cursor.execute(
                "REPLACE INTO container_records (container_name, owner, tenant_id, root_pass, os_type, ssh_port) VALUES (?, ?, ?, ?, ?, ?)",
                (tenant_name, target_owner, int(tenant_id), parsed_root_pass, os_type, assigned_port)
            )
            conn.commit()
            conn.close()
            time.sleep(0.5)
            flash(f"🎉 容器 {tenant_name} 注册成功，所有者: [{target_owner}]，端口: {assigned_port}！")
    except Exception as e:
        flash(f"❌ 系统异常: {str(e)}")
        
    return redirect(url_for('index'))

@app.route('/containers/action', methods=['POST'])
@login_required
def container_action():
    selected = request.form.getlist('selected_containers')
    action = request.form.get('action')
    
    if not selected:
        flash("请先在列表中选中要操作的容器!")
        return redirect(url_for('index'))
        
    success_count = 0
    fail_count = 0
    
    for c_name in selected:
        try:
            if action == 'restart':
                status_res = run_incus(["info", c_name], check=False)
                is_running = status_res and "Status: Running" in status_res.stdout
                if is_running:
                    res = run_incus(["restart", c_name], check=False, timeout=30)
                else:
                    res = run_incus(["start", c_name], check=False, timeout=30)
            elif action == 'stop':
                res = run_incus(["stop", c_name], check=False, timeout=30)
            elif action == 'delete':
                res = run_incus(["delete", "--force", c_name], check=False, timeout=30)
            else:
                continue
                
            if res and res.returncode == 0:
                success_count += 1
                if action == 'delete':
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM container_records WHERE container_name = ?", (c_name,))
                    conn.commit()
                    conn.close()
            else:
                fail_count += 1
        except Exception:
            fail_count += 1
            
    action_text_map = {'restart': '智能重启/启动', 'stop': '停止', 'delete': '删除'}
    act_str = action_text_map.get(action, '操作')
    flash(f"批量[{act_str}]完成: 成功 {success_count} 个，失败 {fail_count} 个。")
    return redirect(url_for('index'))

@app.route('/container/single_action')
@login_required
def single_action():
    c_name = request.args.get('name')
    act = request.args.get('act')
    db_records = get_db_container_records()
    
    if c_name in db_records and session['user'] != 'admin' and db_records[c_name]['owner'] != session['user']:
        flash("❌ 无权管理此容器！")
        return redirect(url_for('index'))

    try:
        if act == 'start':
            res = run_incus(["start", c_name], check=False, timeout=30)
            if res and res.returncode == 0:
                flash(f"✅ 容器 [{c_name}] 已成功启动！")
            else:
                flash(f"❌ 启动失败: {res.stderr if res else '未知错误'}")
        elif act == 'stop':
            res = run_incus(["stop", c_name], check=False, timeout=30)
            if res and res.returncode == 0:
                flash(f"✅ 容器 [{c_name}] 已成功停止！")
            else:
                flash(f"❌ 停止失败: {res.stderr if res else '未知错误'}")
        elif act == 'restart':
            status_res = run_incus(["info", c_name], check=False)
            is_running = status_res and "Status: Running" in status_res.stdout
            if is_running:
                res = run_incus(["restart", c_name], check=False, timeout=30)
                if res and res.returncode == 0:
                    flash(f"✅ 容器 [{c_name}] 已成功重启！")
                else:
                    flash(f"❌ 重启失败: {res.stderr if res else '未知错误'}")
            else:
                res = run_incus(["start", c_name], check=False, timeout=30)
                if res and res.returncode == 0:
                    flash(f"✅ 容器 [{c_name}] 当前已停止，已为您自动执行启动！")
                else:
                    flash(f"❌ 启动失败: {res.stderr if res else '未知错误'}")
        elif act == 'unmount':
            res = run_incus(["config", "device", "remove", c_name, "custom_share"], check=False, timeout=15)
            if res and res.returncode == 0:
                flash(f"✅ 已清除容器 [{c_name}] 的自定义挂载点！")
            else:
                flash(f"❌ 取消挂载失败或本身无自定义挂载设备")
    except Exception as e:
        flash(f"❌ 操作异常: {str(e)}")

    return redirect(url_for('index'))

@app.route('/container/mount', methods=['POST'])
@login_required
def mount_directory():
    c_name = request.form.get('container_name')
    host_path = request.form.get('host_path', '').strip()
    container_path = request.form.get('container_path', '').strip()

    if not host_path or not container_path:
        flash("❌ 宿主机路径与容器路径均不能为空！")
        return redirect(url_for('index'))

    try:
        res = run_incus([
            "config", "device", "add",
            c_name, "custom_share", "disk",
            f"source={host_path}", f"path={container_path}"
        ], check=False, timeout=15)
        
        if res and res.returncode == 0:
            flash(f"🎉 成功将宿主机路径 [{host_path}] 挂载到容器 [{c_name}] 的 [{container_path}]！")
        else:
            flash(f"❌ 挂载失败: {res.stderr if res else '未知错误'}")
    except Exception as e:
        flash(f"❌ 挂载异常: {str(e)}")

    return redirect(url_for('index'))

@app.route('/container/reinstall', methods=['POST'])
@login_required
def reinstall_container():
    c_name = request.form.get('container_name')
    os_type = request.form.get('os_type')
    db_records = get_db_container_records()

    if c_name not in db_records:
        flash("❌ 重装失败：未找到该容器元数据记录！")
        return redirect(url_for('index'))

    rec = db_records[c_name]
    tenant_id = str(rec['tenant_id'])
    old_port = rec['ssh_port']
    
    try:
        run_incus(["delete", "--force", c_name], check=False, timeout=30)
        cmd = ["create_lxd.sh", c_name, os_type, tenant_id, "512MB", "5GB"]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        output = process.stdout + process.stderr
        ssh_user = "admin" if os_type in ["ub24", "debian13"] else "root"
        user_match = re.search(r"登录用户\s*[:：]\s*([A-Za-z0-9_-]+)", output, re.IGNORECASE)
        if user_match:
            ssh_user = user_match.group(1)
            
        pass_match = re.search(r"(?:Root\s*密码|登录密码)\s*:\s*([^\s]+)", output, re.IGNORECASE)
        if pass_match:
            parsed_root_pass = pass_match.group(1)
        else:
            print(f"DEBUG OUTPUT: {output}")
            parsed_root_pass = "123456"

        run_incus(["start", c_name], check=False, timeout=30)
        run_incus(["config", "set", c_name, f"user.owner={rec['owner']}"], check=False)
        host_ip = get_host_ip()
        
        run_incus([
            "config", "device", "add",
            c_name, "ssh_proxy", "proxy",
            f"listen=tcp:0.0.0.0:{old_port}",
            "connect=tcp:127.0.0.1:22"
        ], check=False)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "REPLACE INTO container_records (container_name, owner, tenant_id, root_pass, os_type, ssh_port) VALUES (?, ?, ?, ?, ?, ?)",
            (c_name, rec['owner'], int(tenant_id), parsed_root_pass, os_type, old_port)
        )
        conn.commit()
        conn.close()

        flash(f"⚡ 容器 [{c_name}] 系统已成功重装为 [{os_type}]！")
    except Exception as e:
        flash(f"❌ 系统重装失败: {str(e)}")

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)










三、 部署与后台守护运行
为了确保面板在后台持续工作，我们可以用 Debian 13 原生的 systemd 服务来管理它。

1. 创建 Systemd 服务文件
rambo@debian137:~$ sudo vim /etc/systemd/system/lxcweb.service
[Unit]
Description=LXC Lightweight Management Web Panel
After=network.target lxc.service

[Service]
Type=simple
User=lxcweb
WorkingDirectory=/home/lxcweb
# 使用 gunicorn 启动，启用 2 个工作进程，监听 5000 端口
ExecStart=/usr/bin/gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target



ExecStart参数说明：
app:app：第一个app是文件名app.py，第二个app是代码中Flask实例的变量名 (app = Flask(__name__))
--workers 2：开启 2 个并发工作进程，可根据 CPU 核心数调整




2. 启动服务并设置开机自启
rambo@debian137:~$ sudo systemctl daemon-reload && sudo systemctl enable --now lxcweb
rambo@debian137:~$ sudo systemctl status lxcweb
● lxcweb.service - LXC Lightweight Management Web Panel
     Loaded: loaded (/etc/systemd/system/lxcweb.service; enabled; preset: enabled)
     Active: active (running) since Tue 2026-09-22 09:30:46 HKT; 2min 52s ago
 Invocation: fdbbd9854039458f997d4e8116182dd7
   Main PID: 34369 (gunicorn: maste)
      Tasks: 3 (limit: 9404)
     Memory: 34M (peak: 42.3M)
        CPU: 957ms
     CGroup: /system.slice/lxcweb.service
             ├─34369 "gunicorn: master [app:app]"
             └─34372 "gunicorn: worker [app:app]"

Sep 22 09:30:46 debian137 systemd[1]: Started lxcweb.service - LXC Lightweight Management Web Panel.
Sep 22 09:30:47 debian137 gunicorn[34369]: [2026-09-22 09:30:47 +0800] [34369] [INFO] Starting gunicorn 23.0.0
Sep 22 09:30:47 debian137 gunicorn[34369]: [2026-09-22 09:30:47 +0800] [34369] [INFO] Listening at: http://0.0.0.0:5000 (34369)
Sep 22 09:30:47 debian137 gunicorn[34369]: [2026-09-22 09:30:47 +0800] [34369] [INFO] Using worker: gthread
Sep 22 09:30:47 debian137 gunicorn[34372]: [2026-09-22 09:30:47 +0800] [34372] [INFO] Booting worker with pid: 34372






rambo@debian137:~$ sudo netstat -anpt|grep 5000
tcp      0     0 0.0.0.0:5000      0.0.0.0:*   LISTEN      19605/gunicorn: mas    



# 放行宿主机防火墙端口
根据你宿主机使用的防火墙工具，放行 5000 端口：
1. 如果使用的是 nftables（Debian 默认）
检查是否有防火墙规则限制。如果配置了入站规则，需要放行 5000 端口：
sudo nft add rule inet filter input tcp dport 5000 accept

2. 如果使用的是 ufw
sudo ufw allow 5000/tcp
sudo ufw reload

3. 如果使用的是 iptables
sudo iptables -A INPUT -p tcp --dport 5000 -j ACCEPT





四、 验证与使用方式
本地测试访问：
在宿主机上打开浏览器访问 http://IP:5000，或使用 curl http://0.0.0.0:5000/login
测试账号登录：
管理员账密：admin/Admin123456
zhangsan用户账密：zhangsan/Zhang123456
lisi用户账密：lisi/Lisi123456


# 先测管理员登录

```
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922062139071-1001009137.png)
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922062218798-1006091157.png)

<font color=red>**测试创建容器**</font>
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922063509780-2020715710.png)
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093427762-943756831.png)


<font color=red>**测试指定租户创建容器**</font>
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093533924-1083570437.png)
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093613771-374823465.png)







# 测租户登录
```shell
验证"一键重建"流程：
登录后点击底部的【重置系统 / 一键销毁与重建】
输入二次确认容器名 debian01，点击确认

后端会自动以 sudo 调用你的 /etc/lxc/destroy_and_rebuild.sh debian01 tpl-debian13 脚本

约 2~3 秒后弹窗提示成功，网页自动更新IP和最新运行状态

```
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093738409-1206680004.png)
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093839848-623718603.png)
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922093908347-1505103905.png)


<font color=red>**测试把本地目录挂载到容器中**</font>
![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922095741711-728141009.png)
```shell
# 在宿机上添加测试文件
rambo@debian137:~$ echo "hello from host" > /home/rambo/test/a.txt


如果验证发现 /mnt/data 下面没有同步宿主机的内容，可以在宿主机执行以下命令检查 Incus 的设备配置是否正确生效：
rambo@debian137:~$ incus config show 容器名称 --expanded
在输出中检查是否有类似以下的 devices 配置项：
devices:
  custom_share:
    path: /mnt/data
    source: /home/rambo/test
    type: disk
如果没有，说明 Web 端的挂载指令未成功写入该容器，可以尝试在Web端重新点一次"确认挂载"


# 进入容器确定文件的一致性
rambo@debian137:~$ sudo incus exec alpine326 -- /bin/sh
# cat /mnt/data/a.txt
hello from host

ok,挂载没问题

```

<font color=red>**测试重装容器**</font>
> 因为是重装所以上述的a.txt会消失
> ![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922100123494-1326467949.png)
> ![image](https://img2024.cnblogs.com/blog/1139005/202609/1139005-20260922100212933-777834305.png)

```shell
# 再来查看容器中的数据
rambo@debian137:~$ sudo incus exec alpine326 -- /bin/sh
# cat /mnt/data/a.txt
cat: /mnt/data/a.txt: No such file or directory
# 

```






# FAQ
```shell
# 强力删除残留实例
incus delete alpine326 --force





```