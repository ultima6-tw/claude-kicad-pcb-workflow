#!/usr/bin/env python3
"""Full routing of CELL1: zones, power pins connected to planes, then signals and low-current power.

Power is connected first: the first version connected it after the signals, and the exits of 36 GND pins were blocked by signal tracks.

Layer usage: In1 = GND_B_300V; In4 = power split (within the cell):
- P52V: top band (y < 33.5), near the P52V bulk capacitors
- N52V: the DAC band (y 34–56)
- P5V: the rest (y > 56.5)
- P3V3_IN: small island around the LDO and JB1.14/16, higher priority than P5V

Low-current supplies (CELL1_P3V3, VREF_5V, VREF_IN) are routed with A* as ordinary nets.

Method: pull a stub out of the pad, then search on F.Cu (or the pad's layer) for the nearest point where a via can be placed, or a same-net track already connected to the plane;
if no path is found, record a failure instead of forcing a connection. Side A (GND_A, P24V_F, VIN_5) is done together in the central band and is not handled here.

Memory is the same as route_cell.py (peak about 500MB).

Usage (KiCad Python): route_power.py <base board with placement only> <output board> <report json> <side_a.json> [previous report json]
"""
import heapq
import json
import math
import re
import sys
import time

import pcbnew

sys.argv_saved = sys.argv
import route_cell as rc  # noqa: E402

GND = "/GND_B_300V"
ZONES = [
    # (net, layer, priority, x0, y0, x1, y1)
    # For x < GND_NOTCH_X, In1 only extends to GND_NOTCH_Y: no side-B plane under side-A parts
    (GND, pcbnew.In1_Cu, 0, 20.0, 20.0, 170.0, 136.0),
    ("/P52V", pcbnew.In4_Cu, 1, 20.0, 20.0, 170.0, 33.5),
    ("/N52V", pcbnew.In4_Cu, 1, 20.0, 34.0, 170.0, 56.0),
    ("/CELL1/P5V", pcbnew.In4_Cu, 1, 20.0, 56.5, 170.0, 120.0),
    ("/CELL1/P3V3_IN", pcbnew.In4_Cu, 2, 61.0, 89.6, 80.5, 100.5),
]
PLANE_NETS = [GND, "/P52V", "/N52V", "/CELL1/P5V", "/CELL1/P3V3_IN"]
TRACE_NETS = ["/CELL1_P3V3", "/CELL1/VREF_5V", "/CELL1/VREF_IN"]
BFS_LIMIT = 200000
GND_NOTCH_X = 70.0
GND_NOTCH_Y = 120.0


def add_zone(board, net, layer, prio, x0, y0, x1, y1):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(board.FindNet(net))
    z.SetAssignedPriority(prio)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetMinThickness(pcbnew.FromMM(0.2))
    o = z.Outline()
    o.NewOutline()
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if net == GND:
        pts = [(x0, y0), (x1, y0), (x1, y1), (GND_NOTCH_X, y1), (GND_NOTCH_X, GND_NOTCH_Y), (x0, GND_NOTCH_Y)]
    for x, y in pts:
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board.Add(z)


def in_zone(net, x, y):
    for n, _, prio, x0, y0, x1, y1 in ZONES:
        if n != net:
            continue
        if x0 + 0.5 <= x <= x1 - 0.5 and y0 + 0.5 <= y <= y1 - 0.5:
            if net == GND and x < GND_NOTCH_X + 0.5 and y > GND_NOTCH_Y - 0.5:
                return False
            # Inside an island, only the island's own net may place vias
            if net == "/CELL1/P5V" and 61.0 - 0.5 <= x <= 80.5 + 0.5 and 89.6 - 0.5 <= y <= 100.5 + 0.5:
                return False
            return True
    return False


