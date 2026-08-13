# -*- coding: utf-8 -*-
"""merge_manifest.py — 从各题 manifest 片段重建 results/manifest.md（防并行写冲突）

用法：python scripts/merge_manifest.py <workspace目录> [--check]

背景：多个 solver 实例并行追加共享 manifest.md 会产生重复行/交错写（2020A 实测踩坑）。
v0.2 协议改为：
  - solver 只写本问片段 results/q{n}/manifest-fragment.md（同列格式，只含本问图表行）；
  - 主循环在 M2 收尾运行本脚本，从全部片段重建共享 results/manifest.md。

合并规则：
  1. 按 q1, q2, ... 数字序收集 results/q*/manifest-fragment.md 的表格行；
  2. 兼容旧工作区：若某问无片段但共享 manifest 已有该问行，保留旧行（迁移期）；
  3. 以"文件"列去重——同一文件后写的片段行覆盖先出现的行（含旧行）；
  4. 行内文件路径若不存在于工作区，警告并标记（--check 模式下退出码 1）。

--check：只读校验（不重写 manifest），供 workflow_gate/CI 用。
"""
import argparse
import glob
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HEADER = """# 结果清单（paper-writer 的唯一输入契约）

> 每张图表一行：文件（相对题目根）× 生成脚本 × 一句话结论
> 本文件由 scripts/merge_manifest.py 从 results/q*/manifest-fragment.md 自动重建，请勿手工追加。

| 图表 | 文件 | 生成脚本 | 一句话结论 |
|---|---|---|---|
"""


def out(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode())


def is_sep(line):
    body = line.strip().strip("|")
    return bool(body) and set(body.replace("|", "")) <= set(":- ")


