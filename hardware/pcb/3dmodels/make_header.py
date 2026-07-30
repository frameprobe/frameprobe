from pathlib import Path

import cadquery as cq

PITCH = 2.54
N = 9
PIN_SQ = 0.64
PLASTIC_H = 2.5
BOARD_T = 1.6      # main PCB thickness
CLIP_STUB = 1.5    # clipped leg protrusion past front surface
MODULE_TOP = 3.5   # back surface -> module top face
TOP_STUB = 2.0     # pin protrusion above module top

# Model frame matches KiCad footprint convention: pin1 at (0,0), row along -y,
# z=0 at the mounting (back) surface of the main board, +z toward the module.
z_lo = -(BOARD_T + CLIP_STUB)
z_hi = MODULE_TOP + TOP_STUB

row_len = (N - 1) * PITCH

plastic = (cq.Workplane("XY")
           .center(0, -row_len / 2)
           .rect(PITCH, row_len + PITCH)
           .extrude(PLASTIC_H))

pins = None
for k in range(N):
    p = (cq.Workplane("XY")
         .workplane(offset=z_lo)
         .center(0, -PITCH * k)
         .rect(PIN_SQ, PIN_SQ)
         .extrude(z_hi - z_lo))
    pins = p if pins is None else pins.union(p)

asm = cq.Assembly()
asm.add(plastic, name="insulator", color=cq.Color(0.1, 0.1, 0.1))
asm.add(pins, name="pins", color=cq.Color(0.83, 0.69, 0.33))
asm.save(str(Path(__file__).parent / "PinHeader_1x09_clipped.step"))
print("written")
