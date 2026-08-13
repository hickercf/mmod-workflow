# -*- coding: utf-8 -*-
"""Modex-style workflow engine for the unified math-modeling workflow.

The engine is a SQLite state machine (Modex-style control plane) that drives the
comp_cumcm 8-step template and reuses the existing three-stage gates from
``workflow_gate.py`` as automatic quality gates.

Usage:
    python scripts/workflow_engine.py <workspace> init --template comp_cumcm [--subquestions N] [--title X]
    python scripts/workflow_engine.py <workspace> status [--json]
    python scripts/workflow_engine.py <workspace> start <S1..S8>
    python scripts/workflow_engine.py <workspace> complete <S1..S8> [--note ...]
    python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> resolve [--response <json>]
    python scripts/workflow_engine.py <workspace> checkpoint <S1..S8> reject --feedback <text>
    python scripts/workflow_engine.py <workspace> gate <S1..S8>
    python scripts/workflow_engine.py <workspace> advance
    python scripts/workflow_engine.py <workspace> resume
    python scripts/workflow_engine.py <workspace> backfill [--steps S1,S2,...] [--confirmed modeling,abstract,paper]
    python scripts/workflow_engine.py <workspace> sync-state [--check]
    python scripts/workflow_engine.py <workspace> report

``status``, ``gate``, ``advance``, ``report`` and ``sync-state --check`` are
read-only.  All writes are logged to ``<workspace>/.engine/workflow.db`` and
``progress.md``.  ``sync-state`` keeps ``workflow-state.json`` aligned with the
engine so ``workflow_gate.py`` remains the three-stage compatibility view.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent
sys.path.insert(0, str(HERE))
import workflow_gate as wg  # noqa: E402  (reuse three-stage gates + helpers)

ENGINE_DIR = ".engine"
DB_FILE = "workflow.db"
TEMPLATE_DIR = ROOT_DIR / "templates" / "comp_cumcm"
STEPS_FILE = TEMPLATE_DIR / "steps.json"

CHECKPOINT_KINDS = ("approve", "feedback")
STEP_STATUSES = ("pending", "running", "waiting_checkpoint", "rejected", "completed")
STAGE_MAP = {"modeling": ("S1", "S2"), "code": ("S3", "S4", "S5"), "paper": ("S6", "S7", "S8")}
CONFIRMATION_MAP = {"modeling": "modeling", "abstract": "abstract", "paper": "paper"}
EVIDENCE_FILES = (
    "diagnostics.md",
    "ablation.md",
    "independent-validation.md",
    "uncertainty.md",
    "failure-boundaries.md",
    "semantic-checks.md",
)


class EngineError(Exception):
    """An actionable error caused by a bad command or workspace state."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def local_now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- DB helpers

def db_path(root: Path) -> Path:
    return root / ENGINE_DIR / DB_FILE


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    if not path.is_file():
        raise EngineError(f"Missing engine DB {path}. Run init first.")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS steps (
            id TEXT PRIMARY KEY,
            template TEXT NOT NULL,
            skill TEXT NOT NULL,
            display_name TEXT NOT NULL,
            step_order INTEGER NOT NULL,
            checkpoint TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            step_id TEXT NOT NULL,
            ctype TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            data TEXT DEFAULT '{}',
            response TEXT DEFAULT '{}',
            created_at TEXT,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            step_id TEXT,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            created_at TEXT
        );
        """
    )
    connection.commit()


def log(connection: sqlite3.Connection, step_id: str | None, level: str, message: str) -> None:
    connection.execute(
        "INSERT INTO logs (step_id, level, message, created_at) VALUES (?, ?, ?, ?)",
        (step_id, level, message, utc_now()),
    )
    connection.commit()


def get_meta(connection: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def set_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    connection.commit()


def step_row(connection: sqlite3.Connection, step_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()


def all_steps(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM steps ORDER BY step_order").fetchall()


def require_step(connection: sqlite3.Connection, step_id: str) -> sqlite3.Row:
    row = step_row(connection, step_id)
    if row is None:
        raise EngineError(f"Unknown step {step_id}; expected one of S1..S8")
    return row


def set_step_status(
    connection: sqlite3.Connection,
    step_id: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    connection.execute(
        "UPDATE steps SET status = ?, error_message = ? WHERE id = ?",
        (status, error_message, step_id),
    )
    connection.commit()


def step_state_for_gate(root: Path) -> dict[str, Any]:
    """Reuse workflow_gate's state view (managed workspaces) or transient."""
    state_path = root / wg.STATE_FILE
    if state_path.is_file():
        try:
            return wg.load_state(root)
        except wg.GateError:
            return wg.transient_state(root)
    return wg.transient_state(root)


