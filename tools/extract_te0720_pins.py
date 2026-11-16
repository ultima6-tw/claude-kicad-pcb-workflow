#!/usr/bin/env python3
"""Extract the B2B connector pins and nets from page 5 of the TE0720 Rev 04 schematic.

Input: HTML produced by pdftotext -f 5 -l 5 -bbox
Output: JSON {"JM1": {"1": "VIN", ...}, ...} (module-side pin numbers)

Rules:
- Left/right side is decided by the x position of the actual pin-number text; on JM3 the odd pins are on the left, on JM1/JM2 the even pins
- The net text must be on the same row as the pin number
- Power pins share one bus in the drawing and their text does not line up with a row, so the list from TRM Table 6 is used instead
- All other pins without a net are treated as GND, then checked against the I/O counts in the TRM and the drawing

Usage: extract_te0720_pins.py <page5.html> <output.json>
"""
import collections
import json
import re
import sys

# TRM Rev 04 Table 6. "JM2.4 / JM2.4" in the TRM is a typo; the drawing shows JM2.2, JM2.4
POWER = {
    ("JM1", 1): "VIN", ("JM1", 3): "VIN", ("JM1", 5): "VIN",
    ("JM2", 2): "VIN", ("JM2", 4): "VIN", ("JM2", 6): "VIN", ("JM2", 8): "VIN",
    ("JM1", 13): "3.3VIN", ("JM1", 15): "3.3VIN",
    ("JM2", 91): "VREF_JTAG",  # TRM: 3.3VIN brought out internally, direction OUT, used only as the JTAG reference
    ("JM2", 1): "VCCIO34", ("JM2", 3): "VCCIO34",
    ("JM2", 5): "VCCIO33",
    ("JM2", 7): "VCCIO13", ("JM2", 9): "VCCIO13",
    ("JM1", 9): "VCCIO35", ("JM1", 11): "VCCIO35",
    ("JM2", 10): "3.3V", ("JM2", 12): "3.3V",
    ("JM1", 39): "1.8V",
    ("JM2", 19): "1.5V",
}
NET = re.compile(
    r"^(B\d+_(L\d+_[PN]|IO\d+|VREF)|MIO\d+|PHY_\w+|EN1|PGOOD|MODE|JTAGMODE|NOSEQ|RESIN|"
    r"X_T[A-Z]+|SOUT_[PN]|SIN_[PN]|OTG-\S+|VBUS_V_EN|USB-VBUS|VBAT_IN|LED\w*|ETH\w*)$"
)


def main(html, out):
    t = open(html).read()
    words = [
        (float(a), float(b), float(c), float(d), w)
        for a, b, c, d, w in re.findall(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', t
        )
    ]
    markers = {}
    for x0, y0, x1, y1, w in words:
        m = re.fullmatch(r"PIJM([123])0(\d+)", w)
        if m:
            markers[(f"JM{m.group(1)}", int(m.group(2)))] = ((x0 + x1) / 2, (y0 + y1) / 2)

    pos = {}
    for (con, pin), (mx, my) in markers.items():
        near = [
            w for w in words
            if w[4] == str(pin) and abs((w[0] + w[2]) / 2 - mx) < 18 and -12 < (w[1] + w[3]) / 2 - my < 2
        ]
        assert near, (con, pin)
        n = min(near, key=lambda w: abs((w[1] + w[3]) / 2 - my))
        pos[(con, pin)] = ((n[0] + n[2]) / 2, (n[1] + n[3]) / 2)

    result = collections.defaultdict(dict)
    for con in ("JM1", "JM2", "JM3"):
        xs = [v[0] for k, v in pos.items() if k[0] == con]
        center = (min(xs) + max(xs)) / 2
        for (c, pin), (x, y) in sorted(pos.items()):
            if c != con:
                continue
            left = x < center
            cand = [
                w for w in words
                if abs((w[1] + w[3]) / 2 - y) < 3.2
                and NET.match(w[4])
                and ((w[2] < x and x - w[2] < 150) if left else (w[0] > x and w[0] - x < 150))
            ]
            cand.sort(key=lambda w: abs((w[0] + w[2]) / 2 - x))
            name = POWER.get((con, pin))
            if name is None:
                name = cand[0][4] if cand else "GND"
            result[con][str(pin)] = name
    json.dump(result, open(out, "w"), indent=1, ensure_ascii=False)

    # Check: I/O counts from the TRM
    for con in ("JM1", "JM2", "JM3"):
        names = list(result[con].values())
        hr = [n for n in names if re.match(r"B\d+_(L\d+_[PN]|IO\d+)", n)]
        by = collections.Counter(n.split("_")[0] for n in hr)
        print(con, "pins", len(names), "HR", len(hr), dict(by), "MIO", sum(n.startswith("MIO") for n in names), "GND", names.count("GND"))
        dup = [n for n, k in collections.Counter(names).items() if k > 1 and n not in {"GND", "VIN", "3.3VIN", "VCCIO34", "VCCIO13", "VCCIO35", "3.3V"}]
        print("  duplicate nets:", dup)
    # Differential pairs must be complete, and no I/O net may appear twice on the sheet
    all_io = [n for c in result.values() for n in c.values() if re.match(r"B\d+_L\d+_[PN]$", n)]
    assert len(all_io) == len(set(all_io)), "duplicate I/O net"
    missing = [n for n in all_io if n[:-1] + ("N" if n[-1] == "P" else "P") not in all_io]
    print("differential pairs missing the other half:", missing)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
