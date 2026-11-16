#!/usr/bin/env python3
"""Copy the peripheral part libraries from the local Ultra Librarian library into the project and fix pin types and footprint paths.

The original files (eda-libraries) are left untouched. UL pin types are often wrong (e.g. isolated supply inputs
marked power_in, outputs marked power_in), causing false or missed ERC errors, so they are corrected per the
datasheets in the project copy.

Usage: import_ul_parts.py <eda-libraries/KICAD/v9> <kicad/lib directory>
"""
import os
import re
import shutil
import sys

# library name: (footprint file name, {pin name: type})
PARTS = {
    "ul_REF5050IDR": (
        "D8",
        {"DNC": "no_connect", "NC": "no_connect", "VIN": "power_in", "TEMP": "passive", "GND": "power_in", "TRIM/NR": "passive", "VOUT": "power_out"},
    ),
    "ul_TPS75233QPWPR": (
        "PWP20",
        {"GND/HEATSINK": "power_in", "GND": "power_in", "IN": "power_in", "*EN": "input", "PG/*RESET": "open_collector", "FB/SENSE": "passive", "OUTPUT": "power_out", "NC": "no_connect"},
    ),
    "ul_REC15E-2405SZ": (
        "REC15E-2415SZ_RCP",
        {"+VIN": "passive", "-VIN": "passive", "CTRL": "passive", "-VOUT": "passive", "TRIM": "passive", "+VOUT": "power_out"},
    ),
    "ul_R3M-2409S-SMD": (
        "R3M_SMD_RCP",
        {"+VIN": "passive", "-VIN": "passive", "CTRL": "passive", "-VOUT": "passive", "+VOUT": "power_out", "NC": "no_connect"},
    ),
}


# STEP file names in the local eda-libraries/3D
STEP = {
    "ul_REF5050IDR": "REF5050IDR.STEP",
    "ul_TPS75233QPWPR": "TPS75233QPWPREP.STEP",
    "ul_REC15E-2405SZ": "REC15E-2405SZ--3DModel-STEP-1.STEP",
    "ul_R3M-2409S-SMD": "R3M-2409S_SMD.STEP",
}
# For an output with several same-named pins, only the first is power_out and the rest are passive; otherwise ERC reports power_out connected to power_out
SINGLE_DRIVER = {"OUTPUT"}


def main(src, dst):
    for lib, (fp, types) in PARTS.items():
        t = open(f"{src}/symbols/{lib}.kicad_sym").read()
        seen = set()

        def fix(m):
            name = m.group(3)
            kind = types.get(name, m.group(1))
            if name in SINGLE_DRIVER and name in seen:
                kind = "passive"
            seen.add(name)
            return f"(pin {kind} {m.group(2)}"

        t = re.sub(r'\(pin (\w+) (\w+)(?=\s+\(at [^)]*\)\s+\(length [\d.]+\)\s+\(name "([^"]*)")', fix, t)
        assert seen <= set(types), (lib, seen - set(types))
        t, n = re.subn(rf'\(property "Footprint" "{re.escape(fp)}"', f'(property "Footprint" "{lib}:{fp}"', t)
        assert n >= 1, lib
        with open(f"{dst}/symbols/{lib}.kicad_sym", "w") as f:
            f.write(t)
        d = f"{dst}/footprints/{lib}.pretty"
        os.makedirs(d, exist_ok=True)
        m = open(f"{src}/footprints/{lib}.pretty/{fp}.kicad_mod").read()
        # The 3D model path was an absolute path on the Desktop; change it to a project-relative path and copy the STEP file
        m = re.sub(r'\(model "[^"]*"', '(model "${KIPRJMOD}/../lib/3d/' + STEP[lib] + '"', m)
        shutil.copyfile(f"{src}/../../3D/{STEP[lib]}", f"{dst}/3d/{STEP[lib]}")
        # TPS75233 PowerPAD: the symbol has no pin for it, so the footprint's EPAD would get no net.
        # The datasheet requires it to be soldered to ground, so merge it into pad 1 (GND/HEATSINK)
        if lib == "ul_TPS75233QPWPR":
            m, k = re.subn(r'\(pad "EPAD"', '(pad "1"', m)
            assert k == 1
        with open(f"{d}/{fp}.kicad_mod", "w") as f:
            f.write(m)
        print(lib, re.findall(r'\(symbol "([^"]+)"', t)[0], sorted(seen))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
