#!/usr/bin/env python3
"""Precise SPICE netlist → schematic renderer.

Uses exact LTspice symbol pin positions and proper Manhattan wire routing.
"""

import sys, math, re
from collections import defaultdict, deque

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Arc, Polygon, FancyBboxPatch
import matplotlib.patches as mpatches

# ── LTspice symbol definitions (pin positions in grid units) ──────────────

SCALE = 5  # LTspice grid → render pixels

SYMBOLS = {
    'nmos': {
        'bbox': (0, 0, 48, 96),
        'pins': [('D', 48, 0, 'r'), ('G', 0, 80, 'l'), ('S', 48, 96, 'r')],
        'type': 'transistor',
    },
    'pmos': {
        'bbox': (0, 0, 48, 96),
        'pins': [('D', 48, 0, 'r'), ('G', 0, 80, 'l'), ('S', 48, 96, 'r')],
        'type': 'transistor',
    },
    'res': {
        'bbox': (0, 16, 32, 80),
        'pins': [('A', 16, 16, 'u'), ('B', 16, 96, 'd')],
        'type': 'passive',
    },
    'cap': {
        'bbox': (0, 0, 32, 64),
        'pins': [('A', 16, 0, 'u'), ('B', 16, 64, 'd')],
        'type': 'passive',
    },
    'ind': {
        'bbox': (0, 16, 32, 80),
        'pins': [('A', 16, 16, 'u'), ('B', 16, 96, 'd')],
        'type': 'passive',
    },
    'voltage': {
        'bbox': (-32, 16, 64, 80),
        'pins': [('+', 0, 16, 'u'), ('-', 0, 96, 'd')],
        'type': 'source',
    },
    'current': {
        'bbox': (-32, 16, 64, 80),
        'pins': [('+', 0, 16, 'u'), ('-', 0, 96, 'd')],
        'type': 'source',
    },
    'e': {
        'bbox': (-48, 16, 80, 80),
        'pins': [('+', 0, 16, 'u'), ('-', 0, 96, 'd'),
                 ('P', -48, 32, 'l'), ('N', -48, 80, 'l')],
        'type': 'vcvs',
    },
    'g': {
        'bbox': (-48, 16, 80, 80),
        'pins': [('+', 0, 16, 'u'), ('-', 0, 96, 'd'),
                 ('P', -48, 32, 'l'), ('N', -48, 80, 'l')],
        'type': 'vcvs',
    },
    'diode': {
        'bbox': (0, 0, 32, 64),
        'pins': [('A', 16, 0, 'u'), ('C', 16, 64, 'd')],
        'type': 'passive',
    },
    'npn': {
        'bbox': (0, 0, 48, 96),
        'pins': [('C', 48, 0, 'r'), ('B', 0, 80, 'l'), ('E', 48, 96, 'r')],
        'type': 'transistor',
    },
    'pnp': {
        'bbox': (0, 0, 48, 96),
        'pins': [('C', 48, 0, 'r'), ('B', 0, 80, 'l'), ('E', 48, 96, 'r')],
        'type': 'transistor',
    },
}

# Component type → symbol name
TYPE_SYMBOL = {
    'R': 'res', 'C': 'cap', 'L': 'ind',
    'V': 'voltage', 'I': 'current',
    'M': 'nmos', 'D': 'diode',
    'Q': 'npn', 'E': 'e', 'G': 'g',
    'X': 'res',  # subcircuit → generic box
}

# ── Netlist parser ─────────────────────────────────────────────────────────

