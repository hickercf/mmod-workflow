# S6 任务简报：论文写作与装配（comp-paper-zh）

派发对象：paper-writer（主循环主导，可并行每问）
输入：results/manifest.md（唯一图表事实源）、每问 summary + 六份深度证据
输出：

- 每问三份独立正文（职责分离，禁止互抄长段落，可见标题点明本问对象）：
  `paper/sections/qN-modeling-process.md`、`qN-results.md`、`qN-model-argumentation.md`
- `paper/abstract.md`：背景/总体框架一段 + 每问独立一段 + 综合边界一段 + 关键词
- `paper/paper-expansion-ledger.md`：每问三职责行，目标页数与 overlap guard
- `paper/evidence-ledger.md`、`paper/argument-map.md`、`paper/question-depth-matrix.md`：证据闭合三件套
- 装配稿：`paper/latex/main.tex`（模板：templates/comp_cumcm/latex/）或 `paper/word/`
  （scripts/word_build.py）；正文至少 25 页（四问数据题 28--35 规划）
- 每张正文图：图下自明标题 + 紧随其后的读图解释段落

完成后运行：`python scripts/workflow_engine.py <workspace> complete S6`
主循环把摘要与装配稿交用户 approve（对应 confirm abstract），再 `checkpoint S6 resolve`。
