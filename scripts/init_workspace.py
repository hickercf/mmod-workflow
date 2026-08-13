# -*- coding: utf-8 -*-
"""init_workspace.py — 一键生成题目工作区骨架

用法：python scripts/init_workspace.py 2020A-furnace --title "炉温曲线" --subquestions 4
在 workspace/ 下创建标准目录结构与 progress.md / README.md。
目录名强制 ASCII（中文路径会导致 LaTeX/部分库崩溃）。
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.join(PROJECT_ROOT, "workspace")

SUBDIRS = [
    "00-problem",
    "01-analysis",
    "data/raw",
    "data/cleaned",
    "code",
    "results",
    "paper/word",
    "paper/latex",
    "paper/final",
    "paper/sections",
]

PROGRESS_MD = """# 进度记录（全队唯一事实源）

> 主循环每完成一个关卡追加一条：时间 / 关卡 / 产出 / 风险与待办

| 时间 | 关卡 | 产出 | 风险/待办 |
|---|---|---|---|
"""

MANIFEST_MD = """# 结果清单（paper-writer 的唯一输入契约）

> 每张图表一行：文件（相对题目根）× 生成脚本 × 一句话结论

| 图表 | 文件 | 生成脚本 | 一句话结论 |
|---|---|---|---|
"""

M1_TEMPLATES = {
    "data-audit.md": """---
status: draft
---
# 数据审计

| dataset | audit_item | finding | impact | action | verified |
|---|---|---|---|---|---|
""",
    "research-plan.md": """---
status: draft
---
# 研究计划

| question | research_objective | core_output | decision_rule | main_risk | fallback | verified |
|---|---|---|---|---|---|---|
""",
    "claim-evidence-matrix.md": """---
status: draft
---
# 主张与证据规划

| question | claim_id | claim | evidence_needed | independent_check | falsification_test | uncertainty | status |
|---|---|---|---|---|---|---|---|
""",
    "derivation-notes.md": """---
status: draft
---
# 推导准备

| question | variables | assumptions | objective_or_relation | constraints | direction_unit_checks | failure_condition | verified |
|---|---|---|---|---|---|---|---|
""",
    "experiment-matrix.md": """---
status: draft
---
# 实验矩阵

| question | experiment | purpose | protocol | metric_or_check | expected_artifact | verified |
|---|---|---|---|---|---|---|
""",
}

M2_EVIDENCE_TEMPLATE = """---
question: q{question}
status: draft
---
# {title}

| check | method | result | evidence | implication | verified |
|---|---|---|---|---|---|
"""

INDEPENDENT_VALIDATION_TEMPLATE = """---
question: q{question}
status: draft
validation_kind:
independence_basis:
validation_artifact:
---
# {title}

| check | method | result | evidence | implication | verified |
|---|---|---|---|---|---|
"""

M2_EVIDENCE_TITLES = {
    "diagnostics.md": "模型诊断",
    "ablation.md": "消融与组件贡献",
    "independent-validation.md": "独立验证",
    "uncertainty.md": "不确定性分析",
    "failure-boundaries.md": "失效边界",
    "semantic-checks.md": "公式语义、方向与单位检查",
}


def m2_evidence_template(question, filename, title):
    template = (
        INDEPENDENT_VALIDATION_TEMPLATE
        if filename == "independent-validation.md"
        else M2_EVIDENCE_TEMPLATE
    )
    return template.format(question=question, title=title)

PAPER_EXPANSION_TEMPLATE = """---
status: draft
---
# 正文证据与篇幅规划

| question | section_type | purpose | unique_content | source_artifacts | target_pages | overlap_guard | verified |
|---|---|---|---|---|---|---|---|
"""

QUESTION_DEPTH_TEMPLATE = """---
status: draft
---
# 分问题深度矩阵

| question | modeling_process | results_interpretation | model_argumentation | independent_validation | uncertainty | failure_boundary | verified |
|---|---|---|---|---|---|---|---|
"""

REVISION_LOG_TEMPLATE = """---
status: open
---
# 两轮审查闭环

| round | reviewer | findings | changes | recheck | status |
|---|---|---|---|---|---|
"""

PAPER_SECTION_TEMPLATES = {
    "01-problem-analysis.md": """# 问题背景与重述

## 问题背景

## 任务重述

# 问题分析

## 子问题的数学结构

## 数据结构与质量审计

## 总体研究路线
""",
    "02-assumptions-symbols.md": """# 模型假设

## 公共模型假设

## 数据预处理假设与原则

# 符号说明

## 统一符号

## 指标口径
""",
    "03-modeling-and-solution.md": """# 模型的建立与求解

本章按问题顺序装配每问的建模过程、结果解释和模型论证三份独立正文。
""",
    "07-model-evaluation.md": """# 模型评价与应用边界

## 跨问决策链与评价口径

## 方案执行规则

## 适用边界与补充数据
""",
    "08-conclusion.md": """# 结论
