#!/usr/bin/env python3
"""Place the hv_awg parts using KiCad's built-in Python (pcbnew).

Layout (board coordinates in mm, board (20,20)–(320,310), 300×290 total):
- 4 cells in a 2×2 arrangement: CELL1 top left, CELL2 top right, CELL3 bottom left, CELL4 bottom right
- CELL2 = CELL1 shifted by 150; CELL3, CELL4 = CELL2, CELL1 rotated 180° about the board center (170,165)
  so all SMAs are on the top and bottom board edges, the modules are near the center, and clock tracks are short
- The central band (y 132–198) holds the power supplies and root circuitry

The positions for one cell are defined once, in the CELL and DAC tables.
DAC table coordinates are screen coordinates relative to the AD8460 center, with U1 rotated 270°: OUT faces up (board edge),
DB at the bottom right and SPI at the bottom left, both facing the module.

Usage (KiCad Python): place_board.py <board.kicad_pcb> <cell list, e.g. 1 or 1,2,3,4>
"""
import sys

import pcbnew

BOARD = (20.0, 20.0, 320.0, 310.0)
CENTER = (170.0, 165.0)
CELL_DX = 150.0

# Parts within a cell: {base reference: (x, y, rot)}, in CELL1 board coordinates
MODULE = (95.0, 100.0)
CELL = {
    "U1": (MODULE[0], MODULE[1], 0),  # TE0720
    # 5V: REC15E, input pins toward the central band (side A), output toward the module
    "PS1": (46.0, 124.0, 90),
    "L1": (46.0, 131.5, 0),
    "C1": (53.0, 131.5, 0),
    "C2": (59.0, 131.5, 0),
    "C3": (26.0, 120.0, 90),  # Y capacitor, across the A/B isolation gap
    "C4": (64.0, 106.0, 0),
    "C5": (62.0, 114.0, 0),
    # 3.3VIN: TPS75233 to the left of JB1.14/16
    "U2": (67.0, 90.0, 0),
    "C6": (60.5, 87.5, 90),
    "C7": (60.5, 92.5, 90),
    "C8": (67.0, 98.5, 0),
    # Module decoupling: under the module, between the two connector rows (Integration Guide: low-profile parts allowed)
    "C13": (90.0, 92.0, 0),
    "C14": (90.0, 95.0, 0),
    "C15": (90.0, 98.0, 0),
    "C16": (100.0, 92.0, 0),
    "C17": (100.0, 95.0, 0),
    # VREF: 9V -> TPS22810 -> REF5050
    "U3": (127.0, 80.0, 0),
    "R2": (122.0, 80.0, 90),
    "R3": (127.0, 85.0, 0),
    "C9": (122.0, 85.0, 90),
    "C10": (132.0, 85.0, 90),
    "U4": (140.0, 80.0, 0),
    "C11": (137.0, 87.0, 0),
    "C12": (143.0, 87.0, 0),
    # Debug and boot configuration
    "J1": (122.0, 100.0, 0),
    "J2": (130.0, 100.0, 0),
    "J3": (138.0, 100.0, 0),
    "R1": (122.0, 118.0, 0),
    "TP1": (130.0, 118.0, 0),
}

DAC_CENTERS = {1: (38.75, 44.0), 2: (76.25, 44.0), 3: (113.75, 44.0), 4: (151.25, 44.0)}
# Relative to the AD8460 center; see the module docstring
DAC = {
    "U1": (0, 0, 270),
    "J1": (-4.5, -20.9, 90),  # SMA: pad 1 aligned with the OUT pin, opening toward the board edge
    # P52V (top pins on screen, x -2.25..-1.25)
    "C1": (-1.5, -9.8, 90),
    "C2": (1.0, -14.4, 0),
    "C3": (6.0, -14.4, 0),
    "C4": (11.0, -14.4, 0),
    "C5": (16.0, -14.4, 0),
    # Other top pins
    "C16": (-3.6, -10.5, 90),  # COMP_H–OUT
    "R3": (2.0, -9.8, 90),  # IOUTN
    "R2": (3.6, -9.8, 90),  # IOUTP
    "R7": (5.6, -9.8, 90),  # SDN_RESET pull-down
    # N52V (left pins on screen, y -1.75..0.25)
    "C6": (-9.6, -0.75, 0),
    "C7": (-15.0, -6.0, 0),
    "C8": (-15.0, -2.5, 0),
    "C9": (-15.0, 1.0, 0),
    "C10": (-15.0, 4.5, 0),
    # Other left pins
    "C17": (-9.7, -3.6, 180),  # COMP_L–OUT
    "C15": (-11.0, 1.75, 180),  # COMP_T
    "R5": (-9.5, 7.5, 0),  # CS_N pull-up
    "R6": (-9.5, 9.2, 0),  # RESET_N pull-up
    # Bottom: SYNC, 5V, VREF; DB0–7 left clear for routing
    "R4": (-6.6, 9.8, 90),
    "C11": (-4.4, 9.8, 270),
    "C12": (-2.9, 9.8, 270),
    # Right: AVDD, REFIO, FS_ADJ, TMP; DB8–13 left clear for routing
    "C13": (9.8, -1.9, 0),
    "C14": (13.4, -3.4, 0),
    "R1": (9.8, -4.9, 0),
    "TP1": (16.0, -1.0, 0),
    # SDN_IO: tri-state buffer and Schmitt trigger
    "U2": (11.5, -9.0, 0),
    "U3": (17.5, -9.0, 0),
    "C18": (11.5, -11.7, 0),
    "C19": (17.5, -11.7, 0),
    "C20": (7.3, -9.0, 90),
    "R8": (13.8, -5.6, 0),
    "R9": (18.2, -5.6, 0),
}


def cell_xy(k, x, y):
    """Map CELL1 coordinates to cell k."""
    if k in (2, 3):
        x += CELL_DX
    if k in (3, 4):
        x, y = 2 * CENTER[0] - x, 2 * CENTER[1] - y
    return x, y


def cell_rot(k, rot):
    return (rot + 180) % 360 if k in (3, 4) else rot


def offset_ref(base, off):
    pre = base.rstrip("0123456789")
    return f"{pre}{int(base[len(pre):]) + off}"


def place(board, ref, x, y, rot):
    f = board.FindFootprintByReference(ref)
    assert f is not None, ref
    f.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    f.SetOrientationDegrees(rot)


def outline(board):
    # Draw only if there is no outline yet
    if any(d.GetLayer() == pcbnew.Edge_Cuts for d in board.GetDrawings()):
        return
    x0, y0, x1, y1 = BOARD
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for a, b in zip(pts, pts[1:]):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
        s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)


def main(path, cells):
    board = pcbnew.LoadBoard(path)
    outline(board)
    n = 0
    for k in cells:
        for base, (x, y, rot) in CELL.items():
            px, py = cell_xy(k, x, y)
            place(board, offset_ref(base, k * 1000), px, py, cell_rot(k, rot))
            n += 1
        for j, (dx, dy) in DAC_CENTERS.items():
            for base, (sx, sy, rot) in DAC.items():
                px, py = cell_xy(k, dx + sx, dy + sy)
                place(board, offset_ref(base, k * 1000 + j * 100), px, py, cell_rot(k, rot))
                n += 1
    pcbnew.SaveBoard(path, board)
    print("placed", n)


if __name__ == "__main__":
    main(sys.argv[1], [int(c) for c in sys.argv[2].split(",")])
