"""第二个剧本《规则楼》：验证剧本Schema与引擎的通用性 + 三条金标准走查。

这是"项目里有很多剧本"的关键证据：引擎零改动即可承载一个
题材不同（规则怪谈）、数值不同（violations）、结局不同的剧本。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.constitution import Constitution
from engine.state import WorldState
from engine.pipeline import Pipeline
from engine.llm import MockProvider

STORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "stories", "rule-tower.json")
MOCK = STORY.replace(".json", ".mock.json")


def run_walk(choice_script):
    c = Constitution.load(STORY)
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims())
    p = Pipeline(c, MockProvider(MockProvider.load_script(MOCK)), state)
    p.start()
    steps = 0
    for idx in choice_script:
        if state.finished:
            break
        p.turn(choice_index=idx)
        steps += 1
        assert steps < 50, "走查超过50步未收敛"
    assert state.finished, "走查未达成结局"
    assert state.fallback_flags == [], "存在降级标记: %s" % state.fallback_flags
    for k, v in state.stats.items():
        assert 0 <= v <= 100, "%s=%s 越界" % (k, v)
    return state


class TestRuleTower(unittest.TestCase):
    def test_constitution_valid(self):
        c = Constitution.load(STORY)
        self.assertEqual(c.story_id, "rule-tower")
        self.assertIn("f_zhou_key", c.facts_catalog)
        # 违规次数是剧本自定义的全局数值（0-3），引擎无需改动即支持
        self.assertEqual(c.global_defs()["violations"]["max"], 3)

    def test_path_A_rule_follower_end_escape(self):
        s = run_walk([1, 1, 2, 2, 1])
        self.assertEqual(s.ending["id"], "end_escape")
        self.assertEqual(s.stats["violations"], 0)

    def test_path_B_empath_end_hero(self):
        s = run_walk([1, 1, 1, 1, 2, 1, 2])
        self.assertEqual(s.ending["id"], "end_hero")
        self.assertIn("f_zhou_key", s.facts)

    def test_path_C_curious_selfish_end_stay(self):
        s = run_walk([2, 2, 1, 1, 2, 4])
        self.assertEqual(s.ending["id"], "end_stay")
        self.assertEqual(s.stats["violations"], 1)  # 违反应门规则被记账

    def test_three_paths_three_endings(self):
        endings = {run_walk([1, 1, 2, 2, 1]).ending["id"],
                   run_walk([1, 1, 1, 1, 2, 1, 2]).ending["id"],
                   run_walk([2, 2, 1, 1, 2, 4]).ending["id"]}
        self.assertEqual(len(endings), 3, "三条路线未分化出三个结局: %s" % endings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
