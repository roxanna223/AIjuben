"""「歧路」Web API（FastAPI）· 多剧本支持。

运行：
  .venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8000
环境变量：
  STORY_MODE=mock|llm     # 默认 mock（无需API Key）
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL   # llm 模式配置
  ADMIN_TOKEN             # 管理接口令牌（/api/admin/* 需 X-Admin-Token 头）
  RATE_LIMIT_PER_MIN / RATE_TURN_PER_MIN   # 每IP每分钟限流（默认 60 / 20）
  QILU_EVENTS_FILE / EVENT_SALT            # 行为事件采集（默认 data/events.jsonl）
"""
import asyncio
import json
import os
import queue
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.constitution import Constitution
from engine.state import WorldState
from engine.pipeline import Pipeline, build_provider
from engine.llm import LLMError
import metrics
from server import events

BASE = Path(__file__).resolve().parent.parent
STORIES = BASE / "stories"
DATA_DIR = BASE / "data" / "sessions"
MODE = os.environ.get("STORY_MODE", "mock")

app = FastAPI(title="歧路 · AI互动叙事引擎")

# 内存驻留上限：超出后淘汰最久未使用的会话（状态已落盘，可随时读回），
# 避免长文本 + 大量历史会话把小内存机器吃爆。可用 MAX_MEM_SESSIONS 环境变量调整。
MAX_MEM_SESSIONS = int(os.environ.get("MAX_MEM_SESSIONS", "256"))
SESSIONS: "OrderedDict[str, Pipeline]" = OrderedDict()
_cache_c: Dict[str, Constitution] = {}
_cache_p: Dict[Any, Any] = {}

# ---- 安全与采集配置 ----
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")            # 管理接口令牌；空=管理接口关闭
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))   # API 每IP每分钟
RATE_TURN_PER_MIN = int(os.environ.get("RATE_TURN_PER_MIN", "20"))     # 回合接口从严
RATE_CREATE_PER_MIN = int(os.environ.get("RATE_CREATE_PER_MIN", "20")) # 开局接口从严(防连点刷开局烧token)
_rate_hits: Dict[str, List[float]] = {}
_rate_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _rate_ok(ip: str, limit: int) -> bool:
    """滑动窗口限流：每IP每分钟最多 limit 次。"""
    if limit <= 0:
        return True
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate_hits.get(ip, []) if now - t < 60.0]
        if len(hits) >= limit:
            _rate_hits[ip] = hits
            return False
        hits.append(now)
        _rate_hits[ip] = hits
        if len(_rate_hits) > 5000:  # 防内存膨胀：清理空条目
            for k in [k for k, v in _rate_hits.items() if not v]:
                _rate_hits.pop(k, None)
    return True


def _admin_ok(request: Request) -> bool:
    return bool(ADMIN_TOKEN) and \
        request.headers.get("X-Admin-Token", "") == ADMIN_TOKEN


def _remember(p: Pipeline) -> None:
    """把会话放进内存并维持上限：最新访问挪到末尾，超限时从最旧开始淘汰。"""
    sid = p.state.session_id
    if sid in SESSIONS:
        SESSIONS.move_to_end(sid)
        return
    SESSIONS[sid] = p
    while len(SESSIONS) > MAX_MEM_SESSIONS:
        _old_sid, old = SESSIONS.popitem(last=False)
        try:
            _persist(old.state)  # 淘汰前确保落盘
        except Exception:  # noqa: BLE001
            pass

# 启动时扫描剧本注册表（剧本宪法文件，排除 mock 脚本）
STORY_REGISTRY: Dict[str, Path] = {}
for _p in sorted(STORIES.glob("*.json")):
    if _p.name.endswith(".mock.json"):
        continue
    try:
        _c = Constitution.load(str(_p))
        STORY_REGISTRY[_c.story_id] = _p
    except Exception as e:  # noqa: BLE001
        print("[warn] 剧本加载失败 %s: %s" % (_p.name, e))

DEFAULT_STORY = "midnight-train" if "midnight-train" in STORY_REGISTRY \
    else (next(iter(STORY_REGISTRY), ""))


@app.middleware("http")
async def security_and_analytics(request: Request, call_next):
    """安全与埋点统一入口：IP 限流 + 首页访问埋点。"""
    ip = _client_ip(request)
    path = request.url.path
    if path.startswith("/api"):
        if path.rstrip("/") == "/api/sessions":
            limit = RATE_CREATE_PER_MIN     # 开局接口独立从严:防止连点重复开局
        elif path.rstrip("/").endswith("/turn"):
            limit = RATE_TURN_PER_MIN
        else:
            limit = RATE_LIMIT_PER_MIN
        if not _rate_ok(ip, limit):
            return JSONResponse(status_code=429,
                                content={"detail": "请求过于频繁，请稍后再试"})
    if request.method == "GET" and path in ("/", "/index.html"):
        events.record_event("page_view", ip=ip,
                            ua=request.headers.get("user-agent", ""), path=path)
    return await call_next(request)


def _story_path(story_id: str) -> Path:
    p = STORY_REGISTRY.get(story_id)
    if p is None:
        raise HTTPException(status_code=404, detail="剧本不存在: %s" % story_id)
    return p


