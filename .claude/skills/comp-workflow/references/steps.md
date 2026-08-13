---
name: comp-workflow-steps
purpose: "8 步（S1..S8）逐一说明：每步派发的 comp-* 子技能、输入/输出契约、对应三阶段、检查点类型与负责人。供主循环按 steps.json 驱动每步。"
---

# 8 步派发详表

对应 `templates/comp_cumcm/steps.json` 与 `docs/workflow-design.md` 第 2 节的 8 步定义。每步状态为 `pending → running → waiting_checkpoint → completed`；`complete` 跑质量门，通过后带检查点步骤转 `waiting_checkpoint`，无检查点步骤直接 `completed`。步骤在**插入本仓库深化证据与评审判审两步**之前，源自 Modex 的 7 步（prob-analysis → modeling → code → figures → paper → compile），并合并了"两种图"为一步。

```jsonc
// templates/comp_cumcm/steps.json 中 8 步的 id / skill / 检查点
{
  "S1": {"skill": "comp-prob-analysis", "checkpoint": "approve"},
  "S2": {"skill": "comp-modeling",      "checkpoint": "feedback"},
  "S3": {"skill": "comp-code-race",     "checkpoint": "approve"},
  "S4": {"skill": "comp-deep-evidence", "checkpoint": ""},
  "S5": {"skill": "comp-figures",       "checkpoint": ""},
  "S6": {"skill": "comp-paper-zh",      "checkpoint": "approve"},
  "S7": {"skill": "comp-review",        "checkpoint": ""},
  "S8": {"skill": "comp-compile-zh",    "checkpoint": "approve"}
}
```

| 步骤 | skill | 三阶段映射 | 检查点 | 负责人 |
|---|---|---|---|---|
| S1 | comp-prob-analysis | M1-A | approve | problem-analyzer |
| S2 | comp-modeling | M1-B | feedback | model-advisor |
| S3 | comp-code-race | M2 基础求解 | approve | solver（并行） |
| S4 | comp-deep-evidence | M2 深化 | 无（自动门） | solver |
| S5 | comp-figures | M2 图表 | 无（自动门） | solver / data-processing |
| S6 | comp-paper-zh | M3-A/B/C | approve | paper-writer |
| S7 | comp-review | M3-D | 无（自动门） | paper-reviewer / paper-judge |
| S8 | comp-compile-zh | M3-E | approve | compliance-check + 编译工具 |

---

## S1 审题与数据分析（comp-prob-analysis）

- **三阶段**：M1-A（审题与数据机制审计）。
- **检查点**：approve。
- **负责人**：problem-analyzer。
- **输入**：`00-problem/` 题面与附件、`data/raw/` 实际数据。
- **输出**（必须真实落盘，禁止占位）：
  - `PROBLEM_ANALYSIS.md`：题型判定、每问任务重述、数据盘点结论、风险清单。
  - `01-analysis/analysis.md`：P1 审题、数据盘点和问题拆解。
  - `01-analysis/data-audit.md`：表头 dataset/audit_item/finding/impact/action/verified，≥5 行，`status: ready`。
  - `01-analysis/research-plan.md`：每问至少一行，`status: ready`。
  - `01-analysis/claim-evidence-matrix.md`：每问至少 2 条可证伪主张，`status: ready`。每条主张在看结果前写明独立检查、证伪条件和不确定性处理（对齐 M1 规约）。
- **知识库**：先读外部索引与决策规则，再读内部 INDEX，按需单张读卡并登记。
- **完成后**：`complete S1`；主循环向用户展示 `PROBLEM_ANALYSIS.md` 摘要，approve 后 `checkpoint S1 resolve`。

## S2 建模方案与赛马注册（comp-modeling）

- **三阶段**：M1-B（候选、推导与实验冻结）。
- **检查点**：feedback。
- **负责人**：model-advisor。
- **输入**：S1 全部产物、知识库检索结果。
- **输出**：
  - `01-analysis/model-selection.md`：人类可读方案说明，frontmatter `frozen: true`。
  - `01-analysis/scheme-registry.json`：`version: 1`；每问 ≥2 候选且含 baseline/advanced；required race 冻结 schemes/feasibility_checks/primary_metric/direction/protocol；waived 必须有 waiver_reason。
  - `01-analysis/derivation-notes.md`：每问变量/假设/目标/约束/方向单位/失败条件，`status: ready`。逐问检查变量、假设、目标/关系、约束、公式方向、阈值方向、单位、失败条件。
  - `01-analysis/experiment-matrix.md`：每问至少 4 项实验，覆盖方案比较/诊断/独立验证/不确定性或失效边界，`status: ready`。
  - `MODELING_REPORT.md`：赛马注册说明 + 知识库卡使用登记。
