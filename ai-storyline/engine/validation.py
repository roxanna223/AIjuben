"""工程化内容校验框架（Content Validation Scale）。

设计目标（v0.4.8）：
1. 校验口径是数据、不是代码——规则以声明式量表描述：
   - 内置通用规则插件（数值/事实合法性、出发点绑定等）；
   - 剧本宪法可选 `validation` 段声明**情景化规则**（哪些数值在哪些剧情点
     允许变化、幅度上限、理由禁用词、事实的合法出处），剧本作者零引擎
     改动即可为具体情景配置工程化校验。
2. 一个量表、三种运行环境（可复用）：
   - 构建期：mock 脚本/宪法加载时校验，防止坏内容进生产（tests + CLI）；
   - 运行期：AI 每场生成后即时校验（error→驳回重写，warn→接受并记账）；
   - 审计期：离线扫描历史会话事件账本，追查"数值出发点/剧情出发点"违规。
3. 插件化：新校验维度 = 注册一个 check 函数 + 在 DEFAULT_RULES 声明规则，
   不触碰框架代码；剧本可用 `validation.rules` 按规则覆盖严重度/参数。
4. 报告结构化：每条规则的 pass/fail/warn + 维度 + 严重度 + 汇总分值(0~100)，
   全量落事件账本（validation_report），可审计、可评测。

铁律不变：校验器是确定性代码（语义类检查由流水线喂入 LLM 判定结果），
校验失败只驳回重写，绝不自行改写内容。
"""
from typing import Any, Dict, List, Optional

VALID_UPDATE_TYPES = ("stat", "tendency", "fact", "close_fact")
VALID_SOURCES = ("scene", "choice", "event", "beat_grant")
DIMENSIONS = ("数值合法性", "剧情合法性", "数值出发点", "剧情出发点", "语义一致性")


class Finding:
    """单条校验结果：一条规则对一次"变化"的判定。"""

    def __init__(self, rule_id: str, dimension: str, severity: str,
                 status: str, detail: str, target: str = ""):
        self.rule_id = rule_id
        self.dimension = dimension
        self.severity = severity            # error | warn
        self.status = status                # fail | warn
        self.detail = detail
        self.target = target

    def to_dict(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id, "dimension": self.dimension,
                "severity": self.severity, "status": self.status,
                "detail": self.detail, "target": self.target}


class ChangeCtx:
    """一次"变化"的完整上下文：校验的原子单位。

    同一套校验规则吃同一个上下文对象——运行期吃 AI 生成的 scene，
    审计期吃会话事件账本，构建期吃 mock 脚本，三种来源归一。
    """

    def __init__(self, kind: str, target: str, delta: Any, reason: str,
                 source: str, beat_id: Optional[str]):
        self.kind = kind        # stat | tendency | fact | close_fact
        self.target = target
        self.delta = delta
        self.reason = (reason or "").strip()
        self.source = source    # scene | choice | event | beat_grant
        self.beat_id = beat_id  # 发生变化的剧情点（节拍）

    def label(self) -> str:
        return "%s %s" % (self.kind, self.target)


class ValidationReport:
    """一次校验的完整报告：逐条 finding + 汇总。"""

    def __init__(self):
        self.findings: List[Finding] = []
        self.checked: Dict[str, int] = {}   # rule_id -> 检查次数（含通过）

    def add(self, finding: Optional[Finding]) -> None:
        if finding is not None:
            self.findings.append(finding)

    def count(self, rule_id: str, n: int = 1) -> None:
        self.checked[rule_id] = self.checked.get(rule_id, 0) + n

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    def error_messages(self) -> List[str]:
        """供审查器驳回重写用的纯文本意见列表。"""
        return ["[%s] %s" % (f.dimension, f.detail) for f in self.errors]

    def verdict(self) -> str:
        """rewrite=有error需重写 | accept_with_warnings=仅警告 | pass=全过 | no_changes=无变化可查。"""
        if self.errors:
            return "rewrite"
        if self.warnings:
            return "accept_with_warnings"
        return "pass"

    def score(self) -> int:
        return max(0, 100 - 20 * len(self.errors) - 5 * len(self.warnings))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict(),
            "score": self.score(),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "checked": dict(self.checked),
            "findings": [f.to_dict() for f in self.findings],
        }


