#!/usr/bin/env python3
"""Generate the hierarchical schematic for the integrated hv_awg board.

Hierarchy: root → POWER (1 instance), CELL (4 instances) → DAC (4 per CELL, 16 total)
- POWER: kicad/power/ (CQB150W ×2, R3M-2409S), converted to a sub-sheet by convert()
- DAC: kicad/ad8460/, converted to a sub-sheet by convert(), with PWR_FLAG removed
- CELL: generated directly by this script (TE0720, REC15E, TPS75233, TPS22810, REF5050)
- The FPGA pin assignment table is written to PORTS.md and kicad/hv_awg/pin_map.json

Reference designator rule: parts in CELL k get +k*1000, DAC j adds +j*100 (e.g. C1 in cell 2 DAC 3 = C2301).

Usage: build_integrated.py <kicad dir> <project dir>
"""
import json
import re
import sys
import uuid

K = "/Applications/KiCad/KiCad.app/Contents/SharedSupport"
PRJ = "hv_awg"
N_CELL = 4
N_DAC = 4
DAC_SIGNALS = [f"DB{i}" for i in range(14)] + ["SYNC", "CS_N"]
SHARED = ["SCLK", "SDI", "SDO", "RESET_N", "SDN_RESET", "SDN_DRV", "SDN_OE_N"]
FLAGS = [f"SDN_FLAG{j}" for j in range(1, N_DAC + 1)]
INTER = ["F_TRIG_IN", "F_TRIG_OUT", "F_SCLK", "F_MOSI", "F_MISO", "F_CS0", "F_CS1", "F_CS2", "F_EN", "F_CLK_SEL", "F_TRIG_SEL"]
MASTER_ONLY = {"F_EN", "F_CLK_SEL", "F_TRIG_SEL", "F_TRIG_OUT"}  # These pins are left unconnected at root on Slave cells
# PHY_COM is not connected: the Trenz TE0705 carrier also just leaves it on the connector
ETH = [f"PHY_MDI{i}_{s}" for i in range(4) for s in "PN"]
POWER_NETS = ["P24V_F", "GND_A", "P9V", "P52V", "N52V", "GND_B_300V"]


def block_at(t, i):
    """Return the end position (exclusive) of the parenthesis block opened at t[i]."""
    d = 0
    s = False
    j = i
    while True:
        c = t[j]
        if s:
            if c == "\\":
                j += 1
            elif c == '"':
                s = False
        elif c == '"':
            s = True
        elif c == "(":
            d += 1
        elif c == ")":
            d -= 1
            if d == 0:
                return j + 1
        j += 1


def blocks(t, head):
    out = []
    i = 0
    while True:
        i = t.find(head, i)
        if i < 0:
            return out
        e = block_at(t, i)
        out.append((i, e))
        i = e


def uid():
    return str(uuid.uuid4())


def sym_at(b):
    x, y, a = re.search(r"\(at ([\d.\-]+) ([\d.\-]+) ([\d.\-]+)\)", b).groups()
    return float(x), float(y), float(a)


def rotate(px, py, a):
    """Rotate symbol-local coordinates (y up) by a degrees."""
    a = int(a) % 360
    return {0: (px, py), 90: (-py, px), 180: (-px, -py), 270: (py, -px)}[a]


def pin_positions(t, sym_block):
    """Compute the sheet coordinates of every pin of a symbol (0/90/180/270 degrees, not mirrored)."""
    lib = re.search(r'\(lib_id "([^"]+)"', sym_block).group(1)
    x, y, a = sym_at(sym_block)
    assert "(mirror" not in sym_block[:300], lib
    i = t.index(f'(symbol "{lib}"')
    lib_blk = t[i : block_at(t, i)]
    pos = {}
    for pi, pe in blocks(lib_blk, "(pin "):
        p = lib_blk[pi:pe]
        m = re.search(r"\(at ([\d.\-]+) ([\d.\-]+) ", p)
        n = re.search(r'\(number "([^"]+)"', p)
        if m and n:
            rx, ry = rotate(float(m.group(1)), float(m.group(2)), a)
            pos[n.group(1)] = (round(x + rx, 2), round(y - ry, 2))
    return pos


def remove_spans(t, spans):
    for i, e in sorted(spans, reverse=True):
        t = t[:i] + t[e:]
    return t


def label_xy(b):
    x, y = re.search(r"\(at ([\d.\-]+) ([\d.\-]+) ", b).groups()
    return round(float(x), 2), round(float(y), 2)


