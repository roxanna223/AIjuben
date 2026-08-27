"""玩家行为事件采集(生产数据)。

每个请求追加一条 JSON 到 data/events.jsonl,供产品/运营分析:
  {"ts": 时间戳, "ip_h": IP加盐哈希(脱敏), "ua": User-Agent截断,
   "action": 事件类型, "meta": 附加信息}

安全设计:
- 不落原始IP,用 EVENT_SALT 加盐 SHA-256 截断,同人可聚合、无法反查;
- 采集失败静默吞掉,绝不影响业务请求;
- 事件类型: page_view / stories_view / session_create / turn /
  session_view / recap_view / admin_metrics / admin_events
"""
import hashlib
import json
import os
import threading
import time

EVENTS_FILE = os.environ.get("QILU_EVENTS_FILE", "data/events.jsonl")
_SALT = os.environ.get("EVENT_SALT", "qilu-default-salt")
_lock = threading.Lock()


def hash_ip(ip: str) -> str:
    """IP 加盐哈希(截断16位),既支持去重统计又不暴露隐私。"""
    return hashlib.sha256(("%s|%s" % (_SALT, ip)).encode("utf-8")).hexdigest()[:16]


def record_event(action: str, ip: str = "", ua: str = "", **meta) -> None:
    """追加一条事件。所有异常吞掉:埋点失败不能影响游戏。"""
    try:
        ev = {
            "ts": time.time(),
            "ip_h": hash_ip(ip) if ip else "",
            "ua": (ua or "")[:120],
            "action": action,
        }
        if meta:
            ev["meta"] = meta
        line = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
        with _lock:
            with open(EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def read_recent(limit: int = 100) -> list:
    """读取最近 limit 条事件(新→旧)。"""
    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out
