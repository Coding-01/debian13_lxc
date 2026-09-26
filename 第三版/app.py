#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import sqlite3
import subprocess
import socket
import time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = 'super_secret_lxd_key_change_me'
DB_FILE = 'users.db'

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
        tenant_id INTEGER UNIQUE,
        port_range TEXT DEFAULT '10000-20000'
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS container_records (
        container_name TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        tenant_id INTEGER NOT NULL,
        root_pass TEXT NOT NULL DEFAULT '123456',
        os_type TEXT NOT NULL DEFAULT 'Linux',
        ssh_port INTEGER,
        cpu_limit TEXT DEFAULT '1核',
        mem_limit TEXT DEFAULT '512MB',
        disk_limit TEXT DEFAULT '5GB'
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        client_ip TEXT NOT NULL,
        action_desc TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_store (
        key_name TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        desc TEXT NOT NULL,
        script TEXT NOT NULL
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS container_ports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        container_name TEXT NOT NULL,
        device_name TEXT NOT NULL,
        host_port INTEGER NOT NULL,
        container_port INTEGER NOT NULL
    )
    ''')
    
    for col, default_val in [
        ("os_type", "Linux"), 
        ("ssh_port", "NULL"), 
        ("cpu_limit", "1核"), 
        ("mem_limit", "512MB"), 
        ("disk_limit", "5GB")
    ]:
        try:
            cursor.execute(f"ALTER TABLE container_records ADD COLUMN {col} TEXT DEFAULT '{default_val}'")
        except Exception:
            pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN port_range TEXT DEFAULT '10000-20000'")
    except Exception:
        pass

    default_users = [
        ('admin', 'AdminPass123', 'admin', 1, '1-65535'),
        ('zhangsan', 'Zhang123456', 'user', 10, '10000-20000'),
        ('lisi', 'Lisi123456', 'user', 11, '20001-30000')
    ]
    for u, p, r, tid, prange in default_users:
        cursor.execute("SELECT id FROM users WHERE username = ?", (u,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (username, password, role, tenant_id, port_range) VALUES (?, ?, ?, ?, ?)",
                (u, p, r, tid, prange)
            )

    cursor.execute("SELECT COUNT(*) FROM app_store")
    if cursor.fetchone()[0] == 0:
        default_apps = [
            (
                "wordpress",
                "WordPress 博客系统",
                "一键部署 WordPress + Nginx + PHP-FPM + MariaDB 数据库 (自动适配系统)",
                """
            if command -v apt &> /dev/null; then
                export DEBIAN_FRONTEND=noninteractive
                apt update && apt install -y nginx php-fpm php-mysql mariadb-server curl unzip rsync
                systemctl enable nginx mariadb php*-fpm
                systemctl start nginx mariadb
            elif command -v dnf &> /dev/null; then
                dnf install -y epel-release
                dnf install -y nginx php-fpm php-mysqlnd mariadb-server curl unzip rsync
                systemctl enable nginx mariadb php-fpm
                systemctl start nginx mariadb
            fi
            
            cat << 'EOF' > /etc/nginx/sites-available/default 2>/dev/null || cat << 'EOF' > /etc/nginx/conf.d/default.conf
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    root /var/www/html;
    index index.php index.html index.htm;
    server_name _;
    location / {
        try_files $uri $uri/ /index.php?$args;
    }
    location ~ \\.php$ {
        include snippets/fastcgi-php.conf 2>/dev/null || true;
        fastcgi_pass unix:/run/php/php-fpm.sock 2>/dev/null || fastcgi_pass unix:/run/php-fpm/www.sock;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
    location ~ /\\.ht {
        deny all;
    }
}
EOF
            
            mkdir -p /var/www/html
            mysql -e "CREATE DATABASE IF NOT EXISTS wordpress;" 2>/dev/null || true
            mysql -e "CREATE USER IF NOT EXISTS 'wpuser'@'localhost' IDENTIFIED BY 'WpPass123!';" 2>/dev/null || true
            mysql -e "GRANT ALL PRIVILEGES ON wordpress.* TO 'wpuser'@'localhost'; FLUSH PRIVILEGES;" 2>/dev/null || true
            
            cd /var/www/html && rm -rf *
            curl -O https://wordpress.org/latest.zip && unzip -q latest.zip && mv wordpress/* . && rm -rf wordpress latest.zip
            chown -R www-data:www-data /var/www/html 2>/dev/null || chown -R nginx:nginx /var/www/html || true
            
            systemctl restart nginx
            systemctl restart php*-fpm 2>/dev/null || systemctl restart php-fpm || true
        """
            ),
            (
                "nginx_latest",
                "Nginx 最新稳定版",
                "一键在线安装高性能最新版 Nginx Web 服务器 (自动适配 Debian/Ubuntu/CentOS/Rocky)",
                """
            if command -v apt &> /dev/null; then
                export DEBIAN_FRONTEND=noninteractive
                apt update && apt install -y nginx curl
                systemctl enable nginx
                systemctl start nginx
            elif command -v dnf &> /dev/null; then
                dnf install -y epel-release
                dnf install -y nginx curl
                systemctl enable nginx
                systemctl start nginx
            fi
            
            mkdir -p /var/www/html
            echo "<h1>Hello from Universal Nginx Deployed via App Store!</h1>" > /var/www/html/index.html
            systemctl restart nginx
        """
            )
        ]
        for k, t, d, s in default_apps:
            cursor.execute("INSERT OR IGNORE INTO app_store (key_name, title, desc, script) VALUES (?, ?, ?, ?)", (k, t, d, s))

    conn.commit()
    conn.close()

init_db()

def get_all_apps():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT key_name, title, desc, script FROM app_store")
    rows = cursor.fetchall()
    conn.close()
    apps = {}
    for r in rows:
        apps[r[0]] = {"title": r[1], "desc": r[2], "script": r[3]}
    return apps

def write_audit_log(username, action_desc):
    try:
        client_ip = request.remote_addr or "127.0.0.1"
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_logs (username, client_ip, action_desc) VALUES (?, ?, ?)",
            (username, client_ip, action_desc)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_next_available_tenant_id():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(tenant_id) FROM users")
    max_id = cursor.fetchone()[0]
    conn.close()
    return (max_id + 1) if (max_id and max_id >= 10) else 10

def get_next_ssh_port(username=None, port_range_str="10000-20000"):
    # 如果指定了用户，从数据库动态读取该用户设定的端口范围
    if username:
        user_info = get_db_user(username)
        if user_info and user_info.get('port_range'):
            port_range_str = user_info['port_range']

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT ssh_port FROM container_records")
    used_ports = {row[0] for row in cursor.fetchall() if row[0]}
    conn.close()

    # 解析规则（如：80,443,22,10301-10602）
    parts = port_range_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                p_min, p_max = map(int, part.split('-'))
                for p in range(p_min, p_max + 1):
                    # 自动过滤常用系统特权端口及 22/80/443，并确保未被占用
                    if p not in used_ports and p not in [22, 80, 443]:
                        return p
            except ValueError:
                pass
        else:
            try:
                p = int(part)
                if p not in used_ports and p not in [22, 80, 443]:
                    return p
            except ValueError:
                pass

    return 2302

def get_available_web_port(preferred_port=8080):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT ssh_port FROM container_records")
    used_db_ports = {row[0] for row in cursor.fetchall() if row[0]}
    conn.close()

    port = preferred_port
    while port < 65535:
        if port not in used_db_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('0.0.0.0', port))
                    return port
                except OSError:
                    pass
        port += 1
    return port

def get_db_user(username):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, role, tenant_id, port_range FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"username": row[0], "password": row[1], "role": row[2], "tenant_id": row[3], "port_range": row[4] or "10000-20000"}
    return None

def get_all_users_detail():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password, role, tenant_id, port_range FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "password": r[2], "role": r[3], "tenant_id": r[4], "port_range": r[5] or "10000-20000"} for r in rows]

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
    cursor.execute("SELECT container_name, owner, tenant_id, root_pass, os_type, ssh_port, cpu_limit, mem_limit, disk_limit FROM container_records")
    rows = cursor.fetchall()
    conn.close()
    res = {}
    for r in rows:
        port = r[5] if r[5] else (2302 + r[0].__hash__() % 100)
        res[r[0]] = {
            "owner": r[1], 
            "tenant_id": r[2], 
            "root_pass": r[3], 
            "os_type": r[4], 
            "ssh_port": port,
            "cpu_limit": r[6] if r[6] else "1核",
            "mem_limit": r[7] if r[7] else "512MB",
            "disk_limit": r[8] if r[8] else "5GB"
        }
    return res

def get_container_ports(container_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, device_name, host_port, container_port FROM container_ports WHERE container_name = ?", (container_name,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "device_name": r[1], "host_port": r[2], "container_port": r[3]} for r in rows]

def is_port_allowed(port, port_range_str):
    if not port_range_str:
        return False
    parts = port_range_str.split(',')
    for part in parts:
        part = part.strip()
        if '-' in part:
            try:
                p_min, p_max = map(int, part.split('-'))
                if p_min <= port <= p_max:
                    return True
            except ValueError:
                pass
        else:
            try:
                if int(part) == port:
                    return True
            except ValueError:
                pass
    return False

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
        
        owner_info = get_db_user(owner)
        user_port_range = owner_info['port_range'] if owner_info else "10000-20000"
        
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
            
        custom_ports = get_container_ports(c_name)

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
            "status": status,
            "cpu_limit": info["cpu_limit"],
            "mem_limit": info["mem_limit"],
            "disk_limit": info["disk_limit"],
            "port_range": user_port_range,
            "custom_ports": custom_ports
        })
        
    return containers_list

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = get_db_user(username)
        if user and user['password'] == password:
            session['user'] = username
            write_audit_log(username, "登录后台系统成功")
            return redirect(url_for('index'))
        else:
            flash("用户名或密码错误！")
            return render_template('login.html')
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user' in session:
        write_audit_log(session['user'], "退出登录")
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user_info = get_db_user(session['user'])
    containers = get_user_incus_containers(session['user'])
    all_users_info = get_all_users_detail() if session['user'] == 'admin' else []
    current_tenant_id = user_info['tenant_id'] if user_info else 10
    return render_template(
        'index.html',
        containers=containers,
        all_users_info=all_users_info,
        current_tenant_id=current_tenant_id,
        user_info=user_info
    )

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    if session['user'] != 'admin':
        flash("❌ 只有超级管理员可以添加用户！")
        return redirect(url_for('index'))
    new_username = request.form.get('new_username', '').strip()
    new_password = request.form.get('new_password', '').strip()
    port_range = request.form.get('port_range', '10000-20000').strip()
    if new_username and new_password:
        try:
            auto_tid = get_next_available_tenant_id()
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password, role, tenant_id, port_range) VALUES (?, ?, 'user', ?, ?)",
                (new_username, new_password, auto_tid, port_range)
            )
            conn.commit()
            conn.close()
            write_audit_log(session['user'], f"添加新租户: {new_username} (端口范围: {port_range})")
            flash(f"🎉 成功添加新租户 [{new_username}]（端口范围: {port_range}）！数据已持久化。")
        except sqlite3.IntegrityError:
            flash(f"❌ 添加失败：用户名 [{new_username}] 已存在！")
    return redirect(url_for('index'))

@app.route('/admin/update_user_ports', methods=['POST'])
@login_required
def update_user_ports():
    if session['user'] != 'admin':
        flash("❌ 只有超级管理员可以修改用户端口范围！")
        return redirect(url_for('index'))
    username = request.form.get('username')
    port_range = request.form.get('port_range', '').strip()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET port_range = ? WHERE username = ?", (port_range, username))
    conn.commit()
    conn.close()
    flash(f"✅ 用户 [{username}] 端口规则已更新为: {port_range}。")
    return redirect(url_for('index'))

@app.route('/create', methods=['POST'])
@login_required
def create_container():
    tenant_name = request.form.get('tenant_name', '').strip()
    
    if not re.match(r'^[a-zA-Z0-9_-]{3,16}$', tenant_name):
        flash("❌ 错误：容器名称必须是 3-16 位的字母、数字、下划线或减号！")
        return redirect(url_for('index'))

    os_type = request.form.get('os_type', '').strip()
    tenant_id = request.form.get('tenant_id', '').strip()
    mem_limit = request.form.get('mem_limit', '512MB').strip()
    disk_limit = request.form.get('disk_limit', '5GB').strip()
    cpu_limit = request.form.get('cpu_limit', '1核').strip()
    assign_owner = request.form.get('assign_owner', '').strip()
    
    target_owner = assign_owner if (session['user'] == 'admin' and assign_owner) else session['user']

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if session['user'] != 'admin':
        cursor.execute("SELECT COUNT(*) FROM container_records WHERE owner = ?", (target_owner,))
        count = cursor.fetchone()[0]
        if count >= 3:
            conn.close()
            flash("❌ 您的账号最多只能创建 3 个容器，已达配额上限！")
            return redirect(url_for('index'))
    conn.close()
        
    if not all([tenant_name, os_type, tenant_id, mem_limit, disk_limit, cpu_limit]):
        flash("❌ 错误：所有表单字段均不能为空！")
        return redirect(url_for('index'))
    
    cmd = ["create_lxd.sh", tenant_name, os_type, tenant_id, mem_limit, disk_limit]
    
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = process.stdout + process.stderr
        
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

            run_incus(["config", "set", tenant_name, f"user.owner={target_owner}"], check=False)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT ssh_port FROM container_records WHERE container_name = ?", (tenant_name,))
            row = cursor.fetchone()
            
            if row and row[0]:
                assigned_port = row[0]
            else:
                # 传入 target_owner 按照用户制定的端口规则及排除项分配首个可用端口
                assigned_port = get_next_ssh_port(username=target_owner)
                run_incus([
                    "config", "device", "add",
                    tenant_name, "ssh_proxy", "proxy",
                    f"listen=tcp:0.0.0.0:{assigned_port}",
                    "connect=tcp:127.0.0.1:22"
                ], check=False)
            
            cursor.execute(
                "REPLACE INTO container_records (container_name, owner, tenant_id, root_pass, os_type, ssh_port, cpu_limit, mem_limit, disk_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tenant_name, target_owner, int(tenant_id), parsed_root_pass, os_type, assigned_port, cpu_limit, mem_limit, disk_limit)
            )
            conn.commit()
            conn.close()
            time.sleep(0.5)
            write_audit_log(session['user'], f"成功创建容器: {tenant_name} (归属: {target_owner})")
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
                    cursor.execute("DELETE FROM container_ports WHERE container_name = ?", (c_name,))
                    conn.commit()
                    conn.close()
            else:
                fail_count += 1
        except Exception:
            fail_count += 1
            
    action_text_map = {'restart': '智能重启/启动', 'stop': '停止', 'delete': '批量删除'}
    act_str = action_text_map.get(action, '操作')
    write_audit_log(session['user'], f"执行批量{act_str}: 操作对象 {selected}")
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
            run_incus(["start", c_name], check=False, timeout=30)
            flash(f"✅ 容器 [{c_name}] 已启动！")
        elif act == 'stop':
            run_incus(["stop", c_name], check=False, timeout=30)
            flash(f"✅ 容器 [{c_name}] 已停止！")
        elif act == 'restart':
            run_incus(["restart", c_name], check=False, timeout=30)
            flash(f"✅ 容器 [{c_name}] 已重启！")
        elif act == 'unmount':
            run_incus(["config", "device", "remove", c_name, "custom_share"], check=False, timeout=15)
            flash(f"✅ 已取消挂载！")
        elif act == 'destroy':
            run_incus(["delete", "--force", c_name], check=False, timeout=30)
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM container_records WHERE container_name = ?", (c_name,))
            cursor.execute("DELETE FROM container_ports WHERE container_name = ?", (c_name,))
            conn.commit()
            conn.close()
            flash(f"🗑️ 容器 [{c_name}] 已彻底销毁！")
            return redirect(url_for('index'))
            
        write_audit_log(session['user'], f"单容器操作 [{act}]: {c_name}")
    except Exception as e:
        flash(f"❌ 操作异常: {str(e)}")

    return redirect(url_for('index'))

@app.route('/container/terminal')
@login_required
def container_terminal():
    c_name = request.args.get('name')
    db_records = get_db_container_records()
    if c_name in db_records and session['user'] != 'admin' and db_records[c_name]['owner'] != session['user']:
        flash("❌ 无权访问此容器终端！")
        return redirect(url_for('index'))
    
    write_audit_log(session['user'], f"通过 Web 终端连入容器: {c_name}")
    bin_path = get_incus_bin()
    
    import socket
    def find_free_port():
        s = socket.socket()
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    ttyd_port = find_free_port()
    subprocess.Popen(
        ["ttyd", "-p", str(ttyd_port), "-W", "sudo", bin_path, "shell", c_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    host_ip = get_host_ip()
    return f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
    <meta charset="UTF-8">
    <title>容器 [{c_name}] Web 终端</title>
    <style>
    body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #1e1e1e; overflow: hidden; }}
    iframe {{ width: 100%; height: 100%; border: none; }}
    .top-bar {{ position: absolute; top: 5px; right: 15px; z-index: 999; }}
    .btn-back {{ background: #dc3545; color: white; padding: 5px 12px; text-decoration: none; border-radius: 4px; font-family: sans-serif; font-size: 12px; }}
    </style>
    </head>
    <body>
    <div class="top-bar">
        <a href="/" class="btn-back">关闭并返回控制台</a>
    </div>
    <iframe src="http://{host_ip}:{ttyd_port}"></iframe>
    </body>
    </html>
    """

@app.route('/container/reset_pwd')
@login_required
def container_reset_pwd():
    c_name = request.args.get('name')
    db_records = get_db_container_records()
    if c_name in db_records and session['user'] != 'admin' and db_records[c_name]['owner'] != session['user']:
        flash("❌ 无权操作！")
        return redirect(url_for('index'))
    
    new_pass = "P" + os.urandom(4).hex() + "8!"
    run_incus(["exec", c_name, "--", "sh", "-c", f"echo 'root:{new_pass}' | chpasswd"], check=False)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE container_records SET root_pass = ? WHERE container_name = ?", (new_pass, c_name))
    conn.commit()
    conn.close()
    
    write_audit_log(session['user'], f"重置密码: {c_name}")
    flash(f"🔑 密码已重置为: {new_pass}")
    return redirect(url_for('index'))

@app.route('/container/mount', methods=['POST'])
@login_required
def mount_directory():
    c_name = request.form.get('container_name')
    host_path = request.form.get('host_path', '').strip()
    container_path = request.form.get('container_path', '').strip()

    if not host_path or not container_path:
        flash("❌ 路径不能为空！")
        return redirect(url_for('index'))

    res = run_incus(["config", "device", "add", c_name, "custom_share", "disk", f"source={host_path}", f"path={container_path}"], check=False, timeout=15)
    if res and res.returncode == 0:
        flash(f"🎉 挂载成功！")
    else:
        flash(f"❌ 挂载失败")
    return redirect(url_for('index'))

@app.route('/container/reinstall', methods=['POST'])
@login_required
def reinstall_container():
    c_name = request.form.get('container_name')
    os_type = request.form.get('os_type')
    db_records = get_db_container_records()
    if c_name not in db_records:
        return redirect(url_for('index'))

    rec = db_records[c_name]
    tenant_id = str(rec['tenant_id'])
    old_port = rec['ssh_port']
    
    try:
        run_incus(["delete", "--force", c_name], check=False, timeout=30)
        subprocess.run(["create_lxd.sh", c_name, os_type, tenant_id, rec['mem_limit'], rec['disk_limit']], capture_output=True, text=True, timeout=120)
        run_incus(["start", c_name], check=False, timeout=30)
        run_incus(["config", "set", c_name, f"user.owner={rec['owner']}"], check=False)
        run_incus(["config", "device", "add", c_name, "ssh_proxy", "proxy", f"listen=tcp:0.0.0.0:{old_port}", "connect=tcp:127.0.0.1:22"], check=False)
        flash(f"⚡ 系统已重装为 [{os_type}]！")
    except Exception as e:
        flash(f"❌ 重装异常: {str(e)}")

    return redirect(url_for('index'))

# ==================== 端口管理核心路由 ====================
@app.route('/container/port/manage', methods=['POST'])
@login_required
def manage_container_port():
    c_name = request.form.get('container_name')
    action = request.form.get('action') 
    host_port = int(request.form.get('host_port', 0))
    container_port = int(request.form.get('container_port', 80))
    port_id = request.form.get('port_id')

    db_records = get_db_container_records()
    if c_name not in db_records:
        flash("❌ 容器不存在！")
        return redirect(url_for('index'))
    
    if session['user'] != 'admin' and db_records[c_name]['owner'] != session['user']:
        flash("❌ 无权操作此容器的端口！")
        return redirect(url_for('index'))

    owner_username = db_records[c_name]['owner']
    owner_info = get_db_user(owner_username)
    if session['user'] != 'admin':
        allowed_range_str = owner_info['port_range'] if owner_info else "10000-20000"
        if action in ['add', 'edit'] and not is_port_allowed(host_port, allowed_range_str):
            flash(f"❌ 宿主机端口 [{host_port}] 不在您的账号被授权的允许规则范围内 ({allowed_range_str})！")
            return redirect(url_for('index'))

    if action in ['add', 'edit'] and (host_port == 22 or host_port < 1024):
        flash(f"⚠️ 警告：您正在操作保留或危险端口 [{host_port}]（如 22 或特权端口）！")

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        if action == 'add':
            cursor.execute("SELECT container_name FROM container_ports WHERE host_port = ?", (host_port,))
            if cursor.fetchone():
                conn.close()
                flash(f"❌ 宿主机端口 [{host_port}] 已被其他映射占用！")
                return redirect(url_for('index'))
            
            device_name = f"port_proxy_{host_port}"
            res = run_incus([
                "config", "device", "add",
                c_name, device_name, "proxy",
                f"listen=tcp:0.0.0.0:{host_port}",
                f"connect=tcp:127.0.0.1:{container_port}"
            ], check=False)

            if res and res.returncode == 0:
                cursor.execute(
                    "INSERT INTO container_ports (container_name, device_name, host_port, container_port) VALUES (?, ?, ?, ?)",
                    (c_name, device_name, host_port, container_port)
                )
                conn.commit()
                flash(f"🎉 成功添加端口映射: 宿主机 {host_port} -> 容器 {container_port}（即时生效）！")
            else:
                flash("❌ 添加端口代理失败，端口可能已被占用。")

        elif action == 'edit':
            cursor.execute("SELECT device_name, host_port FROM container_ports WHERE id = ? AND container_name = ?", (port_id, c_name))
            row = cursor.fetchone()
            if not row:
                conn.close()
                flash("❌ 要修改的端口记录不存在！")
                return redirect(url_for('index'))
            
            old_device_name, old_host_port = row[0], row[1]
            
            if host_port != old_host_port:
                cursor.execute("SELECT container_name FROM container_ports WHERE host_port = ? AND id != ?", (host_port, port_id))
                if cursor.fetchone():
                    conn.close()
                    flash(f"❌ 新的宿主机端口 [{host_port}] 已被占用！")
                    return redirect(url_for('index'))

            run_incus(["config", "device", "remove", c_name, old_device_name], check=False)
            new_device_name = f"port_proxy_{host_port}"
            res = run_incus([
                "config", "device", "add",
                c_name, new_device_name, "proxy",
                f"listen=tcp:0.0.0.0:{host_port}",
                f"connect=tcp:127.0.0.1:{container_port}"
            ], check=False)

            if res and res.returncode == 0:
                cursor.execute(
                    "UPDATE container_ports SET device_name = ?, host_port = ?, container_port = ? WHERE id = ?",
                    (new_device_name, host_port, container_port, port_id)
                )
                conn.commit()
                flash(f"✅ 端口映射修改成功并即时生效（宿主机 {host_port} -> 容器 {container_port}）！")
            else:
                flash("❌ 修改端口映射失败。")

        conn.close()
        write_audit_log(session['user'], f"容器端口操作 [{action}]: 容器 {c_name}, 宿主机端口 {host_port}")
    except Exception as e:
        flash(f"❌ 端口操作异常: {str(e)}")

    return redirect(url_for('index'))

@app.route('/container/port/delete', methods=['GET'])
@login_required
def delete_container_port():
    port_id = request.args.get('id')
    db_records = get_db_container_records()
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT container_name, device_name, host_port FROM container_ports WHERE id = ?", (port_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            flash("❌ 端口映射记录不存在！")
            return redirect(url_for('index'))
        
        c_name, dev_name, host_port = row[0], row[1], row[2]
        if session['user'] != 'admin' and db_records.get(c_name, {}).get('owner') != session['user']:
            conn.close()
            flash("❌ 无权操作此容器端口！")
            return redirect(url_for('index'))

        run_incus(["config", "device", "remove", c_name, dev_name], check=False)
        cursor.execute("DELETE FROM container_ports WHERE id = ?", (port_id,))
        conn.commit()
        conn.close()
        write_audit_log(session['user'], f"删除容器端口映射: 容器 {c_name}, 宿主机端口 {host_port}")
        flash(f"🗑️ 端口映射已成功删除并即时生效！")
    except Exception as e:
        flash(f"❌ 删除端口异常: {str(e)}")
        
    return redirect(url_for('index'))
# ================================================================

@app.route('/container/apps', methods=['GET', 'POST'])
@login_required
def container_apps():
    containers = get_user_incus_containers(session['user'])
    app_scripts = get_all_apps()
    
    if request.method == 'POST':
        form_action = request.form.get('form_action')
        
        if form_action == 'publish_app':
            if session['user'] != 'admin':
                flash("❌ 只有管理员可以上架或修改应用！")
                return redirect(url_for('container_apps'))
            
            key_name = request.form.get('key_name', '').strip()
            title = request.form.get('title', '').strip()
            desc = request.form.get('desc', '').strip()
            script = request.form.get('script', '').strip()
            
            uploaded_file = request.files.get('script_file')
            if uploaded_file and uploaded_file.filename:
                try:
                    file_content = uploaded_file.read().decode('utf-8')
                    if file_content.strip():
                        script = file_content
                except Exception:
                    pass
            
            if not re.match(r'^[a-zA-Z0-9_]{2,30}$', key_name):
                flash("❌ 错误：应用标识(Key)只能由 2-30 位字母、数字、下划线组成！")
                return redirect(url_for('container_apps'))
                
            if not all([key_name, title, desc, script]):
                flash("❌ 错误：所有上架字段均不能为空！")
                return redirect(url_for('container_apps'))
                
            try:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute(
                    "REPLACE INTO app_store (key_name, title, desc, script) VALUES (?, ?, ?, ?)",
                    (key_name, title, desc, script)
                )
                conn.commit()
                conn.close()
                write_audit_log(session['user'], f"上架/修改应用: {title} ({key_name})")
                flash(f"🎉 成功保存应用 [{title}]！")
            except Exception as e:
                flash(f"❌ 保存失败: {str(e)}")
            return redirect(url_for('container_apps'))

        elif form_action == 'delete_app':
            if session['user'] != 'admin':
                flash("❌ 只有管理员可以删除应用！")
                return redirect(url_for('container_apps'))
            
            target_key = request.form.get('target_key', '').strip()
            if target_key:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM app_store WHERE key_name = ?", (target_key,))
                conn.commit()
                conn.close()
                write_audit_log(session['user'], f"删除应用: {target_key}")
                flash(f"🗑️ 应用 [{target_key}] 已成功删除！")
            return redirect(url_for('container_apps'))

        app_action = request.form.get('app_action')
        target_container = request.form.get('target_container')
        
        if not target_container:
            flash("❌ 请先为应用选择一个目标容器！")
            return redirect(url_for('container_apps'))
            
        db_records = get_db_container_records()
        if target_container in db_records and session['user'] != 'admin' and db_records[target_container]['owner'] != session['user']:
            flash("❌ 无权向此容器部署应用！")
            return redirect(url_for('container_apps'))

        if app_action in app_scripts:
            app_info = app_scripts[app_action]
            res = run_incus(["exec", target_container, "--", "bash", "-c", app_info["script"]], check=False, timeout=180)
            
            if res and res.returncode == 0:
                web_port = get_available_web_port(8080)
                proxy_name = f"app_proxy_{app_action}_{int(time.time())}"
                
                proxy_add_res = run_incus([
                    "config", "device", "add",
                    target_container, proxy_name, "proxy",
                    f"listen=tcp:0.0.0.0:{web_port}",
                    "connect=tcp:127.0.0.1:80"
                ], check=False)
                
                if proxy_add_res and proxy_add_res.returncode == 0:
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO container_ports (container_name, device_name, host_port, container_port) VALUES (?, ?, ?, ?)",
                        (target_container, proxy_name, web_port, 80)
                    )
                    conn.commit()
                    conn.close()

                host_ip = get_host_ip()
                if proxy_add_res and proxy_add_res.returncode == 0:
                    flash(f"🎉 [{app_info['title']}] 在容器 [{target_container}] 部署成功！\n"
                          f"👉 访问地址: http://{host_ip}:{web_port}\n"
                          f"🔌 映射端口: {web_port}")
                else:
                    flash(f"🎉 [{app_info['title']}] 部署成功，但外网端口映射绑定失败或端口冲突。")
            else:
                flash(f"❌ 部署失败: {res.stderr if res else '未知错误'}")
                
        return redirect(url_for('container_apps'))

    return render_template('apps.html', containers=containers, app_scripts=app_scripts)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