# ==================== 内置规则插件 ====================
# 每个插件: fn(scale, ctx) -> Optional[Finding]（违规时返回 Finding，通过返回 None）
# 插件是"工程化校验的分支"：新增维度 = 新增插件 + 在 DEFAULT_RULES 登记。

def _stat_target_defined(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind != "stat":
        return None
    if ctx.target not in scale.known_stats:
        return Finding("stat_target_defined", "数值合法性", "error", "fail",
                       "引用了未定义的数值 %s（可用: %s）"
                       % (ctx.target, ", ".join(sorted(scale.known_stats))),
                       ctx.target)
    return None


def _tendency_dim_defined(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind != "tendency":
        return None
    if ctx.target not in scale.ten_dims:
        return Finding("tendency_dim_defined", "数值合法性", "error", "fail",
                       "引用了未定义的倾向维度 %s（可用: %s）"
                       % (ctx.target, ", ".join(sorted(scale.ten_dims))),
                       ctx.target)
    return None


def _fact_declared(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind not in ("fact", "close_fact"):
        return None
    if not ctx.target or ctx.target not in scale.facts_catalog:
        return Finding("fact_declared", "剧情合法性", "error", "fail",
                       "使用了未声明的事实 %s" % (ctx.target or "<空>"), ctx.target)
    return None


def _update_type_valid(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind not in VALID_UPDATE_TYPES:
        return Finding("update_type_valid", "剧情合法性", "error", "fail",
                       "未知更新类型 %r（可选: %s）" % (ctx.kind, ", ".join(VALID_UPDATE_TYPES)),
                       str(ctx.kind))
    return None


def _zero_delta_forbidden(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind != "stat":
        return None
    if isinstance(ctx.delta, (int, float)) and float(ctx.delta) == 0.0:
        return Finding("zero_delta_forbidden", "数值出发点", "warn", "warn",
                       "%s 的变化量为 0，无实际效果，建议删除该条更新" % ctx.label(),
                       ctx.target)
    return None


def _reason_required(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    if ctx.kind != "stat":
        return None
    try:
        delta = abs(float(ctx.delta))
    except (TypeError, ValueError):
        return None
    if ctx.reason:
        return None
    if delta >= scale.rule_param("reason_required", "min_error_delta", 10):
        return Finding("reason_required", "数值出发点", "error", "fail",
                       "%s 变化幅度 %.1f 但缺少原因说明（大额变化必须解释剧情依据）"
                       % (ctx.label(), delta), ctx.target)
    return Finding("reason_required", "数值出发点", "warn", "warn",
                   "%s 变化缺少原因说明，建议补充剧情依据" % ctx.label(), ctx.target)


def _beat_grant_not_premature(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    """剧情出发点·硬防线：节拍保留事实由引擎在节拍完成时自动授予，
    其他节拍提前授予 = 提前触发后续剧情点。"""
    if ctx.kind != "fact":
        return None
    owner = scale.beat_grants.get(ctx.target)
    if owner and owner != ctx.beat_id:
        return Finding("beat_grant_not_premature", "剧情出发点", "error", "fail",
                       "事实 %s 由节拍 %s 完成时自动授予，不得在节拍 %s 提前写入"
                       % (ctx.target, owner, ctx.beat_id or "?"), ctx.target)
    return None


def _plot_point_gate(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    """数值出发点·情景化：数值变化必须发生在宪法声明的剧情点上。

    声明口径（story.validation.plot_points[target]）：
      allow_at: [节拍列表]          变化允许发生的剧情点（缺省=全部节拍）
      max_abs_delta: 数值            单次变化幅度上限
      forbid_reason_hints: {节拍: [关键词]}  该节拍的理由中禁止出现的剧情点外关键词
        （例：b1 禁止"消失/不见了"——乘客消失是 b2 的剧情点）
    """
    if ctx.kind != "stat":
        return None
    spec = scale.plot_points.get(ctx.target)
    if not spec:
        return None
    allow = spec.get("allow_at")
    if allow and ctx.beat_id not in allow:
        return Finding("plot_point_gate", "数值出发点", "error", "fail",
                       "数值 %s 在节拍 %s 未声明允许变化（允许: %s）"
                       % (ctx.target, ctx.beat_id or "?", ", ".join(allow)),
                       ctx.target)
    try:
        delta = abs(float(ctx.delta))
    except (TypeError, ValueError):
        delta = 0.0
    cap = spec.get("max_abs_delta")
    if cap is not None and delta > float(cap):
        return Finding("plot_point_gate", "数值出发点", "error", "fail",
                       "数值 %s 单次变化 %.1f 超出上限 %.1f（剧情点幅度约束）"
                       % (ctx.target, delta, float(cap)), ctx.target)
    hints = (spec.get("forbid_reason_hints") or {}).get(ctx.beat_id or "")
    if hints and ctx.reason:
        for kw in hints:
            if kw in ctx.reason:
                return Finding("plot_point_gate", "数值出发点", "error", "fail",
                               "数值 %s 在节拍 %s 的理由 %r 包含剧情点外关键词 %r"
                               "（该剧情尚未发生，属于提前触发）"
                               % (ctx.target, ctx.beat_id, ctx.reason[:20], kw),
                               ctx.target)
    return None


def _fact_origin_gate(scale: "ValidationScale", ctx: ChangeCtx) -> Optional[Finding]:
    """剧情出发点·情景化：事实必须在其声明的剧情点/来源下授予。

    声明口径（story.validation.fact_origins[fact_id]）：
      beats: [节拍列表]   允许授予该事实的剧情点
      via: [来源列表]     允许的授予来源（scene/choice/beat_grant）
    节拍自己保留的事实（beat grants）不受此门约束（引擎自动授予，冗余标注幂等）。
    """
    if ctx.kind not in ("fact", "close_fact"):
        return None
    if ctx.target in scale.beat_grants and scale.beat_grants[ctx.target] == ctx.beat_id:
        return None
    spec = scale.fact_origins.get(ctx.target)
    if not spec:
        return None
    beats = spec.get("beats") or []
    if beats and ctx.beat_id not in beats:
        return Finding("fact_origin_gate", "剧情出发点", "error", "fail",
                       "事实 %s 在节拍 %s 未声明允许授予（允许: %s）"
                       % (ctx.target, ctx.beat_id or "?", ", ".join(beats)),
                       ctx.target)
    via = spec.get("via") or []
    if via and ctx.source not in via:
        return Finding("fact_origin_gate", "剧情出发点", "error", "fail",
                       "事实 %s 不允许通过来源 %s 授予（允许: %s）"
                       % (ctx.target, ctx.source, ", ".join(via)), ctx.target)
    return None


BUILTIN_CHECKS = {
    "stat_target_defined": _stat_target_defined,
    "tendency_dim_defined": _tendency_dim_defined,
    "fact_declared": _fact_declared,
    "update_type_valid": _update_type_valid,
    "zero_delta_forbidden": _zero_delta_forbidden,
    "reason_required": _reason_required,
    "beat_grant_not_premature": _beat_grant_not_premature,
    "plot_point_gate": _plot_point_gate,
    "fact_origin_gate": _fact_origin_gate,
}

DEFAULT_RULES: List[Dict[str, Any]] = [
    {"id": "update_type_valid", "dimension": "剧情合法性", "severity": "error",
     "check": "update_type_valid", "desc": "更新类型必须是 stat/tendency/fact/close_fact"},
    {"id": "stat_target_defined", "dimension": "数值合法性", "severity": "error",
     "check": "stat_target_defined", "desc": "stat 目标必须是宪法声明的数值ID"},
    {"id": "tendency_dim_defined", "dimension": "数值合法性", "severity": "error",
     "check": "tendency_dim_defined", "desc": "倾向维度必须是宪法声明的五维之一"},
    {"id": "fact_declared", "dimension": "剧情合法性", "severity": "error",
     "check": "fact_declared", "desc": "事实ID必须来自宪法事实清单"},
    {"id": "zero_delta_forbidden", "dimension": "数值出发点", "severity": "warn",
     "check": "zero_delta_forbidden", "desc": "变化量为0的更新无实际效果"},
    {"id": "reason_required", "dimension": "数值出发点", "severity": "error",
     "check": "reason_required", "desc": "数值变化应携带剧情原因（大额变化必须）",
     "params": {"min_error_delta": 10}, "dynamic_severity": True},
    {"id": "beat_grant_not_premature", "dimension": "剧情出发点", "severity": "error",
     "check": "beat_grant_not_premature", "desc": "节拍保留事实不得提前授予"},
    {"id": "plot_point_gate", "dimension": "数值出发点", "severity": "error",
     "check": "plot_point_gate", "desc": "数值变化必须发生在声明的剧情点/幅度内（情景化）"},
    {"id": "fact_origin_gate", "dimension": "剧情出发点", "severity": "error",
     "check": "fact_origin_gate", "desc": "事实必须在其声明的剧情点/来源授予（情景化）"},
]


class ValidationScale:
    """校验量表：规则装配 + 变化归一 + 报告汇总。

    情景化装配：`constitution.validation` 的 plot_points / fact_origins 是
    剧本专属口径；rules 可覆盖内置规则的严重度与参数。
    """

    def __init__(self, constitution: Any):
        self.c = constitution
        self.rules: Dict[str, Dict[str, Any]] = {r["id"]: dict(r) for r in DEFAULT_RULES}
        validation = getattr(constitution, "validation", {}) or {}
        for r in validation.get("rules", []):
            base = self.rules.get(r["id"], {})
            self.rules[r["id"]] = {**base, **r}
        self.plot_points: Dict[str, Any] = validation.get("plot_points", {})
        self.fact_origins: Dict[str, Any] = validation.get("fact_origins", {})
        self.beat_grants: Dict[str, str] = {
            f: b["id"] for b in constitution.beats for f in b.get("grants", [])}
        self.known_stats = set(constitution.char_defs()) | set(constitution.global_defs())
        self.ten_dims = set(constitution.ten_dims())
        self.facts_catalog = constitution.facts_catalog

    def rule_param(self, rule_id: str, key: str, default: Any) -> Any:
        return (self.rules.get(rule_id, {}).get("params") or {}).get(key, default)

    # ---------- 变化归一（三种来源共用） ----------

    def ctx_from_update(self, u: Dict[str, Any], source: str,
                        beat_id: Optional[str]) -> ChangeCtx:
        kind = u.get("type", "")
        if kind == "stat":
            return ChangeCtx("stat", u.get("target", ""), u.get("delta"),
                             u.get("reason", ""), source, beat_id)
        if kind == "tendency":
            return ChangeCtx("tendency", u.get("dim", ""), u.get("delta"),
                             u.get("reason", ""), source, beat_id)
        if kind in ("fact", "close_fact"):
            return ChangeCtx(kind, u.get("id", ""), None,
                             u.get("text", ""), source, beat_id)
        return ChangeCtx(kind, "", None, "", source, beat_id)

    def scene_changes(self, scene: Dict[str, Any]) -> List[ChangeCtx]:
        """把场景JSON拆成'变化'列表：world_updates 记 scene 来源，
        选项 effects 记 choice 来源，选项倾向标签记 tendency。"""
        beat_id = (scene.get("scene_meta") or {}).get("beat_id")
        out: List[ChangeCtx] = []
        for u in scene.get("world_updates") or []:
            out.append(self.ctx_from_update(u, "scene", beat_id))
        for ch in scene.get("choices") or []:
            for u in ch.get("effects") or []:
                out.append(self.ctx_from_update(u, "choice", beat_id))
            for dim, delta in (ch.get("tendency") or {}).items():
                out.append(ChangeCtx("tendency", dim, delta, "", "choice", beat_id))
        return out

    # ---------- 校验 ----------

    def check_change(self, ctx: ChangeCtx,
                     report: Optional[ValidationReport] = None) -> List[Finding]:
        out: List[Finding] = []
        for rule in self.rules.values():
            fn = BUILTIN_CHECKS.get(rule.get("check", ""))
            if fn is None:
                continue
            if report is not None:
                report.count(rule["id"])
            finding = fn(self, ctx)
            if finding is not None:
                finding.rule_id = rule["id"]
                # 动态严重度规则（如 reason_required 按幅度决定 warn/error）以插件判定为准，
                # 其余规则可被规则表/剧本配置覆盖严重度
                if not rule.get("dynamic_severity"):
                    finding.severity = rule.get("severity", finding.severity)
                finding.status = "fail" if finding.severity == "error" else "warn"
                out.append(finding)
        return out

    def check_scene(self, scene: Dict[str, Any]) -> ValidationReport:
        """运行期/构建期入口：校验一整场AI输出。"""
        report = ValidationReport()
        for ctx in self.scene_changes(scene):
            for finding in self.check_change(ctx, report):
                report.add(finding)
        return report

    # ---------- 审计入口（会话事件账本） ----------

    def audit_event_log(self, state_dict: Dict[str, Any]) -> ValidationReport:
        """审计期入口：重建历史事件账本中的变化，逐条校验出发点。

        beat 归属：turn 内 beat_done 之前的结算 = 该节拍的选项后果（选择本身）；
        beat_done 之后的结算 = 该回合新激活节拍的场景 world_updates（剧情推进）。
        """
        report = ValidationReport()
        events = state_dict.get("event_log") or []
        beat_status = state_dict.get("beat_status") or {}
        active_by_turn: Dict[int, str] = {}   # 激活回合 -> 节拍（场景更新归属，优先）
        done_by_turn: Dict[int, str] = {}     # 完成回合 -> 节拍
        for bid, st in beat_status.items():
            t = st.get("turn")
            if isinstance(t, int):
                (active_by_turn if st.get("status") == "active"
                 else done_by_turn).setdefault(t, bid)
        done_at: Dict[int, str] = {}         # 完成回合 -> 节拍（选项效果归属）
        bd_index: Dict[int, int] = {}        # 完成回合 -> 首个 beat_done 事件位置
        for i, e in enumerate(events):
            if e.get("type") == "beat_done" and isinstance(e.get("turn"), int):
                done_at.setdefault(e["turn"], (e.get("payload") or {}).get("beat_id", ""))
                bd_index.setdefault(e["turn"], i)
        for i, e in enumerate(events):
            if e.get("type") not in ("stat", "tendency", "fact", "close_fact"):
                continue
            t = e.get("turn")
            if not isinstance(t, int):
                continue
            bdi = bd_index.get(t)
            if bdi is not None and i < bdi:
                beat = done_at.get(t)                       # beat_done 之前 → 选项后果
                source = "choice"
            else:
                beat = active_by_turn.get(t) or done_at.get(t)  # 之后 → 新场景剧情
                source = "scene"
            p = e.get("payload") or {}
            if e["type"] == "stat":
                ctx = ChangeCtx("stat", p.get("target", ""), p.get("delta"),
                                p.get("reason", ""), source, beat)
            elif e["type"] == "tendency":
                ctx = ChangeCtx("tendency", p.get("dim", ""), p.get("delta"), "",
                                source, beat)
            else:
                ctx = ChangeCtx(e["type"], p.get("id", ""), None,
                                p.get("text", ""), source, beat)
            for finding in self.check_change(ctx, report):
                report.add(finding)
        return report
