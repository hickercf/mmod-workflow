---
name: comp-workflow
description: "全国大学生数学建模竞赛（CUMCM）统一 8 步竞赛工作流的顶层编排 SOP：分析→建模注册→并行赛马求解→深化证据→图表→论文→评审→合规编译。当需要按 Modex 式线性步骤从题面跑到可提交论文包，或使用 comp_cumcm 模板与 workflow_engine.py 状态机编排每个步骤并过质量门与人工检查点时触发。"
---

# comp-workflow 统一 8 步编排 SOP

你是 **comp-workflow** 技能：一个针对高要求国奖级论文包的线性 8 步竞赛工作流的**顶层编排者**。你驱动的是 `scripts/workflow_engine.py`（SQLite 状态机）+ `templates/comp_cumcm/`（8 步定义）驱动的 `pending → running → waiting_checkpoint → completed` 状态推进。

唯一事实源是 `docs/workflow-design.md`。**不要发明新命令、新步骤或新规则**——本技能的所有命令、产出契约、质量门与状态语义都以该文档为准，与 `workflow_engine.py` 的实际命令逐条对齐。任何与现有脚本不一致之处，以 `docs/workflow-design.md` 为准并回查脚本源码。

## 定位：与 math-modeling 技能的关系

- 本技能（`comp-workflow`）是**新统一工作流的顶层编排**。主循环按它驱动 8 步（S1..S8），每步派发一个 comp-* 子技能给对应子 Agent，跑质量门，处理人工检查点，管理断点恢复。
- 既有 `math-modeling` 技能的三阶段（M1 建模 -> M2 代码 -> M3 论文）**仍然是阶段内活动标签**，不退场。8 步通过 `sync-state` 映射回三阶段（S1-S2→modeling、S3-S5→code、S6-S8→paper），沿用的 M1/M2/M3 工件契约（data-audit、scheme-registry、六份深度证据、三份分离正文、判审团等）在 8 步中被逐项落实。
- 因此：**用户在平面上只看到 8 步，阶段用 M1/M2/M3 或 S1..S8 均可，同一套状态由引擎与 `workflow_gate.py` 对齐**。两者不冲突：引擎是更细粒度的控制面，`workflow_gate.py` 三阶段门禁被复用与只读检查。

### 血缘与演进

- 本技能以 Modex 的 7 步竞赛工作流（分析→建模→代码→图→论文→编译）为骨架，插入本仓库既有优势：三阶段契约、候选赛马、六份深度证据、两轮对抗审查 + 三席盲评判审团、外部知识库优先检索。
- 8 步 = Modex 7 步把"两种图"合并为一步（S5），并**新增 S4 深化证据**与 **S7 评审判审**两步。

## 引擎命令速查表

状态机库文件位于 `<workspace>/.engine/workflow.db`（`.engine/` 加入 .gitignore），表结构含 `meta`、`steps`、`checkpoints`、`logs`。所有命令首参数为 `<workspace>`。

```bash
python scripts/workflow_engine.py <workspace> init --template comp_cumcm [--subquestions N] [--title X]
python scripts/workflow_engine.py <workspace> status [--json]                 # 只读
python scripts/workflow_engine.py <workspace> start <S1..S8>                 # 置 running
python scripts/workflow_engine.py <workspace> complete <S1..S8> [--note ...] # 跑质量门；通过→waiting_checkpoint/completed
python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> resolve [--response <json>]
python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> reject --feedback <text>
python scripts/workflow_engine.py <workspace> gate <S1..S8>                  # 只读跑该步质量门
python scripts/workflow_engine.py <workspace> advance                         # 打印下一个可执行步骤
python scripts/workflow_engine.py <workspace> resume                          # running→pending，打印可重入步骤
python scripts/workflow_engine.py <workspace> backfill [--steps S1,S2,...] [--confirmed modeling,abstract,paper]
python scripts/workflow_engine.py <workspace> sync-state [--check]           # 对齐 workflow-state.json；--check 只读
python scripts/workflow_engine.py <workspace> report                         # 机器可读 JSON
```

