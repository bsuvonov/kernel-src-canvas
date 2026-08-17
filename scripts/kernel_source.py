#!/usr/bin/env python3
"""Shared source-inspection helpers for kernel-src-canvas scripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path


PAIR_RE = re.compile(r"^([A-Za-z_]\w*):([A-Za-z_]\w*)$")


def resolve_source(kernel_root: str | Path, source: str | Path) -> tuple[Path, Path]:
    root = Path(kernel_root).expanduser().resolve()
    candidate = Path(source).expanduser()
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not root.is_dir():
        raise ValueError(f"kernel root is not a directory: {root}")
    if not target.is_file():
        raise ValueError(f"target source is not a file: {target}")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"target source is outside kernel root: {target}") from exc
    return root, relative


def parse_pair(value: str) -> tuple[str, str]:
    match = PAIR_RE.fullmatch(value)
    if not match:
        raise ValueError(f"expected CALLER:CALLEE, got: {value}")
    return match.group(1), match.group(2)


def strip_c(text: str) -> str:
    """Replace comments and literals while preserving newlines and offsets."""
    output: list[str] = []
    index = 0
    state = "code"
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and following == "*":
                output.extend((" ", " "))
                index += 2
                state = "block"
            elif char == "/" and following == "/":
                output.extend((" ", " "))
                index += 2
                state = "line"
            elif char == '"':
                output.append(" ")
                index += 1
                state = "string"
            elif char == "'":
                output.append(" ")
                index += 1
                state = "char"
            else:
                output.append(char)
                index += 1
        elif state == "block":
            if char == "*" and following == "/":
                output.extend((" ", " "))
                index += 2
                state = "code"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
        elif state == "line":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "code"
        else:
            quote = '"' if state == "string" else "'"
            if char == "\\" and index + 1 < len(text):
                output.extend((" ", "\n" if following == "\n" else " "))
                index += 2
            elif char == quote:
                output.append(" ")
                index += 1
                state = "code"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
    return "".join(output)


def ctags_functions(path: Path) -> list[dict]:
    if not shutil.which("ctags"):
        raise RuntimeError("Universal Ctags is required but `ctags` was not found")
    command = [
        "ctags",
        "--output-format=json",
        "--fields=+neKSt",
        "--c-kinds=f",
        "-o",
        "-",
        str(path),
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or "ctags failed") from exc
    tags = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    for tag in tags:
        if "line" not in tag or "end" not in tag:
            raise RuntimeError("ctags output lacks line/end fields; use Universal Ctags")
    return tags


def grouped_tags(tags: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for tag in tags:
        grouped[tag["name"]].append(tag)
    return dict(grouped)


def clean_source(path: Path) -> tuple[list[str], list[str]]:
    raw = path.read_text(errors="replace")
    return raw.splitlines(), strip_c(raw).splitlines()


def function_bodies(path: Path, tags: list[dict]) -> dict[str, list[str]]:
    _, clean_lines = clean_source(path)
    bodies: dict[str, list[str]] = defaultdict(list)
    for tag in tags:
        fragment = "\n".join(clean_lines[tag["line"] - 1 : tag["end"]])
        brace = fragment.find("{")
        bodies[tag["name"]].append(fragment[brace + 1 :] if brace >= 0 else fragment)
    return dict(bodies)


def contains_call(bodies: dict[str, list[str]], caller: str, callee: str) -> bool:
    pattern = re.compile(rf"\b{re.escape(callee)}\s*\(")
    return any(pattern.search(body) for body in bodies.get(caller, []))


def contains_reference(bodies: dict[str, list[str]], caller: str, callee: str) -> bool:
    pattern = re.compile(rf"\b{re.escape(callee)}\b")
    return any(pattern.search(body) for body in bodies.get(caller, []))


def direct_callers(
    kernel_root: Path,
    target_relative: Path,
    tags: list[dict],
    caller_scope: str | Path,
) -> dict[str, list[str]]:
    public = sorted({tag["name"] for tag in tags if not tag.get("file")})
    patterns = {
        name: re.compile(rf"\b{re.escape(name)}\s*\(") for name in public
    }
    callers: dict[str, set[str]] = defaultdict(set)
    scope_root = (kernel_root / caller_scope).resolve()
    if not scope_root.is_dir():
        raise ValueError(f"caller scope is not a directory: {scope_root}")
    target = (kernel_root / target_relative).resolve()
    for path in scope_root.rglob("*.c"):
        if path.resolve() == target:
            continue
        cleaned = strip_c(path.read_text(errors="replace"))
        display = f"linux/{path.relative_to(kernel_root).as_posix()}"
        for name, pattern in patterns.items():
            if pattern.search(cleaned):
                callers[name].add(display)
    return {name: sorted(paths) for name, paths in sorted(callers.items())}


def default_scope(target_relative: Path) -> str:
    return target_relative.parent.as_posix()
