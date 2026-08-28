# Cursor 调研 01：世界观设定工具

> 日期：2026-08-26  
> 目标：自然语言描述 → AI 辅助生成完整世界观；支持自动补齐与多轮完善；最终输出**固定格式基本盘字段**，字段填完即进入下一步。

---

## 一、结论先行

**能做到。** 没有单一产品同时覆盖「多轮访谈补齐 + 强制字段门禁 + 可编程导出」，但自建管线成熟：

**推荐路线 = 访谈 Skill（一次一问）+ JSON Schema 基本盘（三态字段）+ Lorebook 式记忆注入 + 可选第三方对照验证（Dunia / Novelcrafter / Loreum）。**

---

## 二、需求拆解

| 子需求 | 关键点 | 现成覆盖度 |
|---|---|---|
| 自然语言开世界 | 一句话/一段话 → 结构化初稿 | 高（Dunia、Inkfluence、Storyflow） |
| 自动补齐 | 未说清的部分 AI 补全并标「待确认」 | 中（LLM 强，产品少做门禁） |
| 多轮完善 | 记住已定稿、矛盾即时指出 | 中（开源 Skill 强，SaaS 偏单次） |
| 固定格式基本盘 | 字段齐 = 世界观冻结 | 低（需自建 Schema） |
| 一致性校验 | 改 A 不破坏 B | 中（Storyflow、Loreum、学术管线） |

---

## 三、工具盘点

### 3.1 生成与画布类

| 工具 | 特点 | 对本项目价值 | 价格量级 |
|---|---|---|---|
| **Dunia** | Creation Wizard 快出设定；可「玩进世界」压力测试 | 验证世界观是否扛得住互动 | 免费起 |
| **Storyflow** | 画布 Story Bible；AI 可读整板并查矛盾 | 可视化 lore/阵营/时间线 | ~$8/月起 |
| **Inkfluence** | 一键 story bible（1500–4000 字脚手架） | 冷启动加速，非最终真相源 | 免费起 |
| **Taskade Genesis** | 提示词 → 可克隆的世界工作区 | 快速原型空间 | 免费起 |

### 3.2 结构化存档类

| 工具 | 特点 | 对本项目价值 |
|---|---|---|
| **World Anvil** | 25+ 世界模板，交叉引用强 | **字段清单最佳参考** |
| **Campfire** | 模块化人物/时间线/关系 | 字段模块化参考 |
| **Novelcrafter Codex** | Codex 注入后续写作 | 中期写作一致性 |
| **Loreum + MCP** | 实体库 + AI 改动审核入典 | 结构化 canon 候选 |
| **Obsidian** | 本地双链笔记 | 轻量本地存储层 |

### 3.3 提示词 / Skill / CLI（可直接做成项目能力）

| 资产 | 特点 | 对本项目价值 |
|---|---|---|
| **everyday-writer world-builder Questioner** | 分层提问：概念→主角→冲突→规则→社会→历史；一次一问；「不知道」记入 open questions | **访谈流程蓝本** |
| **gameforge-cli** | AI 访谈 + JSON/MD 输出 + 校验 + 断点续跑 | 管线工程参考 |
| **纯 Structured Output + JSON Schema** | 把 AI 当 API，字段契约化 | **基本盘门禁的技术核心** |
| **NovelAI / SillyTavern Lorebook** | 关键词命中注入设定 | 长篇不「失忆」的记忆层蓝本 |

---

## 四、基本盘字段草案（齐 = 可进调研 02）

字段用三态：`draft`（AI 补齐）/ `confirmed`（用户确认）/ `open`（待决）。

| 字段 ID | 中文名 | 必填 | 说明 |
|---|---|---|---|
| `style` | 风格基调 | 是 | 规则怪谈 / 赛博 / 古风等 |
| `era` | 年代时空 | 是 | 当代、近未来、架空纪元… |
| `premise` | 世界前提 | 是 | 一句话世界条件（不是具体剧情） |
| `setting_core` | 核心舞台 | 是 | 主要发生地 + 感官氛围 |
| `rules` | 世界硬规则 | 是 | ≥3 条可执行规则，含代价 |
| `taboos` | 禁忌与后果 | 是 | 违反规则的可见后果（怪谈关键） |
| `factions` | 主要势力 | 是 | 2–5 个；目标与冲突轴 |
| `history_wound` | 历史伤口 | 是 | 塑造当下的过去事件 |
| `tone_promise` | 情绪承诺 | 是 | 读者/玩家离开时的感觉 |
| `opening_situation` | 开场具体设定 | 是 | 时间点、地点、初始状态 |
| `inciting_hook` | 诱发钩子 | 是 | 打破日常的第一推力 |
| `knowledge_state_schema` | 知识状态预留 | 建议 | 谁知道哪条规则（怪谈必需） |
| `open_questions` | 待决清单 | 否 | 阻塞项清零才解锁下游 |

**门禁**：所有必填为 `confirmed`，且无 blocking `open_questions` → 导出 `world_bible.json` + `world_bible.md`。

---

## 五、推荐落地（MVP）

1. 写 Cursor Skill：访谈规则 + 字段清单 + 矛盾检测。  
2. 每轮更新 WorldBible JSON；摘要确认后再冻结。  
3. 同一句话丢进 Dunia 玩测，把缺口写回 Schema。  
4. 生产阶段再接 Structured Output API；第三方不当唯一真相源。

### 风险

- 字段贪多 → 只收「能制造张力」的字段。  
- AI 补齐越权 → 必须三态与确认门禁。  
- 规则无代价 → 访谈时强制追问 limits/costs。

---

## 六、参考链接

- everyday-writer Questioner：https://github.com/deupaxx/everyday-writer/blob/main/skills/world-builder/questioner.md  
- Dunia：https://dunia.gg/  
- Storyflow：https://storyflow.so/  
- Inkfluence Story Bible：https://www.inkfluenceai.com/ai-story-bible-generator  
- Loreum：https://loreum.app/  
- gameforge-cli：https://www.npmjs.com/package/gameforge-cli  
- World Anvil：https://www.worldanvil.com/  
