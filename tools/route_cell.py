#!/usr/bin/env python3
"""CELL1 signal routing (the user wants to see how far Claude can route on its own, so Freerouting is not used).

Method: multi-layer A* on a 0.125mm grid.
- Routing layers: F.Cu, In2.Cu, In3.Cu, B.Cu (In1 reserved for GND, In4 for power; zones automatically clear vias passing through)
- Fine-pitch pads are first pulled out straight along the pad's long axis (stub), then handed to A*
- Each net is connected in order: search from the already-connected part to the next pad; if no path is found, record a failure instead of forcing a connection
- KiCad DRC is the authority on clearance; this script only makes a conservative estimate

Memory estimate: grid 1280×960×4 layers × 4 bytes ≈ 20MB; A* is capped at 2 million nodes per search, about 300MB;
single process, far below the machine limit.

Usage (KiCad Python): route_cell.py <base.kicad_pcb with placement only> <output board.kicad_pcb> <report json> <side_a.json> [previous report json]
"""
import heapq
import json
import os
import math
import re
import sys
import time
from array import array

import pcbnew

GRID = 0.125
X0, Y0, X1, Y1 = 20.0, 20.0, 172.0, 136.0
NX, NY = int((X1 - X0) / GRID) + 1, int((Y1 - Y0) / GRID) + 1
TRACK = 0.15
CLEAR = 0.15
VIA_D, VIA_H = 0.45, 0.2
LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.B_Cu]
LAYER_COST = [1.6, 1.0, 1.0, 1.2]
VIA_COST = 6.0
HV_KEEPOUT = 2.7
MAX_EXPAND = 2000000
FREE, BLOCK = 0, -1

mm = pcbnew.ToMM


def idx(ix, iy):
    return iy * NX + ix


def to_grid(x, y):
    return int(round((x - X0) / GRID)), int(round((y - Y0) / GRID))


def to_mm(ix, iy):
    return X0 + ix * GRID, Y0 + iy * GRID


class Grid:
    def __init__(self):
        self.maps = [array("i", [FREE]) * (NX * NY) for _ in LAYERS]

    def mark_rect(self, li, x0, y0, x1, y1, net):
        ax, ay = to_grid(x0, y0)
        bx, by = to_grid(x1, y1)
        m = self.maps[li]
        for iy in range(max(0, ay - 1), min(NY, by + 2)):
            # Mark only grid points that actually fall inside the rectangle
            y = Y0 + iy * GRID
            if y < y0 or y > y1:
                continue
            base = iy * NX
            for ix in range(max(0, ax - 1), min(NX, bx + 2)):
                x = X0 + ix * GRID
                if x < x0 or x > x1:
                    continue
                v = m[base + ix]
                m[base + ix] = net if v == FREE or v == net else BLOCK

    def mark_disk(self, li, x, y, r, net):
        cx, cy = to_grid(x, y)
        n = int(r / GRID) + 1
        m = self.maps[li]
        for dy in range(-n, n + 1):
            iy = cy + dy
            if not 0 <= iy < NY:
                continue
            for dx in range(-n, n + 1):
                ix = cx + dx
                if 0 <= ix < NX and (dx * dx + dy * dy) * GRID * GRID <= r * r:
                    k = iy * NX + ix
                    v = m[k]
                    m[k] = net if v == FREE or v == net else BLOCK

    def mark_seg(self, li, a, b, r, net):
        ax, ay = a
        bx, by = b
        n = max(1, int(math.hypot(bx - ax, by - ay) / GRID))
        for i in range(n + 1):
            t = i / n
            self.mark_disk(li, ax + (bx - ax) * t, ay + (by - ay) * t, r, net)


def via_ok(g, ix, iy, net):
    # The map means "track center may not enter" and already includes clearance + half track width; the via radius adds 0.15mm ≈ 2 cells
    for m in g.maps:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx * dx + dy * dy > 5:
                    continue
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < NX and 0 <= jy < NY):
                    return False
                v = m[jy * NX + jx]
                if v != FREE and v != net:
                    return False
    return True


