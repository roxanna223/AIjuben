"""导演规划器（Route Director）：确定性代码，不调用AI。

职责：
1. 节拍调度 —— fixed 必走 / conditional 条件触发 / optional 倾向解锁；
   窗口错过的 conditional/optional 标记 skipped 并关闭其 grants 事实。
2. 结局池筛选 —— 引用已关闭事实、或阈值超出定义区间的结局标记为不可达。
3. 人物调度 —— 按节拍 cast + 好感度TOP2 给出场名单。
4. 收束模式 —— 结局池只剩1个时提示编剧回收伏笔（防烂尾）。
"""
from typing import Any, Dict, List, Optional

from . import conditions
from .state import WorldState
from .constitution import Constitution

KIND_PRIORITY = {"fixed": 0, "conditional": 1, "optional": 2}


class DirectorInstruction:
    def __init__(self, beat_id: Optional[str], must_happen: str = "",
                 characters_present: Optional[List[str]] = None,
                 notes: Optional[List[str]] = None,
                 ending_mode: bool = False, order: int = 0,
                 fact_hints: Optional[List[Dict[str, Any]]] = None):
        self.beat_id = beat_id
        self.must_happen = must_happen
        self.characters_present = characters_present or []
        self.notes = notes or []
        self.ending_mode = ending_mode
        self.order = order
        self.fact_hints = fact_hints or []

    def to_dict(self) -> Dict[str, Any]:
        return {"beat_id": self.beat_id, "must_happen": self.must_happen,
                "characters_present": self.characters_present,
                "notes": self.notes, "ending_mode": self.ending_mode,
                "fact_hints": self.fact_hints}


