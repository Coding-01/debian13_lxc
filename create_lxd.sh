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