def astar(g, starts, goals, net):
    """starts: {(layer, ix, iy)}; goals: {(layer, ix, iy)}. Returns a list of nodes or None."""
    if not starts or not goals:
        return None
    gxy = [(l, x, y) for l, x, y in goals]
    gset = set(goals)

    def h(ix, iy):
        return min(max(abs(ix - x), abs(iy - y)) * 0.0 + math.hypot(ix - x, iy - y) for _, x, y in gxy[:8]) * GRID

    pq = []
    best = {}
    prev = {}
    for s in starts:
        best[s] = 0.0
        heapq.heappush(pq, (h(s[1], s[2]), 0.0, s))
    n = 0
    moves = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
    while pq:
        f, c, node = heapq.heappop(pq)
        if c > best.get(node, 1e18):
            continue
        if node in gset:
            path = [node]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        n += 1
        if n > MAX_EXPAND:
            return None
        li, ix, iy = node
        m = g.maps[li]
        lc = LAYER_COST[li] * GRID
        for dx, dy, w in moves:
            jx, jy = ix + dx, iy + dy
            if not (0 <= jx < NX and 0 <= jy < NY):
                continue
            v = m[jy * NX + jx]
            if v != FREE and v != net:
                continue
            if dx and dy:  # Diagonal moves may not cut corners
                a = m[iy * NX + jx]
                b = m[jy * NX + ix]
                if (a != FREE and a != net) or (b != FREE and b != net):
                    continue
            nn = (li, jx, jy)
            nc = c + lc * w
            if nc < best.get(nn, 1e18):
                best[nn] = nc
                prev[nn] = node
                heapq.heappush(pq, (nc + h(jx, jy), nc, nn))
        if via_ok(g, ix, iy, net):
            for lj in range(len(LAYERS)):
                if lj == li:
                    continue
                nn = (lj, ix, iy)
                nc = c + VIA_COST
                if nc < best.get(nn, 1e18):
                    best[nn] = nc
                    prev[nn] = node
                    heapq.heappush(pq, (nc + h(ix, iy), nc, nn))
    return None


