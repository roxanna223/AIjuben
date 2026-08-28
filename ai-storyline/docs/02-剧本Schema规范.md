# 剧本Schema规范 v1.1（草案）

> v1.1 变更（v0.4.4）：新增 `fixed_plot` 固定剧情锚点——基础剧情细节定稿（含依据与变数条件），跨局一致、省token。
>
> 本文档定义三类数据结构：**剧本宪法**（静态，剧本发布时定稿）、**世界状态**（动态，单局内演化）、**场景输出**（AI每轮生成的结构化结果）。
>
> 设计原则：
> 1. **文本与数据分离**——AI写给人看的文本，与机器结算用的元数据，分开存放；
> 2. **一切可JSON化**——所有约束对AI可见、可程序校验；
> 3. **约束最小化**——只约束"骨架"（世界观/人物/关系/节拍/结局），不约束血肉（具体对白、场景）。

---

## 1. 剧本宪法 StoryConstitution（静态）

剧本发布时一次性定稿；一份宪法服务千千万万个玩家局，是"不让AI盲写"的落地形式。

```json
{
  "schema_version": "1.0",
  "story_id": "midnight-train",
  "title": "午夜列车",
  "genre": ["悬疑", "无限流"],
  "world": {
    "setting": "21世纪初的华北小城，一列凌晨开出的绿皮慢车……",
    "rules": ["每停靠一站，乘客就会少一名，且无人记得少的是谁"],
    "tone": "冷峻克制，留白多，靠细节营造不安",
    "style_guide": "对话体：对白为主（≥70%），叙述精短；每场300-600字",
    "taboos_content": ["不得出现性暗示/血腥细节", "不得出现真实地名、真实事件"],
    "taboos_story": ["凶手不得在节拍b4之前暴露", "不得引入手机等能轻易求援的现代工具"]
  },
  "characters": [
    {
      "id": "pc",
      "name": "你",
      "role": "protagonist",
      "identity": "回家奔丧的年轻编剧",
      "personality_axes": {"caution": 0, "empathy": 0, "order": 0, "curiosity": 0, "trust": 0},
      "goal": "活着下车",
      "secret": "三年前你曾坐过这趟车",
      "speech": "由玩家选择决定"
    },
    {
      "id": "lin",
      "name": "林sir",
      "role": "support",
      "identity": "休假的刑警",
      "personality": ["冷静", "重证据", "偶尔黑色幽默"],
      "goal": "弄清乘客消失的规律",
      "secret": "他其实是当年事故的调查员",
      "speech": "短句、冷峻",
      "voice_sample": "“先别急着害怕。人不会凭空消失，只会被人‘拿走’。”"
    }
  ],
  "relationships": [
    {"from": "pc", "to": "lin", "type": "合作", "initial": 40, "note": "同节车厢的陌生人"}
  ],
  "beats": [
    {
      "id": "b1", "kind": "fixed", "order": 1,
      "must_happen": "主角在末班列车上醒来，发现车厢里的人异常安静",
      "constraints": "不得揭示任何超自然现象"
    },
    {
      "id": "b2", "kind": "fixed", "order": 2,
      "must_happen": "第一次停站：一名乘客消失，且除主角与林sir外无人记得"
    },
    {
      "id": "b3", "kind": "conditional", "order": 3,
      "when": {"all": [{"fact": "f_saw_ledger"}, {"any": [{"stat": {"trust_lin": {"gte": 50}}}]}]},
      "must_happen": "林sir向主角透露他带着一份乘客名册"
    },
    {
      "id": "b4", "kind": "fixed", "order": 4,
      "must_happen": "车厢断电的黑暗中，主角必须做出救人还是自保的选择",
      "note": "全剧价值观分叉点"
    }
  ],
  "fixed_plot": [
    {
      "id": "fp_station1_victim",
      "beat": "b2",
      "fact": "第一站泗水站消失的乘客是沈阿婆——靠窗织毛衣、带着枣红色毛线篮的老太太",
      "basis": "林sir的乘客名册上，沈阿婆的名字在泗水站前被红笔圈起——名册的红圈决定谁消失，这是这趟车一直以来的规矩",
      "mutable_by": "只有玩家改写了名册、破坏红圈标记等行为改变了这一依据，下一个消失的人才会改变"
    }
  ],
  "endings": [
    {
      "id": "end_truth", "name": "真相大白", "type": "good",
      "conditions": {"facts": ["f_truth_revealed"], "stats": {"trust_lin": {"gte": 70}}}
    },
    {
      "id": "end_escape", "name": "独自生还", "type": "neutral",
      "conditions": {"facts": ["f_escaped"], "stats": {"trust_lin": {"lt": 40}}}
    },
    {
      "id": "end_lost", "name": "成为乘客", "type": "bad",
      "conditions": {"stats": {"sanity": {"lte": 20}}}
    }
  ],
  "stats": {
    "characters": {
      "trust_lin": {"label": "林sir的信任", "min": 0, "max": 100, "initial": 40}
    },
    "global": {
      "sanity": {"label": "理智值", "min": 0, "max": 100, "initial": 80}
    },
    "tendencies": ["caution", "empathy", "order", "curiosity", "trust"]
  },
  "chapter_plan": {"target_chapters": 6, "words_per_scene_min": 300, "words_per_scene_max": 600}
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `world.setting` | string | 时代/地点/环境，AI生成的一级依据 |
| `world.rules` | string[] | 世界机制（无限流的"规则"写在这里，AI不得违反） |
| `world.tone` | string | 文风基调 |
| `world.style_guide` | string | 输出形态指令（对话体、字数） |
| `world.taboos_content` | string[] | **内容安全禁忌**（硬红线，审查器必查） |
| `world.taboos_story` | string[] | **设定边界禁忌**（防剧透/防崩设定，审查器必查） |
| `facts` | 对象[] | **事实清单** `{id, desc}`：所有会被授予/关闭/用作条件的事实必须先在此声明；AI的effects/world_updates只能用清单内ID，审查器与结算器双重校验 |
| `characters[].voice_sample` | string | 台词示例，帮AI锁定声线（可选但强烈建议） |
| `characters[].secret` | string | 该角色隐瞒的事实（编剧可见，玩家不可见） |
| `beats[].kind` | enum | `fixed`必发生 / `conditional`条件触发 / `optional`可选支线 |
| `beats[].when` | 表达式 | 条件：`fact(s)`（已记录事实）+ `stat(s)`（数值区间）+ `tendency`（倾向阈值），支持 all/any 组合 |
| `beats[].unlock` | 表达式 | 可选支线的解锁条件（通常基于倾向向量） |
| `beats[].grants` | string[] | 本节拍**完成后**授予的事实ID；**一个事实只能有一个来源**，节拍被跳过时其 grants 自动关闭（依赖这些事实的结局随之不可达） |
| `beats[].fact_hints` | 对象[] | 本场可授予事实的提示（`{fact, hint}`），导演会把它注入编剧指令，让AI知道"叙事发生X时应标注事实Y"——真实LLM模式下机械结算可靠性的关键 |
| `beats[].cast` | string[] | 本场必出场人物ID |
| `fixed_plot` | 对象[] | **固定剧情锚点（v0.4.4起）**：`{id, beat, fact, basis?, mutable_by?}`。用户不可操作的基础剧情细节在此定稿（如"第一站消失的是谁"），导演按节拍把 `fact`+`basis` 注入编剧指令并标注"不得改写"；一致性审查同步校验（玩家已改变依据的除外）。作用：① 跨局/跨会话一致，故事骨架不漂移；② 基础剧情不再每次现编，省 token；③ 依据（basis）成立则该剧情**必然触发**，只有玩家行为改变了依据（mutable_by 描述的途径）才产生变数 |
| `endings[].conditions` | 表达式 | 同上（常用 `facts`+`stats` 合取形式）；结局是"条件"而非"选项"，玩家不是"选"结局，是"走"出来的 |

**节拍表的作用（最重要）**：它是烂尾的解药。AI随便怎么写，但故事骨架必须踩点——`fixed`节拍是硬里程碑，`conditional`节拍由玩家行为触发，`optional`节拍由倾向向量解锁。**同一节拍，不同玩家走出不同路径，但节拍本身不消失。**

---

## 2. 世界状态 WorldState（动态）

单局内持续演化，是"记录用户行为"的载体。

```json
{
  "session_id": "s_abc123",
  "story_id": "midnight-train",
  "turn": 23,
  "chapter": 3,
  "stats": {"trust_lin": 62, "sanity": 55},
  "tendencies": {"caution": 0.6, "empathy": -0.2, "order": 0.1, "curiosity": 0.8, "trust": 0.4},
  "facts": ["f_saw_ledger", "f_truth_hint_2"],
  "beat_status": [
    {"beat_id": "b1", "status": "done", "turn": 2},
    {"beat_id": "b2", "status": "done", "turn": 9},
    {"beat_id": "b3", "status": "done", "turn": 15},
    {"beat_id": "b4", "status": "active"}
  ],
  "endings_viable": ["end_truth", "end_escape"],
  "memory": {
    "recent": "最近10场场景全文",
    "chapter_summary": "本章滚动摘要（每5场压缩一次）",
    "global_summary": "全局摘要（每章末压缩一次）"
  },
  "event_log": [
    {"turn": 1, "type": "choice", "payload": {"choice": "翻看邻座乘客的报纸", "tendency": {"curiosity": 1}}},
    {"turn": 1, "type": "stat", "payload": {"trust_lin": {"delta": -5, "reason": "你擅自翻动他人物品"}}}
  ]
}
```

### 关键设计

- **`tendencies` 倾向向量**：5维，取值 -1~1。每个选择带倾向标签，AI结算时更新。它不直接写进正文，而是决定：解锁什么支线、哪些人物愿意向你吐露秘密、结局池怎么收窄。
- **`facts` 事实表**：已发生且被确认的事实ID，是节拍/结局条件的判定依据，也是审查器查"前后矛盾"的基准。
- **`endings_viable` 可达结局池**：导演每轮重新计算，某些路线的结局会中途"死掉"（这也是张力来源）。
- **三层记忆**：`recent`（全文）+ `chapter_summary`（滚动摘要）+ `global_summary`（全局摘要）。越往上越省token，越往下越保证一致性。

### 5维倾向定义

| 维度 | 正极 | 负极 | 示例选择标签 |
|---|---|---|---|
| caution 谨慎 | 谨慎 | 激进 | "先观察再行动" (+1) / "直接掀开窗帘" (-1) |
| empathy 共情 | 共情 | 利己 | "先救那个孩子" (+1) / "保命要紧" (-1) |
| order 守序 | 守序 | 越轨 | "按规则下车" (+1) / "偷看名册" (-1) |
| curiosity 好奇 | 好奇 | 克制 | "追问真相" (+1) / "不多管闲事" (-1) |
| trust 信任 | 信任 | 多疑 | "把发现的线索告诉林sir" (+1) / "隐瞒" (-1) |

---

## 3. 场景输出 SceneOutput（AI每轮生成）

AI编剧每轮输出的结构化结果，**文本与元数据分离**。v0.3 起正文为**对话体 `dialogue` 数组**（文字游戏式：每行一个说话人，前端渲染为带名字/头像的对话气泡，旁白居中；头像位后续可直接替换为人物图片）：

```json
{
  "dialogue": [
    {"speaker": "narrator", "text": "灯在毫无预兆中灭了。车厢陷入浓稠的黑暗。"},
    {"speaker": "boy", "text": "叔叔——救救我！"},
    {"speaker": "pc", "text": "别怕，我过来了。"},
    {"speaker": "lin", "text": "人不会凭空消失，只会被人‘拿走’。"}
  ],
  "scene_meta": {
    "beat_id": "b4",
    "characters_present": ["pc", "boy", "lin"],
    "location": "3号车厢"
  },
  "choices": [
    {
      "text": "把断电时摸到的名册交给林sir",
      "tendency": {"trust": 1, "order": 0.5},
      "effects_hint": {"trust_lin": 10},
      "visible_condition": {"fact": "f_saw_ledger"}
    }
  ],
  "world_updates": [
    {"type": "stat", "target": "sanity", "delta": -5, "reason": "目睹乘客消失"},
    {"type": "fact", "id": "f_truth_hint_2", "text": "名册上主角的名字被红笔圈起"}
  ]
}
```

### dialogue 对话行规范

| 字段 | 说明 |
|---|---|
| `speaker` | 说话人ID。只能是剧本 `characters` 中的人物ID（含主角 `pc`）或 `narrator`（旁白）。审查器在LLM模式下校验，未定义ID会被驳回重写 |
| `text` | 单行台词/叙述。同一行只放一句台词；`narrator` 行用于环境、动作等非台词叙述，须精短（≤60字/行） |
| `pc` | 主角行只表现玩家所选行动的即时反应，不替玩家长篇发言 |
| 占比 | 非 narrator 行（对白）应占总字数 70% 以上；总字数仍需满足 `chapter_plan` 的 300-600 字要求 |

- **兼容性**：旧版单段 `narrative` 字符串仍被接受，服务端自动归一化为单条 `narrator` 行；旧存档可无缝续玩。
- **流式输出**：对话行按"完成一行推一行"（NDJSON `line` 事件，只含 `speaker/text`，不泄露JSON元数据）；前端逐行渲染气泡，最终以审查通过的 `dialogue` 为准。
- `choices`：AI生成2-4个，可带 `visible_condition`（条件选项，路线差异化就在这）；用户也可自由输入，由规划器把自由输入**翻译**成倾向标签+数值影响后入账。
- `world_updates`：由AI起草、**由系统审核后落账**（AI不能直接改库，必须过结算器校验数值范围）。支持三种类型：`stat`（数值变化）/ `fact`（授予事实）/ `close_fact`（关闭事实——让依赖该事实的节拍与结局永久不可达，用于"错过就无法回头"的路线分叉）。
- 格式校验：JSON Schema 强制校验 + 解析失败自动重试（这是工程上最容易被忽略的坑）。

---

## 4. 校验与版本

1. **剧本宪法校验**：发布前程序校验（JSON Schema + 节拍ID引用完整性 + 结局条件引用的stats/facts必须存在）。
2. **场景输出校验**：每轮程序校验（结构合法 + 数值范围 + taboos关键词初筛）。
3. **版本演进**：`schema_version` 语义化版本；宪法改版后旧存档声明"该剧本已更新，建议重开"。