### 命令语义要点

- **只读**：`status`、`gate`、`advance`、`report`、`sync-state --check`。
- **写库**：其余命令均写库，且记录进 `logs` 与 `progress.md`。
- `init` 按 `--template comp_cumcm` 读取 `templates/comp_cumcm/steps.json` 建立 8 步库，可用 `--subquestions N` 与 `--title X` 补充元信息。
- `complete` 是**质量门入口**：门不过则拒绝，步骤保持 `running` 并写 blockers 到 logs。
- `backfill` 用于把**已有**的历史产物导入引擎以获得断点恢复能力；它不能代替 Agent 补写证据。
- `sync-state` 在最终收尾时把 8 步状态映射回三阶段（S1-S2→modeling、S3-S5→code、S6-S8→paper），使 `workflow_gate.py status` 仍显示 complete。

## 8 步派发规则

每步的派发对象、输入、输出与完成后的引擎命令见 `references/steps.md`；赛马细节见 `references/race-protocol.md`；质量门与人工检查点清单见 `references/quality-gates.md`。下面是顶层速览：

| 步 | skill | 派发（子 Agent） | 完成命令 | 检查点 |
|---|---|---|---|---|
| S1 审题与数据分析 | comp-prob-analysis | problem-analyzer | `complete S1` | approve |
| S2 建模方案与赛马注册 | comp-modeling | model-advisor | `complete S2` | feedback |
| S3 并行求解与赛马选优 | comp-code-race | solver（按 qN×scheme 并行） | `complete S3` | approve |
| S4 深化与深度证据 | comp-deep-evidence | solver（每问一个，只做 winner） | `complete S4` | 无（自动门） |
| S5 图表生成与清单 | comp-figures | solver / data-processing | 主循环重建 manifest 后 `complete S5` | 无（自动门） |
| S6 论文写作与装配 | comp-paper-zh | paper-writer | `complete S6` | approve |
| S7 两轮评审与三席盲评 | comp-review | paper-reviewer / paper-judge（×3） | `complete S7` | 无（自动门） |
| S8 合规检查与最终包编译 | comp-compile-zh | compliance-check + 编译工具 | `complete S8` | approve |

各步详细输入/输出契约见 `references/steps.md`（含每步三阶段映射、负责人、完成命令、检查点类型）。

### 通用编排不变式

- **先 `start`，后派发**。每步开始时 `start Sx`，子 Agent 产出落盘后主循环跑质量门。
- **质量门通过才推进**。`complete` 通过检查点步骤转 `waiting_checkpoint`，无检查点步骤直接 `completed`。
- **推进前先 `advance`**。`advance` 只有前置门全绿才把下一步列为可执行。
- **完成后调用正确的引擎命令**（见上表），由本技能主循环执行，禁止子 Agent 自行 `complete` 后直接跳过门。

## 检查点处理规则

检查点是人工闸门，`approve` 与 `feedback` 两种类型，**均禁止跳过**。

- **approve**：S1/S3/S6/S8。主循环必须把产物摘要给用户看（S1 看 `PROBLEM_ANALYSIS.md` 摘要、S3 看赛马表与 winner、S6 看摘要+装配稿、S8 看最终包），用户确认后 `checkpoint <Sx> resolve`（可带 response）。
- **feedback**：S2。主循环把 `MODELING_REPORT.md` 与赛马注册交给用户；采纳意见后 `checkpoint S2 resolve`；若用户要求修改，`checkpoint S2 reject --feedback <text>` 并把步骤置回 `running` 重新执行同一 skill。
- **reject（打回重跑）**：`checkpoint Sx reject --feedback <text>` 记录反馈并把该步置回 `running`，主循环据此**重新执行同一子技能**，**不允许跳过**该步。
- **approve 前展示真实产物**：主循环给用户看的是产物摘要（文件/路径/关键结果），而不是"已完成"之类的结论性空话。
- 每个检查点生成一行 `checkpoints` 记录，时间与 response 留痕（对齐"文件即协议"）。

