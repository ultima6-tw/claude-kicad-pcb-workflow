#!/usr/bin/env python3
"""Generate the KiCad symbol and footprint for the carrier-board side of the TE0720.

The three connectors and four mounting holes are built as a single footprint, so their
relative positions cannot drift during layout, and each of the 4 TE0720s can be moved as one unit.

Sources:
- Pin nets: kicad/lib/te0720_pins.json (from tools/extract_te0720_pins.py, module-side pin numbers)
- Odd/even swap: Trenz "4 x 5 SoM Integration Guide": JB1.1 mates with JM1.2, JM1-89 with JB1-90
- Position and orientation: TE07XX-Connector-Dimension.png on the same page (carrier top view)
  - Mounting holes 34 x 44, Φ3.2
  - JB1/JB2 32 apart center to center, vertically centered on the hole pattern; pin 1 top right, pin 99 bottom right, pin 2 top left
  - JB3 center 1.00 from the upper hole row, horizontally centered; pin 1 top left, pin 2 bottom left, pin 59 top right
- Pad geometry: KiCad built-in Samtec_LSHM-150/-130 footprints

Usage: gen_te0720.py <kicad/lib directory> <KiCad footprints directory>
"""
import json
import os
import re
import sys

NAME = "TE0720"
SERIES = {"JB1": "150", "JB2": "150", "JB3": "130"}
# Origin at the center of the mounting-hole rectangle, x right, y down; rot=True means rotated 90 degrees clockwise
PLACE = {"JB1": (-16.0, 0.0, True), "JB2": (16.0, 0.0, True), "JB3": (0.0, -21.0, False)}
HOLES = [(-17, -22), (17, -22), (-17, 22), (17, 22)]
MODULE = (40.0, 50.0)
OUT = {"3.3V", "1.8V", "1.5V", "VREF_JTAG"}
IN = {"VIN", "3.3VIN", "VCCIO13", "VCCIO33", "VCCIO34", "VCCIO35", "GND"}


def carrier_pin(module_pin):
    """Carrier-side pin number; odd pins mate with even pins."""
    p = int(module_pin)
    return p + 1 if p % 2 else p - 1


def carrier_table(pins):
    """Return {"JB1": {carrier pin number: net}, ...}"""
    return {c.replace("JM", "JB"): {carrier_pin(k): v for k, v in d.items()} for c, d in pins.items()}


def pin_type(name):
    if name in IN:
        return "power_in"
    if name in OUT:
        return "power_out"
    return "bidirectional"


def font(hide=False):
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size 1.27 1.27)){h})"


def make_symbol(path, table):
    w = 15.24
    body = ""
    for unit, con in enumerate(("JB1", "JB2", "JB3"), 1):
        d = table[con]
        n = max(d)
        rows = n // 2 + (2 if con == "JB3" else 0)
        top = rows * 2.54 / 2
        y = lambda r: round((top - 1.27 - r * 2.54) / 1.27) * 1.27
        graphics = (
            f"\t\t(symbol \"{NAME}_{unit}_1\"\n"
            f"\t\t\t(rectangle (start {-w} {top}) (end {w} {-top})\n"
            "\t\t\t\t(stroke (width 0.254) (type default))\n\t\t\t\t(fill (type background))\n\t\t\t)\n"
            f"\t\t\t(text \"{con}\" (at 0 {top - 2.54} 0) (effects (font (size 1.27 1.27))))\n"
        )
        for p in range(1, n + 1):
            r = (p - 1) // 2
            x, ang = (-w - 2.54, 0) if p % 2 else (w + 2.54, 180)
            # 3.3V has two pins (JB2.9/11); only the first is power_out, otherwise ERC reports power_out connected to power_out
            kind = "passive" if (con, p) == ("JB2", 11) else pin_type(d[p])
            graphics += (
                f"\t\t\t(pin {kind} line (at {x} {y(r):.2f} {ang}) (length 2.54)\n"
                f"\t\t\t\t(name \"{d[p]}\" {font()})\n\t\t\t\t(number \"{con}.{p}\" {font()})\n\t\t\t)\n"
            )
        if con == "JB3":
            for i, (num, label) in enumerate((("SH", "SHIELD"), ("MH", "MOUNT"))):
                graphics += (
                    f"\t\t\t(pin passive line (at {-w - 2.54} {y(n // 2 + i):.2f} 0) (length 2.54)\n"
                    f"\t\t\t\t(name \"{label}\" {font()})\n\t\t\t\t(number \"{num}\" {font()})\n\t\t\t)\n"
                )
        body += graphics + "\t\t)\n"
    out = f"""(kicad_symbol_lib
	(version 20251024)
	(generator "hv_awg_pcb")
	(generator_version "10.0")
	(symbol "{NAME}"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "U" (at 0 68.58 0) {font()})
		(property "Value" "TE0720-04" (at 0 66.04 0) {font()})
		(property "Footprint" "{NAME}:{NAME}" (at 0 0 0) {font(True)})
		(property "Datasheet" "https://wiki.trenz-electronic.de/display/PD/TE0720+TRM" (at 0 0 0) {font(True)})
		(property "Description" "Trenz TE0720 Zynq-7000 SoM, carrier side: JB1/JB2 LSHM-150, JB3 LSHM-130. Pin names are module nets." (at 0 0 0) {font(True)})
{body}		(embedded_fonts no)
	)
)
"""
    with open(path, "w") as f:
        f.write(out)


