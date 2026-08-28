"""工程化校验框架（ValidationScale）测试：规则插件、情景化口径、构建期/审计期。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.constitution import Constitution, ConstitutionError
from engine.validation import ValidationScale, ChangeCtx

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORY = os.path.join(BASE, "stories", "midnight-train.json")
MOCK = STORY.replace(".json", ".mock.json")
STORY2 = os.path.join(BASE, "stories", "rule-tower.json")
MOCK2 = STORY2.replace(".json", ".mock.json")


def scale_for(story=STORY):
    c = Constitution.load(story)
    return c, ValidationScale(c)


def scene(beat_id="b1", updates=None, choices=None):
    return {"scene_meta": {"beat_id": beat_id},
            "dialogue": [{"speaker": "narrator", "text": "…"}],
            "choices": choices or [{"text": "继续", "tendency": {}}],
            "world_updates": updates or []}


class TestBuiltinRules(unittest.TestCase):
    def test_stat_target_defined(self):
        _, s = scale_for()
        rep = s.check_scene(scene(updates=[{"type": "stat", "target": "nope",
                                            "delta": -5, "reason": "x"}]))
        self.assertTrue(any(f.rule_id == "stat_target_defined" for f in rep.errors))

    def test_tendency_dim_defined(self):
        _, s = scale_for()
        rep = s.check_scene(scene(choices=[{"text": "继续",
                                            "tendency": {"不存在维度": 1}}]))
        self.assertTrue(any(f.rule_id == "tendency_dim_defined" for f in rep.errors))

    def test_fact_declared(self):
        _, s = scale_for()
        rep = s.check_scene(scene(updates=[{"type": "fact", "id": "f_ghost",
                                            "text": "x"}]))
        self.assertTrue(any(f.rule_id == "fact_declared" for f in rep.errors))

    def test_unknown_update_type(self):
        _, s = scale_for()
        rep = s.check_scene(scene(updates=[{"type": "teleport", "target": "x"}]))
        self.assertTrue(any(f.rule_id == "update_type_valid" for f in rep.errors))

    def test_zero_delta_and_missing_reason_are_warnings(self):
        _, s = scale_for()
        rep = s.check_scene(scene(updates=[
            {"type": "stat", "target": "sanity", "delta": 0, "reason": "x"},
            {"type": "stat", "target": "sanity", "delta": -3, "reason": ""},
        ]))
        self.assertFalse(rep.errors, rep.error_messages())
        self.assertTrue(any(f.rule_id == "zero_delta_forbidden" for f in rep.warnings))
        self.assertTrue(any(f.rule_id == "reason_required" for f in rep.warnings))
        self.assertEqual(rep.verdict(), "accept_with_warnings")
        self.assertLess(rep.score(), 100)

    def test_missing_reason_large_delta_is_error(self):
        _, s = scale_for()
        rep = s.check_scene(scene(updates=[{"type": "stat", "target": "sanity",
                                            "delta": -25, "reason": ""}]))
        self.assertTrue(any(f.rule_id == "reason_required" for f in rep.errors))


class TestOriginGates(unittest.TestCase):
    def test_beat_grant_not_premature(self):
        _, s = scale_for()
        rep = s.check_scene(scene("b1", updates=[{"type": "fact", "id": "f_ledger_confirmed",
                                                  "text": "x"}]))
        self.assertTrue(any(f.rule_id == "beat_grant_not_premature" for f in rep.errors))
        self.assertTrue(any("自动授予" in f.detail for f in rep.errors))

    def test_own_beat_grant_redundancy_allowed(self):
        _, s = scale_for()
        rep = s.check_scene(scene("b3", updates=[{"type": "fact", "id": "f_ledger_confirmed",
                                                  "text": "x"}]))
        self.assertFalse(any(f.rule_id == "beat_grant_not_premature" for f in rep.errors))

    def test_plot_point_gate_reason_hint(self):
        """情景化：b1 的理由出现'消失'（b2 的剧情点）→ 提前触发，驳回。"""
        _, s = scale_for()
        rep = s.check_scene(scene("b1", updates=[{"type": "stat", "target": "sanity",
                                                  "delta": -5, "reason": "目睹乘客凭空消失"}]))
        self.assertTrue(any(f.rule_id == "plot_point_gate" for f in rep.errors))
        self.assertTrue(any("提前触发" in f.detail for f in rep.errors))
        # b2 是消失剧情点：同样理由合法
        rep2 = s.check_scene(scene("b2", updates=[{"type": "stat", "target": "sanity",
                                                   "delta": -5, "reason": "目睹乘客凭空消失"}]))
        self.assertFalse(any(f.rule_id == "plot_point_gate" for f in rep2.errors))

    def test_plot_point_gate_max_delta(self):
        _, s = scale_for()
        rep = s.check_scene(scene("b6", updates=[{"type": "stat", "target": "sanity",
                                                  "delta": -45, "reason": "真相"}]))
        self.assertTrue(any(f.rule_id == "plot_point_gate" for f in rep.errors))

    def test_fact_origin_gate_beat_and_source(self):
        _, s = scale_for()
        rep = s.check_scene(scene("b4", updates=[{"type": "fact", "id": "f_escaped",
                                                  "text": "独自下车"}]))
        self.assertTrue(any(f.rule_id == "fact_origin_gate" for f in rep.errors))
        # 正确的剧情点+来源：b6 的选项授予 → 通过
        rep2 = s.check_scene(scene("b6", choices=[{"text": "下车", "tendency": {},
                                                   "effects": [{"type": "fact", "id": "f_escaped",
                                                                "text": ""}]}]))
        self.assertFalse(any(f.rule_id == "fact_origin_gate" for f in rep2.errors))

    def test_unchecked_target_skips_gates(self):
        """未声明口径的数值不受剧情点门约束（只受通用规则）。"""
        _, s = scale_for()
        rep = s.check_scene(scene("b1", updates=[{"type": "stat", "target": "trust_lin",
                                                  "delta": -2, "reason": "x"}]))
        self.assertFalse(any(f.rule_id == "plot_point_gate" for f in rep.errors))


class TestBuildAndAudit(unittest.TestCase):
    def test_mock_scenes_pass_build_validation(self):
        """构建期：两个剧本的 mock 全场景必须零 error（防坏内容进生产）。"""
        import json
        for story, mock in ((STORY, MOCK), (STORY2, MOCK2)):
            c = Constitution.load(story)
            s = ValidationScale(c)
            script = json.load(open(mock, encoding="utf-8"))
            for bid, sc in script["scenes"].items():
                rep = s.check_scene(sc)
                self.assertFalse(rep.errors,
                                 "%s mock 场景 %s 校验失败: %s"
                                 % (c.story_id, bid, rep.error_messages()))
                self.assertFalse(rep.findings and False)

    def test_audit_detects_injected_violation(self):
        """审计期：会话事件账本中的提前触发变化被追查出来。
        beat_done 之前的结算=选项后果（b1）；之后的=新场景剧情（b2）。"""
        c, s = scale_for()
        state = {
            "story_id": c.story_id,
            "beat_status": {"b1": {"status": "done", "turn": 2},
                            "b2": {"status": "active", "turn": 2}},
            "event_log": [
                # 选项后果：b1 就出现"目睹乘客凭空消失"→ 提前触发
                {"turn": 2, "type": "stat",
                 "payload": {"target": "sanity", "delta": -5,
                             "reason": "目睹乘客凭空消失"}},
                {"turn": 2, "type": "beat_done", "payload": {"beat_id": "b1"}},
                # 场景世界更新：b2 提前授予 b3 的保留事实
                {"turn": 2, "type": "fact",
                 "payload": {"id": "f_ledger_confirmed", "text": "x"}},
            ],
        }
        rep = s.audit_event_log(state)
        ids = {f.rule_id for f in rep.errors}
        self.assertIn("plot_point_gate", ids)
        self.assertIn("beat_grant_not_premature", ids)
        self.assertEqual(rep.verdict(), "rewrite")

    def test_audit_clean_session_passes(self):
        c, s = scale_for()
        state = {
            "story_id": c.story_id,
            "beat_status": {"b1": {"status": "done", "turn": 2},
                            "b2": {"status": "active", "turn": 2}},
            "event_log": [
                {"turn": 2, "type": "beat_done", "payload": {"beat_id": "b1"}},
                {"turn": 2, "type": "stat",
                 "payload": {"target": "sanity", "delta": -5,
                             "reason": "目睹乘客凭空消失"}},
            ],
        }
        rep = s.audit_event_log(state)
        # b2 是消失剧情点：合法（beat_done at turn 2 = b1，但事件在 beat_done 之后 → b2）
        self.assertFalse(rep.errors, rep.error_messages())


class TestConstitutionValidationBlock(unittest.TestCase):
    def test_bad_plot_point_target_rejected(self):
        raw = json_load(STORY)
        raw["validation"] = {"plot_points": {"ghost_stat": {"allow_at": ["b1"]}}}
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)

    def test_bad_beat_ref_rejected(self):
        raw = json_load(STORY)
        raw["validation"] = {"plot_points": {"sanity": {"allow_at": ["b99"]}}}
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)

    def test_bad_fact_origin_rejected(self):
        raw = json_load(STORY)
        raw["validation"] = {"fact_origins": {"f_ghost": {"beats": ["b1"]}}}
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)

    def test_bad_rule_override_rejected(self):
        raw = json_load(STORY)
        raw["validation"] = {"rules": [{"id": "no_such_rule", "severity": "error"}]}
        with self.assertRaises(ConstitutionError):
            Constitution.validate(raw)


def json_load(path):
    import json
    return json.load(open(path, encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
