#!/usr/bin/env python3
"""Create a structured evidence inventory for a Linux kernel C source file."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from kernel_source import (
    clean_source,
    ctags_functions,
    default_scope,
    direct_callers,
    grouped_tags,
    resolve_source,
)


C_KEYWORDS = {
    "alignof",
    "asm",
    "case",
    "defined",
    "do",
    "for",
    "if",
    "return",
    "sizeof",
    "switch",
    "typeof",
    "while",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory functions, calls, entrances, references, and tracepoints"
    )
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--source", required=True, help="Path relative to kernel root")
    parser.add_argument(
        "--caller-scope",
        help="Directory relative to kernel root; defaults to the target's parent",
    )
    parser.add_argument("--output", default="-", help="JSON path or - for stdout")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    root, relative = resolve_source(args.kernel_root, args.source)
    target = root / relative
    scope = args.caller_scope or default_scope(relative)
    tags = ctags_functions(target)
    grouped = grouped_tags(tags)
    _, clean_lines = clean_source(target)
    names = set(grouped)

    definitions = []
    for name in sorted(grouped):
        variants = grouped[name]
        definitions.append(
            {
                "name": name,
                "static": all(tag.get("file", False) for tag in variants),
                "variants": [
                    {
                        "line": tag["line"],
                        "end": tag["end"],
                        "signature": tag.get("signature", ""),
                    }
                    for tag in variants
                ],
            }
        )

    internal_calls: dict[tuple[str, str], set[int]] = defaultdict(set)
    reference_candidates: dict[tuple[str, str], set[int]] = defaultdict(set)
    call_tokens: dict[str, set[str]] = defaultdict(set)
    call_pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
    for tag in tags:
        caller = tag["name"]
        start, end = tag["line"], tag["end"]
        for lineno in range(start, end + 1):
            line = clean_lines[lineno - 1]
            for match in call_pattern.finditer(line):
                callee = match.group(1)
                if callee in C_KEYWORDS:
                    continue
                call_tokens[caller].add(callee)
                if callee in names and callee != caller:
                    internal_calls[(caller, callee)].add(lineno)
            for callee in names - {caller}:
                if re.search(rf"\b{re.escape(callee)}\b", line) and not re.search(
                    rf"\b{re.escape(callee)}\s*\(", line
                ):
                    reference_candidates[(caller, callee)].add(lineno)

    tracepoints: dict[str, dict[str, set]] = defaultdict(
        lambda: {"emitters": set(), "lines": set()}
    )
    for lineno, line in enumerate(clean_lines, 1):
        for match in re.finditer(r"\b(trace_[A-Za-z0-9_]+)\s*\(", line):
            trace = match.group(1)
            tracepoints[trace]["lines"].add(lineno)
            for tag in tags:
                if tag["line"] <= lineno <= tag["end"]:
                    tracepoints[trace]["emitters"].add(tag["name"])

    callers = direct_callers(root, relative, tags, scope)
    report = {
        "kernel_root": str(root),
        "source": relative.as_posix(),
        "caller_scope": scope,
        "functions": definitions,
        "direct_entrance_candidates": [
            {"function": name, "callers": paths} for name, paths in callers.items()
        ],
        "internal_calls": [
            {"caller": caller, "callee": callee, "lines": sorted(lines)}
            for (caller, callee), lines in sorted(internal_calls.items())
        ],
        "reference_candidates": [
            {"caller": caller, "callee": callee, "lines": sorted(lines)}
            for (caller, callee), lines in sorted(reference_candidates.items())
        ],
        "tracepoints": [
            {
                "name": name,
                "emitters": sorted(data["emitters"]),
                "lines": sorted(data["lines"]),
            }
            for name, data in sorted(tracepoints.items())
        ],
        "call_tokens": {
            caller: sorted(tokens) for caller, tokens in sorted(call_tokens.items())
        },
    }

    rendered = json.dumps(report, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
