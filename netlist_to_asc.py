#!/usr/bin/env python3
"""Convert SPICE netlist to LTspice .asc schematic with auto-placement.

The key insight: LLMs are good at generating code, and SPICE netlists ARE code.
This converter bridges netlist code → visual schematic, enabling an LLM-driven
circuit design workflow.
"""

import sys
import re
from collections import defaultdict, deque

# ── Symbol mapping ──────────────────────────────────────────────────────────

SYMBOL_MAP = {
    'R': 'res',     'C': 'cap',     'L': 'ind',
    'V': 'voltage', 'I': 'current',
    'M': 'nmos',    'Q': 'npn',     'D': 'diode',
    'E': 'e',       'G': 'g',       'H': 'h',      'F': 'f',
}

# For each symbol, list pin names in order (used to match netlist pin order)
# Then each pin's offset from the symbol origin in grid units
PIN_OFFSETS = {
    'res':     [(-1, 0), (1, 0)],          # 1 (left), 2 (right)
    'cap':     [(-1, 0), (1, 0)],
    'ind':     [(-1, 0), (1, 0)],
    'voltage': [(0, -1), (0, 1)],          # + (top), - (bottom)
    'current': [(0, -1), (0, 1)],
    'nmos':    [(1, -1), (-1, 0), (1, 1)], # D(top-right), G(left), S(bot-right)
    'pmos':    [(1, -1), (-1, 0), (1, 1)], # D, G, S — same pin layout
    'npn':     [(1, -1), (-1, 0), (1, 1)], # C(top), B(left), E(bottom)
    'pnp':     [(1, -1), (-1, 0), (1, 1)],
    'diode':   [(-1, 0), (1, 0)],          # anode(left), cathode(right)
    'e':       [(-1, 0), (-1, 1), (1, -1), (1, 1)], # in+/in-/out+/out-
    'g':       [(-1, 0), (-1, 1), (1, -1), (1, 1)],
    'h':       [(-1, 0), (-1, 1), (1, -1), (1, 1)],
    'f':       [(-1, 0), (-1, 1), (1, -1), (1, 1)],
}

GRID = 32
MARGIN = 64
COL_SPACING = 224   # pixels between columns
ROW_SPACING = 96    # pixels between rows

# ── Parser ──────────────────────────────────────────────────────────────────

def parse_netlist(content):
    """Parse SPICE netlist. Returns (components, directives)."""
    components = []
    directives = []

    # Merge continuation lines
    lines = content.split('\n')
    merged = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith('*') or s.startswith('#'):
            directives.append(s)
            continue
        if s.startswith('+'):
            if merged:
                merged[-1] += ' ' + s[1:].strip()
            continue
        merged.append(s)

    for line in merged:
        line = line.strip()
        if not line:
            continue

        ch = line[0].upper()

        if ch == '.':
            directives.append(line)
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        ref = parts[0]
        typ = ref[0].upper()

        if typ == 'M' and len(parts) >= 6:
            components.append({
                'ref': ref, 'type': 'M',
                'nets': [parts[1], parts[2], parts[3]],  # D, G, S
                'model': parts[5], 'value': '', 'params': ' '.join(parts[6:]),
            })

        elif typ in ('R', 'C', 'L') and len(parts) >= 4:
            components.append({
                'ref': ref, 'type': typ,
                'nets': [parts[1], parts[2]],
                'value': parts[3], 'model': '', 'params': '',
            })

        elif typ in ('V', 'I') and len(parts) >= 4:
            # Re-merge to handle SINE(...) with spaces inside parens
            raw = ' '.join(parts[3:])
            value, params = _split_value_params(raw)
            components.append({
                'ref': ref, 'type': typ,
                'nets': [parts[1], parts[2]],
                'value': value, 'model': '', 'params': params,
            })

        elif typ == 'D' and len(parts) >= 4:
            components.append({
                'ref': ref, 'type': 'D',
                'nets': [parts[1], parts[2]],  # anode, cathode
                'value': parts[3], 'model': parts[3], 'params': '',
            })

        elif typ == 'Q' and len(parts) >= 6:
            components.append({
                'ref': ref, 'type': 'Q',
                'nets': [parts[1], parts[2], parts[3]],  # C, B, E
                'model': parts[5], 'value': '', 'params': ' '.join(parts[6:]),
            })

        elif typ in ('E', 'G') and len(parts) >= 5:
            # SPICE: E<name> <out+> <out-> <in+> <in-> <gain>
            # Reorder to match symbol pin order: in+, in-, out+, out-
            components.append({
                'ref': ref, 'type': typ,
                'nets': [parts[3], parts[4], parts[1], parts[2]],
                'value': parts[5] if len(parts) > 5 else '', 'model': '', 'params': '',
            })

        elif typ == 'X' and len(parts) >= 3:
            # Find subcircuit name (last non-param token)
            i = len(parts) - 1
            while i > 1 and parts[i].startswith(('W=', 'L=', 'M=')):
                i -= 1
            sub_name = parts[i]
            nets = parts[1:i]
            params = ' '.join(parts[i+1:]) if i+1 < len(parts) else ''
            components.append({
                'ref': ref, 'type': 'X',
                'nets': nets,
                'value': sub_name, 'model': sub_name, 'params': params,
            })

    return components, directives