def lshm_pads(fp_dir, series):
    n = {"150": "50", "130": "30"}[series]
    t = open(f"{fp_dir}/Connector_Samtec.pretty/Samtec_LSHM-{series}-xx.x-x-DV-S_2x{n}-1SH_P0.50mm_Vertical.kicad_mod").read()
    return re.findall(
        r'\(pad "([^"]*)" (\w+) (\w+)\s*\(at ([\-\d.]+) ([\-\d.]+)[^)]*\)\s*\(size ([\d.]+) ([\d.]+)\)(?:\s*\(drill ([\d.]+)\))?', t
    )


def transform(x, y, place):
    cx, cy, rot = place
    if rot:
        x, y = -y, x
    return round(cx + x, 3), round(cy + y, 3)


def make_footprint(path, fp_dir):
    mx, my = MODULE[0] / 2, MODULE[1] / 2
    out = (
        f'(footprint "{NAME}"\n\t(version 20260206)\n\t(generator "hv_awg_pcb")\n\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
        '\t(descr "Trenz TE0720 carrier side: JB1/JB2 LSHM-150, JB3 LSHM-130, 4x M3 34x44. Per TE07XX-Connector-Dimension.")\n'
        "\t(attr smd)\n"
    )
    for field, text, y, layer in (
        ("Reference", "REF**", -my - 1.5, "F.SilkS"),
        ("Value", "TE0720-04", my + 1.5, "F.Fab"),
    ):
        out += (
            f'\t(property "{field}" "{text}"\n\t\t(at 0 {y} 0)\n\t\t(layer "{layer}")\n'
            "\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n"
        )
    # Module outline: drawn on Fab and Silk, not as courtyard, because small parts may be placed under the module (Integration Guide)
    for layer, width in (("F.Fab", 0.1), ("F.SilkS", 0.12)):
        out += (
            f"\t(fp_rect (start {-mx} {-my}) (end {mx} {my})\n"
            f'\t\t(stroke (width {width}) (type solid)) (fill no) (layer "{layer}"))\n'
        )
    for con, series in SERIES.items():
        place = PLACE[con]
        half = {"150": 16.0, "130": 11.0}[series]
        hw, hh = (3.0, half) if place[2] else (half, 3.0)
        out += (
            f"\t(fp_rect (start {place[0] - hw} {place[1] - hh}) (end {place[0] + hw} {place[1] + hh})\n"
            '\t\t(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        )
        # pin 1 marker
        p1 = transform(-{"150": 12.25, "130": 7.25}[series], -1.85, place)
        off = (p1[0] + 1.6, p1[1]) if place[2] else (p1[0], p1[1] - 1.6)
        out += (
            f"\t(fp_circle (center {off[0]} {off[1]}) (end {off[0] + 0.2} {off[1]})\n"
            '\t\t(stroke (width 0.12) (type solid)) (fill yes) (layer "F.SilkS"))\n'
        )
        for num, kind, shape, x, y, sx, sy, drill in lshm_pads(fp_dir, series):
            tx, ty = transform(float(x), float(y), place)
            if place[2]:
                sx, sy = sy, sx
            if kind == "smd":
                out += (
                    f'\t(pad "{con}.{num}" smd {shape} (at {tx} {ty}) (size {sx} {sy})\n'
                    '\t\t(layers "F.Cu" "F.Paste" "F.Mask"))\n'
                )
            elif kind == "thru_hole":
                out += (
                    f'\t(pad "SH" thru_hole {shape} (at {tx} {ty}) (size {sx} {sy}) (drill {drill})\n'
                    '\t\t(layers "*.Cu" "*.Mask"))\n'
                )
            else:
                out += (
                    f'\t(pad "" np_thru_hole {shape} (at {tx} {ty}) (size {sx} {sy}) (drill {drill})\n'
                    '\t\t(layers "*.Cu" "*.Mask"))\n'
                )
    for x, y in HOLES:
        out += (
            f'\t(pad "MH" thru_hole circle (at {x} {y}) (size 6 6) (drill 3.2)\n'
            '\t\t(layers "*.Cu" "*.Mask"))\n'
        )
        out += (
            f"\t(fp_circle (center {x} {y}) (end {x + 3.25} {y})\n"
            '\t\t(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        )
    for con, series in SERIES.items():
        n = {"150": "50", "130": "30"}[series]
        cx, cy, rot = PLACE[con]
        r = -90 if rot else 0
        out += (
            f'\t(model "${{KICAD10_3DMODEL_DIR}}/Connector_Samtec.3dshapes/Samtec_LSHM-{series}-xx.x-x-DV-S_2x{n}-1SH_P0.50mm_Vertical.step"\n'
            f"\t\t(offset (xyz {cx} {-cy} 0))\n\t\t(scale (xyz 1 1 1))\n\t\t(rotate (xyz 0 0 {r}))\n\t)\n"
        )
    out += ")\n"
    with open(path, "w") as f:
        f.write(out)


if __name__ == "__main__":
    lib, fp_dir = sys.argv[1], sys.argv[2]
    pins = json.load(open(f"{lib}/te0720_pins.json"))
    os.makedirs(f"{lib}/footprints/{NAME}.pretty", exist_ok=True)
    make_symbol(f"{lib}/symbols/{NAME}.kicad_sym", carrier_table(pins))
    make_footprint(f"{lib}/footprints/{NAME}.pretty/{NAME}.kicad_mod", fp_dir)
    print("ok")
