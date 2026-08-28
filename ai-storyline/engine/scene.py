"""场景输出（SceneOutput）的对话体结构工具。

v0.3 起，场景正文从单段小说体 narrative 字符串升级为结构化 dialogue 数组：

    {"dialogue": [{"speaker": "<人物id|narrator>", "text": "台词"}, ...]}

- speaker 只能是剧本人物id（含主角 pc）或 "narrator"（旁白/环境叙述）；
- 前端按 speaker 渲染人物对话气泡（头像占位），后续可直接把占位替换为人物图片；
- 旧脚本/旧存档中的 narrative 字符串会被归一化为单条 narrator 行，保证兼容。
"""
from typing import Any, Dict, List

NARRATOR = "narrator"


def as_dialogue_lines(scene: Any) -> List[Dict[str, str]]:
    """把任意形态的场景正文归一化为对话行列表 [{speaker, text}]。

    优先取 dialogue 数组；缺失/为空时回退到旧版 narrative 字符串（单条旁白行）。
    """
    if not isinstance(scene, dict):
        return []
    raw = scene.get("dialogue")
    if isinstance(raw, list) and raw:
        lines: List[Dict[str, str]] = []
        for ln in raw:
            if not isinstance(ln, dict):
                continue
            sp = str(ln.get("speaker") or NARRATOR)
            tx = str(ln.get("text") or "").strip()
            if tx:
                lines.append({"speaker": sp, "text": tx})
        if lines:
            return lines
    narr = str(scene.get("narrative") or "").strip()
    if narr:
        return [{"speaker": NARRATOR, "text": narr}]
    return []


def dialogue_text(scene: Any) -> str:
    """对话行的纯文本合并（审查器/一致性检查/摘要/评审用）。"""
    return "\n".join("%s: %s" % (ln["speaker"], ln["text"]) for ln in as_dialogue_lines(scene))


def dialogue_len(scene: Any) -> int:
    """对话正文总字数（不含说话人标签）。"""
    return sum(len(ln["text"]) for ln in as_dialogue_lines(scene))
