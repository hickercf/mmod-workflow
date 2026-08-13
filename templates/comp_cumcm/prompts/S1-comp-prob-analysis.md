# S1 任务简报：审题与数据分析（comp-prob-analysis）

派发对象：problem-analyzer（子 Agent）
输入：`00-problem/` 题面与附件、`data/raw/` 实际数据
输出（必须真实落盘，禁止占位）：

- `PROBLEM_ANALYSIS.md`：题型判定、每问任务重述、数据盘点结论、风险清单
- `01-analysis/analysis.md`：P1 审题、数据盘点和问题拆解
- `01-analysis/data-audit.md`：表头精确为 dataset/audit_item/finding/impact/action/verified，至少 5 行，status: ready
- `01-analysis/research-plan.md`：每问至少一行，status: ready
- `01-analysis/claim-evidence-matrix.md`：每问至少 2 条可证伪主张，status: ready

知识库：先读外部 `D:\数学建模知识库\MathModel-Agent-KB\00_Index\MOC-总索引.md` 与
`模型选择决策规则.md`，再读内部 `knowledge-base/INDEX.md`；按需单张读卡并登记使用。
登记格式（gate S1 强制，缺失阻断）：在 `PROBLEM_ANALYSIS.md` 或 `01-analysis/analysis.md`
写一行非占位登记，如 `参考卡：外部 问题模式库-拟合.md，用于题型判定（仅参考思路）`；
未引用时如实写明理由，如 `参考卡：未使用（以题面与数据实测为准）`。
注意：卡片只提供建模思路与方法启发，禁止把卡片中的数值/阈值/结论写入本题工件。
完成后运行：`python scripts/workflow_engine.py <workspace> complete S1`
主循环 gate S1 通过后展示 `PROBLEM_ANALYSIS.md` 摘要，请用户 approve 后
`checkpoint S1 resolve`。