def parse_netlist(content):
    components, directives = [], []
    lines = content.split('\n')
    merged = []
    for line in lines:
        s = line.strip()
        if not s: continue
        if s.startswith('*') or s.startswith('#'):
            directives.append(s); continue
        if s.startswith('+'):
            if merged: merged[-1] += ' ' + s[1:].strip()
            continue
        merged.append(s)

    for line in merged:
        line = line.strip()
        if not line: continue
        ch = line[0].upper()
        if ch == '.':
            directives.append(line); continue
        parts = line.split()
        if len(parts) < 3: continue
        ref = parts[0]; typ = ref[0].upper()

        if typ == 'M' and len(parts) >= 6:
            components.append({'ref': ref, 'type': 'M',
                'nets': [parts[1], parts[2], parts[3]],
                'model': parts[5], 'value': '', 'params': ' '.join(parts[6:])})
        elif typ in ('R','C','L') and len(parts) >= 4:
            components.append({'ref': ref, 'type': typ,
                'nets': [parts[1], parts[2]],
                'value': parts[3], 'model': '', 'params': ''})
        elif typ in ('V','I') and len(parts) >= 4:
            raw = ' '.join(parts[3:])
            m = re.search(r'([A-Z]+)\s*\(', raw)
            if m:
                idx = raw.index(m.group(0))
                before, after = raw[:idx].strip(), raw[idx:].strip()
                value, params = (before, after) if before else (after, '')
            else:
                value, params = raw, ''
            components.append({'ref': ref, 'type': typ,
                'nets': [parts[1], parts[2]],
                'value': value, 'model': '', 'params': params})
        elif typ == 'D' and len(parts) >= 4:
            components.append({'ref': ref, 'type': 'D',
                'nets': [parts[1], parts[2]],
                'value': parts[3], 'model': parts[3], 'params': ''})
        elif typ in ('E','G') and len(parts) >= 5:
            components.append({'ref': ref, 'type': typ,
                'nets': [parts[3], parts[4], parts[1], parts[2]],
                'value': parts[5] if len(parts) > 5 else '',
                'model': '', 'params': ''})

    return components, directives


# ── Layout engine ──────────────────────────────────────────────────────────

class LayeredLayout:
    """Sugiyama-style layered graph layout for circuit schematics."""

    def __init__(self, components):
        self.components = {c['ref']: c for c in components}
        self.nets = defaultdict(set)
        for c in components:
            for net in c['nets']:
                if net != '0':
                    self.nets[net].add(c['ref'])

        # Build adjacency
        self.adj = defaultdict(set)  # ref → downstream refs
        self.rev_adj = defaultdict(set)  # ref → upstream refs
        for net, refs in self.nets.items():
            for r1 in refs:
                for r2 in refs:
                    if r1 != r2:
                        self.adj[r1].add(r2)

    def layout(self, canvas_w=1600, canvas_h=900):
        """Returns {ref: (x, y)} in render pixels."""
        # 1. Layer assignment (BFS from sources)
        sources = [c['ref'] for c in self.components.values()
                   if c['type'] in ('V', 'I')]
        layers = defaultdict(list)
        assigned = {}

        q = deque()
        for s in sources:
            assigned[s] = 0
            layers[0].append(s)
            q.append(s)

        while q:
            ref = q.popleft()
            cur = assigned[ref]
            for down in self.adj.get(ref, set()):
                if down not in assigned:
                    assigned[down] = cur + 1
                    layers[cur + 1].append(down)
                    q.append(down)

        # Unassigned → layer 0
        for c in self.components:
            if c not in assigned:
                assigned[c] = 0
                layers[0].append(c)

        max_layer = max(layers.keys()) if layers else 0

        # 2. Barycenter crossing minimization
        for _ in range(4):
            for l in range(1, max_layer + 1):
                bary = {}
                for ref in layers[l]:
                    neighbors = [assigned[n] for n in self.rev_adj.get(ref, set())
                                if n in assigned]
                    bary[ref] = sum(neighbors) / len(neighbors) if neighbors else 0
                layers[l].sort(key=lambda r: bary.get(r, 0))

        # 3. Assign coordinates
        positions = {}
        x_spacing = canvas_w / (max_layer + 2)
        y_spacing = 100

        for l in range(max_layer + 1):
            refs = layers[l]
            # Sort within layer: voltage sources top, ground-referenced bottom
            def sort_key(r):
                c = self.components.get(r)
                if not c: return (0, r)
                has_0 = '0' in c['nets']
                is_v = c['type'] in ('V','I')
                if is_v: return (0, r)
                if has_0: return (2, r)
                return (1, r)
            refs.sort(key=sort_key)

            x = 120 + l * x_spacing
            total_h = (len(refs) - 1) * y_spacing
            y_start = canvas_h / 2 - total_h / 2

            for i, ref in enumerate(refs):
                positions[ref] = (x, y_start + i * y_spacing)

        return positions


