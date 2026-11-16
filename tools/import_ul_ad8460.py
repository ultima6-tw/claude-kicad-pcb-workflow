#!/usr/bin/env python3
"""Copy the AD8460 library from the local Ultra Librarian library into the project and fix its pin types.

The original files (eda-libraries) are left untouched. Pin numbers and names were checked against AD8460
datasheet Table 6; the only two differences are *RESET and *CS, which is UL's notation for active-low.

Some UL pin types are wrong and cause false or missed ERC errors:
- GND marked power_out (should be power_in)
- pin 14 HVCC marked unspecified (should be power_in)
- pin 16 NC marked power_in (should be no_connect)
- OUT, COMP_*, TMP marked unspecified; AVDD/DVDD are internal LDO outputs and must not be treated as power inputs

Usage: import_ul_ad8460.py <eda-libraries/KICAD/v9> <kicad/lib directory>
"""
import os
import re
import sys

TYPES = {
    "GND": "power_in",
    "HVCC": "power_in",
    "HVEE": "power_in",
    "VCC_5V": "power_in",
    "VREF_5V": "power_in",
    "AVDD_3P3V": "passive",
    "DVDD_3P3V": "passive",
    "OUT": "passive",
    "COMP_H": "passive",
    "COMP_L": "passive",
    "COMP_T": "passive",
    "TMP": "output",
    "IOUTP": "passive",
    "IOUTN": "passive",
    "INP": "passive",
    "INN": "passive",
    "REFIO_1P2V": "passive",
    "FS_ADJ": "passive",
    "SDO": "tri_state",
    "NC": "no_connect",
}


def main(src, dst):
    t = open(f"{src}/symbols/ul_AD8460BSVZ.kicad_sym").read()

    t, n = re.subn(r'\(pin (\w+) (\w+)(?=\s+\(at [^)]*\)\s+\(length [\d.]+\)\s+\(name "([^"]*)")', lambda m: f"(pin {TYPES.get(m.group(3), m.group(1))} {m.group(2)}", t)
    assert n == 80, n
    t = t.replace('(name "*RESET"', '(name "~{RESET}"').replace('(name "*CS"', '(name "~{CS}"')
    t = t.replace('(property "Footprint" "SV-80-7_ADI"', '(property "Footprint" "ul_AD8460BSVZ:SV-80-7_ADI"')
    with open(f"{dst}/symbols/ul_AD8460BSVZ.kicad_sym", "w") as f:
        f.write(t)
    d = f"{dst}/footprints/ul_AD8460BSVZ.pretty"
    os.makedirs(d, exist_ok=True)
    # The 3D model path was an absolute path on the Desktop; change it to a project-relative path (the STEP file is already copied to lib/3d)
    fp = open(f"{src}/footprints/ul_AD8460BSVZ.pretty/SV-80-7_ADI.kicad_mod").read()
    fp, m = re.subn(r'\(model "[^"]*ul_AD8460BSVZ\.step"', '(model "${KIPRJMOD}/../lib/3d/ul_AD8460BSVZ.step"', fp)
    assert m == 1
    with open(f"{d}/SV-80-7_ADI.kicad_mod", "w") as f:
        f.write(fp)
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
