"""体验基线测量与用量埋点测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import metrics
from engine.llm import OpenAICompatProvider
from fastapi.testclient import TestClient

from server.app import app, SESSIONS

client = TestClient(app)


def fake_session(sid, finished, ending, beats_done, turns=8, minutes=12):
    import time
    now = time.time()
    return {
        "session_id": sid, "story_id": "midnight-train",
        "turn": turns, "chapter": 2,
        "started_at": now - minutes * 60, "last_active_at": now,
        "stats": {"trust_lin": 40, "sanity": 50},
        "tendencies": {"caution": 0, "empathy": 0, "order": 0, "curiosity": 0, "trust": 0},
        "facts": [], "closed_facts": [],
        "beat_status": {b: {"status": "done", "turn": i + 1} for i, b in enumerate(beats_done)},
        "endings_viable": [], "memory": {"recent": [], "chapter_summary": [], "global_summary": []},
        "event_log": [], "current_scene": None,
        "finished": finished,
        "ending": {"id": ending, "name": ending, "type": "good"} if ending else None,
        "fallback_flags": [],
    }


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _write(self, d):
        with open(os.path.join(self.tmp, "%s.json" % d["session_id"]), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def test_compute_metrics(self):
        self._write(fake_session("s_a", True, "end_truth", ["b1", "b2", "b4", "b6"], minutes=20))
        self._write(fake_session("s_b", True, "end_passenger", ["b1", "b2", "b4", "b6"], minutes=10))
        self._write(fake_session("s_c", True, "end_conductor", ["b1", "b2", "b4", "b5", "b6"], minutes=18))
        self._write(fake_session("s_d", False, None, [], turns=1, minutes=2))  # 开局即弃
        m = metrics.compute_metrics(metrics.load_sessions(self.tmp, "midnight-train"))
        self.assertEqual(m["sessions"], 4)
        self.assertEqual(m["finished"], 3)
        self.assertAlmostEqual(m["finish_rate"], 0.75)
        self.assertAlmostEqual(m["ch1_complete_rate"], 0.75)  # s_d 未过b1
        self.assertEqual(m["distinct_endings"], 3)
        self.assertEqual(m["distinct_paths"], 2)  # 前两条同路径，第三条多b5
        self.assertAlmostEqual(m["avg_duration_min"], 16.0)
        self.assertEqual(m["fallback_count"], 0)
        verdicts = {c["name"]: c["pass"] for c in metrics.verdict(m)}
        self.assertTrue(verdicts["第1章完读率"])
        self.assertTrue(verdicts["结局达成率"])
        self.assertTrue(verdicts["结局路线分化度"])
        self.assertTrue(verdicts["平均会话时长(分钟)"])

    def test_missing_timestamps_tolerated(self):
        d = fake_session("s_e", True, "end_truth", ["b1"], turns=2)
        d.pop("started_at")
        self._write(d)
        m = metrics.compute_metrics(metrics.load_sessions(self.tmp, "midnight-train"))
        self.assertEqual(m["sessions"], 1)
        self.assertEqual(m["avg_duration_min"], 0.0)

    def test_report_smoke(self):
        self._write(fake_session("s_a", True, "end_truth", ["b1"], minutes=30))
        text = metrics.report(metrics.compute_metrics(metrics.load_sessions(self.tmp)))
        self.assertIn("体验基线验收报告", text)
        self.assertIn("PASS", text)


class TestUsageParse(unittest.TestCase):
    def test_parse_usage(self):
        u = OpenAICompatProvider.parse_usage({
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300}
        }, latency_ms=456.7)
        self.assertEqual(u["prompt_tokens"], 1200)
        self.assertEqual(u["completion_tokens"], 300)
        self.assertEqual(u["latency_ms"], 456.7)

    def test_parse_usage_none(self):
        self.assertIsNone(OpenAICompatProvider.parse_usage({}))


class TestHistoryApi(unittest.TestCase):
    def setUp(self):
        SESSIONS.clear()

    def test_history_contains_scenes_and_choices(self):
        r = client.post("/api/sessions")
        sid = r.json()["sid"]
        client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 1})
        r = client.get("/api/sessions/%s" % sid)
        view = r.json()
        kinds = [h["kind"] for h in view["history"]]
        self.assertIn("narr", kinds)
        self.assertIn("choice", kinds)
        # 最后一个条目应是当前场景正文
        self.assertEqual(view["history"][-1]["kind"], "narr")
        self.assertEqual(view["history"][-1]["text"], view["scene"]["narrative"])

    def test_admin_metrics_endpoint(self):
        r = client.get("/api/admin/metrics")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("sessions", body)
        self.assertIn("verdict", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
