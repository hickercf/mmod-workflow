# S8 任务简报：合规检查与最终包编译（comp-compile-zh）

派发对象：compliance-check + 编译工具
输入：S7 通过的论文包
流程：

1. 编译最终包：LaTeX（scripts/build_latex.py / build_latex.bat）或 Word
   （scripts/word_build.py），输出 `paper/final/` 下 PDF 或 DOCX
2. `paper/final/compliance-report.md`：frontmatter
   status: pass / body_pages（>=25）/ appendix_pages / page_rule_checked / body_page_target
3. 更新 `paper/evidence-ledger.md` 的 reviewed_package 指向真实最终包
4. 最终数字抽查：正文数字与 results summary 一致（数据真实性红线）

完成后运行：`python scripts/workflow_engine.py <workspace> complete S8`
gate S8 = 合规 pass + 最终包有效 + check paper 全绿。
主循环把最终包交用户 approve（对应 confirm paper），`checkpoint S8 resolve` 后
`python scripts/workflow_engine.py <workspace> sync-state`，工作流完成。
