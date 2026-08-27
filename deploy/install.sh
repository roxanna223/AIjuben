#!/bin/sh
# 「歧路」一键安装脚本（在服务器上以 root 执行）
# 用法：sh /opt/qilu/deploy/install.sh
set -e

APP=/opt/qilu/ai-storyline

echo "==> [1/6] 安装 Python 3.11（Alinux3 自带 3.6 太老）"
if ! command -v python3.11 >/dev/null 2>&1; then
    dnf install -y python3.11 python3.11-pip || dnf install -y python39 python39-pip
fi
if command -v python3.11 >/dev/null 2>&1; then PY=python3.11; else PY=python3.9; fi
echo "    using $($PY --version)"

echo "==> [2/6] 创建 venv 并安装依赖"
cd "$APP"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> [3/6] 安装并配置 nginx 反向代理"
if ! command -v nginx >/dev/null 2>&1; then
    dnf install -y nginx
fi
cp /opt/qilu/deploy/nginx-qilu.conf /etc/nginx/conf.d/qilu.conf
rm -f /etc/nginx/conf.d/default.conf
systemctl enable nginx
systemctl restart nginx || systemctl start nginx

echo "==> [4/6] 注册 systemd 服务（开机自启）"
cp /opt/qilu/deploy/qilu.service /etc/systemd/system/qilu.service
systemctl daemon-reload
systemctl enable qilu
systemctl restart qilu

echo "==> [5/6] 配置 2G swap（内存兜底）"
if ! swapon --show 2>/dev/null | grep -q swap; then
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "    swap 2G enabled"
else
    echo "    swap 已存在，跳过"
fi

echo "==> [6/6] 每日备份（凌晨 3:15，保留 30 天）"
mkdir -p /opt/qilu/backups
cp /opt/qilu/deploy/backup.sh /opt/qilu/backup.sh
chmod +x /opt/qilu/backup.sh
printf '15 3 * * * root /opt/qilu/backup.sh >> /opt/qilu/backups/backup.log 2>&1\n' > /etc/cron.d/qilu-backup
chmod 644 /etc/cron.d/qilu-backup

echo ""
echo "===== 安装完成 ====="
systemctl status qilu --no-pager | head -6
curl -s http://127.0.0.1:8000/api/health && echo "" || echo "[warn] 应用健康检查未通过，看上面日志"