class Router:
    def __init__(self, board):
        self.board = board
        self.g = Grid()
        self.net_id = {}
        self.pads = {}
        self.items = []
        self._load()

    def nid(self, name):
        if name not in self.net_id:
            self.net_id[name] = len(self.net_id) + 1
        return self.net_id[name]

    def _load(self):
        margin = CLEAR + TRACK / 2
        side_a = set(json.load(open(sys.argv[4]))) if len(sys.argv) > 4 else set()
        for f in self.board.GetFootprints():
            ref = f.GetReference()
            if not re.match(r"[A-Z]+1\d{3}$", ref):
                continue
            for p in f.Pads():
                pos = p.GetPosition()
                x, y = mm(pos.x), mm(pos.y)
                bb = p.GetBoundingBox()
                x0, y0, x1, y1 = mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())
                netname = p.GetNetname()
                real = netname and not netname.startswith("unconnected-")
                n = self.nid(netname) if real else BLOCK
                on = [i for i, l in enumerate(LAYERS) if p.IsOnLayer(l)]
                if p.HasHole():
                    on = list(range(len(LAYERS)))
                hv = netname in side_a
                extra = HV_KEEPOUT if hv else margin
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    extra = max(extra, 0.25 + TRACK / 2 + 0.03)  # KiCad hole clearance 0.25mm
                for li in on:
                    self.g.mark_rect(li, x0 - extra, y0 - extra, x1 + extra, y1 + extra, BLOCK if hv else n)
                if real:
                    self.pads.setdefault(netname, []).append(dict(ref=ref, num=p.GetNumber(), x=x, y=y, x0=x0, y0=y0, x1=x1, y1=y1, on=on, f=f))
        # Board edge
        m = self.g.maps
        for li in range(len(LAYERS)):
            self.g.mark_rect(li, X0 - 1, Y0 - 1, X1 + 1, Y0 + 0.3, BLOCK)
            self.g.mark_rect(li, X0 - 1, Y0 - 1, X0 + 0.3, Y1 + 1, BLOCK)

    def stub(self, pad):
        """Elongated pad: pull outward along the long axis and return (end x, y); square pads are not pulled."""
        w, h = pad["x1"] - pad["x0"], pad["y1"] - pad["y0"]
        if max(w, h) < 1.2 * min(w, h) or len(pad["on"]) != 1 or max(w, h) > 3:
            return None
        f = pad["f"]
        cx, cy = self.center_of(pad)
        L = max(w, h) / 2 + 0.75
        if h > w:
            s = 1 if pad["y"] > cy else -1
            return pad["x"], pad["y"] + s * L
        s = 1 if pad["x"] > cx else -1
        return pad["x"] + s * L, pad["y"]

    def center_of(self, pad):
        f = pad["f"]
        pos = f.GetPosition()
        cx, cy = mm(pos.x), mm(pos.y)
        if f.GetFPID().GetUniStringLibItemName() == "TE0720":
            con = pad["num"].split(".")[0]
            ox, oy = {"JB1": (-16, 0), "JB2": (16, 0), "JB3": (0, -21)}.get(con, (0, 0))
            return cx + ox, cy + oy
        return cx, cy

    def reserve(self, names):
        """Reserve straight exits for all pads first, so tracks routed early do not block the exits of later pads."""
        for name in names:
            n = self.nid(name)
            for p in self.pads.get(name, []):
                e = self.stub(p)
                if e:
                    self.g.mark_seg(p["on"][0], (p["x"], p["y"]), e, TRACK + CLEAR + 0.02, n)

    def route_net(self, name):
        pads = self.pads.get(name, [])
        n = self.nid(name)
        if len(pads) < 2:
            return "skip", 0
        # Pull out all stubs first; stub end points are the A* start and goal points
        ends = []
        made = []
        for p in pads:
            e = self.stub(p)
            li = p["on"][0]
            if e:
                gx, gy = to_grid(*e)
                v = self.g.maps[li][gy * NX + gx] if 0 <= gx < NX and 0 <= gy < NY else BLOCK
                # Give up if the stub path is occupied
                ok = v == FREE or v == n
                if ok:
                    for t in range(11):
                        tx = p["x"] + (e[0] - p["x"]) * t / 10
                        ty = p["y"] + (e[1] - p["y"]) * t / 10
                        ix, iy = to_grid(tx, ty)
                        vv = self.g.maps[li][iy * NX + ix]
                        if vv != FREE and vv != n:
                            ok = False
                            break
                if not ok:
                    return f"stub:{p['ref']}.{p['num']}", 0
                made.append((li, (p["x"], p["y"]), e))
                ends.append([(li, gx, gy)])
            else:
                gx, gy = to_grid(p["x"], p["y"])
                ends.append([(l, gx, gy) for l in p["on"]])
        for li, a, b in made:
            self.emit_track(name, n, li, a, b)
        tree = set(ends[0])
        rest = ends[1:]
        lengths = 0.0
        while rest:
            # Connect the nearest pad first
            def dist(group):
                return min(math.hypot(g[1] - t[1], g[2] - t[2]) for g in group for t in list(tree)[:40])

            rest.sort(key=dist)
            target = rest.pop(0)
            path = astar(self.g, tree, set(target), n)
            if path is None:
                return "fail", lengths
            lengths += self.emit_path(name, n, path)
            tree |= set(path)
        # For square pads the stub end point is the pad center; off-grid pads get a short extra segment
        for p in pads:
            if not self.stub(p):
                gx, gy = to_grid(p["x"], p["y"])
                gxm, gym = to_mm(gx, gy)
                if abs(gxm - p["x"]) > 1e-3 or abs(gym - p["y"]) > 1e-3:
                    self.emit_track(name, n, p["on"][0], (p["x"], p["y"]), (gxm, gym))
        return "ok", lengths

    def emit_track(self, name, n, li, a, b):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        t.SetWidth(pcbnew.FromMM(TRACK))
        t.SetLayer(LAYERS[li])
        t.SetNet(self.board.FindNet(name))
        self.board.Add(t)
        self.g.mark_seg(li, a, b, TRACK + CLEAR + 0.02, n)

    def emit_via(self, name, n, x, y):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(pcbnew.FromMM(VIA_H))
        v.SetWidth(pcbnew.FromMM(VIA_D))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.board.FindNet(name))
        self.board.Add(v)
        for li in range(len(LAYERS)):
            self.g.mark_disk(li, x, y, VIA_D / 2 + CLEAR + TRACK / 2 + 0.02, n)

    def emit_path(self, name, n, path):
        length = 0.0
        i = 0
        while i < len(path) - 1:
            a = path[i]
            if a[0] != path[i + 1][0]:
                x, y = to_mm(a[1], a[2])
                self.emit_via(name, n, x, y)
                i += 1
                continue
            # Merge segments on the same layer in the same direction
            j = i + 1
            d = (path[j][1] - a[1], path[j][2] - a[2])
            while j + 1 < len(path) and path[j + 1][0] == a[0] and (path[j + 1][1] - path[j][1], path[j + 1][2] - path[j][2]) == d:
                j += 1
            pa = to_mm(a[1], a[2])
            pb = to_mm(path[j][1], path[j][2])
            self.emit_track(name, n, a[0], pa, pb)
            length += math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            i = j
        return length


