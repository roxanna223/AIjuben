"""体验基线测量：从会话存档计算关键指标，对照调研基线验收。

用法：
  python3 metrics.py [--dir data/sessions] [--story midnight-train]

指标与目标（PRD §6 / 架构文档 §9）：
  第1章完读率 ≥60%（点点穿书内部考核线）
  结局达成率   ≥50%（自定，防烂尾验收线）
  结局路线分化 ≥3  （本产品核心卖点）
  平均会话时长 ≥15分钟（PRD目标）
"""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

TARGETS = {
    "ch1_complete_rate": {"value": 0.60, "desc": "第1章完读率≥60%（点点穿书考核线）"},
    "finish_rate": {"value": 0.50, "desc": "结局达成率≥50%（自定，防烂尾验收线）"},
    "min_distinct_endings": {"value": 3, "desc": "结局路线分化度≥3（本产品核心卖点）"},
    "avg_duration_min": {"value": 15.0, "desc": "单次会话时长≥15分钟（PRD目标）"},
}


def load_sessions(data_dir: str, story_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    for f in sorted(Path(data_dir).glob("s_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if story_id and d.get("story_id") != story_id:
            continue
        sessions.append(d)
    return sessions


def compute_metrics(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(sessions)
    finished = [s for s in sessions if s.get("finished")]
    # 第1章完读率的代理：b1节拍已完成的会话占比（节拍是章的骨架）
    b1_done = [s for s in sessions
               if any(st.get("status") == "done" for b, st in s.get("beat_status", {}).items()
                      if b == "b1")]
    endings = Counter(s.get("ending", {}).get("id", "?") for s in finished)
    paths: Counter = Counter()
    for s in sessions:
        done = [b for b, st in sorted(s.get("beat_status", {}).items(),
                                      key=lambda kv: kv[1].get("turn", 0))
                if st.get("status") == "done"]
        if done:  # 开局即弃的空路径不计入路线多样性
            paths[tuple(done)] += 1
    durations = []
    for s in finished:
        t0, t1 = s.get("started_at"), s.get("last_active_at")
        if t0 and t1 and t1 >= t0:
            durations.append((t1 - t0) / 60.0)
    fallbacks = sum(len(s.get("fallback_flags", [])) for s in sessions)
    return {
        "sessions": n,
        "finished": len(finished),
        "finish_rate": len(finished) / n if n else 0.0,
        "ch1_complete_rate": len(b1_done) / n if n else 0.0,
        "endings": dict(endings),
        "distinct_endings": len(endings),
        "distinct_paths": len(paths),
        "avg_duration_min": statistics.mean(durations) if durations else 0.0,
        "avg_turns": statistics.mean([s.get("turn", 0) for s in sessions]) if n else 0.0,
        "fallback_count": fallbacks,
    }


def verdict(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = [
        ("第1章完读率", m["ch1_complete_rate"], TARGETS["ch1_complete_rate"]["value"], "≥"),
        ("结局达成率", m["finish_rate"], TARGETS["finish_rate"]["value"], "≥"),
        ("结局路线分化度", m["distinct_endings"], TARGETS["min_distinct_endings"]["value"], "≥"),
        ("平均会话时长(分钟)", m["avg_duration_min"], TARGETS["avg_duration_min"]["value"], "≥"),
    ]
    return [{"name": name, "value": val, "target": t, "op": op,
             "pass": (val >= t) if op == "≥" else (val <= t)}
            for name, val, t, op in checks]


def report(m: Dict[str, Any]) -> str:
    lines = [
        "体验基线验收报告",
        "=" * 46,
        "会话总数: %d ｜ 完成结局: %d ｜ 平均回合数: %.1f" % (
            m["sessions"], m["finished"], m["avg_turns"]),
        "生成降级次数: %d" % m["fallback_count"],
        "-" * 46,
    ]
    for c in verdict(m):
        lines.append("[%s] %s: %.3f (目标 %s %.1f)" % (
            "PASS" if c["pass"] else "FAIL", c["name"], c["value"], c["op"], c["target"]))
    lines.append("-" * 46)
    lines.append("结局分布: %s" % (m["endings"] or "无"))
    lines.append("不同剧情路径数: %d" % m["distinct_paths"])
    lines.append("=" * 46)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="体验基线测量")
    ap.add_argument("--dir", default="data/sessions")
    ap.add_argument("--story", default=None)
    args = ap.parse_args()
    sessions = load_sessions(args.dir, args.story)
    m = compute_metrics(sessions)
    print(report(m))


if __name__ == "__main__":
    main()
