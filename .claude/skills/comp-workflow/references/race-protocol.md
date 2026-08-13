---
name: comp-workflow-race-protocol
purpose: "赛马机制的完整规则：S2 注册、S3 并行实现同口径、比较表结构、winner 选择顺序、三方一致性校验、S4/S5 只对 winner 闭环的深化。"
---

# 赛马机制（race protocol）

赛马让每个问题先在**多个候选方案之间公平竞争**，再只对胜者做深度证据与图表闭环，避免把资源浪费在陪跑方案上。规则与 `docs/workflow-design.md` 第 4 节一致。

## 1. 赛马要解决的问题

- 同一子问题常有多个可行方法（如一个插值/拟合类、一个基于机理的 advanced）。不做比较就写论文，会缺少"为什么选这个"的可证伪依据。
- 统一用"注册 → 并跑同口径 → 排序 → 择优 → 对 winner 闭环"的协议，让选择基于受控数据而非直觉。
- 关键前提：**fair comparison**。只有同口径才有可比性，不同口径的差别会被误判成方案优劣。

## 2. S2 注册赛马（comp-modeling）

- 每问在 `scheme-registry.json` 中注册 **≥2 个名称互异的候选**，且必须包含 `kind: baseline` 与 `kind: advanced`。
- `advanced` 表示有明确机制改进、验证改进或适配数据结构的改进，**不等于**深度学习或更复杂。
- **required race**（`race.required: true`）必须冻结（不得在 M2/M3 擅自改写）：
  - `schemes`：候选集合；
  - `feasibility_checks`：可行性检查项；
  - `primary_metric`：主指标；
  - `direction`：优化方向（更大/更小/目标值）；
  - `protocol`：公平比较协议（数据切分/随机种子/可比预算）。
- **waived race**（`race.required: false`）必须写实质 `waiver_reason`，M3 只写简洁定性选择理由，不伪造指标。
- 注册的机器合法性由 **S2 gate（即 `check_modeling`）** 验证。注册冻结后，候选集、是否赛马、可行性检查、主指标、方向、辅助指标、协议、waiver 均不得在 M2 擅改。

## 3. S3 并行实现与同口径口径（comp-code-race）

- 主循环按 **qN × scheme** 并行派 solver，每个实例只做一个候选、一个问。
- 每问每个注册候选一个独立脚本 `code/<qN>_<scheme>.py`，**禁止候选间复用主逻辑**。
- 所有候选必须在**同一口径**下比较，即 registry protocol 约定：
  - 同一数据划分；
  - 同一折数；
  - 同一随机种子口径；
  - 可比预算。
- 随机算法必须有重复实验或不确定性说明（对齐 fair comparison 规约）。
- **只对 `race.required: true` 的问题**写量化 `scheme-comparison.md`；waived 问题不写量化比较，`summary.md` 的 `chosen_scheme` 仍须精确匹配注册候选名，正文记录选择理由。

## 4. 比较表结构（scheme-comparison.md）

- frontmatter：`winner`、`primary_metric`。
- 赛马表列至少包含：**scheme、可行性/status、主指标列**。
- `results/qN/summary.md` 的 `schemes_compared` 覆盖全部注册候选，`chosen_scheme` 精确匹配注册名。
- 表内应能区分可行与不可行方案，主指标列给出各候选的量化值。

示例骨架：

```markdown
---
winner: q1_baseline
primary_metric: RMSE
---

| scheme | feasible | RMSE (越小越优) | 备注 |
|---|---|---|---|
| q1_baseline | yes | 0.83 | 现行基准 |
| q1_advanced | yes | 0.61 | 机制改进 |
```

## 5. winner 选择顺序

固定序，**不可行方案永远不能成为 winner**：

1. **feasibility（可行性硬门）**——不满足即淘汰；
2. **primary_metric（主指标）**——在可行方案间按主指标排序；
3. **robustness / secondary metrics**——主指标接近时看稳健性与辅助指标；
4. **runtime / interpretability**——最后用运行时间与可解释性并列决策。

## 6. 三方一致性校验

`scheme-comparison.md` 的 **winner** 必须与以下三方完全一致，缺一即 gate 失败：

- 赛马表的 `winner` 字段；和
- `results/qN/summary.md` 的 `chosen_scheme`；和
- registry 中该问注册的候选名之一（`race.schemes` 之一）。

引擎 **S3 gate** 校验赛马表结构 + winner 一致性；**S2 gate**（check_modeling）已保证注册合法。不一致时把 blockers 交回 S3 solver 修复，不允许主循环自行改表。

## 7. S4 / S5 只对 winner 闭环

- **S4 深度证据只对 winner 闭环**（每问六份：diagnostics / ablation / independent-validation / uncertainty / failure-boundaries / semantic-checks）。
- ablation 可对 **winner 与 runner-up** 对比拆解，用于解释 advanced 相对 baseline 的增量贡献。
- **S5 图表只产出 winner 及必要的诊断图**，不画陪跑方案的成套图。
- S6 论文对 required race 引用 `scheme-comparison.md` 写量化择优；waived 问题引用 M1 `waiver_reason` 与 summary 事实写定性选择理由。
- paper-writer 不得在 M3 发明缺失证据；赛马结论必须回溯到 S3 受控比较。

## 8. 快速自检清单

- [ ] 每问 ≥2 候选且含 baseline/advanced，名称互异
- [ ] 所有候选同一数据划分/折数/随机种子/可比预算
- [ ] `code/<qN>_<scheme>.py` 候选间不复用主逻辑
- [ ] required race 写量化 comparison，waived 写 waiver_reason
- [ ] winner 选择走了 feasibility→primary→robustness→runtime 顺序
- [ ] winner 与 summary、registry 三方一致
- [ ] S4 只对 winner 闭环；ablation 允许 winner 与 runner-up 对比
- [ ] S3 gate 通过才进入 S4

## 9. 典型错误与修正

| 错误 | 修正 |
|---|---|
| advanced 只是更复杂无机制改进 | 重写为说明机制/验证/数据结构适配改进 |
| 不同候选用不同随机种子 | 统一到 registry protocol 的同一口径 |
| 让不可行方案当 winner | 淘汰；按固定序重新选 feasible 方案 |
| S4 对全候选都做全套深度证据 | 只对 winner 闭环，ablation 可按需对比 |
| 主循环自行修表对齐一致性 | 交回 S3 solver 修复，不改三方原始产物 |
| waived 问题仍伪造指标比较 | 只写定性选择理由，引用 waiver_reason |