## 失败恢复

- **gate 失败**：`complete` 拒绝，步骤保持 `running`，blockers 写入 logs。主循环把 **blockers 交回对应子 Agent** 修复——不回交给错误的 agent，不得由主循环写占位内容骗过门禁。
- **禁止写占位**：任何产出文件若为空、`status` 非 ready/solved/verified、表头缺失字段、frontmatter 缺键，都是门禁 blocker，必须由对应 Agent 补真实内容后重跑门。
- **断点恢复 / 崩溃恢复**：`resume` 把 `running` 复位为 `pending` 并打印可重入步骤；未决检查点按 `references/resume-recovery.md` 处理。历史工作区（无 `.engine/`）用 `backfill` 导入以获得断点恢复能力。
- **迭代预算**：沿用 `math-modeling/references/iteration-budget.md`（每关卡修复≤2轮、判审团 re-score≤2、全程≤8）。每次 gate 复评后 `iteration_budget.py record`，判审团 re-score 后 `iteration_budget.py rescore`，推进前 `iteration_budget.py check`。超限写 `paper/decision-memo.md` 停下等用户，绝不静默继续。

## 完成后收尾

1. 在最终人工检查点（S8 approve）resolve 后运行：
   ```bash
   python scripts/workflow_engine.py <workspace> sync-state
   ```
   `sync-state` 把 8 步状态映射回三阶段（S1-S2→modeling、S3-S5→code、S6-S8→paper），使 `workflow_gate.py status` 与引擎一致。可用 `sync-state --check` 先只读核对。
2. 更新 `progress.md`：每步或每个关键门完成后追加一行（时间/步骤/产出/风险）。
3. 向用户汇总最终交付物路径（`paper/final/` 的 PDF/DOCX、`compliance-report.md`、evidence ledger 指向的真实包）与门禁状态。
4. 只有 `advance` 从头到尾走通且 S8 检查点 resolve，才宣称工作流完成——门禁通过才算数。

## 沿用的既有规约（阶段内适用）

8 步编排复用本仓库既有契约，不松绑：

- **数据真实性红线**：论文数字只来自 `results/qN/summary.md`；图表引用只来自 canonical `results/manifest.md`；独立验证必须登记 `validation_kind`/`independence_basis`/`validation_artifact`。
- **图表规范**：PNG/PDF 同 stem 双份；中文样式由 `plot_style.py` 注入；图表自明标题并在 manifest/evidence ledger 中闭合。
- **论文深度**：正文 ≥25 页（四问数据题 28--35，正文与附录分开统计）；每张正文图自明标题 + 紧随其后的读图解释；摘要按"背景/总体框架 + 每问独立段 + 综合边界"组织，结尾用题目定制的决策整合章，不套通用模板。
- **Windows 环境**：文件 IO 显式 `encoding='utf-8'`；代码相对题目根目录、禁止硬编码盘符；bat 只写 ASCII；控制台尽量 ASCII-safe。
- **知识库纪律**：见 `references/kb-retrieval.md`。
- **协议字段唯一**：frontmatter 禁止重复顶层键，`workflow-state.json`/`scheme-registry.json` 禁止重复 JSON 成员名，不依赖解析器后值覆盖。

## Token 与协作纪律

- 子 Agent 任务只给**目标、路径、范围**，不复述文件全稿；模板细节由复现记录与 manifest 片段负责。
- 知识库检索按固定顺序执行并登记（见下）。
- 关键决策人确认：M1 模型冻结（S2 经 `checkpoint resolve`/feedback）、M3 摘要（S6 approve）、M3 最终包（S8 approve）仍是对应 `confirm modeling/abstract/paper` 的反映。
- 所有新增目录（`.engine/`、`templates/`）纳入 .gitignore；不改动旧产物与历史工作区。

