"""安全与行为采集测试(需独立进程运行,环境变量在 import 前注入)。

运行方式(单独执行,勿混入主测试套件):
  .venv/bin/python -m unittest discover -s tests -p "security_tests.py" -v

原因: server.app 在 import 时读取环境变量,与其他测试模块共用进程会导致配置互相污染。
"""
import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="qilu_sec_")
os.environ["STORY_MODE"] = "mock"
os.environ["QILU_EVENTS_FILE"] = os.path.join(_TMP, "events.jsonl")
os.environ["EVENT_SALT"] = "test-salt"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["RATE_LIMIT_PER_MIN"] = "5"
os.environ["RATE_CREATE_PER_MIN"] = "3"
os.environ["RATE_TURN_PER_MIN"] = "3"
os.environ["MAX_MEM_SESSIONS"] = "8"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
import server.app as server_app  # noqa: E402
from server.app import app, SESSIONS  # noqa: E402
from server import events  # noqa: E402

client = TestClient(app)


class TestSecurity(unittest.TestCase):
    def setUp(self):
        SESSIONS.clear()
        server_app._rate_hits.clear()

    def test_01_events_written_and_ip_hashed(self):
        r = client.get("/")  # page_view
        self.assertEqual(r.status_code, 200)
        r = client.post("/api/sessions")  # session_create
        self.assertEqual(r.status_code, 200)
        sid = r.json()["sid"]
        r = client.post("/api/sessions/%s/turn" % sid,
                        json={"choice_index": 1})  # turn
        self.assertEqual(r.status_code, 200)

        rows = events.read_recent(20)
        actions = {row["action"] for row in rows}
        self.assertIn("page_view", actions)
        self.assertIn("session_create", actions)
        self.assertIn("turn", actions)
        for row in rows:
            if row["action"] == "session_create":
                self.assertEqual(row["meta"]["sid"], sid)
            if row.get("ip_h"):
                # IP 必须脱敏:16位hex哈希,不能出现点分十进制原文
                self.assertRegex(row["ip_h"], r"^[0-9a-f]{16}$")
        # 事件里不允许出现任何原始IP形态
        blob = "\n".join(str(r_) for r_ in rows)
        self.assertNotRegex(blob, r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

    def test_02_rate_limit_429(self):
        codes = [client.get("/api/health").status_code for _ in range(7)]
        self.assertEqual(codes[0], 200)
        self.assertIn(429, codes)
        self.assertEqual(codes[-1], 429)

    def test_03_admin_metrics_auth(self):
        self.assertEqual(client.get("/api/admin/metrics").status_code, 403)
        self.assertEqual(client.get(
            "/api/admin/metrics",
            headers={"X-Admin-Token": "wrong"}).status_code, 403)
        r = client.get("/api/admin/metrics",
                       headers={"X-Admin-Token": "test-admin-token"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("sessions", r.json())

    def test_04_admin_events_auth_and_filter(self):
        r = client.get("/api/admin/events",
                       headers={"X-Admin-Token": "test-admin-token"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("events", r.json())
        r = client.get("/api/admin/events",
                       headers={"X-Admin-Token": "test-admin-token"},
                       params={"action": "page_view"})
        rows = r.json()["events"]
        self.assertTrue(all(x["action"] == "page_view" for x in rows))

    def test_05_create_rate_limit(self):
        # 开局接口独立限流(3次/分):连点刷开局会被429拦截,防止重复烧token
        codes = [client.post("/api/sessions").status_code for _ in range(4)]
        self.assertEqual(codes[0], 200)
        self.assertIn(429, codes)
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main(verbosity=2)
