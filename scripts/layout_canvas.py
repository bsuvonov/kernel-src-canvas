#!/usr/bin/env python3
"""Assign fixed columns and readable Graphviz-assisted lanes to a canvas DAG."""

from __future__ import annotations

import argparse
import collections
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from kernel_source import parse_pair


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lay out a kernel-source canvas")
    parser.add_argument("canvas", help="Draft .canvas JSON")
    parser.add_argument("--output", "-o", help="Output path; defaults to in-place")
    parser.add_argument(
        "--primary-edge",
        action="append",
        default=[],
        metavar="CALLER:CALLEE",
        help="Logical lane edge to favor; repeat as needed",
    )
    parser.add_argument("--column-start", type=int, default=760)
    parser.add_argument("--column-step", type=int, default=560)
    parser.add_argument("--note-gap", type=int, default=96)
    parser.add_argument("--nodesep", type=float, default=0.30)
    return parser.parse_args()


def function_label(text: str) -> str | None:
    match = re.fullmatch(r"`([A-Za-z_]\w*)\(\)`", text)
    return match.group(1) if match else None


def width_for(node: dict) -> int:
    if node.get("color") == "4":
        return 560
    text = node.get("text", "")
    if node.get("color") == "6":
        return max(430, min(550, 45 + len(text) * 9))
    if node.get("color") == "3":
        return max(390, min(540, 45 + len(text) * 8))
    return max(250, min(390, 38 + len(text) * 9))


