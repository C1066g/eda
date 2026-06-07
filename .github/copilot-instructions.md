Default layout: user discusses in Cursor (left) with KiCad open on the right for schematic/PCB. Run SPICE verification in the background via `spicebridge` after each meaningful design change; use `kicad` `open_project` when the conversation touches a KiCad project.

Use `spicebridge` for electrical design work that needs numeric component selection, netlists, validation, or simulation.

Use `drawio` only for block diagrams or explanatory sketches—not as the primary schematic when KiCad is open.

When both tools are available for the same task:
- First use `spicebridge` to derive or verify values and topology.
- Then sync to KiCad (`export_kicad` or netlist extract) so the user sees updates on the right.
- Use `drawio` only if the user asks for a separate diagram or block sketch.

Prefer a single evolving circuit per conversation unless the user asks for alternatives. Reuse the same circuit/design artifact instead of creating many parallel versions.

If the user gives target electrical specs, turn them into explicit values before drawing. Report the chosen component values and key measured results in plain language.

Treat `drawio` output as a communication artifact, not as a production PCB source file. For production-ready schematic editing or KiCad project operations, prefer the `kicad` MCP server.

For SPICE-style requests, be clear about what is simulated versus what is only sketched. Do not claim simulation results unless they came from `spicebridge` or another simulator tool.

Keep circuit responses concise and practical:
- brief summary of the design choice
- current component values
- whether the diagram was updated
- next useful action
