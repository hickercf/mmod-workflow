# 统一数学建模工作流设计（v1）

> 本文是 `comp-workflow` 技能、`scripts/workflow_engine.py`、`templates/comp_cumcm/`
> 与全部质量门的**唯一事实源**。改动任何实现前先改本文。
>
> 血缘：以 Modex-MH-Agent 的 7 步竞赛工作流（分析→建模→代码→图→图→论文→编译，
> SQLite 状态机 + 人工 checkpoint + 自动质量门 + 断点恢复）为骨架，整合本仓库既有优势
> （M1/M2/M3 三阶段契约、候选赛马机制、六份深度证据、两轮对抗审查 + 三席盲评判审团、
> 外部知识库优先检索），目标产出高要求国奖级论文包。

## 1. 设计目标

1. **完整工作流**：从题面到可提交论文包，8 个步骤、线性推进、可暂停/恢复/重跑。
2. **赛马机制**：每问至少 2 个注册候选（baseline + advanced），M2 并行实现、同口径
   比较、按规则选优；深度证据只对 winner（及需要的 runner-up）闭环。
3. **双闸质量**：每步自动质量门（文件契约/图表健康/数字一致性/页数）+ 人工检查点
   （approve / feedback），两者都通过才进入下一步。
4. **高要求终检**：两轮对抗审查 + 三席盲评判审团 + 合规报告，全部 pass 才出最终包。
5. **知识库驱动**：外部知识库（`D:\数学建模知识库\MathModel-Agent-KB\00_Index\MOC-总索引.md`）
   优先、内部 `knowledge-base/INDEX.md` 补充，按需单张读卡。
6. **与既有生态兼容**：`workflow-state.json` / `workflow_gate.py` 继续可用，历史工作区
   不受影响；引擎通过 `sync-state` 与之对齐。

## 2. 总览：comp_cumcm 八步模板

Modex 的 7 步（prob-analysis → modeling → code → figures → figures-drawio →
paper → compile）合并了“两种图”为一步，并插入本仓库的深化证据与评审判审两步：

| 步骤 | skill | 产出契约 | 检查点 | 三阶段映射 |
|---|---|---|---|---|
| S1 | comp-prob-analysis | `PROBLEM_ANALYSIS.md`、`01-analysis/analysis.md`、`01-analysis/data-audit.md` | approve | M1-A |
| S2 | comp-modeling | `01-analysis/model-selection.md`(frozen)、`scheme-registry.json`、`MODELING_REPORT.md`、研究计划/主张/推导/实验四表 | feedback | M1-B |
| S3 | comp-code-race | 每问每候选 `code/*.py`、`results/qN/summary.md`、`scheme-comparison.md`（赛马表 + winner） | approve | M2 基础求解 |
| S4 | comp-deep-evidence | 每问六份深度证据 `results/qN/{diagnostics,ablation,independent-validation,uncertainty,failure-boundaries,semantic-checks}.md` | 无（自动门） | M2 深化 |
| S5 | comp-figures | 每问 `results/qN/figs/*.png`+同 stem PDF、`manifest-fragment.md`→canonical `results/manifest.md` | 无（自动门） | M2 图表 |
| S6 | comp-paper-zh | 每问三份正文 `paper/sections/qN-{modeling-process,results,model-argumentation}.md`、`abstract.md`、装配稿（tex/docx）、证据台账/论证地图/深度矩阵 | approve | M3-A/B/C |
| S7 | comp-review | `review-report.md`(round≥2, p0=0, pass)、`revision-log.md`(closed)、`depth-audit.md`(≥30/36)、`judge-scorecard-{A,B,C}.md`、`judge-panel.md`(pass) | 无（自动门） | M3-D |
| S8 | comp-compile-zh | `paper/final/compliance-report.md`(pass)、最终 PDF/DOCX、`reviewed_package` 指向真实文件 | approve | M3-E |

