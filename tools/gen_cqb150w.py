#!/usr/bin/env python3
"""Generate the KiCad symbol and footprint for the Cincon CQB150W (quarter brick).

Dimensions: CQB150W datasheet Rev V17, page 9, Mechanical Specification (BOTTOM VIEW).
The footprint is viewed from above the board (module on the F side), so the bottom view is mirrored left to right.

Bottom view, origin at the body center:
- Left column x=-23.6: pin 3(-Vin) y=-7.62, pin 2(On/Off) y=0, pin 1(+Vin) y=+7.62
- Right column x=+23.6: pin 4(-Vo) y=-7.62, 5(-Sen) y=-3.81, 6(Trim) y=0, 7(+Sen) y=+3.81, 8(+Vo) y=+7.62
- Pins: Φ1.02 ×6 (pin 1,2,3,5,6,7), Φ1.50 ×2 (pin 4,8)
- M3 holes: (+25.4, -13.075), (-25.4, +13.075)
- Body 57.9 × 36.8, height 12.7

Usage: gen_cqb150w.py <kicad/lib directory>
"""
import os
import sys

NAME = "CQB150W"
PINS = [
    # number, name, symbol side, symbol y
    ("1", "+Vin", "L", 5.08),
    ("2", "ON/OFF", "L", 0),
    ("3", "-Vin", "L", -5.08),
    ("8", "+Vo", "R", 10.16),
    ("7", "+Sen", "R", 5.08),
    ("6", "Trim", "R", 0),
    ("5", "-Sen", "R", -5.08),
    ("4", "-Vo", "R", -10.16),
]
BOTTOM = {
    "1": (-23.6, 7.62),
    "2": (-23.6, 0),
    "3": (-23.6, -7.62),
    "4": (23.6, -7.62),
    "5": (23.6, -3.81),
    "6": (23.6, 0),
    "7": (23.6, 3.81),
    "8": (23.6, 7.62),
}
BIG = {"4", "8"}
HOLES_BOTTOM = [(25.4, -13.075), (-25.4, 13.075)]
BODY = (57.9, 36.8)


def font():
    return "(effects (font (size 1.27 1.27)))"


def make_symbol(path):
    w, h = 12.7, 12.7
    pins = ""
    for num, name, side, y in PINS:
        x = -w - 2.54 if side == "L" else w + 2.54
        ang = 0 if side == "L" else 180
        pins += (
            f'\t\t\t(pin passive line (at {x} {y} {ang}) (length 2.54)\n'
            f'\t\t\t\t(name "{name}" {font()})\n\t\t\t\t(number "{num}" {font()})\n\t\t\t)\n'
        )
    out = f"""(kicad_symbol_lib
	(version 20251024)
	(generator "hv_awg_pcb")
	(generator_version "10.0")
	(symbol "{NAME}"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "PS" (at 0 {h + 1.27} 0) {font()})
		(property "Value" "CQB150W-24S48" (at 0 {-h - 1.27} 0) {font()})
		(property "Footprint" "{NAME}:{NAME}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Datasheet" "https://www.cincon.com/productdownload/Datasheet-CQB150W-series.pdf" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(property "Description" "Cincon CQB150W quarter brick isolated DC-DC, 150W" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
		(symbol "{NAME}_0_1"
			(rectangle (start {-w} {h}) (end {w} {-h})
				(stroke (width 0.254) (type default))
				(fill (type background))
			)
		)
		(symbol "{NAME}_1_1"
{pins}		)
	)
)
"""
    with open(path, "w") as f:
        f.write(out)


def make_footprint(path):
    bx, by = BODY[0] / 2, BODY[1] / 2
    cx, cy = bx + 0.5, by + 0.5
    out = f'(footprint "{NAME}"\n\t(version 20241229)\n\t(generator "hv_awg_pcb")\n\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
    out += '\t(descr "Cincon CQB150W quarter brick, datasheet Rev V17 page 9, mirrored from bottom view")\n\t(attr through_hole)\n'
    for field, text, y, layer in (
        ("Reference", "REF**", -cy - 1.2, "F.SilkS"),
        ("Value", "CQB150W-24S48", cy + 1.2, "F.Fab"),
    ):
        out += (
            f'\t(property "{field}" "{text}"\n\t\t(at 0 {y} 0)\n\t\t(layer "{layer}")\n'
            "\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n"
        )
    for x, y, layer, width in ((bx, by, "F.Fab", 0.1), (bx + 0.12, by + 0.12, "F.SilkS", 0.12), (cx, cy, "F.CrtYd", 0.05)):
        out += (
            f"\t(fp_rect (start {-x} {-y}) (end {x} {y})\n"
            f'\t\t(stroke (width {width}) (type solid)) (fill no) (layer "{layer}"))\n'
        )
    # pin 1 marker (+Vin, bottom right when viewed from above)
    px, py = -BOTTOM["1"][0], BOTTOM["1"][1]
    out += (
        f"\t(fp_circle (center {px + 3} {py}) (end {px + 3.4} {py})\n"
        '\t\t(stroke (width 0.12) (type solid)) (fill yes) (layer "F.SilkS"))\n'
    )
    for num, (bxp, byp) in BOTTOM.items():
        x, y = -bxp, byp  # mirror bottom view to top view
        drill, pad = (1.8, 3.0) if num in BIG else (1.3, 2.2)
        shape = "rect" if num == "1" else "circle"
        out += (
            f'\t(pad "{num}" thru_hole {shape} (at {x} {y}) (size {pad} {pad}) (drill {drill})\n'
            '\t\t(layers "*.Cu" "*.Mask"))\n'
        )
    for bxp, byp in HOLES_BOTTOM:
        out += (
            f'\t(pad "" np_thru_hole circle (at {-bxp} {byp}) (size 3.2 3.2) (drill 3.2)\n'
            '\t\t(layers "*.Cu" "*.Mask"))\n'
        )
    out += ")\n"
    with open(path, "w") as f:
        f.write(out)


if __name__ == "__main__":
    lib = sys.argv[1]
    os.makedirs(f"{lib}/footprints/{NAME}.pretty", exist_ok=True)
    make_symbol(f"{lib}/symbols/{NAME}.kicad_sym")
    make_footprint(f"{lib}/footprints/{NAME}.pretty/{NAME}.kicad_mod")
    print("ok")
