# Licensing

Copyright (C) 2026 Marco Nett.

| Path | Licence |
|---|---|
| `hardware/` — PCB source, enclosure | CERN-OHL-S v2, strongly reciprocal ([`hardware/LICENSE`](hardware/LICENSE)) |
| `arduino/`, `color-switcher-vulkan/`, `main.py`, `analyze*.py`, `*.sh` | GPL-3.0-or-later ([`LICENSE`](LICENSE)) |

## Name and logo

**All rights to the frameprobe name and the rocket logo are reserved.**
Neither licence grants trademark or design rights. This covers the logo
wherever it appears: the PCB silkscreen and gerbers, the enclosure STLs, and
the renders and photos. Remove both before fabricating a modified board or
enclosure, and use your own branding. CERN-OHL-S counts trademark notices as
*Notices* (§1.10) and requires they be retained (§3.3), so this reservation
carries into derivatives.

## Third-party material

Not my work, not covered by the licences above, and under their authors' own
terms. Both are cosmetic, 3D preview and STEP/STL export only, not the
electrical design or the fab outputs:

- `hardware/pcb/3dmodels/RP2040-Zero.step`: Waveshare RP2040-Zero model, STEP
  header credits `xiaojisheng`
- `hardware/pcb/3dmodels/LED_VBPW34S_VIS.step`: Vishay

The design also uses KiCad's standard footprint libraries, whose CC-BY-SA-4.0
licence has an exception allowing this without the design becoming a derivative.
Build dependencies (arduino-pico, Adafruit NeoPixel, GLFW, pyserial,
prompt_toolkit) are fetched, not redistributed here.