def _split_value_params(raw):
    """Split a V/I value string into value and params.

    E.g. 'DC 5V AC 1' → ('DC 5V', 'AC 1')
         'SINE(0 1 1k)' → ('SINE(0 1 1k)', '')
         'AC 1 SIN(0 1 1k)' → ('AC 1', 'SIN(0 1 1k)')
    """
    # Find first open-paren — everything after is part of a waveform spec
    m = re.search(r'([A-Z]+)\s*\(', raw)
    if m:
        # Split before the waveform keyword
        idx = raw.index(m.group(0))
        before = raw[:idx].strip()
        after = raw[idx:].strip()
        if before:
            return before, after
        return after, ''

    return raw, ''


def get_symbol(comp):
    """Map component to LTspice symbol."""
    t = comp['type']
    if t == 'M':
        model = comp.get('model', '').upper()
        return 'pmos' if ('P' in model and 'N' not in model) else 'nmos'
    if t == 'Q':
        model = comp.get('model', '').upper()
        return 'pnp' if 'PNP' in model else 'npn'
    return SYMBOL_MAP.get(t, 'res')


def get_pin_offsets(comp):
    """Get list of (dx, dy) offsets for each pin of this component."""
    sym = get_symbol(comp)
    return PIN_OFFSETS.get(sym, [(0, -1), (1, 0), (0, 1)])


# ── Layout ──────────────────────────────────────────────────────────────────

def layout(components):
    """Auto-place components.

    Returns dict: ref -> {'x': int, 'y': int, 'rotation': str, 'symbol': str}
    """
    if not components:
        return {}

    # Build net → component graph
    net_comps = defaultdict(set)
    for c in components:
        for net in c['nets']:
            if net != '0':
                net_comps[net].add(c['ref'])

    # Determine sources (voltage/current sources, or refs starting with 'V')
    sources = []
    for c in components:
        if c['type'] in ('V', 'I'):
            sources.append(c['ref'])

    # BFS columns from sources
    col = {}
    q = deque()
    for ref in sources:
        col[ref] = 0
        q.append(ref)

    while q:
        ref = q.popleft()
        cur = col[ref]
        comp = next((c for c in components if c['ref'] == ref), None)
        if not comp:
            continue
        for net in comp['nets']:
            if net == '0':
                continue
            for other in net_comps.get(net, set()):
                if other != ref and other not in col:
                    col[other] = cur + 1
                    q.append(other)

    for c in components:
        if c['ref'] not in col:
            col[c['ref']] = 0

    # Group by column
    cols = defaultdict(list)
    for c in components:
        cols[col[c['ref']]].append(c)

    # Within each column, sort: voltage sources at top, then signal, then ground-referenced
    result = {}
    for col_idx in sorted(cols):
        col_comps = cols[col_idx]
        # Sort heuristic
        def sort_key(c):
            nets = c['nets']
            has_gnd = '0' in nets
            is_source = c['type'] in ('V', 'I')
            # Sources at top, ground-referenced at bottom
            if is_source: return (0, c['ref'])
            if has_gnd: return (2, c['ref'])
            return (1, c['ref'])
        col_comps.sort(key=sort_key)

        y = 2
        for c in col_comps:
            sym = get_symbol(c)
            rot = 'R0'
            if c['type'] in ('V', 'I'):
                rot = 'R0'
            elif c['type'] == 'M' and sym == 'pmos':
                rot = 'M180'

            result[c['ref']] = {
                'x': MARGIN + col_idx * COL_SPACING,
                'y': MARGIN + y * ROW_SPACING,
                'rotation': rot,
                'symbol': sym,
            }
            y += 1

    return result


# ── ASC generation ──────────────────────────────────────────────────────────

