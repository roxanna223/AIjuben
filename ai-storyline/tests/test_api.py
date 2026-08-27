"""Web API 测试（FastAPI TestClient）。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import server.app as server_app
from server.app import app, SESSIONS

client = TestClient(app)


class TestApi(unittest.TestCase):
    def setUp(self):
        SESSIONS.clear()

    def test_health(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_create_session_and_finish_walk(self):
        # 开局
        r = client.post("/api/sessions")
        self.assertEqual(r.status_code, 200)
        view = r.json()
        self.assertTrue(view["sid"].startswith("s_"))
        self.assertFalse(view["finished"])
        self.assertIn("narrative", view["scene"])
        sid = view["sid"]

        # 路径A：谨慎利己 → 成为乘客
        for idx in (2, 2, 1, 3):
            r = client.post("/api/sessions/%s/turn" % sid, json={"choice_index": idx})
            self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["finished"])
        self.assertEqual(r.json()["ending"]["id"], "end_passenger")

        # 复盘
        r = client.get("/api/sessions/%s/recap" % sid)
        self.assertEqual(r.status_code, 200)
        recap = r.json()
        self.assertEqual(recap["ending"]["id"], "end_passenger")
        self.assertGreaterEqual(recap["event_count"], 10)
        self.assertIn("trust_lin", recap["stats"])

    def test_free_text_turn(self):
        r = client.post("/api/sessions")
        sid = r.json()["sid"]
        r = client.post("/api/sessions/%s/turn" % sid, json={"free_text": "我四处张望"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("narrative", r.json()["scene"])

    def test_invalid_choice_rejected(self):
        r = client.post("/api/sessions")
        sid = r.json()["sid"]
        r = client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 99})
        self.assertEqual(r.status_code, 400)

    def test_resume_after_restart(self):
        """模拟服务重启：清空内存会话，从持久化JSON恢复。"""
        r = client.post("/api/sessions")
        sid = r.json()["sid"]
        client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 1})
        SESSIONS.clear()  # 服务"重启"
        r = client.get("/api/sessions/%s" % sid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sid"], sid)
        self.assertTrue(r.json()["turn"] > 0)

    def test_static_frontend_served(self):
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("歧路", r.text)

    def test_story_list(self):
        r = client.get("/api/stories")
        self.assertEqual(r.status_code, 200)
        stories = {s["id"]: s for s in r.json()}
        self.assertIn("midnight-train", stories)
        self.assertIn("rule-tower", stories)
        self.assertGreaterEqual(stories["rule-tower"]["endings"], 3)

    def test_rule_tower_session_via_api(self):
        r = client.post("/api/sessions", json={"story_id": "rule-tower"})
        self.assertEqual(r.status_code, 200)
        view = r.json()
        self.assertEqual(view["story"]["id"], "rule-tower")
        sid = view["sid"]
        for idx in (1, 1, 2, 2, 1):   # 守序路线 → 逃出生天
            r = client.post("/api/sessions/%s/turn" % sid, json={"choice_index": idx})
        self.assertTrue(r.json()["finished"])
        self.assertEqual(r.json()["ending"]["id"], "end_escape")

    def test_turn_streaming_ndjson(self):
        r = client.post("/api/sessions")
        sid = r.json()["sid"]
        r = client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 1},
                        headers={"Accept": "application/x-ndjson"})
        self.assertEqual(r.status_code, 200)
        lines = [l for l in r.text.strip().split("\n") if l.strip()]
        evts = [json.loads(l) for l in lines]
        self.assertEqual(evts[-1]["type"], "done")
        self.assertIn("narrative", evts[-1]["view"]["scene"])
        self.assertEqual(evts[-1]["view"]["sid"], sid)

    def test_unknown_story_rejected(self):
        r = client.post("/api/sessions", json={"story_id": "nope"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