# ── Manhattan router ───────────────────────────────────────────────────────

class ManhattanRouter:
    """Route wires between exact pin positions using Manhattan geometry."""

    def __init__(self, components, positions):
        self.components = {c['ref']: c for c in components}
        self.positions = positions
        self.used_y = set()  # track used trunk y positions

    def compute_pin_abs(self, ref):
        """Get absolute pin positions for a component."""
        if ref not in self.positions or ref not in self.components:
            return []
        comp = self.components[ref]
        x0, y0 = self.positions[ref]
        sym_name = self._symbol_for(comp)
        sym = SYMBOLS.get(sym_name, SYMBOLS['res'])
        pins = []
        for i, (name, px, py, direction) in enumerate(sym['pins']):
            if i < len(comp['nets']):
                pins.append({
                    'name': name, 'net': comp['nets'][i],
                    'x': x0 + px * SCALE / 4,  # Scale LTspice grid → render px
                    'y': y0 + py * SCALE / 4,
                    'direction': direction,
                })
        return pins

    def route(self):
        """Return list of wire segments: [(x1,y1,x2,y2), ...]"""
        # Collect all pins by net
        net_pins = defaultdict(list)
        for ref in self.components:
            for pin in self.compute_pin_abs(ref):
                if pin['net'] != '0':
                    net_pins[pin['net']].append(pin)

        segments = []
        trunk_y_offset = 0

        for net, pins in net_pins.items():
            if len(pins) < 2:
                continue

            # Sort pins by x
            pins_sorted = sorted(pins, key=lambda p: p['x'])
            x_min = pins_sorted[0]['x']
            x_max = pins_sorted[-1]['x']

            # Choose trunk y: try average y first, then offset if conflict
            avg_y = sum(p['y'] for p in pins) / len(pins)
            # Quantize to avoid too-close trunks
            trunk_y = round(avg_y / 10) * 10 + trunk_y_offset * 6
            trunk_y_offset += 1

            # Vertical segments: pin → trunk
            for p in pins:
                if abs(p['y'] - trunk_y) > 2:
                    segments.append((p['x'], p['y'], p['x'], trunk_y))

            # Horizontal trunk
            if len(pins_sorted) >= 2:
                segments.append((x_min, trunk_y, x_max, trunk_y))

        return segments

    def _symbol_for(self, comp):
        t = comp['type']
        if t == 'M':
            model = comp.get('model', '').upper()
            return 'pmos' if ('P' in model and 'N' not in model) else 'nmos'
        if t == 'Q':
            model = comp.get('model', '').upper()
            return 'pnp' if 'PNP' in model else 'npn'
        return TYPE_SYMBOL.get(t, 'res')


# ── Drawer ─────────────────────────────────────────────────────────────────

