#!/usr/bin/env python3
"""Validate a kernel-source canvas against source and layout invariants."""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from kernel_source import (
    clean_source,
    contains_call,
    contains_reference,
    ctags_functions,
    default_scope,
    direct_callers,
    function_bodies,
    parse_pair,
    resolve_source,
)


INTERNAL_LABEL = re.compile(r"^`([A-Za-z_]\w*)\(\)`$")
EXTERNAL_LABEL = re.compile(r"^`([^`:]+):([A-Za-z_]\w*)\(\)`$")
TRACE_LABEL = re.compile(r"^`(trace_[A-Za-z0-9_]+)\(\)`$")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate source evidence, node roles, edges, and geometry"
    )
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--source", required=True, help="Path relative to kernel root")
    parser.add_argument("--canvas", required=True)
    parser.add_argument(
        "--caller-scope",
        help="Directory relative to kernel root; defaults to the target's parent",
    )
    parser.add_argument(
        "--indirect-entrance",
        action="append",
        default=[],
        metavar="FUNCTION",
        help="Proved scoped entrance not discoverable as a direct C call",
    )
    parser.add_argument(
        "--callback-edge",
        action="append",
        default=[],
        metavar="CALLER:CALLEE",
        help="Proved function-reference edge; repeat as needed",
    )
    parser.add_argument(
        "--context-root",
        action="append",
        default=[],
        metavar="FUNCTION",
        help="Intentional displayed root that is not a scoped entrance",
    )
    parser.add_argument("--column-start", type=int, default=760)
    parser.add_argument("--column-step", type=int, default=560)
    parser.add_argument("--note-gap", type=int, default=96)
    return parser.parse_args()


class Results:
    def __init__(self) -> None:
        self.passes: list[str] = []
        self.errors: list[str] = []

    def check(self, name: str, condition: bool, detail: object = "") -> None:
        if condition:
            self.passes.append(name)
        else:
            suffix = f": {detail}" if detail else ""
            self.errors.append(name + suffix)