def convert(src, remove_prefix, interface, instances):
    """Convert a standalone schematic into a sub-sheet. interface: {net: shape}; instances: [(path, offset), ...], path includes root."""
    t = open(src).read()

    # 1. Remove PWR_FLAG symbols and the labels attached to their pins
    spans = []
    dead = set()
    for i, e in blocks(t, "(symbol\n"):
        b = t[i:e]
        ref = re.search(r'\(reference "([^"]+)"', b).group(1)
        if ref.startswith(remove_prefix):
            spans.append((i, e))
            dead |= set(pin_positions(t, b).values())
    for i, e in blocks(t, "(label "):
        if label_xy(t[i:e]) in dead:
            spans.append((i, e))
    t = remove_spans(t, spans)

    # 2. Convert the first label of each interface net into a hierarchical_label
    done = set()
    edits = []
    for i, e in blocks(t, "(label "):
        b = t[i:e]
        name = re.match(r'\(label "([^"]+)"', b).group(1)
        if name in interface and name not in done:
            done.add(name)
            nb = re.sub(
                r'^\(label "([^"]+)"',
                lambda m: f'(hierarchical_label "{m.group(1)}"\n\t\t(shape {interface[name]})',
                b,
            )
            edits.append((i, e, nb))
    assert done == set(interface), set(interface) - done
    for i, e, nb in sorted(edits, reverse=True):
        t = t[:i] + nb + t[e:]

    # 3. Rewrite instances to the integrated board's paths and add the offset to each reference
    out = []
    last = 0
    for i, e in blocks(t, "(instances"):
        b = t[i:e]
        ref = re.search(r'\(reference "([^"]+)"', b).group(1)
        unit = re.search(r"\(unit (\d+)\)", b).group(1)
        pre, num = re.match(r"([A-Za-z#]+)(\d+)", ref).groups()
        paths = "".join(
            f'\n\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{pre}{int(num) + off}")\n\t\t\t\t\t(unit {unit})\n\t\t\t\t)'
            for path, off in instances
        )
        out.append(t[last:i])
        out.append(f'(instances\n\t\t\t(project "{PRJ}"{paths}\n\t\t\t)\n\t\t)')
        last = e
    out.append(t[last:])
    t = "".join(out)

    # 4. Sub-sheets do not need sheet_instances
    return remove_spans(t, blocks(t, "(sheet_instances"))


def lib_file(lib, base):
    if lib.startswith("ul_") or lib in ("TE0720", "CQB150W", "LMK1C1106A"):
        return f"{base}/lib/symbols/{lib}.kicad_sym"
    return f"{K}/symbols/{lib}.kicad_sym"


