# 「歧路」服务器部署说明

## 目录结构(服务器 /opt/qilu)

```
/opt/qilu/
├── ai-storyline/          # 项目代码(含 .venv、.env、data/)
├── deploy/                # 安装脚本与配置(install.sh / qilu.service / nginx-qilu.conf)
├── backups/               # 每日会话数据备份(sessions-YYYY-MM-DD.tar.gz,保留30天)
└── backup.sh              # 备份脚本(cron 每天 3:15 执行)
```

## 关键路径与命令

| 事项 | 命令 |
|---|---|
| 应用日志 | `journalctl -u qilu -f` |
| 重启应用 | `systemctl restart qilu` |
| 健康检查 | `curl http://127.0.0.1:8000/api/health` |
| nginx 日志 | `tail -f /var/log/nginx/access.log` |
| 手动备份 | `/opt/qilu/backup.sh` |
| 恢复备份 | `tar xzf backups/sessions-某天.tar.gz -C /opt/qilu/ai-storyline/` |

## 更新代码流程

1. 本地改完代码,打包上传(排除 .venv/.env/data):
   `tar czf - ai-storyline | ssh root@<IP> "tar xzf - -C /opt/qilu"`
2. 若依赖有变化: `ssh root@<IP> "/opt/qilu/ai-storyline/.venv/bin/pip install -r /opt/qilu/ai-storyline/requirements.txt"`
3. 重启: `ssh root@<IP> "systemctl restart qilu"`

## 内存保护设计(2G 内存方案)

- `MAX_MEM_SESSIONS=256`:内存最多驻留 256 个会话,超出淘汰最久未用(状态已落盘,访问时自动读回);
- 2G swap 兜底,避免内存耗尽进程被杀;
- 单 worker 运行,uvicorn 线程池处理并发(请求多为等待 LLM 返回的 I/O)。

## 备份/恢复要点

- 每日备份 `data/`(会话 JSON + 用量日志);
- 恢复时停止服务更稳妥:`systemctl stop qilu && tar xzf ... && systemctl start qilu`。

## 运维注意

- **API Key 成本**:DeepSeek 按 token 计费,定期看 `data/usage.jsonl` 和 DeepSeek 平台余额;
- **安全组**:入方向需放行 22/80/443;若加域名且走 443,需备案并补 HTTPS 证书(Let's Encrypt);
- **到期提醒**:0 元练手实例 1 年到期,续费前先确认备份完整。

## 上线检查单(部署完成后照做)

1. **放行 80 端口**(不放开公网访问不到):
   ECS 控制台 → 实例 → 点实例名进详情 → **安全组** 页签 → 点安全组ID →
   **入方向 → 手动添加**:
   - 授权策略:允许 / 优先级:1 / 协议:TCP / 端口范围:80/80 / 授权对象:0.0.0.0/0
   - 如需 HTTPS 再加一条 443/443
2. **浏览器验证**:访问 `http://公网IP/` → 看到「歧路」页面;
3. **玩一局验证**:开一局点几下 → 服务器 `ls /opt/qilu/ai-storyline/data/sessions/` 能看到新会话 JSON;
4. **跑一次备份**:`/opt/qilu/backup.sh`,确认 `/opt/qilu/backups/` 出现 tar.gz;
5. **改 root 密码**(可选):`passwd root`,换成只自己知道的密码,并删除本机 `deploy/ssh_keys/askpass.sh` 里的旧密码。
