"""工程化校验 CLI（Content Validation Scale · 构建期 + 审计期）。

校验口径 = 内置规则插件 + 剧本宪法 `validation` 段的情景化声明（剧情点/幅度/理由禁用词/事实出处），
见 engine/validation.py。同一套量表三种运行环境：运行期（流水线自动）、构建期（本脚本）、审计期（本脚本）。

用法：
  # 构建期：校验剧本宪法 validation 段 + mock 脚本全场景（防止坏内容进生产）
  python scripts/validate_content.py --story midnight-train --mock

  # 审计期：离线扫描历史会话事件账本，追查"数值出发点/剧情出发点"违规
  python scripts/validate_content.py --story midnight-train --sessions data/sessions

退出码：0=全部通过；1=存在 error（构建期拦截/审计发现违规）。
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.constitution import Constitution
from engine.validation import ValidationScale

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _print_report(title: str, rep, indent: str = "  ") -> int:
    errs, warns = len(rep.errors), len(rep.warnings)
    print("%s%s: verdict=%s score=%d errors=%d warnings=%d"
          % (indent, title, rep.verdict(), rep.score(), errs, warns))
    for f in rep.findings:
        tag = "✗" if f.severity == "error" else "△"
        print("%s  %s [%s/%s] %s" % (indent, tag, f.rule_id, f.dimension, f.detail))
    return errs


def validate_mock(story_id: str) -> int:
    """构建期：宪法 validation 段已在加载时校验；此处全量校验 mock 场景。"""
    story_path = os.path.join(BASE, "stories", "%s.json" % story_id)
    mock_path = os.path.join(BASE, "stories", "%s.mock.json" % story_id)
    if not os.path.exists(mock_path):
        print("[warn] 未找到 mock 脚本: %s" % mock_path)
        return 0
    c = Constitution.load(story_path)
    scale = ValidationScale(c)
    script = json.load(open(mock_path, encoding="utf-8"))
    total_err = 0
    print("== 构建期校验: %s (%d 个场景) ==" % (c.title, len(script.get("scenes", {}))))
    for bid in sorted(script.get("scenes", {})):
        rep = scale.check_scene(script["scenes"][bid])
        total_err += _print_report("beat %s" % bid, rep)
    if not script.get("scenes"):
        print("[warn] mock 脚本无 scenes")
    print("== 构建期结果: %s ==" % ("通过" if total_err == 0 else "存在 %d 条 error" % total_err))
    return 1 if total_err else 0


def audit_sessions(story_id: str, data_dir: str) -> int:
    """审计期：重建会话事件账本中的变化，逐条校验出发点。"""
    c = Constitution.load(os.path.join(BASE, "stories", "%s.json" % story_id))
    scale = ValidationScale(c)
    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    if not files:
        print("[warn] 无会话文件: %s" % data_dir)
        return 0
    total_err = total_warn = total_sessions = 0
    print("== 审计期: %s (%d 个会话文件) ==" % (c.title, len(files)))
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("story_id") != story_id:
            continue
        rep = scale.audit_event_log(d)
        if rep.findings:
            total_sessions += 1
            errs = _print_report(os.path.basename(f), rep)
            total_err += errs
            total_warn += len(rep.warnings)
    print("== 审计期结果: %d 个会话存在违规, error=%d warn=%d =="
          % (total_sessions, total_err, total_warn))
    return 1 if total_err else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="工程化校验 CLI（构建期/审计期）")
    ap.add_argument("--story", required=True, help="剧本ID，如 midnight-train")
    ap.add_argument("--mock", action="store_true", help="构建期：校验 mock 脚本全场景")
    ap.add_argument("--sessions", metavar="DIR", help="审计期：扫描会话存档目录")
    args = ap.parse_args()
    rc = 0
    if args.mock:
        rc |= validate_mock(args.story)
    if args.sessions:
        rc |= audit_sessions(args.story, args.sessions)
    if not args.mock and not args.sessions:
        ap.error("至少指定 --mock 或 --sessions 之一")
    return rc


if __name__ == "__main__":
    sys.exit(main())