class Sheet:
    """A schematic sheet whose connections are made with labels. paths: [(path, offset), ...]."""

    def __init__(self, base, paths, iface=None):
        self.base = base
        self.paths = paths
        self.iface = dict(iface or {})
        self.used_iface = set()
        self.libs = {}
        self.items = []

    def lib(self, lib, name):
        key = f"{lib}:{name}"
        if key not in self.libs:
            t = open(lib_file(lib, self.base)).read()
            i = t.index(f'(symbol "{name}"')
            b = t[i : block_at(t, i)]
            pins = {}
            for m in re.finditer(r'\(symbol "[^"]*_(\d+)_(\d+)"', b):
                unit = int(m.group(1))
                sub = b[m.start() : block_at(b, m.start())]
                for pi, pe in blocks(sub, "(pin "):
                    p = sub[pi:pe]
                    kind = re.match(r"\(pin (\w+)", p).group(1)
                    at = re.search(r"\(at ([\d.\-]+) ([\d.\-]+) ([\d.\-]+)\)", p).groups()
                    num = re.search(r'\(number "([^"]+)"', p).group(1)
                    pins[num] = (unit, float(at[0]), float(at[1]), int(at[2]), kind)
            self.libs[key] = (b.replace(f'(symbol "{name}"', f'(symbol "{key}"', 1), pins)
        return self.libs[key][1]

    def label(self, name, x, y, ang):
        just = "left" if ang in (0, 90) else "right"
        if name in self.iface and name not in self.used_iface:
            self.used_iface.add(name)
            self.items.append(
                f'\t(hierarchical_label "{name}"\n\t\t(shape {self.iface[name]})\n\t\t(at {x} {y} {ang})\n'
                f"\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)\n"
                f'\t\t(uuid "{uid()}")\n\t)\n'
            )
        else:
            self.items.append(
                f'\t(label "{name}"\n\t\t(at {x} {y} {ang})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
                f'\t\t\t(justify {just} bottom)\n\t\t)\n\t\t(uuid "{uid()}")\n\t)\n'
            )

    def add(self, lib, name, ref, value, fp, x, y, nets=None, nc=None, unit_at=None):
        """nets: {pin number: net}; nc: list of pin numbers. unit_at: {unit: (x, y)} for multi-unit symbols."""
        nets = nets or {}
        nc = nc or []
        pins = self.lib(lib, name)
        allunits = sorted({p[0] for p in pins.values()} - {0}) or [1]
        pre, num = re.match(r"([A-Za-z#]+)(\d+)", ref).groups()
        for u in allunits:
            ux, uy = (unit_at or {}).get(u, (x, y))
            paths = "".join(
                f'\n\t\t\t\t(path "{path}"\n\t\t\t\t\t(reference "{pre}{int(num) + off}")\n\t\t\t\t\t(unit {u})\n\t\t\t\t)'
                for path, off in self.paths
            )
            hide = "\n\t\t\t\t(hide yes)"
            prop = lambda k, v, px, py, h="": (
                f'\t\t(property "{k}" "{v}"\n\t\t\t(at {px} {py} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t){h}\n\t\t\t\t(justify left)\n\t\t\t)\n\t\t)\n'
            )
            # Place the text above the symbol outline
            top = max(p[2] for p in pins.values() if p[0] in (u, 0))
            self.items.append(
                f'\t(symbol\n\t\t(lib_id "{lib}:{name}")\n\t\t(at {ux} {uy} 0)\n\t\t(unit {u})\n\t\t(exclude_from_sim no)\n\t\t(in_bom {"no" if pre.startswith("#") else "yes"})\n\t\t(on_board {"no" if pre.startswith("#") else "yes"})\n\t\t(dnp no)\n'
                f'\t\t(uuid "{uid()}")\n'
                + prop("Reference", ref, ux + 2.54, round(uy - top - 2.54, 2) if len(pins) > 2 else uy - 1.27)
                + prop("Value", value, ux + 2.54, round(uy - top - 5.08, 2) if len(pins) > 2 else uy + 1.27)
                + prop("Footprint", fp, ux, uy, hide)
                + prop("Datasheet", "", ux, uy, hide)
                + f'\t\t(instances\n\t\t\t(project "{PRJ}"{paths}\n\t\t\t)\n\t\t)\n\t)\n'
            )
            for num_, (pu, px, py, ang, kind) in pins.items():
                if pu not in (u, 0):
                    continue
                sx, sy = round(ux + px, 2), round(uy - py, 2)
                if num_ in nets:
                    la = {0: 180, 180: 0, 90: 270, 270: 90}[ang]
                    self.label(nets[num_], sx, sy, la)
                elif num_ in nc:
                    self.items.append(f'\t(no_connect\n\t\t(at {sx} {sy})\n\t\t(uuid "{uid()}")\n\t)\n')

    def sheet(self, name, file, su, x, y, w, pins, page_paths):
        """pins: [(net name, type, 'L'|'R')]; page_paths: [(path, page)]. Returns {pin name: (x, y)}."""
        lines = []
        pos = {}
        for side in "LR":
            group = [p for p in pins if p[2] == side]
            px = x if side == "L" else x + w
            ang = 180 if side == "L" else 0
            just = "left" if side == "L" else "right"
            for k, (pn, kind, _) in enumerate(group):
                py = round(y + 2.54 + 2.54 * k, 2)
                pos[pn] = (px, py)
                lines.append(
                    f'\t\t(pin "{pn}" {kind}\n\t\t\t(at {px} {py} {ang})\n\t\t\t(uuid "{uid()}")\n'
                    f"\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify {just})\n\t\t\t)\n\t\t)\n"
                )
        n = max(len([p for p in pins if p[2] == s]) for s in "LR")
        h = round(5.08 + 2.54 * n, 2)
        inst = "".join(f'\n\t\t\t\t(path "{p}"\n\t\t\t\t\t(page "{pg}")\n\t\t\t\t)' for p, pg in page_paths)
        self.items.append(
            f"\t(sheet\n\t\t(at {x} {y})\n\t\t(size {w} {h})\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(dnp no)\n"
            f'\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n\t\t(fill\n\t\t\t(color 0 0 0 0)\n\t\t)\n\t\t(uuid "{su}")\n'
            f'\t\t(property "Sheetname" "{name}"\n\t\t\t(at {x} {round(y - 0.71, 2)} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left bottom)\n\t\t\t)\n\t\t)\n'
            f'\t\t(property "Sheetfile" "{file}"\n\t\t\t(at {x} {round(y + h + 0.6, 2)} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(justify left top)\n\t\t\t)\n\t\t)\n'
            + "".join(lines)
            + f'\t\t(instances\n\t\t\t(project "{PRJ}"{inst}\n\t\t\t)\n\t\t)\n\t)\n'
        )
        return pos

    def text(self, u, paper, root=False):
        libs = "\n".join("\t\t" + v[0] for v in self.libs.values())
        tail = '\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n' if root else ""
        return (
            f'(kicad_sch\n\t(version 20260101)\n\t(generator "hv_awg_pcb")\n\t(generator_version "10.0")\n\t(uuid "{u}")\n\t(paper "{paper}")\n'
            f"\t(lib_symbols\n{libs}\n\t)\n" + "".join(self.items) + tail + "\t(embedded_fonts no)\n)\n"
        )


def carrier_table(pins):
    return {c.replace("JM", "JB"): {(int(k) + 1 if int(k) % 2 else int(k) - 1): v for k, v in d.items()} for c, d in pins.items()}


def allocate(table):
    """Return {cell net: (connector pin, module net)}."""
    alloc = {}
    # DAC1/DAC2 use JB1 (B35), DAC3/DAC4 use JB2 (B13), each in connector order to minimize trace crossings
    b35 = [(p, n) for p, n in sorted(table["JB1"].items()) if re.match(r"B35_L", n)]
    b13 = [(p, n) for p, n in sorted(table["JB2"].items()) if re.match(r"B13_L", n)]
    seq = [(1, b35[:16]), (2, b35[16:32]), (3, b13[:16]), (4, b13[16:32])]
    for j, pool in seq:
        for sig, (p, n) in zip(DAC_SIGNALS, pool):
            alloc[f"D{j}_{sig}"] = (f"JB{1 if j < 3 else 2}.{p}", n)
    # Shared control and inter-FPGA signals use JB3 (B34); the clock is fixed on MRCC pin B34_L12_P
    b34 = {n: p for p, n in table["JB3"].items() if re.match(r"B34_L", n)}
    alloc["F_CLK"] = (f"JB3.{b34['B34_L12_P']}", "B34_L12_P")
    rest = [(p, n) for n, p in sorted(b34.items(), key=lambda kv: kv[1]) if not n.startswith(("B34_L12_", "B34_L13_"))]
    names = SHARED + FLAGS + ["VREF_EN"] + INTER
    assert len(names) <= len(rest)
    for sig, (p, n) in zip(names, rest):
        alloc[sig] = (f"JB3.{p}", n)
    return alloc


