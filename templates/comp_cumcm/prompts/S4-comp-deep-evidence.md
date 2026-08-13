# S4 任务简报：深化与深度证据（comp-deep-evidence）

派发对象：solver（每问一个实例，只做 winner 及必要的 runner-up 对比）
输入：S3 的 winner 与赛马产物
输出（每问六份，frontmatter `question: qN`、`status: verified`，表头
check/method/result/evidence/implication/verified，evidence 必须引用真实工件）：

- `results/qN/diagnostics.md`：至少 3 项
- `results/qN/ablation.md`：至少 1 项（模型确实不可拆时允许实质 waiver）
- `results/qN/independent-validation.md`：至少 1 条独立证据链，禁止 waiver；
  frontmatter 登记 validation_kind / independence_basis / validation_artifact（必须指向真实文件）
- `results/qN/uncertainty.md`：至少 2 项
- `results/qN/failure-boundaries.md`：至少 2 个边界
- `results/qN/semantic-checks.md`：至少 3 项方向/阈值/单位/单调/极端值检查

同一训练拟合、主脚本重跑、同实现换种子不得冒充独立验证。
完成后运行：`python scripts/workflow_engine.py <workspace> complete S4`（无检查点，gate 过即 completed）。
