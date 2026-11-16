#!/usr/bin/env python3
"""Negative test: place a side-B track 1mm from the GND_A pad of PS1001; the high-voltage rule must report an error.
Writes only to <output board>; the original board is not modified. Usage (KiCad Python): test_hv_rule.py <input board> <output board>"""
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
pad = next(p for p in b.FindFootprintByReference("PS1001").Pads() if p.GetNumber() == "2")
pos = pad.GetPosition()
t = pcbnew.PCB_TRACK(b)
off = pcbnew.FromMM(0.95 + 1.0)
t.SetStart(pcbnew.VECTOR2I(pos.x + off, pos.y))
t.SetEnd(pcbnew.VECTOR2I(pos.x + off, pos.y - pcbnew.FromMM(3)))
t.SetWidth(pcbnew.FromMM(0.15))
t.SetLayer(pcbnew.In2_Cu)
t.SetNet(b.FindNet("/GND_B_300V"))
b.Add(t)
pcbnew.SaveBoard(sys.argv[2], b)
print("pad net", pad.GetNetname())