def topological(nodes: set[str], edges: set[tuple[str, str]]) -> list[str]:
    outgoing: dict[str, set[str]] = collections.defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for source, target in edges:
        if target not in outgoing[source]:
            outgoing[source].add(target)
            indegree[target] += 1
    ready = collections.deque(sorted(node for node, degree in indegree.items() if degree == 0))
    order = []
    while ready:
        node = ready.popleft()
        order.append(node)
        for target in sorted(outgoing[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(order) != len(nodes):
        blocked = sorted(node for node, degree in indegree.items() if degree)
        raise ValueError(f"displayed graph contains a cycle involving: {', '.join(blocked)}")
    return order


def main() -> int:
    args = arguments()
    source_path = Path(args.canvas)
    output_path = Path(args.output) if args.output else source_path
    data = json.loads(source_path.read_text())
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("canvas must contain nodes and edges arrays")
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("node IDs are not unique")
    for edge in edges:
        if edge.get("fromNode") not in by_id or edge.get("toNode") not in by_id:
            raise ValueError(f"dangling edge: {edge.get('id', '<unknown>')}")

    for node in nodes:
        node["width"] = 560 if node.get("color") == "4" else node.get(
            "width", width_for(node)
        )
        node["height"] = 119 if node.get("color") == "4" else node.get(
            "height", 60
        )

    outgoing_edges: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in edges:
        outgoing_edges[edge["fromNode"]].append(edge)
    note_target: dict[str, str] = {}
    for node in nodes:
        if node.get("color") != "4":
            continue
        outgoing = outgoing_edges[node["id"]]
        if len(outgoing) != 1:
            raise ValueError(f"green note must have one outgoing edge: {node['id']}")
        target = outgoing[0]["toNode"]
        if by_id[target].get("color") == "4":
            raise ValueError(f"green note cannot target another green note: {node['id']}")
        note_target[node["id"]] = target

    non_notes = set(by_id) - set(note_target)
    graph_edges = {
        (edge["fromNode"], edge["toNode"])
        for edge in edges
        if edge["fromNode"] not in note_target
    }
    if any(source not in non_notes or target not in non_notes for source, target in graph_edges):
        raise ValueError("normal graph edges may not enter or leave green notes")
    order = topological(non_notes, graph_edges)
    outgoing: dict[str, set[str]] = collections.defaultdict(set)
    rank = {node: 0 for node in non_notes}
    for source, target in graph_edges:
        outgoing[source].add(target)
    for source in order:
        for target in outgoing[source]:
            rank[target] = max(rank[target], rank[source] + 1)
    for source in reversed(order):
        if outgoing[source]:
            rank[source] = min(rank[target] for target in outgoing[source]) - 1

    for node in nodes:
        if node["id"] in non_notes:
            node["x"] = args.column_start + rank[node["id"]] * args.column_step
    for note, target in note_target.items():
        by_id[note]["x"] = by_id[target]["x"] - by_id[note]["width"] - args.note_gap

    gaps = [
        by_id[edge["toNode"]]["x"]
        - (by_id[edge["fromNode"]]["x"] + by_id[edge["fromNode"]]["width"])
        for edge in edges
    ]
    if gaps and min(gaps) <= 0:
        raise ValueError(
            "column step is too small for node widths; increase --column-step or reduce widths"
        )

    labels: dict[str, list[str]] = collections.defaultdict(list)
    for node in nodes:
        label = function_label(node.get("text", ""))
        if label:
            labels[label].append(node["id"])

    def resolve_endpoint(value: str) -> str:
        if value in by_id:
            return value
        matches = labels.get(value, [])
        if len(matches) == 1:
            return matches[0]
        raise ValueError(f"primary edge endpoint is not a unique node ID or function: {value}")

    primary = {
        (resolve_endpoint(source), resolve_endpoint(target))
        for source, target in (parse_pair(value) for value in args.primary_edge)
    }
    missing_primary = primary - graph_edges
    if missing_primary:
        raise ValueError(f"primary edges are not canvas edges: {sorted(missing_primary)}")

    if not shutil.which("dot"):
        raise RuntimeError("Graphviz `dot` is required for vertical layout")
    conceptual_rank = dict(rank)
    for note, target in note_target.items():
        conceptual_rank[note] = rank[target] - 1
    ranks: dict[int, list[str]] = collections.defaultdict(list)
    for node, value in conceptual_rank.items():
        ranks[value].append(node)

    dot = [
        "digraph G {",
        f"graph [rankdir=LR, nodesep={args.nodesep}, ranksep=0.75, "
        "splines=polyline, outputorder=edgesfirst, mclimit=4, remincross=true];",
        'node [shape=box, fixedsize=true, label=""];',
    ]
    for node in nodes:
        dot.append(
            f'"{node["id"]}" [width={node["width"] / 96:.5f}, '
            f'height={node["height"] / 96:.5f}];'
        )
    for value in sorted(ranks):
        members = "; ".join(f'"{node}"' for node in sorted(ranks[value]))
        dot.append(f"{{ rank=same; {members}; }}")

    minimum, maximum = min(ranks), max(ranks)
    anchors = []
    for value in range(minimum, maximum + 1):
        anchor = f"rank_anchor_{value - minimum}"
        anchors.append(anchor)
        dot.append(
            f'"{anchor}" [shape=point, width=0.01, height=0.01, style=invis];'
        )
        if ranks.get(value):
            dot.append(
                f'{{ rank=same; "{anchor}"; "{sorted(ranks[value])[0]}"; }}'
            )
    for left, right in zip(anchors, anchors[1:]):
        dot.append(f'"{left}" -> "{right}" [style=invis, weight=1000];')
    for edge in edges:
        source, target = edge["fromNode"], edge["toNode"]
        if source in note_target:
            weight = 100
        elif (source, target) in primary:
            weight = 10
        elif by_id[target].get("color") == "6":
            weight = 2
        else:
            weight = 1
        dot.append(f'"{source}" -> "{target}" [weight={weight}];')
    dot.append("}")

    plain = subprocess.check_output(
        ["dot", "-Tplain"], input="\n".join(dot), text=True
    )
    center_y: dict[str, float] = {}
    for line in plain.splitlines():
        fields = shlex.split(line)
        if fields and fields[0] == "node" and not fields[1].startswith("rank_anchor_"):
            center_y[fields[1]] = -float(fields[3]) * 96
    if set(center_y) != set(by_id):
        raise RuntimeError("Graphviz output did not contain every canvas node")
    for note, target in note_target.items():
        center_y[note] = center_y[target]

    group = {node: node for node in by_id}
    target_note = {}
    for note, target in note_target.items():
        group[note] = target
        group[target] = target
        target_note[target] = note

    def members(key: str) -> list[dict]:
        return [by_id[key]] + ([by_id[target_note[key]]] if key in target_note else [])

    def overlaps(left: dict, right: dict) -> bool:
        return (
            left["x"] < right["x"] + right["width"]
            and right["x"] < left["x"] + left["width"]
            and center_y[left["id"]] - left["height"] / 2
            < center_y[right["id"]] + right["height"] / 2
            and center_y[right["id"]] - right["height"] / 2
            < center_y[left["id"]] + left["height"] / 2
        )

    for _ in range(5000):
        collision = None
        for index, left in enumerate(nodes):
            for right in nodes[index + 1 :]:
                if group[left["id"]] != group[right["id"]] and overlaps(left, right):
                    collision = left, right
                    break
            if collision:
                break
        if not collision:
            break
        left, right = collision
        left_group, right_group = group[left["id"]], group[right["id"]]
        left_movable = left_group in target_note
        right_movable = right_group in target_note
        if not (left_movable or right_movable):
            raise RuntimeError(f"unexpected non-note collision: {left['id']} / {right['id']}")
        if left_movable and right_movable:
            moving, fixed = (
                (left_group, right_group)
                if center_y[left_group] >= center_y[right_group]
                else (right_group, left_group)
            )
        elif left_movable:
            moving, fixed = left_group, right_group
        else:
            moving, fixed = right_group, left_group
        moving_top = min(
            center_y[node["id"]] - node["height"] / 2 for node in members(moving)
        )
        fixed_bottom = max(
            center_y[node["id"]] + node["height"] / 2 for node in members(fixed)
        )
        delta = max(36, fixed_bottom + 36 - moving_top)
        for node in members(moving):
            center_y[node["id"]] += delta
    else:
        raise RuntimeError("green-note collision resolution did not converge")

    top = min(center_y[node["id"]] - node["height"] / 2 for node in nodes)
    for node in nodes:
        node["y"] = round(center_y[node["id"]] - top - node["height"] / 2, 1)

    for edge in edges:
        edge["fromSide"] = "right"
        edge["toSide"] = "left"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n")
    height = max(node["y"] + node["height"] for node in nodes) - min(
        node["y"] for node in nodes
    )
    print(
        f"wrote {output_path}: {len(nodes)} nodes, {len(edges)} edges, "
        f"{maximum - minimum + 1} conceptual columns, {height:.1f}px high"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
