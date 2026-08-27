#!/usr/bin/env python3
"""命令行试玩器（Phase 0）。

用法：
  python3 play_cli.py                       # Mock 模式（无需API Key）
  python3 play_cli.py --mode llm            # 真实LLM（需 LLM_API_KEY 环境变量）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.constitution import Constitution
from engine.state import WorldState
from engine.pipeline import Pipeline, build_provider


def print_scene(state: WorldState, scene: dict) -> None:
    meta = scene.get("scene_meta", {})
    print("\n" + "=" * 56)
    print("第%s章 · 回合%s · beat: %s" % (state.chapter, state.turn, meta.get("beat_id", "?")))
    print("=" * 56)
    print(scene.get("narrative", ""))
    choices = scene.get("choices", [])
    if choices:
        print("\n—— 你的选择 ——")
        for i, ch in enumerate(choices, 1):
            tag = ",".join("%s%+g" % (k, v) for k, v in (ch.get("tendency") or {}).items()) or "—"
            print("  %d. %s  [倾向: %s]" % (i, ch["text"], tag))
    stats = ", ".join("%s=%g" % (k, v) for k, v in sorted(state.stats.items()))
    tend = ", ".join("%s=%+.2f" % (k, v) for k, v in sorted(state.tendencies.items()))
    print("\n数值: %s | 倾向: %s" % (stats, tend))


def print_ending(state: WorldState) -> None:
    print("\n" + "#" * 56)
    if state.ending:
        print("结局【%s · %s】" % (state.ending.get("name"), state.ending.get("type")))
    else:
        print("（未达成结局）")
    path = [b for b, st in state.beat_status.items() if st["status"] in ("done",)]
    print("你的节拍路径: %s" % " → ".join(path))
    print("你的倾向画像: %s" % ", ".join("%s=%+.2f" % (k, v) for k, v in sorted(state.tendencies.items())))
    print("确认事实 %d 项 / 事件账本 %d 条 / 生成降级 %d 次" % (
        len(state.facts), len(state.event_log), len(state.fallback_flags)))
    print("#" * 56)


def main() -> None:
    ap = argparse.ArgumentParser(description="「歧路」引擎试玩")
    ap.add_argument("--story", default="stories/midnight-train.json")
    ap.add_argument("--mode", default="mock", choices=["mock", "llm"])
    ap.add_argument("--mock-script", default=None, help="Mock脚本路径（默认同名校名.mock.json）")
    args = ap.parse_args()

    c = Constitution.load(args.story)
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims())
    script = args.mock_script or args.story.replace(".json", ".mock.json")
    provider = build_provider(args.mode, script)
    p = Pipeline(c, provider, state)

    scene = p.start()
    while True:
        print_scene(state, scene)
        if state.finished:
            break
        raw = input("\n你的选择(输入序号；q退出): ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            print("已退出。")
            return
        if raw.isdigit():
            scene = p.turn(choice_index=int(raw))
        else:
            scene = p.turn(free_text=raw)
    print_ending(state)


if __name__ == "__main__":
    main()