def parse_rows(path):
    """解析一个 markdown 文件中的 4 列表格数据行。"""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or is_sep(line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if (
                len(cells) >= 4
                and cells[0] not in ("图表", "")
                and cells[1].lower() not in {"文件", "file", "artifact"}
            ):
                rows.append(tuple(cells[:4]))
    return rows


def qnum(path):
    m = re.search(r"[/\\]q(\d+)[/\\]", path)
    return int(m.group(1)) if m else 999


def qkey(value):
    m = re.fullmatch(r"q([1-9]\d*)", str(value))
    return int(m.group(1)) if m else None


def resolve_workspace_path(ws, value):
    cleaned = value.strip().strip("`").strip("\"'")
    if not cleaned:
        return None
    candidate = cleaned if os.path.isabs(cleaned) else os.path.join(ws, cleaned)
    resolved = os.path.abspath(candidate)
    try:
        inside = os.path.commonpath([ws, resolved]) == ws
    except ValueError:
        inside = False
    return resolved if inside else None


class DuplicateJsonKeyError(ValueError):
    pass


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def strict_json_load(handle):
    return json.load(handle, object_pairs_hook=unique_json_object)


def registry_questions(ws):
    registry_path = os.path.join(ws, "01-analysis", "scheme-registry.json")
    if not os.path.exists(registry_path):
        return [], []
    try:
        with open(registry_path, "r", encoding="utf-8-sig") as handle:
            registry = strict_json_load(handle)
    except DuplicateJsonKeyError as exc:
        return [], [f"[X] scheme-registry.json malformed: {exc}"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], []
    if not isinstance(registry, dict) or registry.get("version") != 1:
        return [], []
    questions = registry.get("questions")
    if not isinstance(questions, dict):
        return [], []
    return sorted({number for key in questions if (number := qkey(key)) is not None}), []


def result_questions(ws):
    found = set()
    results = os.path.join(ws, "results")
    if not os.path.isdir(results):
        return []
    for name in os.listdir(results):
        number = qkey(name)
        if number is not None and os.path.isdir(os.path.join(results, name)):
            found.add(number)
    for fragment in glob.glob(os.path.join(results, "q*", "manifest-fragment.md")):
        number = qnum(fragment)
        if number != 999:
            found.add(number)
    return sorted(found)


def managed_expected_questions(ws):
    state_path = os.path.join(ws, "workflow-state.json")
    if not os.path.exists(state_path):
        return False, [], []
    try:
        with open(state_path, "r", encoding="utf-8-sig") as handle:
            state = strict_json_load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        return True, [], [f"[X] workflow-state.json malformed: {exc}"]
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        return True, [], ["[X] workflow-state.json malformed: expected schema_version 1"]
    declared = state.get("subquestions", 0)
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        return True, [], ["[X] workflow-state.json malformed: invalid subquestions"]
    if declared:
        return True, list(range(1, declared + 1)), []
    registry, registry_errors = registry_questions(ws)
    if registry_errors:
        return True, [], registry_errors
    derived = registry or result_questions(ws)
    if not derived:
        return True, [], ["[X] managed workspace has no expected questions; refusing empty manifest"]
    return True, derived, []


def managed_fragment_paths(ws, expected_questions):
    blockers = []
    paths = []
    for q in expected_questions:
        fragment = os.path.join(ws, "results", f"q{q}", "manifest-fragment.md")
        rows = parse_rows(fragment)
        if not os.path.exists(fragment):
            blockers.append(f"[X] managed q{q}: missing results/q{q}/manifest-fragment.md")
        elif os.path.getsize(fragment) == 0:
            blockers.append(f"[X] managed q{q}: empty results/q{q}/manifest-fragment.md")
        elif not rows:
            blockers.append(f"[X] managed q{q}: manifest-fragment.md has no artifact rows")
        else:
            paths.append(fragment)
    return paths, blockers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", help="题目工作区目录，如 workspace/2020A-furnace")
    ap.add_argument("--check", action="store_true", help="只读校验，不重写 manifest")
    args = ap.parse_args()

    ws = os.path.abspath(args.workspace)
    if not os.path.isdir(ws):
        sys.exit(f"[X] 工作区不存在: {ws}")
    manifest_path = os.path.join(ws, "results", "manifest.md")
    managed, expected_questions, state_errors = managed_expected_questions(ws)
    if state_errors:
        for error in state_errors:
            out(error)
        sys.exit(1)

    # 1) 收集片段行（按题号序）
    if managed:
        frag_paths, fragment_errors = managed_fragment_paths(ws, expected_questions)
        if fragment_errors:
            for error in fragment_errors:
                out(error)
            sys.exit(1)
        frag_paths = sorted(frag_paths, key=qnum)
    else:
        frag_paths = sorted(
            glob.glob(os.path.join(ws, "results", "q*", "manifest-fragment.md")),
            key=qnum)
    frag_rows = []
    frag_questions = set()
    for fp in frag_paths:
        rows = parse_rows(fp)
        frag_rows.extend(rows)
        frag_questions.add(qnum(fp))
        out(f"[frag] q{qnum(fp)}: {len(rows)} 行  ({os.path.relpath(fp, ws)})")

    # 2) 迁移兼容：旧共享 manifest 中"无片段的题"的行保留
    current_rows = parse_rows(manifest_path)
    legacy_rows = []
    if not managed:
        for row in current_rows:
            q = qnum("/" + row[1].replace("\\", "/") + "/")  # 从文件路径推题号
            if q not in frag_questions:
                legacy_rows.append(row)
    if legacy_rows:
        out(f"[legacy] 保留旧 manifest 中无片段覆盖的 {len(legacy_rows)} 行")

    # 3) 按"文件"列去重（片段行优先、后写覆盖先写）
    merged, index = [], {}
    for row in legacy_rows + frag_rows:
        key = row[1].replace("\\", "/")
        if key in index:
            merged[index[key]] = row
        else:
            index[key] = len(merged)
            merged.append(row)

    # 4) 校验文件存在性与工作区边界
    missing = []
    invalid = []
    for label, fpath, script, _ in merged:
        for p in (fpath, script):
            resolved = resolve_workspace_path(ws, p)
            if resolved is None:
                invalid.append(f"{label}: {p}")
            elif not os.path.exists(resolved):
                missing.append(f"{label}: {p}")
    for item in invalid:
        out(f"[invalid] 工件路径越界 -> {item}")
    for m in missing:
        out(f"[warn] 工件不存在 -> {m}")

    if args.check:
        stale = current_rows != merged
        if stale:
            out("[stale] results/manifest.md 与 canonical fragment merge view 不一致")
        out(
            f"[check] 合并视图 {len(merged)} 行，当前 manifest {len(current_rows)} 行，"
            f"缺失工件 {len(missing)} 处，越界路径 {len(invalid)} 处，stale={int(stale)}"
        )
        sys.exit(1 if missing or invalid or stale else 0)

    if invalid:
        sys.exit("[X] manifest 片段包含越界路径，拒绝重建共享 manifest")

    # 5) 重建 manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        for row in merged:
            f.write("| " + " | ".join(row) + " |\n")
    out(f"[OK] 已重建 {os.path.relpath(manifest_path, ws)}: "
        f"{len(merged)} 行（片段 {len(frag_rows)}，旧行保留 {len(legacy_rows)}，"
        f"缺失警告 {len(missing)}）")


if __name__ == "__main__":
    main()
