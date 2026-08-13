# comp_cumcm LaTeX 模板

- `cumcmthesis.cls`：开源 CUMCM 模板 v2.6（2017/09/16），出处为
  Modex-MH-Agent 安装包内置竞赛模板（`resources/app/skills/comp-paper-zh/templates/cumcm/`），
  按社区许可使用并在此注明出处；需 XeLaTeX 与 ctex（Windows 系统字体宋体/黑体即可）。
- `main.tex`：主骨架，遵循本仓库版式合同（七章主结构、四问为第五章二级标题、
  一级标题 16pt、西文 Times New Roman、图下标题+读图段落、摘要分段结构）。

## 装配流程（S6/S8 使用）

1. `Copy-Item templates/comp_cumcm/latex/* workspace/<题>/paper/latex/ -Recurse`
2. 把 `paper/sections/*.md` 转换为同名 `.tex` 放入 `paper/latex/chapters/`
   （推荐 pandoc：`pandoc -f markdown -t latex`；公式与表格再人工校核）
3. 填写 `main.tex` 中的 TODO：题名、队号、摘要各段、关键词
4. 编译：`python scripts/build_latex.py paper/latex/main.tex`
5. 页数检查：正文 >=25 页（四问数据题 28--35 规划），合规报告登记实测页数

## 承诺书/编号页

默认 `\documentclass[withoutpreface]` 去掉承诺书页；最终提交按当年 CUMCM 通知
将承诺书页加入（官方每年提供单独模板，不要复用旧版）。
