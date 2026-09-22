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
    
    for col, default_val in [
        ("os_type", "Linux"), 
        ("ssh_port", "NULL"), 
        ("cpu_limit", "1核"), 
        ("mem_limit", "512MB"), 
        ("disk_limit", "5GB")
    ]:
        try:
            cursor.execute(f"ALTER TABLE container_records ADD COLUMN {col} { 'INTEGER' if col=='ssh_port' else 'TEXT' } DEFAULT '{default_val}'")
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
            "status": status,
            "cpu_limit": info["cpu_limit"],
            "mem_limit": info["mem_limit"],
            "disk_limit": info["disk_limit"]
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
<label>容器名称 (TENANT_NAME): <small style="color:#666;">(3-16位字母数字下划线/中划线)</small></label>
<input type="text" name="tenant_name" placeholder="例如: mynode01" pattern="^[a-zA-Z0-9_-]{3,16}$" title="必须是3-16位的字母、数字、下划线或减号" required>
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
<label>CPU 核心限制:</label>
<select name="cpu_limit">
<option value="0.5核">0.5 核</option>
<option value="1核" selected>1 核</option>
<option value="2核">2 核</option>
<option value="4核">4 核</option>
</select>
</div>
<div>
<label>内存限制 (MEM_LIMIT):</label>
<select name="mem_limit">
<option value="512MB" selected>512 MB</option>
<option value="1024MB">1024 MB (1GB)</option>
<option value="2048MB">2048 MB (2GB)</option>
<option value="4096MB">4096 MB (4GB)</option>
</select>
</div>
<div>
<label>磁盘限制 (DISK_LIMIT):</label>
<select name="disk_limit">
<option value="5GB" selected>5 GB</option>
<option value="10GB">10 GB</option>
<option value="20GB">20 GB</option>
<option value="50GB">50 GB</option>
</select>
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
<th>资源配额 (CPU/MEM/Disk)</th>
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
<td><small><b>{{ c.cpu_limit }}</b> / <b>{{ c.mem_limit }}</b> / <b>{{ c.disk_limit }}</b></small></td>
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
      <a href="/container/terminal?name={{ c.tenant_name }}" target="_blank">🖥️ Web 终端</a>
      <a href="/container/reset_pwd?name={{ c.tenant_name }}" onclick="return confirm('确定要重置该容器的 Root 密码吗？')">🔑 重置密码</a>
      <a href="javascript:void(0);" onclick="openReinstallModal('{{ c.tenant_name }}')">⚡ 重装系统</a>
      <a href="javascript:void(0);" onclick="openMountModal('{{ c.tenant_name }}')">📁 挂载目录</a>
      <a href="/container/single_action?name={{ c.tenant_name }}&act=unmount">❌ 取消挂载</a>
      <a href="/container/single_action?name={{ c.tenant_name }}&act=destroy" style="color: red; font-weight: bold;" onclick="return confirm('警告：彻底销毁后数据将无法找回！确定操作吗？')">🗑️ 彻底销毁</a>
    </div>
  </div>
</td>
</tr>
{% else %}
<tr>
<td colspan="12" style="text-align: center; color: #888;">暂无容器记录，请展开上方【➕ 创建新容器】创建。</td>
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
            write_audit_log(username, "登录后台系统成功")
            return redirect(url_for('index'))
        else:
            flash("用户名或密码错误！")
            return render_template_string(LOGIN_TEMPLATE)
    return render_template_string(LOGIN_TEMPLATE)

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
            write_audit_log(session['user'], f"添加新租户: {new_username}")
            flash(f"🎉 成功添加新租户 [{new_username}]（密码: {new_password}，租户 ID: {auto_tid}）！数据已持久化。")
        except sqlite3.IntegrityError:
            flash(f"❌ 添加失败：用户名 [{new_username}] 已存在！")
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
    
    if session['user'] == 'admin' and assign_owner:
        target_owner = assign_owner
    else:
        target_owner = session['user']

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
                "REPLACE INTO container_records (container_name, owner, tenant_id, root_pass, os_type, ssh_port, cpu_limit, mem_limit, disk_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tenant_name, target_owner, int(tenant_id), parsed_root_pass, os_type, assigned_port, cpu_limit, mem_limit, disk_limit)
            )
            conn.commit()
            conn.close()
            time.sleep(0.5)
            write_audit_log(session['user'], f"成功创建容器: {tenant_name} (归属: {target_owner}, 规格: {cpu_limit}/{mem_limit}/{disk_limit})")
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
        elif act == 'destroy':
            res = run_incus(["delete", "--force", c_name], check=False, timeout=30)
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM container_records WHERE container_name = ?", (c_name,))
            conn.commit()
            conn.close()
            write_audit_log(session['user'], f"彻底销毁容器: {c_name}")
            flash(f"🗑️ 容器 [{c_name}] 已被彻底销毁！")
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
    
    # 动态启动一个针对该容器的 ttyd 进程，端口随机分配或通过子进程托管
    # 这里采用 xterm.js 网页嵌入 ttyd 的前端 iframe / 静态全屏页面方案
    # 或者直接重定向/动态分配端口执行 ttyd 
    # 为保证最轻量、不卡死，采用直接拉起 ttyd 绑定独立临时端口或者输出完整 Web 终端页面
    import socket
    def find_free_port():
        s = socket.socket()
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    ttyd_port = find_free_port()
    # 后台启动 ttyd 托管该容器的 incus shell
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
        flash("❌ 无权操作此容器！")
        return redirect(url_for('index'))
    
    new_pass = "P" + os.urandom(4).hex() + "8!"
    run_incus(["exec", c_name, "--", "sh", "-c", f"echo 'root:{new_pass}' | chpasswd"], check=False)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE container_records SET root_pass = ? WHERE container_name = ?", (new_pass, c_name))
    conn.commit()
    conn.close()
    
    write_audit_log(session['user'], f"重置容器 Root 密码: {c_name}")
    flash(f"🔑 容器 [{c_name}] 的 Root 密码已重置成功为: {new_pass}")
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
            write_audit_log(session['user'], f"挂载目录到容器 {c_name}: Host({host_path}) -> Container({container_path})")
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
        cmd = ["create_lxd.sh", c_name, os_type, tenant_id, rec['mem_limit'], rec['disk_limit']]
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        output = process.stdout + process.stderr
        ssh_user = "admin" if os_type in ["ub24", "debian13"] else "root"
        user_match = re.search(r"登录用户\s*[:：]\s*([A-Za-z0-9_-]+)", output, re.IGNORECASE)
        if user_match:
            ssh_user = user_match.group(1)
            
        pass_match = re.search(r"(?:Root\s*密码|登录密码)\s*:[^\s]+", output, re.IGNORECASE)
        parsed_root_pass = pass_match.group(1) if pass_match else "123456"

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
            "REPLACE INTO container_records (container_name, owner, tenant_id, root_pass, os_type, ssh_port, cpu_limit, mem_limit, disk_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (c_name, rec['owner'], int(tenant_id), parsed_root_pass, os_type, old_port, rec['cpu_limit'], rec['mem_limit'], rec['disk_limit'])
        )
        conn.commit()
        conn.close()

        write_audit_log(session['user'], f"重装容器系统: {c_name} -> {os_type}")
        flash(f"⚡ 容器 [{c_name}] 系统已成功重装为 [{os_type}]！")
    except Exception as e:
        flash(f"❌ 系统重装失败: {str(e)}")

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
