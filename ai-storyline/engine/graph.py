"""故事导图（StoryGraph）：玩家可见的渐进解锁路线图。

设计原则（延续"AI只负责写，确定性代码负责管"的铁律，导图零AI参与）：
1. 渐进解锁：节点只在玩家真正到达时出现——
   - 节拍激活（到达该剧情）→ beat 节点；
   - 玩家自由输入产生的剧情 → free 节点（玩家自己编写的剧情）；
   - 结局达成 → ending 节点；
   未到达的节拍/结局绝不出现（防剧透）。
2. 选择即岔路：玩家在节点上做的每次选择都记录为一条有向边
   （from 上一节点 → to 下一节点，标签=所选选项文案）；
   节拍因条件/倾向未满足而被跳过时，挂一个空心"岔路"占位节点
   （不透露节拍内容，只表示"这里存在另一条路"）。
3. 全量落盘：nodes/edges 随会话存档持久化，断线续玩后导图原样恢复。
"""
from typing import Any, Dict, Optional

from .state import WorldState


def _short(text: str, n: int = 26) -> str:
    """节点标题截断（防止长文本撑爆导图节点）。"""
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


class StoryGraph:
    """确定性导图账本：只操作 WorldState 上的 graph_* 字段，不调用AI。"""

    def __init__(self, state: WorldState, constitution: Any = None):
        self.s = state
        self.c = constitution
        self.pending_label: Optional[str] = None  # 上一选择文案，等下一节点出现时画边
        # 旧存档兼容：无导图字段但有节拍状态 → 从节拍/事件账本回填已有路线
        if not self.s.graph_nodes and self.s.beat_status and self.c is not None:
            self._backfill()

    def _backfill(self) -> None:
        """旧存档回填：已完成/进行中的节拍重建为节点，节拍间的选择重建为边。"""
        done = [b for b in self.c.beats
                if self.s.beat_status.get(b["id"], {}).get("status") in ("done", "active")]
        done.sort(key=lambda b: self.s.beat_status[b["id"]].get("turn", 0))
        choices = sorted((e for e in self.s.event_log if e["type"] == "choice"),
                         key=lambda e: e["turn"])
        prev = None
        for b in done:
            st = self.s.beat_status[b["id"]]
            nid = "beat:" + b["id"]
            self.s.graph_nodes.append({"id": nid, "kind": "beat", "beat_id": b["id"],
                                       "label": _short(b.get("must_happen", ""), 26),
                                       "order": b.get("order"), "turn": st.get("turn")})
            if prev:
                # 边标签 = 触发本节点的那次选择（选择回合 == 本节点激活回合）
                label = next((e.get("payload", {}).get("choice", "")
                              for e in choices if e["turn"] == st.get("turn", 0)), "")
                self.s.graph_edges.append({"from": prev, "to": nid, "label": label,
                                           "kind": "choice" if label else "advance",
                                           "turn": st.get("turn", 0)})
            prev = nid
        self.s.graph_last = prev

    # ---------- 对外事件（由导演/流水线调用） ----------

    def on_choice(self, text: str) -> None:
        """玩家选了某个选项：记下文案，下一节点激活时作为边的标签。"""
        self.pending_label = (text or "").strip()

    def on_free(self, text: str) -> None:
        """玩家自由输入（自己编写的剧情）：立即生成一个 free 节点。"""
        text = (text or "").strip()
        if not text:
            return
        seq = sum(1 for n in self.s.graph_nodes if n["kind"] == "free") + 1
        nid = "free:%d" % seq
        self._add_node({"id": nid, "kind": "free", "label": _short(text, 26),
                        "full": _short(text, 60), "turn": self.s.turn})
        self._edge(self.s.graph_last, nid, "自主行动", "free")
        self.s.graph_last = nid
        self.pending_label = None   # 自由输入的承接边走 advance（无选项标签）

    def on_beat_activated(self, beat: Dict[str, Any]) -> None:
        """节拍被导演激活（玩家到达该剧情）→ 解锁 beat 节点。"""
        nid = "beat:" + beat["id"]
        if not self._has_node(nid):
            self._add_node({"id": nid, "kind": "beat", "beat_id": beat["id"],
                            "label": _short(beat.get("must_happen", ""), 26),
                            "order": beat.get("order"), "turn": self.s.turn})
        # 首次激活画边（重试已存在节点时不重复画边）
        if self.s.graph_last != nid:
            self._edge(self.s.graph_last, nid, self.pending_label,
                       "choice" if self.pending_label else "advance")
        self.pending_label = None
        self.s.graph_last = nid

    def on_beat_skipped(self, beat: Dict[str, Any]) -> None:
        """节拍被跳过（条件/倾向未满足）→ 空心"岔路"占位（不透露剧情内容）。"""
        nid = "skip:" + beat["id"]
        if self._has_node(nid):
            return
        self._add_node({"id": nid, "kind": "skipped", "beat_id": beat["id"],
                        "label": "未走上的岔路", "turn": self.s.turn})
        self._edge(self.s.graph_last, nid, "未选择", "skip")

    def on_ending(self, ending: Dict[str, Any]) -> None:
        """结局判定 → ending 节点（导图终点）；带上玩家通向结局的最后一次选择。"""
        nid = "ending:" + (ending.get("id") or "end")
        if self._has_node(nid):
            return
        self._add_node({"id": nid, "kind": "ending",
                        "label": ending.get("name") or "结局",
                        "ending_id": ending.get("id"), "turn": self.s.turn})
        label = self.pending_label or ""
        self._edge(self.s.graph_last, nid, label, "choice" if label else "advance")
        self.pending_label = None
        self.s.graph_last = nid

    # ---------- 内部 ----------

    def _has_node(self, nid: str) -> bool:
        return any(n["id"] == nid for n in self.s.graph_nodes)

    def _add_node(self, node: Dict[str, Any]) -> None:
        node["kind"] = node.get("kind", "beat")
        self.s.graph_nodes.append(node)
        self.s.log("graph_node", {"id": node["id"], "kind": node["kind"]})

    def _edge(self, src: Optional[str], dst: str, label: Optional[str], kind: str) -> None:
        if not src or src == dst:
            return
        self.s.graph_edges.append({
            "from": src, "to": dst,
            "label": (label or "").strip(),
            "kind": kind, "turn": self.s.turn,
        })
        self.s.log("graph_edge", {"from": src, "to": dst, "label": (label or "").strip()})

    # ---------- 查询 ----------

    def view(self) -> Dict[str, Any]:
        """当前导图快照（供API下发）。"""
        active = next((b for b, st in self.s.beat_status.items()
                       if st.get("status") == "active"), None)
        return {
            "nodes": list(self.s.graph_nodes),
            "edges": list(self.s.graph_edges),
            "last": self.s.graph_last,
            "active_beat": active,
            "finished": self.s.finished,
            "ending": self.s.ending,
        }
