# mmod-workflow — 数学建模国赛 Agent（统一 8 步工作流 + DSH 插件）

以 Modex 式竞赛工作流（分析→建模→代码→图表→论文→编译）为骨架，整合
**三阶段契约（M1 建模 / M2 代码 / M3 论文）、候选赛马机制、六份深度证据、
两轮对抗审查 + 三席盲评判审团、外部知识库驱动**，从题面到可提交论文包的全流程
Agent 工作流。附带 **DSH（DeepSeek Harness）动态插件**：Agent 工具驱动引擎 +
网页 8 步状态看板。

## 特性

- **8 步状态机**（SQLite，`pending → running → waiting_checkpoint → completed`）：
  S1 审题 → S2 建模与赛马注册 → S3 并行赛马求解 → S4 深度证据 → S5 图表 →
  S6 论文装配 → S7 两轮评审+三席盲评 → S8 合规编译
- **赛马机制**：每问 ≥2 注册候选（baseline + advanced），同折同种子同口径并行比较，
  winner 按 feasibility → 主指标 → 稳健性 → runtime 规则选出，三方一致性机器校验
- **双闸质量门**：每步自动门（文件契约/图表健康/页数/数字一致性）+ 人工检查点
  （S1/S3/S6/S8 approve、S2 feedback），检查点可打回重跑、断点可恢复
- **高要求终检**：两轮对抗审查 + 三席盲评判审团 + 合规报告（正文 ≥25 页）全过才出包
- **知识库驱动**：外部知识库优先（MOC 总索引 → 模型选择决策规则 → 内部 INDEX →
  按需单张读卡）；S1/S2 门禁强制"参考卡"登记（登记动作强制、使用不强制；
  卡片只启发思路，数值必须来自可执行脚本产物）
- **DSH 插件**：`mmod_workflow` 工具（11 个引擎动作）+ 设置页 8 步状态看板

## 架构

| 步骤 | skill | 检查点 | 三阶段映射 |
|---|---|---|---|
| S1 审题分析 | comp-prob-analysis | approve | M1-A |
| S2 建模与赛马注册 | comp-modeling | feedback | M1-B |
| S3 并行求解与赛马选优 | comp-code-race | approve | M2 基础 |
| S4 深化与深度证据 | comp-deep-evidence | 自动门 | M2 深化 |
| S5 图表与清单 | comp-figures | 自动门 | M2 图表 |
| S6 论文写作与装配 | comp-paper-zh | approve | M3-A/B/C |
| S7 两轮评审与三席盲评 | comp-review | 自动门 | M3-D |
| S8 合规检查与最终包 | comp-compile-zh | approve | M3-E |

## 快速开始

```bash
# 1. 建工作区骨架
python scripts/init_workspace.py workspace/2026A-demo --title "题名" --subquestions 4

# 2. 初始化引擎（8 步模板 comp_cumcm）
python scripts/workflow_engine.py workspace/2026A-demo init --template comp_cumcm --subquestions 4

# 3. 查看下一步并推进
python scripts/workflow_engine.py workspace/2026A-demo advance
python scripts/workflow_engine.py workspace/2026A-demo start S1
# …… 完成后跑质量门
python scripts/workflow_engine.py workspace/2026A-demo complete S1
python scripts/workflow_engine.py workspace/2026A-demo checkpoint S1 resolve
```

引擎命令（`<workspace> <命令>` 与 `<命令> <workspace>` 均可）：

```bash
python scripts/workflow_engine.py <ws> init --template comp_cumcm --subquestions N [--title X]
python scripts/workflow_engine.py <ws> status [--json] | advance | resume | report
python scripts/workflow_engine.py <ws> start <S1..S8>
python scripts/workflow_engine.py <ws> complete <S1..S8> [--note ...]
python scripts/workflow_engine.py <ws> gate <S1..S8>
python scripts/workflow_engine.py <ws> checkpoint <S1..S8> resolve [--response ...]
python scripts/workflow_engine.py <ws> checkpoint <S1..S8> reject --feedback ...
python scripts/workflow_engine.py <ws> backfill [--steps ...] [--confirmed ...]
python scripts/workflow_engine.py <ws> sync-state [--check]
```

自由文本参数（title/note/response/feedback）支持 `b64:` 前缀 base64 编码（DSH 插件传参用）。

## 质量门速览

| 步骤 | 自动门 |
|---|---|
| S1 | PROBLEM_ANALYSIS/analysis/data-audit 非空 + **知识库登记行** |
| S2 | 五表契约 + scheme-registry 机器验证 + **知识库登记行** + 用户确认 |
| S3 | summary solved + 赛马表 winner 三方一致 + 脚本存在 |
| S4 | 六份深度证据 + independent-validation frontmatter（kind/basis/artifact） |
| S5 | canonical manifest `merge_manifest --check` + PNG/PDF 图对 |
| S6 | 每问三份正文 + 摘要 + 装配稿 + 证据三件套 |
| S7 | review-report round≥2/p0=0/pass + 判审团三席 + judge-panel pass |
| S8 | 合规 pass + 最终包有效 + `check paper` 全绿（总锁） |

## DSH 插件

见 [`plugin/README.md`](plugin/README.md)：`host.js`（`mmod_workflow` 工具 +
`mmod-status` RPC）、`client.js`（设置页状态看板）。在 DSH 会话中
`cordis_define`（code.host/code.client 分别粘贴两个文件内容）→ `cordis_run` 激活。

## 知识库接入

检索顺序固定：外部 `D:\数学建模知识库\MathModel-Agent-KB\00_Index\MOC-总索引.md`
→ 外部 `模型选择决策规则.md` → 内部 `knowledge-base/INDEX.md` → 按需单张读卡。
外部缺失仅回退内部库；S1/S2 门禁强制登记"参考卡：…，用于 …"（未引用时写明理由）。
卡片只提供建模思路与方法启发，禁止把卡片数值/阈值/结论写入本题工件。

## 目录结构

```
scripts/                 workflow_engine.py（状态机）/ workflow_gate.py（三阶段门禁，被复用）
                         / merge_manifest.py / init_workspace.py / plot_style.py
templates/comp_cumcm/    steps.json（8 步定义）、prompts/（每步任务简报）、
                         latex/（cumcmthesis.cls v2.6 + main.tex 骨架）
.claude/skills/comp-workflow/  SKILL.md + references/（steps/race-protocol/quality-gates/
                         resume-recovery/kb-retrieval）
plugin/                  DSH 插件：host.js / client.js / README.md
docs/                    workflow-design.md（唯一事实源）/ workflow-validation.md（2025C 回溯验证）
tests/                   引擎门禁测试（pytest）
```

## 许可与致谢

- 本仓库 MIT 许可（见 LICENSE）。
- `templates/comp_cumcm/latex/cumcmthesis.cls` 为开源 CUMCM 模板 v2.6
  （2017/09/16），源自社区竞赛模板，按社区许可使用并注明出处。
- 工作流编排理念参考 Modex-MH-Agent 的 7 步竞赛工作流；本仓库**不包含**
  任何加密 Skill 内容或商业资产，仅复用其开源 LaTeX 模板。

## 验证

`docs/workflow-validation.md`：以 2025C（NIPT）完整产物回填验证，8/8 质量门全绿、
状态对齐、断点恢复演练通过（未重跑模型）。