# ---------------------------------------------------------------- template

def load_steps_template() -> list[dict[str, Any]]:
    if not STEPS_FILE.is_file():
        raise EngineError(f"Missing template {STEPS_FILE}")
    try:
        with STEPS_FILE.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineError(f"Cannot read template {STEPS_FILE}: {exc}") from exc
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise EngineError(f"Template {STEPS_FILE} must define a non-empty steps list")
    for step in steps:
        if not step.get("id") or not step.get("skill"):
            raise EngineError(f"Template step missing id/skill: {step}")
        checkpoint = step.get("checkpoint", "")
        if checkpoint and checkpoint not in CHECKPOINT_KINDS:
            raise EngineError(f"Template step {step['id']} has invalid checkpoint {checkpoint}")
    return steps


# ---------------------------------------------------------------- quality gates

KB_MARKERS = ("参考卡", "知识库依据", "知识库参考", "卡引用", "参考知识库", "knowledge-base")


def kb_registration_present(path: Path) -> bool:
    """A non-placeholder knowledge-base registration line (used or not used)."""
    if not wg.nonempty_file(path):
        return False
    for line in wg.read_text(path).splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in KB_MARKERS):
            if not wg.placeholder_value(stripped):
                return True
    return False


def kb_registration_blockers(
    root: Path, candidates: tuple[str, ...], label: str, blockers: list[str]
) -> None:
    """Require a knowledge-base registration in one of the candidate files.

    The gate enforces the *consideration and traceability* of the knowledge
    base, not its content: a line like ``参考卡：<卡名>，用于 <决策>`` or
    ``知识库依据：…`` passes; an explicit ``参考卡：未使用（理由）`` also
    passes. Cards only inform modeling ideas — numbers must still come from
    workspace script artifacts.
    """
    if not any(kb_registration_present(root / relative) for relative in candidates):
        blockers.append(
            f"{label}: 未登记知识库参考——在 {' 或 '.join(candidates)} 中写一行非占位登记，"
            "如「参考卡：<外部/内部卡名>，用于 <决策>（仅参考思路）」；未引用时写明理由"
        )


