#! /bin/sh
set -e

# Regenerates everything needed to fab and assemble the board:
#   - ERC/DRC reports (aborts on violations, before exporting anything)
#   - Gerbers + Excellon drill into hardware/pcb/production/gerbers/,
#     zipped as production/frameprobe_gerbers.zip (JLCPCB upload)
#   - BOM (bom.csv) and pick-and-place (cpl.csv) in JLCPCB column format
#   - Netlist (production/frameprobe.net)
#   - STEP (CAD/enclosure design) and STL (slicer) in hardware/pcb/
#   - Top/back render PNGs
# STEP colors only show in real CAD apps (Fusion, FreeCAD); slicers and STL
# are always single-color.

cd "$(dirname "$0")"

KICAD_CLI="$(command -v kicad-cli || true)"
if [ -z "$KICAD_CLI" ]; then
    KICAD_CLI="/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
fi
if [ ! -x "$KICAD_CLI" ]; then
    echo "error: kicad-cli not found (install KiCad or add kicad-cli to PATH)" >&2
    exit 1
fi

cd hardware/pcb
PCB="frameprobe.kicad_pcb"
SCH="frameprobe.kicad_sch"

# Sanity checks first — abort before exporting anything if the design is broken.
"$KICAD_CLI" sch erc "$SCH" --severity-all --exit-code-violations -o production/erc.rpt
"$KICAD_CLI" pcb drc "$PCB" --schematic-parity --refill-zones --save-board --severity-all --exit-code-violations -o production/drc.rpt

# Gerbers + drill, zipped for upload
rm -rf production/gerbers
"$KICAD_CLI" pcb export gerbers "$PCB" -o production/gerbers/ \
    --layers "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" \
    --subtract-soldermask
"$KICAD_CLI" pcb export drill "$PCB" -o production/gerbers/ \
    --format excellon --excellon-units mm --generate-map --map-format gerberx2
rm -f production/frameprobe_gerbers.zip
(cd production/gerbers && zip -q ../frameprobe_gerbers.zip ./*)

# BOM + CPL (JLCPCB column names)
"$KICAD_CLI" sch export bom "$SCH" -o production/bom.csv \
    --fields "Value,Reference,Footprint,LCSC" \
    --labels "Comment,Designator,Footprint,LCSC Part #" \
    --group-by "Value,Footprint" --exclude-dnp
"$KICAD_CLI" pcb export pos "$PCB" -o production/cpl_raw.csv \
    --format csv --units mm --side front --smd-only --exclude-dnp --use-drill-file-origin
sed '1s/.*/Designator,Val,Package,Mid X,Mid Y,Rotation,Layer/' production/cpl_raw.csv > production/cpl.csv
rm -f production/cpl_raw.csv

# Netlist
"$KICAD_CLI" sch export netlist "$SCH" -o production/frameprobe.net

# 3D models + renders
# "$KICAD_CLI" pcb export step --subst-models --force -o frameprobe.step "$PCB"
"$KICAD_CLI" pcb export stl --subst-models --force -o frameprobe.stl "$PCB"
"$KICAD_CLI" pcb render --side top --width 840 --height 1264 -o render_top.png "$PCB"
"$KICAD_CLI" pcb render --side bottom --width 840 --height 1264 -o render_back.png "$PCB"
