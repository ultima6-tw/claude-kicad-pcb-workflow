#!/usr/bin/env python3
"""Keep only the CELL1 parts and fill the zones, for DRC. The other parts are still stacked at the origin; leaving them in would flood the report.

The input board must have the correct .kicad_pro next to it: zone clearance is decided at fill time, and without the A/B rules the fill ends up too close.

Usage (KiCad Python): fill_c1.py <input board> <output board>
"""
import os
import re
import shutil
import sys
import time

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
for f in list(b.GetFootprints()):
    if not re.match(r"[A-Z]+1\d{3}$", f.GetReference()):
        b.Remove(f)
t = time.time()
zones = b.Zones()
pcbnew.ZONE_FILLER(b).Fill(zones)
print("zones", len(list(zones)), "fill", round(time.time() - t, 1), "s")
pcbnew.SaveBoard(sys.argv[2], b)
# SaveBoard rewrites the project file; the output must use the same rules as the input
shutil.copy(os.path.splitext(sys.argv[1])[0] + ".kicad_pro", os.path.splitext(sys.argv[2])[0] + ".kicad_pro")
