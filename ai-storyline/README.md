# 「歧路」AI互动叙事平台（工作名）

> 定位：有剧本框架约束的对话体互动叙事——主线骨架由人定，实时剧情由AI写，用户的每次选择被记录为数值与性格倾向，AI"导演"据此规划千人千线。

> **迭代记录**:项目现状、全部迭代历史、安全措施与运维速查见 `docs/05-迭代文档.md`;**每次功能更新必须在该文档追加迭代记录**。

## 目录结构

```
ai-storyline/
├── docs/                      # 设计文档（评审中）
│   ├── 01-PRD.md              # 产品需求（MVP范围/成功指标/风险）
│   ├── 02-剧本Schema规范.md    # 剧本宪法/世界状态/场景输出 三类数据结构
│   ├── 03-系统架构.md          # 四层模型/流水线/成本/评测/内容安全
│   ├── 04-样例剧本-午夜列车.md  # 样例剧本节拍骨架 + 千人千线走查演示
│   └── 05-迭代文档.md          # 迭代历史/生产环境/安全措施/运维速查(每次更新必写)
├── engine/                    # 引擎（纯Python标准库）
│   ├── constitution.py        # 剧本宪法：加载与校验
│   ├── conditions.py          # 条件表达式求值（节拍触发/结局判定共用）
│   ├── state.py               # 世界状态：数值/倾向/事实/三层记忆/事件账本/序列化
│   ├── director.py            # 导演规划器：节拍调度/结局池筛选/人物调度/章节推进
│   ├── graph.py               # 故事导图：渐进解锁的路线节点/选择分叉边/玩家自创剧情节点
│   ├── validation.py          # 工程化校验量表：数值/剧情出发点的规则插件+情景化口径(构建/运行/审计三用)
│   ├── ledger.py              # 结算器：AI的world_updates审核落账
│   ├── llm.py                 # LLM Provider（Mock确定性 / OpenAI兼容）
│   └── pipeline.py            # 流水线：导演→编剧→审查器→结算
├── server/                    # Web服务（FastAPI + 静态前端）
│   ├── app.py                 # API：剧本列表/开局/回合/状态/复盘 + 会话持久化（断线续玩）
│   └── static/                # 对话流前端（index.html/app.js/style.css，零构建，多剧本选择）
├── stories/                   # 剧本库（引擎零改动即可承载新剧本）
│   ├── midnight-train.json    # 《午夜列车》剧本宪法 + .mock.json 确定性脚本
│   └── rule-tower.json        # 《规则楼》剧本宪法 + .mock.json（题材/数值/结局均不同）
├── scripts/
│   ├── validate_content.py    # 工程化校验CLI：构建期校验mock / 审计期扫描历史会话
│   ├── llm_walkthrough.py     # 真实LLM金标准走查
│   └── judge_quality.py       # LLM-as-judge 质量抽检
├── tests/                     # 81个测试：引擎单元 + 校验量表 + 两个剧本金标准走查 + Web API
├── play_cli.py                # 命令行试玩器
├── metrics.py                 # 体验基线测量（对照调研基线验收）
└── run_server.sh              # Web服务启动脚本
```

## 快速开始

```bash
# 1) 首次：创建虚拟环境并装依赖（FastAPI/uvicorn/httpx）
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn httpx

# 2) 配置 .env（已包含 DeepSeek Key；STORY_MODE=llm 默认真实AI，mock 可切换）

# 3) 跑全部测试
.venv/bin/python -m unittest discover -s tests -v

# 4) 启动Web服务（默认读 .env → 真实LLM模式）
./run_server.sh
# 打开 http://127.0.0.1:8000 开始玩

# 5) 真实LLM金标准走查（脚本化，打印全文+用量）
.venv/bin/python scripts/llm_walkthrough.py --story midnight-train --path 1,1,1,2,1,1,1

# 6) 纯命令行试玩（Mock对照）
python3 play_cli.py
```

## 设计核心（一句话版）

| 层 | 职责 | 谁来实现 |
|---|---|---|
| 剧本宪法 | 世界观/人物/关系/节拍表/结局池/禁忌 | 人写（或AI辅助），发布定稿 |
| 世界状态 | 数值/倾向向量/事实/三层记忆/事件账本 | 确定性代码 |
| AI编剧 | 正文+选项+world_updates草案 | LLM（规划器→编剧→审查器流水线） |
| 导演规划器 | 节拍调度/结局池筛选/人物调度/收束模式 | 确定性代码 |
| 故事导图 | 路线节点渐进解锁/选择分叉边/玩家自创剧情节点 | 确定性代码（零AI参与） |
| 校验量表 | 数值/剧情出发点的工程化校验（规则插件+情景化口径，构建/运行/审计三用） | 确定性代码+LLM判定注入 |

**铁律：AI只负责写，确定性代码负责管。**

## API

```
GET  /api/stories                      剧本列表（前端选择）
POST /api/sessions                     开局 {story_id} → {sid, scene, history, ...}
POST /api/sessions/{sid}/turn          回合 {choice_index | free_text} → 下一场景/结局
GET  /api/sessions/{sid}               断线续玩（从 data/sessions/*.json 恢复，含历史时间线）
GET  /api/sessions/{sid}/map           故事导图（渐进解锁的路线节点/选择分叉边）
GET  /api/sessions/{sid}/recap         结局复盘（路线/倾向/选择/数据足迹）
GET  /api/admin/metrics                体验基线指标（?story_id= 可过滤）
GET  /api/health                       健康检查
```

