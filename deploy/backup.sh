#!/bin/sh
# 每日备份「歧路」会话数据，保留最近 30 天
set -e
TS=$(date +%F)
DEST=/opt/qilu/backups
mkdir -p "$DEST"
tar czf "$DEST/sessions-$TS.tar.gz" -C /opt/qilu/ai-storyline data 2>/dev/null || true
find "$DEST" -name '*.tar.gz' -mtime +30 -delete
echo "[backup] $(date '+%F %T') -> $DEST/sessions-$TS.tar.gz"
