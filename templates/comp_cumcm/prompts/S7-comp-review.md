# S7 任务简报：两轮评审与三席盲评（comp-review）

派发对象：paper-reviewer（两轮）、paper-judge（三席并行，互不共享上下文）
输入：S6 装配稿与全部证据工件
流程：

1. Round 1：reviewer 挑 P0/P1/P2，写 `paper/review-report.md`；writer 修订并记
   `paper/revision-log.md`
2. Round 2：reviewer 从头复核，要求 `round >= 2`、`p0_count: 0`、`verdict: pass`
3. 深度审计：`paper/depth-audit.md` 九维总分 >=30/36、每维 >=3
4. 三席盲评：并行派 3 个 paper-judge 席 A/B/C（不知通过阈值），各出
   `paper/judge-scorecard-{A,B,C}.md`；`python scripts/judge_aggregate.py <workspace> --target <国一|国二>`
   聚合出 `paper/judge-panel.md`（verdict: pass、conflicts: 0）
5. 迭代预算：`scripts/iteration_budget.py record <workspace> paper --open-issues N`；
   超限必须写 `paper/decision-memo.md` 停下等用户

完成后运行：`python scripts/workflow_engine.py <workspace> complete S7`（无检查点）。
