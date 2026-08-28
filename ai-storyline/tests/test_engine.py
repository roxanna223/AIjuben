"""Phase 0 验收测试：引擎逻辑 + 三条金标准走查（三个不同结局）。

运行： python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.constitution import Constitution, ConstitutionError
from engine.state import WorldState
from engine.pipeline import Pipeline
from engine.llm import MockProvider
from engine import conditions

STORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "stories", "midnight-train.json")
MOCK = STORY.replace(".json", ".mock.json")


def build(story_path=STORY):
    c = Constitution.load(story_path)
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims())
    p = Pipeline(c, MockProvider(MockProvider.load_script(MOCK)), state)
    return c, state, p


def run_walk(choice_script):
    """按预定选择序列跑完一局，返回 state。"""
    c, state, p = build()
    p.start()
    steps = 0
    for idx in choice_script:
        if state.finished:
            break
        p.turn(choice_index=idx)
        steps += 1
        assert steps < 50, "走查超过50步未收敛"
    return state


class TestConditions(unittest.TestCase):
    def test_fact(self):
        self.assertTrue(conditions.check_condition({"fact": "f_x"}, {"f_x"}, {}, {}))
        self.assertFalse(conditions.check_condition({"fact": "f_x"}, set(), {}, {}))

    def test_stat_gte(self):
        self.assertTrue(conditions.check_condition(
            {"stat": {"s": {"gte": 50}}}, set(), {"s": 60}, {}))

    def test_stat_from_tendency_pool(self):
        self.assertTrue(conditions.check_condition(
            {"stat": {"empathy": {"gte": 0.5}}}, set(), {}, {"empathy": 0.8}))

    def test_all_any(self):
        cond = {"all": [{"fact": "f_x"}, {"any": [{"stat": {"s": {"gte": 50}}}]}]}
        self.assertTrue(conditions.check_condition(cond, {"f_x"}, {"s": 60}, {}))
        self.assertFalse(conditions.check_condition(cond, {"f_x"}, {"s": 40}, {}))

    def test_reachability(self):
        cond = {"stats": {"trust_lin": {"gte": 70}}}
        self.assertTrue(conditions.stat_threshold_reachable(
            cond, {"trust_lin": {"min": 0, "max": 100}}, {}, []))
        self.assertFalse(conditions.stat_threshold_reachable(
            cond, {"trust_lin": {"min": 0, "max": 60}}, {}, []))


class TestConstitution(unittest.TestCase):
    def test_load_valid(self):
        c = Constitution.load(STORY)
        self.assertEqual(c.story_id, "midnight-train")
        self.assertIn("f_truth_revealed", c.facts_catalog)

    def test_missing_field_rejected(self):
        raw = {"story_id": "x"}  # 缺title/world/beats...
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)

    def test_unknown_stat_in_ending_rejected(self):
        import json
        with open(STORY, encoding="utf-8") as f:
            raw = json.load(f)
        raw["endings"][0]["conditions"]["stats"]["nonexist_stat"] = {"gte": 1}
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)


class TestDirector(unittest.TestCase):
    def test_fixed_beats_in_order(self):
        c, state, p = build()
        self.assertEqual(p.director.next_instruction().beat_id, "b1")

    def test_optional_unlock_by_tendency(self):
        c, state, p = build()
        state.tendencies["empathy"] = 0.8
        # 直接构造：把 b7 之前的节拍标记为终态，验证 unlock 判定
        self.assertTrue(p.director._unlock_satisfied(c.beat_index["b7"]))

    def test_skip_closes_grants(self):
        c, state, p = build()
        state.facts.add("f_ledger_seen")
        state.stats["trust_lin"] = 10  # 条件不满足
        p.director.mark_done("b1")
        p.director.mark_done("b2")
        instr = p.director.next_instruction()
        # b3 被跳过，grants 关闭
        self.assertEqual(state.beat_status["b3"]["status"], "skipped")
        self.assertIn("f_ledger_confirmed", state.closed_facts)
        self.assertEqual(instr.beat_id, "b4")


class TestLedger(unittest.TestCase):
    def test_stat_clamped_to_bounds(self):
        c, state, p = build()
        state.stats["sanity"] = 10
        p.ledger._apply_update(state, {"type": "stat", "target": "sanity", "delta": -50})
        self.assertEqual(state.stats["sanity"], 0)

    def test_unknown_stat_rejected(self):
        c, state, p = build()
        with self.assertRaises(Exception):
            p.ledger._apply_update(state, {"type": "stat", "target": "nope", "delta": 1})

    def test_tendency_clamped(self):
        c, state, p = build()
        state.apply_tendency("curiosity", 5)
        self.assertEqual(state.tendencies["curiosity"], 1.0)


class TestGoldenWalkthroughs(unittest.TestCase):
    """三条预定选择序列 → 三个不同结局（Phase 0 验收核心）。"""

    def run_walk_and_assert_healthy(self, script):
        state = run_walk(script)
        self.assertTrue(state.finished, "走查未达成结局")
        # 无生成降级、无结局兜底
        self.assertEqual(state.fallback_flags, [], "存在降级标记: %s" % state.fallback_flags)
        # 数值都在定义域内
        for k, v in state.stats.items():
            self.assertTrue(0 <= v <= 100, "%s=%s 越界" % (k, v))
        for k, v in state.tendencies.items():
            self.assertTrue(-1 <= v <= 1, "%s=%s 越界" % (k, v))
        # 记忆与账本
        self.assertLessEqual(len(state.memory["recent"]), 10)
        self.assertTrue(state.event_log)
        return state

    def test_path_A_cautious_selfish_end_passenger(self):
        state = self.run_walk_and_assert_healthy([2, 2, 1, 3])
        self.assertEqual(state.ending["id"], "end_passenger")

    def test_path_B_empathetic_trusting_end_truth(self):
        state = self.run_walk_and_assert_healthy([1, 1, 1, 2, 1, 1, 1])
        self.assertEqual(state.ending["id"], "end_truth")

    def test_path_C_curious_distrustful_end_conductor(self):
        state = self.run_walk_and_assert_healthy([2, 3, 2, 1, 2, 2])
        self.assertEqual(state.ending["id"], "end_conductor")

    def test_three_paths_three_endings(self):
        endings = {run_walk([2, 2, 1, 3]).ending["id"],
                   run_walk([1, 1, 1, 2, 1, 1, 1]).ending["id"],
                   run_walk([2, 3, 2, 1, 2, 2]).ending["id"]}
        self.assertEqual(len(endings), 3, "三条路线未分化出三个结局: %s" % endings)


class TestDialogueFormat(unittest.TestCase):
    """v0.3 对话体输出：结构化 dialogue 数组 + 旧版 narrative 兼容。"""

    def test_legacy_narrative_normalized(self):
        from engine.scene import as_dialogue_lines, dialogue_text
        scene = {"narrative": "车厢摇晃。"}
        self.assertEqual(as_dialogue_lines(scene),
                         [{"speaker": "narrator", "text": "车厢摇晃。"}])
        self.assertIn("车厢摇晃", dialogue_text(scene))

    def test_dialogue_preferred_over_narrative(self):
        from engine.scene import as_dialogue_lines
        scene = {"narrative": "旧正文", "dialogue": [{"speaker": "lin", "text": "别怕。"}]}
        self.assertEqual(as_dialogue_lines(scene),
                         [{"speaker": "lin", "text": "别怕。"}])

    def test_mock_scenes_have_dialogue(self):
        c, state, p = build()
        scene = p.start()
        self.assertIn("dialogue", scene)
        self.assertTrue(scene["dialogue"])
        self.assertEqual(scene["dialogue"][0]["speaker"], "narrator")

    def test_critic_rejects_unknown_speaker_in_strict_mode(self):
        c, state, p = build()
        p.critic.strict = True
        issues = p.critic.review({
            "dialogue": [{"speaker": "ghost", "text": "你好"}],
            "choices": [{"text": "继续", "tendency": {}}],
            "world_updates": [],
        })
        self.assertTrue(any("未定义说话人" in i for i in issues))

    def test_critic_rejects_empty_dialogue(self):
        c, state, p = build()
        issues = p.critic.review({
            "dialogue": [],
            "choices": [{"text": "继续", "tendency": {}}],
            "world_updates": [],
        })
        self.assertTrue(any("dialogue 为空" in i for i in issues))

    def test_critic_rejects_too_many_dialogue_rows_strict(self):
        """交互节奏：对白行(非旁白)超过8行驳回，旁白不计入。"""
        c, state, p = build()
        p.critic.strict = True
        lines = [{"speaker": "lin", "text": "台词%d" % i} for i in range(9)]
        issues = p.critic.review({
            "dialogue": lines,
            "choices": [{"text": "继续", "tendency": {}}],
            "world_updates": [],
        })
        self.assertTrue(any("对白行过多" in i for i in issues))
        # 旁白行不计入对白行数：9行里3行旁白+6行对白 → 不触发该驳回
        lines2 = ([{"speaker": "narrator", "text": "环境描写"}] * 3
                  + [{"speaker": "lin", "text": "台词%d" % i} for i in range(6)])
        issues2 = p.critic.review({
            "dialogue": lines2,
            "choices": [{"text": "继续", "tendency": {}}],
            "world_updates": [],
        })
        self.assertFalse(any("对白行过多" in i for i in issues2))

    def test_state_memory_stores_dialogue(self):
        c, state, p = build()
        p.start()
        last = state.memory["recent"][-1]
        self.assertIn("dialogue", last)
        self.assertTrue(last["dialogue"])
        self.assertTrue(last["narrative"])  # 纯文本副本仍保留（摘要/提示词用）


class TestGenerationFallbackRetry(unittest.TestCase):
    """生成失败兜底：不吞节拍——点"重试"后重新生成同一节拍，剧情不断裂。"""

    def test_fallback_keeps_beat_and_retries(self):
        from engine.llm import LLMError

        class FailProvider:
            is_mock = False

            def generate(self, system, user):
                raise LLMError("模拟API故障")

        c, state, p = build()
        p.provider = FailProvider()
        scene = p.start()
        # 兜底场景：提示重试，且不把失败节拍标记完成、不写入记忆
        self.assertTrue(scene.get("_fallback"))
        self.assertEqual(scene["choices"][0]["text"], "重试")
        self.assertEqual(state.beat_status["b1"]["status"], "active")
        self.assertEqual(state.memory["recent"], [])

        # 换回可用Provider后点"重试"：重新生成 b1（而不是跳到 b2）
        p.provider = MockProvider(MockProvider.load_script(MOCK))
        scene2 = p.turn(choice_index=1)
        self.assertFalse(scene2.get("_fallback"))
        self.assertIn("dialogue", scene2)
        self.assertEqual(state.beat_status["b1"]["status"], "active")   # 播完才结算
        self.assertEqual([m["beat"] for m in state.memory["recent"]], ["b1"])

        # 再推进一次：b1 才真正完成，随后正常进入 b2
        p.turn(choice_index=1)
        self.assertEqual(state.beat_status["b1"]["status"], "done")


class TestFixedPlot(unittest.TestCase):
    """固定剧情锚点：用户不可操作的基础剧情细节定稿，跨局一致、有据可依。"""

    def test_fixed_plot_loaded(self):
        c, state, p = build()
        self.assertTrue(c.fixed_plot)
        b2 = c.fixed_plot_for("b2")
        self.assertTrue(any("沈阿婆" in f["fact"] for f in b2))

    def test_fixed_plot_injected_into_instruction(self):
        c, state, p = build()
        p.director.mark_done("b1")
        instr = p.director.next_instruction()
        self.assertEqual(instr.beat_id, "b2")
        self.assertTrue(any("固定剧情" in n and "沈阿婆" in n for n in instr.notes))
        self.assertIn("固定剧情", p._user_prompt(instr, None))

    def test_fixed_plot_unknown_beat_rejected(self):
        import json
        from engine.constitution import ConstitutionError
        with open(STORY, encoding="utf-8") as f:
            raw = json.load(f)
        raw["fixed_plot"] = raw.get("fixed_plot", []) + [
            {"id": "fp_bad", "beat": "nope", "fact": "x"}]
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
