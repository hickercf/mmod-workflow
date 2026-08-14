---
name: comp-workflow-quality-gates
purpose: "每步自动质量门清单（S1 文件契约、S2=check modeling、S3 赛马表、S4 六份证据、S5 manifest+图对、S6 三正文+装配+三件套、S7 两轮评审+判审团、S8 合规+check paper）与人工检查点清单。"
---

# 质量门与人工检查点

每步在 `complete` 时跑自动质量门，通过后带检查点步骤进入人工检查点；两层都通过才进入下一步。gate 失败 → 步骤保持 `running`，blockers 写 logs，主循环交回对应子 Agent 修复。引擎内置 gate 复用 `scripts/workflow_gate.py` 的 helper（`nonempty_file`、`frontmatter_value`、`markdown_table_raw`、`valid_pdf/docx`、`check_modeling/check_code/check_paper` 等）。

## 门禁通则

- `complete` 是**唯一门入口**；`gate <Sx>` 是只读预运行，可视作查看 blockers 的快捷方式。
- gate 失败时 blockers 写进 logs，步骤保持 `running`——主循环据此交回对应子 Agent 修复，**禁止写占位**。
- 空文件、`status` 非 ready/solved/verified、表头缺字段、frontmatter 缺键都是 blocker。
- frontmatter 顶层键唯一、JSON 成员名唯一（不依赖解析器后值覆盖）。
- 只有 `advance` 前置门全绿才推进下一步。

## S1 自动门：文件契约

- `PROBLEM_ANALYSIS.md`、`01-analysis/analysis.md`、`01-analysis/data-audit.md`、`01-analysis/research-plan.md`、`01-analysis/claim-evidence-matrix.md` 均存在且非空。
- `data-audit.md` 表头 dataset/audit_item/finding/impact/action/verified，≥5 行，`status: ready`。
- `research-plan.md` 每问至少一行、`claim-evidence-matrix.md` 每问至少 2 条可证伪主张，均 `status: ready`。

## S2 自动门：check modeling（复用 check_modeling）

- `model-selection.md` frontmatter `frozen: true`。
- `scheme-registry.json` 版本 1；每问 ≥2 候选含 baseline/advanced、名称互异；required race 冻结 schemes/feasibility_checks/primary_metric/direction/protocol；waived 有 waiver_reason。
- `derivation-notes.md`、`experiment-matrix.md`（每问 ≥4 实验）`status: ready`。
- 机器验证直接调 `workflow_gate.py` 的 `check_modeling`。
- **知识库登记**：`MODELING_REPORT.md` 或 `model-selection.md` 含非占位"参考卡/知识库依据"行（登记动作强制、使用不强制）。
- **选型论证**：`MODELING_REPORT.md` 或 `model-selection.md` 每问段落含候选对比/选择理由/赛马决策等非占位说明（对应获奖论文"选型论证是拿分点"）。

## S3 自动门：赛马表（check_code 相关 helper）

- 每问有匹配 `qN` 的非空生产脚本 `code/<qN>_<scheme>.py`。
- `summary.md`：`status: solved`、`chosen_scheme`、非 none `robustness`、`schemes_compared`、`key_results` 含带单位核心值。
- required race 的 `scheme-comparison.md`：表结构正确（scheme/可行性/主指标列），winner 必须 feasible，且与 summary `chosen_scheme`、registry 三方一致。
- `reproducibility.md`：实际 command、`exit_code: 0`、真实 outputs。
- `manifest-fragment.md` 草稿存在。

## S4 自动门：六份深度证据

每问 `results/qN/` 六份文件，frontmatter `question: qN`、`status: verified`，表头 check/method/result/evidence/implication/verified，evidence 引用真实工件：

- `diagnostics.md` ≥3 项；
- `ablation.md` ≥1 项（仅不可拆时实质 waiver）；
- `independent-validation.md` ≥1 条独立证据链（禁 waiver，frontmatter 登记 validation_kind/independence_basis/validation_artifact 指向真实文件）；
- `uncertainty.md` ≥2 项；
- `failure-boundaries.md` ≥2 个边界；
- `semantic-checks.md` ≥3 项方向/阈值/单位/单调/极端值检查。

独立验证不得由同一训练的训练拟合、主脚本重跑、同实现换种子冒充；专用证据路径须在表 `evidence` 中被引用。

## S5 自动门：manifest + 图对

- canonical `results/manifest.md` 由主循环重建。
- `merge_manifest.py --check` 通过（fragment 与 canonical 一致）。
- 每问至少一对 **PNG/PDF 同 stem** 图，自明标题；中文样式由 `plot_style.py` 注入。
- 图表在 manifest 与 evidence ledger 中闭合。

## S6 自动门：三正文 + 装配 + 三件套（check_paper 相关 helper）

