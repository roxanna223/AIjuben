# Cursor 调研 03：故事推进模拟器（大世界观脉络）

> 日期：2026-08-26  
> 目标：建立世界观主线运转脉络（非单角色）；有一套符合世界设定的运算规则（如规则怪谈）；能推演「从何时开始、未来 N 年如何发展」的大画面推进。

---

## 一、结论先行

**能做到，但必须分层，不能拿纯 LLM 智能体硬跑百年。**

推荐架构：

```
宏观编年史（规则引擎 + LLM 写年表）
    → 中观阶段快照（关键转折年）
        → 微观智能体模拟（仅关键片段，≤50 agents）
```

规则裁决放在 **Game Master 层**（DeepMind Concordia 模式），角色智能体只负责「我想做什么」，世界因果由规则引擎判定。

---

## 二、需求拆解

| 子需求 | 关键点 |
|---|---|
| 大画面推进 | 以年/时代为 tick，产出大事年表 |
| 符合世界规则 | 规则怪谈等硬规则可执行、可裁决 |
| 非单角色 | 势力、地点、规则变异、信息扩散 |
| 可对接下游 | 年表与世界状态快照供角色小说使用 |

---

## 三、参照系盘点

### 3.1 学术 / 开源引擎

| 项目 | 要点 | 价值 |
|---|---|---|
| **Stanford Generative Agents / Smallville** | 记忆流 + 检索 + 反思 + 规划；25 agents 涌现派对组织 | 微观层架构蓝本 |
| **a16z AI Town**（MIT） | Smallville 工程化；tick 循环、记忆向量库 | **代码级可抄** |
| **DeepMind Concordia** | GM 裁决环境；智能体只提议行动 | **规则怪谈裁决层正解** |
| **Narra（gqy20/narra）** | YAML 声明规则/剧情线 + Go 内核 + 批量仿真；Godot 客户端 | **与互动叙事需求最接近** |
| **World History Engine** | 图数据库实体关系 + 时间轴回放 + MCP | 大时间线可视化 |
| **WorldLines** | 多 agent（world/place/soul）；事件溯源、分支/撤销 | 持久世界运行时参考 |
| **BRING** | Director 后台推进时间、NPC 社交、概率引擎 | 后台世界演化参考 |

### 3.2 产品层对照

| 产品 | 能做什么 | 局限 |
|---|---|---|
| Dunia / WorldLines 产品站 | 世界持续运转、后果落地 | 难导出为你的 Schema |
| 纯 ChatGPT 推演 | 快速出「伪年表」 | 无状态机，易自相矛盾 |

---

## 四、规则怪谈类规则引擎

### 4.1 规则三段式

每条规则 = **Trigger（触发）+ Validation（生效条件）+ Action（后果）**

例：直视实体 A > 3 秒（Trigger）∧ 未持绝缘物（Validation）→ 实体瞬移至身后（Action）。

分保护性规则（必须做）与危害性规则（不能做）。规则既是机制也是叙事素材。

### 4.2 知识状态（Knowledge State）

系统跟踪每个角色/玩家对每条规则的知晓程度：未知 / 片面 / 完全。信息靠事件在世界中扩散（契合 Smallville 信息传播涌现）。

**务必在调研 01 Schema 预留 `knowledge_state_schema`。**

### 4.3 可参考实现

- Narra 内容包 YAML 声明世界规则 + `simulate --runs` 批量验包  
- 观察者模式全局状态管理（小型 Unity 怪谈原型常见做法）

---

## 五、大画面 N 年推演方案

### 5.1 宏观层（主路径，先做）

输入：规则集、势力表、当前世界状态、时间跨度（如 20/50 年）。

机制：

1. 以「年」或「时代」为 tick。  
2. 规则引擎先算结构性变化（势力消长、资源、规则变异、灾难阈值）。  
3. LLM 只负责把状态差分写成编年史条目（禁止 LLM 偷偷改规则）。  
4. 输出：`chronicle.json`（大事年表）+ 若干 `world_snapshot`。

### 5.2 中观层

从年表挑关键转折点，生成该时期完整快照：势力版图、存活重要人物、新禁忌、社会氛围。

### 5.3 微观层（按需）

仅对用户选定的时期/地点跑 AI Town 式模拟，为调研 04 提供场景素材。硬限制：≤50 agents、短时段。

### 5.4 状态要求

世界状态必须：**可快照、可 diff、可 seed 复现**（JSON 事件日志 + append-only）。

---

## 六、推荐落地（MVP）

1. **P0**：规则 YAML + 年 tick 编年史生成器（无多智能体）。  
2. **P1**：世界状态快照导出，供角色线读取。  
3. **P2**：关键片段接入 AI Town / Concordia 式微观模拟。  
4. 细读仓库：`gqy20/narra`、`a16z-infra/ai-town`、`google-deepmind/concordia`。

### 风险

- 成本黑洞：全智能体长跑 → 严格限微观。  
- LLM 改规则：因果裁决必须在 GM/规则引擎。  
- 一致性：摘要链 + 事件日志 + 规则校验器三件套。

---

## 七、参考链接

- Generative Agents 论文：https://arxiv.org/pdf/2304.03442  
- AI Town：https://github.com/a16z-infra/ai-town  
- Concordia：https://github.com/google-deepmind/concordia  
- Narra：https://github.com/gqy20/narra  
- World History Engine：https://github.com/Watashicuvu/world-history-engine  
- WorldLines：https://worldlines.gg/  
- BRING：https://github.com/Eva-E1/BRING  
