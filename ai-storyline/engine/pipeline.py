"""AI编剧流水线（Narrator Pipeline）：规划器指令 → 编剧生成 → 审查器 → 落账。

铁律：AI 只负责"写"（dialogue/choices/world_updates 草案），
确定性代码（导演/结算器/审查器）负责"管"。
"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .constitution import Constitution
from .scene import NARRATOR, as_dialogue_lines, dialogue_text, dialogue_len
from .state import WorldState
from .director import RouteDirector, DirectorInstruction
from .ledger import Ledger, LedgerError
from .llm import MockProvider, OpenAICompatProvider, LLMError

JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)
# 从部分JSON中逐行提取对话体行（speaker在前、text在后，模型按模板输出时可增量流式）
DIALOGUE_LINE_RE = re.compile(r'"speaker"\s*:\s*"([^"\\]*)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)


def _unescape_json_str(s: str) -> str:
    try:
        return json.loads('"%s"' % s)
    except json.JSONDecodeError:
        return s


class Critic:
    """审查器：禁忌、一致性、格式。发现问题返回意见，由编剧重写。"""

    SENSITIVE_KEYWORDS = ["自杀", "自残", "性暗示", "性行为", "色情", "血腥"]

    def __init__(self, constitution: Constitution, strict: bool = True):
        self.c = constitution
        self.strict = strict

    def review(self, scene: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        lines = as_dialogue_lines(scene)
        text = dialogue_text(scene)
        if not lines:
            issues.append("dialogue 为空（需提供 dialogue 数组或兼容的 narrative）")
        for ln in lines:
            if not ln["text"].strip():
                issues.append("dialogue 存在空文本行")
        # 说话人必须在剧本人物表内（旁白 narrator 除外）；严格模式才校验，避免旧脚本被误伤
        if self.strict:
            known = {ch["id"] for ch in self.c.characters} | {NARRATOR}
            for ln in lines:
                if ln["speaker"] not in known:
                    issues.append("dialogue 出现未定义说话人 %r（可用: %s）"
                                  % (ln["speaker"], ", ".join(sorted(known))))
            # 交互节奏：对白行(非旁白)每场 5~6 行，超过 8 行驳回（给AI留弹性但压住频率）
            dialogue_rows = sum(1 for ln in lines if ln["speaker"] != NARRATOR)
            if dialogue_rows > 8:
                issues.append("对白行过多: %d行（要求5~6行，上限8行，旁白不计）" % dialogue_rows)
        # 禁忌短语检查（内容安全 + 设定边界）
        for kw in (self.c.world.get("taboos_content") or []) + (self.c.world.get("taboos_story") or []):
            if kw and kw in text:
                issues.append("违反禁忌: %s" % kw)
        for kw in self.SENSITIVE_KEYWORDS:
            if kw in text:
                issues.append("疑似违规词: %s" % kw)
        # 字数（仅真实模型启用严格模式；Mock 文本短，不检查）
        # 阈值取声明值的0.5x/1.5x，给AI留出合理的弹性，避免无谓重试
        if self.strict:
            lo = (self.c.chapter_plan or {}).get("words_per_scene_min")
            hi = (self.c.chapter_plan or {}).get("words_per_scene_max")
            n = dialogue_len(scene)
            if lo and n < lo * 0.5:
                issues.append("正文过短: %d字 < %d字（目标250~450字，可用旁白行补足）" % (n, lo * 0.5))
            if hi and n > hi * 1.5:
                issues.append("正文过长: %d字 > %d字" % (n, hi * 1.5))
        # 选项
        choices = scene.get("choices", [])
        if not 1 <= len(choices) <= 4:
            issues.append("选项数量非法: %d" % len(choices))
        for i, ch in enumerate(choices):
            if not ch.get("text"):
                issues.append("第%d个选项缺少text" % (i + 1))
            if not isinstance(ch.get("tendency"), dict):
                issues.append("第%d个选项缺少tendency标签" % (i + 1))
        # world_updates 引用的数值/类型必须合法
        known = set(self.c.char_defs()) | set(self.c.global_defs())
        for u in scene.get("world_updates", []):
            if u.get("type") not in ("stat", "fact", "close_fact"):
                issues.append("world_updates 未知更新类型 %r" % u.get("type"))
                continue
            if u.get("type") == "stat" and u.get("target") not in known:
                issues.append("world_updates 引用了未定义数值 %s" % u.get("target"))
            if u.get("type") in ("fact", "close_fact") and not u.get("id"):
                issues.append("world_updates 缺少事实id")
        # 事实ID必须来自宪法事实清单（AI不得凭空发明内部ID）；
        # 选项effects的stat目标必须是数值ID（倾向变化只能写 tendency 字段）
        for ch in choices:
            for u in (ch.get("effects") or []):
                if u.get("type") not in ("stat", "fact", "close_fact"):
                    issues.append("选项effects未知更新类型 %r" % u.get("type"))
                elif u.get("type") == "stat" and u.get("target") not in known:
                    issues.append("选项effects引用了未定义数值 %s（倾向请写在tendency字段）"
                                  % u.get("target"))
                elif u.get("type") in ("fact", "close_fact") and u.get("id") not in self.c.facts_catalog:
                    issues.append("选项effects使用了未声明的事实 %s" % u.get("id"))
        return issues


class Pipeline:
    def __init__(self, constitution: Constitution, provider, state: WorldState):
        self.c = constitution
        self.provider = provider
        self.state = state
        self.director = RouteDirector(constitution, state)
        self.ledger = Ledger(constitution)
        self.critic = Critic(constitution, strict=not getattr(provider, "is_mock", False))

    # ---------- 对外接口 ----------

    def start(self) -> Dict[str, Any]:
        instr = self.director.next_instruction()
        return self._generate(instr, None)

    def turn(self, choice_index: Optional[int] = None, free_text: str = "",
             on_line: Optional[Any] = None) -> Dict[str, Any]:
        if self.state.finished:
            return {"finished": True, "ending": self.state.ending}
        if self.state.current_scene is None:
            raise RuntimeError("没有当前场景，请先 start()")
        # 1) 结算用户选择
        choices = self.state.current_scene.get("choices", [])
        if choice_index is not None:
            if not 1 <= choice_index <= len(choices):
                raise ValueError("选项序号越界: %d (共%d个)" % (choice_index, len(choices)))
            chosen = choices[choice_index - 1]
        elif free_text.strip():
            chosen = {"text": free_text, "tendency": {}, "effects": [], "_free": True}
        else:
            raise ValueError("必须提供选项序号或自由输入")
        self.state.turn += 1
        try:
            self.ledger.settle_choice(self.state, chosen)
        except LedgerError as e:
            # 选项效果不合法时丢弃效果，保留叙事与倾向为空的兜底，绝不崩溃
            self.state.fallback_flags.append("choice_settle_partial: %s" % str(e)[:80])
            self.state.log("choice_settle_partial", {"reason": str(e)})
            chosen = {"text": chosen.get("text", ""), "tendency": {}, "effects": []}
            self.ledger.settle_choice(self.state, chosen)
        # 2) 当前节拍完成：以导演指令为准，绝不信任AI输出的beat_id（防幻觉污染状态）
        cur_beat = self._active_beat
        if cur_beat:
            self.director.mark_done(cur_beat)
        self.state.log("turn_end", {"beat": cur_beat, "choice": chosen.get("text")})
        # 3) 下一节拍
        instr = self.director.next_instruction()
        if instr.beat_id is None:
            return self._finish()
        return self._generate(instr, chosen, on_line=on_line)

    def _finish(self) -> Dict[str, Any]:
        ending = self.director.judge_ending()
        self.state.ending = ending
        self.state.finished = True
        self.state.log("ending", {"ending_id": ending["id"] if ending else None})
        return {"finished": True, "ending": ending}

    # ---------- 生成 ----------

    def _generate(self, instr: DirectorInstruction, chosen: Optional[Dict[str, Any]],
                  on_line: Optional[Any] = None) -> Dict[str, Any]:
        self._active_beat = instr.beat_id  # 导演指令是唯一权威
        system = self._system_prompt()
        user = self._user_prompt(instr, chosen)
        if on_line is not None and hasattr(self.provider, "generate_stream"):
            scene = self._writer_streaming(system, user, instr, on_line)
        else:
            scene = self._writer_with_retries(system, user, instr)
        # 生成兜底：不落账、不写入记忆、不消耗节拍——玩家点"重试"后重新生成本节拍
        if scene.get("_fallback"):
            self.state.current_scene = scene
            self.state.last_active_at = time.time()
            self._active_beat = None   # 关键：节拍保持 active，下一次交互重试同一节拍，绝不吞剧情
            self.state.log("generation_fallback_shown", {"beat": instr.beat_id})
            return scene
        # 审查器第二道关：LLM事实一致性检查 + 玩家选择承接检查（仅真实模型模式）
        contradictions = self._consistency_check(scene, instr, chosen)
        if contradictions and not getattr(self.provider, "is_mock", False):
            feedback = ("\n\n[一致性审查驳回] 新剧情与既定事实存在以下矛盾，必须修正：\n"
                        + "\n".join("- " + c for c in contradictions)
                        + "\n请在不违反事实的前提下重写。"
                        + "若包含 choice_ignored，本场开头必须先直接承接玩家上一选择（被示意的人先开口、"
                          "被选择的行动先发生），再推进节拍。")
            self.state.log("consistency_rejected",
                           {"beat": instr.beat_id, "contradictions": contradictions})
            scene = self._writer_with_retries(system, user + feedback, instr)
            # 重写后仍矛盾：接受但标记（评测可见，不无限循环）
            remain = self._consistency_check(scene, instr)
            if remain:
                self.state.fallback_flags.append("consistency_ignored: " + "; ".join(remain)[:80])
                self.state.log("consistency_ignored",
                               {"beat": instr.beat_id, "contradictions": remain})
        # AI输出的beat_id与指令不符时记录（不阻断，但不用于状态结算）
        ai_beat = (scene.get("scene_meta") or {}).get("beat_id")
        if ai_beat and ai_beat != instr.beat_id:
            self.state.log("beat_id_mismatch",
                           {"instructed": instr.beat_id, "ai_output": ai_beat})
        # 场景落账（选项效果等用户选择时再落）；非法更新过滤后落账，绝不崩溃
        try:
            self.ledger.settle_scene(self.state, scene)
        except LedgerError as e:
            self.state.fallback_flags.append("settle_partial: %s" % str(e)[:80])
            self.state.log("settle_partial", {"beat": instr.beat_id, "reason": str(e)})
            scene["world_updates"] = [u for u in (scene.get("world_updates") or [])
                                      if self._update_ok(u)]
            for ch in scene.get("choices", []):
                ch["effects"] = [u for u in (ch.get("effects") or [])
                                 if self._update_ok(u)]
            self.ledger.settle_scene(self.state, scene)  # 过滤后必合法
        self.state.current_scene = scene
        self.state.push_scene(scene)
        self.state.turn += 1
        self.state.last_active_at = time.time()
        if self.state.turn % 5 == 0:
            self._compress_chapter(instr)
        return scene

    def _update_ok(self, u: Dict[str, Any]) -> bool:
        """单条更新是否合法（结算器校验）。"""
        try:
            self.ledger._validate_update(self.state, u)
            return True
        except LedgerError:
            return False

    def _consistency_check(self, scene: Dict[str, Any],
                           instr: DirectorInstruction,
                           chosen: Optional[Dict[str, Any]] = None) -> List[str]:
        """LLM事实一致性检查 + 玩家选择承接检查（真实模型模式）：新场景是否与既定事实矛盾、
        是否明确回应了玩家上一选择。

        Mock模式返回空（确定性脚本天然一致）。
        """
        if getattr(self.provider, "is_mock", False):
            return []
        s = self.state
        known = "\n".join("- %s: %s" % (fid, self.c.facts_catalog.get(fid, fid))
                          for fid in sorted(s.facts))
        narrative = dialogue_text(scene)[:800]
        if not narrative:
            return []
        choice_ask = ""
        if chosen and chosen.get("text"):
            choice_ask = (
                "\n另外，玩家在本场之前的选择是：「%s」。请检查新场景是否明确承接了这一选择"
                "（被示意的人要开口回应、被选择的行动要被执行并产生可见后果）。"
                "若新场景完全无视或回避了玩家选择，在 contradictions 中加一条："
                "choice_ignored: 具体说明哪里没有承接。"
            ) % chosen["text"]
        prompt = (
            "你是一致性审查员。以下是此前剧情的既定事实，请检查新场景是否与之矛盾"
            "（人物身份/性别/关系、物件归属、时间线、地点、逻辑）。\n"
            "【既定事实】\n%s\n【新场景】\n%s\n%s"
            "只输出JSON：{\"contradictions\": [\"矛盾描述\", ...]}；无矛盾输出空数组。"
        ) % (known or "无", narrative, choice_ask)
        try:
            out = self.provider.generate("你是事实一致性审查员，只输出JSON。", prompt)
            m = JSON_BLOCK_RE.search(out)
            if not m:
                return []
            data = json.loads(m.group(0))
            return [c for c in data.get("contradictions", []) if isinstance(c, str)][:5]
        except Exception as e:  # noqa: BLE001
            self.state.log("consistency_check_error", {"reason": str(e)})
            return []

    def _compress_chapter(self, instr: DirectorInstruction) -> None:
        """三层记忆的章节摘要：真实LLM模式下用模型摘要，Mock模式用占位。"""
        s = self.state
        if getattr(self.provider, "is_mock", False):
            s.compress_scene("第%d回合: %s" % (s.turn, instr.must_happen[:80]))
            return
        recent = "\n".join(m.get("narrative") or dialogue_text(m)
                           for m in s.memory["recent"][-5:])
        prev = "; ".join(s.memory["chapter_summary"][-2:])
        prompt = ("请把以下剧情压缩为100字以内的章节摘要（只保留关键事实、人物关系变化、未解悬念）：\n"
                  "【已有摘要】%s\n【最近剧情】\n%s" % (prev or "无", recent))
        try:
            summary = self.provider.generate("你是剧情摘要器，只输出不超过100字的中文摘要。", prompt)
            s.compress_scene(summary.strip()[:150])
        except Exception as e:  # noqa: BLE001
            s.compress_scene("(摘要失败) %s" % instr.must_happen[:80])

    def _writer_streaming(self, system: str, user: str,
                          instr: DirectorInstruction, on_line: Any) -> Dict[str, Any]:
        """流式编剧：第1次尝试流式输出（把已完成的对话行增量推给前端，
        只推 speaker/text，不泄露JSON元数据），失败后第2/3次用非流式重写，
        前端在done事件里以最终 dialogue 覆盖校验。"""
        last_err = ""
        for attempt in range(3):
            try:
                if attempt == 0:
                    buf: List[str] = []
                    emitted = 0
                    for delta in self.provider.generate_stream(system, user):
                        buf.append(delta)
                        joined = "".join(buf)
                        # 正则从头匹配：前缀性质保证前 emitted 个匹配与上次一致，只推新增行
                        for m in list(DIALOGUE_LINE_RE.finditer(joined))[emitted:]:
                            emitted += 1
                            speaker, text = m.group(1), _unescape_json_str(m.group(2))
                            if speaker and text:
                                on_line(speaker, text)
                    self._record_usage(instr)
                    text = "".join(buf)
                else:
                    text = self.provider.generate(system, user)
                    self._record_usage(instr)
                scene = self._parse_scene(text)
                issues = self.critic.review(scene)
                if not issues:
                    return scene
                last_err = "; ".join(issues)
            except (LLMError, json.JSONDecodeError, ValueError) as e:
                last_err = str(e)
            user = user + "\n\n[上一轮生成被驳回，修订意见] " + last_err + "\n请严格按JSON格式重新输出。"
        # 三次失败：降级保守输出并标记（评测可见）
        self.state.fallback_flags.append("generation_fallback: " + last_err[:80])
        self.state.log("generation_fallback", {"beat": instr.beat_id, "reason": last_err})
        return {"dialogue": [{"speaker": NARRATOR, "text": "（本段剧情生成失败，点击下方按钮重试）"}],
                "scene_meta": {"beat_id": instr.beat_id},
                "choices": [{"text": "重试", "tendency": {}, "effects": []}],
                "world_updates": [],
                "_fallback": True}

    def _writer_with_retries(self, system: str, user: str,
                             instr: DirectorInstruction) -> Dict[str, Any]:
        last_err = ""
        for attempt in range(3):
            try:
                text = self.provider.generate(system, user)
                self._record_usage(instr)
                scene = self._parse_scene(text)
                issues = self.critic.review(scene)
                if not issues:
                    return scene
                last_err = "; ".join(issues)
            except (LLMError, json.JSONDecodeError, ValueError) as e:
                last_err = str(e)
            # 带修订意见重试
            user = user + "\n\n[上一轮生成被驳回，修订意见] " + last_err + "\n请严格按JSON格式重新输出。"
        # 三次失败：降级保守输出并标记（评测可见）
        self.state.fallback_flags.append("generation_fallback: " + last_err[:80])
        self.state.log("generation_fallback", {"beat": instr.beat_id, "reason": last_err})
        return {"dialogue": [{"speaker": NARRATOR, "text": "（本段剧情生成失败，点击下方按钮重试）"}],
                "scene_meta": {"beat_id": instr.beat_id},
                "choices": [{"text": "重试", "tendency": {}, "effects": []}],
                "world_updates": [],
                "_fallback": True}

    def _record_usage(self, instr: DirectorInstruction) -> None:
        """真实LLM调用的用量埋点（token/延迟），供成本与延迟达标测量。"""
        u = getattr(self.provider, "last_usage", None)
        if not u:
            return
        path = os.environ.get("QILU_USAGE_FILE", "data/usage.jsonl")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.time(), "story": self.c.story_id, "sid": self.state.session_id,
                    "beat": instr.beat_id, "model": getattr(self.provider, "model", "?"),
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "latency_ms": u.get("latency_ms", 0),
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 埋点失败不影响主流程

    @staticmethod
    def _parse_scene(text: str) -> Dict[str, Any]:
        m = JSON_BLOCK_RE.search(text)
        if not m:
            raise json.JSONDecodeError("未找到JSON块", text, 0)
        return json.loads(m.group(0))

    # ---------- Prompt 组装 ----------

    def _system_prompt(self) -> str:
        c = self.c
        chars = "\n".join(
            "- %s(%s): %s。说话风格: %s" % (
                ch["id"], ch.get("identity", ""), ch.get("personality", []),
                ch.get("speech", "无"))
            for ch in c.characters if ch["id"] != "pc")
        facts = "\n".join("- %s: %s" % (fid, desc)
                          for fid, desc in sorted(c.facts_catalog.items()))
        speaker_ids = [ch["id"] for ch in c.characters]
        return (
            "你是互动叙事游戏《%s》的AI编剧。严格遵守以下剧本宪法，只写用户能看到的内容。\n"
            "【世界观】%s\n【世界规则】%s\n【文风】%s\n【输出形态】%s\n"
            "【内容禁忌（硬红线）】%s\n【设定禁忌】%s\n"
            "【人物卡】\n%s\n"
            "【事实清单（effects/world_updates中的fact与close_fact只能使用这些ID）】\n%s\n"
            "【写作铁律】\n"
            "1. 正文必须输出为 dialogue 对话行数组（文字游戏对话体），对白占比70%%以上，叙述精短；\n"
            "2. dialogue 每行格式固定为 {\"speaker\":\"人物ID\",\"text\":\"台词\"}，speaker 键在前；"
            "speaker 只能是：narrator（旁白/环境叙述）或人物ID %s；"
            "narrator 行用于动作、环境、氛围等非台词叙述，每行不超过60字；pc 是主角，"
            "其台词只表现玩家所选行动的即时反应，不必替玩家长篇发言；同一行只放一句台词；\n"
            "3. 交互节奏与篇幅（两者必须同时满足）：每场人物对白（除 narrator 外的行）5~6 行——"
            "玩家每 5~6 句对话遇到一次选项，对白超过 6 行会被审查器驳回重写；"
            "narrator 旁白行不计入对白行数（环境描写可以穿插），每行20~60字；"
            "全文总字数必须 ≥250 字（目标250~450字，低于250字会被审查驳回）："
            "对白每行15~50字，用2~4行旁白补足篇幅与氛围，把句子写充实，不要写太短；\n"
            "4. 禁止泄露任何NPC的secret；节拍未到不得剧透；\n"
            "5. 选项必须真实分化——至少一个选项会显著改变后续走向；"
            "每场输出 3~4 个选项（文字游戏节奏：选项出现频率要高，确实做不到才减少）；\n"
            "6. 每个选项必须带tendency标签，如实标注其性格倾向含义；"
            "注意区分：tendency 是倾向（%s），effects 里的 type=stat 只能使用数值ID（%s），"
            "绝不允许把倾向名写进 effects 的 target（否则会被驳回）；\n"
            "7. 选项与场景在叙事上真正发生的事实，必须从事实清单中挑选对应ID写入effects/world_updates"
            "——这是剧情机械结算的依据，漏标会让后续剧情无法解锁；\n"
            "8. scene_meta.beat_id 必须与导演指令中的节拍一致；\n"
            "9. 只输出一个JSON对象，不要输出其他文字。JSON结构：\n"
            '{"dialogue":[{"speaker":"lin","text":"台词"},{"speaker":"narrator","text":"旁白/环境描写"}],'
            '"scene_meta":{"beat_id":"...","characters_present":["pc","..."],"location":"..."},'
            '"choices":[{"text":"...","tendency":{"curiosity":1},"effects":[{"type":"stat","target":"sanity","delta":-5,"reason":"..."},{"type":"fact","id":"f_x","text":"..."},{"type":"close_fact","id":"f_x"}]}],'
            '"world_updates":[{"type":"stat","target":"sanity","delta":-5,"reason":"..."}]}\n'
            "注意：effects 是玩家选择该选项后的后果；world_updates 是本场景立即生效的变化；"
            "可用的数值：%s；可用的倾向维度：%s。"
        ) % (c.title, c.world.get("setting", ""), "; ".join(c.world.get("rules", [])),
             c.world.get("tone", ""), c.world.get("style_guide", ""),
             "; ".join(c.world.get("taboos_content", [])), "; ".join(c.world.get("taboos_story", [])),
             chars, facts, ", ".join(speaker_ids),
             ", ".join(c.ten_dims()),
             ", ".join(sorted(set(c.char_defs()) | set(c.global_defs()))),
             ", ".join(sorted(set(c.char_defs()) | set(c.global_defs()))),
             ", ".join(c.ten_dims()))

    def _user_prompt(self, instr: DirectorInstruction, chosen: Optional[Dict[str, Any]]) -> str:
        s = self.state
        lines = []
        lines.append("【导演指令】本场必须发生的节拍: %s" % instr.must_happen)
        lines.append("出场人物: %s" % ", ".join(instr.characters_present))
        if instr.fact_hints:
            lines.append("【本场可授予的事实（叙事发生时务必在effects/world_updates标注对应ID）】")
            for h in instr.fact_hints:
                lines.append("- %s: %s" % (h.get("fact"), h.get("hint")))
        for n in instr.notes:
            lines.append("注意: " + n)
        lines.append("【当前状态】第%d章/第%d回合 | 数值: %s | 倾向: %s" % (
            s.chapter, s.turn,
            ", ".join("%s=%g" % (k, v) for k, v in sorted(s.stats.items())),
            ", ".join("%s=%g" % (k, v) for k, v in sorted(s.tendencies.items()))))
        lines.append("【已确认事实】%s" % (", ".join(sorted(s.facts)) or "无"))
        lines.append("【已关闭可能】%s" % (", ".join(sorted(s.closed_facts)) or "无"))
        if s.memory["recent"]:
            lines.append("【近期剧情】")
            for m in s.memory["recent"][-3:]:
                lines.append("- (beat %s) %s" % (
                    m["beat"], (m.get("narrative") or dialogue_text(m))[:100]))
        if s.memory["chapter_summary"]:
            lines.append("【章节摘要】%s" % "; ".join(s.memory["chapter_summary"][-3:]))
        if chosen:
            if chosen.get("_free"):
                lines.append("【玩家刚刚的自主行动/发言（必须让在场人物明确回应或受影响，剧情要直接接住它）】%s"
                             % chosen.get("text"))
                lines.append("写作要求：本场开头2~4行必须先承接玩家这一行动——行动先发生、相关人物先开口回应，"
                             "让玩家立刻看到自己行动的后果；随后再自然过渡到本场节拍。")
            else:
                lines.append("【玩家上一选择】%s" % chosen.get("text"))
                lines.append("写作要求：本场开头2~4行必须先承接玩家的选择——被示意的人要先开口、"
                             "被选择的行动要先发生并产生可见后果（例如选了‘先听他怎么说’，他必须先开口继续讲）；"
                             "随后再自然过渡到本场节拍。不得跳过玩家选择的即时后果，"
                             "否则会被一致性审查驳回重写。")
        else:
            lines.append("【本场为开场】")
        lines.append("\n[META]%s[/META]" % json.dumps(
            {"beat_id": instr.beat_id, "facts": sorted(s.facts)}, ensure_ascii=False))
        return "\n".join(lines)


def build_provider(mode: str, mock_script_path: Optional[str] = None):
    if mode == "mock":
        return MockProvider(MockProvider.load_script(mock_script_path))
    return OpenAICompatProvider()