- **S2 gate = check modeling**：registry 机器验证、frontmatter frozen、各表 status ready。
- **完成后**：`complete S2`；向用户交 `MODELING_REPORT.md` 与赛马表求 feedback；采纳后 `checkpoint S2 resolve`；要求修改则 `checkpoint S2 reject --feedback ...` 并重跑本步。

## S3 并行求解与赛马选优（comp-code-race）

- **三阶段**：M2 基础求解契约。
- **检查点**：approve。
- **负责人**：solver（多实例并行）。
- **输入**：S2 冻结的 `scheme-registry.json`、`data/cleaned/` 清洗后数据。
- **派发**：主循环按 **qN × scheme** 并行派 solver，每个实例只做一个候选一个问，只用同一口径（见 `race-protocol.md`）。
- **输出**：
  - 每问每候选脚本 `code/<qN>_<scheme>.py`（候选间禁止复用主逻辑）。
  - `results/qN/summary.md`：`status: solved`、非 none `robustness`、`chosen_scheme`、`schemes_compared`、`key_results` 含带单位核心值。
  - required race 的 `results/qN/scheme-comparison.md`：frontmatter winner/primary_metric，赛马表含 scheme、可行性/status、主指标列，winner 必须 feasible。
  - `results/qN/reproducibility.md`：实际 command、`exit_code: 0`、真实 outputs。
  - 每问 `results/qN/manifest-fragment.md` 草稿。
- **规则**：所有数值来自 workspace 内可执行脚本输出，禁止聊天补数、外推或美化。
- **完成后**：`complete S3`；向用户展示赛马表与 winner，approve 后 `checkpoint S3 resolve` 进入 S4。

## S4 深化与深度证据（comp-deep-evidence）

- **三阶段**：M2 深化。
- **检查点**：无（自动门）。
- **负责人**：solver，每问一个实例。
- **输入**：S3 的 winner 与赛马产物。
- **输出**：每问六份 `results/qN/*.md`，frontmatter `question: qN`、`status: verified`，表头 check/method/result/evidence/implication/verified，evidence 引用真实工件：
  - `diagnostics.md`（≥3）、`ablation.md`（≥1，仅不可拆时实质 waiver）、`independent-validation.md`（≥1 条证据链，禁 waiver，登记 validation_kind/independence_basis/validation_artifact 指向真实文件）、`uncertainty.md`（≥2）、`failure-boundaries.md`（≥2）、`semantic-checks.md`（≥3 项方向/阈值/单位/单调/极端值检查）。
- **闭环**：深度证据只对 winner 闭环；ablation 可做 winner 与 runner-up 对比。独立验证不得由同一训练拟合、主脚本重跑、同实现换种子冒充。
- **完成后**：`complete S4`（无检查点，自动门过即 completed）。

## S5 图表生成与清单（comp-figures）

- **三阶段**：M2 图表。
- **检查点**：无（自动门）。
- **负责人**：solver / data-processing，每问一个实例。
- **输入**：S3/S4 的 winner 结果与证据。
- **输出**：每问 `results/qN/figs/fig_*.png` 与**同 stem PDF** 成对；自明标题；必要时 `results/qN/tables/*.csv`；每问正式 `results/qN/manifest-fragment.md`（solver 只写本问片段）。
- **主循环执行**：`merge_manifest.py` 重建 canonical `results/manifest.md` → `--check` → `complete S5`。
- **gate S5 检查**：canonical manifest 重建且 --check 通过、每问至少一对 PNG/PDF；中文样式由 `plot_style.py` 注入。

## S6 论文写作与装配（comp-paper-zh）