def _load_constitution(story_id: str) -> Constitution:
    if story_id not in _cache_c:
        _cache_c[story_id] = Constitution.load(str(_story_path(story_id)))
    return _cache_c[story_id]


def _mock_path(story_id: str) -> str:
    return str(_story_path(story_id).with_name(story_id + ".mock.json"))


def _load_provider(story_id: str):
    key = (MODE, story_id)
    if key not in _cache_p:
        if MODE == "llm":
            try:
                _cache_p[key] = build_provider("llm")
            except LLMError as e:
                print("[warn] LLM不可用，回退Mock模式: %s" % e)
                _cache_p[key] = build_provider("mock", _mock_path(story_id))
        else:
            _cache_p[key] = build_provider("mock", _mock_path(story_id))
    return _cache_p[key]


def _new_session(story_id: str) -> Pipeline:
    c = _load_constitution(story_id)
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims(),
                       session_id="s_" + uuid.uuid4().hex[:8])
    return Pipeline(c, _load_provider(story_id), state)


def _get_pipeline(sid: str) -> Pipeline:
    if sid in SESSIONS:
        SESSIONS.move_to_end(sid)  # 刷新最近使用，避免被淘汰
        return SESSIONS[sid]
    f = DATA_DIR / ("%s.json" % sid)
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        c = _load_constitution(d.get("story_id") or DEFAULT_STORY)
        state = WorldState.from_dict(d)
        p = Pipeline(c, _load_provider(state.story_id), state)
        _remember(p)  # 从磁盘读回并纳入LRU管理
        return p
    raise HTTPException(status_code=404, detail="会话不存在: %s" % sid)


def _persist(state: WorldState) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / ("%s.json" % state.session_id)).write_text(state.dumps(), encoding="utf-8")


def _stat_defs(c: Constitution) -> Dict[str, Dict]:
    """数值定义（含标签/区间），供前端渲染动态数值条。"""
    defs: Dict[str, Dict] = {}
    for sid, d in {**c.char_defs(), **c.global_defs()}.items():
        defs[sid] = {"label": d.get("label", sid), "min": d["min"], "max": d["max"]}
    for t in c.ten_dims():
        defs[t] = {"label": t, "min": -1, "max": 1}
    return defs


def _history(state: WorldState) -> list:
    """把三层记忆的recent场景与事件账本的选择按回合配对，重建可渲染的历史时间线。"""
    scenes = state.memory.get("recent", [])
    choices = [e for e in state.event_log if e["type"] == "choice"]
    out = []
    for i, sc in enumerate(scenes):
        out.append({"kind": "narr", "turn": sc.get("turn"), "text": sc.get("narrative", "")})
        lo = sc.get("turn", 0)
        hi = scenes[i + 1].get("turn", 10 ** 9) if i + 1 < len(scenes) else 10 ** 9
        for ch in choices:
            if lo < ch.get("turn", 0) <= hi:
                out.append({"kind": "choice", "turn": ch.get("turn"),
                            "text": (ch.get("payload") or {}).get("choice", "")})
    return out


def _session_view(state: WorldState, scene: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = _load_constitution(state.story_id)
    return {
        "sid": state.session_id,
        "story": {"id": state.story_id, "title": c.title, "genre": c.genre},
        "finished": state.finished,
        "ending": state.ending,
        "chapter": state.chapter,
        "turn": state.turn,
        "stats": state.stats,
        "tendencies": state.tendencies,
        "stat_defs": _stat_defs(c),
        "facts": sorted(state.facts),
        "closed_facts": sorted(state.closed_facts),
        "beat_path": [b for b, st in sorted(state.beat_status.items(),
                                            key=lambda kv: kv[1].get("turn", 0))
                      if st["status"] == "done"],
        "history": _history(state),
        "scene": scene if not state.finished else None,
    }


class CreateIn(BaseModel):
    story_id: str = "midnight-train"


class TurnIn(BaseModel):
    choice_index: Optional[int] = None
    free_text: str = ""


@app.get("/api/stories")
def list_stories(request: Request):
    events.record_event("stories_view", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""))
    out = []
    for story_id, p in STORY_REGISTRY.items():
        try:
            c = _load_constitution(story_id)
            out.append({
                "id": c.story_id, "title": c.title, "genre": c.genre,
                "desc": c.world.get("setting", ""),
                "endings": len(c.endings), "chapters": c.chapter_plan.get("target_chapters"),
            })
        except Exception:  # noqa: BLE001
            continue
    return out


@app.post("/api/sessions")
def create_session(request: Request, body: Optional[CreateIn] = None):
    story_id = body.story_id if body else DEFAULT_STORY
    p = _new_session(story_id)
    scene = p.start()
    _remember(p)
    _persist(p.state)
    events.record_event("session_create", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""),
                        story=story_id, sid=p.state.session_id)
    return _session_view(p.state, scene)