## 外部文档索引

- 事实源：`docs/workflow-design.md`
- 引擎：`scripts/workflow_engine.py`
- 模板：`templates/comp_cumcm/steps.json`、`templates/comp_cumcm/prompts/*.md`、`templates/comp_cumcm/latex/`
- 本技能参考：`references/steps.md|race-protocol.md|quality-gates.md|resume-recovery.md|kb-retrieval.md`

### 本技能参考速览

| 文件 | 内容 |
|---|---|
| `references/steps.md` | 8 步逐一输入/输出契约、三阶段映射、检查点、负责人 |
| `references/race-protocol.md` | 赛马注册/并跑/比较/选优/三方一致性/winner 闭环 |
| `references/quality-gates.md` | 每步自动门 + 人工检查点清单 |
| `references/resume-recovery.md` | 断点恢复、backfill、未决检查点处理 |
| `references/kb-retrieval.md` | 外部→内部检索顺序、回退、登记 |

## 入口示例：从零开始

```bash
# 预检环境（可选，沿用 math-modeling 规约）
python scripts/env_check.py

# 建立 8 步状态机
python scripts/workflow_engine.py workspace/<题名> init --template comp_cumcm --subquestions N --title "题名"

# 发起第一轮编排
python scripts/workflow_engine.py workspace/<题名> start S1
# …派发 problem-analyzer，产出落盘后…
python scripts/workflow_engine.py workspace/<题名> complete S1
python scripts/workflow_engine.py workspace/<题名> advance
```

对已有人工推进、但想获得断点恢复的旧工作区，用 `backfill --steps S1,S2,...` 导入已有产物。

## 三阶段 gate 定位映射

`workflow_gate.py` 与引擎并存，只用它做三阶段视角的只读核对与兼容检查：

- **M1（S1-S2）**：`workflow_gate.py <workspace> check modeling` / `advance modeling`。
- **M2（S3-S5）**：`check/advance code`。
- **M3（S6-S8）**：`check/advance paper`。
- 非托管 workspace（无 `.engine/`）用 `workflow_gate.py` 只读检查，不降门槛；`backfill` 把已有产物导入引擎以获断点恢复。
- `sync-state` 才是把 8 步状态写回三阶段的主轴；`workflow_gate.py` 的 `confirm modeling/abstract/paper` 由对应人工检查点（S2 冻结 / S6 摘要 / S8 最终包）在用户确认后反映。

## 编排节奏建议

- **线性推进为主**：S1→S2→…→S8 严格先后，前置门全绿（`advance`）才开下一步，避免并行污染门禁语义。
- **阶段内可并行**：S3 按 `qN × scheme` 并行派 solver；S4/S5 按 `qN` 并行；S6 可并行每问；S7 三席盲评并行。均须由主循环统一收尾过门。
- **逐步留痕**：每步 `complete` 后向 `progress.md` 追加（时间/步骤/产出/风险）；`complete --note ...` 可附加本步说明。
- **不越级**：禁止在 S2 前完成 S3 赛马、或在 S7 前宣称 review pass / 生成最终包。所有 M3 深度/审查/合规状态以受控工件与门禁为准。

## 排障速查

| 症状 | 处理 |
|---|---|
| `complete` 报 blockers | 把 blockers 交回该步对应子 Agent；不写占位 |
| `advance` 不推进下一步 | 前置门未全绿，先修对应步门禁 |
| 状态卡在某步 | `status`/`report` 查库态，`resume` 复位或处理未决检查点 |
| 用户对产物不满 | `checkpoint Sx reject --feedback` 打回重跑同一 skill |
| 需要只读看某步门禁 | `gate <Sx>`（不写库） |
| 回到三阶段视角 | `sync-state --check` 只读核对映射 |
