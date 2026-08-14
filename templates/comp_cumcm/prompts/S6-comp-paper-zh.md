# S6 任务简报：论文写作与装配（comp-paper-zh）

派发对象：paper-writer（主循环主导，可并行每问）
输入：results/manifest.md（唯一图表事实源）、每问 summary + 六份深度证据
写作指导（必读）：

- 内置规范：`.claude/skills/comp-workflow/references/writing-guidelines.md`（获奖论文写作硬规则）
- 技能库（如有）：`knowledge-base/distillation/writing-skills.md`（56 条写作技能，
  摘要密度/结构/图表/验证/失分点；只作写法启发，数值仍以 workspace 脚本产物为准）
- 反例教训：摘要单位笔误（cm/s vs m/s）、写了硬约束没满足、图无编号、
  分析段与求解段逐句复写——一律禁止

硬规则（写作与评审共同核对）：

1. 摘要每问独立成段，段内"模型名+做了什么+带单位核心值"三点齐备；数值密度 5–20 个
2. **核心值单位三重核对**：正文 ↔ 摘要 ↔ 题干单位（如 m/s、周、kg/m²）完全一致
3. 每问至少一张**结果汇总表**；逐条结果外置附录/支撑文件
4. 模型论证节必须含**选型论证**（为何不用替代模型/为何用此模型），禁止模型堆砌
5. 带硬约束的优化问：逐问报达标值 + 约束核验表
6. 问题分析段只写思路，与求解段禁止逐句复写
7. 每张图：图下自明标题 + 紧随其后的读图解释段落（既有契约）

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
