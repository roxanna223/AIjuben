#!/bin/sh
# 「歧路」一键部署(在本机 Mac 上执行)
# 用法: sh deploy/deploy.sh <服务器公网IP>
# 流程: 首次用 root 密码登录装公钥(askpass 免交互)→ 免密上传 → 安装 → 验证
set -e
HOST="${1:?用法: sh deploy/deploy.sh <公网IP>}"
cd "$(dirname "$0")/.."   # 进入工作区根目录(路径含空格,必须用相对路径)

KEY=deploy/ssh_keys/id_qilu
ASK=deploy/ssh_keys/askpass.sh
KH=/tmp/qilu_known_hosts
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KH -o ConnectTimeout=20"
KEY_SSH="ssh $SSH_OPTS -i $KEY root@$HOST"

echo "==> [1/5] 用 root 密码登录并安装免密公钥(仅此一次需要密码)"
DISPLAY=none SSH_ASKPASS="$ASK" SSH_ASKPASS_REQUIRE=force \
  ssh $SSH_OPTS -o PreferredAuthentications=password,keyboard-interactive \
  -o NumberOfPasswordPrompts=3 \
  root@$HOST "mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qF 'qilu-server@roxanna223' ~/.ssh/authorized_keys 2>/dev/null || cat >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys" < "$KEY.pub"
echo "    [ok] 公钥已安装"

echo "==> [2/5] 验证免密登录"
$KEY_SSH 'echo "    [ok] 免密登录成功: $(hostname) / $(uname -r)"'

echo "==> [3/5] 打包并上传代码与部署配置"
PKG=/tmp/qilu_pkg
rm -rf "$PKG" && mkdir -p "$PKG"
tar czf "$PKG/ai-storyline.tar.gz" \
  --exclude='.venv' --exclude='.env' --exclude='data' \
  --exclude='__pycache__' --exclude='.DS_Store' --exclude='._*' ai-storyline
tar czf "$PKG/deploy.tar.gz" \
  --exclude='ssh_keys' --exclude='env.server' --exclude='run_remote.exp' --exclude='._*' deploy
scp $SSH_OPTS -i "$KEY" "$PKG/ai-storyline.tar.gz" "$PKG/deploy.tar.gz" root@$HOST:/tmp/
scp $SSH_OPTS -i "$KEY" deploy/env.server root@$HOST:/tmp/env.server
$KEY_SSH 'mkdir -p /opt/qilu \
  && tar xzf /tmp/ai-storyline.tar.gz -C /opt/qilu \
  && tar xzf /tmp/deploy.tar.gz -C /opt/qilu \
  && cp /tmp/env.server /opt/qilu/ai-storyline/.env \
  && chmod 600 /opt/qilu/ai-storyline/.env \
  && chmod +x /opt/qilu/deploy/install.sh /opt/qilu/deploy/backup.sh \
  && rm -f /tmp/ai-storyline.tar.gz /tmp/deploy.tar.gz /tmp/env.server \
  && echo "    [ok] 代码已就位: $(ls /opt/qilu)"'

echo "==> [4/5] 执行安装(约 2~5 分钟)"
$KEY_SSH 'sh /opt/qilu/deploy/install.sh'

echo "==> [5/5] 验证服务"
$KEY_SSH 'curl -s http://127.0.0.1:8000/api/health; echo; curl -s -o /dev/null -w "nginx: HTTP %{http_code}\n" http://127.0.0.1/'

echo ""
echo "===== 部署完成 ====="
echo "下一步: 阿里云控制台安全组放行 80 端口后,浏览器访问 http://$HOST/ 即可"
