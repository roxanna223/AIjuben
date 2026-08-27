"""世界状态（WorldState）：单局内的全部动态数据。"""
import json
import time
from typing import Any, Dict, List, Optional


class WorldState:
    def __init__(self, story_id: str, char_defs: Dict[str, Dict], global_defs: Dict[str, Dict],
                 ten_dims: List[str], session_id: str = "s_000"):
        self.session_id = session_id
        self.story_id = story_id
        self.turn = 0
        self.chapter = 1
        self.started_at = time.time()
        self.last_active_at = self.started_at
        self.stats: Dict[str, float] = {}
        for sid, d in char_defs.items():
            self.stats[sid] = float(d["initial"])
        for sid, d in global_defs.items():
            self.stats[sid] = float(d["initial"])
        self.tendencies: Dict[str, float] = {t: 0.0 for t in ten_dims}
        self.facts: set = set()
        self.closed_facts: set = set()
        self.beat_status: Dict[str, Dict] = {}   # beat_id -> {status, turn}
        self.endings_viable: List[str] = []
        self.memory: Dict[str, Any] = {"recent": [], "chapter_summary": [], "global_summary": []}
        self.event_log: List[Dict[str, Any]] = []
        self.current_scene: Optional[Dict[str, Any]] = None
        self.finished = False
        self.ending: Optional[Dict[str, Any]] = None
        self.fallback_flags: List[str] = []  # 生成降级标记（评测用）

    # ---------- 数值 ----------

    def apply_stat(self, target: str, delta: float, bounds: Dict[str, float],
                   reason: str = "") -> float:
        lo, hi = bounds["min"], bounds["max"]
        old = self.stats[target]
        self.stats[target] = max(lo, min(hi, old + delta))
        self.event_log.append({"turn": self.turn, "type": "stat",
                               "payload": {"target": target, "delta": delta,
                                           "from": old, "to": self.stats[target], "reason": reason}})
        return self.stats[target]

    def apply_tendency(self, dim: str, delta: float) -> float:
        old = self.tendencies[dim]
        self.tendencies[dim] = max(-1.0, min(1.0, old + delta))
        self.event_log.append({"turn": self.turn, "type": "tendency",
                               "payload": {"dim": dim, "delta": delta,
                                           "from": old, "to": self.tendencies[dim]}})
        return self.tendencies[dim]

    def add_fact(self, fact_id: str, text: str = "") -> None:
        if fact_id not in self.facts:
            self.facts.add(fact_id)
            self.event_log.append({"turn": self.turn, "type": "fact",
                                   "payload": {"id": fact_id, "text": text}})

    def close_fact(self, fact_id: str) -> None:
        self.closed_facts.add(fact_id)
        self.event_log.append({"turn": self.turn, "type": "close_fact",
                               "payload": {"id": fact_id}})

    def log(self, etype: str, payload: Dict[str, Any]) -> None:
        self.event_log.append({"turn": self.turn, "type": etype, "payload": payload})

    # ---------- 记忆 ----------

    def push_scene(self, scene: Dict[str, Any]) -> None:
        self.memory["recent"].append({"turn": self.turn,
                                      "beat": scene.get("scene_meta", {}).get("beat_id"),
                                      "narrative": scene.get("narrative", ""),
                                      "facts": [u for u in scene.get("world_updates", []) if u.get("type") == "fact"]})
        if len(self.memory["recent"]) > 10:
            self.memory["recent"] = self.memory["recent"][-10:]

    def compress_scene(self, text: str) -> None:
        """占位摘要（Phase 0）：真实实现为LLM摘要，见架构文档第3节。"""
        self.memory["chapter_summary"].append(text[:120])
        if len(self.memory["chapter_summary"]) > 8:
            self.memory["chapter_summary"] = self.memory["chapter_summary"][-8:]

    # ---------- 序列化 ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "story_id": self.story_id,
            "turn": self.turn, "chapter": self.chapter,
            "started_at": self.started_at, "last_active_at": self.last_active_at,
            "stats": dict(self.stats), "tendencies": dict(self.tendencies),
            "facts": sorted(self.facts), "closed_facts": sorted(self.closed_facts),
            "beat_status": dict(self.beat_status), "endings_viable": list(self.endings_viable),
            "memory": self.memory, "event_log": self.event_log,
            "current_scene": self.current_scene,
            "finished": self.finished, "ending": self.ending,
            "fallback_flags": self.fallback_flags,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "WorldState":
        """从持久化JSON恢复（用于断线续玩）。"""
        s = WorldState.__new__(WorldState)
        s.session_id = d.get("session_id", "s_000")
        s.story_id = d["story_id"]
        s.turn = d.get("turn", 0)
        s.chapter = d.get("chapter", 1)
        s.started_at = d.get("started_at") or time.time()
        s.last_active_at = d.get("last_active_at") or s.started_at
        s.stats = dict(d.get("stats", {}))
        s.tendencies = dict(d.get("tendencies", {}))
        s.facts = set(d.get("facts", []))
        s.closed_facts = set(d.get("closed_facts", []))
        s.beat_status = dict(d.get("beat_status", {}))
        s.endings_viable = list(d.get("endings_viable", []))
        s.memory = d.get("memory") or {"recent": [], "chapter_summary": [], "global_summary": []}
        s.event_log = list(d.get("event_log", []))
        s.current_scene = d.get("current_scene")
        s.finished = bool(d.get("finished", False))
        s.ending = d.get("ending")
        s.fallback_flags = list(d.get("fallback_flags", []))
        return s

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
