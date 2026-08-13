# -*- coding: utf-8 -*-
"""Tests for scripts/workflow_engine.py (Modex-style state machine + gates)."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import workflow_engine as we  # noqa: E402

TEST_ROOT = HERE.parent / "tmp" / "engine-tests"


@pytest.fixture()
def root(tmp_path_factory) -> Path:  # noqa: ANN001
    """Fresh per-test workspace root inside the project tmp dir (sandbox-safe).

    pytest's built-in tmp_path is avoided because the file sandbox denies
    removing directories addressed with the Windows extended-path prefix.
    """
    directory = TEST_ROOT / f"ws-{uuid.uuid4().hex[:12]}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def make_workspace(root: Path, subquestions: int = 1) -> Path:
    for relative in (
        "00-problem", "01-analysis", "code", "data/raw", "data/cleaned",
        "results/q1/figs", "results/q1/tables", "paper/sections",
        "paper/final", "paper/word", "paper/latex",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "00-problem" / "problem.pdf").write_bytes(b"%PDF-1.4 fake")
    rc = we.main([str(root), "init", "--subquestions", str(subquestions)])
    assert rc == 0
    return root


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def s1_artifacts(root: Path, kb_line: bool = True) -> None:
    write(root / "PROBLEM_ANALYSIS.md", "# 审题分析\n\n题型：拟合。\n")
    write(root / "01-analysis" / "analysis.md", "# 分析\n\n问题拆解。\n")
    write(root / "01-analysis" / "data-audit.md",
          "---\nstatus: ready\n---\n\n"
          "| dataset | audit_item | finding | impact | action | verified |\n"
          "|---|---|---|---|---|---|\n"
          "| d1 | 缺失 | 无 | 低 | 保持 | yes |\n")
    if kb_line:
        with (root / "PROBLEM_ANALYSIS.md").open("a", encoding="utf-8") as handle:
            handle.write("\n参考卡：外部 问题模式库-拟合.md，用于题型判定（仅参考思路）\n")


def test_init_creates_eight_steps(root: Path) -> None:
    root = make_workspace(root)
    rc = we.main([str(root), "status", "--json"])
    assert rc == 0
    connection = we.connect(root)
    steps = we.all_steps(connection)
    assert [step["id"] for step in steps] == [f"S{i}" for i in range(1, 9)]
    assert {step["checkpoint"] for step in steps if step["checkpoint"]} == {"approve", "feedback"}
    assert we.get_meta(connection, "subquestions") == 1
    # double init requires --force
    assert we.main([str(root), "init", "--subquestions", "1"]) == 2
    assert we.main([str(root), "init", "--force", "--subquestions", "1"]) == 0


def test_start_complete_checkpoint_flow(root: Path) -> None:
    root = make_workspace(root)
    assert we.main([str(root), "start", "S1"]) == 0
    # gate fails while artifacts are missing; step stays running
    assert we.main([str(root), "complete", "S1"]) == 1
    connection = we.connect(root)
    assert we.step_row(connection, "S1")["status"] == "running"
    s1_artifacts(root)
    assert we.main([str(root), "complete", "S1"]) == 0
    assert we.step_row(connection, "S1")["status"] == "waiting_checkpoint"
    # checkpoint ops require the right state
    assert we.main([str(root), "checkpoint", "S1", "resolve"]) == 0
    assert we.step_row(connection, "S1")["status"] == "completed"
    row = connection.execute(
        "SELECT * FROM checkpoints WHERE step_id = 'S1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "resolved"


def test_complete_without_checkpoint_goes_completed(root: Path) -> None:
    root = make_workspace(root)
    # S4 has no checkpoint; empty gate (only needs questions + evidence files) must fail first
    assert we.main([str(root), "start", "S4"]) == 0
    assert we.main([str(root), "complete", "S4"]) == 1
    for filename in we.EVIDENCE_FILES:
        write(root / "results/q1" / filename, "---\nquestion: q1\nstatus: verified\n---\n\n| check | method | result | evidence | implication | verified |\n|---|---|---|---|---|---|\n| a | b | c | d | e | yes |\n")
    write(root / "results/q1" / "independent-validation.md",
          "---\nquestion: q1\nstatus: verified\nvalidation_kind: holdout\n"
          "independence_basis: 留出数据独立于拟合\nvalidation_artifact: results/q1/tables/holdout.csv\n---\n\n"
          "| check | method | result | evidence | implication | verified |\n|---|---|---|---|---|---|\n"
          "| iv | holdout | 0.9 | results/q1/tables/holdout.csv | 好 | yes |\n")
    write(root / "results/q1" / "tables" / "holdout.csv", "metric,value\nacc,0.9\n")
    assert we.main([str(root), "complete", "S4"]) == 0
    connection = we.connect(root)
    assert we.step_row(connection, "S4")["status"] == "completed"


def test_reject_feedback_sets_rejected(root: Path) -> None:
    root = make_workspace(root)
    s1_artifacts(root)
    we.main([str(root), "start", "S1"])
    we.main([str(root), "complete", "S1"])
    assert we.main([str(root), "checkpoint", "S1", "reject", "--feedback", "方向不对"]) == 0
    connection = we.connect(root)
    assert we.step_row(connection, "S1")["status"] == "rejected"
    row = connection.execute(
        "SELECT * FROM checkpoints WHERE step_id = 'S1' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "rejected"
    assert "方向不对" in json.loads(row["response"])["feedback"]
    # advance points back at the rejected step
    assert we.main([str(root), "advance"]) == 0


def test_advance_ordering_and_resume(root: Path) -> None:
    root = make_workspace(root)
    connection = we.connect(root)
    we.main([str(root), "start", "S3"])
    assert we.main([str(root), "advance"]) == 0  # S1 pending is first; S3 blocked
    # simulate crash while S3 running after S1/S2 completed via backfill
    we.main([str(root), "backfill", "--steps", "S1,S2"])
    we.main([str(root), "start", "S3"])
    assert we.main([str(root), "resume"]) == 0
    assert we.step_row(connection, "S3")["status"] == "pending"
    assert we.main([str(root), "advance"]) == 0


def test_backfill_and_sync_state(root: Path) -> None:
    root = make_workspace(root)
    rc = we.main([str(root), "backfill", "--steps", "S1,S2,S3", "--confirmed", "modeling"])
    assert rc == 0
    connection = we.connect(root)
    assert we.get_meta(connection, "confirmations") == {"modeling": True}
    assert all(
        we.step_row(connection, step_id)["status"] == "completed"
        for step_id in ("S1", "S2", "S3")
    )
    rc = we.main([str(root), "sync-state", "--check"])
    assert rc == 1  # no workflow-state.json yet
    assert we.main([str(root), "sync-state"]) == 0
    state = json.loads((root / "workflow-state.json").read_text(encoding="utf-8"))
    assert state["stages"]["modeling"]["status"] == "completed"
    assert state["stages"]["code"]["status"] == "pending"
    assert state["current_stage"] == "code"
    assert state["confirmations"]["modeling"]["confirmed"] is True
    assert we.main([str(root), "sync-state", "--check"]) == 0


def test_kb_registration_gate(root: Path) -> None:
    """S1 gate requires a non-placeholder knowledge-base registration line."""
    make_workspace(root)
    # without registration -> gate fails with an explicit blocker
    s1_artifacts(root, kb_line=False)
    we.main([str(root), "start", "S1"])
    assert we.main([str(root), "complete", "S1"]) == 1
    connection = we.connect(root)
    assert we.step_row(connection, "S1")["status"] == "running"
    assert "知识库" in (we.step_row(connection, "S1")["error_message"] or "")
    # with registration -> passes
    s1_artifacts(root, kb_line=True)
    assert we.main([str(root), "complete", "S1"]) == 0
    assert we.step_row(connection, "S1")["status"] == "waiting_checkpoint"
    # an explicit "not used" reason also passes
    write(root / "PROBLEM_ANALYSIS.md", "# 审题分析\n\n题型：拟合。\n\n参考卡：未使用（以题面与数据实测为准）\n")
    assert we.main([str(root), "gate", "S1"]) == 0
    # unit-level: S2 registration markers and placeholder rejection
    assert we.kb_registration_present(root / "PROBLEM_ANALYSIS.md") is True
    write(root / "PROBLEM_ANALYSIS.md", "# 审题分析\n\n题型：拟合。\n\n参考卡：待补\n")
    assert we.kb_registration_present(root / "PROBLEM_ANALYSIS.md") is False
    blockers: list[str] = []
    we.kb_registration_blockers(root, ("MODELING_REPORT.md", "01-analysis/model-selection.md"), "S2", blockers)
    assert blockers and "S2" in blockers[0]


def test_gate_s3_race_consistency(root: Path) -> None:
    root = make_workspace(root)
    registry = {
        "version": 1,
        "questions": {
            "q1": {
                "candidates": [
                    {"name": "baseline_a", "kind": "baseline"},
                    {"name": "advanced_b", "kind": "advanced"},
                ],
                "race": {
                    "required": True,
                    "schemes": ["baseline_a", "advanced_b"],
                    "feasibility_checks": ["可运行"],
                    "primary_metric": "cv_rmse",
                    "direction": "min",
                    "protocol": "同折 5 折",
                },
            }
        },
    }
    write(root / "01-analysis" / "scheme-registry.json", json.dumps(registry, ensure_ascii=False))
    write(root / "code" / "q1_baseline_a.py", "print('ok')\n")
    write(root / "code" / "q1_advanced_b.py", "print('ok')\n")
    write(root / "results/q1" / "summary.md",
          "---\nquestion: q1\nstatus: solved\nchosen_scheme: baseline_a\n"
          "schemes_compared: [\"baseline_a\", \"advanced_b\"]\nrobustness: 聚类稳健 SE\n---\n\n# 摘要\n")
    write(root / "results/q1" / "scheme-comparison.md",
          "---\nwinner: baseline_a\nprimary_metric: cv_rmse\n---\n\n"
          "| scheme | feasibility | cv_rmse |\n|---|---|---|\n"
          "| baseline_a | pass | 0.032 |\n| advanced_b | pass | 0.040 |\n")
    assert we.main([str(root), "start", "S3"]) == 0
    assert we.main([str(root), "complete", "S3"]) == 0
    # break the winner consistency -> the read-only gate must fail
    write(root / "results/q1" / "scheme-comparison.md",
          "---\nwinner: advanced_b\nprimary_metric: cv_rmse\n---\n\n"
          "| scheme | feasibility | cv_rmse |\n|---|---|---|\n"
          "| baseline_a | pass | 0.032 |\n| advanced_b | pass | 0.040 |\n")
    assert we.main([str(root), "gate", "S3"]) == 1
