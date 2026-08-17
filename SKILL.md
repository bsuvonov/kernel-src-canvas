---
name: kernel-src-canvas
description: Create, revise, and validate Obsidian `.canvas` call graphs for Linux kernel C source files using a local kernel tree as the source of truth. Use when Codex needs to identify subsystem entrances, internal call paths, callback relationships, external callees, and tracepoints; produce a readable left-to-right kernel-source canvas; improve an existing canvas layout; or audit a canvas for source and structural integrity.
---

# Kernel Source Canvas

Produce an Obsidian JSON Canvas that explains how a Linux kernel source file is entered and how its important call paths flow. Favor verified relationships and readable lanes over exhaustive or compact diagrams.

## Workflow

1. Confirm Python 3.10+, Universal Ctags, and Graphviz `dot` are available.
2. Resolve the source location before analysis:
   - Use a kernel root or target-file path already supplied by the user, including an absolute path outside the current workspace.
   - Otherwise, look for the requested target in the current workspace without assuming the kernel tree is `./` or `./linux`.
   - If the target is absent or multiple candidates are plausible, ask the user for the exact code-file location. Also request the kernel source root when it cannot be derived reliably from that file path. Do not guess a location or start source analysis before the file is resolved.
3. Locate the caller scope, output path, and any existing canvases that establish local style.
4. Read [references/canvas-spec.md](references/canvas-spec.md) before selecting nodes or writing JSON.
5. Inventory the target with the analysis script:

   ```bash
   python3 scripts/analyze_kernel_source.py \
     --kernel-root /path/to/linux \
     --source mm/vmscan.c \
     --caller-scope mm \
     --output /tmp/vmscan-analysis.json
   ```

6. Inspect the reported definitions, direct entrance candidates, internal calls, reference candidates, and tracepoints against the source. Treat reference candidates as leads only; distinguish real callback uses from same-named variables.
7. Select every true scoped entrance, important internal paths, relevant external callees, and every tracepoint. Keep shared functions as single nodes.
8. Build a draft `.canvas` with stable IDs, node text, colors, dimensions, and verified edges. Coordinates may be provisional.
9. Rank and lay out the draft:

   ```bash
   python3 scripts/layout_canvas.py draft.canvas \
     --output vmscan.canvas \
     --primary-edge try_to_free_pages:do_try_to_free_pages \
     --primary-edge do_try_to_free_pages:shrink_zones
   ```

   Pass `--primary-edge` for the logical spine of each major lane. The script requires Graphviz `dot`.

10. Validate the result:

   ```bash
   python3 scripts/validate_canvas.py \
     --kernel-root /path/to/linux \
     --source mm/vmscan.c \
     --canvas vmscan.canvas \
     --caller-scope mm \
     --indirect-entrance __acct_reclaim_writeback \
     --callback-edge kswapd_run:kswapd
   ```

   Repeat `--indirect-entrance`, `--callback-edge`, and `--context-root` when source inspection proves those exceptions.

11. Visually inspect the canvas at normal zoom. Fix crossed lanes, connectors that pass through unrelated boxes, long avoidable vertical runs, and crowded tracepoint branches. Run validation again after every layout or content edit.

## Source Decisions

- Use `--caller-scope mm` for the developed memory-management convention. For another subsystem, set the directory whose outside-target calls define green entrances.
- Count direct calls, inline-wrapper paths, registered callbacks, ops-table callbacks, and worker function references only when source evidence establishes the relationship.
- Supply indirect entrances explicitly to validation; automated name matching does not prove indirect control flow.
- Use external yellow nodes selectively for meaningful cross-file continuations. Tracepoints are exhaustive, not selective.
- If improving an existing canvas, preserve verified nodes, edges, notes, and established workspace state. Re-layout or amend only what the audit shows should change.

## Resources

- `references/canvas-spec.md`: authoritative node, caller, layout, and validation rules.
- `scripts/analyze_kernel_source.py`: structured source inventory and evidence report.
- `scripts/layout_canvas.py`: fixed-column DAG ranking and Graphviz-assisted lane layout.
- `scripts/validate_canvas.py`: source-backed semantic and geometry validator.
