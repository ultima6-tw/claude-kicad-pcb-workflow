#!/usr/bin/env python3
"""Generate the KiCad symbol for the LMK1C1106A (1:6 LVCMOS clock buffer, TSSOP-14).

This part is not in the KiCad built-in libraries. Pinout source: TI SNAS947 (MAY 2025) Table 5-1, Figure 5-6.
The footprint is the built-in Package_SO:TSSOP-14_4.4x5mm_P0.65mm.

Usage: gen_lmk1c1106a.py <kicad/lib directory>
"""
import sys

NAME = "LMK1C1106A"
LEFT = [("1", "CLKIN", "input"), ("2", "1G", "input")]
RIGHT = [("3", "Y0", "output"), ("14", "Y1", "output"), ("11", "Y2", "output"), ("13", "Y3", "output"), ("6", "Y4", "output"), ("9", "Y5", "output")]
TOP = [("5", "VDD", "power_in"), ("8", "VDD", "passive"), ("12", "VDD", "passive")]
BOTTOM = [("4", "GND", "power_in"), ("7", "GND", "passive"), ("10", "GND", "passive")]


def font(hide=False):
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size 1.27 1.27)){h})"


def pin(num, name, kind, x, y, ang):
    return (
        f"\t\t\t(pin {kind} line (at {x} {y} {ang}) (length 2.54)\n"
        f"\t\t\t\t(name \"{name}\" {font()})\n\t\t\t\t(number \"{num}\" {font()})\n\t\t\t)\n"
    )


def main(lib):
    w, h = 10.16, 10.16
    pins = ""
    for i, (n, nm, k) in enumerate(LEFT):
        pins += pin(n, nm, k, -w - 2.54, 2.54 - i * 5.08, 0)
    for i, (n, nm, k) in enumerate(RIGHT):
        pins += pin(n, nm, k, w + 2.54, 6.35 - i * 2.54, 180)
    for i, (n, nm, k) in enumerate(TOP):
        pins += pin(n, nm, k, -2.54 + i * 2.54, h + 2.54, 270)
    for i, (n, nm, k) in enumerate(BOTTOM):
        pins += pin(n, nm, k, -2.54 + i * 2.54, -h - 2.54, 90)
    out = f"""(kicad_symbol_lib
	(version 20251024)
	(generator "hv_awg_pcb")
	(generator_version "10.0")
	(symbol "{NAME}"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "U" (at -7.62 13.97 0) {font()})
		(property "Value" "{NAME}" (at 2.54 13.97 0) {font()})
		(property "Footprint" "Package_SO:TSSOP-14_4.4x5mm_P0.65mm" (at 0 0 0) {font(True)})
		(property "Datasheet" "https://www.ti.com/lit/ds/symlink/lmk1c1108a.pdf" (at 0 0 0) {font(True)})
		(property "Description" "1:6 LVCMOS clock buffer, asynchronous output enable, 250 MHz at 3.3 V" (at 0 0 0) {font(True)})
		(symbol "{NAME}_1_1"
			(rectangle (start {-w} {h}) (end {w} {-h})
				(stroke (width 0.254) (type default))
				(fill (type background))
			)
{pins}		)
		(embedded_fonts no)
	)
)
"""
    with open(f"{lib}/symbols/{NAME}.kicad_sym", "w") as f:
        f.write(out)
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1])