def save_keep_project(path, board):
    """Save the board but keep the destination's .kicad_pro.

    When the board was loaded from a location without a .kicad_pro, SaveBoard overwrites the destination's project file with defaults,
    and the net classes and the A/B high-voltage rules silently disappear (reproduced; see "Pitfalls we hit" in README.md).
    """
    pro = os.path.splitext(path)[0] + ".kicad_pro"
    keep = open(pro, "rb").read() if os.path.exists(pro) else None
    pcbnew.SaveBoard(path, board)
    if keep is not None:
        open(pro, "wb").write(keep)


def signal_order(r, prev_report=None):
    # Order: DB first (many nets, fixed paths), then shared control
    names = sorted(r.pads)
    skip = re.compile(r"(GND|P52V|N52V|P5V|P3V3|VREF_5V|VREF_IN|P9V|P24V|VIN_5|PHY_|/GND_A)")
    data = [n for n in names if re.search(r"/D\d_DB\d+$", n)]
    other = [n for n in names if n not in data and not skip.search(n) and len(r.pads[n]) >= 2]
    order = data + other
    # Nets that failed in the previous run are routed first
    if prev_report:
        prev = json.load(open(prev_report))
        hard = [n for n in order if n in prev and prev[n][0] != "ok"]
        order = hard + [n for n in order if n not in hard]
        print("priority", hard, flush=True)
    return order


def main(base, path, report):
    # Always start from a board with placement only and no tracks; never rip up and reroute on the same board
    board = pcbnew.LoadBoard(base)
    assert len(list(board.Tracks())) == 0, "base board must not have tracks"
    r = Router(board)
    order = signal_order(r, sys.argv[5] if len(sys.argv) > 5 else None)
    r.reserve(order)
    t0 = time.time()
    res = {}
    for k, n in enumerate(order):
        st, L = r.route_net(n)
        res[n] = (st, round(L, 1))
        print(f"{k + 1}/{len(order)} {n} {st} {L:.1f}mm {time.time() - t0:.0f}s", flush=True)
    save_keep_project(path, board)
    c = {}
    for st, _ in res.values():
        key = st.split(":")[0]
        c[key] = c.get(key, 0) + 1
    print("summary", c, "tracks", len(list(board.Tracks())))
    json.dump(res, open(report, "w"), indent=0, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
