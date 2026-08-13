# 2025C 回溯验证报告（workflow-validation）

> 验证对象：`scripts/workflow_engine.py`（Modex 式 8 步状态机）+ `templates/comp_cumcm/`
> + 复用的三阶段门禁。验证方式：把已完成工作区 `workspace/2025C-nipt` 的既有产物
> **回填**到新状态机，验证 8 步 gate 全绿、状态对齐与断点恢复，不重跑任何模型。
> 日期：2026-08-13（引擎 v1）。

## 1. 回填过程

```bash
python scripts/workflow_engine.py workspace/2025C-nipt init --template comp_cumcm --subquestions 4 --title "2025C NIPT"
python scripts/workflow_engine.py workspace/2025C-nipt backfill --steps S1,S2,S3,S4,S5,S6,S7,S8 --confirmed modeling,abstract,paper
```

- 8 步全部 `completed`；S1/S2/S3/S6/S8 的检查点按模板类型生成 `resolved` 记录；
- 三项用户确认（modeling/abstract/paper）写入引擎 meta；
- `workflow-state.json` 未改动（`sync-state --check` 只读验证）。

## 2. 八步质量门结果

| 步骤 | 门禁内容 | 结果 |
|---|---|---|
| S1 | PROBLEM_ANALYSIS.md + analysis.md + data-audit.md 非空 | PASS（PROBLEM_ANALYSIS.md 由既有 analysis.md 回填生成） |
| S2 | `check modeling`：五表契约 + registry 机器验证 + 用户确认 | PASS |
| S3 | 每问 summary solved/chosen_scheme + 赛马表 winner 三方一致 + 脚本存在 | PASS |
| S4 | 六份深度证据 + independent-validation frontmatter（kind/basis/artifact） | PASS |
| S5 | canonical manifest `merge_manifest --check` + 每问 PNG/PDF 图对 | PASS |
| S6 | 每问三份正文 + abstract + 装配稿（docx 有效）+ 三件套 | PASS |
| S7 | review-report round≥2/p0=0/pass + revision-log closed + depth-audit + 判审团三席 + judge-panel pass | PASS |
| S8 | compliance pass + 最终包有效 + `check paper` 全绿 | PASS |

8/8 全绿。S8 是总锁：合规 + 最终包 + 完整 `check_paper`（含证据台账、论证地图、
深度审计、两轮审查、判审团聚合），保证新工作流的最终门不低于既有三阶段门。

## 3. 状态对齐（sync-state）

- `sync-state --check` PASS：引擎 8 步状态映射回三阶段
  （S1-S2→modeling、S3-S5→code、S6-S8→paper）后，与 `workflow-state.json` 的
  stages 状态完全一致（modeling/code/paper 均 completed）。
- 历史工作区兼容：无 `.engine/` 的工作区仍走 `workflow_gate.py` 只读检查。

## 4. 断点恢复演练

1. 用 SQLite 直写把 S7 置为 `running`（模拟步骤执行中崩溃）；
2. `resume` → S7 复位为 `pending`，日志记录 crash recovery；
3. `advance` → 输出 `next: start S7 (comp-review)`；
4. 重新 `backfill --steps S7` 恢复完成态。

结论：崩溃后可从最近未完成步骤重入，检查点记录不丢失。

## 5. 结论与边界

- **结论**：引擎 + 模板 + 门禁在真实完整产物上验证通过，可作为 comp_cumcm 的
  统一控制面；`workflow_gate.py` 仍是三阶段兼容视图，两者不冲突。
- **边界**：本次为回填验证，未真实执行 S1-S8 的 agent 派发；真实跑题的编排
  （子 agent 并行赛马、检查点与用户的交互）由 `comp-workflow` 技能 SOP 驱动，
  建议在下一次真实比赛中全流程演练。
- 遗留：`compliance-report.md` 正文内“18:58 生成”时间戳与最终 docx mtime（20:46）
  存在文案出入，非门禁问题，已在报告中登记。
