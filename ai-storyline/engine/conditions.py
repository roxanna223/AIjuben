"""条件表达式求值：节拍触发（when/unlock）与结局判定（conditions）共用。

支持两种结构（节拍用单数、结局用复数，语义相同）：
  {"all": [cond, ...]} / {"any": [cond, ...]}
  {"fact": "f_xxx"}                          —— 单个事实已记录
  {"facts": ["f_a", "f_b"]}                  —— 全部事实已记录
  {"stat": {"trust_lin": {"gte": 50}}}        —— 单个数值阈值
  {"stats": {"trust_lin": {"gte": 70}, "sanity": {"gte": 40}}}  —— 多个数值阈值
"""
from typing import Any, Dict, List, Optional


def _check_bounds(value: float, bounds: Dict[str, float]) -> bool:
    for op, threshold in bounds.items():
        if op == "gte" and not value >= threshold:
            return False
        if op == "lte" and not value <= threshold:
            return False
        if op == "gt" and not value > threshold:
            return False
        if op == "lt" and not value < threshold:
            return False
        if op == "eq" and not value == threshold:
            return False
    return True


def check_condition(cond: Optional[Dict[str, Any]],
                    facts: set,
                    stats: Dict[str, float],
                    tendencies: Dict[str, float]) -> bool:
    if cond is None:
        return True
    if not isinstance(cond, dict):
        raise ValueError("条件必须是对象: %r" % (cond,))
    if "all" in cond:
        return all(check_condition(c, facts, stats, tendencies) for c in cond["all"])
    if "any" in cond:
        return any(check_condition(c, facts, stats, tendencies) for c in cond["any"])
    # 同一字典内可同时出现 facts/stats/tendency 等键，语义为合取（全部满足）
    ok = True
    if "facts" in cond:
        ok = ok and all(f in facts for f in cond["facts"])
    if "fact" in cond:
        ok = ok and cond["fact"] in facts
    if "stats" in cond:
        for target, bounds in cond["stats"].items():
            pool = stats if target in stats else tendencies
            if target not in pool or not _check_bounds(pool[target], bounds):
                ok = False
    if "stat" in cond:
        target, bounds = next(iter(cond["stat"].items()))
        pool = stats if target in stats else tendencies
        if target not in pool or not _check_bounds(pool[target], bounds):
            ok = False
    if "tendency" in cond:
        target, bounds = next(iter(cond["tendency"].items()))
        if target not in tendencies or not _check_bounds(tendencies[target], bounds):
            ok = False
    return ok


def _iter_stat_nodes(cond: Optional[Dict[str, Any]]):
    """遍历条件树里的所有数值节点，yield (target, bounds)。"""
    if cond is None:
        return
    if "all" in cond:
        for c in cond["all"]:
            yield from _iter_stat_nodes(c)
    elif "any" in cond:
        for c in cond["any"]:
            yield from _iter_stat_nodes(c)
    elif "stats" in cond:
        for target, bounds in cond["stats"].items():
            yield target, bounds
    elif "stat" in cond:
        target, bounds = next(iter(cond["stat"].items()))
        yield target, bounds
    elif "tendency" in cond:
        target, bounds = next(iter(cond["tendency"].items()))
        yield target, bounds


def stat_threshold_reachable(cond: Optional[Dict[str, Any]],
                             char_defs: Dict[str, Dict],
                             global_defs: Dict[str, Dict],
                             ten_dims: List[str]) -> bool:
    """保守可达性判定（结局池筛选用）：

    数值阈值当前不满足，但若阈值仍落在该数值的定义区间 [min,max] 内，
    就认为"仍可能达成"——宁可多留结局，不误杀路线。
    """
    for target, bounds in _iter_stat_nodes(cond):
        if target in char_defs:
            lo, hi = char_defs[target]["min"], char_defs[target]["max"]
        elif target in global_defs:
            lo, hi = global_defs[target]["min"], global_defs[target]["max"]
        elif target in ten_dims:
            lo, hi = -1.0, 1.0
        else:
            return False  # 引用未定义的数值 → 不可达
        for op, threshold in bounds.items():
            if op in ("gte", "gt") and threshold > hi:
                return False
            if op in ("lte", "lt") and threshold < lo:
                return False
            if op == "eq" and not (lo <= threshold <= hi):
                return False
    return True


def required_facts(cond: Optional[Dict[str, Any]]) -> List[str]:
    """收集条件树里要求的全部事实ID。"""
    out: List[str] = []
    if cond is None:
        return out
    if "all" in cond:
        for c in cond["all"]:
            out.extend(required_facts(c))
    elif "any" in cond:
        for c in cond["any"]:
            out.extend(required_facts(c))
    elif "facts" in cond:
        out.extend(cond["facts"])
    elif "fact" in cond:
        out.append(cond["fact"])
    return out