class SchematicDrawer:
    """Draw circuit symbols and wires on a matplotlib canvas."""

    def __init__(self, ax, components, positions, wire_segments):
        self.ax = ax
        self.components = {c['ref']: c for c in components}
        self.positions = positions
        self.wire_segments = wire_segments

        # Scale factor: LTspice grid → render
        self.s = SCALE / 4  # LTspice uses grid/4 for pin offsets within symbol

    def draw_all(self):
        self._draw_wires()
        for ref in self.components:
            if ref in self.positions:
                self._draw_component(ref)

    def _draw_wires(self):
        for x1, y1, x2, y2 in self.wire_segments:
            self.ax.plot([x1, x2], [y1, y2], 'k-', linewidth=1.2, alpha=0.7)

    def _draw_component(self, ref):
        comp = self.components[ref]
        x, y = self.positions[ref]
        t = comp['type']
        sym = self._symbol_for(comp)
        spec = SYMBOLS.get(sym)

        if sym in ('res',):
            self._draw_resistor(x, y, spec, comp)
        elif sym == 'cap':
            self._draw_capacitor(x, y, spec, comp)
        elif sym == 'ind':
            self._draw_inductor(x, y, spec, comp)
        elif sym in ('voltage',):
            self._draw_voltage_source(x, y, spec, comp)
        elif sym in ('current',):
            self._draw_current_source(x, y, spec, comp)
        elif sym in ('nmos', 'pmos'):
            self._draw_mosfet(x, y, spec, comp, sym)
        elif sym in ('npn', 'pnp'):
            self._draw_bjt(x, y, spec, comp, sym)
        elif sym == 'diode':
            self._draw_diode(x, y, spec, comp)
        elif sym in ('e', 'g'):
            self._draw_vcvs(x, y, spec, comp)
        else:
            self._draw_box(x, y, spec, comp)

        # Label
        val = comp.get('value', '') or comp.get('model', '')
        bbox_h = (spec['bbox'][3] - spec['bbox'][1]) * self.s
        label_y = y + bbox_h + 14
        self.ax.text(x, label_y, ref, ha='center', va='top',
                    fontsize=9, fontfamily='monospace', fontweight='bold', color='#1a1a1a')
        if val and val != ref:
            self.ax.text(x, label_y + 12, val, ha='center', va='top',
                        fontsize=7.5, fontfamily='monospace', color='#666666')

    def _resistor_pin_abs(self, x, y, spec):
        """Compute absolute pin A and B positions."""
        s = self.s
        bx, by, bw, bh = spec['bbox']
        pins = spec['pins']
        # Pin A at (bx+pin_ax, by+pin_ay), pin B at (bx+pin_bx, by+pin_by)
        pa = (x + (pins[0][1] - bw/2) * s, y + (pins[0][2] - bh/2) * s)
        pb = (x + (pins[1][1] - bw/2) * s, y + (pins[1][2] - bh/2) * s)
        return pa, pb

    def _draw_resistor(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        pa, pb = self._resistor_pin_abs(x, y, spec)
        x1, y1 = pa; x2, y2 = pb

        # Resistor: zigzag between pa and pb (vertical)
        n = 5
        h_seg = (y2 - y1) / (2*n + 1)
        width = bw * s * 1.2
        xs_zig = [x1]
        for i in range(n):
            xs_zig.extend([x1 - width/2, x1 + width/2])
        xs_zig.append(x2)
        ys_zig = [y1]
        for i in range(1, 2*n + 1):
            ys_zig.append(y1 + i * h_seg)
        ys_zig.append(y2)
        self.ax.plot(xs_zig, ys_zig, 'k-', linewidth=1.8, solid_capstyle='round')

        # Wire extensions
        self.ax.plot([x1, x1], [y1 - 16, y1], 'k-', linewidth=1.2)
        self.ax.plot([x2, x2], [y2, y2 + 16], 'k-', linewidth=1.2)

    def _draw_capacitor(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        cx = x + (spec['pins'][0][1] - bw/2) * s
        cy_top = y + (spec['pins'][0][2] - bh/2) * s
        cy_bot = y + (spec['pins'][1][2] - bh/2) * s
        gap = 6
        plate_h = bh * s * 0.35

        # Plates
        self.ax.plot([cx - gap, cx - gap], [cy_top + 8, cy_top + 8 + plate_h],
                    'k-', linewidth=2.5)
        self.ax.plot([cx + gap, cx + gap], [cy_bot - 8 - plate_h, cy_bot - 8],
                    'k-', linewidth=2.5)
        # Extensions
        self.ax.plot([cx, cx], [cy_top, cy_top + 8], 'k-', linewidth=1.2)
        self.ax.plot([cx, cx], [cy_bot - 8, cy_bot], 'k-', linewidth=1.2)

    def _draw_inductor(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        cx = x + (spec['pins'][0][1] - bw/2) * s
        cy_top = y + (spec['pins'][0][2] - bh/2) * s
        cy_bot = y + (spec['pins'][1][2] - bh/2) * s
        r = bh * s * 0.08
        n = 4
        dy = (cy_bot - cy_top - 16) / (2*n)
        for i in range(n):
            arc_cy = cy_top + 8 + dy + i * 2 * dy
            arc = Arc((cx - r, arc_cy), 2*r, dy*2, angle=0, theta1=90, theta2=270,
                     linewidth=1.5, color='black')
            self.ax.add_patch(arc)
            arc2 = Arc((cx + r, arc_cy + dy), 2*r, dy*2, angle=0, theta1=270, theta2=90,
                      linewidth=1.5, color='black')
            self.ax.add_patch(arc2)
        self.ax.plot([cx, cx], [cy_top, cy_top + 8], 'k-', linewidth=1.2)
        self.ax.plot([cx, cx], [cy_bot - 8, cy_bot], 'k-', linewidth=1.2)

    def _draw_voltage_source(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        cx = x + (spec['pins'][0][1] - bw/2) * s
        cy_top = y + (spec['pins'][0][2] - bh/2) * s
        cy_bot = y + (spec['pins'][1][2] - bh/2) * s
        r = 16
        circle = Circle((cx, (cy_top + cy_bot)/2), r, fill=True,
                       facecolor='white', edgecolor='black', linewidth=2, zorder=2)
        self.ax.add_patch(circle)
        self.ax.text(cx, (cy_top + cy_bot)/2 + 2, '~', ha='center', va='center',
                    fontsize=11, fontweight='bold', zorder=3)
        self.ax.plot([cx, cx], [cy_top, cy_top + 8], 'k-', linewidth=1.2)
        self.ax.plot([cx, cx], [cy_bot - 8, cy_bot], 'k-', linewidth=1.2)

    def _draw_current_source(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        cx = x + (spec['pins'][0][1] - bw/2) * s
        cy_top = y + (spec['pins'][0][2] - bh/2) * s
        cy_bot = y + (spec['pins'][1][2] - bh/2) * s
        r_outer, r_inner = 16, 10
        mid_y = (cy_top + cy_bot)/2
        Circle((cx, mid_y), r_outer, fill=True, facecolor='white',
               edgecolor='black', linewidth=2, zorder=2).set_transform(self.ax.transData)
        self.ax.add_patch(Circle((cx, mid_y), r_outer, fill=True, facecolor='white',
                                 edgecolor='black', linewidth=2, zorder=2))
        self.ax.add_patch(Circle((cx, mid_y), r_inner, fill=False,
                                 edgecolor='black', linewidth=1.5, zorder=3))
        self.ax.annotate('', xy=(cx, mid_y + 8), xytext=(cx, mid_y - 8),
                        arrowprops=dict(arrowstyle='->', lw=2, color='black'), zorder=4)
        self.ax.plot([cx, cx], [cy_top, mid_y - r_outer], 'k-', linewidth=1.2)
        self.ax.plot([cx, cx], [mid_y + r_outer, cy_bot], 'k-', linewidth=1.2)

    def _draw_mosfet(self, x, y, spec, comp, sym_type):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        w, h = bw * s, bh * s
        # Origin is top-left of bbox
        ox = x + (bx - bw/2) * s
        oy = y + (by - bh/2) * s

        # Gate (left edge) — pin is at (bx+0, by+80) relative
        gx = ox  # left edge
        gy = oy + h * 0.83  # gate pin y relative

        # Drain (top right)
        dx = ox + w
        dy = oy

        # Source (bottom right)
        sx = ox + w
        sy = oy + h

        # Channel (vertical line on right)
        self.ax.plot([ox + w*0.8, ox + w*0.8], [oy + h*0.1, oy + h*0.9],
                    'k-', linewidth=2)

        # Gate (vertical line on left)
        gate_right = ox + w*0.4
        self.ax.plot([gate_right, gate_right], [oy + h*0.25, oy + h*0.75],
                    'k-', linewidth=1.5)

        # Gate input wire
        self.ax.plot([ox - 16, gate_right], [gy, gy], 'k-', linewidth=1.2)

        # Drain wire
        self.ax.plot([ox + w*0.8, ox + w*0.8], [oy, dy], 'k-', linewidth=1.2)
        self.ax.plot([ox + w*0.8, ox + w*0.8 + 16], [oy, oy], 'k-', linewidth=1.2)

        # Source wire
        self.ax.plot([ox + w*0.8, ox + w*0.8], [oy + h*0.9, sy], 'k-', linewidth=1.2)
        self.ax.plot([ox + w*0.8, ox + w*0.8 + 16], [sy, sy], 'k-', linewidth=1.2)

        # Substrate arrow (pointing inward for NMOS, outward for PMOS)
        arrow_dir = -1 if sym_type == 'nmos' else 1
        arr_y = oy + h*0.5
        self.ax.annotate('', xy=(ox + w*0.3, arr_y + arrow_dir*10),
                        xytext=(ox + w*0.3, arr_y - arrow_dir*10),
                        arrowprops=dict(arrowstyle='->', lw=1.2, color='black'))

        # Source arrow (direction indicates NMOS vs PMOS)
        s_arr_y = sy - 16
        if sym_type == 'nmos':
            self.ax.annotate('', xy=(sx + 8, s_arr_y - 8), xytext=(sx + 8, s_arr_y + 8),
                           arrowprops=dict(arrowstyle='->', lw=1.2, color='black'))
        else:
            self.ax.annotate('', xy=(sx + 8, s_arr_y + 8), xytext=(sx + 8, s_arr_y - 8),
                           arrowprops=dict(arrowstyle='->', lw=1.2, color='black'))

    def _draw_bjt(self, x, y, spec, comp, sym_type):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        ox = x + (bx - bw/2) * s
        oy = y + (by - bh/2) * s
        w, h = bw * s, bh * s

        # Collector (top)
        cx, cy = ox + w, oy
        # Base (left)
        bx_p, by_p = ox, oy + h*0.83
        # Emitter (bottom)
        ex, ey = ox + w, oy + h

        # Vertical line
        self.ax.plot([ox + w*0.7, ox + w*0.7], [oy + h*0.1, oy + h*0.9],
                    'k-', linewidth=2)
        # Base plate
        self.ax.plot([ox, ox + w*0.7], [by_p, by_p], 'k-', linewidth=1.2)
        # Collector
        self.ax.plot([ox + w*0.7, ox + w*0.7], [oy, oy + h*0.1], 'k-', linewidth=1.2)
        self.ax.plot([ox + w*0.7, ox + w*0.7 + 16], [oy, oy], 'k-', linewidth=1.2)
        # Emitter
        self.ax.plot([ox + w*0.7, ox + w*0.7], [oy + h*0.9, oy + h], 'k-', linewidth=1.2)
        self.ax.plot([ox + w*0.7, ox + w*0.7 + 16], [oy + h, oy + h], 'k-', linewidth=1.2)
        # Emitter arrow
        arr_y = ey - 16
        if sym_type == 'npn':
            self.ax.annotate('', xy=(ex + 8, arr_y - 8), xytext=(ex + 8, arr_y + 8),
                           arrowprops=dict(arrowstyle='->', lw=1.2, color='black'))
        else:
            self.ax.annotate('', xy=(ex + 8, arr_y + 8), xytext=(ex + 8, arr_y - 8),
                           arrowprops=dict(arrowstyle='->', lw=1.2, color='black'))

    def _draw_diode(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        cx = x + (spec['pins'][0][1] - bw/2) * s
        cy_top = y + (spec['pins'][0][2] - bh/2) * s
        cy_bot = y + (spec['pins'][1][2] - bh/2) * s
        sz = 14
        mid = (cy_top + cy_bot) / 2
        # Triangle
        tri = Polygon([(cx, mid - sz), (cx + sz, mid), (cx, mid + sz)],
                     fill=False, edgecolor='black', linewidth=2)
        self.ax.add_patch(tri)
        # Bar
        self.ax.plot([cx - sz, cx - sz], [mid - sz, mid + sz], 'k-', linewidth=2.5)
        self.ax.plot([cx, cx], [cy_top, mid - sz], 'k-', linewidth=1.2)
        self.ax.plot([cx - sz, cx - sz], [mid, cy_bot], 'k-', linewidth=1.2)
        self.ax.plot([cx - sz, cx], [cy_bot, cy_bot], 'k-', linewidth=1.2)

    def _draw_vcvs(self, x, y, spec, comp):
        s = self.s
        bx, by, bw, bh = spec['bbox']
        ox = x + (bx - bw/2) * s
        oy = y + (by - bh/2) * s
        mid_x = ox + bw * s / 2
        mid_y = oy + bh * s / 2
        sz = bh * s * 0.35

        # Diamond
        diamond = Polygon([(mid_x, mid_y - sz), (mid_x + sz, mid_y),
                          (mid_x, mid_y + sz), (mid_x - sz, mid_y)],
                         fill=True, facecolor='white', edgecolor='black', linewidth=2)
        self.ax.add_patch(diamond)

        # Input + (top-left)
        in_plus_y = oy + (spec['pins'][0][2] - bh/2) * s
        self.ax.plot([mid_x - sz*0.6, mid_x - sz*0.6], [in_plus_y, mid_y - sz*0.5],
                    'k-', linewidth=1.2)
        self.ax.text(mid_x - sz*0.6 - 8, in_plus_y, '+', ha='right', va='center', fontsize=8)

        # Input - (bottom-left)
        in_minus_y = oy + (spec['pins'][1][2] - bh/2) * s
        self.ax.plot([mid_x - sz*0.6, mid_x - sz*0.6], [mid_y + sz*0.5, in_minus_y],
                    'k-', linewidth=1.2)
        self.ax.text(mid_x - sz*0.6 - 8, in_minus_y, '-', ha='right', va='center', fontsize=8)

        # Output + (top-right)
        out_plus_y = oy + (spec['pins'][2][2] - bh/2) * s
        self.ax.plot([mid_x + sz*0.6, mid_x + sz*0.6], [out_plus_y, mid_y - sz*0.5],
                    'k-', linewidth=1.2)
        self.ax.text(mid_x + sz*0.6 + 8, out_plus_y, '+', ha='left', va='center', fontsize=8)

        # Output - (bottom-right)
        out_minus_y = oy + (spec['pins'][3][2] - bh/2) * s
        self.ax.plot([mid_x + sz*0.6, mid_x + sz*0.6], [mid_y + sz*0.5, out_minus_y],
                    'k-', linewidth=1.2)
        self.ax.text(mid_x + sz*0.6 + 8, out_minus_y, '-', ha='left', va='center', fontsize=8)

    def _draw_box(self, x, y, spec, comp):
        s = self.s
        w, h = 60, 60
        rect = Rectangle((x - w/2, y - h/2), w, h, fill=True, facecolor='#f5f5f5',
                        edgecolor='#888888', linewidth=1, linestyle='--')
        self.ax.add_patch(rect)
        label = comp.get('type', '?') + (comp.get('value', '') or '')
        self.ax.text(x, y, label[:10], ha='center', va='center', fontsize=8,
                    fontfamily='monospace')

    def _symbol_for(self, comp):
        t = comp['type']
        if t == 'M':
            model = comp.get('model', '').upper()
            return 'pmos' if ('P' in model and 'N' not in model) else 'nmos'
        if t == 'Q':
            model = comp.get('model', '').upper()
            return 'pnp' if 'PNP' in model else 'npn'
        return TYPE_SYMBOL.get(t, 'res')


# ── Ground symbol drawing ──────────────────────────────────────────────────

def draw_grounds(ax, components, positions):
    """Draw ground symbols for components connected to net 0."""
    s = SCALE / 4
    for c in components:
        if '0' not in c['nets'] or c['ref'] not in positions:
            continue
        x, y = positions[c['ref']]
        # Find which pin connects to ground
        sym_name = TYPE_SYMBOL.get(c['type'], 'res')
        if c['type'] == 'M':
            sym_name = 'pmos' if ('P' in c.get('model','').upper() and 'N' not in c.get('model','').upper()) else 'nmos'
        spec = SYMBOLS.get(sym_name)
        if not spec:
            continue
        # Use the last pin's bottom as ground reference
        bx, by, bw, bh = spec['bbox']
        gx = x + (spec['pins'][-1][1] - bw/2) * s
        gy = y + (spec['pins'][-1][2] - bh/2) * s + 20

        # Draw ground symbol
        ax.plot([gx, gx], [y + bh*s, gy], 'k-', linewidth=1.2)
        for i in range(3):
            w = 12 - i * 3
            ax.plot([gx - w, gx + w], [gy + i*5, gy + i*5], 'k-', linewidth=1.5)


# ── Main render function ───────────────────────────────────────────────────

def render_netlist(content, output_path, width=1600, height=900):
    components, directives = parse_netlist(content)
    if not components:
        print("No components found in netlist")
        return False

    print(f"Parsed {len(components)} components")

    # Layout
    layout_engine = LayeredLayout(components)
    positions = layout_engine.layout(width, height)

    # Route wires
    router = ManhattanRouter(components, positions)
    wire_segments = router.route()

    print(f"Layout: {len(positions)} placed, {len(wire_segments)} wire segments")

    # Draw
    fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=120)
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)  # invert y: top=0, bottom=height
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_facecolor('#FCFCFC')

    drawer = SchematicDrawer(ax, components, positions, wire_segments)
    drawer.draw_all()
    draw_grounds(ax, components, positions)

    # Net labels at key nodes
    labeled = set()
    for c in components:
        for net in c['nets']:
            if net in labeled or net == '0' or net.isdigit():
                continue
            labeled.add(net)
            if c['ref'] in positions:
                x, y = positions[c['ref']]
                ax.text(x + 20, y - 20, net, fontsize=8, fontfamily='monospace',
                       fontweight='bold', color='#1a5276',
                       bbox=dict(boxstyle='round,pad=0.15', fc='#EBF5FB', ec='#2980B9', alpha=0.9))

    # Title
    for d in directives:
        if d.startswith('*') or d.startswith('#'):
            ax.set_title(d.lstrip('*# ').strip(), fontsize=12, fontfamily='monospace',
                        pad=15, color='#333333')
            break

    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    plt.close(fig)
    return True


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: render_schematic.py <netlist.cir> [output.png]")
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else infile.replace('.cir', '.png').replace('.net', '.png')

    with open(infile) as f:
        content = f.read()

    ok = render_netlist(content, outfile)
    if ok:
        print(f"Saved: {outfile}")
    else:
        sys.exit(1)