步骤状态机：`pending → running → waiting_checkpoint → completed`；检查点被打回为
`rejected`（记录 feedback，主循环据此重跑该步）；崩溃恢复把 `running` 复位为 `pending`。

## 3. 引擎：scripts/workflow_engine.py

Modex 式 SQLite 状态机，库文件位于 `<workspace>/.engine/workflow.db`（`.engine/` 加入
.gitignore）。表：`meta`、`steps`、`checkpoints`、`logs`。

### 3.1 命令

```bash
python scripts/workflow_engine.py <workspace> init --template comp_cumcm [--subquestions N] [--title X]
python scripts/workflow_engine.py <workspace> status [--json]
python scripts/workflow_engine.py <workspace> start <S1..S8>
python scripts/workflow_engine.py <workspace> complete <S1..S8> [--note ...]   # 跑质量门；通过→waiting_checkpoint(有检查点)/completed
python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> resolve [--response <json>]
python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> reject --feedback <text>
python scripts/workflow_engine.py <workspace> gate <S1..S8>                     # 只读跑该步质量门
python scripts/workflow_engine.py <workspace> advance                           # 打印下一个可执行步骤（前置门全绿才推进）
python scripts/workflow_engine.py <workspace> resume                            # running→pending，打印可重入步骤
python scripts/workflow_engine.py <workspace> backfill [--steps S1,S2,...] [--confirmed modeling,abstract,paper]
python scripts/workflow_engine.py <workspace> sync-state [--check]              # 对齐 workflow-state.json；--check 只读
python scripts/workflow_engine.py <workspace> report                            # 机器可读 JSON（供主循环/UI）
```

`status`、`gate`、`advance`、`report`、`sync-state --check` 只读；其余命令写库。
所有写操作记入 `logs` 与 `progress.md`。自由文本参数（`--title/--note/--response/--feedback`）
支持 `b64:` 前缀的 base64 编码值（DSH 插件经 shell 传参时使用，引擎在 main() 统一解码）。

### 3.2 质量门实现

S1/S3/S4/S6/S7/S8 使用引擎内置 gate 函数（复用 `scripts/workflow_gate.py` 的
helper：`nonempty_file`、`frontmatter_value`、`markdown_table_raw`、`valid_pdf/docx`、
`check_modeling/check_code/check_paper` 等）；S2 直接调 `check_modeling`；S5 调
`merge_manifest.py --check` + 图对检查。gate 失败 → `complete` 拒绝，步骤保持
`running` 并写 blockers 到 logs（主循环把 blockers 交给对应子 agent 修复，不写占位）。

### 3.3 检查点协议

- `approve`：resolve 需要 response（可空）；主循环必须给用户看产物摘要。
- `feedback`：resolve 接受用户意见，主循环把它转成下一步修订任务；reject 记录反馈并
  把步骤置回 `running`（重新执行同一 skill，不允许跳过）。
- 每个检查点生成一行 `checkpoints` 记录，时间与 response 留痕（对齐“文件即协议”）。

## 4. 赛马机制（race protocol）

1. **S2 注册**：`scheme-registry.json` 每问 ≥2 候选、含 baseline 与 advanced、
   唯一名称；required race 冻结 schemes/feasibility/primary_metric/direction/protocol；
   waived 必须写 waiver_reason。由 `check_modeling` 机器验证。
2. **S3 并行**：主循环按 `qN × scheme` 并行派 solver（每个实例只做一个候选一个问），
   全部用**相同数据划分、相同折数、相同随机种子口径、可比预算**（registry protocol）。
3. **比较**：`results/qN/scheme-comparison.md` 赛马表（scheme/可行性/主指标列），
   winner 顺序 = feasibility → primary metric → robustness/secondary → runtime/interpretability；
   winner 必须 feasible 且与 `summary.md chosen_scheme`、registry 三方一致。
4. **深化**：S4 深度证据只对 winner 闭环；ablation 可对 winner 与其 runner-up 对比
   拆解。S5 图表只产出 winner 及必要的诊断图。