""",
}


def question_section_template(question, section_type):
    if section_type == "modeling-process":
        headings = (
            "任务转化：本问对象与数学目标",
            "机理与假设：本问作用链与简化条件",
            "变量与符号：本问新增量与单位",
            "模型建立与推导：本问关系式、目标与约束",
            "求解流程：本问算法、参数与复现入口",
        )
        lead = (
            f"## 问题{question}：请改为本问模型或决策对象\n\n"
            "### 请改为本问具体模型的建立与求解"
        )
    elif section_type == "results":
        headings = (
            "核心结果：本问关键输出与图表",
            "结果解释：本问物理、业务或决策含义",
        )
        lead = "### 请改为本问具体结果对象与解释"
    else:
        headings = (
            "方案选择：本问候选方案与择优依据",
            "模型诊断：本问结构与拟合检查",
            "独立验证：本问第二证据链",
            "不确定性：本问误差与敏感性来源",
            "失效边界：本问适用条件与失败场景",
        )
        lead = "### 请改为本问具体模型的论证与边界"
    body = "\n\n".join(f"**{heading}**\n" for heading in headings)
    note = "<!-- 写作时将冒号后的占位语改为本问的模型、变量、引理或决策对象。 -->"
    return f"{lead}\n\n{note}\n\n{body}\n"


def initial_workflow_state(name, subquestions):
    """Return the persisted state used by workflow_gate.py.

    Keep this data deliberately small and JSON-only: the workflow gate must be
    usable on a clean Windows Python installation without extra dependencies.
    """
    return {
        "schema_version": 1,
        "quality_contract": "deep-research-v2",
        "project": name,
        "subquestions": subquestions,
        "current_stage": "modeling",
        "confirmations": {
            "modeling": {"confirmed": False, "confirmed_at": None},
            "abstract": {"confirmed": False, "confirmed_at": None},
            "paper": {"confirmed": False, "confirmed_at": None},
        },
        "stages": {
            "modeling": {"status": "pending", "blockers": []},
            "code": {"status": "pending", "blockers": []},
            "paper": {"status": "pending", "blockers": []},
        },
        "history": [],
    }


def main():
    p = argparse.ArgumentParser(description="生成题目工作区骨架")
    p.add_argument("name", help="ASCII 短名，如 2020A-furnace")
    p.add_argument("--title", default="", help="中文题名（写入内部 README）")
    p.add_argument("--subquestions", type=int, default=0,
                   help="已知子问题数，自动建 results/q{n}/ 子目录")
    args = p.parse_args()

    if not args.name.isascii():
        sys.exit(f"[X] 工作区名必须是 ASCII（当前: {args.name}），"
                 f"例如 2020A-furnace。中文题注请用 --title。")
    if not all(c.isalnum() or c in "-_" for c in args.name):
        sys.exit("[X] 工作区名只允许字母、数字、- 和 _")

    root = os.path.join(WORKSPACE, args.name)
    if os.path.exists(root):
        sys.exit(f"[X] 已存在: {root}")

    for sub in SUBDIRS:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    for filename, content in PAPER_SECTION_TEMPLATES.items():
        with open(
            os.path.join(root, "paper", "sections", filename),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(content)
    for i in range(1, args.subquestions + 1):
        os.makedirs(os.path.join(root, f"results/q{i}/figs"), exist_ok=True)
        os.makedirs(os.path.join(root, f"results/q{i}/tables"), exist_ok=True)
        for filename, title in M2_EVIDENCE_TITLES.items():
            with open(os.path.join(root, f"results/q{i}/{filename}"), "w", encoding="utf-8") as f:
                f.write(m2_evidence_template(i, filename, title))
        for section_type in ("modeling-process", "results", "model-argumentation"):
            with open(
                os.path.join(root, f"paper/sections/q{i}-{section_type}.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(question_section_template(i, section_type))

    for filename, content in M1_TEMPLATES.items():
        with open(os.path.join(root, "01-analysis", filename), "w", encoding="utf-8") as f:
            f.write(content)
    with open(os.path.join(root, "paper", "paper-expansion-ledger.md"), "w", encoding="utf-8") as f:
        f.write(PAPER_EXPANSION_TEMPLATE)
    with open(os.path.join(root, "paper", "question-depth-matrix.md"), "w", encoding="utf-8") as f:
        f.write(QUESTION_DEPTH_TEMPLATE)
    with open(os.path.join(root, "paper", "revision-log.md"), "w", encoding="utf-8") as f:
        f.write(REVISION_LOG_TEMPLATE)

    with open(os.path.join(root, "progress.md"), "w", encoding="utf-8") as f:
        f.write(PROGRESS_MD)
    with open(os.path.join(root, "results", "manifest.md"), "w", encoding="utf-8") as f:
        f.write(MANIFEST_MD)
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"# {args.name}\n\n题名：{args.title or '（待填）'}\n\n"
                f"题面与附件放入 `00-problem/`，原始数据放入 `data/raw/`（只读不改）。\n")
    with open(os.path.join(root, "workflow-state.json"), "w", encoding="utf-8") as f:
        json.dump(initial_workflow_state(args.name, args.subquestions), f,
                  ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[OK] 工作区已生成: {root}")
    print("     下一步：把题面附件放入 00-problem/，然后让 Claude 启动审题（problem-analyzer）。")


if __name__ == "__main__":
    main()
