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

检查宿主机内核是否具备 LXC 所需功能：
rambo@debian137:~$ sudo lxc-checkconfig

重点观察是否有 enabled、available 或类似正常状态

检查AppArmor：
rambo@debian137:~$ sudo systemctl enable --now apparmor
rambo@debian137:~$ sudo aa-status
如果 lxc-checkconfig 中出现某些功能缺失，先不要创建生产容器，应先解决内核或相关软件包问题

启动网络服务：
rambo@debian137:~$ sudo systemctl enable --now lxc-net
rambo@debian137:~$ sudo systemctl restart lxc-net
rambo@debian137:~$ systemctl status lxc-net
如果能看到 lxcbr0，说明宿主机的 LXC NAT 网桥基本建立成功。LXC 默认的独立网桥通常使用私有网段，并通过宿主机进行 NAT；这种方式适合先学习和运行普通服务

# 查看镜像
rambo@debian137:~$ sudo lxc-ls

# 查看传统LXC容器列表
rambo@debian137:~$ sudo lxc-ls -f

# 查看容器目录
rambo@debian137:~$ sudo ls -lh /var/lib/lxc/

# 查看状态
rambo@debian137:~$ sudo lxc-info -n <CONTAINER_NAME>

# 进入容器
rambo@debian137:~$ sudo lxc-attach -n <CONTAINER_NAME>  --clear-env -- /bin/bash
root@xxx:/# 
apt update && apt install -y ca-certificates curl vim sudo wget curl systemd
echo "root:aaaaaa" | chpasswd
exit

# 查看容器IP
rambo@debian137:~$ sudo lxc-attach -n <CONTAINER_NAME>  --clear-env -- ip a sh eth0

# 启停容器
rambo@debian137:~$ sudo lxc-{start|stop|restart} -n <CONTAINER_NAME>

# 查看信息
rambo@debian137:~$ sudo lxc-info -n <CONTAINER_NAME>

# 删除容器
rambo@debian137:~$ sudo lxc-destroy -n <CONTAINER_NAME>

# 设置容器开机自动启动
rambo@debian137:~$ sudo vim /var/lib/lxc/<CONTAINER_NAME>/config
lxc.start.auto = 1 
lxc.start.delay = 5

# 测试
rambo@debian137:~$ sudo systemctl {start|stop|restart|status} lxc


# 在容器内部部署服务
以 Nginx 为例：
rambo@debian137:~$ sudo lxc-attach -n debian01 --clear-env -- bash -c '
apt update && DEBIAN_FRONTEND=noninteractive &&
apt install -y nginx &&
systemctl enable nginx && systemctl restart nginx'

# 查看服务
rambo@debian137:~$ sudo lxc-attach -n <CONTAINER_NAME>  --clear-env -- systemctl status nginx

# 查看监听端口
rambo@debian137:~$ sudo lxc-attach -n <CONTAINER_NAME>  --clear-env -- netstat -anpt|grep 80


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
在宿主机创建文件 /home/lxcweb/app.py：
rambo@debian137:~$ sudo vim /home/lxcweb/app.py         # 见app.py

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


rambo@debian137:~$ sudo netstat -anpt|grep 5000
tcp      0     0 0.0.0.0:5000      0.0.0.0:*   LISTEN      19605/gunicorn: mas    


四、 验证与使用方式
本地测试访问：
在宿主机上打开浏览器访问 http://IP:5000，或使用 curl http://0.0.0.0:5000/login
测试账号登录：
管理员账密：admin/Admin123456
zhangsan用户账密：zhangsan/Zhang123456
lisi用户账密：lisi/Lisi123456

```