def generate_asc(components, directives, positions):
    """Generate .asc schematic file."""
    out = []
    out.append('Version 4')
    out.append('SHEET 1 1600 1200')

    # Collect nets → (ref, pin_index) for wiring
    net_pins = defaultdict(list)  # net → [(ref, pin_idx, pin_x, pin_y)]

    for c in components:
        ref = c['ref']
        if ref not in positions:
            continue
        pos = positions[ref]
        cx, cy = pos['x'], pos['y']
        offsets = get_pin_offsets(c)
        nets = c['nets']

        for i, net in enumerate(nets):
            if i < len(offsets):
                dx, dy = offsets[i]
                px = cx + dx * GRID
                py = cy + dy * GRID
                net_pins[net].append((ref, i, px, py))

    # SYMBOL entries
    for c in components:
        ref = c['ref']
        if ref not in positions:
            continue
        pos = positions[ref]
        sym = pos['symbol']
        x, y, rot = pos['x'], pos['y'], pos['rotation']

        out.append(f'SYMBOL {sym} {x} {y} {rot}')
        out.append(f'SYMATTR InstName {ref}')

        if c['type'] in ('M', 'D', 'Q'):
            out.append(f'SYMATTR Value {c["model"]}')
        else:
            out.append(f'SYMATTR Value {c["value"]}')

        if c.get('params'):
            out.append(f'SYMATTR Value2 {c["params"]}')

    # WIRE entries — route each net
    wire_lines = []
    for net, pins in net_pins.items():
        if net == '0':
            continue  # ground handled by FLAG
        if len(pins) < 2:
            continue

        xs = sorted(set(p[2] for p in pins))
        ys = sorted(set(p[3] for p in pins))

        # Choose a routing strategy:
        # If all pins are in the same column (same x), use a vertical bus
        # If all in same row, horizontal bus
        # Otherwise, L-shaped routing from each pin to a common bus

        if len(set(xs)) == 1:
            # All same column — vertical wire
            y_min, y_max = min(ys), max(ys)
            wire_lines.append(f'WIRE {xs[0]} {y_min} {xs[0]} {y_max}')
        elif len(set(ys)) == 1:
            # All same row — horizontal wire
            x_min, x_max = min(xs), max(xs)
            wire_lines.append(f'WIRE {x_min} {ys[0]} {x_max} {ys[0]}')
        else:
            # Multi-column, multi-row: route to a horizontal bus at average y
            avg_y = sum(ys) // len(ys)
            # Vertical segments from each pin to bus
            for _, _, px, py in pins:
                if py != avg_y:
                    wire_lines.append(f'WIRE {px} {py} {px} {avg_y}')
            # Horizontal bus
            x_min, x_max = min(xs), max(xs)
            wire_lines.append(f'WIRE {x_min} {avg_y} {x_max} {avg_y}')

    # Add WIRE entries (sorted for determinism)
    for w in sorted(set(wire_lines)):
        out.append(w)

    # FLAG entries — net labels at key nodes
    for net, pins in net_pins.items():
        if not pins:
            continue
        # Use first pin's position for label placement
        _, _, px, py = pins[0]
        if net == '0':
            out.append(f'FLAG {px} {py+16} 0')
        elif net.upper() in ('VDD', 'VCC', 'VP', 'VDD!'):
            out.append(f'FLAG {px} {py-16} {net}')
        elif net.lower() in ('in', 'out', 'input', 'output'):
            out.append(f'FLAG {px} {py} {net}')
        # Also label internal nets that aren't just node numbers
        elif not net.isdigit():
            out.append(f'FLAG {px} {py} {net}')

    # Directives as TEXT
    y_text = 1100
    for d in reversed(directives):
        if d.startswith('.'):
            out.append(f'TEXT {MARGIN} {y_text} Left 2 !{d}')
        else:
            out.append(f'TEXT {MARGIN} {y_text} Left 2 ;{d.lstrip("*# ")}')
        y_text -= 24

    out.append('')
    return '\n'.join(out)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: netlist_to_asc.py <netlist.cir> [output.asc]")
        print("  Converts a SPICE netlist to an LTspice .asc schematic")
        print("  with automatic component placement and wire routing.")
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else \
        infile.replace('.cir', '.asc').replace('.net', '.asc')

    with open(infile) as f:
        content = f.read()

    components, directives = parse_netlist(content)
    print(f"Components ({len(components)}):")
    for c in components:
        print(f"  {c['ref']} ({c['type']}): nets={c['nets']} value={c.get('value','')}")

    positions = layout(components)
    print(f"\nLayout computed for {len(positions)} components")

    asc = generate_asc(components, directives, positions)
    with open(outfile, 'w') as f:
        f.write(asc)

    print(f"Written: {outfile}")


if __name__ == '__main__':
    main()
