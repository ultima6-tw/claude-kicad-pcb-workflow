#!/usr/bin/env python3
"""Write the netlist exported by kicad-cli into the pads of a .kicad_pcb and fill in each footprint's schematic path.

The MCP's sync_schematic_to_board does not support multi-level hierarchies with reused sheets: parts inside
CELL and DAC get no net, and the root and POWER net names differ from the official netlist. This script
treats the official netlist as authoritative; afterwards verify with `kicad-cli pcb drc --schematic-parity`,
not with this script's own counts.

Usage: assign_nets.py <hv.xml> <board.kicad_pcb>
"""
import re
import sys
import xml.etree.ElementTree as ET


def block_at(t, i):
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


def main(xml, board):
    r = ET.parse(xml).getroot()
    net_of = {}
    for n in r.find("nets"):
        for p in n:
            name = n.get("name")
            if name.startswith("unconnected-"):  # KiCad internally escapes slashes in unconnected net names
                name = name.replace("/", "{slash}")
            net_of[(p.get("ref"), p.get("pin"))] = name
    comp = {}
    for c in r.find("components"):
        sp = c.find("sheetpath")
        props = {x.get("name"): x.get("value") for x in c.findall("property")}
        comp[c.get("ref")] = dict(
            names=sp.get("names"), stamps=sp.get("tstamps"), tstamp=c.findtext("tstamps").split()[0], sfile=props.get("Sheetfile", ""),
            datasheet=c.findtext("datasheet") or "", descr=c.findtext("description") or "", dnp="dnp" in props, no_bom="exclude_from_bom" in props,
        )

    t = open(board).read()
    out = []
    last = 0
    seen = set()
    n_pad = n_net = 0
    for i, e in blocks(t, "(footprint "):
        b = t[i:e]
        ref = re.search(r'\(property "Reference" "([^"]+)"', b).group(1)
        assert ref in comp, ref
        seen.add(ref)

        def pad_fix(pb):
            nonlocal n_pad, n_net
            num = re.match(r'\(pad "([^"]*)"', pb).group(1)
            pb = re.sub(r'\s*\(net (?:\d+ )?"[^"]*"\)', "", pb)
            n_pad += 1
            net = net_of.get((ref, num))
            if net is None:
                return pb
            n_net += 1
            esc = net.replace("\\", "\\\\").replace('"', '\\"')
            # put (net ...) before uuid, matching the order KiCad saves in
            return re.sub(r'(\s*)\(uuid ', lambda m: f'{m.group(1)}(net "{esc}"){m.group(1)}(uuid ', pb, count=1)

        res = []
        l2 = 0
        for pi, pe in blocks(b, "(pad "):
            res.append(b[l2:pi])
            res.append(pad_fix(b[pi:pe]))
            l2 = pe
        res.append(b[l2:])
        b = "".join(res)

        c = comp[ref]
        b = re.sub(r'\s*\((?:path|sheetname|sheetfile) "[^"]*"\)', "", b)
        ins = f'\n\t\t(path "{c["stamps"]}{c["tstamp"]}")\n\t\t(sheetname "{c["names"]}")\n\t\t(sheetfile "{c["sfile"]}")'
        for field, val in (("Datasheet", c["datasheet"]), ("Description", c["descr"])):
            esc = val.replace("\\", "\\\\").replace('"', '\\"')
            b = re.sub(rf'\(property "{field}" "(?:[^"\\]|\\.)*"', lambda m: f'(property "{field}" "{esc}"', b)
        # attr: DNP and BOM flags must match the symbol
        m = re.search(r"\(attr([^)]*)\)", b)
        flags = m.group(1).split() if m else []
        flags = [f for f in flags if f not in ("dnp", "exclude_from_bom")]
        if c["no_bom"]:
            flags.append("exclude_from_bom")
        if c["dnp"]:
            flags.append("dnp")
        if m:
            b = b[: m.start()] + "(attr " + " ".join(flags) + ")" + b[m.end() :] if flags else b[: m.start()] + b[m.end() :]
        elif flags:
            ins += "\n\t\t(attr " + " ".join(flags) + ")"
        k = b.rfind("(property ")
        k = block_at(b, k)
        b = b[:k] + ins + b[k:]
        out.append(t[last:i])
        out.append(b)
        last = e
    out.append(t[last:])
    missing = set(comp) - seen
    assert not missing, sorted(missing)[:10]
    open(board, "w").write("".join(out))
    print(f"footprints {len(seen)}, pads {n_pad}, with net {n_net}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