@app.post("/api/sessions/{sid}/turn")
async def play_turn(sid: str, body: TurnIn, request: Request):
    p = _get_pipeline(sid)
    if p.state.finished:
        return _session_view(p.state, None)
    accept = request.headers.get("accept", "")
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")

    def _record_turn(state: WorldState) -> None:
        events.record_event("turn", ip=ip, ua=ua, sid=state.session_id,
                            story=state.story_id, turn=state.turn,
                            choice=body.choice_index is not None,
                            free_len=len(body.free_text or ""),
                            finished=state.finished,
                            ending=(state.ending or {}).get("id"))

    # NDJSON 流式：生成跑在独立线程，正文增量经队列实时推给前端
    if "ndjson" in accept:
        q: "queue.Queue" = queue.Queue()

        def on_chunk(text: str) -> None:
            q.put(("delta", text))

        def work() -> None:
            try:
                scene = p.turn(choice_index=body.choice_index,
                               free_text=body.free_text, on_chunk=on_chunk)
                _persist(p.state)
                _record_turn(p.state)
                q.put(("done", _session_view(p.state, scene)))
            except (ValueError, RuntimeError) as e:
                q.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

        async def gen():
            while True:
                kind, payload = await asyncio.to_thread(q.get)
                if kind == "delta":
                    yield json.dumps({"type": "delta", "text": payload},
                                     ensure_ascii=False) + "\n"
                elif kind == "done":
                    yield json.dumps({"type": "done", "view": payload},
                                     ensure_ascii=False) + "\n"
                    break
                else:
                    yield json.dumps({"type": "error", "detail": payload},
                                     ensure_ascii=False) + "\n"
                    break

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    # 兼容：非流式JSON
    try:
        scene = p.turn(choice_index=body.choice_index, free_text=body.free_text)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    _persist(p.state)
    _record_turn(p.state)
    return _session_view(p.state, scene)


@app.get("/api/sessions/{sid}")
def get_session(sid: str, request: Request):
    p = _get_pipeline(sid)
    events.record_event("session_view", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""),
                        sid=sid, story=p.state.story_id)
    return _session_view(p.state, p.state.current_scene)


@app.get("/api/sessions/{sid}/recap")
def get_recap(sid: str, request: Request):
    p = _get_pipeline(sid)
    events.record_event("recap_view", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""),
                        sid=sid, story=p.state.story_id)
    s = p.state
    c = _load_constitution(s.story_id)
    choices = [{"turn": e["turn"], "choice": (e.get("payload") or {}).get("choice", "")}
               for e in s.event_log if e["type"] == "choice"]
    beats = [{"beat_id": b, "turn": st.get("turn")}
             for b, st in sorted(s.beat_status.items(), key=lambda kv: kv[1].get("turn", 0))]
    # 路线图数据：按宪法节拍顺序全量展示（含跳过/未达），供前端绘制节点图
    route = []
    for b in sorted(c.beats, key=lambda x: x["order"]):
        st = s.beat_status.get(b["id"], {})
        route.append({
            "beat_id": b["id"], "order": b["order"], "kind": b["kind"],
            "must_happen": b.get("must_happen", ""),
            "status": st.get("status", "pending"),
            "turn": st.get("turn"),
            "skip_reason": st.get("why", ""),
        })
    return {
        "sid": s.session_id,
        "story": {"id": s.story_id, "title": c.title},
        "finished": s.finished,
        "ending": s.ending,
        "beats": beats,
        "route": route,
        "stats": s.stats,
        "tendencies": s.tendencies,
        "facts": sorted(s.facts),
        "choices": choices,
        "fallback_flags": s.fallback_flags,
        "event_count": len(s.event_log),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "mode": MODE, "stories": len(STORY_REGISTRY)}


@app.get("/api/admin/metrics")
def admin_metrics(request: Request, story_id: Optional[str] = None):
    """体验基线指标（对标调研基线）；story_id 缺省统计全部剧本。
    需要 X-Admin-Token 请求头（ADMIN_TOKEN 环境变量配置）。"""
    if not _admin_ok(request):
        raise HTTPException(status_code=403, detail="管理接口需要 X-Admin-Token")
    events.record_event("admin_metrics", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""))
    sessions = metrics.load_sessions(str(DATA_DIR), story_id=story_id)
    m = metrics.compute_metrics(sessions)
    m["verdict"] = metrics.verdict(m)
    m["story_id"] = story_id
    return m


@app.get("/api/admin/events")
def admin_events(request: Request, limit: int = 100,
                 action: Optional[str] = None):
    """最近玩家行为事件(新→旧)。需要 X-Admin-Token 请求头。"""
    if not _admin_ok(request):
        raise HTTPException(status_code=403, detail="管理接口需要 X-Admin-Token")
    events.record_event("admin_events", ip=_client_ip(request),
                        ua=request.headers.get("user-agent", ""))
    limit = max(1, min(limit, 500))
    rows = events.read_recent(500)
    if action:
        rows = [r for r in rows if r.get("action") == action]
    return {"count": len(rows[:limit]), "events": rows[:limit]}


# 静态前端（最后挂载，避免遮蔽API路由）
app.mount("/", StaticFiles(directory=str(BASE / "server" / "static"), html=True), name="static")