- **三阶段**：M3-A（规划）/ M3-B（分离写作）/ M3-C（证据闭合）。
- **检查点**：approve。
- **负责人**：paper-writer，主循环主导，可并行每问。
- **输入**：`results/manifest.md`（唯一图表事实源）、每问 summary + 六份深度证据。
- **输出**：
  - 每问三份独立正文 `paper/sections/qN-{modeling-process,results,model-argumentation}.md`（建模过程/结果/论证严格分离：建模过程写任务/机理/推导/求解，结果写数值与解释，论证写方案选择/诊断/独立验证/不确定性/失效边界；三者只交叉引用不复制）。
  - `paper/abstract.md`：背景/总体框架一段 + 每问独立一段 + 综合边界一段 + 关键词。
  - `paper/paper-expansion-ledger.md`：每问三职责行 + 目标页数 + overlap guard。
  - 证据闭合三件套 `evidence-ledger.md` / `argument-map.md` / `question-depth-matrix.md`。
  - 装配稿 `paper/latex/main.tex`（模板 `templates/comp_cumcm/latex/`）或 `paper/word/`（scripts/word_build.py）。
  - 正文 ≥25 页（四问数据题 28--35 规划，正文与附录分开统计）。
  - 每张正文图：图下自明标题 + 紧随其后的读图解释段落。
- **完成后**：`complete S6`；主循环把摘要与装配稿交用户 approve（对应 confirm abstract）后 `checkpoint S6 resolve`。

## S7 两轮评审与三席盲评（comp-review）

- **三阶段**：M3-D。
- **检查点**：无（自动门）。
- **负责人**：paper-reviewer（两轮）、paper-judge（三席并行）。
- **输入**：S6 装配稿与全部证据工件。
- **流程**：
  1. Round 1 reviewer 挑 P0/P1/P2 写 `paper/review-report.md`；writer 修订记 `paper/revision-log.md`。
  2. Round 2 reviewer 从头复核，要求 `round >= 2`、`p0_count: 0`、`verdict: pass`。
  3. 深度审计 `paper/depth-audit.md`：九维总分 ≥30/36、每维 ≥3。
  4. 三席盲评并行派 3 个 paper-judge 席 A/B/C（互不共享上下文、不知通过阈值），各出 `judge-scorecard-{A,B,C}.md`；`judge_aggregate.py --target <国一|国二>` 聚合出 `judge-panel.md`（verdict:pass、conflicts:0）。
  5. 迭代预算：`iteration_budget.py record <workspace> paper --open-issues N`、re-score 后 `rescore`；超限写 `paper/decision-memo.md` 停下等用户。
- **完成后**：`complete S7`（无检查点）。

## S8 合规检查与最终包编译（comp-compile-zh）

- **三阶段**：M3-E。
- **检查点**：approve。
- **负责人**：compliance-check + 编译工具。
- **输入**：S7 通过的论文包。
- **流程**：
  1. 编译最终包：LaTeX（scripts/build_latex.py / build_latex.bat）或 Word（scripts/word_build.py），输出 `paper/final/` 下 PDF 或 DOCX。
  2. `paper/final/compliance-report.md`：frontmatter status:pass / body_pages（≥25）/ appendix_pages / page_rule_checked / body_page_target。
  3. 更新 `paper/evidence-ledger.md` 的 reviewed_package 指向真实最终包。
  4. 最终数字抽查：正文数字与 results summary 一致（数据真实性红线）。
- **完成后**：`complete S8`（gate = 合规 pass + 最终包有效 + check paper 全绿）；最终包交用户 approve（对应 confirm paper），resolve 后 `sync-state`，工作流完成。

---

## 派发不变式（全部步骤通用）

- 主循环先 `start Sx`，再派发对应 comp-* 子 Agent。
- 子 Agent 只收目标/路径/范围，不复述文件全稿。
- 子 Agent 产出落盘后，主循环跑质量门（`complete`）或只读 `gate`。
- 带检查点步骤在 `waiting_checkpoint` 前必须先向用户展示真实产物摘要。
- 任何 `reject` 都打回该步重跑同一 skill，禁止跳过。
- 每步或关键门完成后向 `progress.md` 追加一行。
- 无检查点步骤（S4/S5/S7）由自动门直接 completed，仍需 `advance` 验证前置门全绿。

## 常见交互陷阱

| 陷阱 | 正确做法 |
|---|---|
| 子 Agent 自行 `complete` 后直接宣称下一步 | 引擎命令由主循环统一执行，禁止子 Agent 跳过门 |
| 在 `waiting_checkpoint` 上重跑该步 | 补人工确认，不重跑 |
| 跳过 S2 feedback 直接进 S3 | 不允许；registry 冻结前必须用户反馈 |
| 对每一候选都做全套 S4 证据 | 只对 winner 闭环 |
