#!/usr/bin/env python3
"""Write the net classes and netclass_patterns into hv_awg.kicad_pro.

These settings have been overwritten and lost before; when they are missing, the A/B high-voltage rules in
.kicad_dru silently stop working while DRC still passes. So reapply them before every DRC run, and use
tools/test_hv_rule.py to confirm the rules actually catch violations.

Usage: apply_netclass.py <hv_awg.kicad_pro> <side_a.json>
"""
import json
import sys


def main(pro, side_a):
    side = json.load(open(side_a))
    c = json.load(open(pro))
    ns = c["net_settings"]
    base = ns["classes"][0]
    base.update(clearance=0.15, track_width=0.15, via_diameter=0.45, via_drill=0.2)

    def cls(name, **k):
        x = dict(base)
        x.update(name=name, priority=1, **k)
        return x

    ns["classes"] = [
        base,
        cls("SIDE_A", clearance=0.2, track_width=0.5, via_diameter=0.8, via_drill=0.4),
        cls("HV52", clearance=0.2, track_width=0.8, via_diameter=0.8, via_drill=0.4),
        cls("PWR", clearance=0.15, track_width=0.5, via_diameter=0.6, via_drill=0.3),
    ]
    pat = []
    for n in side + ["/ETH_CHASSIS"]:
        pat.append({"netclass": "SIDE_A", "pattern": n})
    for n in ["/P52V", "/N52V"]:
        pat.append({"netclass": "HV52", "pattern": n})
    for n in ["/GND_B_300V", "/P9V", "/CELL1_P3V3", "/CELL*/P5V", "/CELL*/P3V3", "/CELL*/P3V3_IN", "/CELL*/VREF_IN"]:
        pat.append({"netclass": "PWR", "pattern": n})
    ns["netclass_patterns"] = pat
    c.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {}).update(
        min_clearance=0.15, min_track_width=0.15, min_via_diameter=0.45, min_through_hole_diameter=0.2, min_via_annular_width=0.1, min_connection=0.15
    )
    json.dump(c, open(pro, "w"), indent=2)
    print("classes", [x["name"] for x in ns["classes"]], "patterns", len(pat))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
