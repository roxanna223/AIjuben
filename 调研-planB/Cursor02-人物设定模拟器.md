# Cursor 调研 02：人物设定模拟器 / 编辑器

> 日期：2026-08-26  
> 目标：根据已生成世界观，自动生成主要人物及相关字段（基础人设、性格、外貌等），并支持编辑与关系网。

---

## 一、结论先行

**五环里现成标准最多的一环。** 直接采用 **SillyTavern `chara_card_v2/v3` 开放规范** 作为人物数据结构，再叠「世界观驱动生成 + 关系网骨架 + 压力 QA」。

不必从零发明字段格式。

---

## 二、需求拆解

| 子需求 | 关键点 |
|---|---|
| 世界观驱动生成 | 人物服装、社会位置、禁忌知识必须属于该世界 |
| 完整字段 | 人设 / 性格 / 外貌 / 动机 / 声音样本 |
| 关系网 | 盟友、对手、秘密持有者等「剧情功能位」 |
| 可编辑 | 字段级采纳/改写，导出给下游小说推进 |
| 一致性 | 长篇生成时人设不漂移 |

---

## 三、核心资产：Character Card 规范

### V2 事实标准字段（社区 90%+）

| 字段 | 作用 |
|---|---|
| `name` | 角色名 |
| `description` | 外貌、身份、背景（模型必读） |
| `personality` | 性格摘要（建议第二人称 `{{char}}`） |
| `scenario` | 场景上下文 |
| `first_mes` | 开场白 |
| `mes_example` | 示例对话（**锚定语气，调研 04 极关键**） |
| `system_prompt` / `post_history_instructions` | 行为约束 |
| `alternate_greetings` | 多开场 |
| `character_book` | 角色专属 Lorebook |

### V3 增量（2025+）

- `assets`：头像、表情差分、语音/Live2D → 对接大选择配图  
- `.charx`：ZIP 打包（card.json + assets/）  
- 更可预测的角色书行为（regex / constant）

规范参考：https://github.com/malfoyslastname/character-card-spec-v2

---

## 四、工具盘点

### 4.1 编辑器 / 规范生态

| 工具 | 特点 | 价值 |
|---|---|---|
| **SillyTavern** | 角色卡 + 世界书 + 群聊 | 原型底座与验证环境 |
| **Chara Snap / ST Card Builder / Bae Card Builder** | 在线 V2/V3 编辑导出 | 过渡期人工微调 |
| **CHUB / ClawHub** | 卡片分享库 | 字段写法参考 |

### 4.2 AI 生成器

| 工具 | 特点 | 价值 |
|---|---|---|
| **Inkfluence Character Bible** | 一键：voice / flaw / want / 三拍弧 | 冷启动脚手架 |
| **Storyflow Character Profile** | 画布卡片 + 关系连线 | 关系可视化参考 |
| **CharGen（开源）** | 关键词→完整人设 + NPC system prompt + 绘图 prompt；支持本地 LLM | **可嵌入候选** |
| **Talefy / Story321** | 动机、秘密、压力反应倾向 | 「反应倾向」字段设计参考 |
| **Campfire Characters / Relationships / Arcs** | 人物表 + 关系网 + 弧光时间线 | 编辑器 UX 参考 |
| **Character.AI** | 对话测人设 | 「压力面试 QA」范式 |

---

## 五、关键机制：世界观 → 人物

### 5.1 生成顺序（推荐）

1. 注入调研 01 的 `world_bible`（规则、势力、禁忌、开场）。  
2. 先生成**关系网骨架**（不要孤立抽人）：主角需要盟友 / 对手 / 人情债 / 秘密持有者等功能位。  
3. 每个节点扩成完整角色卡。  
4. AI 补齐字段标 `auto_generated`，用户逐条确认。  
5. **压力 QA**：让模型扮演该角色回答 5 个高压问题，检查是否符合 personality。  
6. 导出 V2/V3 JSON；`character_book` 内嵌该角色事实条目。

### 5.2 建议人物 Schema（在 V2 之上扩展）

| 层 | 字段 |
|---|---|
| 基础 | 姓名、年龄、身份、社会位置、所属势力 |
| 外貌 | prose 描写 + 图像 prompt（双份） |
| 性格 | 3–5 特质 + flaw + 盲点 |
| 动机 | want / need / 秘密 / 恐惧 |
| 互动关键 | 压力反应（战/逃/骗/求）、说谎条件、翻脸底线 |
| 声音 | `mes_example` 2–3 段 |
| 关系 | 对他者的情感债务（亏欠/怨恨/爱慕…） |
| 知识 | 已知世界规则列表（对接怪谈知识状态） |

---

## 六、推荐落地（MVP）

1. 以 `chara_card_v2` 为存储格式，扩展项目私有 `extensions.omniPlot` 字段。  
2. Cursor Skill：读 world_bible → 出关系网 → 批量出角色卡 JSON。  
3. 过渡期用 Chara Snap / SillyTavern 人工微调。  
4. 自建轻量编辑器只做：字段表单 + 关系图 + 确认门禁。

### 风险

- 人设模板化 → prompt 强制缺陷/秘密/矛盾点。  
- 与世界观脱节 → 生成前强制注入势力与禁忌。  
- 字段过多 → 核心层只留「能制造分支张力」的字段。

---

## 七、参考链接

- Character Card Spec V2：https://github.com/malfoyslastname/character-card-spec-v2  
- SillyTavern：https://github.com/SillyTavern/SillyTavern  
- CharGen：https://github.com/Karmacoke/chargen  
- Inkfluence Character Bible：https://www.inkfluenceai.com/ai-character-bible-generator  
- Storyflow Character：https://storyflow.so/ai-character-profile-generator  
- Campfire Character Builder：https://campfirewriting.com/character-builder  