def build_cell(base, root, cell_paths, dac_su, table, alloc):
    iface = {
        "P24V_F": "passive", "GND_A": "passive", "P9V": "passive", "P52V": "passive", "N52V": "passive", "GND_B_300V": "passive",
        "F_CLK": "input", "F_TRIG_IN": "input", "F_TRIG_OUT": "output", "F_SCLK": "bidirectional", "F_MOSI": "bidirectional", "F_MISO": "bidirectional",
        "F_CS0": "bidirectional", "F_CS1": "bidirectional", "F_CS2": "bidirectional",
        "F_EN": "output", "F_CLK_SEL": "output", "F_TRIG_SEL": "output", "P3V3": "passive",
    }
    iface.update({n: "passive" for n in ETH})
    s = Sheet(base, cell_paths, iface)

    # TE0720: fixed-function pins
    nets = {}
    nc = []
    used = {v[0]: k for k, v in alloc.items()}
    power_map = {
        "VIN": "P5V", "3.3VIN": "P3V3_IN", "GND": "GND_B_300V",
        "VCCIO13": "P3V3", "VCCIO33": "P3V3", "VCCIO34": "P3V3", "VCCIO35": "P3V3", "3.3V": "P3V3",
        "VREF_JTAG": "VREF_JTAG", "X_TMS": "X_TMS", "X_TCK": "X_TCK", "X_TDO": "X_TDO", "X_TDI": "X_TDI",
        "MIO14": "UART_MIO14", "MIO15": "UART_MIO15", "MODE": "BOOT_MODE", "JTAGMODE": "JTAGMODE", "PGOOD": "PGOOD",
    }
    for con, d in table.items():
        for p, n in d.items():
            key = f"{con}.{p}"
            if key in used:
                nets[key] = used[key]
            elif n in power_map:
                nets[key] = power_map[n]
            elif n in ETH:
                nets[key] = n
            else:
                nc.append(key)
    nets["SH"] = "GND_B_300V"
    nets["MH"] = "GND_B_300V"
    s.add("TE0720", "TE0720", "U1", "TE0720-04", "TE0720:TE0720", 0, 0, nets, nc, unit_at={1: (60.96, 111.76), 2: (182.88, 111.76), 3: (304.8, 86.36)})

    # DAC sheet ×4
    pos_list = [(431.8, 25.4), (508, 25.4), (431.8, 106.68), (508, 106.68)]
    for j in range(1, N_DAC + 1):
        pins = [(n, "input", "L") for n in DAC_SIGNALS + ["SCLK", "SDI"]] + [("SDO", "tri_state", "L")]
        pins += [(n, "input", "L") for n in ("RESET_N", "SDN_RESET", "SDN_DRV", "SDN_OE_N")] + [("SDN_FLAG", "output", "L")]
        pins += [(n, "passive", "R") for n in ("P52V", "N52V", "P5V", "VREF_5V", "P3V3", "GND_B_300V")]
        pg = [(f"{p}/{dac_su[j]}", str(3 + (k * (N_DAC + 1)) + j)) for k, (p, _) in enumerate(cell_paths)]
        x, y = pos_list[j - 1]
        pp = s.sheet(f"DAC{j}", "ad8460.kicad_sch", dac_su[j], x, y, 25.4, pins, pg)
        for n, xy in pp.items():
            if n in DAC_SIGNALS:
                net = f"D{j}_{n}"
            elif n == "SDN_FLAG":
                net = f"SDN_FLAG{j}"
            else:
                net = n
            ang = 180 if xy[0] == x else 0
            s.label(net, xy[0], xy[1], ang)

    # 5V: one REC15E-2405SZ per cell; input filter and Y capacitor follow the proven iso_12v_to_24v design
    X0, Y0 = 40.64, 228.6
    s.add("Device", "L", "L1", "4.7uH IHLP2020", "Inductor_SMD:L_Vishay_IHLP-2020", X0, Y0, {"1": "VIN_5", "2": "P24V_F"})
    s.add("Device", "C", "C1", "2.2uF 100V", "Capacitor_SMD:C_1206_3216Metric", X0 + 20.32, Y0, {"1": "P24V_F", "2": "GND_A"})
    s.add("Device", "C", "C2", "2.2uF 100V", "Capacitor_SMD:C_1206_3216Metric", X0 + 40.64, Y0, {"1": "P24V_F", "2": "GND_A"})
    s.add("ul_REC15E-2405SZ", "REC15E-2405SZ", "PS1", "REC15E-2405SZ", "ul_REC15E-2405SZ:REC15E-2415SZ_RCP", X0 + 66.04, Y0 - 5.08,
          {"1": "VIN_5", "2": "GND_A", "4": "GND_B_300V", "6": "P5V"}, ["3", "5"])
    s.add("Device", "C", "C3", "1.5nF 2kV", "Capacitor_SMD:C_2225_5664Metric", X0 + 142.24, Y0, {"1": "GND_A", "2": "GND_B_300V"})
    s.add("Device", "C", "C4", "47uF 16V", "Capacitor_SMD:CP_Elec_8x10.5", X0 + 165.1, Y0, {"1": "P5V", "2": "GND_B_300V"})
    s.add("Device", "C", "C5", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", X0 + 187.96, Y0, {"1": "P5V", "2": "GND_B_300V"})

    # 3.3VIN: TPS75233
    Y1 = 274.32
    s.add("ul_TPS75233QPWPR", "TPS75233QPWPR", "U2", "TPS75233QPWPR", "ul_TPS75233QPWPR:PWP20", X0 + 20.32, Y1,
          {"3": "P5V", "4": "P5V", "5": "GND_B_300V", "7": "P3V3_IN", "8": "P3V3_IN", "9": "P3V3_IN",
           "1": "GND_B_300V", "10": "GND_B_300V", "11": "GND_B_300V", "17": "GND_B_300V", "20": "GND_B_300V"}, ["6"])
    # Datasheet: input 0.22-1µF close to the pin; output at least 47µF with ESR 100mΩ-10Ω.
    # So the output uses a 100µF tantalum, with no large ceramic in parallel on P3V3_IN (it would pull the effective ESR out of range)
    s.add("Device", "C", "C6", "1uF", "Capacitor_SMD:C_0603_1608Metric", X0, Y1 + 40.64, {"1": "P5V", "2": "GND_B_300V"})
    s.add("Device", "C", "C7", "10uF", "Capacitor_SMD:C_1206_3216Metric", X0 + 20.32, Y1 + 40.64, {"1": "P5V", "2": "GND_B_300V"})
    s.add("Device", "C", "C8", "100uF 10V Ta ESR>100m", "Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D", X0 + 40.64, Y1 + 40.64, {"1": "P3V3_IN", "2": "GND_B_300V"})

    # VREF: 9V → TPS22810 → REF5050, FPGA-controlled (VCC_5V comes up before VREF_5V; AD8460 powers up in shutdown)
    X2 = 254
    s.add("Power_Management", "TPS22810DBV", "U3", "TPS22810DBV", "Package_TO_SOT_SMD:SOT-23-6", X2, Y1,
          {"1": "P9V", "2": "GND_B_300V", "3": "VREF_EN", "5": "VREF_QOD", "6": "VREF_IN"}, ["4"])
    s.add("Device", "R", "R2", "10k", "Resistor_SMD:R_0603_1608Metric", X2 - 45.72, Y1, {"1": "VREF_EN", "2": "GND_B_300V"})
    s.add("Device", "R", "R3", "100R", "Resistor_SMD:R_0603_1608Metric", X2 + 40.64, Y1, {"1": "VREF_QOD", "2": "VREF_IN"})
    s.add("Device", "C", "C9", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", X2 - 25.4, Y1 + 30.48, {"1": "P9V", "2": "GND_B_300V"})
    s.add("Device", "C", "C10", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", X2, Y1 + 30.48, {"1": "VREF_IN", "2": "GND_B_300V"})
    X3 = 355.6
    s.add("ul_REF5050IDR", "REF5050IDR", "U4", "REF5050IDR", "ul_REF5050IDR:D8", X3, Y1,
          {"2": "VREF_IN", "4": "GND_B_300V", "5": "VREF_NR", "6": "VREF_5V"}, ["3"])
    s.add("Device", "C", "C11", "1uF", "Capacitor_SMD:C_0603_1608Metric", X3 - 25.4, Y1 + 30.48, {"1": "VREF_NR", "2": "GND_B_300V"})
    s.add("Device", "C", "C12", "1uF", "Capacitor_SMD:C_0603_1608Metric", X3, Y1 + 30.48, {"1": "VREF_5V", "2": "GND_B_300V"})

    # Module power decoupling
    X4 = 457.2
    for i, (ref, val, fp, net) in enumerate(
        (
            ("C13", "10uF", "Capacitor_SMD:C_1206_3216Metric", "P5V"),
            ("C14", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", "P5V"),
            ("C15", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", "P3V3_IN"),
            ("C16", "10uF", "Capacitor_SMD:C_1206_3216Metric", "P3V3"),
            ("C17", "0.1uF", "Capacitor_SMD:C_0603_1608Metric", "P3V3"),
        )
    ):
        s.add("Device", "C", ref, val, fp, X4 + 25.4 * i, Y1 + 30.48, {"1": net, "2": "GND_B_300V"})

    # Debug and boot configuration (JTAG, UART, MODE jumper; JTAGMODE fixed to select FPGA; PGOOD test point)
    Y5 = 228.6
    H = "Connector_PinHeader_2.54mm:PinHeader_1x"
    s.add("Connector_Generic", "Conn_01x06", "J1", "JTAG", H + "06_P2.54mm_Vertical", 330.2, Y5,
          {"1": "VREF_JTAG", "2": "X_TMS", "3": "X_TCK", "4": "X_TDO", "5": "X_TDI", "6": "GND_B_300V"})
    s.add("Connector_Generic", "Conn_01x03", "J2", "UART", H + "03_P2.54mm_Vertical", 370.84, Y5,
          {"1": "UART_MIO14", "2": "UART_MIO15", "3": "GND_B_300V"})
    s.add("Connector_Generic", "Conn_01x02", "J3", "MODE: open=QSPI, short=SD", H + "02_P2.54mm_Vertical", 406.4, Y5,
          {"1": "BOOT_MODE", "2": "GND_B_300V"})
    s.add("Device", "R", "R1", "10k", "Resistor_SMD:R_0603_1608Metric", 449.58, Y5, {"1": "JTAGMODE", "2": "GND_B_300V"})
    s.add("Connector", "TestPoint", "TP1", "PGOOD", "TestPoint:TestPoint_Pad_D1.5mm", 485.14, Y5, {"1": "PGOOD"})

    # Every interface net must be used, otherwise its hierarchical pin is left dangling
    missing = set(iface) - s.used_iface
    assert not missing, missing
    return s


def build_root_io(r):
    """Clock, trigger, inter-FPGA pull-ups/pull-downs, RJ45. Powered from the CELL1 module's 3.3V output;
    buffer outputs stay low until the master drives F_EN high, to avoid back-powering the I/O of Slaves not yet powered."""
    G, V = "GND_B_300V", "CELL1_P3V3"
    R0603 = "Resistor_SMD:R_0603_1608Metric"
    C0603 = "Capacitor_SMD:C_0603_1608Metric"
    SMA = "Connector_Coaxial:SMA_Amphenol_132289_EdgeMount"
    MUX = "Package_SO:VSSOP-8_2.3x2mm_P0.5mm"
    r.add("Oscillator", "ASE-xxxMHz", "Y101", "50MHz 3.3V", "Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm", 350.52, 88.9,
          {"1": V, "2": G, "3": "OSC_CLK", "4": V})

    # Clock and trigger share the same signal chain: SMA in → 33Ω → 2:1 mux → 1:6 buffer → 4 FPGAs + SMA out
    # LMK1C1106A ROUT is 50Ω at 3.3V (datasheet), so no series resistor is added on the outputs
    chains = [
        (50.8, 100, "CLK", "OSC_CLK", "F_CLK_SEL", "CLK_OUT"),
        (119.38, 200, "TRIG", "MASTER_TRIG_OUT", "F_TRIG_SEL", "TRIG_OUT"),
    ]
    for y, b, name, internal, sel, out in chains:
        i = b // 100 - 1  # 0 or 1
        r.add("Connector", "Conn_Coaxial", f"J{102 + 2 * i}", f"{name}_IN", SMA, 304.8, y, {"1": f"{name}_IN_RAW", "2": G})
        r.add("Device", "R", f"R{101 + 3 * i}", "33R", R0603, 330.2, y, {"1": f"{name}_IN_RAW", "2": f"{name}_IN"})
        r.add("Device", "R", f"R{102 + 3 * i}", "10k", R0603, 350.52, y, {"1": f"{name}_IN", "2": G})
        r.add("74xGxx", "74LVC2G157", f"U{101 + 2 * i}", "SN74LVC2G157DCU", MUX, 393.7, y,
              {"1": internal, "2": f"{name}_IN", "4": G, "5": f"{name}_MUX", "6": sel, "7": G, "8": V}, ["3"])
        r.add("Device", "R", f"R{103 + 3 * i}", "10k", R0603, 424.18, y + 12.7, {"1": sel, "2": G})
        nets = {"1": f"{name}_MUX", "2": "F_EN", "3": f"{name}_1", "14": f"{name}_2", "11": f"{name}_3", "13": f"{name}_4", "6": out,
                "5": V, "8": V, "12": V, "4": G, "7": G, "10": G}
        r.add("LMK1C1106A", "LMK1C1106A", f"U{102 + 2 * i}", "LMK1C1106APWR", "Package_SO:TSSOP-14_4.4x5mm_P0.65mm", 457.2, y, nets, ["9"])
        r.add("Connector", "Conn_Coaxial", f"J{103 + 2 * i}", out, SMA, 520.7, y, {"1": out, "2": G})

    # I/O is high-Z during FPGA configuration: F_EN pulled low (buffer off), CS pulled high (deselected), MISO pulled low
    r.add("Device", "R", "R107", "10k", R0603, 304.8, 170.18, {"1": "F_EN", "2": G})
    r.add("Device", "R", "R108", "10k", R0603, 325.12, 170.18, {"1": "F_MISO", "2": G})
    for i in range(3):
        r.add("Device", "R", f"R{109 + i}", "10k", R0603, 345.44 + 20.32 * i, 170.18, {"1": V, "2": f"SLAVE{i + 2}_CS"})

    # RJ45: connected to CELL1 only. Wiring follows the Trenz TE0705 Ethernet page: center tap 100nF to GND;
    # shield 100pF/1MΩ to GND, not tied directly to the platform. LEDs unconnected (the TE0720 B2B does not bring out the PHY LEDs)
    r.add("Connector", "RJ45_JK0654219", "J101", "JK0654219NL", "Connector_RJ:RJ45_Pulse_JK0654219NL_Horizontal", 304.8, 228.6,
          {"11": "PHY_MDI0_P", "10": "PHY_MDI0_N", "4": "PHY_MDI1_P", "5": "PHY_MDI1_N",
           "3": "PHY_MDI2_P", "2": "PHY_MDI2_N", "8": "PHY_MDI3_P", "9": "PHY_MDI3_N",
           "12": "ETH_CT", "6": "ETH_CT", "1": "ETH_CT", "7": "ETH_CT", "SH": "ETH_CHASSIS"},
          ["13", "14", "15", "16"])
    r.add("Device", "C", "C101", "100nF 50V", C0603, 355.6, 228.6, {"1": "ETH_CT", "2": G})
    r.add("Device", "C", "C102", "100pF 1kV", "Capacitor_SMD:C_1206_3216Metric", 375.92, 228.6, {"1": "ETH_CHASSIS", "2": G})
    r.add("Device", "R", "R112", "1M 1kV", "Resistor_SMD:R_2512_6332Metric", 396.24, 228.6, {"1": "ETH_CHASSIS", "2": G})

    # Decoupling: one 0.1µF per VDD pin, plus one shared 10µF
    r.add("Device", "C", "C103", "10uF", "Capacitor_SMD:C_1206_3216Metric", 304.8, 279.4, {"1": V, "2": G})
    for i in range(9):
        r.add("Device", "C", f"C{104 + i}", "0.1uF", C0603, 325.12 + 20.32 * i, 279.4, {"1": V, "2": G})


def main(base, proj):
    d = f"{base}/{PRJ}"
    root_file = f"{d}/{PRJ}.kicad_sch"
    root = re.search(r'\(uuid "?([0-9a-f\-]{36})', open(root_file).read()).group(1)

    table = carrier_table(json.load(open(f"{base}/lib/te0720_pins.json")))
    alloc = allocate(table)

    su_power = uid()
    su_cell = {k: uid() for k in range(1, N_CELL + 1)}
    dac_su = {j: uid() for j in range(1, N_DAC + 1)}
    cell_paths = [(f"/{root}/{su_cell[k]}", k * 1000) for k in su_cell]

    # POWER
    power = convert(
        f"{base}/power/power.kicad_sch",
        "#",
        {"P24V_A": "input", "VIN_F": "output", "GND_A": "passive", "P52V": "output", "N52V": "output", "P9V": "output", "GND_B_300V": "passive"},
        [(f"/{root}/{su_power}", 0)],
    )
    open(f"{d}/power.kicad_sch", "w").write(power)

    # DAC: path /root/cell/dac
    dac_iface = {n: "input" for n in DAC_SIGNALS + ["SCLK", "SDI", "RESET_N", "SDN_RESET", "SDN_DRV", "SDN_OE_N"]}
    dac_iface.update({"SDO": "tri_state", "SDN_FLAG": "output"})
    dac_iface.update({n: "passive" for n in ("P52V", "N52V", "P5V", "VREF_5V", "P3V3", "GND_B_300V")})
    # Each DAC position has its own sheet uuid, but they all share the same ad8460.kicad_sch
    inst = [(f"/{root}/{su_cell[k]}/{dac_su[j]}", k * 1000 + j * 100) for k in su_cell for j in dac_su]
    open(f"{d}/ad8460.kicad_sch", "w").write(convert(f"{base}/ad8460/ad8460.kicad_sch", "#", dac_iface, inst))

    # CELL
    cell = build_cell(base, root, cell_paths, dac_su, table, alloc)
    open(f"{d}/cell.kicad_sch", "w").write(cell.text(uid(), "A1"))

    # ROOT
    r = Sheet(base, [(f"/{root}", 0)])
    r.add("Connector", "Screw_Terminal_01x02", "J1", "24V IN", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal",
          25.4, 50.8, {"1": "P24V_A", "2": "GND_A"})
    pp = r.sheet(
        "POWER", "power.kicad_sch", su_power, 60.96, 40.64, 45.72,
        [("P24V_A", "input", "L"), ("GND_A", "passive", "L"), ("VIN_F", "output", "R"), ("P52V", "output", "R"), ("N52V", "output", "R"), ("P9V", "output", "R"), ("GND_B_300V", "passive", "R")],
        [(f"/{root}", "2")],
    )
    names = {"VIN_F": "P24V_F"}
    for n, xy in pp.items():
        r.label(names.get(n, n), xy[0], xy[1], 180 if xy[0] == 60.96 else 0)
    for i, net in enumerate(("GND_B_300V", "P52V", "N52V")):
        r.add("power", "PWR_FLAG", f"#FLG{i + 1}", "PWR_FLAG", "", 134.62 + 15.24 * i, 30.48, {"1": net})

    cell_pins = (
        [(n, "passive", "L") for n in POWER_NETS]
        + [("F_CLK", "input", "L"), ("F_TRIG_IN", "input", "L"), ("F_TRIG_OUT", "output", "L")]
        + [(n, "bidirectional", "L") for n in ("F_SCLK", "F_MOSI", "F_MISO", "F_CS0", "F_CS1", "F_CS2")]
        + [("F_EN", "output", "L"), ("F_CLK_SEL", "output", "L"), ("F_TRIG_SEL", "output", "L")]
        + [(n, "passive", "R") for n in ETH]
        + [("P3V3", "passive", "R")]
    )
    for k in su_cell:
        x, y = 60.96 + (k - 1) % 2 * 152.4, 81.28 + (k - 1) // 2 * 81.28
        pg = [(f"/{root}", str(3 + (k - 1) * (N_DAC + 1)))]
        pos = r.sheet(f"CELL{k}", "cell.kicad_sch", su_cell[k], x, y, 45.72, cell_pins, pg)
        for n, xy in pos.items():
            side = 180 if xy[0] == x else 0
            if n in POWER_NETS or n in ("F_SCLK", "F_MOSI", "F_MISO"):
                r.label(n, xy[0], xy[1], side)
            elif n == "F_CLK":
                r.label(f"CLK_{k}", xy[0], xy[1], side)
            elif n == "F_TRIG_IN":
                r.label(f"TRIG_{k}", xy[0], xy[1], side)
            elif n in MASTER_ONLY:
                if k == 1:
                    r.label({"F_TRIG_OUT": "MASTER_TRIG_OUT"}.get(n, n), xy[0], xy[1], side)
                else:
                    r.items.append(f'\t(no_connect\n\t\t(at {xy[0]} {xy[1]})\n\t\t(uuid "{uid()}")\n\t)\n')
            elif n == "P3V3":
                if k == 1:
                    r.label("CELL1_P3V3", xy[0], xy[1], side)  # Supply for the clock and trigger circuits
                else:
                    r.items.append(f'\t(no_connect\n\t\t(at {xy[0]} {xy[1]})\n\t\t(uuid "{uid()}")\n\t)\n')
            elif n in ("F_CS0", "F_CS1", "F_CS2"):
                idx = int(n[-1])
                if k == 1:
                    r.label(f"SLAVE{idx + 2}_CS", xy[0], xy[1], side)  # The master's three CS lines go to CELL2, 3, 4 respectively
                elif idx == 0:
                    r.label(f"SLAVE{k}_CS", xy[0], xy[1], side)
                else:
                    r.items.append(f'\t(no_connect\n\t\t(at {xy[0]} {xy[1]})\n\t\t(uuid "{uid()}")\n\t)\n')
            elif n in ETH:
                if k == 1:
                    r.label(n, xy[0], xy[1], side)  # Only the master connects to RJ45
                else:
                    r.items.append(f'\t(no_connect\n\t\t(at {xy[0]} {xy[1]})\n\t\t(uuid "{uid()}")\n\t)\n')
    build_root_io(r)
    open(root_file, "w").write(r.text(root, "A2", root=True))

    # Library tables
    libs = sorted({key.split(":")[0] for sh in (cell, r) for key in sh.libs} | {"Device", "power", "Connector", "74xGxx", "Oscillator", "LMK1C1106A", "CQB150W", "ul_AD8460BSVZ", "ul_R3M-2409S-SMD"})
    with open(f"{d}/sym-lib-table", "w") as f:
        f.write("(sym_lib_table\n  (version 7)\n")
        for n in libs:
            f.write(f'  (lib (name "{n}")(type "KiCad")(uri "{lib_file(n, base)}")(options "")(descr ""))\n')
        f.write(")\n")
    fps = {
        "TE0720": 1, "CQB150W": 1, "ul_AD8460BSVZ": 1, "ul_REC15E-2405SZ": 1, "ul_R3M-2409S-SMD": 1, "ul_TPS75233QPWPR": 1, "ul_REF5050IDR": 1,
        "Connector_RJ": 0, "Oscillator": 0, "Package_SO": 0, "Capacitor_SMD": 0, "Capacitor_Tantalum_SMD": 0, "Capacitor_THT": 0, "Resistor_SMD": 0, "Inductor_SMD": 0, "Diode_SMD": 0, "Fuse": 0, "Connector_Coaxial": 0, "TestPoint": 0,
        "Package_TO_SOT_SMD": 0, "Connector_PinHeader_2.54mm": 0, "TerminalBlock_Phoenix": 0,
    }
    with open(f"{d}/fp-lib-table", "w") as f:
        f.write("(fp_lib_table\n  (version 7)\n")
        for n, local in fps.items():
            uri = f"{base}/lib/footprints/{n}.pretty" if local else f"{K}/footprints/{n}.pretty"
            f.write(f'  (lib (name "{n}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n')
        f.write(")\n")

    # Pin assignment table
    json.dump({k: list(v) for k, v in alloc.items()}, open(f"{d}/pin_map.json", "w"), indent=0)
    with open(f"{proj}/PORTS.md", "w") as f:
        f.write("# PORTS: TE0720 pin assignment (generated by tools/build_integrated.py, identical for every CELL)\n\n")
        f.write("| Cell net | Carrier pin | Zynq bank net |\n|---|---|---|\n")
        for k in sorted(alloc, key=lambda n: (alloc[n][0].split(".")[0], int(alloc[n][0].split(".")[1]))):
            f.write(f"| `{k}` | {alloc[k][0]} | `{alloc[k][1]}` |\n")
    print("ok", len(alloc), "signals")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