## 剧本库（Schema 通用性证据）

| 剧本 | 题材 | 自定义数值 | 结局 |
|---|---|---|---|
| 《午夜列车》 | 悬疑/无限流 | 理智值、林sir信任 | 4个（含隐藏） |
| 《规则楼》 | 无限流/规则怪谈 | 理智值、老周信任、**违规次数(0-3)** | 4个（含隐藏） |

两个剧本题材、数值、节拍、结局完全不同，**引擎与Schema零改动**即可承载——新增剧本只需新增两个JSON文件（宪法+Mock脚本），并自动出现在Web端剧本列表。

## 体验基线测量（对标调研基线）

```bash
python3 metrics.py                     # 命令行报告
curl http://127.0.0.1:8000/api/admin/metrics   # API（含逐项PASS/FAIL）
```

指标与目标（PRD §6）：第1章完读率≥60%（点点穿书考核线）／结局达成率≥50%／结局路线分化度≥3／平均会话时长≥15分钟。
真实LLM模式的 token/延迟埋点写入 `data/usage.jsonl`（`QILU_USAGE_FILE` 可改路径），用于成本达标测量。

## 质量评测工具

```bash
# 工程化校验（构建期/审计期二合一CLI，校验口径见剧本 validation 段与 engine/validation.py）
.venv/bin/python scripts/validate_content.py --story midnight-train --mock               # 构建期:校验mock全场景
.venv/bin/python scripts/validate_content.py --story midnight-train --sessions data/sessions  # 审计期:扫描历史会话的数值/剧情出发点违规

# 真实LLM金标准走查（脚本化，打印全文+用量）
.venv/bin/python scripts/llm_walkthrough.py --story midnight-train --path 1,1,1,2,1,1,1
# LLM-as-judge 自动抽检（多局随机走查 + 四维打分，报告存 data/quality/）
.venv/bin/python scripts/judge_quality.py --story midnight-train --runs 2 --seed 42
```

首轮抽检结果（LLM-as-judge，5分制）：《午夜列车》一致性4.50/文风4.90/选项4.40/惊喜度4.70；
《规则楼》一致性4.69/文风5.00/选项4.54/惊喜度4.62。真实模型模式下每场生成后自动做**事实一致性审查**（矛盾→带反馈重写）。

## Phase 0/1 验收进度（2026-08）

| 验收项（架构文档§11） | 状态 |
|---|---|
| 开局→选择→生成→结算→节拍推进→结局判定 闭环 | ✅ 引擎+CLI+Web API 三层跑通 |
| 连续运行无JSON解析失败、无事实矛盾 | ✅ 39个测试全过，0降级标记 |
| 同一剧本≥3条不同结局路径 | ✅ 两个剧本各3条金标准走查（共6条）→ 各3个不同结局 |
| Schema通用性（多剧本） | ✅ 《规则楼》零引擎改动上线，自定义数值/结局全支持 |
| Web MVP：人物对话UI（逐句推进/自动播放/交互点输入/✦影响提示）/数值面板/复盘/剧本选择 | ✅ http://127.0.0.1:8000（Mock/LLM模式） |
| 断线续玩 + 历史回放 | ✅ 会话JSON持久化 + 完整时间线重建（测试覆盖） |
| 体验基线自动测量（完读率/达成率/分化度/时长） | ✅ metrics.py + admin API（真实会话可出报告） |
| 真实LLM生成闭环（DeepSeek） | ✅ 双剧本走查：节拍全触发、事实授予正确、结局条件真实匹配、0生成降级 |
| 基础剧情确定性（fixed_plot 固定剧情锚点） | ✅ 跨局一致实测（第一站消失者=沈阿婆·名册红圈依据），导演注入+审查校验双保险 |
| 单场景成本与延迟 | ✅ 实测：55次调用/10.4万tok/¥0.15；流式后首字节约4s（此前整场约7s干等） |
| SSE/NDJSON流式输出 | ✅ 对话行增量实时推送（JSON元数据不外泄），失败自动回退非流式重写 |
| 路线复盘可视化 | ✅ 结局页SVG节点图：完成/跳过/未达节拍 + 选项分叉标签 + 结局节点（含图例） |
| 故事导图（渐进解锁路线图） | ✅ 顶栏「🗺 故事导图」：只点亮到达过的节点；每次选择画一条分叉边；自由输入的玩家自创剧情生成专属节点；未走上的岔路以空心占位呈现（不剧透）；随会话存档持久化 |
| 工程化校验量表（数值/剧情出发点） | ✅ `engine/validation.py` 规则插件框架：数值只在声明的剧情点/幅度内变化（理由禁用词硬拦"提前触发"）；节拍保留事实不得提前授予；构建期校验 mock、运行期驳回重写、审计期离线扫描历史会话 |
| 生成质量（文风/一致性/惊喜度） | ✅ LLM-as-judge抽检：双剧本四维 4.4-5.0/5分；每场自动事实一致性审查 |
| 调研基线（完读率60%等）与真实用户验证 | ⏳ 等真实玩家数据（/api/admin/metrics 自动统计） |

## 待办（等待输入）

1. **用户评审设计文档**：Schema约束力度 / 五维倾向 / 剧本底子
2. **真实玩家体验数据**：把 http://47.114.103.41/ 发给朋友试玩；体验基线在 `/api/admin/metrics`、玩家行为在 `/api/admin/events`（均需 `X-Admin-Token` 请求头，令牌见本机 `deploy/env.server`）
3. 评审通过后打磨：路线分享、更多剧本、数据可视化面板