def main() -> int:
    args = arguments()
    results = Results()
    root, relative = resolve_source(args.kernel_root, args.source)
    target = root / relative
    scope = args.caller_scope or default_scope(relative)
    callback_edges = {parse_pair(value) for value in args.callback_edge}
    indirect = set(args.indirect_entrance)
    context_roots = set(args.context_root)

    data = json.loads(Path(args.canvas).read_text())
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    results.check("nodes array", isinstance(nodes, list))
    results.check("edges array", isinstance(edges, list))
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise SystemExit(1)

    node_ids = [node.get("id") for node in nodes]
    edge_ids = [edge.get("id") for edge in edges]
    by_id = {node.get("id"): node for node in nodes}
    results.check("unique node IDs", len(by_id) == len(nodes))
    results.check("unique edge IDs", len(set(edge_ids)) == len(edge_ids))
    results.check(
        "unique displayed text", len({node.get("text") for node in nodes}) == len(nodes)
    )
    results.check(
        "no dangling edges",
        all(
            edge.get("fromNode") in by_id and edge.get("toNode") in by_id
            for edge in edges
        ),
    )
    if results.errors:
        print("\n".join(f"FAIL {error}" for error in results.errors))
        return 1

    results.check(
        "edge side metadata",
        all(
            edge.get("fromSide") == "right" and edge.get("toSide") == "left"
            for edge in edges
        ),
    )
    gaps = [
        by_id[edge["toNode"]]["x"]
        - (by_id[edge["fromNode"]]["x"] + by_id[edge["fromNode"]]["width"])
        for edge in edges
    ]
    results.check("positive horizontal gaps", not gaps or min(gaps) > 0, min(gaps) if gaps else "")

    overlaps = []
    for index, left in enumerate(nodes):
        for right in nodes[index + 1 :]:
            if (
                left["x"] < right["x"] + right["width"]
                and right["x"] < left["x"] + left["width"]
                and left["y"] < right["y"] + right["height"]
                and right["y"] < left["y"] + left["height"]
            ):
                overlaps.append((left["id"], right["id"]))
    results.check("no node overlaps", not overlaps, overlaps[:10])

    tags = ctags_functions(target)
    defined = {tag["name"] for tag in tags}
    bodies = function_bodies(target, tags)
    _, clean_lines = clean_source(target)

    internal_nodes: dict[str, str] = {}
    external_nodes: dict[str, tuple[str, str]] = {}
    trace_nodes: dict[str, str] = {}
    green_nodes: set[str] = set()
    bad_labels = []
    for node in nodes:
        color = node.get("color")
        text = node.get("text", "")
        if color == "4":
            green_nodes.add(node["id"])
        elif color == "3":
            match = EXTERNAL_LABEL.fullmatch(text)
            if match:
                external_nodes[node["id"]] = (match.group(1), match.group(2))
            else:
                bad_labels.append((node["id"], text))
        elif color == "6":
            match = TRACE_LABEL.fullmatch(text)
            if match:
                trace_nodes[node["id"]] = match.group(1)
            else:
                bad_labels.append((node["id"], text))
        elif color is None:
            match = INTERNAL_LABEL.fullmatch(text)
            if match:
                internal_nodes[node["id"]] = match.group(1)
            else:
                bad_labels.append((node["id"], text))
        else:
            bad_labels.append((node["id"], f"unsupported color {color}: {text}"))
    results.check("node labels and colors", not bad_labels, bad_labels)
    results.check(
        "target functions exist",
        set(internal_nodes.values()) <= defined,
        sorted(set(internal_nodes.values()) - defined),
    )
    results.check(
        "target functions deduplicated",
        len(internal_nodes.values()) == len(set(internal_nodes.values())),
    )
    results.check(
        "tracepoints deduplicated",
        len(trace_nodes.values()) == len(set(trace_nodes.values())),
    )
    results.check(
        "external functions deduplicated",
        len(external_nodes.values()) == len(set(external_nodes.values())),
    )

    external_cache: dict[str, set[str]] = {}
    missing_external = []
    for _, (path_text, function) in external_nodes.items():
        path = (root / path_text).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            missing_external.append((path_text, function, "outside kernel root"))
            continue
        if not path.is_file():
            missing_external.append((path_text, function, "missing file"))
            continue
        if path_text not in external_cache:
            external_cache[path_text] = {tag["name"] for tag in ctags_functions(path)}
        if function not in external_cache[path_text]:
            missing_external.append((path_text, function, "missing definition"))
    results.check("yellow external functions exist", not missing_external, missing_external)

    outgoing: dict[str, list[dict]] = collections.defaultdict(list)
    incoming: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in edges:
        outgoing[edge["fromNode"]].append(edge)
        incoming[edge["toNode"]].append(edge)

    green_targets: dict[str, str] = {}
    bad_green = []
    target_display = f"linux/{relative.as_posix()}"
    for node_id in green_nodes:
        node = by_id[node_id]
        node_outgoing = outgoing[node_id]
        if len(node_outgoing) != 1 or node_outgoing[0]["toNode"] not in internal_nodes:
            bad_green.append((node_id, "must point once to an internal function"))
            continue
        target_id = node_outgoing[0]["toNode"]
        green_targets[node_id] = internal_nodes[target_id]
        target_node = by_id[target_id]
        if node.get("width") != 560 or node.get("height") != 119:
            bad_green.append((node_id, "must be 560x119"))
        if node["x"] != target_node["x"] - node["width"] - args.note_gap:
            bad_green.append((node_id, "wrong horizontal offset"))
        if abs(node["y"] + node["height"] / 2 - (target_node["y"] + target_node["height"] / 2)) > 1:
            bad_green.append((node_id, "not center-aligned"))
        text = node.get("text", "")
        if not all(marker in text for marker in ("- Caller files:", "\n    Called", "\n    Why:")):
            bad_green.append((node_id, "missing required text fields"))
        if target_display in text:
            bad_green.append((node_id, "lists the target file as a caller"))
    results.check("green note structure", not bad_green, bad_green)
    results.check(
        "one green note per target",
        len(green_targets.values()) == len(set(green_targets.values())),
    )

    source_trace_edges = set()
    source_tracepoints = set()
    for lineno, line in enumerate(clean_lines, 1):
        for match in re.finditer(r"\b(trace_[A-Za-z0-9_]+)\s*\(", line):
            trace = match.group(1)
            source_tracepoints.add(trace)
            for tag in tags:
                if tag["line"] <= lineno <= tag["end"]:
                    source_trace_edges.add((tag["name"], trace))
    canvas_tracepoints = set(trace_nodes.values())
    canvas_trace_edges = {
        (internal_nodes[edge["fromNode"]], trace_nodes[edge["toNode"]])
        for edge in edges
        if edge["toNode"] in trace_nodes and edge["fromNode"] in internal_nodes
    }
    results.check(
        "all tracepoints represented",
        canvas_tracepoints == source_tracepoints,
        sorted(canvas_tracepoints ^ source_tracepoints),
    )
    results.check(
        "trace edges match emitters",
        canvas_trace_edges == source_trace_edges,
        sorted(canvas_trace_edges ^ source_trace_edges),
    )

    bad_semantic_edges = []
    seen_callback_pairs = set()
    for edge in edges:
        source_id, target_id = edge["fromNode"], edge["toNode"]
        if source_id in green_nodes:
            continue
        if source_id not in internal_nodes:
            bad_semantic_edges.append((edge["id"], "edge source is not target function or green note"))
            continue
        caller = internal_nodes[source_id]
        if target_id in internal_nodes:
            callee = internal_nodes[target_id]
            pair = (caller, callee)
            valid = contains_call(bodies, caller, callee)
            if not valid and pair in callback_edges:
                valid = contains_reference(bodies, caller, callee)
                if valid:
                    seen_callback_pairs.add(pair)
            if not valid:
                bad_semantic_edges.append((edge["id"], f"unproved internal edge {caller}:{callee}"))
        elif target_id in external_nodes:
            callee = external_nodes[target_id][1]
            pair = (caller, callee)
            valid = contains_call(bodies, caller, callee)
            if not valid and pair in callback_edges:
                valid = contains_reference(bodies, caller, callee)
                if valid:
                    seen_callback_pairs.add(pair)
            if not valid:
                bad_semantic_edges.append((edge["id"], f"unproved external edge {caller}:{callee}"))
        elif target_id in trace_nodes:
            if (caller, trace_nodes[target_id]) not in source_trace_edges:
                bad_semantic_edges.append((edge["id"], "unproved trace edge"))
        else:
            bad_semantic_edges.append((edge["id"], "unknown edge target role"))
    results.check("all semantic edges source-backed", not bad_semantic_edges, bad_semantic_edges)
    results.check(
        "declared callback edges used and proved",
        seen_callback_pairs == callback_edges,
        sorted(callback_edges - seen_callback_pairs),
    )
    results.check(
        "yellow nodes have callers",
        all(incoming[node_id] for node_id in external_nodes),
    )
    results.check(
        "purple nodes have emitters",
        all(incoming[node_id] for node_id in trace_nodes),
    )

    direct = direct_callers(root, relative, tags, scope)
    for name in indirect | context_roots:
        if name not in defined:
            results.errors.append(f"declared exception is not a target function: {name}")
    expected_entrances = set(direct) | indirect
    canvas_entrances = set(green_targets.values())
    results.check(
        "true entrance set exact",
        canvas_entrances == expected_entrances,
        {
            "missing": sorted(expected_entrances - canvas_entrances),
            "extra": sorted(canvas_entrances - expected_entrances),
        },
    )
    results.check(
        "context roots are not entrances",
        not (context_roots & expected_entrances),
        sorted(context_roots & expected_entrances),
    )

    normal_edges = [edge for edge in edges if edge["fromNode"] not in green_nodes]
    rank = {}
    off_grid = []
    for node_id, node in by_id.items():
        if node_id in green_nodes:
            continue
        value = (node["x"] - args.column_start) / args.column_step
        rounded = round(value)
        if abs(value - rounded) > 1e-9:
            off_grid.append((node_id, node["x"]))
        rank[node_id] = rounded
    results.check("fixed x columns", not off_grid, off_grid)
    results.check(
        "all callees rank rightward",
        all(rank[edge["toNode"]] > rank[edge["fromNode"]] for edge in normal_edges),
    )
    normal_outgoing: dict[str, list[str]] = collections.defaultdict(list)
    for edge in normal_edges:
        normal_outgoing[edge["fromNode"]].append(edge["toNode"])
    results.check(
        "callers maximally compacted",
        all(
            rank[source] == min(rank[target] for target in targets) - 1
            for source, targets in normal_outgoing.items()
        ),
    )

    internal_incoming = collections.Counter()
    for edge in edges:
        if edge["fromNode"] in internal_nodes and edge["toNode"] in internal_nodes:
            internal_incoming[edge["toNode"]] += 1
    displayed_roots = {
        function
        for node_id, function in internal_nodes.items()
        if internal_incoming[node_id] == 0
    }
    unnoted_roots = displayed_roots - canvas_entrances
    results.check(
        "unnoted roots are explicit context",
        unnoted_roots == context_roots,
        {
            "undeclared": sorted(unnoted_roots - context_roots),
            "unused": sorted(context_roots - unnoted_roots),
        },
    )

    height = (
        max(node["y"] + node["height"] for node in nodes)
        - min(node["y"] for node in nodes)
        if nodes
        else 0
    )
    print(f"PASS {len(results.passes)} checks")
    for name in results.passes:
        print(f"PASS {name}")
    print(
        "SUMMARY "
        + json.dumps(
            {
                "nodes": len(nodes),
                "edges": len(edges),
                "internal": len(internal_nodes),
                "green": len(green_nodes),
                "yellow": len(external_nodes),
                "purple": len(trace_nodes),
                "min_horizontal_gap": min(gaps) if gaps else None,
                "overlaps": len(overlaps),
                "height": round(height, 1),
            },
            sort_keys=True,
        )
    )
    if results.errors:
        print(f"FAIL {len(results.errors)} checks")
        for error in results.errors:
            print(f"FAIL {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