class PowerRouter(rc.Router):
    def load_existing(self):  # The current flow starts from an empty board; kept for adding tracks on top of existing routing later
        """Mark existing tracks and vias on the board into the grid."""
        lidx = {l: i for i, l in enumerate(rc.LAYERS)}
        n_t = 0
        for t in self.board.Tracks():
            n = self.nid(t.GetNetname())
            if t.Type() == pcbnew.PCB_VIA_T:
                p = t.GetPosition()
                for li in range(len(rc.LAYERS)):
                    self.g.mark_disk(li, rc.mm(p.x), rc.mm(p.y), rc.VIA_D / 2 + rc.CLEAR + rc.TRACK / 2 + 0.02, n)
            else:
                li = lidx.get(t.GetLayer())
                if li is None:
                    continue
                a, b = t.GetStart(), t.GetEnd()
                self.g.mark_seg(li, (rc.mm(a.x), rc.mm(a.y)), (rc.mm(b.x), rc.mm(b.y)), rc.TRACK + rc.CLEAR + 0.02, n)
            n_t += 1
        return n_t

    def inside_own_pad(self, name, x, y):
        for p in self.pads.get(name, []):
            if p["x0"] - 0.1 <= x <= p["x1"] + 0.1 and p["y0"] - 0.1 <= y <= p["y1"] + 0.1:
                return True
        return False

    def straight_to_pad(self, name, n, pad):
        """When the exit is occupied, connect with a straight line to a nearby same-net pad instead (e.g. the AD8460 P5V pin to its decoupling capacitor)."""
        li = pad["on"][0]
        m = self.g.maps[li]
        near = [q for q in self.pads.get(name, []) if q is not pad and li in q["on"]]
        near.sort(key=lambda q: math.hypot(q["x"] - pad["x"], q["y"] - pad["y"]))
        for q in near:
            d = math.hypot(q["x"] - pad["x"], q["y"] - pad["y"])
            if d > 4.0:
                break
            steps = int(d / 0.05) + 1
            clear = True
            for t in range(steps + 1):
                ix, iy = rc.to_grid(pad["x"] + (q["x"] - pad["x"]) * t / steps, pad["y"] + (q["y"] - pad["y"]) * t / steps)
                if m[iy * rc.NX + ix] not in (rc.FREE, n):
                    clear = False
                    break
            if clear:
                self.emit_track(name, n, li, (pad["x"], pad["y"]), (q["x"], q["y"]))
                return "ok"
        return "stub"

    def to_plane(self, name, n, pad, attach):
        """Search from the pad: place a via on the same layer, or connect to attach (same-net nodes already connected to the plane). Returns a status."""
        li = pad["on"][0]
        m = self.g.maps[li]
        e = self.stub(pad)
        start = (pad["x"], pad["y"]) if e is None else e
        sx, sy = rc.to_grid(*start)
        if e is not None:
            # If the stub is occupied, route from the pad center instead
            ok = True
            for t in range(11):
                tx = pad["x"] + (e[0] - pad["x"]) * t / 10
                ty = pad["y"] + (e[1] - pad["y"]) * t / 10
                ix, iy = rc.to_grid(tx, ty)
                v = m[iy * rc.NX + ix]
                if v not in (rc.FREE, n):
                    ok = False
                    break
            if not ok:
                return self.straight_to_pad(name, n, pad)
        pq = [(0.0, sx, sy)]
        best = {(sx, sy): 0.0}
        prev = {}
        goal = None
        kind = None
        cnt = 0
        moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
        while pq:
            c, ix, iy = heapq.heappop(pq)
            if c > best.get((ix, iy), 1e18):
                continue
            cnt += 1
            if cnt > BFS_LIMIT:
                return "limit"
            if (li, ix, iy) in attach and (ix, iy) != (sx, sy):
                goal, kind = (ix, iy), "attach"
                break
            x, y = rc.to_mm(ix, iy)
            if in_zone(name, x, y) and not self.inside_own_pad(name, x, y) and rc.via_ok(self.g, ix, iy, n):
                goal, kind = (ix, iy), "via"
                break
            for dx, dy, w in moves:
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < rc.NX and 0 <= jy < rc.NY):
                    continue
                v = m[jy * rc.NX + jx]
                if v != rc.FREE and v != n:
                    continue
                if dx and dy:
                    a = m[iy * rc.NX + jx]
                    b = m[jy * rc.NX + ix]
                    if (a != rc.FREE and a != n) or (b != rc.FREE and b != n):
                        continue
                nc = c + w
                if nc < best.get((jx, jy), 1e18):
                    best[(jx, jy)] = nc
                    prev[(jx, jy)] = (ix, iy)
                    heapq.heappush(pq, (nc, jx, jy))
        if goal is None:
            return "fail"
        path = [goal]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        nodes = [(li, ix, iy) for ix, iy in path]
        # pad center to the start point
        self.emit_track(name, n, li, (pad["x"], pad["y"]), rc.to_mm(sx, sy))
        if len(nodes) > 1:
            self.emit_path(name, n, nodes)
        attach.update(nodes)
        if kind == "via":
            x, y = rc.to_mm(*goal)
            self.emit_via(name, n, x, y)
        return "ok"

    def connect_plane_net(self, name):
        n = self.nid(name)
        res = {"ok": 0, "th": 0, "stub": 0, "fail": 0, "limit": 0}
        attach = set()
        fails = []
        pads = list(self.pads.get(name, []))
        # Fine-pitch pads first; their exits are tighter
        pads.sort(key=lambda p: (p["f"].GetFPID().GetUniStringLibItemName() not in ("SV-80-7_ADI", "TE0720"), p["ref"], p["num"]))
        for p in pads:
            if len(p["on"]) == len(rc.LAYERS):  # Through-hole: connect directly to the plane
                res["th"] += 1
                continue
            st = self.to_plane(name, n, p, attach)
            res[st] += 1
            if st != "ok":
                fails.append(f"{p['ref']}.{p['num']}:{st}")
        return res, fails


def main(base, dst, report, prev_report=None):
    board = pcbnew.LoadBoard(base)
    assert len(list(board.Tracks())) == 0, "base board must not have tracks"
    r = PowerRouter(board)
    for z in ZONES:
        add_zone(board, *z)
    order = rc.signal_order(r, prev_report)
    # Reserve exits for signals and low-current power first, so power vias do not block them
    r.reserve(order + TRACE_NETS)
    out = {}
    # Order: power pins to planes -> VREF_5V -> signals -> other low-current power
    for name in PLANE_NETS:
        res, fails = r.connect_plane_net(name)
        out[name] = dict(res=res, fails=fails)
        print(name, res, fails[:40], flush=True)
    t0 = time.time()
    for k, name in enumerate(["/CELL1/VREF_5V"] + order + ["/CELL1_P3V3", "/CELL1/VREF_IN"]):
        st, L = r.route_net(name)
        out[name] = dict(res=st, length=round(L, 1))
        print(f"{k + 1} {name} {st} {L:.1f}mm {time.time() - t0:.0f}s", flush=True)
    rc.save_keep_project(dst, board)
    json.dump(out, open(report, "w"), indent=0, ensure_ascii=False)
    print("done tracks", len(list(board.Tracks())))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[5] if len(sys.argv) > 5 else None)
