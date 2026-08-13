# -*- coding: utf-8 -*-
"""Persisted artifact gates for the three-stage math-modeling workflow.

Usage:
    python scripts/workflow_gate.py <workspace> status
    python scripts/workflow_gate.py <workspace> start <modeling|code|paper>
    python scripts/workflow_gate.py <workspace> confirm <modeling|abstract|paper>
    python scripts/workflow_gate.py <workspace> check <modeling|code|paper>
    python scripts/workflow_gate.py <workspace> advance <modeling|code|paper>

The command-first form is also accepted, for example
``python scripts/workflow_gate.py status workspace/demo``.  ``status`` and
``check`` never modify the workspace; ``start``, ``confirm``, and ``advance``
are the only commands that update ``workflow-state.json``.

For the code stage, ``workflow-state.json`` declares the expected question
count via ``subquestions``.  If that count is zero, the gate derives expected
questions from existing ``results/qN`` directories so legacy workspaces can
still be checked read-only.  Every expected question must have its own solved
summary, non-none robustness marker, matching script, readable PNG/PDF figure
pair, and manifest row that points to an existing artifact and producer script
for that question.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


STAGES = ("modeling", "code", "paper")
CONFIRMATION_STAGES = ("modeling", "abstract", "paper")
STATE_FILE = "workflow-state.json"
PROGRESS_FILE = "progress.md"
SCHEME_REGISTRY_FILE = "01-analysis/scheme-registry.json"
Q_DIR_RE = re.compile(r"q([1-9][0-9]*)$")
PRODUCER_SCRIPT_SUFFIXES = {".py", ".m"}
M1_TABLE_CONTRACTS = {
    "01-analysis/data-audit.md": (
        "dataset",
        "audit_item",
        "finding",
        "impact",
        "action",
        "verified",
    ),
    "01-analysis/research-plan.md": (
        "question",
        "research_objective",
        "core_output",
        "decision_rule",
        "main_risk",
        "fallback",
        "verified",
    ),
    "01-analysis/claim-evidence-matrix.md": (
        "question",
        "claim_id",
        "claim",
        "evidence_needed",
        "independent_check",
        "falsification_test",
        "uncertainty",
        "status",
    ),
    "01-analysis/derivation-notes.md": (
        "question",
        "variables",
        "assumptions",
        "objective_or_relation",
        "constraints",
        "direction_unit_checks",
        "failure_condition",
        "verified",
    ),
    "01-analysis/experiment-matrix.md": (
        "question",
        "experiment",
        "purpose",
        "protocol",
        "metric_or_check",
        "expected_artifact",
        "verified",
    ),
}
M2_EVIDENCE_FILES = (
    "diagnostics.md",
    "ablation.md",
    "independent-validation.md",
    "uncertainty.md",
    "failure-boundaries.md",
    "semantic-checks.md",
)
M2_EVIDENCE_COLUMNS = (
    "check",
    "method",
    "result",
    "evidence",
    "implication",
    "verified",
)
INDEPENDENT_VALIDATION_KINDS = {
    "holdout",
    "external-data",
    "alternative-implementation",
    "analytical-cross-check",
    "benchmark",
    "manual-double-check",
    "synthetic-truth",
    "forward-reconstruction",
    "counterfactual",
}
INDEPENDENT_VALIDATION_ARTIFACT_HINTS = (
    "validation",
    "holdout",
    "external",
    "backtest",
    "benchmark",
    "crosscheck",
    "cross-check",
    "analytic",
    "synthetic",
    "reconstruction",
    "counterfactual",
    "manual-audit",
)
QUESTION_SECTION_SUFFIXES = {
    "modeling_process": "modeling-process",
    "results_interpretation": "results",
    "model_argumentation": "model-argumentation",
}
QUESTION_SECTION_HEADINGS = {
    "modeling_process": ("任务转化", "机理与假设", "变量与符号", "模型建立与推导", "求解流程"),
    "results_interpretation": ("核心结果", "结果解释"),
    "model_argumentation": ("方案选择", "模型诊断", "独立验证", "不确定性", "失效边界"),
}
MARKDOWN_FIGURE_RE = re.compile(
    r"^[ \t]*!\[(?P<caption>[^\]]*)\]\((?P<path>[^)\n]+)\)[ \t]*$",
    re.MULTILINE,
)
GENERIC_FIGURE_CAPTIONS = {
    "图",
    "图片",
    "示意图",
    "结果图",
    "分析图",
    "模型结果",
    "figure",
    "plot",
}
QUESTION_SECTION_MIN_CHARS = {
    "modeling_process": 1200,
    "results_interpretation": 600,
    "model_argumentation": 1200,
}
EXPANSION_LEDGER_COLUMNS = (
    "question",
    "section_type",
    "purpose",
    "unique_content",
    "source_artifacts",
    "target_pages",
    "overlap_guard",
    "verified",
)
QUESTION_DEPTH_COLUMNS = (
    "question",
    "modeling_process",
    "results_interpretation",
    "model_argumentation",
    "independent_validation",
    "uncertainty",
    "failure_boundary",
    "verified",
)
REVISION_LOG_COLUMNS = (
    "round",
    "reviewer",
    "findings",
    "changes",
    "recheck",
    "status",
)
LEDGER_COLUMNS = (
    "paper_location",
    "claim_or_value",
    "summary_source",
    "manifest_row",
    "reproducibility_record",
    "verified",
    "notes",
)
ARGUMENT_MAP_COLUMNS = (
    "question",
    "core_claim",
    "model_basis",
    "alternative_or_waiver",
    "evidence",
    "robustness",
    "limitation_boundary",
    "paper_location",
    "verified",
)
DEPTH_AUDIT_COLUMNS = ("dimension", "score", "evidence", "gap")
DEPTH_DIMENSIONS = (
    "problem transformation",
    "mechanism/derivation",
    "scheme justification",
    "algorithm transparency",
    "evidence/interpretation",
    "robustness/uncertainty",
    "limitation/boundary",
    "cross-question coherence",
    "visual communication",
)
DEPTH_KEY_DIMENSIONS = (
    "scheme justification",
    "evidence/interpretation",
    "robustness/uncertainty",
)
PLACEHOLDER_EXACT = {
    "",
    "-",
    "--",
    "tbd",
    "todo",
    "n/a",
    "na",
    "null",
    "none",
    "待补",
    "待完善",
    "待定",
    "待填",
    "无",
}
PLACEHOLDER_PATTERNS = ("tbd", "todo", "待补", "待完善", "待定", "待填")


class GateError(Exception):
    """An actionable error caused by a bad command or workspace state."""


class DuplicateJsonKeyError(ValueError):
    """A JSON object repeated a member name and is therefore ambiguous."""


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=unique_json_object)


def nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""


def read_bytes(path: Path, length: int) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(length)
    except OSError:
        return b""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_state(root: Path) -> dict[str, Any]:
    state_path = root / STATE_FILE
    if not state_path.is_file():
        raise GateError(
            f"Missing {STATE_FILE}. Create this workspace with "
            "scripts/init_workspace.py (existing workspaces are not changed automatically)."
        )
    try:
        state = strict_json_loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise GateError(f"Cannot read {state_path}: {exc}") from exc

    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise GateError(f"Unsupported {STATE_FILE} schema; expected schema_version 1.")
    if state.get("current_stage") not in {*STAGES, None}:
        raise GateError(f"Invalid current_stage in {STATE_FILE}.")
    stages = state.get("stages")
    if not isinstance(stages, dict) or any(stage not in stages for stage in STAGES):
        raise GateError(f"Invalid stages in {STATE_FILE}.")
    for stage in STAGES:
        if not isinstance(stages[stage], dict) or stages[stage].get("status") not in {
            "pending", "in_progress", "completed"
        }:
            raise GateError(f"Invalid status for stage '{stage}' in {STATE_FILE}.")
        if "blockers" in stages[stage] and not isinstance(stages[stage]["blockers"], list):
            raise GateError(f"Invalid blockers for stage '{stage}' in {STATE_FILE}.")
    normalize_confirmations(state)
    return state


def transient_state(root: Path) -> dict[str, Any]:
    """Minimal in-memory state for read-only checks of legacy workspaces."""
    return {
        "_legacy": True,
        "schema_version": 1,
        "project": root.name,
        "subquestions": 0,
        "current_stage": None,
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


def normalize_confirmations(state: dict[str, Any]) -> None:
    confirmations = state.setdefault("confirmations", {})
    if not isinstance(confirmations, dict):
        raise GateError("Invalid confirmations in workflow-state.json.")
    for stage in CONFIRMATION_STAGES:
        existing = confirmations.setdefault(stage, {"confirmed": False, "confirmed_at": None})
        if not isinstance(existing, dict):
            raise GateError(f"Invalid confirmation for stage '{stage}' in workflow-state.json.")
        existing.setdefault("confirmed", False)
        existing.setdefault("confirmed_at", None)
        if not isinstance(existing["confirmed"], bool):
            raise GateError(f"Invalid confirmed flag for stage '{stage}' in workflow-state.json.")


def is_managed(state: dict[str, Any]) -> bool:
    return not state.get("_legacy", False)


def has_confirmation(state: dict[str, Any], stage: str) -> bool:
    return bool(state.get("confirmations", {}).get(stage, {}).get("confirmed"))


def save_state(root: Path, state: dict[str, Any]) -> None:
    state_path = root / STATE_FILE
    temporary = state_path.with_suffix(".json.tmp")
    persisted = {key: value for key, value in state.items() if not key.startswith("_")}
    try:
        temporary.write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(state_path)
    except OSError as exc:
        raise GateError(f"Cannot save {state_path}: {exc}") from exc


def add_history(state: dict[str, Any], action: str, stage: str) -> None:
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        raise GateError("Invalid history in workflow-state.json.")
    history.append({"at": utc_now(), "action": action, "stage": stage})


def append_progress(root: Path, stage: str, action: str, output: str, risk: str = "") -> None:
    progress = root / PROGRESS_FILE
    if not progress.exists():
        progress.write_text(
            "# 进度记录（全队唯一事实源）\n\n"
            "| 时间 | 关卡 | 产出 | 风险/待办 |\n"
            "|---|---|---|---|\n",
            encoding="utf-8",
        )
    timestamp = dt.datetime.now().replace(microsecond=0).isoformat()
    row = f"| {timestamp} | workflow:{stage}:{action} | {output} | {risk} |\n"
    with progress.open("a", encoding="utf-8") as handle:
        handle.write(row)


def expected_questions(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None = None,
) -> list[int]:
    declared = state.get("subquestions", 0)
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        raise GateError("Invalid subquestions in workflow-state.json.")
    if declared:
        return list(range(1, declared + 1))

    if registry is not None and isinstance(registry.get("questions"), dict):
        questions = []
        for key in registry["questions"]:
            match = Q_DIR_RE.fullmatch(str(key))
            if match:
                questions.append(int(match.group(1)))
        if questions:
            return sorted(set(questions))

    questions = []
    results = root / "results"
    if results.is_dir():
        for child in results.iterdir():
            match = Q_DIR_RE.fullmatch(child.name) if child.is_dir() else None
            if match:
                questions.append(int(match.group(1)))
    return sorted(questions)


def question_path(root: Path, question: int) -> Path:
    return root / "results" / f"q{question}"


def matches(path: Path, pattern: str) -> list[Path]:
    return [candidate for candidate in path.glob(pattern) if nonempty_file(candidate)]


def parse_frontmatter_details(path: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """Parse leading simple frontmatter and report duplicate top-level keys."""
    text = read_text(path)
    if not text:
        return {}, ()
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ()

    fields: dict[str, str] = {}
    seen: set[str] = set()
    duplicates: list[str] = []
    current_list_key: str | None = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped in {"---", "..."}:
            return fields, tuple(duplicates)
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            if current_list_key:
                item = stripped
                if item.startswith("-"):
                    item = item[1:].strip()
                item = item.strip("\"'")
                if item:
                    existing = fields.get(current_list_key, "")
                    fields[current_list_key] = (
                        f"{existing}\n{item}" if existing else item
                    )
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        if key:
            if key in seen and key not in duplicates:
                duplicates.append(key)
            seen.add(key)
            fields[key] = value
            if not value:
                current_list_key = key
    return {}, ()


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse only leading YAML-style frontmatter with simple fields and lists."""
    return parse_frontmatter_details(path)[0]


