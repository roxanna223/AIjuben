#!/usr/bin/env python3
"""LLM-as-judge 自动质量抽检：多局随机走查 + 每场景四维打分。

这是架构文档§9"人工小样本打分"的自动化替身——由评审模型按统一量表评分，
结果可重复、可对比；上线后仍需真人抽检交叉验证。

用法：
  .venv/bin/python scripts/judge_quality.py --story midnight-train --runs 2 --seed 42
输出：data/quality/{story}.json + 控制台汇总
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

_env = BASE / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from engine.constitution import Constitution
from engine.scene import dialogue_text
from engine.state import WorldState
from engine.pipeline import Pipeline, build_provider

JUDGE_PROMPT = (
    "你是互动叙事作品评审。请对下面这段剧情场景按4个维度打1-5分（1=差，5=极好）：\n"
    "- consistency: 与已知设定/前文的一致性\n"
    "- style: 文风与题材基调的贴合度\n"
    "- choices: 选项的分化度与可玩性\n"
    "- surprise: 惊喜度/戏剧张力\n"
    "只输出JSON：{\"consistency\":5,\"style\":5,\"choices\":5,\"surprise\":5,\"comment\":\"一句话评语\"}\n"
    "【场景】\n%s"
)

DIMS = ["consistency", "style", "choices", "surprise"]


def judge_scene(provider, narrative: str):
    try:
        out = provider.generate("你是叙事评审，只输出JSON。", JUDGE_PROMPT % narrative[:800])
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return None
        d = json.loads(m.group(0))
        return {k: int(d.get(k, 0)) for k in DIMS}, d.get("comment", "")
    except Exception as e:  # noqa: BLE001
        print("[warn] 评审调用失败: %s" % e)
        return None


def run_walk(c: Constitution, provider, rng: random.Random):
    state = WorldState(c.story_id, c.char_defs(), c.global_defs(), c.ten_dims(),
                       session_id="s_judge_%s" % rng.randrange(10 ** 6))
    p = Pipeline(c, provider, state)
    collected = []
    scene = p.start()
    steps = 0
    while not state.finished and steps < 30:
        collected.append({"beat": scene.get("scene_meta", {}).get("beat_id"),
                          "narrative": dialogue_text(scene)})
        opts = scene.get("choices", [])
        if not opts:
            break
        scene = p.turn(choice_index=rng.randint(1, len(opts)))
        steps += 1
    return collected, state


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM-as-judge 质量抽检")
    ap.add_argument("--story", default="midnight-train")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    c = Constitution.load(str(BASE / "stories" / ("%s.json" % args.story)))
    provider = build_provider("llm")
    rng = random.Random(args.seed)

    print("开始抽检《%s》：%d局随机走查（seed=%d）…" % (c.title, args.runs, args.seed))
    runs = []
    for run in range(args.runs):
        t0 = time.time()
        scenes, state = run_walk(c, provider, rng)
        judged = []
        for sc in scenes:
            r = judge_scene(provider, sc["narrative"])
            if r:
                scores, comment = r
                judged.append({"beat": sc["beat"], "scores": scores, "comment": comment})
        runs.append({
            "ending": (state.ending or {}).get("id"),
            "ending_name": (state.ending or {}).get("name"),
            "scenes": len(scenes),
            "judged": judged,
            "fallback_flags": state.fallback_flags,
            "seconds": round(time.time() - t0, 1),
        })
        print("  第%d局：%d场景/%d评审完成，结局=%s，耗时%.0fs" % (
            run + 1, len(scenes), len(judged),
            (state.ending or {}).get("name", "未完成"), time.time() - t0))

    # 聚合
    totals = {k: [] for k in DIMS}
    for run in runs:
        for j in run["judged"]:
            for k in DIMS:
                totals[k].append(j["scores"][k])
    agg = {k: round(sum(v) / len(v), 2) if v else None for k, v in totals.items()}
    agg["n_scenes_judged"] = len(totals[DIMS[0]])

    report = {"story": c.story_id, "title": c.title, "seed": args.seed,
              "runs": runs, "aggregate": agg}
    out_dir = BASE / "data" / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ("%s.json" % c.story_id)).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 《%s》质量抽检汇总（LLM-as-judge，%d个场景）=====" % (
        c.title, agg["n_scenes_judged"]))
    print("一致性 consistency: %s | 文风 style: %s | 选项 choices: %s | 惊喜度 surprise: %s" % (
        agg["consistency"], agg["style"], agg["choices"], agg["surprise"]))
    print("结局分布: %s" % {r["ending_name"]: sum(1 for x in runs if x["ending_name"] == r["ending_name"]) for r in runs})
    print("详细报告: data/quality/%s.json" % c.story_id)


if __name__ == "__main__":
    main()
