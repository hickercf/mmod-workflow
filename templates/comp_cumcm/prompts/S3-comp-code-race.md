# S3 任务简报：并行求解与赛马选优（comp-code-race）

派发对象：solver（每问每候选一个实例，主循环并行派发）
输入：S2 冻结的 scheme-registry.json（候选、可行性、主指标、方向、协议）、
`data/cleaned/` 清洗后数据
规则（赛马协议，见 .claude/skills/comp-workflow/references/race-protocol.md）：

- 每问每个注册候选一个独立脚本 `code/<qN>_<scheme>.py`，禁止候选间复用主逻辑
- 所有候选必须同一数据划分、同一折数、同一随机种子口径、可比预算
- 输出 `results/qN/summary.md`（status: solved、chosen_scheme、schemes_compared、
  key_results 含带单位核心值、robustness 非 none）
- required race 输出 `results/qN/scheme-comparison.md`：frontmatter winner/primary_metric，
  赛马表含 scheme、可行性/status、主指标列，winner 必须 feasible
- 每问输出 `results/qN/manifest-fragment.md` 草稿（S5 正式重建）
完成后运行：`python scripts/workflow_engine.py <workspace> complete S3`
主循环展示赛马表与 winner 给用户 approve；`checkpoint S3 resolve` 后进入 S4。