5. 引擎 S3 gate 校验赛马表结构、winner 一致性；S2 gate（check_modeling）已保证注册合法。

## 5. 知识库检索（kb-retrieval）

检索顺序固定：**外部** `D:\数学建模知识库\MathModel-Agent-KB\00_Index\MOC-总索引.md`
→ 外部 `模型选择决策规则.md` → **内部** `knowledge-base/INDEX.md` → 按需单张读卡。
外部库缺失/校验失败时仅回退内部库。禁止整目录灌入上下文。检索结果必须在
`MODELING_REPORT.md`/`model-selection.md` 中登记“读了哪几张卡、用于哪个决策”。

**门禁（S1/S2 强制）**：gate S1 检查 `PROBLEM_ANALYSIS.md` 或 `analysis.md` 含非占位
登记行（`参考卡：<卡名>，用于 <决策>`）；gate S2 检查 `MODELING_REPORT.md` 或
`model-selection.md` 含登记行。未引用卡片时写明理由亦可过门（登记动作强制、使用不强制）。
**边界**：卡片只提供建模思路与方法启发，禁止把卡片数值/阈值/结论写入本题工件——
本题所有数值必须来自 workspace 内可执行脚本产物（与“数据真实性红线”一致）。

## 6. 与现有三阶段生态的兼容

- `workflow_gate.py` 与 `workflow-state.json` 保持不变；引擎是**更细粒度的控制面**。
- `sync-state` 把 8 步状态映射回三阶段：S1-S2→modeling、S3-S5→code、S6-S8→paper；
  三步完成且对应 confirmation 存在时，`workflow_gate status` 仍显示 complete。
- 历史工作区（无 `.engine/`）继续用 `workflow_gate.py` 只读检查；`backfill` 可把已有
  产物导入引擎以获得断点恢复能力。
- 所有新增目录（`.engine/`、`templates/`）纳入 .gitignore/仓库管理，不改动旧产物。

## 7. 交付物清单

| 文件 | 职责 |
|---|---|
| `docs/workflow-design.md` | 本文 |
| `scripts/workflow_engine.py` | SQLite 状态机引擎 |
| `templates/comp_cumcm/steps.json` | 8 步定义（引擎 init 读取） |
| `templates/comp_cumcm/prompts/*.md` | 每步主循环任务简报模板 |
| `templates/comp_cumcm/latex/` | cumcmthesis.cls（来源：Modex 安装包内置开源模板 v2.6）+ main.tex 骨架 |
| `.claude/skills/comp-workflow/SKILL.md` | 顶层编排 SOP |
| `.claude/skills/comp-workflow/references/{steps,race-protocol,quality-gates,resume-recovery,kb-retrieval}.md` | 编排细节 |
| `tests/test_workflow_engine.py` | 引擎 + gate 测试 |

## 8. 验证方式（2025C 回溯）

1. `init` 2025C-nipt（`--subquestions 4`）。
2. `backfill --steps S1..S8 --confirmed modeling,abstract,paper`：8 步全部 completed，
   检查点 resolved，时间戳取自现有 `workflow-state.json`/`progress.md`。
3. 逐 `gate S1..S8` 全部零 blockers；`sync-state --check` 与现有状态一致。
4. `resume` 演练：把 S7 置 running 模拟崩溃，`resume` 复位并给出可重入步骤。
5. 结论写入 `docs/workflow-validation.md`（2025C 回溯报告）。

## 9. 非目标（v1 不做）

- 不重写 `workflow_gate.py` 的三阶段门禁逻辑（只复用）。
- 不做 Modex 式的图形 DOM 几何检查与视觉 QA（保留为 M3/人工终审项；v2 可接入）。
- 不破解 Modex 的加密 SKILL；LaTeX 模板仅复用其内置开源 `cumcmthesis.cls`（v2.6，
  按社区许可使用并注明出处）。
- 不把主循环调度器做成守护进程；编排仍由主循环（Agent 会话）驱动，引擎只负责状态与门。
