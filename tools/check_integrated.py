#!/usr/bin/env python3
"""Verify the integrated board netlist.

1. POWER and the 16 DAC copies: map each single-sheet netlist through its reference offset; internal nets must
   match exactly, and interface nets must be a subset of some net on the integrated board.
2. FPGA pins: for every signal in pin_map.json, the TE0720 pin and the DAC pin must be on the same net.
3. No shorts between cells: D*_DB* in different cells must be on different nets.

4. Connections of the clock, trigger, master control pins, and RJ45.

Usage: check_integrated.py <hv.xml> <power.xml> <ad8460.xml> <pin_map.json> <te0720_pins.json>
"""
import json
import re
import sys
import xml.etree.ElementTree as ET

AD8460_PIN = {f"DB{i}": str(53 + i) for i in range(14)}
AD8460_PIN.update({"CS_N": "40"})


def nets(path):
    r = ET.parse(path).getroot()
    return {n.get("name"): {(p.get("ref"), p.get("pin")) for p in n} for n in r.find("nets")}


def shift(ref, off):
    pre, num = re.match(r"([A-Za-z#]+)(\d+)", ref).groups()
    return f"{pre}{int(num) + off}"


def check(single, whole, off, tag):
    ok = bad = interface = 0
    for name, pins in single.items():
        mapped = {(shift(r, off), p) for r, p in pins if not r.startswith("#")}
        if not mapped:
            continue
        hits = [n for n, s in whole.items() if mapped <= s]
        if len(hits) != 1:
            bad += 1
            print(f"  [ERR] {tag} {name}: found {hits}")
        elif whole[hits[0]] == mapped:
            ok += 1
        else:
            interface += 1
    return ok, interface, bad


def main(hv, power, ad, pin_map, te0720):
    whole = nets(hv)
    whole = {n: {x for x in s if not x[0].startswith("#")} for n, s in whole.items()}
    total = 0
    ok, i, b = check(nets(power), whole, 0, "POWER")
    total += b
    print(f"POWER: internal match {ok}, interface {i}, errors {b}")
    single = nets(ad)
    oks = ifs = 0
    for k in range(1, 5):
        for j in range(1, 5):
            ok, i, b = check(single, whole, k * 1000 + j * 100, f"C{k}D{j}")
            total += b
            oks += ok
            ifs += i
    print(f"DAC ×16: internal match {oks}, interface {ifs}, total errors so far {total}")

    by_pin = {p: n for n, s in whole.items() for p in s}
    pm = json.load(open(pin_map))
    bad = seen = 0
    db_nets = set()
    for k in range(1, 5):
        fpga = f"U{k * 1000 + 1}"
        for j in range(1, 5):
            dac = f"U{k * 1000 + j * 100 + 1}"
            for sig, pin in AD8460_PIN.items():
                a = by_pin.get((fpga, pm[f"D{j}_{sig}"][0]))
                b_ = by_pin.get((dac, pin))
                seen += 1
                if a is None or a != b_:
                    bad += 1
                    print(f"  [ERR] C{k} D{j} {sig}: FPGA {a} / DAC {b_}")
                if a in db_nets:
                    bad += 1
                    print(f"  [ERR] {a} used more than once")
                db_nets.add(a)
            # SYNC goes through 33Ω: the FPGA pin must connect to pin 1 of R4
            a = by_pin.get((fpga, pm[f"D{j}_SYNC"][0]))
            b_ = by_pin.get((f"R{k * 1000 + j * 100 + 4}", "1"))
            seen += 1
            if a is None or a != b_:
                bad += 1
                print(f"  [ERR] C{k} D{j} SYNC: {a} / {b_}")
    print(f"FPGA↔DAC pins: checked {seen}, errors {bad}")
    total += bad

    # Clock, trigger: each FPGA's F_CLK / F_TRIG_IN must connect to its buffer output
    bad = 0
    y_pin = {1: "3", 2: "14", 3: "11", 4: "13"}
    for k in y_pin:
        fpga = f"U{k * 1000 + 1}"
        for sig, buf in (("F_CLK", "U102"), ("F_TRIG_IN", "U104")):
            a = by_pin.get((fpga, pm[sig][0]))
            b_ = by_pin.get((buf, y_pin[k]))
            if a is None or a != b_:
                bad += 1
                print(f"  [ERR] CELL{k} {sig}: {a} / {b_}")
    # Master control pins and RJ45 connect only to CELL1; the same pin on a slave must not be on that net
    for sig, part, pin in (("F_EN", "U102", "2"), ("F_EN", "U104", "2"), ("F_CLK_SEL", "U101", "6"), ("F_TRIG_SEL", "U103", "6"), ("F_TRIG_OUT", "U103", "1")):
        a = by_pin.get(("U1001", pm[sig][0]))
        if a is None or a != by_pin.get((part, pin)):
            bad += 1
            print(f"  [ERR] master {sig}: {a}")
        for k in (2, 3, 4):
            if by_pin.get((f"U{k * 1000 + 1}", pm[sig][0])) == a:
                bad += 1
                print(f"  [ERR] CELL{k} {sig} connected to the master net")
    mdi = {"PHY_MDI0_P": "11", "PHY_MDI0_N": "10", "PHY_MDI1_P": "4", "PHY_MDI1_N": "5", "PHY_MDI2_P": "3", "PHY_MDI2_N": "2", "PHY_MDI3_P": "8", "PHY_MDI3_N": "9"}
    te = json.load(open(te0720))["JM1"]
    for name, rj in mdi.items():
        mod = next(int(p) for p, n in te.items() if n == name)
        car = mod + 1 if mod % 2 else mod - 1
        a = by_pin.get(("U1001", f"JB1.{car}"))
        if a is None or a != by_pin.get(("J101", rj)):
            bad += 1
            print(f"  [ERR] {name}: {a} / {by_pin.get(('J101', rj))}")
    print(f"clock/trigger/RJ45: errors {bad}")
    total += bad
    print("Result:", "all OK" if total == 0 else f"{total} errors")


if __name__ == "__main__":
    main(*sys.argv[1:6])
