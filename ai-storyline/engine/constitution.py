"""剧本宪法（StoryConstitution）：加载与校验。"""
import json
from typing import Any, Dict, List

from . import conditions

REQUIRED_TOP = ["story_id", "title", "world", "characters", "beats", "endings", "stats"]

BEAT_KINDS = {"fixed", "conditional", "optional"}


class ConstitutionError(ValueError):
    pass


class Constitution:
    """剧本宪法：静态规则包。发布时定稿，一局内不变。"""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw
        self.story_id: str = raw["story_id"]
        self.title: str = raw["title"]
        self.genre: List[str] = raw.get("genre", [])
        self.world: Dict[str, Any] = raw.get("world", {})
        self.characters: List[Dict[str, Any]] = raw.get("characters", [])
        self.beats: List[Dict[str, Any]] = raw.get("beats", [])
        self.endings: List[Dict[str, Any]] = raw.get("endings", [])
        self.stats: Dict[str, Any] = raw.get("stats", {})
        self.chapter_plan: Dict[str, Any] = raw.get("chapter_plan", {})
        # 便捷索引
        self.char_index: Dict[str, Dict] = {c["id"]: c for c in self.characters}
        self.beat_index: Dict[str, Dict] = {b["id"]: b for b in self.beats}
        # 事实清单 = 宪法声明的facts + 各节拍grants（去重）
        declared = {f["id"]: f.get("desc", f["id"]) for f in raw.get("facts", [])}
        for b in self.beats:
            for f in b.get("grants", []):
                declared.setdefault(f, b.get("must_happen", f))
        self.facts_catalog: Dict[str, str] = declared

    # ---------- 加载与校验 ----------

    @staticmethod
    def load(path: str) -> "Constitution":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return Constitution.validate(raw)

    @staticmethod
    def validate(raw: Dict[str, Any]) -> "Constitution":
        def fail(msg: str):
            raise ConstitutionError("剧本宪法校验失败: " + msg)

        for k in REQUIRED_TOP:
            if k not in raw:
                fail("缺少顶层字段 %s" % k)

        # 数值定义
        char_defs = raw["stats"].get("characters", {})
        global_defs = raw["stats"].get("global", {})
        ten_dims = raw["stats"].get("tendencies", [])
        if not isinstance(ten_dims, list) or not ten_dims:
            fail("stats.tendencies 必须是非空数组")
        for group_name, group in (("characters", char_defs), ("global", global_defs)):
            for sid, d in group.items():
                for k in ("min", "max", "initial"):
                    if k not in d:
                        fail("stats.%s.%s 缺少字段 %s" % (group_name, sid, k))
                if not (d["min"] <= d["initial"] <= d["max"]):
                    fail("stats.%s.%s 初始值不在[min,max]内" % (group_name, sid))

        # 人物
        char_ids = [c["id"] for c in raw["characters"]]
        if "pc" not in char_ids:
            fail("characters 必须包含主角 id=pc")
        if len(char_ids) != len(set(char_ids)):
            fail("character id 重复")

        # 节拍
        seen = set()
        seen_grants = set()
        for b in raw["beats"]:
            if b.get("kind") not in BEAT_KINDS:
                fail("beat %s 的 kind 非法: %r" % (b.get("id"), b.get("kind")))
            if b["id"] in seen:
                fail("beat id 重复: %s" % b["id"])
            seen.add(b["id"])
            if "order" not in b:
                fail("beat %s 缺少 order" % b["id"])
            if b.get("kind") != "fixed" and ("when" if b["kind"] == "conditional" else "unlock") not in b:
                fail("beat %s 缺少触发条件" % b["id"])
            if not b.get("must_happen"):
                fail("beat %s 缺少 must_happen" % b["id"])
            for f in b.get("grants", []):
                if f in seen_grants:
                    fail("事实 %s 被多个节拍 grants（事实只能由一个来源授予）" % f)
                seen_grants.add(f)
            for cid in b.get("cast", []):
                if cid not in char_ids:
                    fail("beat %s 的 cast 引用了不存在的人物 %s" % (b["id"], cid))

        # 事实清单声明（可选但强烈建议）：每项 {id, desc}
        seen_fact_ids = set()
        for f in raw.get("facts", []):
            if not isinstance(f, dict) or not f.get("id"):
                fail("facts 中的条目必须是 {id, desc} 对象")
            if f["id"] in seen_fact_ids:
                fail("facts 声明重复: %s" % f["id"])
            seen_fact_ids.add(f["id"])
        known_facts = seen_fact_ids | set(seen_grants)

        # 节拍触发条件引用的事实必须已声明（防止拼写错误导致节拍永不触发）
        for b in raw["beats"]:
            cond = b.get("when") if b["kind"] == "conditional" else b.get("unlock")
            for f in conditions.required_facts(cond):
                if f not in known_facts:
                    fail("beat %s 的触发条件引用了未声明的事实 %s（请在 facts 清单声明）" % (b["id"], f))
            for h in b.get("fact_hints", []):
                if h.get("fact") not in known_facts:
                    fail("beat %s 的 fact_hints 引用了未声明的事实 %s" % (b["id"], h.get("fact")))

        # 结局：条件引用的 stats/facts 必须存在
        known_stats = set(char_defs) | set(global_defs) | set(ten_dims)
        for e in raw["endings"]:
            for target, _ in conditions._iter_stat_nodes(e.get("conditions")):
                if target not in known_stats:
                    fail("结局 %s 的条件引用了未定义的数值 %s" % (e["id"], target))
            for f in conditions.required_facts(e.get("conditions")):
                if f not in known_facts:
                    fail("结局 %s 的条件引用了未声明的事实 %s" % (e["id"], f))
            if not e.get("name"):
                fail("结局 %s 缺少 name" % e["id"])

        return Constitution(raw)

    # ---------- 查询 ----------

    def char_defs(self) -> Dict[str, Dict]:
        return self.stats.get("characters", {})

    def global_defs(self) -> Dict[str, Dict]:
        return self.stats.get("global", {})

    def ten_dims(self) -> List[str]:
        return self.stats.get("tendencies", [])

    def initial_stats(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for group in (self.char_defs(), self.global_defs()):
            for sid, d in group.items():
                out[sid] = float(d["initial"])
        return out

    def initial_tendencies(self) -> Dict[str, float]:
        return {t: 0.0 for t in self.ten_dims()}
