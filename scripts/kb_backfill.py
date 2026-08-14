# -*- coding: utf-8 -*-
"""赛马结果回填知识库（经验闭环）：把 workspace 的赛马结论追加到
``knowledge-base/distillation/race-log.md``，使 Agent 每跑一题选型能力累积。

用法:
    python scripts/kb_backfill.py <workspace> [--log <race-log路径>] [--dry-run] [--force]

输入（全部只读）:
    - 01-analysis/scheme-registry.json   （候选、race 协议）
    - results/qN/summary.md              （chosen_scheme、robustness、key_results）
    - results/qN/scheme-comparison.md    （winner、主指标、赛马表；仅 required race）

输出:
    每问一行追加到 race-log.md（默认 knowledge-base/distillation/race-log.md）。
    幂等：同一 workspace+问 已登记则跳过（--force 覆盖该行）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_LOG = ROOT / "knowledge-base" / "distillation" / "race-log.md"
Q_DIR_RE = re.compile(r"q([1-9][0-9]*)$")


class BackfillError(Exception):
    pass


def strict_json_loads(text: str) -> Any:
    return json.loads(text)


def load_registry(root: Path) -> dict[str, Any]:
    path = root / "01-analysis" / "scheme-registry.json"
    if not path.is_file():
        return {}
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackfillError(f"cannot read {path}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def frontmatter(path: Path) -> dict[str, str]:
    text = ""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    current_list_key: str | None = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped in {"---", "..."}:
            return fields
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1].isspace():
            if current_list_key and stripped.startswith("-"):
                fields[current_list_key] = fields.get(current_list_key, "") + "\n" + stripped[1:].strip()
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        fields[key] = value
        if not value:
            current_list_key = key
    return fields


def comparison_rows(path: Path) -> list[dict[str, str]]:
    text = ""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    header: list[str] = []
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        columns = [c.strip() for c in stripped.strip("|").split("|")]
        if len(columns) < 2:
            continue
        if all(set(c) <= {"-", ":"} for c in columns):
            continue
        if not header:
            header = [c.lower() for c in columns]
            continue
        if len(columns) >= len(header):
            rows.append(dict(zip(header, columns[: len(header)])))
    return rows


def metric_column(rows: list[dict[str, str]], metric: str) -> str | None:
    lowered = metric.lower()
    scheme_keys = {"scheme", "name", "method", "candidate", "方案", "模型", "feasibility", "status", "可行", "状态"}
    for row in rows:
        for key in row:
            if key in scheme_keys:
                continue
            if lowered in key.lower():
                return key
    return None


def scheme_column(rows: list[dict[str, str]]) -> str | None:
    for key in ("scheme", "name", "method", "candidate", "方案", "模型"):
        if any(key == col for row in rows for col in row):
            return key
    return None


def question_dirs(root: Path) -> list[int]:
    results = root / "results"
    if not results.is_dir():
        return []
    return sorted(
        int(Q_DIR_RE.fullmatch(child.name).group(1))
        for child in results.iterdir()
        if child.is_dir() and Q_DIR_RE.fullmatch(child.name)
    )


def build_row(workspace: Path, question: int, registry: dict[str, Any]) -> str | None:
    label = f"q{question}"
    summary_path = workspace / "results" / label / "summary.md"
    if not summary_path.is_file():
        return None
    summary = frontmatter(summary_path)
    if summary.get("status") != "solved":
        return None

    chosen = summary.get("chosen_scheme", "").strip()
    candidates: list[tuple[str, str]] = []
    race = {}
    spec = (registry.get("questions") or {}).get(label) if registry else None
    if isinstance(spec, dict):
        for candidate in spec.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("name"):
                candidates.append((str(candidate["name"]), str(candidate.get("kind", ""))))
        if isinstance(spec.get("race"), dict):
            race = spec["race"]

    comparison = workspace / "results" / label / "scheme-comparison.md"
    winner = chosen
    primary = str(race.get("primary_metric", "")).strip()
    outcome = ""
    if comparison.is_file():
        fm = frontmatter(comparison)
        winner = fm.get("winner", "").strip() or chosen
        primary = fm.get("primary_metric", "").strip() or primary
        rows = comparison_rows(comparison)
        scheme_col = scheme_column(rows)
        metric_col = metric_column(rows, primary) if primary else None
        if scheme_col and metric_col:
            cells = []
            for row in rows:
                name = row.get(scheme_col, "").strip()
                value = row.get(metric_col, "").strip()
                if name and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
                    cells.append(f"{name}={value}")
            # keep it compact: winner first, then the rest
            winner_first = [c for c in cells if c.startswith(winner + "=")]
            others = [c for c in cells if not c.startswith(winner + "=")]
            outcome = "；".join(winner_first + others)[:200]
    if not outcome:
        first_key = (summary.get("key_results") or "").strip().splitlines()[0] if summary.get("key_results") else ""
        outcome = first_key[:180]

    robustness = summary.get("robustness", "").strip()
    scheme_text = ", ".join(f"{name}({kind})" if kind else name for name, kind in candidates) or "-"
    now = dt.datetime.now().strftime("%Y-%m-%d")
    reason = f"chosen={chosen or '-'}; winner={winner or '-'}; metric={primary or '-'} ({race.get('direction', '')})"
    return (
        f"| {now} | {workspace.name} | {label} | {scheme_text} | {reason} | "
        f"{outcome} | {robustness or '-'} | results/{label}/scheme-comparison.md |"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="赛马结果回填知识库 race-log")
    parser.add_argument("workspace")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2
    log_path = Path(args.log).resolve()
    registry = load_registry(workspace)

    rows: list[str] = []
    for question in question_dirs(workspace):
        row = build_row(workspace, question, registry)
        if row:
            rows.append(row)

    if args.dry_run:
        for row in rows:
            print(row)
        print(f"[dry-run] {len(rows)} row(s) would be appended to {log_path}")
        return 0

    header = (
        "# 赛马结果回填日志（race-log）\n\n"
        "> 每行 = 一道子问题的赛马结论（候选集 / winner / 主指标 / 结果摘要 / 稳健性），"
        "由 scripts/kb_backfill.py 从 workspace 追加；数值均来自 workspace 可复现产物。\n\n"
        "| 日期 | workspace | 问 | 候选(kind) | 赛马协议 | 结果摘要 | 稳健性 | 数据源 |\n"
        "|---|---|---|---|---|---|---|---|\n"
    )
    if not log_path.is_file():
        log_path.write_text(header, encoding="utf-8")
    lines = log_path.read_text(encoding="utf-8").splitlines()
    added = 0
    for row in rows:
        key = row.split("|")[3].strip() if len(row.split("|")) > 3 else ""
        existing = any(
            line.startswith("|") and f"| {workspace.name} | {key} |" in line
            for line in lines
        )
        if existing and not args.force:
            continue
        if existing and args.force:
            lines = [line for line in lines if not (
                line.startswith("|") and f"| {workspace.name} | {key} |" in line
            )]
        lines.append(row)
        added += 1
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"race-log updated: {added} row(s) at {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