def requires_unique_frontmatter(path: Path, label: str, blockers: list[str]) -> None:
    if not nonempty_file(path):
        return
    _, duplicates = parse_frontmatter_details(path)
    for key in duplicates:
        blockers.append(f"{label} frontmatter has duplicate key: {key}")


def frontmatter_value(path: Path, field: str) -> str | None:
    return parse_frontmatter(path).get(field.lower())


def requires_nonempty(path: Path, label: str, blockers: list[str]) -> None:
    if not nonempty_file(path):
        blockers.append(f"Missing or empty {label}: {path.as_posix()}")


def requires_frontmatter_value(
    path: Path,
    field: str,
    expected: str,
    label: str,
    blockers: list[str],
) -> None:
    if nonempty_file(path) and (frontmatter_value(path, field) or "").lower() != expected.lower():
        blockers.append(f"{label}: {path.as_posix()}")


def registry_question_number(label: str) -> int | None:
    match = Q_DIR_RE.fullmatch(label)
    return int(match.group(1)) if match else None


def load_scheme_registry(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = root / SCHEME_REGISTRY_FILE
    if not nonempty_file(path):
        return None, [f"M1: missing non-empty {SCHEME_REGISTRY_FILE}"]
    try:
        registry = strict_json_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        return None, [f"M1: cannot read {SCHEME_REGISTRY_FILE}: {exc}"]
    if not isinstance(registry, dict):
        return None, [f"M1: {SCHEME_REGISTRY_FILE} must contain a JSON object"]
    return registry, []


def candidate_names(candidates: Any) -> list[str]:
    if not isinstance(candidates, list):
        return []
    names: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            name = str(candidate.get("name", "")).strip()
            if name:
                names.append(name)
    return names


def duplicate_casefolded(values: list[str]) -> bool:
    lowered = [value.casefold() for value in values]
    return len(lowered) != len(set(lowered))


def parse_list_value(value: str | None) -> list[str]:
    if value is None:
        return []
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    items: list[str] = []
    for part in re.split(r"[\n,]", stripped):
        item = part.strip().strip("-").strip().strip("\"'")
        if item:
            items.append(item)
    return items


def covers_all(actual: list[str], expected: list[str]) -> bool:
    return set(actual) == set(expected)


def validate_scheme_registry(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    if registry is None:
        return blockers
    if registry.get("version") != 1:
        blockers.append("M1 scheme registry must record version: 1")
    questions = registry.get("questions")
    if not isinstance(questions, dict) or not questions:
        blockers.append("M1 scheme registry must define a non-empty questions object")
        return blockers
    for label in questions:
        if registry_question_number(str(label)) is None:
            blockers.append(f"M1 scheme registry has invalid question key: {label}")

    expected = expected_questions(root, state, registry)
    for question in expected:
        label = f"q{question}"
        spec = questions.get(label)
        if not isinstance(spec, dict):
            blockers.append(f"M1 {label}: scheme registry missing question entry")
            continue

        candidates = spec.get("candidates")
        names = candidate_names(candidates)
        candidate_set = set(names)
        kinds = {
            str(candidate.get("kind", "")).strip().lower()
            for candidate in candidates
            if isinstance(candidate, dict)
        } if isinstance(candidates, list) else set()
        if len(candidate_set) < 2:
            blockers.append(f"M1 {label}: scheme registry needs >=2 distinct candidates")
        if duplicate_casefolded(names):
            blockers.append(f"M1 {label}: candidate names must be unique case-insensitively")
        if "baseline" not in kinds or "advanced" not in kinds:
            blockers.append(f"M1 {label}: candidates must include baseline and advanced kinds")

        race = spec.get("race")
        if not isinstance(race, dict):
            blockers.append(f"M1 {label}: missing race object")
            continue
        required = race.get("required")
        if not isinstance(required, bool):
            blockers.append(f"M1 {label}: race.required must be true or false")
            continue
        if required:
            schemes = race.get("schemes")
            if not isinstance(schemes, list):
                schemes = []
            scheme_names = [str(scheme).strip() for scheme in schemes if str(scheme).strip()]
            scheme_set = set(scheme_names)
            if len(scheme_set) < 2:
                blockers.append(f"M1 {label}: required race needs >=2 distinct scheme names")
            if duplicate_casefolded(scheme_names):
                blockers.append(f"M1 {label}: race scheme names must be unique case-insensitively")
            unknown = [
                scheme for scheme in scheme_names
                if scheme not in candidate_set
            ]
            if unknown:
                blockers.append(
                    f"M1 {label}: race schemes must exactly match candidate names ({', '.join(unknown)})"
                )
            checks = race.get("feasibility_checks")
            if not isinstance(checks, list) or not any(str(item).strip() for item in checks):
                blockers.append(f"M1 {label}: required race needs nonempty feasibility_checks")
            if not str(race.get("primary_metric", "")).strip():
                blockers.append(f"M1 {label}: required race needs nonempty primary_metric")
            if race.get("direction") not in {"min", "max"}:
                blockers.append(f"M1 {label}: required race direction must be min or max")
            if not str(race.get("protocol", "")).strip():
                blockers.append(f"M1 {label}: required race needs nonempty protocol")
        elif not str(race.get("waiver_reason", "")).strip():
            blockers.append(f"M1 {label}: non-race question needs nonempty waiver_reason")
    return blockers


def registered_question_specs(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    specs: list[tuple[int, dict[str, Any]]] = []
    questions = registry.get("questions", {})
    if not isinstance(questions, dict):
        return specs
    for question in expected_questions(root, state, registry):
        spec = questions.get(f"q{question}")
        if isinstance(spec, dict):
            specs.append((question, spec))
    return specs


def markdown_table_raw(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text(path)
    header: list[str] = []
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) < 2:
            continue
        if all(set(column) <= {"-", ":"} for column in columns):
            continue
        if not header:
            header = columns
            continue
        if len(columns) >= len(header):
            rows.append(dict(zip(header, columns[:len(header)])))
    return header, rows


def find_table_column(headers: list[str], candidates: set[str]) -> str | None:
    lowered = {header.lower(): header for header in headers}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None




def find_status_column(headers: list[str]) -> str | None:
    for header in headers:
        normalized = header.lower()
        if "feasibility" in normalized or "status" in normalized:
            return header
        if "可行" in header or "状态" in header:
            return header
    return None


def finite_number(value: str | None) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", stripped):
        return False
    try:
        parsed = float(stripped)
    except ValueError:
        return False
    return math.isfinite(parsed)


def feasible_status(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    return normalized in {"pass", "feasible", "ok"}


def scheme_race_blockers(root: Path, question: int, spec: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    label = f"q{question}"
    race = spec.get("race") if isinstance(spec.get("race"), dict) else {}
    candidates = candidate_names(spec.get("candidates"))
    candidate_set = set(candidates)
    summary = question_path(root, question) / "summary.md"
    chosen = (frontmatter_value(summary, "chosen_scheme") or "").strip()
    if not chosen:
        blockers.append(f"M2 {label}: summary.md must record nonempty chosen_scheme")
        return blockers

    if not race.get("required"):
        if chosen not in candidate_set:
            blockers.append(f"M2 {label}: chosen_scheme must exactly match a registered candidate")
        return blockers

    registered_schemes = [
        str(scheme).strip()
        for scheme in race.get("schemes", [])
        if str(scheme).strip()
    ]
    compared = parse_list_value(frontmatter_value(summary, "schemes_compared"))
    if not covers_all(compared, registered_schemes):
        blockers.append(f"M2 {label}: summary schemes_compared must exactly match registered race schemes")

    comparison = question_path(root, question) / "scheme-comparison.md"
    if not nonempty_file(comparison):
        blockers.append(f"M2 {label}: missing non-empty results/{label}/scheme-comparison.md")
        return blockers

    winner = (frontmatter_value(comparison, "winner") or "").strip()
    primary_metric = (frontmatter_value(comparison, "primary_metric") or "").strip()
    registry_metric = str(race.get("primary_metric", "")).strip()
    if not winner:
        blockers.append(f"M2 {label}: scheme-comparison.md must record nonempty winner")
    if not primary_metric:
        blockers.append(f"M2 {label}: scheme-comparison.md must record nonempty primary_metric")
    if primary_metric and primary_metric != registry_metric:
        blockers.append(f"M2 {label}: primary_metric must exactly match registry primary_metric")
    if winner and winner not in set(registered_schemes):
        blockers.append(f"M2 {label}: winner must exactly match a registered race scheme")
    if winner and chosen != winner:
        blockers.append(f"M2 {label}: summary chosen_scheme must match comparison winner")

    headers, rows = markdown_table_raw(comparison)
    scheme_column = find_table_column(headers, {"scheme", "name", "method", "candidate", "方案", "模型"})
    metric_column = find_table_column(headers, {registry_metric})
    status_column = find_status_column(headers)
    if not rows or scheme_column is None or metric_column is None or status_column is None:
        blockers.append(
            f"M2 {label}: scheme-comparison table needs scheme, feasibility/status, "
            "and primary metric columns"
        )
        return blockers

    table_schemes = [
        row.get(scheme_column, "").strip()
        for row in rows
        if row.get(scheme_column, "").strip()
    ]
    if len(set(table_schemes)) < 2:
        blockers.append(f"M2 {label}: scheme-comparison table needs >=2 schemes")
    for scheme in registered_schemes:
        matching = [
            row for row in rows
            if row.get(scheme_column, "").strip() == scheme
        ]
        if len(matching) != 1:
            blockers.append(f"M2 {label}: comparison table must contain exactly one row for '{scheme}'")
            continue
        row = matching[0]
        status = normalized_cell(row.get(status_column)).casefold()
        if status not in {"pass", "feasible", "ok", "infeasible"}:
            blockers.append(
                f"M2 {label}: scheme '{scheme}' status must be pass|feasible|ok|infeasible"
            )
        if scheme == winner and status not in {"pass", "feasible", "ok"}:
            blockers.append(
                f"M2 {label}: winning scheme '{scheme}' needs feasible status pass|feasible|ok"
            )
        if not finite_number(row.get(metric_column)):
            blockers.append(f"M2 {label}: scheme '{scheme}' needs finite numeric {metric_column} value")
    return blockers


def governed_table_blockers(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
    relative: str,
    columns: tuple[str, ...],
    *,
    minimum_rows: int = 1,
    minimum_rows_per_question: int = 0,
) -> list[str]:
    blockers: list[str] = []
    path = root / relative
    label = relative.replace("/", " ")
    requires_nonempty(path, label, blockers)
    if not nonempty_file(path):
        return blockers
    requires_unique_frontmatter(path, label, blockers)
    if (frontmatter_value(path, "status") or "").strip().lower() != "ready":
        blockers.append(f"M1 {relative} must record status: ready")

    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != columns:
        blockers.append(f"M1 {relative} table columns must be exactly " + "|".join(columns))
        return blockers
    if len(rows) < minimum_rows:
        blockers.append(f"M1 {relative} needs at least {minimum_rows} substantive rows")

    question_counts: dict[int, int] = {}
    claim_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        for column in columns:
            if placeholder_value(row.get(column)):
                blockers.append(f"M1 {relative} row {index} column {column} is empty or placeholder")
        if "verified" in columns and normalized_cell(row.get("verified")).casefold() != "yes":
            blockers.append(f"M1 {relative} row {index} must record verified=yes")
        if "status" in columns:
            status = normalized_cell(row.get("status")).casefold()
            if status not in {"planned", "verified"}:
                blockers.append(f"M1 {relative} row {index} status must be planned or verified")
        if "claim_id" in columns:
            claim_id = normalized_cell(row.get("claim_id")).casefold()
            if claim_id in claim_ids:
                blockers.append(f"M1 {relative} has duplicate claim_id: {claim_id}")
            claim_ids.add(claim_id)
        if "question" in columns:
            question = argument_question_number(row.get("question"))
            if question is None:
                blockers.append(f"M1 {relative} row {index} has invalid question")
            else:
                question_counts[question] = question_counts.get(question, 0) + 1

    if "question" in columns:
        expected = set(expected_questions(root, state, registry))
        unknown = sorted(set(question_counts) - expected)
        for question in unknown:
            blockers.append(f"M1 {relative} has unknown question q{question}")
        for question in sorted(expected):
            count = question_counts.get(question, 0)
            if count < minimum_rows_per_question:
                blockers.append(
                    f"M1 {relative} q{question} needs at least "
                    f"{minimum_rows_per_question} substantive rows"
                )
    return blockers


def m1_research_contract_blockers(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    row_requirements = {
        "01-analysis/data-audit.md": (5, 0),
        "01-analysis/research-plan.md": (1, 1),
        "01-analysis/claim-evidence-matrix.md": (2, 2),
        "01-analysis/derivation-notes.md": (1, 1),
        "01-analysis/experiment-matrix.md": (4, 4),
    }
    for relative, columns in M1_TABLE_CONTRACTS.items():
        minimum_rows, per_question = row_requirements[relative]
        blockers.extend(
            governed_table_blockers(
                root,
                state,
                registry,
                relative,
                columns,
                minimum_rows=minimum_rows,
                minimum_rows_per_question=per_question,
            )
        )
    return blockers


def check_modeling(root: Path, state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    analysis = root / "01-analysis" / "analysis.md"
    selection = root / "01-analysis" / "model-selection.md"

    requires_nonempty(analysis, "P1 analysis", blockers)
    requires_nonempty(selection, "P2 model selection", blockers)
    requires_unique_frontmatter(selection, "P2 model selection", blockers)
    requires_frontmatter_value(
        selection,
        "frozen",
        "true",
        "P2 selection is not frozen (add frontmatter 'frozen: true')",
        blockers,
    )
    if is_managed(state) and not has_confirmation(state, "modeling"):
        blockers.append("M1 modeling requires recorded user confirmation")
    if is_managed(state):
        registry, registry_blockers = load_scheme_registry(root)
        blockers.extend(registry_blockers)
        blockers.extend(validate_scheme_registry(root, state, registry))
        blockers.extend(m1_research_contract_blockers(root, state, registry))
    return blockers


def result_question_dirs(root: Path) -> list[Path]:
    results = root / "results"
    if not results.is_dir():
        return []
    return sorted(
        (path for path in results.iterdir() if path.is_dir() and Q_DIR_RE.fullmatch(path.name)),
        key=lambda path: int(Q_DIR_RE.fullmatch(path.name).group(1)),
    )


def path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def resolve_workspace_path(root: Path, value: str) -> Path | None:
    cleaned = value.strip().strip("`").strip("\"'")
    if not cleaned:
        return None
    candidate = Path(cleaned)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    return candidate if path_inside(candidate, root) else None


def valid_png(path: Path) -> bool:
    return nonempty_file(path) and read_bytes(path, 8) == b"\x89PNG\r\n\x1a\n"


def valid_pdf(path: Path) -> bool:
    return nonempty_file(path) and read_bytes(path, 5) == b"%PDF-"


def valid_docx(path: Path) -> bool:
    if not nonempty_file(path) or read_bytes(path, 4) != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
    return "[Content_Types].xml" in names and any(
        name.startswith("word/") and name.endswith(".xml") for name in names
    )


def valid_tex(path: Path) -> bool:
    text = read_text(path)
    if not text:
        return False
    return bool(re.search(r"\\documentclass\b|\\begin\s*\{\s*document\s*\}", text))


def valid_paper_artifact(path: Path, allow_tex: bool) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return valid_pdf(path)
    if suffix == ".docx":
        return valid_docx(path)
    if allow_tex and suffix == ".tex":
        return valid_tex(path)
    return False


def valid_figure_pairs(question_dir: Path) -> list[tuple[Path, Path]]:
    pngs = {path.stem: path for path in (question_dir / "figs").glob("*.png") if valid_png(path)}
    pdfs = {path.stem: path for path in (question_dir / "figs").glob("*.pdf") if valid_pdf(path)}
    return [(pngs[stem], pdfs[stem]) for stem in sorted(pngs.keys() & pdfs.keys())]


def artifact_question(root: Path, artifact: Path) -> int | None:
    try:
        relative = artifact.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if len(parts) < 3 or parts[0] != "results":
        return None
    match = Q_DIR_RE.fullmatch(parts[1])
    return int(match.group(1)) if match else None


def manifest_rows(root: Path) -> list[dict[str, Any]]:
    manifest = read_text(root / "results" / "manifest.md")
    parsed: list[dict[str, Any]] = []
    for line_number, line in enumerate(manifest.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) < 4 or all(set(column) <= {"-", ":"} for column in columns):
            continue
        if columns[1].lower() in {"文件", "file", "artifact"}:
            continue
        artifact = resolve_workspace_path(root, columns[1])
        script = resolve_workspace_path(root, columns[2])
        parsed.append({
            "line": line_number,
            "label": columns[0],
            "artifact_text": columns[1],
            "script_text": columns[2],
            "artifact": artifact,
            "script": script,
            "question": artifact_question(root, artifact) if artifact else None,
        })
    return parsed


def manifest_table_rows(path: Path) -> list[tuple[str, str, str, str]]:
    parsed: list[tuple[str, str, str, str]] = []
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) < 4 or all(set(column) <= {"-", ":"} for column in columns):
            continue
        if columns[1].lower() in {"文件", "file", "artifact"}:
            continue
        parsed.append(tuple(columns[:4]))
    return parsed


def question_from_manifest_path(value: str) -> int | None:
    match = re.search(r"(^|[/\\])q([1-9][0-9]*)([/\\]|$)", value.replace("\\", "/"))
    return int(match.group(2)) if match else None


def canonical_fragment_rows(root: Path, questions: list[int]) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    blockers: list[str] = []
    rows: list[tuple[str, str, str, str]] = []
    for question in questions:
        label = f"q{question}"
        fragment = question_path(root, question) / "manifest-fragment.md"
        if not nonempty_file(fragment):
            blockers.append(f"M2 {label}: missing non-empty results/{label}/manifest-fragment.md")
            continue
        fragment_rows = manifest_table_rows(fragment)
        if not fragment_rows:
            blockers.append(f"M2 {label}: manifest-fragment.md has no artifact rows")
            continue
        rows.extend(fragment_rows)

    merged: list[tuple[str, str, str, str]] = []
    index: dict[str, int] = {}
    for row in rows:
        key = row[1].replace("\\", "/")
        if key in index:
            merged[index[key]] = row
        else:
            index[key] = len(merged)
            merged.append(row)
    return merged, blockers


def manifest_path_blockers(root: Path, rows: list[tuple[str, str, str, str]]) -> list[str]:
    blockers: list[str] = []
    for label, artifact_text, script_text, _ in rows:
        for value in (artifact_text, script_text):
            resolved = resolve_workspace_path(root, value)
            if resolved is None:
                blockers.append(f"M2 manifest row '{label}' has path outside workspace: {value}")
            elif not nonempty_file(resolved):
                blockers.append(f"M2 manifest row '{label}' points to missing artifact: {value}")
    return blockers


def managed_manifest_blockers(root: Path, questions: list[int]) -> list[str]:
    canonical, blockers = canonical_fragment_rows(root, questions)
    blockers.extend(manifest_path_blockers(root, canonical))
    current = manifest_table_rows(root / "results" / "manifest.md")
    if current != canonical:
        blockers.append("M2 results/manifest.md is stale; rebuild it from manifest fragments")
    return blockers


def manifest_row_is_valid_for_question(root: Path, row: dict[str, Any], question: int) -> bool:
    artifact = row["artifact"]
    script = row["script"]
    if row["question"] != question or artifact is None or script is None:
        return False
    if not nonempty_file(artifact) or not producer_script_matches_question(root, script, question):
        return False
    if artifact.suffix.lower() == ".png" and not valid_png(artifact):
        return False
    if artifact.suffix.lower() == ".pdf" and not valid_pdf(artifact):
        return False
    return True


def valid_manifest_artifacts_for_question(root: Path, rows: list[dict[str, Any]], question: int) -> list[Path]:
    return [
        row["artifact"] for row in rows
        if manifest_row_is_valid_for_question(root, row, question)
    ]


def manifest_reference_matches(root: Path, reference: str, row: dict[str, Any]) -> bool:
    cleaned = reference.strip().strip("`").strip("\"'")
    if not cleaned:
        return False
    if cleaned == row.get("label", ""):
        return True
    if cleaned == row.get("artifact_text", ""):
        return True
    artifact = row.get("artifact")
    if artifact is None:
        return False
    return mentions_path(cleaned, root, artifact)


def resolve_manifest_reference(
    root: Path,
    reference: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matches = [row for row in rows if manifest_reference_matches(root, reference, row)]
    return matches[0] if len(matches) == 1 else None


def producer_script_matches_question(root: Path, script: Path, question: int) -> bool:
    if not nonempty_file(script) or script.suffix.lower() not in PRODUCER_SCRIPT_SUFFIXES:
        return False
    if not path_inside(script, root / "code"):
        return False
    return bool(re.search(rf"(^|[^0-9])q0*{question}([^0-9]|$)", script.stem, re.IGNORECASE))


def reproducibility_script(root: Path, report: Path) -> Path | None:
    script_value = frontmatter_value(report, "script") or frontmatter_value(report, "script_path")
    return resolve_workspace_path(root, script_value) if script_value else None


def relative_workspace_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def mentions_path(value: str, root: Path, path: Path) -> bool:
    normalized = value.replace("\\", "/").lower()
    relative = relative_workspace_path(root, path).lower()
    absolute = str(path.resolve()).replace("\\", "/").lower()
    return relative in normalized or absolute in normalized


def existing_question_figures_or_tables(root: Path, question: int) -> list[Path]:
    question_dir = question_path(root, question)
    artifacts: list[Path] = []
    figs = question_dir / "figs"
    artifacts.extend(path for path in figs.glob("*.png") if valid_png(path))
    artifacts.extend(path for path in figs.glob("*.pdf") if valid_pdf(path))
    tables = question_dir / "tables"
    artifacts.extend(path for path in tables.iterdir() if path.is_file() and nonempty_file(path)) if tables.is_dir() else []
    return artifacts


def parse_frontmatter_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, list):
            return None
        entries = [str(item).strip() for item in parsed if str(item).strip()]
        return entries or None
    entries = []
    for line in stripped.splitlines():
        item = line.strip()
        if item.startswith("-"):
            item = item[1:].strip()
        item = item.strip("\"'")
        if item:
            entries.append(item)
    return entries or None


def resolve_output_entries(root: Path, value: str | None) -> set[Path] | None:
    entries = parse_frontmatter_list(value)
    if entries is None:
        return None
    resolved: set[Path] = set()
    for entry in entries:
        if entry.lower().endswith(".bak"):
            return None
        path = resolve_workspace_path(root, entry)
        if path is None or not nonempty_file(path):
            return None
        resolved.add(path)
    return resolved


def reproducibility_report_is_valid(
    root: Path,
    report: Path,
    question: int,
    manifest_artifacts: list[Path],
) -> bool:
    if (frontmatter_value(report, "question") or "").strip().lower() != f"q{question}":
        return False
    if (frontmatter_value(report, "exit_code") or "").strip() != "0":
        return False
    for field in ("command", "outputs", "checked_at", "checked_by"):
        if not non_none_value(frontmatter_value(report, field)):
            return False
    script = reproducibility_script(root, report)
    if script is None or not producer_script_matches_question(root, script, question):
        return False

    outputs = resolve_output_entries(root, frontmatter_value(report, "outputs"))
    if outputs is None:
        return False
    summary = question_path(root, question) / "summary.md"
    if summary.resolve() not in outputs:
        return False
    if not any(artifact.resolve() in outputs
               for artifact in existing_question_figures_or_tables(root, question)):
        return False
    if not any(artifact.resolve() in outputs for artifact in manifest_artifacts):
        return False
    return True


def markdown_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text(path)
    header: list[str] = []
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = [column.strip().lower() for column in stripped.strip("|").split("|")]
        if len(columns) < 2:
            continue
        if all(set(column) <= {"-", ":"} for column in columns):
            continue
        if not header:
            header = columns
            continue
        if header and len(columns) >= len(header):
            rows.append(dict(zip(header, columns[:len(header)])))
    return header, rows


def normalized_table_header(headers: list[str]) -> tuple[str, ...]:
    return tuple(header.strip().lower() for header in headers)


def normalized_cell(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip().strip("\"'`")).strip()


def placeholder_value(value: str | None, *, allow_explicit_none: bool = False) -> bool:
    normalized = normalized_cell(value).casefold()
    if allow_explicit_none and normalized in {"none", "no residual gap", "无", "无遗留"}:
        return False
    if normalized in PLACEHOLDER_EXACT:
        return True
    return any(pattern in normalized for pattern in PLACEHOLDER_PATTERNS)


def argument_question_number(value: str | None) -> int | None:
    normalized = normalized_cell(value).casefold()
    match = re.fullmatch(r"q0*([1-9][0-9]*)", normalized)
    if match:
        return int(match.group(1))
    if re.fullmatch(r"[1-9][0-9]*", normalized):
        return int(normalized)
    return None


def strip_reference_token(value: str) -> str:
    token = value.strip().strip("<>").strip().strip("`").strip("\"'")
    token = token.split("#", 1)[0].strip()
    token = token.rstrip(".,;:，；。)")
    if " " in token and not Path(token).exists():
        token = token.split(" ", 1)[0]
    return token


def reference_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    patterns = (
        r"\[[^\]]+\]\(([^)]+)\)",
        r"`([^`]+)`",
        r"<([^>]+)>",
        r"(?:(?:\.{0,2}[/\\])?(?:results|paper|01-analysis|code)[/\\][^\s,;，；)\]]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value):
            token = match.group(1) if match.groups() else match.group(0)
            cleaned = strip_reference_token(token)
            if cleaned and cleaned not in tokens:
                tokens.append(cleaned)
    return tokens


def references_path(value: str, root: Path, target: Path) -> bool:
    for token in reference_tokens(value):
        resolved = resolve_workspace_path(root, token)
        if resolved is not None and resolved == target.resolve():
            return True
        if mentions_path(token, root, target):
            return True
    return mentions_path(value, root, target)


def mentions_question(value: str, question: int) -> bool:
    return bool(re.search(rf"\bq0*{question}\b", value, re.IGNORECASE))


def evidence_ledger_has_question(root: Path, question: int) -> bool:
    ledger = root / "paper" / "evidence-ledger.md"
    if not nonempty_file(ledger):
        return False
    _, rows = markdown_table(ledger)
    manifest = manifest_rows(root)
    for row in rows:
        summary = resolve_workspace_path(root, row.get("summary_source", ""))
        repro = resolve_workspace_path(root, row.get("reproducibility_record", ""))
        manifest_match = resolve_manifest_reference(root, row.get("manifest_row", ""), manifest)
        source_questions = [
            artifact_question(root, path)
            for path in (summary, repro)
            if path is not None and nonempty_file(path)
        ]
        if manifest_match and manifest_match.get("question") is not None:
            source_questions.append(manifest_match["question"])
        if question in source_questions:
            return True
    return False


def argument_evidence_is_compatible(
    root: Path,
    question: int,
    value: str,
    race_required: bool,
    manifest: list[dict[str, Any]],
) -> bool:
    tokens = reference_tokens(value)
    if not tokens:
        return False
    for token in tokens:
        resolved = resolve_workspace_path(root, token)
        if resolved is None or not nonempty_file(resolved):
            continue
        relative = relative_workspace_path(root, resolved)
        label = f"q{question}"
        if relative in {
            f"results/{label}/summary.md",
            f"results/{label}/reproducibility.md",
        }:
            return True
        if re.fullmatch(
            rf"results/{label}/(?:diagnostics|ablation|independent-validation|uncertainty|failure-boundaries|semantic-checks)\.md",
            relative,
        ):
            return True
        if race_required and relative == f"results/{label}/scheme-comparison.md":
            return True
        if relative == "results/manifest.md" and mentions_question(value, question):
            if any(manifest_row_is_valid_for_question(root, row, question) for row in manifest):
                return True
        if relative == "paper/evidence-ledger.md" and mentions_question(value, question):
            if evidence_ledger_has_question(root, question):
                return True
    return False


def substantive_waiver(value: str) -> bool:
    text = normalized_cell(value)
    if placeholder_value(text):
        return False
    normalized = text.casefold()
    if normalized in {"waiver", "see waiver", "见 waiver", "见豁免"}:
        return False
    return len(text) >= 10


def argument_map_blockers(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    path = root / "paper" / "argument-map.md"
    requires_nonempty(path, "M3 argument map", blockers)
    if not nonempty_file(path):
        return blockers
    if (frontmatter_value(path, "status") or "").strip().lower() != "verified":
        blockers.append("M3 argument map must record status: verified")

    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != ARGUMENT_MAP_COLUMNS:
        blockers.append(
            "M3 argument map table columns must be exactly "
            + "|".join(ARGUMENT_MAP_COLUMNS)
        )
        return blockers
    if not rows:
        blockers.append("M3 argument map needs at least one data row")
        return blockers

    expected = expected_questions(root, state, registry)
    expected_set = set(expected)
    manifest = manifest_rows(root)
    specs = {
        question: spec
        for question, spec in registered_question_specs(root, state, registry or {})
    }
    seen: set[int] = set()
    for index, row in enumerate(rows, start=1):
        question = argument_question_number(row.get("question"))
        if question is None or question not in expected_set:
            blockers.append(f"M3 argument map row {index} has unknown question")
            continue
        seen.add(question)
        label = f"q{question}"

        for column in ARGUMENT_MAP_COLUMNS:
            if placeholder_value(row.get(column)):
                blockers.append(f"M3 argument map row {index} column {column} is empty or placeholder")
        if normalized_cell(row.get("verified")).casefold() != "yes":
            blockers.append(f"M3 argument map row {index} must record verified=yes")

        spec = specs.get(question, {})
        race = spec.get("race") if isinstance(spec.get("race"), dict) else {}
        race_required = bool(race.get("required"))
        evidence = row.get("evidence", "")
        if not argument_evidence_is_compatible(root, question, evidence, race_required, manifest):
            blockers.append(
                f"M3 argument map row {index} evidence must reference an existing compatible {label} source"
            )

        alternative = row.get("alternative_or_waiver", "")
        if race_required:
            if re.search(r"\bwaiver\b|豁免", alternative, re.IGNORECASE):
                blockers.append(f"M3 argument map {label}: required race cannot be written as a waiver")
            comparison = question_path(root, question) / "scheme-comparison.md"
            if not references_path(alternative, root, comparison):
                blockers.append(f"M3 argument map {label}: required race must cite scheme-comparison.md")
            winner = (frontmatter_value(comparison, "winner") or "").strip()
            chosen = (frontmatter_value(question_path(root, question) / "summary.md", "chosen_scheme") or "").strip()
            legal_names = set(candidate_names(spec.get("candidates")))
            if not winner:
                blockers.append(f"M3 argument map {label}: required race must include a comparison winner")
            elif winner not in legal_names or chosen != winner:
                blockers.append(f"M3 argument map {label}: comparison winner must match the selected registered scheme")
            elif winner.casefold() not in alternative.casefold():
                blockers.append(f"M3 argument map {label}: required race rationale must name winner {winner}")
        elif not substantive_waiver(alternative):
            blockers.append(f"M3 argument map {label}: waived question needs a substantive waiver/selection reason")

    missing = sorted(expected_set - seen)
    for question in missing:
        blockers.append(f"M3 argument map missing row for q{question}")
    return blockers


def finite_decimal(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = value.strip()
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", stripped):
        return None
    try:
        parsed = float(stripped)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_dimension_score(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not re.fullmatch(r"[+-]?\d+", stripped):
        return None
    parsed = int(stripped)
    return parsed if 0 <= parsed <= 4 else None


def normalized_dimension(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def depth_evidence_path_is_allowed(root: Path, path: Path) -> bool:
    relative = relative_workspace_path(root, path)
    if relative in {
        "01-analysis/analysis.md",
        "01-analysis/data-audit.md",
        "01-analysis/research-plan.md",
        "01-analysis/claim-evidence-matrix.md",
        "01-analysis/derivation-notes.md",
        "01-analysis/experiment-matrix.md",
        "01-analysis/model-selection.md",
        SCHEME_REGISTRY_FILE,
        "results/manifest.md",
        "paper/evidence-ledger.md",
        "paper/argument-map.md",
        "paper/paper-expansion-ledger.md",
        "paper/question-depth-matrix.md",
        "paper/revision-log.md",
        "paper/review-report.md",
    }:
        return True
    if re.fullmatch(
        r"results/q[1-9][0-9]*/(?:summary|reproducibility|scheme-comparison|diagnostics|ablation|independent-validation|uncertainty|failure-boundaries|semantic-checks)\.md",
        relative,
    ):
        return True
    sections = root / "paper" / "sections"
    return path.suffix.lower() == ".md" and path_inside(path, sections)


def depth_evidence_is_traceable(root: Path, value: str) -> bool:
    for token in reference_tokens(value):
        resolved = resolve_workspace_path(root, token)
        if (
            resolved is not None
            and nonempty_file(resolved)
            and depth_evidence_path_is_allowed(root, resolved)
        ):
            return True
    return False


JUDGE_SEATS = ("A", "B", "C")
JUDGE_TIERS = {"国一": (85.0, 70.0), "国二": (75.0, 60.0)}


def judge_panel_blockers(root: Path) -> list[str]:
    """M3 three-seat blind judge panel gate (P0-2). Verifies the machine-generated
    paper/judge-panel.md is internally consistent with a pass verdict."""
    blockers: list[str] = []
    panel = root / "paper" / "judge-panel.md"
    requires_nonempty(panel, "M3 judge panel", blockers)
    for seat in JUDGE_SEATS:
        card = root / "paper" / f"judge-scorecard-{seat}.md"
        requires_nonempty(card, f"M3 judge scorecard {seat}", blockers)
    if not nonempty_file(panel):
        return blockers

    fields = parse_frontmatter(panel)
    if (fields.get("verdict") or "").strip().lower() != "pass":
        blockers.append("M3 judge panel must record verdict: pass")
    target = (fields.get("target_tier") or "").strip()
    if target not in JUDGE_TIERS:
        blockers.append("M3 judge panel target_tier must be 国一 or 国二")
    conflicts = (fields.get("conflicts") or "").strip()
    if not re.fullmatch(r"[+-]?\d+", conflicts):
        blockers.append("M3 judge panel conflicts must be an integer")
    elif int(conflicts) != 0:
        blockers.append("M3 judge panel must resolve all cross-seat conflicts (conflicts: 0)")
    min_total = finite_decimal(fields.get("min_weighted_total"))
    low_crit = finite_decimal(fields.get("lowest_criterion_score"))
    if target in JUDGE_TIERS:
        pass_total, floor = JUDGE_TIERS[target]
        if min_total is None:
            blockers.append("M3 judge panel min_weighted_total must be numeric")
        elif min_total < pass_total:
            blockers.append(
                f"M3 judge panel min_weighted_total must be >= {pass_total:g} for {target}"
            )
        if low_crit is None:
            blockers.append("M3 judge panel lowest_criterion_score must be numeric")
        elif low_crit < floor:
            blockers.append(
                f"M3 judge panel lowest_criterion_score must be >= {floor:g} for {target}"
            )
    return blockers


def depth_audit_blockers(root: Path) -> list[str]:
    blockers: list[str] = []
    path = root / "paper" / "depth-audit.md"
    requires_nonempty(path, "M3 depth audit", blockers)
    if not nonempty_file(path):
        return blockers

    fields = parse_frontmatter(path)
    if (fields.get("status") or "").strip().lower() != "pass":
        blockers.append("M3 depth audit must record status: pass")
    total_value = finite_decimal(fields.get("total_score"))
    min_value = finite_decimal(fields.get("min_dimension_score"))
    if total_value is None:
        blockers.append("M3 depth audit total_score must be numeric")
    if min_value is None:
        blockers.append("M3 depth audit min_dimension_score must be numeric")
    p0_value = (fields.get("p0_count") or "").strip()
    if not re.fullmatch(r"[+-]?\d+", p0_value):
        blockers.append("M3 depth audit p0_count must be integer 0")
    elif int(p0_value) != 0:
        blockers.append("M3 depth audit p0_count must be 0")

    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != DEPTH_AUDIT_COLUMNS:
        blockers.append(
            "M3 depth audit table columns must be exactly "
            + "|".join(DEPTH_AUDIT_COLUMNS)
        )
        return blockers
    if not rows:
        blockers.append("M3 depth audit needs nine dimension rows")
        return blockers

    expected_dimensions = set(DEPTH_DIMENSIONS)
    scores: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        dimension = normalized_dimension(row.get("dimension"))
        if dimension not in expected_dimensions:
            blockers.append(f"M3 depth audit row {index} has unknown dimension")
            continue
        if dimension in scores:
            blockers.append(f"M3 depth audit duplicate dimension: {dimension}")
            continue
        score = parse_dimension_score(row.get("score"))
        if score is None:
            blockers.append(f"M3 depth audit {dimension} score must be an integer 0..4")
            continue
        scores[dimension] = score
        evidence = row.get("evidence")
        if placeholder_value(evidence):
            blockers.append(f"M3 depth audit {dimension} evidence is empty or placeholder")
        elif not depth_evidence_is_traceable(root, evidence or ""):
            blockers.append(
                f"M3 depth audit {dimension} evidence must reference an existing "
                "allowed workspace evidence artifact"
            )
        if placeholder_value(row.get("gap"), allow_explicit_none=True):
            blockers.append(f"M3 depth audit {dimension} gap is empty or placeholder")

    for dimension in DEPTH_DIMENSIONS:
        if dimension not in scores:
            blockers.append(f"M3 depth audit missing dimension: {dimension}")
    if len(scores) != len(DEPTH_DIMENSIONS):
        return blockers

    total = sum(scores.values())
    minimum = min(scores.values())
    if total_value is not None and total_value != total:
        blockers.append("M3 depth audit total_score must equal table score sum")
    if min_value is not None and min_value != minimum:
        blockers.append("M3 depth audit min_dimension_score must equal table minimum")
    if total < 30:
        blockers.append("M3 depth audit total_score threshold is 30")
    if minimum < 3:
        blockers.append("M3 depth audit min_dimension_score threshold is 3")
    for dimension in DEPTH_KEY_DIMENSIONS:
        if scores[dimension] < 3:
            blockers.append(f"M3 depth audit key dimension {dimension} must score >=3")
    return blockers


def evidence_ledger_blockers(root: Path, ledger: Path) -> list[str]:
    blockers: list[str] = []
    for field in ("reviewed_package", "verified_at", "verified_by"):
        if not non_none_value(frontmatter_value(ledger, field)):
            blockers.append(f"M3 evidence ledger frontmatter must include nonempty {field}")
    package_value = frontmatter_value(ledger, "reviewed_package")
    package = resolve_workspace_path(root, package_value) if package_value else None
    final_dir = root / "paper" / "final"
    if (
        package is None
        or not path_inside(package, final_dir)
        or not valid_paper_artifact(package, allow_tex=False)
    ):
        blockers.append(
            "M3 evidence ledger reviewed_package must point to an existing valid final PDF/DOCX"
        )
    header, rows = markdown_table(ledger)
    if tuple(header) != LEDGER_COLUMNS:
        blockers.append(
            "M3 evidence ledger table columns must be exactly "
            + "|".join(LEDGER_COLUMNS)
        )
        return blockers
    if not rows:
        blockers.append("M3 evidence ledger needs at least one data row")
        return blockers
    manifest = manifest_rows(root)
    for index, row in enumerate(rows, start=1):
        if row.get("verified") != "yes":
            blockers.append(f"M3 evidence ledger row {index} must record verified=yes")
        manifest_reference = row.get("manifest_row", "")
        manifest_match = None
        if not manifest_reference:
            blockers.append(f"M3 evidence ledger row {index} must include manifest_row")
        else:
            manifest_match = resolve_manifest_reference(root, manifest_reference, manifest)
            if manifest_match is None:
                blockers.append(
                    f"M3 evidence ledger row {index} manifest_row must match a results/manifest.md "
                    "label or artifact path"
                )
        summary = resolve_workspace_path(root, row.get("summary_source", ""))
        summary_question = None
        if not summary or not nonempty_file(summary) or summary.name != "summary.md":
            blockers.append(f"M3 evidence ledger row {index} has invalid summary_source")
        else:
            summary_question = artifact_question(root, summary)
        if summary is not None and nonempty_file(summary) and summary.name == "summary.md" and summary_question is None:
            blockers.append(f"M3 evidence ledger row {index} summary_source must be under results/qN/")
        repro = resolve_workspace_path(root, row.get("reproducibility_record", ""))
        repro_question = None
        if not repro or not nonempty_file(repro) or repro.name != "reproducibility.md":
            blockers.append(f"M3 evidence ledger row {index} has invalid reproducibility_record")
        else:
            repro_question = artifact_question(root, repro)
        if repro is not None and nonempty_file(repro) and repro.name == "reproducibility.md" and repro_question is None:
            blockers.append(
                f"M3 evidence ledger row {index} reproducibility_record must be under results/qN/"
            )
        manifest_question = manifest_match.get("question") if manifest_match else None
        if manifest_match and manifest_question is None:
            blockers.append(f"M3 evidence ledger row {index} manifest artifact must be under results/qN/")
        if (
            manifest_question is not None
            and summary_question is not None
            and summary_question != manifest_question
        ):
            blockers.append(
                f"M3 evidence ledger row {index} summary_source q does not match manifest artifact q"
            )
        if (
            manifest_question is not None
            and repro_question is not None
            and repro_question != manifest_question
        ):
            blockers.append(
                f"M3 evidence ledger row {index} reproducibility_record q does not match manifest artifact q"
            )
    return blockers


def non_none_value(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().strip('"\'').lower()
    return bool(normalized) and normalized not in {"none", "null", "n/a", "na"}


def question_evidence_reference_is_valid(
    root: Path,
    question: int,
    value: str,
    report: Path,
) -> bool:
    question_dir = question_path(root, question)
    for token in reference_tokens(value):
        resolved = resolve_workspace_path(root, token)
        if resolved is None or resolved == report.resolve() or not nonempty_file(resolved):
            continue
        if path_inside(resolved, question_dir):
            return True
        if producer_script_matches_question(root, resolved, question):
            return True
        if resolved == (root / "results" / "manifest.md").resolve() and mentions_question(value, question):
            return True
    return False


def independent_validation_blockers(
    root: Path,
    question: int,
    report: Path,
    rows: list[dict[str, str]],
) -> list[str]:
    blockers: list[str] = []
    label = f"q{question}"
    kind = (frontmatter_value(report, "validation_kind") or "").strip().casefold()
    kind = kind.replace("_", "-")
    if kind not in INDEPENDENT_VALIDATION_KINDS:
        blockers.append(
            f"M2 {label} independent-validation.md validation_kind must be one of: "
            + ", ".join(sorted(INDEPENDENT_VALIDATION_KINDS))
        )

    basis = frontmatter_value(report, "independence_basis") or ""
    if placeholder_value(basis) or len(re.sub(r"\s+", "", basis)) < 20:
        blockers.append(
            f"M2 {label} independent-validation.md needs a substantive independence_basis"
        )

    artifact_value = frontmatter_value(report, "validation_artifact") or ""
    artifact = resolve_workspace_path(root, artifact_value)
    if artifact is None or not nonempty_file(artifact):
        blockers.append(
            f"M2 {label} independent-validation.md validation_artifact must reference "
            "an existing workspace file"
        )
        return blockers

    excluded_names = {
        "summary.md",
        "reproducibility.md",
        "scheme-comparison.md",
        "manifest-fragment.md",
        *M2_EVIDENCE_FILES,
    }
    if artifact.resolve() == report.resolve() or artifact.name.casefold() in excluded_names:
        blockers.append(
            f"M2 {label} independent-validation.md validation_artifact must be dedicated "
            "validation evidence, not a primary report"
        )

    primary_script = reproducibility_script(
        root,
        question_path(root, question) / "reproducibility.md",
    )
    is_question_script = producer_script_matches_question(root, artifact, question)
    if primary_script is not None and artifact.resolve() == primary_script.resolve():
        blockers.append(
            f"M2 {label} independent validation must be distinct from the primary "
            "reproducibility script"
        )

    if kind == "alternative-implementation":
        if not is_question_script:
            blockers.append(
                f"M2 {label} alternative-implementation validation_artifact must be a "
                "separate q-specific producer script"
            )
    else:
        allowed_location = (
            path_inside(artifact, question_path(root, question))
            or path_inside(artifact, root / "data")
            or is_question_script
        )
        if not allowed_location:
            blockers.append(
                f"M2 {label} independent validation artifact must belong to q{question}, "
                "data/, or a q-specific validation script"
            )
        normalized_path = relative_workspace_path(root, artifact).casefold()
        if not any(hint in normalized_path for hint in INDEPENDENT_VALIDATION_ARTIFACT_HINTS):
            blockers.append(
                f"M2 {label} validation_artifact path must identify its independent "
                "validation role"
            )

    if rows and not any(
        references_path(row.get("evidence", ""), root, artifact)
        for row in rows
    ):
        blockers.append(
            f"M2 {label} independent-validation.md evidence must cite validation_artifact"
        )
    return blockers


def m2_evidence_report_blockers(root: Path, question: int, filename: str) -> list[str]:
    blockers: list[str] = []
    label = f"q{question}"
    report = question_path(root, question) / filename
    requires_nonempty(report, f"M2 {label} {filename}", blockers)
    if not nonempty_file(report):
        return blockers
    requires_unique_frontmatter(report, f"M2 {label} {filename}", blockers)

    recorded_question = (frontmatter_value(report, "question") or "").strip().casefold()
    if recorded_question != label:
        blockers.append(f"M2 {label} {filename} must record question: {label}")
    status = (frontmatter_value(report, "status") or "").strip().casefold()
    if filename == "ablation.md" and status == "waived":
        reason = frontmatter_value(report, "waiver_reason") or ""
        if len(normalized_cell(reason)) < 20 or placeholder_value(reason):
            blockers.append(f"M2 {label} ablation waiver needs a substantive waiver_reason")
        return blockers
    if status != "verified":
        blockers.append(f"M2 {label} {filename} must record status: verified")

    headers, rows = markdown_table_raw(report)
    if normalized_table_header(headers) != M2_EVIDENCE_COLUMNS:
        blockers.append(
            f"M2 {label} {filename} table columns must be exactly "
            + "|".join(M2_EVIDENCE_COLUMNS)
        )
        return blockers
    minimum_rows = {
        "diagnostics.md": 3,
        "ablation.md": 1,
        "independent-validation.md": 1,
        "uncertainty.md": 2,
        "failure-boundaries.md": 2,
        "semantic-checks.md": 3,
    }[filename]
    if len(rows) < minimum_rows:
        blockers.append(f"M2 {label} {filename} needs at least {minimum_rows} substantive rows")
    for index, row in enumerate(rows, start=1):
        for column in M2_EVIDENCE_COLUMNS:
            if placeholder_value(row.get(column)):
                blockers.append(
                    f"M2 {label} {filename} row {index} column {column} is empty or placeholder"
                )
        if normalized_cell(row.get("verified")).casefold() != "yes":
            blockers.append(f"M2 {label} {filename} row {index} must record verified=yes")
        evidence = row.get("evidence", "")
        if not question_evidence_reference_is_valid(root, question, evidence, report):
            blockers.append(
                f"M2 {label} {filename} row {index} evidence must reference an existing "
                f"{label} artifact or producer script"
            )
    if filename == "independent-validation.md":
        blockers.extend(independent_validation_blockers(root, question, report, rows))
    return blockers


def m2_research_contract_blockers(root: Path, question: int) -> list[str]:
    blockers: list[str] = []
    for filename in M2_EVIDENCE_FILES:
        blockers.extend(m2_evidence_report_blockers(root, question, filename))
    return blockers


def check_code(root: Path, state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    code_dir = root / "code"
    code_files = [
        path for path in code_dir.iterdir()
        if path.is_file() and path.suffix.lower() in PRODUCER_SCRIPT_SUFFIXES and nonempty_file(path)
    ] if code_dir.is_dir() else []

    registry: dict[str, Any] | None = None
    if is_managed(state):
        blockers.extend(check_modeling(root, state))
        registry, _ = load_scheme_registry(root)

    questions = expected_questions(root, state, registry)
    if not questions:
        blockers.append(
            "P3: no expected questions found (set subquestions or create results/q*/)"
        )

    manifest_path = root / "results" / "manifest.md"
    requires_nonempty(manifest_path, "results manifest", blockers)
    rows = manifest_rows(root) if nonempty_file(manifest_path) else []
    if nonempty_file(manifest_path) and not rows:
        blockers.append("P3/P4: results/manifest.md has no artifact rows")
    if is_managed(state):
        blockers.extend(managed_manifest_blockers(root, questions))

    for question in questions:
        label = f"q{question}"
        question_dir = question_path(root, question)
        summary = question_dir / "summary.md"
        if not nonempty_file(summary):
            blockers.append(f"P3 {label}: missing non-empty results/{label}/summary.md")
        else:
            requires_unique_frontmatter(summary, f"P3 {label} summary", blockers)
            if (frontmatter_value(summary, "status") or "").strip().lower() != "solved":
                blockers.append(f"P3 {label}: summary must record status: solved")
            if not non_none_value(frontmatter_value(summary, "robustness")):
                blockers.append(f"P4 {label}: summary must record non-none robustness")

        question_scripts = [
            path for path in code_files
            if producer_script_matches_question(root, path, question)
        ]
        if not question_scripts:
            blockers.append(f"P3 {label}: missing non-empty matching script in code/")

        if is_managed(state):
            reproducibility = question_dir / "reproducibility.md"
            if not nonempty_file(reproducibility):
                blockers.append(f"P3/P4 {label}: missing non-empty results/{label}/reproducibility.md")
            else:
                requires_unique_frontmatter(
                    reproducibility,
                    f"P3/P4 {label} reproducibility",
                    blockers,
                )
                if not reproducibility_report_is_valid(
                    root,
                    reproducibility,
                    question,
                    valid_manifest_artifacts_for_question(root, rows, question),
                ):
                    blockers.append(
                        f"P3/P4 {label}: reproducibility.md must record question={label}, "
                        "script under code/ matching the question, exit_code=0, command, "
                        "outputs covering summary/figure-or-table/manifest artifact, checked_at, and checked_by"
                    )
            blockers.extend(m2_research_contract_blockers(root, question))

        comparison = question_dir / "scheme-comparison.md"
        if is_managed(state) and nonempty_file(comparison):
            requires_unique_frontmatter(
                comparison,
                f"M2 {label} scheme comparison",
                blockers,
            )

        if not valid_figure_pairs(question_dir):
            blockers.append(
                f"P3 {label}: missing readable PNG/PDF figure pair in results/{label}/figs/"
            )

        if rows and not any(manifest_row_is_valid_for_question(root, row, question) for row in rows):
            blockers.append(
                f"P3/P4 {label}: results/manifest.md needs a row with an existing "
                f"results/{label}/ artifact and existing producer script"
            )
    if is_managed(state) and registry is not None:
        for question, spec in registered_question_specs(root, state, registry):
            blockers.extend(scheme_race_blockers(root, question, spec))
    return blockers


def draft_artifacts(root: Path) -> list[Path]:
    paper = root / "paper"
    artifacts: list[Path] = []
    for base, patterns in (
        (paper, ("*.docx", "*.pdf", "*.tex")),
        (paper / "word", ("*.docx", "*.pdf")),
        (paper / "latex", ("*.tex", "*.pdf")),
    ):
        for pattern in patterns:
            artifacts.extend(matches(base, pattern))
    return artifacts


def has_assembled_draft(root: Path, managed: bool) -> bool:
    artifacts = draft_artifacts(root)
    if not managed:
        return bool(artifacts)
    return any(valid_paper_artifact(path, allow_tex=True) for path in artifacts)


def final_artifacts(root: Path) -> list[Path]:
    final_dir = root / "paper" / "final"
    return matches(final_dir, "*.pdf") + matches(final_dir, "*.docx")


def has_final_package(root: Path, managed: bool) -> bool:
    artifacts = final_artifacts(root)
    if not managed:
        return bool(artifacts)
    return any(
        valid_paper_artifact(path, allow_tex=False)
        for path in artifacts
    )


def question_section_path(root: Path, question: int, section_type: str) -> Path:
    suffix = QUESTION_SECTION_SUFFIXES[section_type]
    return root / "paper" / "sections" / f"q{question}-{suffix}.md"


def heading_present(text: str, heading: str) -> bool:
    escaped = re.escape(heading)
    return bool(
        re.search(rf"^#{{1,6}}\s+[^\n]*{escaped}", text, re.MULTILINE)
        or re.search(rf"^\*\*[^\n*]*{escaped}[^\n*]*\*\*\s*$", text, re.MULTILINE)
    )


def paper_structure_blockers(root: Path, questions: list[int]) -> list[str]:
    blockers: list[str] = []
    sections = root / "paper" / "sections"
    required_headings = {
        "01-problem-analysis.md": ("问题背景与重述", "问题分析"),
        "02-assumptions-symbols.md": ("模型假设", "符号说明"),
        "03-modeling-and-solution.md": ("模型的建立与求解",),
        "07-model-evaluation.md": ("模型评价",),
        "08-conclusion.md": ("结论",),
    }
    for filename, headings in required_headings.items():
        path = sections / filename
        requires_nonempty(path, f"M3 standard paper structure {filename}", blockers)
        if not nonempty_file(path):
            continue
        text = read_text(path)
        for heading in headings:
            if not re.search(rf"^#\s+[^\n]*{re.escape(heading)}", text, re.MULTILINE):
                blockers.append(
                    f"M3 standard paper structure {filename} needs level-1 heading: {heading}"
                )

    for question in questions:
        process = question_section_path(root, question, "modeling_process")
        results = question_section_path(root, question, "results_interpretation")
        argument = question_section_path(root, question, "model_argumentation")
        if nonempty_file(process):
            text = read_text(process)
            if re.search(r"^#\s+", text, re.MULTILINE):
                blockers.append(f"M3 q{question} must not be a level-1 chapter")
            if not re.search(r"^##\s+问题", text, re.MULTILINE):
                blockers.append(f"M3 q{question} needs a level-2 problem heading")
            if not re.search(r"^###\s+", text, re.MULTILINE):
                blockers.append(f"M3 q{question} modeling process needs a level-3 heading")
        for path, label in ((results, "results"), (argument, "argumentation")):
            if not nonempty_file(path):
                continue
            text = read_text(path)
            if re.search(r"^#{1,2}\s+", text, re.MULTILINE):
                blockers.append(
                    f"M3 q{question} {label} must stay under the level-2 problem heading"
                )
            if not re.search(r"^###\s+", text, re.MULTILINE):
                blockers.append(f"M3 q{question} {label} needs a level-3 heading")
    return blockers


def figure_explanation_blockers(text: str, label: str) -> list[str]:
    blockers: list[str] = []
    for index, match in enumerate(MARKDOWN_FIGURE_RE.finditer(text), start=1):
        caption = match.group("caption").strip()
        normalized_caption = re.sub(r"[`*_#$\\{}\s]", "", caption).casefold()
        if len(normalized_caption) < 8 or normalized_caption in GENERIC_FIGURE_CAPTIONS:
            blockers.append(
                f"M3 {label} figure {index} needs a specific explanatory caption"
            )

        following_block = ""
        for block in re.split(r"\n\s*\n", text[match.end():]):
            if block.strip():
                following_block = block.strip()
                break
        if (
            not following_block
            or following_block.startswith("#")
            or following_block.startswith("![")
            or following_block.startswith("|")
            or following_block.startswith("```")
        ):
            blockers.append(
                f"M3 {label} figure {index} needs an immediate interpretation paragraph"
            )
            continue
        normalized_explanation = re.sub(
            r"[`*_>#\[\](){}$\\]", "", following_block
        )
        normalized_explanation = re.sub(r"\s+", "", normalized_explanation)
        if len(normalized_explanation) < 60:
            blockers.append(
                f"M3 {label} figure {index} interpretation needs at least 60 substantive characters"
            )
    return blockers


def substantive_paragraphs(text: str) -> set[str]:
    paragraphs: set[str] = set()
    for block in re.split(r"\n\s*\n", text):
        stripped = block.strip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("```")
        ):
            continue
        normalized = re.sub(r"[`*_>#\[\](){}$\\]", "", stripped)
        normalized = re.sub(r"\s+", "", normalized).casefold()
        if len(normalized) >= 120:
            paragraphs.add(normalized)
    return paragraphs


def question_section_blockers(root: Path, question: int) -> list[str]:
    blockers: list[str] = []
    label = f"q{question}"
    texts: dict[str, str] = {}
    for section_type in QUESTION_SECTION_SUFFIXES:
        path = question_section_path(root, question, section_type)
        requires_nonempty(path, f"M3 {label} {section_type} section", blockers)
        if not nonempty_file(path):
            continue
        text = read_text(path)
        texts[section_type] = text
        character_count = len(re.sub(r"\s+", "", text))
        minimum = QUESTION_SECTION_MIN_CHARS[section_type]
        if character_count < minimum:
            blockers.append(
                f"M3 {label} {section_type} section needs at least {minimum} non-whitespace characters"
            )
        for heading in QUESTION_SECTION_HEADINGS[section_type]:
            if not heading_present(text, heading):
                blockers.append(
                    f"M3 {label} {section_type} section missing heading anchor: {heading}"
                )
        blockers.extend(
            figure_explanation_blockers(text, f"{label} {section_type} section")
        )

    forbidden_headings = {
        "modeling_process": QUESTION_SECTION_HEADINGS["model_argumentation"],
        "results_interpretation": (
            "模型建立与推导",
            "求解流程",
            "模型诊断",
            "独立验证",
        ),
        "model_argumentation": ("模型建立与推导", "求解流程", "核心结果"),
    }
    for section_type, headings in forbidden_headings.items():
        text = texts.get(section_type, "")
        for heading in headings:
            if heading_present(text, heading):
                blockers.append(
                    f"M3 {label} {section_type} section must not absorb the separate heading: {heading}"
                )

    paragraph_sets = {
        section_type: substantive_paragraphs(text)
        for section_type, text in texts.items()
    }
    section_types = list(paragraph_sets)
    for left_index, left in enumerate(section_types):
        for right in section_types[left_index + 1:]:
            if paragraph_sets[left] & paragraph_sets[right]:
                blockers.append(
                    f"M3 {label} sections {left} and {right} contain repeated substantive paragraphs"
                )
    return blockers


def paper_source_reference_is_valid(
    root: Path,
    question: int,
    section_type: str,
    value: str,
) -> bool:
    label = f"q{question}"
    for token in reference_tokens(value):
        resolved = resolve_workspace_path(root, token)
        if resolved is None or not nonempty_file(resolved):
            continue
        relative = relative_workspace_path(root, resolved)
        if section_type == "modeling_process" and relative in {
            "01-analysis/analysis.md",
            "01-analysis/research-plan.md",
            "01-analysis/derivation-notes.md",
            SCHEME_REGISTRY_FILE,
        }:
            return True
        if section_type == "results_interpretation" and relative in {
            f"results/{label}/summary.md",
            "results/manifest.md",
        }:
            return True
        if section_type == "model_argumentation" and re.fullmatch(
            rf"results/{label}/(?:scheme-comparison|diagnostics|ablation|independent-validation|uncertainty|failure-boundaries|semantic-checks)\.md",
            relative,
        ):
            return True
    return False


def paper_expansion_ledger_blockers(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    path = root / "paper" / "paper-expansion-ledger.md"
    requires_nonempty(path, "M3 paper expansion ledger", blockers)
    if not nonempty_file(path):
        return blockers
    requires_unique_frontmatter(path, "M3 paper expansion ledger", blockers)
    if (frontmatter_value(path, "status") or "").strip().casefold() != "verified":
        blockers.append("M3 paper expansion ledger must record status: verified")
    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != EXPANSION_LEDGER_COLUMNS:
        blockers.append(
            "M3 paper expansion ledger table columns must be exactly "
            + "|".join(EXPANSION_LEDGER_COLUMNS)
        )
        return blockers

    expected = set(expected_questions(root, state, registry))
    seen: set[tuple[int, str]] = set()
    for index, row in enumerate(rows, start=1):
        for column in EXPANSION_LEDGER_COLUMNS:
            if placeholder_value(row.get(column)):
                blockers.append(
                    f"M3 paper expansion ledger row {index} column {column} is empty or placeholder"
                )
        question = argument_question_number(row.get("question"))
        section_type = normalized_cell(row.get("section_type")).casefold()
        if question is None or question not in expected:
            blockers.append(f"M3 paper expansion ledger row {index} has unknown question")
            continue
        if section_type not in QUESTION_SECTION_SUFFIXES:
            blockers.append(f"M3 paper expansion ledger row {index} has unknown section_type")
            continue
        key = (question, section_type)
        if key in seen:
            blockers.append(
                f"M3 paper expansion ledger duplicates q{question} section_type {section_type}"
            )
        seen.add(key)
        target_pages = finite_decimal(row.get("target_pages"))
        if target_pages is None or target_pages <= 0:
            blockers.append(f"M3 paper expansion ledger row {index} target_pages must be positive")
        if normalized_cell(row.get("verified")).casefold() != "yes":
            blockers.append(f"M3 paper expansion ledger row {index} must record verified=yes")
        if not paper_source_reference_is_valid(
            root,
            question,
            section_type,
            row.get("source_artifacts", ""),
        ):
            blockers.append(
                f"M3 paper expansion ledger row {index} source_artifacts must reference a "
                f"compatible q{question} source"
            )
    for question in sorted(expected):
        for section_type in QUESTION_SECTION_SUFFIXES:
            if (question, section_type) not in seen:
                blockers.append(
                    f"M3 paper expansion ledger missing q{question} section_type {section_type}"
                )
    return blockers


def question_depth_matrix_blockers(
    root: Path,
    state: dict[str, Any],
    registry: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    path = root / "paper" / "question-depth-matrix.md"
    requires_nonempty(path, "M3 question depth matrix", blockers)
    if not nonempty_file(path):
        return blockers
    requires_unique_frontmatter(path, "M3 question depth matrix", blockers)
    if (frontmatter_value(path, "status") or "").strip().casefold() != "verified":
        blockers.append("M3 question depth matrix must record status: verified")
    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != QUESTION_DEPTH_COLUMNS:
        blockers.append(
            "M3 question depth matrix table columns must be exactly "
            + "|".join(QUESTION_DEPTH_COLUMNS)
        )
        return blockers

    expected = set(expected_questions(root, state, registry))
    seen: set[int] = set()
    evidence_targets = {
        "modeling_process": "modeling_process",
        "results_interpretation": "results_interpretation",
        "model_argumentation": "model_argumentation",
        "independent_validation": "independent-validation.md",
        "uncertainty": "uncertainty.md",
        "failure_boundary": "failure-boundaries.md",
    }
    for index, row in enumerate(rows, start=1):
        for column in QUESTION_DEPTH_COLUMNS:
            if placeholder_value(row.get(column)):
                blockers.append(
                    f"M3 question depth matrix row {index} column {column} is empty or placeholder"
                )
        question = argument_question_number(row.get("question"))
        if question is None or question not in expected:
            blockers.append(f"M3 question depth matrix row {index} has unknown question")
            continue
        if question in seen:
            blockers.append(f"M3 question depth matrix duplicates q{question}")
        seen.add(question)
        for column, target in evidence_targets.items():
            if target in QUESTION_SECTION_SUFFIXES:
                expected_path = question_section_path(root, question, target)
            else:
                expected_path = question_path(root, question) / target
            if not references_path(row.get(column, ""), root, expected_path):
                blockers.append(
                    f"M3 question depth matrix q{question} {column} must cite "
                    f"{relative_workspace_path(root, expected_path)}"
                )
        if normalized_cell(row.get("verified")).casefold() != "yes":
            blockers.append(f"M3 question depth matrix q{question} must record verified=yes")
    for question in sorted(expected - seen):
        blockers.append(f"M3 question depth matrix missing row for q{question}")
    return blockers


def revision_log_blockers(root: Path) -> list[str]:
    blockers: list[str] = []
    path = root / "paper" / "revision-log.md"
    requires_nonempty(path, "M3 revision log", blockers)
    if not nonempty_file(path):
        return blockers
    requires_unique_frontmatter(path, "M3 revision log", blockers)
    if (frontmatter_value(path, "status") or "").strip().casefold() != "closed":
        blockers.append("M3 revision log must record status: closed")
    headers, rows = markdown_table_raw(path)
    if normalized_table_header(headers) != REVISION_LOG_COLUMNS:
        blockers.append(
            "M3 revision log table columns must be exactly " + "|".join(REVISION_LOG_COLUMNS)
        )
        return blockers
    rounds: list[int] = []
    for index, row in enumerate(rows, start=1):
        for column in REVISION_LOG_COLUMNS:
            if placeholder_value(row.get(column)):
                blockers.append(f"M3 revision log row {index} column {column} is empty or placeholder")
        value = normalized_cell(row.get("round"))
        if not re.fullmatch(r"[1-9][0-9]*", value):
            blockers.append(f"M3 revision log row {index} round must be a positive integer")
        else:
            rounds.append(int(value))
    if len(set(rounds)) < 2 or not {1, 2}.issubset(set(rounds)):
        blockers.append("M3 revision log must include independent review rounds 1 and 2")
    if rows and normalized_cell(rows[-1].get("status")).casefold() != "pass":
        blockers.append("M3 revision log final row must record status=pass")
    return blockers


def compliance_page_blockers(path: Path) -> list[str]:
    blockers: list[str] = []
    body_pages = finite_decimal(frontmatter_value(path, "body_pages"))
    appendix_pages = finite_decimal(frontmatter_value(path, "appendix_pages"))
    if body_pages is None or body_pages < 25 or not body_pages.is_integer():
        blockers.append("P7 compliance report body_pages must be an integer >=25")
    if appendix_pages is None or appendix_pages < 0 or not appendix_pages.is_integer():
        blockers.append("P7 compliance report appendix_pages must be a nonnegative integer")
    if (frontmatter_value(path, "page_rule_checked") or "").strip().casefold() != "true":
        blockers.append("P7 compliance report must record page_rule_checked: true")
    if not non_none_value(frontmatter_value(path, "body_page_target")):
        blockers.append("P7 compliance report must record nonempty body_page_target")
    return blockers


def check_paper(root: Path, state: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    managed = is_managed(state)
    registry: dict[str, Any] | None = None
    if managed:
        blockers.extend(check_code(root, state))
        registry, _ = load_scheme_registry(root)

    sections = root / "paper" / "sections"
    if not matches(sections, "*.md"):
        blockers.append("P5: missing non-empty paper/sections/*.md")
    if not has_assembled_draft(root, managed):
        if managed:
            blockers.append(
                "P5: missing valid assembled draft (PDF magic, DOCX OOXML, or TeX document marker)"
            )
        else:
            blockers.append("P5: missing assembled draft (.docx in paper/word or .tex in paper/latex)")

    if managed:
        ledger = root / "paper" / "evidence-ledger.md"
        argument_map = root / "paper" / "argument-map.md"
        depth_audit = root / "paper" / "depth-audit.md"
        requires_nonempty(ledger, "M3 evidence ledger", blockers)
        requires_unique_frontmatter(ledger, "M3 evidence ledger", blockers)
        requires_unique_frontmatter(argument_map, "M3 argument map", blockers)
        requires_unique_frontmatter(depth_audit, "M3 depth audit", blockers)
        requires_frontmatter_value(
            ledger,
            "status",
            "verified",
            "M3 evidence ledger must record status: verified",
            blockers,
        )
        if nonempty_file(ledger):
            blockers.extend(evidence_ledger_blockers(root, ledger))
        blockers.extend(argument_map_blockers(root, state, registry))
        blockers.extend(depth_audit_blockers(root))
        blockers.extend(judge_panel_blockers(root))
        blockers.extend(paper_expansion_ledger_blockers(root, state, registry))
        blockers.extend(question_depth_matrix_blockers(root, state, registry))
        blockers.extend(revision_log_blockers(root))

        questions = expected_questions(root, state, registry)
        blockers.extend(paper_structure_blockers(root, questions))
        for question in questions:
            label = f"q{question}"
            question_dir = question_path(root, question)
            summary = question_dir / "summary.md"
            comparison = question_dir / "scheme-comparison.md"
            requires_unique_frontmatter(summary, f"M3 source {label} summary", blockers)
            requires_unique_frontmatter(
                comparison,
                f"M3 source {label} scheme comparison",
                blockers,
            )
            blockers.extend(question_section_blockers(root, question))

    review = root / "paper" / "review-report.md"
    requires_nonempty(review, "P6 review report", blockers)
    requires_unique_frontmatter(review, "P6 review report", blockers)
    requires_frontmatter_value(
        review,
        "p0_count",
        "0",
        "P6 review report must record p0_count: 0",
        blockers,
    )
    if managed and nonempty_file(review):
        review_round = finite_decimal(frontmatter_value(review, "round"))
        if review_round is None or review_round < 2 or not review_round.is_integer():
            blockers.append("P6 review report round must be an integer >=2")
    requires_frontmatter_value(
        review,
        "verdict",
        "pass",
        "P6 review report must record verdict: pass",
        blockers,
    )

    final_dir = root / "paper" / "final"
    compliance = final_dir / "compliance-report.md"
    requires_nonempty(compliance, "P7 compliance report", blockers)
    requires_unique_frontmatter(compliance, "P7 compliance report", blockers)
    requires_frontmatter_value(
        compliance,
        "status",
        "pass",
        "P7 compliance report must record status: pass",
        blockers,
    )
    if managed and nonempty_file(compliance):
        blockers.extend(compliance_page_blockers(compliance))
    if not has_final_package(root, managed):
        if managed:
            blockers.append("P7: paper/final/ needs a valid PDF (%PDF-) or DOCX (OOXML)")
        else:
            blockers.append("P7: paper/final/ needs a non-empty PDF or DOCX")
    if managed:
        if not has_confirmation(state, "abstract"):
            blockers.append("M3 paper requires recorded abstract confirmation")
        if not has_confirmation(state, "paper"):
            blockers.append("M3 paper requires recorded final paper confirmation")
    return blockers


CHECKERS = {
    "modeling": check_modeling,
    "code": check_code,
    "paper": check_paper,
}


def check_stage(root: Path, state: dict[str, Any], stage: str) -> list[str]:
    return CHECKERS[stage](root, state)


def record_check(state: dict[str, Any], stage: str, blockers: list[str]) -> None:
    stage_state = state["stages"][stage]
    stage_state["blockers"] = blockers
    stage_state["last_checked_at"] = utc_now()


def print_check(stage: str, blockers: list[str]) -> None:
    if not blockers:
        print(f"[PASS] {stage} artifact gate")
        return
    print(f"[BLOCKED] {stage} artifact gate ({len(blockers)} issue(s))")
    for blocker in blockers:
        print(f"  - {blocker}")


def command_status(root: Path, state: dict[str, Any]) -> int:
    current = state["current_stage"]
    print(f"Workspace: {root}")
    print(f"Current stage: {current or 'complete'}")
    if is_managed(state):
        for stage in CONFIRMATION_STAGES:
            confirmation = state["confirmations"][stage]
            when = confirmation.get("confirmed_at") or "not recorded"
            status = "confirmed" if confirmation.get("confirmed") else "missing"
            print(f"  confirmation {stage}: {status} ({when})")
    for stage in STAGES:
        marker = " <- current" if stage == current else ""
        print(f"  {stage}: {state['stages'][stage]['status']}{marker}")
        blockers = state["stages"][stage].get("blockers", [])
        if blockers:
            print(f"    blockers ({len(blockers)}):")
            for blocker in blockers:
                print(f"      - {blocker}")
    if current is None:
        print("[PASS] all workflow stages are completed")
    return 0


def require_current(state: dict[str, Any], stage: str) -> None:
    current = state["current_stage"]
    if current is None:
        raise GateError("Workflow is already complete; no stage can be started or advanced.")
    if stage != current:
        raise GateError(f"'{stage}' is not the current stage; expected '{current}'.")


def command_start(root: Path, state: dict[str, Any], stage: str) -> int:
    require_current(state, stage)
    stage_state = state["stages"][stage]
    if stage_state["status"] == "pending":
        stage_state["status"] = "in_progress"
        add_history(state, "start", stage)
        save_state(root, state)
        append_progress(root, stage, "start", f"started {stage} stage", "")
        print(f"[OK] Started {stage} stage")
    else:
        print(f"[OK] {stage} stage is already in progress")
    return 0


def command_confirm(root: Path, state: dict[str, Any], stage: str) -> int:
    if stage not in CONFIRMATION_STAGES:
        raise GateError("Only 'modeling', 'abstract', and 'paper' require user confirmation.")
    current = state["current_stage"]
    if current is None:
        raise GateError("Workflow is already complete; no confirmation can be recorded.")
    if stage == "modeling" and current != "modeling":
        raise GateError(f"'modeling' confirmation is not valid during current stage '{current}'.")
    if stage in {"abstract", "paper"} and current != "paper":
        raise GateError(f"'{stage}' confirmation is only valid during current stage 'paper'.")
    confirmation = state["confirmations"][stage]
    if confirmation["confirmed"]:
        print(f"[OK] {stage} confirmation is already recorded")
        return 0
    confirmation["confirmed"] = True
    confirmation["confirmed_at"] = utc_now()
    add_history(state, "confirm", stage)
    save_state(root, state)
    append_progress(root, stage, "confirm", f"recorded user confirmation for {stage}", "")
    print(f"[OK] Recorded user confirmation for {stage}")
    return 0


def command_check(root: Path, state: dict[str, Any], stage: str) -> int:
    blockers = check_stage(root, state, stage)
    print_check(stage, blockers)
    return 1 if blockers else 0


def command_advance(root: Path, state: dict[str, Any], stage: str) -> int:
    require_current(state, stage)
    if state["stages"][stage]["status"] != "in_progress":
        raise GateError(f"Start '{stage}' before advancing it.")
    blockers = check_stage(root, state, stage)
    record_check(state, stage, blockers)
    if blockers:
        print_check(stage, blockers)
        save_state(root, state)
        return 1

    index = STAGES.index(stage)
    state["stages"][stage]["status"] = "completed"
    add_history(state, "advance", stage)
    if index + 1 < len(STAGES):
        next_stage = STAGES[index + 1]
        state["current_stage"] = next_stage
        state["stages"][next_stage]["status"] = "pending"
        print(f"[OK] Completed {stage}; next stage: {next_stage}")
    else:
        state["current_stage"] = None
        print("[OK] Completed paper; workflow is complete")
    save_state(root, state)
    append_progress(root, stage, "advance", f"completed {stage} stage",
                    f"next={state['current_stage'] or 'complete'}")
    return 0


def parse_arguments(argv: list[str]) -> tuple[Path, str, str | None]:
    parser = argparse.ArgumentParser(
        description="Check and advance the persisted modeling -> code -> paper workflow.",
        epilog=("Use '<workspace> <command> [stage]' or "
                "'<command> <workspace> [stage]'."),
    )
    parser.add_argument("arguments", nargs="+", metavar="ARG")
    values = parser.parse_args(argv).arguments
    commands = {"status", "start", "confirm", "check", "advance"}

    if values[0] in commands:
        command = values.pop(0)
        if not values:
            parser.error("workspace is required")
        workspace = values.pop(0)
    else:
        workspace = values.pop(0)
        if not values:
            parser.error("command is required")
        command = values.pop(0)
        if command not in commands:
            parser.error("command must be status, start, confirm, check, or advance")

    if command == "status":
        if values:
            parser.error("status does not take a stage")
        return Path(workspace).expanduser().resolve(), command, None
    if command == "confirm":
        if len(values) != 1 or values[0] not in CONFIRMATION_STAGES:
            parser.error("confirm requires one stage: modeling, abstract, or paper")
        return Path(workspace).expanduser().resolve(), command, values[0]
    if len(values) != 1 or values[0] not in STAGES:
        parser.error(f"{command} requires one stage: modeling, code, or paper")
    return Path(workspace).expanduser().resolve(), command, values[0]


def main(argv: list[str] | None = None) -> int:
    root, command, stage = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    if not root.is_dir():
        print(f"[X] Workspace directory does not exist: {root}", file=sys.stderr)
        return 2
    try:
        if command == "check" and not (root / STATE_FILE).is_file():
            state = transient_state(root)
        else:
            state = load_state(root)
        if command == "status":
            return command_status(root, state)
        if command == "start":
            return command_start(root, state, stage)
        if command == "confirm":
            return command_confirm(root, state, stage)
        if command == "check":
            return command_check(root, state, stage)
        return command_advance(root, state, stage)
    except GateError as exc:
        print(f"[X] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
