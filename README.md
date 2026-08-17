# Kernel Source Canvas

Turn a Linux kernel C source file into a source-verified [Obsidian Canvas](https://obsidian.md/canvas) call graph.

![Full `mm/vmscan.c` canvas in Obsidian](assets/screenshots/vmscan-overview.png)

`kernel-src-canvas` is a Codex skill for tracing how a kernel source file is entered, following its important internal paths, and showing meaningful connections to the rest of the tree. It combines source analysis, deterministic layout, and validation so the result is useful for exploration rather than being only a generated diagram.

## What the canvas shows

- **Green notes:** externally reached entry functions and why their callers use them.
- **White nodes:** functions defined in the target source file.
- **Yellow nodes:** selected callees defined in other kernel source files.
- **Purple nodes:** every tracepoint emitted by the target file.

Shared functions remain shared nodes, and every displayed relationship must have source evidence. The complete graph and layout contract is documented in [the canvas specification](references/canvas-spec.md).

## Requirements

- Codex with skill support
- Python 3.10 or newer
- [Universal Ctags](https://ctags.io/)
- [Graphviz](https://graphviz.org/) (`dot`)
- A local Linux kernel source tree
- [Obsidian](https://obsidian.md/) to view and navigate the generated file

## Install

Ask Codex to install the repository:

```text
$skill-installer install the skill from https://github.com/bsuvonov/kernel-src-canvas
```

Use `/skills` to confirm that `kernel-src-canvas` is available. Restart Codex if a newly installed skill does not appear.

## Create a canvas

Invoke the skill explicitly and provide the kernel root, target file, caller scope, and output path:

```text
$kernel-src-canvas create and validate an Obsidian canvas for mm/vmscan.c.

Kernel root: /home/me/src/linux
Caller scope: mm
Output: /home/me/canvases/vmscan.canvas
```

Absolute source paths work too:

```text
$kernel-src-canvas create a canvas for /home/me/src/linux/mm/vmscan.c
and save it as /home/me/canvases/vmscan.canvas.
```

When the source location is missing or ambiguous, the skill asks for the exact code-file location before analyzing it. A clear kernel-canvas request may trigger the skill automatically, while `$kernel-src-canvas` makes the choice explicit.

To audit and improve an existing graph:

```text
$kernel-src-canvas audit and improve /home/me/canvases/vmscan.canvas
against /home/me/src/linux/mm/vmscan.c, preserving verified content.
```

## Open the result in Obsidian

An Obsidian vault is an ordinary directory. Copy the generated file into the vault, quoting the path because its name contains a space:

```bash
cp /home/me/canvases/vmscan.canvas "$HOME/Obsidian\ Vault/"
```

Launch Obsidian using the command provided by your installation, for example:

```bash
# Native package or AppImage integration
obsidian

# Flatpak
flatpak run md.obsidian.Obsidian
```

Open **Obsidian Vault**, then select `vmscan.canvas` in the Files pane. When the vault is already open, the copied canvas normally appears there automatically. You can also ask the skill to write directly into the vault:

```text
Output: /home/me/Obsidian\ Vault/vmscan.canvas
```

## What it looks like

### Entrances, call paths, and tracepoints

Green entrance explanations lead into target-file functions, while purple tracepoints branch directly from their real emitters.

![Entrance paths and tracepoints from `mm/vmscan.c`](assets/screenshots/vmscan-entry-paths.png)

### Deeper reclaim paths

The fixed left-to-right columns keep deeper multi-generation LRU paths and cross-file calls readable.

![Multi-generation LRU paths from `mm/vmscan.c`](assets/screenshots/vmscan-lru-paths.png)

### A smaller source file

The same conventions scale down to a more compact graph such as `mm/readahead.c`.

![Canvas generated for `mm/readahead.c`](assets/screenshots/readahead-overview.png)

## How it works

| Component | Purpose |
| --- | --- |
| [`analyze_kernel_source.py`](scripts/analyze_kernel_source.py) | Inventories definitions, scoped entrances, calls, function references, and tracepoints. |
| [`layout_canvas.py`](scripts/layout_canvas.py) | Assigns fixed call-depth columns and Graphviz-assisted vertical lanes. |
| [`validate_canvas.py`](scripts/validate_canvas.py) | Checks source evidence, node roles, entrance coverage, tracepoints, edges, and geometry. |

The skill still performs a final visual pass because a geometrically valid graph can contain awkward connector crossings. See [`SKILL.md`](SKILL.md) for the complete workflow.
