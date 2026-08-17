# Kernel Source Canvas Specification

## Contents

1. [Goal and inputs](#goal-and-inputs)
2. [Source analysis](#source-analysis)
3. [Entrance functions](#entrance-functions)
4. [Node types](#node-types)
5. [Edges and call evidence](#edges-and-call-evidence)
6. [Horizontal layout](#horizontal-layout)
7. [Vertical layout](#vertical-layout)
8. [Improving an existing canvas](#improving-an-existing-canvas)
9. [Validation checklist](#validation-checklist)

## Goal and inputs

Create an Obsidian `.canvas` JSON file for a Linux kernel C source file. Show important functions entered from the chosen caller scope, their internal call paths, relevant cross-file callees, and all tracepoints.

Required inputs:

- Local Linux kernel source root.
- Target C source path relative to that root.
- Caller scope relative to the root. Use `mm` for the developed memory-management convention.
- Output `.canvas` path.
- Existing workspace canvases when they establish a local visual style.

Do not assume the kernel tree is the current directory or `./linux`. Accept a user-supplied absolute target-file path or a kernel-root plus relative source path. If the requested source cannot be found in the current workspace, ask the user for its exact location before continuing. If more than one candidate exists, ask which one to use. Request the kernel source root as well when it cannot be derived reliably from the file path, because caller and external-definition checks require the surrounding tree.

A concise location question is sufficient:

```text
Where is the requested Linux kernel source file? Please provide its absolute path (and the kernel source root if it is not apparent from that path).
```

Prioritize readability and correctness over completeness or compactness.

## Source analysis

Use the local kernel tree as the source of truth.

- Prefer Universal Ctags JSON or `ctags -x --c-kinds=f` to identify function names and line ranges.
- Inspect each included function body.
- Verify every direct call, function reference, callback assignment, tracepoint emission, and external definition.
- Do not infer a relationship from names alone.
- Conditional definitions may share one displayed node when they represent the same function name.
- Record indirect evidence such as ops-table fields, inline wrappers, worker creation, or callback arguments for later validation.

## Entrance functions

An entrance is a target-file function reached from outside the target file by code in the selected caller scope.

- The target file never counts as its own external caller.
- Include direct calls from scoped C files.
- Include proved indirect calls from scoped code, including inline wrappers, ops tables, callback fields, and registered handlers.
- A public function called only outside the selected scope is not a scoped entrance.
- If a candidate root is not a scoped entrance, prune it. Promote included callees only when they themselves have scoped callers.
- Include an extra context root only when a requested path or an exhaustive tracepoint requires it. Mark it as an explicit validation exception rather than giving it a green note.

## Node types

Use text nodes. Keep node IDs unique and stable.

### Internal target functions

- One node per displayed target-file function.
- Label: `` `function_name()` ``.
- Default height: `60` px.
- Use no color field.
- Never duplicate a shared callee to simplify layout.

### Green entrance notes

Green notes are explanations for true scoped entrances only.

- Color: `4`.
- Required size: `560` px wide and `119` px high.
- Exactly one note per entrance and exactly one outgoing edge to that entrance.
- Align note and target centers horizontally.
- Position the note with `note.x = target.x - note.width - 96`.
- Do not give green notes to helpers, internal-only functions, or context roots.
- Do not list the target source file as a caller.

Required text form:

```text
<descriptive definition of what the function does and why it exists>.
- Caller files: `linux/mm/example.c`, `linux/fs/`, `linux/arch/`
    Called <how or when these callers reach the function>.
    Why: <why these callers need it>.
```

Caller listing:

- List exact caller files inside the selected scope.
- Collapse callers outside that scope to `linux/<top-level-folder>/`.
- List relevant caller files or folders without enumerating every call site.
- Keep the definition, Called, and Why lines descriptive.

### Yellow external callees

Yellow nodes represent functions defined outside the target file and called by displayed target functions.

- Color: `3`.
- One node per external function.
- Label: `` `mm/page-writeback.c:folio_wait_writeback()` `` using a path relative to the kernel root.
- Direction is always target function to external callee.
- Verify that the external function exists in the labeled source file.
- Select meaningful cross-file continuations rather than every trivial accessor.

### Purple tracepoints

Tracepoints are exhaustive for a new canvas.

- Scan every `trace_*()` call in the target source.
- Color: `6`.
- One node per unique tracepoint function.
- Label: `` `trace_mm_filemap_fault()` ``.
- Connect every emitting target function directly to the shared tracepoint node.
- If an emitter is otherwise omitted, add it as a context node.
- Keep purple nodes near emitters, preferably one column to the right.
- Do not bury a purple connector behind an unrelated yellow node.
- Do not put tracepoint descriptions inside green notes.

## Edges and call evidence

Every edge must contain:

```json
{
  "fromSide": "right",
  "toSide": "left"
}
```

Rules:

- Internal edge: direct call or proved function-reference/callback use.
- External edge: direct call or proved external callback reference.
- Trace edge: actual `trace_*()` emission in the source function body.
- Green edge: entrance note to its one target.
- Destination left edge must be strictly right of the source right edge.
- Do not add speculative edges.

## Horizontal layout

Use fixed columns with a default `560` px step:

- Column 1: `x = 760`
- Column 2: `x = 1320`
- Column 3: `x = 1880`
- Column 4: `x = 2440`
- Column 5: `x = 3000`

Extend the sequence for deeper paths.

Ranking procedure:

1. Assign roots to the first rank.
2. Assign every child at least one rank right of every displayed parent.
3. Place shared callees at the deepest rank required by any parent.
4. Walk callers from right to left and move each as far right as possible while keeping it one rank left of all children.
5. Keep external and tracepoint sinks immediately after their deepest displayed caller when possible.

This compaction minimizes avoidable horizontal connector length without duplicating nodes.

## Vertical layout

Build readable lanes rather than stacking nodes mechanically.

- Keep a parent close to its children.
- Align the primary child with the parent center whenever possible.
- Keep single-child chains straight.
- Arrange secondary branches above and below the primary lane.
- Give a shared callee one owning parent for its straight lane; route other callers to the same node.
- Separate unrelated lanes when space is needed.
- Prefer additional vertical space over breaking an important straight chain.
- Keep tracepoint branches short and clear.
- No node rectangles may overlap.

After automated layout, visually inspect at normal zoom. Geometry validation alone does not catch every connector that visually crosses a box.

## Improving an existing canvas

- Reuse its verified nodes, IDs, notes, edges, and source revision.
- Audit source accuracy before changing layout.
- Preserve true entrances and exhaustive tracepoint coverage.
- Measure canvas height, total vertical connector travel, straight primary edges, and connector-box intrusions before and after.
- Favor changes that shorten important lanes and clear tracepoint connectors without making the graph cramped.
- Re-run the complete validation checklist after every revision.

## Validation checklist

Before delivering the artifact, verify:

- JSON parses.
- Node IDs and edge IDs are unique.
- No dangling edges or duplicate displayed text exists.
- Every target node maps to a target-file function.
- No target function node is duplicated.
- Every internal edge has direct-call or callback evidence.
- Every yellow function exists in its labeled file.
- Every yellow edge points from a target function to a real external callee.
- Every target tracepoint call has one purple node.
- Every purple edge matches a real emitter.
- Every edge uses right-to-left-side metadata and a positive horizontal gap.
- No node rectangles overlap.
- Caller ranks are maximally compacted.
- Every true scoped entrance has exactly one fixed-size green note.
- No non-entrance has a green note.
- Green notes contain definition, Caller files, Called, and Why text.
- Green notes omit the target file from caller lists.
- Every root without a green note is an explicit context root.
- A final visual pass confirms readable lanes and clear tracepoint connectors.

Report the output path, node and edge totals, validation result, and any intentional context-root or indirect-call exceptions.
