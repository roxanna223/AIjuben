"""结算器（Ledger）：AI 的 world_updates 必须经此审核落账，AI 不能直接改库。

原则：先全量校验、后原子落账——任何一条更新非法则整批拒绝，不留半成品状态。
"""
from typing import Any, Dict, List, Optional

from .state import WorldState
from .constitution import Constitution

VALID_TYPES = ("stat", "fact", "close_fact")


class LedgerError(ValueError):
    pass


class Ledger:
    def __init__(self, constitution: Constitution):
        self.c = constitution

    def _bounds(self, target: str) -> Dict[str, float]:
        if target in self.c.char_defs():
            return self.c.char_defs()[target]
        if target in self.c.global_defs():
            return self.c.global_defs()[target]
        raise LedgerError("未定义的数值 %s" % target)

    def _validate_update(self, state: WorldState, u: Dict[str, Any]) -> None:
        utype = u.get("type")
        if utype not in VALID_TYPES:
            raise LedgerError("未知更新类型 %r" % utype)
        if utype == "stat":
            target = u.get("target")
            self._bounds(target)          # 未定义即抛错
            float(u.get("delta", 0))      # 非数值即抛错
        else:
            if not u.get("id"):
                raise LedgerError("%s 更新缺少 id" % utype)
            if u["id"] not in self.c.facts_catalog:
                raise LedgerError("未声明的事实 %s" % u["id"])

    def _validate_choice(self, state: WorldState, choice: Dict[str, Any]) -> None:
        for dim in (choice.get("tendency") or {}):
            if dim not in state.tendencies:
                raise LedgerError("未定义的倾向维度 %s" % dim)
        for u in (choice.get("effects") or []):
            self._validate_update(state, u)

    def settle_scene(self, state: WorldState, scene: Dict[str, Any]) -> None:
        """场景生成时落账：scene.world_updates（不含选项效果）。先校验后落账。"""
        updates = scene.get("world_updates") or []
        for u in updates:
            self._validate_update(state, u)
        for u in updates:
            self._apply_update(state, u)

    def settle_choice(self, state: WorldState, choice: Dict[str, Any]) -> None:
        """用户选定选项后落账：倾向标签 + 选项效果。先校验后落账。"""
        self._validate_choice(state, choice)
        for dim, delta in (choice.get("tendency") or {}).items():
            state.apply_tendency(dim, float(delta))
        state.log("choice", {"choice": choice.get("text", "")})
        for u in (choice.get("effects") or []):
            self._apply_update(state, u)

    def _apply_update(self, state: WorldState, u: Dict[str, Any]) -> None:
        utype = u.get("type")
        if utype == "stat":
            state.apply_stat(u.get("target"), float(u.get("delta", 0)),
                             self._bounds(u.get("target")), u.get("reason", ""))
        elif utype == "fact":
            state.add_fact(u["id"], u.get("text", ""))
        elif utype == "close_fact":
            state.close_fact(u["id"])