class RouteDirector:
    def __init__(self, constitution: Constitution, state: WorldState):
        self.c = constitution
        self.s = state

    # ---------- 节拍状态 ----------

    def _status(self, beat_id: str) -> str:
        st = self.s.beat_status.get(beat_id)
        return st["status"] if st else "pending"

    def _cursor(self) -> int:
        """游标 = 已进入终态（done/skipped/active）节拍的最大 order。"""
        cur = 0
        for b in self.c.beats:
            st = self._status(b["id"])
            if st in ("done", "skipped", "active"):
                cur = max(cur, b["order"])
        return cur

    def mark_done(self, beat_id: str) -> None:
        b = self.c.beat_index[beat_id]
        self.s.beat_status[beat_id] = {"status": "done", "turn": self.s.turn}
        self.s.log("beat_done", {"beat_id": beat_id})
        # 节拍完成 → 授予其grants事实（与Schema文档一致：grants在完成后生效）
        for f in b.get("grants", []):
            self.s.add_fact(f, "节拍%s完成" % beat_id)
        self._refresh_chapter()

    def _refresh_chapter(self) -> None:
        """章节 = 已完成的fixed节拍数 + 1；全部fixed完成后停在最后一章。"""
        done_fixed = sum(1 for b in self.c.beats
                         if b["kind"] == "fixed" and self._status(b["id"]) == "done")
        all_done = all(self._status(b["id"]) == "done"
                       for b in self.c.beats if b["kind"] == "fixed")
        self.s.chapter = done_fixed if all_done else done_fixed + 1

    def _skip(self, beat_id: str, why: str) -> None:
        b = self.c.beat_index[beat_id]
        for f in b.get("grants", []):
            self.s.close_fact(f)
        self.s.beat_status[beat_id] = {"status": "skipped", "turn": self.s.turn, "why": why}
        self.s.log("beat_skipped", {"beat_id": beat_id, "why": why})

    # ---------- 主入口 ----------

    def next_instruction(self) -> DirectorInstruction:
        self.refresh_endings_viable()

        # 全部 fixed 完成 → 无更多节拍（由流水线判定结局）
        fixed_done = all(self._status(b["id"]) == "done"
                         for b in self.c.beats if b["kind"] == "fixed")
        if fixed_done:
            return DirectorInstruction(beat_id=None, ending_mode=True)

        cursor = self._cursor()
        pending = [b for b in self.c.beats if self._status(b["id"]) == "pending"]
        if not pending:
            return DirectorInstruction(beat_id=None, ending_mode=True)
        next_order = min(b["order"] for b in pending)
        group = sorted([b for b in pending if b["order"] == next_order],
                       key=lambda b: (KIND_PRIORITY.get(b["kind"], 9), b["id"]))

        # 同order组内：先 fixed，再 conditional（条件满足），再 optional（解锁满足）
        for b in group:
            if b["kind"] == "fixed":
                return self._activate(b)
        for b in group:
            if b["kind"] == "conditional" and self._when_satisfied(b):
                return self._activate(b)
        for b in group:
            if b["kind"] == "optional" and self._unlock_satisfied(b):
                return self._activate(b)

        # 组内都不满足 → 跳过（关闭grants），递归处理下一组
        for b in group:
            why = "条件未满足" if b["kind"] == "conditional" else "倾向未解锁"
            self._skip(b["id"], why)
        return self.next_instruction()

    def _when_satisfied(self, b: Dict[str, Any]) -> bool:
        return conditions.check_condition(b.get("when"), self.s.facts,
                                          self.s.stats, self.s.tendencies)

    def _unlock_satisfied(self, b: Dict[str, Any]) -> bool:
        return conditions.check_condition(b.get("unlock"), self.s.facts,
                                          self.s.stats, self.s.tendencies)

    def _activate(self, b: Dict[str, Any]) -> DirectorInstruction:
        self.s.beat_status[b["id"]] = {"status": "active", "turn": self.s.turn}
        notes = []
        if b.get("constraints"):
            notes.append("硬约束: %s" % b["constraints"])
        ending_mode = len(self.s.endings_viable) <= 1
        if ending_mode:
            notes.append("收束模式：结局池已收敛，开始回收伏笔，准备收尾。")
        return DirectorInstruction(beat_id=b["id"], must_happen=b["must_happen"],
                                   characters_present=self._cast(b),
                                   notes=notes, ending_mode=ending_mode, order=b["order"],
                                   fact_hints=b.get("fact_hints", []))

    def _cast(self, b: Dict[str, Any]) -> List[str]:
        present = list(b.get("cast", []))
        if "pc" not in present:
            present.insert(0, "pc")
        # 好感度TOP2补充（跳过已在场的）
        affinities = [(sid, val) for sid, val in self.s.stats.items()
                      if sid in self.c.char_defs() and sid.startswith("trust_")]
        affinities.sort(key=lambda kv: -kv[1])
        for sid, _ in affinities[:2]:
            cid = sid.replace("trust_", "")
            if cid not in present and cid in self.c.char_index:
                present.append(cid)
        return present

    # ---------- 结局池 ----------

    def refresh_endings_viable(self) -> None:
        viable = []
        for e in self.c.endings:
            cond = e.get("conditions")
            if any(f in self.s.closed_facts for f in conditions.required_facts(cond)):
                continue
            if not conditions.stat_threshold_reachable(cond, self.c.char_defs(),
                                                       self.c.global_defs(), self.c.ten_dims()):
                continue
            viable.append(e["id"])
        if viable:
            self.s.endings_viable = viable
        # 空池兜底：保留上一轮结果，避免无结局可用

    def judge_ending(self) -> Optional[Dict[str, Any]]:
        """按宪法中结局声明顺序取第一个条件满足者。

        都不满足时返回"开放结局"（未尽的旅途），绝不把不满足条件的结局错标给玩家。
        """
        for e in self.c.endings:
            if conditions.check_condition(e.get("conditions"), self.s.facts,
                                          self.s.stats, self.s.tendencies):
                return e
        unresolved = {"id": "end_unresolved", "name": "未尽的旅途", "type": "open"}
        self.s.fallback_flags.append("ending_unresolved")
        self.s.log("ending_unresolved", {"endings_viable": list(self.s.endings_viable)})
        return unresolved
