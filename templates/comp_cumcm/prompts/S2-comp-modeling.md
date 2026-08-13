# S2 任务简报：建模方案与赛马注册（comp-modeling）

派发对象：model-advisor（子 Agent）
输入：S1 全部产物、知识库检索结果
输出（必须真实落盘，禁止占位）：

- `01-analysis/model-selection.md`：人类可读方案说明，frontmatter `frozen: true`
- `01-analysis/scheme-registry.json`：`version: 1`；每问 >=2 候选且含 baseline/advanced；
  required race 冻结 schemes/feasibility_checks/primary_metric/direction/protocol；
  waived 必须有 waiver_reason（机器验证规则见 scripts/workflow_gate.py）
- `01-analysis/derivation-notes.md`：每问变量/假设/目标/约束/方向单位/失败条件，status: ready
- `01-analysis/experiment-matrix.md`：每问至少 4 项实验（方案比较/诊断/独立验证/不确定性或失效边界），status: ready
- `MODELING_REPORT.md`：赛马注册说明 + 知识库卡使用登记
  （gate S2 强制：`MODELING_REPORT.md` 或 `model-selection.md` 需含非占位登记行，
  如 `知识库依据（按需读取）：[[线性回归模型]]、[[分类性能评估]]（外部库卡片，仅参考思路）`；
  未引用时写明理由。卡片只启发建模思路，数值/阈值/结论必须来自 workspace 脚本产物）

完成后运行：`python scripts/workflow_engine.py <workspace> complete S2`
主循环 gate S2（即 check modeling）通过后，把 MODELING_REPORT.md 与赛马表交给用户
feedback；采纳意见后 `checkpoint S2 resolve`；若用户要求修改，`checkpoint S2 reject --feedback ...`
并重跑本步。
