"""故事导图（StoryGraph）测试：渐进解锁、选择分叉、自由输入节点、结局节点、持久化。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import server.app as server_app
from server.app import app, SESSIONS

client = TestClient(app)


class TestStoryGraph(unittest.TestCase):
    def setUp(self):
        SESSIONS.clear()
        server_app._rate_hits.clear()

    # ---------- 渐进解锁 ----------

    def test_start_unlocks_only_first_beat(self):
        """开局：导图只解锁第一个节拍节点，其余节拍绝不出现（防剧透）。"""
        view = client.post("/api/sessions").json()
        m = view["story_map"]
        self.assertEqual(len(m["nodes"]), 1)
        self.assertEqual(m["nodes"][0]["kind"], "beat")
        self.assertEqual(m["nodes"][0]["beat_id"], "b1")
        self.assertEqual(m["nodes"][0]["order"], 1)
        self.assertEqual(m["edges"], [])
        self.assertEqual(m["active_beat"], "b1")

    def test_choice_creates_labeled_edge(self):
        """选选项：解锁下一节拍节点，并用选项文案画一条 choice 边。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        view = client.post("/api/sessions/%s/turn" % sid,
                           json={"choice_index": 1}).json()
        m = view["story_map"]
        self.assertEqual(len(m["nodes"]), 2)
        self.assertEqual([n["kind"] for n in m["nodes"]], ["beat", "beat"])
        self.assertEqual(len(m["edges"]), 1)
        e = m["edges"][0]
        self.assertEqual(e["kind"], "choice")
        self.assertEqual(e["from"], "beat:b1")
        self.assertEqual(e["to"], m["nodes"][1]["id"])
        self.assertTrue(e["label"], "选项边应带所选选项文案")

    def test_free_text_creates_player_node(self):
        """自由输入（玩家自己写的剧情）：生成 free 节点并接上自主行动边。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        view = client.post("/api/sessions/%s/turn" % sid,
                           json={"free_text": "我四处张望，数了数车厢里的乘客"}).json()
        m = view["story_map"]
        free_nodes = [n for n in m["nodes"] if n["kind"] == "free"]
        self.assertEqual(len(free_nodes), 1)
        self.assertIn("我四处张望", free_nodes[0]["label"])
        self.assertEqual(free_nodes[0]["id"], "free:1")
        # 边：b1 →(自主行动) free:1 →(自然推进) 下一节拍
        kinds = [e["kind"] for e in m["edges"]]
        self.assertIn("free", kinds)
        free_edge = next(e for e in m["edges"] if e["kind"] == "free")
        self.assertEqual(free_edge["from"], "beat:b1")
        self.assertEqual(free_edge["to"], "free:1")
        self.assertEqual(free_edge["label"], "自主行动")
        adv = next(e for e in m["edges"] if e["kind"] == "advance")
        self.assertEqual(adv["from"], "free:1")
        self.assertEqual(adv["to"], "beat:b2")

    # ---------- 全流程：岔路与结局 ----------

    def test_full_walk_records_skips_and_ending(self):
        """通关：被跳过的节拍显示为空心岔路占位（不透露内容），结局为终点节点。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        for idx in (2, 2, 1, 3):   # 与 test_api 相同的金标准路径 → end_passenger
            view = client.post("/api/sessions/%s/turn" % sid,
                               json={"choice_index": idx}).json()
        self.assertTrue(view["finished"])
        m = view["story_map"]
        self.assertTrue(m["finished"])
        kinds = [n["kind"] for n in m["nodes"]]
        self.assertIn("skipped", kinds, "路径外节拍应以岔路占位出现")
        self.assertIn("ending", kinds, "通关后导图应有结局节点")
        ending_node = next(n for n in m["nodes"] if n["kind"] == "ending")
        self.assertEqual(ending_node["ending_id"], "end_passenger")
        self.assertIn(view["ending"]["name"], ending_node["label"])
        # 岔路占位绝不透露节拍内容
        for n in m["nodes"]:
            if n["kind"] == "skipped":
                self.assertEqual(n["label"], "未走上的岔路")
        # 每个 beat 节点都应有唯一 beat_id
        beat_ids = [n["beat_id"] for n in m["nodes"] if n["kind"] == "beat"]
        self.assertEqual(len(beat_ids), len(set(beat_ids)))

    def test_ending_node_connected_from_last_node(self):
        """结局节点有入边（导图连通到终点），且带上通向结局的最后一次选择。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        for idx in (2, 2, 1, 3):
            view = client.post("/api/sessions/%s/turn" % sid,
                               json={"choice_index": idx}).json()
        m = view["story_map"]
        ending_node = next(n for n in m["nodes"] if n["kind"] == "ending")
        ending_edge = next(e for e in m["edges"] if e["to"] == ending_node["id"])
        self.assertEqual(ending_edge["kind"], "choice")
        self.assertTrue(ending_edge["label"], "通向结局的边应带最后一次选择")
        self.assertEqual(m["last"], ending_node["id"])

    # ---------- 持久化与专用接口 ----------

    def test_map_survives_restart(self):
        """服务重启（内存清空）后从存档恢复：导图不丢。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 1})
        client.post("/api/sessions/%s/turn" % sid,
                    json={"free_text": "我盯着窗外的夜色发呆"})
        SESSIONS.clear()   # 模拟重启
        view = client.get("/api/sessions/%s" % sid).json()
        m = view["story_map"]
        # b1,b2 节拍 + free 自创节点 + 跳过占位 + 后续节拍 b4 = 5 节点
        self.assertEqual(len(m["nodes"]), 5)
        self.assertTrue(any(n["kind"] == "free" for n in m["nodes"]))
        self.assertTrue(any(n["kind"] == "skipped" for n in m["nodes"]))
        self.assertEqual(m["last"], "beat:b4")  # 恢复后仍能继续解锁

    def test_dedicated_map_endpoint(self):
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        r = client.get("/api/sessions/%s/map" % sid)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["sid"], sid)
        self.assertEqual(len(data["map"]["nodes"]), 1)
        self.assertEqual(data["map"]["nodes"][0]["beat_id"], "b1")

    def test_rule_tower_map_unlocks_progressively(self):
        """第二剧本同样适用（引擎零特判）。"""
        view = client.post("/api/sessions", json={"story_id": "rule-tower"}).json()
        sid = view["sid"]
        self.assertEqual(len(view["story_map"]["nodes"]), 1)
        for idx in (1, 1, 2, 2, 1):
            view = client.post("/api/sessions/%s/turn" % sid,
                               json={"choice_index": idx}).json()
        self.assertTrue(view["finished"])
        m = view["story_map"]
        self.assertIn("ending", [n["kind"] for n in m["nodes"]])


    def test_old_save_without_graph_fields_backfilled(self):
        """旧存档（无导图字段）：恢复时从节拍状态/事件账本回填已有路线。"""
        view = client.post("/api/sessions").json()
        sid = view["sid"]
        client.post("/api/sessions/%s/turn" % sid, json={"choice_index": 1})
        SESSIONS.clear()
        # 模拟旧版本存档：删除导图字段后落盘
        f = server_app.DATA_DIR / ("%s.json" % sid)
        d = json.loads(f.read_text(encoding="utf-8"))
        d.pop("graph_nodes", None)
        d.pop("graph_edges", None)
        d.pop("graph_last", None)
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        # 恢复：导图应回填出 b1→b2 与选项边
        view = client.get("/api/sessions/%s" % sid).json()
        m = view["story_map"]
        self.assertEqual([(n["kind"], n["beat_id"]) for n in m["nodes"]],
                         [("beat", "b1"), ("beat", "b2")])
        self.assertEqual(len(m["edges"]), 1)
        self.assertEqual(m["edges"][0]["kind"], "choice")
        self.assertEqual(m["edges"][0]["from"], "beat:b1")
        self.assertEqual(m["edges"][0]["to"], "beat:b2")
        self.assertTrue(m["edges"][0]["label"])
        self.assertEqual(m["last"], "beat:b2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
