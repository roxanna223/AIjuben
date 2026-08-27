#!/usr/bin/env python3
"""真实LLM金标准走查：按预定选择序列跑完一局，打印全部生成内容并汇总用量/延迟。

用法：
  .venv/bin/python scripts/llm_walkthrough.py --story midnight-train --path 1,1,1,2,1,1,1
  （读取 .env 中的 LLM_API_KEY；--mock 可切换确定性模式对照）
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

# 读取 .env（不覆盖已有环境变量）
_env = BASE / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from engine.constitution import Constitution
from engine.state import WorldState
from engine.pipeline import Pipeline, build_provider


def main() -> None:
    ap = argparse.ArgumentParser(description="真实LLM金标准走查")
    ap.add_argument("--story", default="midnight-train")
    ap.add_argument("--path", default="1,1,1,2,1,1,1")
    ap.add_argument("--mock", action="store_true", help="用确定性Mock模式对照")
    args = ap.parse_args()

    c = Constitution.load(str(BASE / "stories" / ("%s.json" % args.story)))
    sid = "s_" + uuid.uuid4().hex[:6]
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims(),
                       session_id=sid)
    provider = (build_provider("mock", str(BASE / "stories" / ("%s.mock.json" % args.story)))
                if args.mock else build_provider("llm"))
    p = Pipeline(c, provider, state)

    choices = [int(x) for x in args.path.split(",") if x.strip()]
    t0 = time.time()
    scene = p.start()
    i = 0
    while True:
        meta = scene.get("scene_meta", {})
        print("\n" + "=" * 64)
        print("[beat %s] 第%s章 · 回合%s · 地点: %s" % (
            meta.get("beat_id"), state.chapter, state.turn, meta.get("location", "?")))
        print("=" * 64)
        print(scene.get("narrative", ""))
        for j, ch in enumerate(scene.get("choices", []), 1):
            tag = ",".join("%s%+g" % (k, v) for k, v in (ch.get("tendency") or {}).items()) or "—"
            print("  %d. %s  [%s]" % (j, ch["text"], tag))
        print("  [数值] %s | [倾向] %s" % (
            {k: round(v, 1) for k, v in state.stats.items()},
            {k: round(v, 2) for k, v in state.tendencies.items()}))
        if state.finished or i >= len(choices):
            break
        idx = choices[i]
        i += 1
        opts = scene.get("choices", [])
        if not 1 <= idx <= len(opts):
            print("\n>>> 脚本选项%d越界（本场共%d个选项），走查提前结束" % (idx, len(opts)))
            break
        print("\n>>> 玩家选择 %d: %s" % (idx, opts[idx - 1]["text"]))
        scene = p.turn(choice_index=idx)

    print("\n" + "#" * 64)
    print("结局: %s" % json.dumps(state.ending, ensure_ascii=False))
    print("节拍路径: %s" % [b for b, st in sorted(state.beat_status.items(),
                                              key=lambda kv: kv[1].get("turn", 0))
                            if st["status"] == "done"])
    print("生成降级: %s" % (state.fallback_flags or "无"))

    # 用量汇总（按本局sid过滤 usage.jsonl）
    uf = BASE / "data" / "usage.jsonl"
    n = tin = tout = tlat = 0
    if uf.exists():
        for line in uf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("sid") == sid:
                n += 1
                tin += d.get("prompt_tokens", 0)
                tout += d.get("completion_tokens", 0)
                tlat += d.get("latency_ms", 0)
    print("本局LLM调用 %d 次 | 输入 %d tok | 输出 %d tok | 生成总延迟 %.1fs | 墙钟 %.1fs"
          % (n, tin, tout, tlat / 1000.0, time.time() - t0))


if __name__ == "__main__":
    main()