def gate_s1(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    for relative in (
        "PROBLEM_ANALYSIS.md",
        "01-analysis/analysis.md",
        "01-analysis/data-audit.md",
    ):
        path = root / relative
        if not wg.nonempty_file(path):
            blockers.append(f"S1: missing non-empty {relative}")
    kb_registration_blockers(
        root, ("PROBLEM_ANALYSIS.md", "01-analysis/analysis.md"), "S1", blockers
    )
    return blockers


def gate_s2(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers = wg.check_modeling(root, step_state_for_gate(root))
    kb_registration_blockers(
        root, ("MODELING_REPORT.md", "01-analysis/model-selection.md"), "S2", blockers
    )
    return blockers


def gate_s3(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    state = step_state_for_gate(root)
    registry, registry_blockers = wg.load_scheme_registry(root)
    blockers.extend(registry_blockers)
    questions = wg.expected_questions(root, state, registry)
    if not questions:
        blockers.append("S3: no expected questions found")
    code_dir = root / "code"
    for question in questions:
        label = f"q{question}"
        qdir = wg.question_path(root, question)
        summary = qdir / "summary.md"
        if not wg.nonempty_file(summary):
            blockers.append(f"S3 {label}: missing non-empty {label}/summary.md")
        elif (wg.frontmatter_value(summary, "status") or "").strip().lower() != "solved":
            blockers.append(f"S3 {label}: summary must record status: solved")
        if wg.nonempty_file(summary) and not (
            wg.frontmatter_value(summary, "chosen_scheme") or ""
        ).strip():
            blockers.append(f"S3 {label}: summary must record nonempty chosen_scheme")
        scripts = [
            path for path in code_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in wg.PRODUCER_SCRIPT_SUFFIXES
            and wg.producer_script_matches_question(root, path, question)
        ] if code_dir.is_dir() else []
        if not scripts:
            blockers.append(f"S3 {label}: missing non-empty code script matching {label}")
        if registry is not None and isinstance(registry.get("questions"), dict):
            spec = registry["questions"].get(label)
            if isinstance(spec, dict):
                blockers.extend(wg.scheme_race_blockers(root, question, spec))
    return blockers


def gate_s4(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    state = step_state_for_gate(root)
    registry, _ = wg.load_scheme_registry(root)
    questions = wg.expected_questions(root, state, registry)
    if not questions:
        blockers.append("S4: no expected questions found")
    for question in questions:
        label = f"q{question}"
        qdir = wg.question_path(root, question)
        for filename in EVIDENCE_FILES:
            path = qdir / filename
            if not wg.nonempty_file(path):
                blockers.append(f"S4 {label}: missing non-empty {label}/{filename}")
        iv = qdir / "independent-validation.md"
        if wg.nonempty_file(iv):
            kind = (wg.frontmatter_value(iv, "validation_kind") or "").strip().lower()
            if kind not in wg.INDEPENDENT_VALIDATION_KINDS:
                blockers.append(
                    f"S4 {label}: independent-validation validation_kind must be one of "
                    + ", ".join(sorted(wg.INDEPENDENT_VALIDATION_KINDS))
                )
            basis = (wg.frontmatter_value(iv, "independence_basis") or "").strip()
            artifact = wg.frontmatter_value(iv, "validation_artifact") or ""
            if not basis:
                blockers.append(f"S4 {label}: independent-validation needs independence_basis")
            resolved = wg.resolve_workspace_path(root, artifact) if artifact else None
            if resolved is None or not wg.nonempty_file(resolved):
                blockers.append(
                    f"S4 {label}: independent-validation validation_artifact must point to an existing file"
                )
    return blockers


def gate_s5(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    manifest = root / "results" / "manifest.md"
    if not wg.nonempty_file(manifest):
        blockers.append("S5: missing non-empty results/manifest.md")
    state = step_state_for_gate(root)
    registry, _ = wg.load_scheme_registry(root)
    questions = wg.expected_questions(root, state, registry)
    for question in questions:
        qdir = wg.question_path(root, question)
        pairs = wg.valid_figure_pairs(qdir)
        if not pairs:
            blockers.append(f"S5 q{question}: need at least one PNG/PDF figure pair in figs/")
    check = subprocess.run(
        [sys.executable, str(HERE / "merge_manifest.py"), str(root), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check.returncode != 0:
        blockers.append("S5: merge_manifest --check failed (manifest stale or artifacts missing)")
    return blockers


def gate_s6(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    state = step_state_for_gate(root)
    registry, _ = wg.load_scheme_registry(root)
    questions = wg.expected_questions(root, state, registry)
    sections = root / "paper" / "sections"
    if not sections.is_dir():
        blockers.append("S6: missing paper/sections/ directory")
    for question in questions:
        for suffix in ("modeling-process", "results", "model-argumentation"):
            path = sections / f"q{question}-{suffix}.md"
            if not wg.nonempty_file(path):
                blockers.append(f"S6 q{question}: missing non-empty sections/q{question}-{suffix}.md")
    for relative in ("paper/abstract.md",):
        if not wg.nonempty_file(root / relative):
            blockers.append(f"S6: missing non-empty {relative}")
    if not assembled_draft_exists(root):
        blockers.append("S6: missing assembled draft (valid .tex/.pdf under paper/latex or "
                        ".docx/.pdf under paper/word|paper/final)")
    for relative in (
        "paper/evidence-ledger.md",
        "paper/argument-map.md",
        "paper/question-depth-matrix.md",
    ):
        if not wg.nonempty_file(root / relative):
            blockers.append(f"S6: missing non-empty {relative}")
    return blockers


def assembled_draft_exists(root: Path) -> bool:
    for relative in ("paper/latex", "paper/word", "paper/final"):
        directory = root / relative
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() == ".pdf" and wg.valid_pdf(path):
                return True
            if path.suffix.lower() == ".docx" and wg.valid_docx(path):
                return True
            if path.suffix.lower() == ".tex" and wg.valid_tex(path):
                return True
    return False


def gate_s7(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    review = root / "paper" / "review-report.md"
    if not wg.nonempty_file(review):
        blockers.append("S7: missing non-empty paper/review-report.md")
    else:
        try:
            round_number = int(wg.frontmatter_value(review, "round") or 0)
        except ValueError:
            round_number = 0
        if round_number < 2:
            blockers.append("S7: review-report round must be >= 2")
        if (wg.frontmatter_value(review, "p0_count") or "").strip() != "0":
            blockers.append("S7: review-report p0_count must be 0")
        if (wg.frontmatter_value(review, "verdict") or "").strip().lower() != "pass":
            blockers.append("S7: review-report verdict must be pass")
    revision = root / "paper" / "revision-log.md"
    if not wg.nonempty_file(revision):
        blockers.append("S7: missing non-empty paper/revision-log.md")
    elif (wg.frontmatter_value(revision, "status") or "").strip().lower() != "closed":
        blockers.append("S7: revision-log status must be closed")
    depth = root / "paper" / "depth-audit.md"
    if not wg.nonempty_file(depth):
        blockers.append("S7: missing non-empty paper/depth-audit.md")
    for seat in ("A", "B", "C"):
        if not wg.nonempty_file(root / "paper" / f"judge-scorecard-{seat}.md"):
            blockers.append(f"S7: missing non-empty paper/judge-scorecard-{seat}.md")
    panel = root / "paper" / "judge-panel.md"
    if not wg.nonempty_file(panel):
        blockers.append("S7: missing non-empty paper/judge-panel.md")
    else:
        if (wg.frontmatter_value(panel, "verdict") or "").strip().lower() != "pass":
            blockers.append("S7: judge-panel verdict must be pass")
        conflicts = wg.frontmatter_value(panel, "conflicts")
        if conflicts is not None and conflicts.strip() != "0":
            blockers.append("S7: judge-panel conflicts must be 0")
    return blockers


def gate_s8(root: Path, connection: sqlite3.Connection) -> list[str]:
    blockers: list[str] = []
    compliance = root / "paper" / "final" / "compliance-report.md"
    if not wg.nonempty_file(compliance):
        blockers.append("S8: missing non-empty paper/final/compliance-report.md")
    else:
        if (wg.frontmatter_value(compliance, "status") or "").strip().lower() != "pass":
            blockers.append("S8: compliance-report status must be pass")
        try:
            pages = int(wg.frontmatter_value(compliance, "body_pages") or 0)
        except ValueError:
            pages = 0
        if pages < 25:
            blockers.append("S8: compliance body_pages must be >= 25")
    final_dir = root / "paper" / "final"
    packages = [
        path for path in final_dir.iterdir()
        if path.is_file() and (
            (path.suffix.lower() == ".pdf" and wg.valid_pdf(path))
            or (path.suffix.lower() == ".docx" and wg.valid_docx(path))
        )
    ] if final_dir.is_dir() else []
    if not packages:
        blockers.append("S8: missing valid final PDF/DOCX in paper/final/")
    blockers.extend(wg.check_paper(root, step_state_for_gate(root)))
    return blockers


GATES = {
    "S1": gate_s1,
    "S2": gate_s2,
    "S3": gate_s3,
    "S4": gate_s4,
    "S5": gate_s5,
    "S6": gate_s6,
    "S7": gate_s7,
    "S8": gate_s8,
}


# ---------------------------------------------------------------- commands

def cmd_init(root: Path, args: argparse.Namespace) -> int:
    engine_root = root / ENGINE_DIR
    if db_path(root).is_file() and not args.force:
        raise EngineError(f"Engine DB already exists at {db_path(root)}; use --force to re-init")
    steps = load_steps_template()
    engine_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(root))
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    connection.execute("DELETE FROM steps")
    connection.execute("DELETE FROM checkpoints")
    connection.execute("DELETE FROM logs")
    connection.execute("DELETE FROM meta")
    for index, step in enumerate(steps, start=1):
        connection.execute(
            "INSERT INTO steps (id, template, skill, display_name, step_order, checkpoint, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (
                step["id"],
                step.get("template", args.template),
                step["skill"],
                step.get("display_name", step["id"]),
                index,
                step.get("checkpoint", ""),
            ),
        )
    set_meta(connection, "template", args.template)
    set_meta(connection, "subquestions", int(args.subquestions or 0))
    set_meta(connection, "title", args.title or "")
    set_meta(connection, "created_at", utc_now())
    log(connection, None, "info", f"initialized template {args.template}")
    print(f"Initialized {args.template} at {root} ({len(steps)} steps)")
    return 0


def cmd_status(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    steps = all_steps(connection)
    rows = []
    for step in steps:
        rows.append({
            "id": step["id"],
            "skill": step["skill"],
            "display_name": step["display_name"],
            "checkpoint": step["checkpoint"],
            "status": step["status"],
            "error_message": step["error_message"],
            "completed_at": step["completed_at"],
        })
    payload = {
        "template": get_meta(connection, "template"),
        "subquestions": get_meta(connection, "subquestions", 0),
        "steps": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Workspace: {root}  template: {payload['template']}  "
              f"subquestions: {payload['subquestions']}")
        print(f"{'ID':<4}{'status':<18}{'checkpoint':<12}{'skill'}")
        for row in rows:
            print(f"{row['id']:<4}{row['status']:<18}{row['checkpoint'] or '-':<12}{row['skill']}")
        pending = [row["id"] for row in rows if row["status"] != "completed"]
        print(f"pending/completed: {len(pending)}/{len(rows)}")
    return 0


def cmd_start(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    step = require_step(connection, args.step)
    if step["status"] == "completed":
        raise EngineError(f"{args.step} is already completed")
    if step["status"] == "running":
        print(f"{args.step} is already running")
        return 0
    if step["status"] == "waiting_checkpoint":
        raise EngineError(f"{args.step} is waiting for a checkpoint; resolve or reject it first")
    set_step_status(connection, args.step, "running")
    connection.execute("UPDATE steps SET started_at = ? WHERE id = ?", (utc_now(), args.step))
    connection.commit()
    log(connection, args.step, "info", "started")
    print(f"{args.step} running: {step['skill']}")
    return 0


def run_gate(root: Path, connection: sqlite3.Connection, step_id: str) -> list[str]:
    gate = GATES[step_id]
    blockers = gate(root, connection)
    log(connection, step_id, "warn" if blockers else "info",
        "gate " + ("PASS" if not blockers else "FAIL: " + "; ".join(blockers)))
    return blockers


def cmd_gate(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    require_step(connection, args.step)
    blockers = run_gate(root, connection, args.step)
    if blockers:
        print(f"[FAIL] gate {args.step}")
        for blocker in blockers:
            print(f"  - {blocker}")
        return 1
    print(f"[PASS] gate {args.step}")
    return 0


def cmd_complete(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    step = require_step(connection, args.step)
    if step["status"] not in ("running", "rejected"):
        raise EngineError(f"{args.step} must be running before complete (currently {step['status']})")
    blockers = run_gate(root, connection, args.step)
    if blockers:
        set_step_status(connection, args.step, "running", error_message="; ".join(blockers))
        log(connection, args.step, "error", "gate failed: " + "; ".join(blockers))
        print(f"[FAIL] gate {args.step}; step stays running")
        for blocker in blockers:
            print(f"  - {blocker}")
        return 1
    note = args.note or ""
    if note:
        log(connection, args.step, "info", f"note: {note}")
    if step["checkpoint"]:
        set_step_status(connection, args.step, "waiting_checkpoint")
        connection.execute(
            "INSERT INTO checkpoints (step_id, ctype, status, data, response, created_at) "
            "VALUES (?, ?, 'pending', ?, '{}', ?)",
            (args.step, step["checkpoint"], json.dumps({"note": note}, ensure_ascii=False), utc_now()),
        )
        connection.commit()
        print(f"[PASS] gate {args.step}; step waits for {step['checkpoint']} checkpoint")
    else:
        connection.execute(
            "UPDATE steps SET completed_at = ? WHERE id = ?", (utc_now(), args.step)
        )
        connection.commit()
        set_step_status(connection, args.step, "completed")
        log(connection, args.step, "info", "completed (no checkpoint)")
        print(f"[PASS] gate {args.step}; step completed")
    return 0


def cmd_checkpoint(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    step = require_step(connection, args.step)
    if step["checkpoint"] not in CHECKPOINT_KINDS:
        raise EngineError(f"{args.step} has no checkpoint")
    if step["status"] != "waiting_checkpoint":
        raise EngineError(f"{args.step} is not waiting for a checkpoint (currently {step['status']})")
    row = connection.execute(
        "SELECT * FROM checkpoints WHERE step_id = ? AND status = 'pending' "
        "ORDER BY id DESC LIMIT 1",
        (args.step,),
    ).fetchone()
    if row is None:
        raise EngineError(f"{args.step} has no pending checkpoint record")
    if args.action == "resolve":
        try:
            response = json.loads(args.response) if args.response else {}
        except json.JSONDecodeError:
            # Shells often strip quotes; fall back to a plain-text response.
            response = {"text": args.response}
        connection.execute(
            "UPDATE checkpoints SET status = 'resolved', response = ?, resolved_at = ? WHERE id = ?",
            (json.dumps(response, ensure_ascii=False), utc_now(), row["id"]),
        )
        connection.execute("UPDATE steps SET completed_at = ? WHERE id = ?", (utc_now(), args.step))
        connection.commit()
        set_step_status(connection, args.step, "completed")
        log(connection, args.step, "info", f"checkpoint resolved {json.dumps(response, ensure_ascii=False)}")
        print(f"{args.step} checkpoint resolved; step completed")
    else:  # reject
        if not args.feedback or not args.feedback.strip():
            raise EngineError("reject requires non-empty --feedback")
        connection.execute(
            "UPDATE checkpoints SET status = 'rejected', response = ?, resolved_at = ? WHERE id = ?",
            (json.dumps({"feedback": args.feedback}, ensure_ascii=False), utc_now(), row["id"]),
        )
        connection.commit()
        set_step_status(connection, args.step, "rejected", error_message=args.feedback)
        log(connection, args.step, "warn", f"checkpoint rejected: {args.feedback}")
        print(f"{args.step} checkpoint rejected with feedback; step set back to rejected")
    return 0


def cmd_advance(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    steps = all_steps(connection)
    next_action = None
    for step in steps:
        status = step["status"]
        if status == "completed":
            continue
        if status == "running":
            next_action = f"step {step['id']} ({step['skill']}) is running; complete or resume it"
        elif status == "waiting_checkpoint":
            next_action = f"step {step['id']} waits for {step['checkpoint']} checkpoint"
        elif status == "rejected":
            next_action = f"step {step['id']} was rejected; rerun it (start -> complete)"
        else:
            previous = steps[step["step_order"] - 2] if step["step_order"] > 1 else None
            if previous is None or previous["status"] == "completed":
                next_action = f"start {step['id']} ({step['skill']})"
            else:
                next_action = f"step {step['id']} blocked by {previous['id']} ({previous['status']})"
        break
    print(f"next: {next_action or 'all steps completed'}")
    return 0


def cmd_resume(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    recovered = []
    for step in all_steps(connection):
        if step["status"] == "running":
            set_step_status(connection, step["id"], "pending")
            connection.execute("UPDATE steps SET started_at = NULL WHERE id = ?", (step["id"],))
            connection.commit()
            recovered.append(step["id"])
            log(connection, step["id"], "warn", "crash recovery: running -> pending")
    if recovered:
        print("recovered to pending: " + ", ".join(recovered))
    else:
        print("no running steps to recover")
    cmd_advance(root, args)
    return 0


def cmd_backfill(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    steps = all_steps(connection)
    chosen = set(args.steps.split(",")) if args.steps else {step["id"] for step in steps}
    unknown = chosen - {step["id"] for step in steps}
    if unknown:
        raise EngineError(f"Unknown steps for backfill: {sorted(unknown)}")
    confirmed = set(args.confirmed.split(",")) if args.confirmed else set()
    invalid = confirmed - {"modeling", "abstract", "paper"}
    if invalid:
        raise EngineError(f"Unknown confirmations: {sorted(invalid)}")
    for step in steps:
        if step["id"] not in chosen:
            continue
        connection.execute(
            "UPDATE steps SET status = 'completed', completed_at = ? WHERE id = ?",
            (utc_now(), step["id"]),
        )
        if step["checkpoint"]:
            connection.execute(
                "INSERT INTO checkpoints (step_id, ctype, status, data, response, created_at, resolved_at) "
                "VALUES (?, ?, 'resolved', '{}', ?, ?, ?)",
                (
                    step["id"],
                    step["checkpoint"],
                    json.dumps({"backfilled": True}, ensure_ascii=False),
                    utc_now(),
                    utc_now(),
                ),
            )
    connection.commit()
    if confirmed:
        set_meta(connection, "confirmations", {key: True for key in confirmed})
    log(connection, None, "info", f"backfilled steps {sorted(chosen)}")
    print(f"backfilled {len(chosen)} step(s); confirmations: {sorted(confirmed)}")
    return 0


def sync_state_payload(root: Path, connection: sqlite3.Connection) -> dict[str, Any]:
    steps = all_steps(connection)
    by_id = {step["id"]: step["status"] for step in steps}
    stages: dict[str, dict[str, Any]] = {}
    current_stage = None
    for stage, ids in STAGE_MAP.items():
        statuses = [by_id.get(step_id, "pending") for step_id in ids]
        completed = all(status == "completed" for status in statuses)
        if not completed and current_stage is None:
            current_stage = stage
        stages[stage] = {"status": "completed" if completed else "pending", "blockers": []}
    existing: dict[str, Any] = {}
    state_path = root / wg.STATE_FILE
    if state_path.is_file():
        try:
            existing = wg.load_state(root)
        except wg.GateError:
            existing = {}
    confirmations = existing.get("confirmations")
    meta_confirmations = get_meta(connection, "confirmations", {})
    if isinstance(meta_confirmations, dict) and meta_confirmations:
        confirmations = {
            key: {"confirmed": bool(value), "confirmed_at": utc_now()}
            for key, value in meta_confirmations.items()
        }
    if confirmations is None:
        confirmations = {key: {"confirmed": False, "confirmed_at": None} for key in wg.CONFIRMATION_STAGES}
    payload = {
        "schema_version": 1,
        "project": root.name,
        "subquestions": get_meta(connection, "subquestions", 0),
        "current_stage": current_stage,
        "confirmations": confirmations,
        "stages": stages,
        "history": existing.get("history", []),
    }
    return payload


def cmd_sync_state(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    payload = sync_state_payload(root, connection)
    if args.check:
        state_path = root / wg.STATE_FILE
        if not state_path.is_file():
            print("[FAIL] sync-state --check: workflow-state.json missing")
            return 1
        try:
            current = wg.load_state(root)
        except wg.GateError as exc:
            print(f"[FAIL] sync-state --check: {exc}")
            return 1
        mismatches = []
        for stage in wg.STAGES:
            if current["stages"][stage]["status"] != payload["stages"][stage]["status"]:
                mismatches.append(f"{stage}: {current['stages'][stage]['status']} != {payload['stages'][stage]['status']}")
        if mismatches:
            print("[FAIL] sync-state --check: " + "; ".join(mismatches))
            return 1
        print("[PASS] sync-state --check: engine stages match workflow-state.json")
        return 0
    wg.save_state(root, payload)
    wg.append_progress(root, "engine", "sync-state", "engine stages synced to workflow-state.json")
    print("synced engine stages to workflow-state.json")
    return 0


def cmd_report(root: Path, args: argparse.Namespace) -> int:
    connection = connect(root)
    steps = all_steps(connection)
    report = {
        "template": get_meta(connection, "template"),
        "subquestions": get_meta(connection, "subquestions", 0),
        "title": get_meta(connection, "title", ""),
        "steps": [
            {
                "id": step["id"],
                "skill": step["skill"],
                "display_name": step["display_name"],
                "checkpoint": step["checkpoint"],
                "status": step["status"],
                "error_message": step["error_message"],
            }
            for step in steps
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- CLI

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="workflow_engine",
        description="Modex-style workflow engine for comp_cumcm (SQLite state machine).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def workspace_arg(parser_: argparse.ArgumentParser) -> None:
        parser_.add_argument("workspace", help="题目工作区目录，如 workspace/2025C-nipt")

    p = sub.add_parser("init", help="create engine DB from a template")
    workspace_arg(p)
    p.add_argument("--template", default="comp_cumcm")
    p.add_argument("--subquestions", type=int, default=0)
    p.add_argument("--title", default="")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("status", help="show step states")
    workspace_arg(p)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("start", help="mark a step as running")
    workspace_arg(p)
    p.add_argument("step")

    p = sub.add_parser("complete", help="run the step gate and complete/wait-checkpoint")
    workspace_arg(p)
    p.add_argument("step")
    p.add_argument("--note", default="")

    p = sub.add_parser("gate", help="read-only quality gate of a step")
    workspace_arg(p)
    p.add_argument("step")

    p = sub.add_parser("checkpoint", help="resolve or reject a pending checkpoint")
    workspace_arg(p)
    p.add_argument("step")
    p.add_argument("action", choices=("resolve", "reject"))
    p.add_argument("--response", default="", help="JSON for resolve")
    p.add_argument("--feedback", default="", help="text for reject")

    p = sub.add_parser("advance", help="print the next actionable step")
    workspace_arg(p)

    p = sub.add_parser("resume", help="crash recovery: running -> pending")
    workspace_arg(p)

    p = sub.add_parser("backfill", help="import existing artifacts as completed steps")
    workspace_arg(p)
    p.add_argument("--steps", default="", help="comma list like S1,S2,S3 (default: all)")
    p.add_argument("--confirmed", default="", help="comma list like modeling,abstract,paper")

    p = sub.add_parser("sync-state", help="align workflow-state.json with the engine")
    workspace_arg(p)
    p.add_argument("--check", action="store_true")

    p = sub.add_parser("report", help="machine-readable JSON report")
    workspace_arg(p)

    return parser.parse_args(argv)


def decode_b64(value: Any) -> Any:
    """Decode a 'b64:'-prefixed free-text CLI argument (shell/plugin safety)."""
    if isinstance(value, str) and value.startswith("b64:"):
        try:
            return base64.b64decode(value[4:], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return value[4:]
    return value


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept both "<workspace> <command> ..." and "<command> <workspace> ...".
    commands = {
        "init", "status", "start", "complete", "gate", "checkpoint",
        "advance", "resume", "backfill", "sync-state", "report",
    }
    if argv and argv[0] not in commands and len(argv) >= 2 and argv[1] in commands:
        argv = [argv[1], argv[0]] + argv[2:]
    args = parse_args(argv)
    for field in ("title", "note", "response", "feedback"):
        current = getattr(args, field, None)
        if current:
            setattr(args, field, decode_b64(current))
    root = Path(args.workspace).resolve()
    if not root.is_dir():
        raise EngineError(f"Workspace does not exist: {root}")
    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "start": cmd_start,
        "complete": cmd_complete,
        "gate": cmd_gate,
        "checkpoint": cmd_checkpoint,
        "advance": cmd_advance,
        "resume": cmd_resume,
        "backfill": cmd_backfill,
        "sync-state": cmd_sync_state,
        "report": cmd_report,
    }
    try:
        return commands[args.command](root, args)
    except EngineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