- 每问三份独立正文 `paper/sections/qN-{modeling-process,results,model-argumentation}.md`，各自职责分离：建模过程写任务/机理/推导/求解，结果写数值与解释，论证写方案选择/诊断/独立验证/不确定性/失效边界；三者只交叉引用不复制。可见标题点明本问对象 + 保留职责锚点。
- `paper/abstract.md`（背景/总体框架 + 每问独立段 + 综合边界 + 关键词）、`paper/paper-expansion-ledger.md`、证据闭合三件套 `evidence-ledger.md`/`argument-map.md`/`question-depth-matrix.md`。
- question depth matrix 每问引用三份正文及独立验证/不确定性/失效边界，防止用全篇平均质量掩盖弱问题。
- 装配稿 `paper/latex/main.tex` 或 `paper/word/`；正文 ≥25 页（四问数据题 28--35 规划）；每张正文图自明标题 + 读图解释。
- gate 检查标题锚点、图后解读、最低实质字符数、错误归属标题、跨文件重复长段落、页数/字数目标。

## S7 自动门：两轮评审 + 判审团（check_paper helper）

- `review-report.md`：`round >= 2`、`p0_count: 0`、`verdict: pass`。
- `revision-log.md`：`status: closed`，含 round 1/2，最后一行 `status=pass`。
- `depth-audit.md`：九维总分 ≥30/36、每维 ≥3，证据路径真实，`p0_count: 0`。
- 判审团：`judge-scorecard-{A,B,C}.md` seat 合法、表列 criterion|weight|score、weighted_total 自洽；`judge-panel.md` `verdict: pass`、`conflicts: 0`、min_weighted_total 达目标档、lowest_criterion_score ≥下限（国一 85/70，国二 75/60）。共享单项两两差 >20 记为冲突，只重派离群席一次。
- 迭代预算：每关卡修复≤2、判审团 re-score≤2、全程≤8；每次复评 `iteration_budget.py record`、re-score `rescore`、推进前 `check`；超限写 `paper/decision-memo.md`。

## S8 自动门：合规 + check paper

- `paper/final/compliance-report.md`：`status: pass`、`body_pages >= 25`、`page_rule_checked: true`、`body_page_target`。
- 最终 PDF/DOCX 是有效文件（`valid_pdf`/`valid_docx`）；evidence ledger 的 reviewed_package 指向真实被审包。
- 最终数字抽查：正文数字与 results summary 一致（数据真实性红线）。
- `workflow_gate.py check paper` 全绿。

## 经验闭环（M2 完成后，主循环建议步骤）

- 跑 `python scripts/kb_backfill.py <workspace>`：把每问赛马结论（候选集/winner/主指标/结果摘要/稳健性）追加到 `knowledge-base/distillation/race-log.md`（幂等，`--dry-run` 预览）。每跑一题，Agent 选型经验累积一条。
- 建模技能库 `knowledge-base/distillation/modeling-skills.md` 与写作技能库 `writing-skills.md` 按需取用（S2 建模、S6 写作、S7 评审）。

## 人工检查点清单

| 步骤 | 类型 | 主循环须给用户看什么 | 用户动作 |
|---|---|---|---|
| S1 | approve | `PROBLEM_ANALYSIS.md` 摘要 | 确认后 `checkpoint S1 resolve` |
| S2 | feedback | `MODELING_REPORT.md` + 赛马注册表 | 采纳→resolve；要求改→reject 重跑 |
| S3 | approve | 赛马表 + winner | 确认后 `checkpoint S3 resolve` |
| S6 | approve | 摘要 + 装配稿（对应 confirm abstract） | 确认后 `checkpoint S6 resolve` |
| S8 | approve | 最终包（对应 confirm paper） | 确认后 `checkpoint S8 resolve` |

## 检查点落地示例

```bash
# S1 用户确认后
python scripts/workflow_engine.py <workspace> checkpoint S1 resolve --response '{"ok":true}'

# S2 用户提出修改后（打回重跑同一 skill）
python scripts/workflow_engine.py <workspace> checkpoint S2 reject --feedback 'advanced 的机制改进不成立，请重写'
```

## 通用门禁纪律

- **规则**：任何检查点未确认前不得跳过；reject 打回该步重跑同一 skill；approve 前主循环必须展示真实产物摘要而非结论性空话。
- gate 失败 → blockers 写 logs，主循环交回对应子 Agent 修复，禁止写占位。
- 只有 `advance` 前置门全绿才把下一步列为可执行——"门禁通过才算数"，聊天陈述不能代替受控工件。
- 任一深度证据/审查状态/页数/数字缺失时返回对应 Agent 补实验/补写，不能在 M3 用文字补成"已验证"。
