---
name: comp-workflow-resume-recovery
purpose: "断点恢复流程：resume 命令、running→pending 复位、可重入步骤判定、checkpoint 未决处理，以及历史/崩溃工作区的恢复。"
---

# 断点恢复（resume-recovery）

工作流可能因会话中断、进程崩溃或临时手动停止而停在任意状态。目标是把状态安全地复位到可继续位置，不重做已完成步骤、不漏掉未决检查点。规则与 `docs/workflow-design.md`（第 3 节状态机、第 6 节兼容、第 8 节验证方式）一致。

## 1. 状态机语义回顾

- 8 步状态：`pending → running → waiting_checkpoint → completed`。
- 检查点被打回：步骤置为 `rejected`（记录 feedback，主循环据此重跑该步）。
- 崩溃恢复：把 `running` 复位为 `pending`（见下），打印可重入步骤。
- 库文件在 `<workspace>/.engine/workflow.db`；表 `meta/steps/checkpoints/logs`。

## 2. resume 命令

```bash
python scripts/workflow_engine.py <workspace> resume
```

`resume` 做的事：

- 把处于 `running`（被认为是"进行到一半"）的步骤**复位为 `pending`**——因为运行被中断，不能假设其产物完整；
- **打印可重入步骤**列表，供主循环判定从哪一步继续。

## 3. running→pending 语义

- `running` 表示子 Agent 正在产出但尚未过门或未确认。崩溃/中断后它既非 completed 亦非回滚，视为**半成品**。
- `resume` 一律把它复位为 `pending`：主循环重新 `start` 该步、重新派发对应子 Agent，而不是直接从断点续跑一个未完成的产物。

## 4. 可重入步骤判定

- **重入 = pending 且前置门全绿**的那一步。
- 主循环调用 `advance` 确认：`advance` 只在前置门全绿时才把下一步列为可执行。
- 已经 `completed`（含无检查点步骤和已 resolve 的检查点步骤）不会被重复执行。
- 仍在 `waiting_checkpoint` 的步骤**不是** pending，不可通过 resume 直接重跑；它需要先处理检查点（见下）。

## 5. checkpoint 未决处理

- 若第 Sx 步停在 `waiting_checkpoint`（`complete` 已过自动门，等 `resolve`）：
  - 直接回到人工确认流程，**不重跑该步**。
  - approve 类型：把产物摘要再展示给用户，确认后 `checkpoint Sx resolve`。
  - feedback 类型（S2）：把 `MODELING_REPORT.md` 再交用户，采纳→resolve；要求改→`checkpoint S2 reject --feedback ...` 并把步骤置回 `running` 后重新派发。
- 若检查点记录存在但状态未落定，先 `status` 查库，再按上面补 `resolve`/`reject`。
- **未决检查点不得被 skip**——那会让门禁状态与真实人工授权脱节。

## 6. 常见恢复场景

| 场景 | 处理 |
|---|---|
| 某步 `running`（崩溃中断） | `resume` → pending → 重新 `start`+派发该步 |
| 某步 `waiting_checkpoint` | 不重跑，回到人工确认/打回 |
| 全链无 `.engine`（历史工作区） | 用 `workflow_gate.py` 只读检查；`backfill` 导入已有产物以获得断点恢复能力 |
| 需把旧产物补进引擎 | `backfill [--steps S1,S2,...] [--confirmed modeling,abstract,paper]` |
| 进展莫名停在某一步 | `status`/`report` 查库态，再按上面场景处理 |

## 7. 恢复后的动作

1. `status` 确认库态与 `advance` 出的下一步一致。
2. 重新派发对应 comp-* 子 Agent，**只给目标/路径/范围**。
3. 该步 `complete` 过门后才允许前进；带检查点步骤走人工确认。
4. 向 `progress.md` 追加一条恢复记录（时间/恢复步骤/原因/风险）。

## 8. backfill 补充说明

- `backfill` 把已有历史产物导入引擎，`--steps S1,S2,...` 指定导入哪些步，`--confirmed modeling,abstract,paper` 回填确认记录。
- 它只起**导入**作用，不能替代 Agent 补写证据；导入后相关步骤仍要 `complete`/`advance` 验证门禁一致性。
- 时间戳取自现有 `workflow-state.json`/`progress.md`，不捏造新时间。

## 9. 演练示例（对齐 docs 第 8 节验证方式）

模拟崩溃恢复：

```bash
# 某时刻 S7 被置为 running（模拟崩溃现场）
python scripts/workflow_engine.py <workspace> resume
# → S7 复位 pending，打印可重入步骤（例如 pending 且前置门全绿的某一步）
python scripts/workflow_engine.py <workspace> advance
# → 确认下一步
```

历史工作区回溯验证：

```bash
python scripts/workflow_engine.py <workspace> backfill --steps S1,S2,S3,S4,S5,S6,S7,S8 --confirmed modeling,abstract,paper
python scripts/workflow_engine.py <workspace> gate S1   # …对 S1..S8 逐门
python scripts/workflow_engine.py <workspace> sync-state --check
```

## 10. 红线

- 禁止从半成品 `running` 直接声明 completed。
- 禁止跳过未决人工检查点。
- 全程复用时限制在 `math-modeling/references/iteration-budget.md` 的 8 轮内；多次恢复不重置预算消耗。
- 恢复不是重新赛马或重写论文的理由：已完成 steps 与已 resolve 检查点原样保留。
