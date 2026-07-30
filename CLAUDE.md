# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an end-to-end display latency measurement tool. It measures the time from a mouse click to visible screen change using custom hardware (photodiode + RP2040 microcontroller). The system has three layers: firmware, host software, and hardware.

## Architecture

**Measurement flow:** The RP2040 sends a USB HID mouse click → color-switcher app toggles screen black/white → photodiode detects the change → ADC samples are sent over serial → `main.py` logs to CSV → `analyze.py` calculates latency.

### Firmware (`arduino/arduino.ino`)
- Board-agnostic within arduino-pico: it needs an ADC input on `A1` (GP27), USB HID, and a NeoPixel status LED. Default FQBN is `rp2040:rp2040:waveshare_rp2040_zero` (the PCB's module); the QT Py perfboard build is `FQBN=rp2040:rp2040:adafruit_qtpy ./flash_rp2040.sh`. `NEOPIXEL_POWER` (a switched NeoPixel rail, QT Py only) is `#ifdef`-guarded, but `PIN_NEOPIXEL` is not — variants without a NeoPixel (`generic`, `rpipico`) don't define it and won't compile as-is
- `analogReadResolution(14)` on pin A1 reads the photodiode via a transimpedance amplifier (fab board: VBPW34S + TLV9061; perfboard: BPW34 + TLC271IP). The RP2040 SAR is 12-bit, so the 14-bit range is upscaled — the extra bits add range, not resolution
- Dark baseline differs per sensor: ~565 ADC counts on the fab PCB, ~950 on the perfboard build — harmless, since `analyze.py`'s midpoint detection measures both reference levels from each row's own samples
- Collects 12,000 ADC samples per test run with 20µs settling delay between reads (~288ms window), sends as CSV-prefixed serial line
- Uses `Mouse.press()`/`Mouse.release()` instead of blocking `Mouse.click()` — press is non-blocking (~15µs), sampling starts immediately
- 20µs ADC settling delay is critical: without it, the sample-and-hold capacitor doesn't fully discharge, compressing dynamic range (black reads ~1238 instead of ~950)
- `usb_hid_poll_interval = 1` overrides arduino-pico's weak default of 10 — a 10ms HID bInterval would add a uniform 0-10ms host-poll delay to every measurement; 1ms matches a 1000Hz gaming mouse
- Inter-click delay carries ±10ms of random jitter, generated in µs (whole-ms offsets modulo a 2ms frame period would only hit two scanout phases). `randomSeed()` is seeded from ADC noise, otherwise every session would repeat the same jitter sequence
- `Serial.flush()` after each CSV line ensures USB bus is idle before next measurement (HID and CDC share the bus)
- Serial protocol: lines starting with `CSV` are data rows, `DONE` ends a session, all other output is debug/status

### Host Control Software (`main.py`)
- Async serial terminal using `prompt_toolkit` for interactive control
- Auto-detects the device by USB VID/PID at 115200 baud: exact matches first (`KNOWN_DEVICES` — 0x239A/0x80F7 for the QT Py, plus the 0x2E8A PID set arduino-pico derives from 0x0003 depending on which USB interfaces are enabled), then any port with a known vendor ID (Adafruit 0x239A, Raspberry Pi 0x2E8A) for firmware builds with an unlisted PID; falls back to `/dev/cu.usbmodem*`/`/dev/ttyACM*` name matching, then to any port whose driver description says "USB Serial" (Windows names CDC devices `USB Serial Device (COMx)`). Pass a port as first CLI arg to override (`uv run main.py /dev/ttyACM1`, `uv run main.py COM5`). Ports are re-scanned on every connect, so Linux re-enumeration (ttyACM0 → ttyACM1) is handled automatically.
- Runs on macOS, Linux and Windows. Windows specifics: COM ports are opened exclusively, so a dead handle is closed before every reconnect (`discard_serial`); `csv.field_size_limit` is capped at 2³¹−1 because a C `long` is 32-bit there; session CSVs resolve against the script directory, not the cwd.
- Commands: `start`, `stop`, `debug`/`d`, `interval <n>`/`i <n>`, `clicks <n>`/`c <n>`, `connect`, `disconnect`
- CSV output goes to `output/` with timestamp-based filenames

### Color Switcher (`color-switcher-vulkan/`)
- C++ Vulkan app for low-latency rendering. Toggles the screen black/white on left mouse press (GLFW callback), Esc quits.
- Picks the present mode in order `IMMEDIATE` (no vsync — tearing is irrelevant to a photodiode) → `MAILBOX` → `FIFO_RELAXED` → `FIFO`, and prints which one it got.
- CMake links Vulkan + glfw3, `-O3 -march=native`; macOS adds the MoltenVK path (`VK_USE_PLATFORM_MACOS_MVK`, Metal/Cocoa/QuartzCore). The binary is `build/bin/color-switcher`.

### Data Processing
- `analyze.py`: Latency analyzer with automatic per-row normalized-crossing detection. Per CSV row: takes the median of the last 200 pre-click samples as baseline and the median of the last 500 samples as the settled level (medians reject QD-OLED flicker dips), measures noise as the peak-to-peak of the last 1000 pre-click samples, skips rows whose swing doesn't clear 2× that noise (missed click / slipped sensor; skip reasons are counted), and timestamps normalized crossings of the swing: t50 (primary latency — 5-sample sustained crossing, timestamped at the run's first sample) plus supplementary t10 (onset; per-row unavailable when 10% of the swing is within the noise, e.g. QD-OLED white-baseline flicker) and t90 (first crossing, no sustain since settled flicker recrosses it). All ranking stats use t50 only — self-scaling across hardware generations (fab PCB ~2800-unit swing, perfboard ~390) with no tuning, and per-row, so results don't depend on what's pooled together. `-t <delta>` switches to the legacy m2p-latency fixed delta-from-baseline scan (mean baseline, single-sample crossing), kept bit-identical for reproducing published numbers (e.g. `test_run1/` was published with `-t 100`; note t50 reads ~0.5ms slower there, since it crosses at ~195 counts instead of 100). Reports the detection mode with min/median signal-to-noise separation, mean (± 95% margin of error), median, p5, p95, p95−p5 spread, min, max, median onset (t10) and sensor+panel response (t10→t90), plus an ASCII histogram (0.5ms bins). Arguments can be CSV files or folders: a folder is scanned recursively for `.csv` files and pooled into one result, with the margin of error design-effect adjusted across files (each file = one session); single files get the naive 1.96·sd/√n margin. Terminal output only, no plotting (the histogram bar falls back from `█` to `#` when stdout can't encode it, e.g. redirected output on Windows). `--json` prints the stats as a JSON array instead; the stats logic is importable via `collect_stats()`.
- `analyze_all.py`: chart-JSON wrapper — analyzes every direct subfolder of a given folder (`uv run analyze_all.py test_run/output`) via `collect_stats()` and prints chart-ready JSON with two top-level keys: `main` (labels = subfolder names, datasets = median/margin of error/p5/p95, sorted fastest median first) and `histogram` (0.5ms bins shared across all cases; labels = bin lower edges in ms, one dataset of counts per case).
- `analyze.md`: plain-language explanation of every field in the `analyze.py` report (what mean ± CI, p5/p95, spread and the histogram actually mean). Keep it in sync when the report changes.
- `test_run1/`: reference captures plus `test_setup.md` (machine, monitor, package versions) and `test_matrix.md` (X11/Wayland × `PROTON_DXVK_LOWLATENCY` × VRR — 8 cases plus 4 special ones). Perfboard-era data; auto midpoint detection handles it, `-t 100` reproduces the originally published numbers.

### Hardware (`hardware/`)
- `pcb/`: KiCad 10 project for the fab board — 30 × 48 mm, TLV9061 TIA + VBPW34S photodiode on the front (JLCPCB-assembled), solder-on Waveshare RP2040-Zero module on the back so the sensor face stays ~1 mm flat against the screen. Custom symbols in `click2photon.kicad_sym`, footprints in `click2photon.pretty/`, 3D models in `3dmodels/`, renders `render_top.png` / `render_back.png`, `click2photon.stl`. TIA output lands on GP27 = A1, so `analogRead(A1)` is unchanged from the perfboard build.
- `./export_fab.sh` regenerates everything fab-related into `hardware/pcb/production/` (gerber zip, BOM, CPL, netlist, ERC/DRC reports) plus the STEP/STL and renders, aborting on any ERC/DRC violation. It needs `kicad-cli` (falls back to the macOS app bundle path). `production/` is gitignored — the fab outputs are generated, not checked in.
- `enclosure/`: 3D-printable case, lid and strap buckle
- `images/`: photos of the assembled board and enclosure (`board.jpg`, `enclosure_front.jpg`, `enclosure_back.jpg`, `enclosure_render.jpg`)

## Commands

### Python environment
Managed with [uv](https://docs.astral.sh/uv/) (`pyproject.toml` + `uv.lock`):
```
uv sync
```

### Run host software
```
uv run main.py
```

### Process latency data
```
uv run analyze.py <csv_file_or_folder> [<csv_file_or_folder> ...] [-t <threshold>]
```

### Chart JSON for a folder of test cases
```
uv run analyze_all.py <folder_of_case_subfolders>
```

### Regenerate PCB fab outputs
```
./export_fab.sh                   # needs kicad-cli; writes hardware/pcb/production/ (gitignored)
```

### Firmware compile and flash
```
./flash_rp2040.sh                                     # RP2040-Zero (default FQBN), auto-detects the port
FQBN=rp2040:rp2040:adafruit_qtpy ./flash_rp2040.sh    # other board
./flash_rp2040.sh /dev/ttyACM1                        # or pass the port explicitly
# Installs the rp2040 core and the Adafruit NeoPixel library on first run.
# Builds into ./build/ (gitignored). arduino-cli reboots the board into BOOTSEL
# by opening the port at 1200 baud, which only works if the firmware already on
# the board implements the touch reset -- a factory board (MicroPython, Pico SDK
# demo) does not. When that fails, or when no port shows up at all, the script
# prompts for the BOOT button and copies the .uf2 to the RPI-RP2 drive itself
# (BOOTSEL_TIMEOUT=60 seconds by default). A board already in BOOTSEL is detected
# up front and flashed directly, without touching the serial port.
# or manually (the rp2040:rp2040 core comes from a third-party index, not Arduino's default):
arduino-cli core install rp2040:rp2040 --additional-urls https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
arduino-cli lib install "Adafruit NeoPixel"
arduino-cli compile --fqbn rp2040:rp2040:waveshare_rp2040_zero arduino
arduino-cli upload -p /dev/cu.usbmodem101 --fqbn rp2040:rp2040:waveshare_rp2040_zero arduino
```

### Vulkan color switcher
```
# Dependencies (macOS): brew install vulkan-headers vulkan-loader molten-vk glfw cmake
./build_vulkan.sh
./run_vulkan.sh
```

## CSV Format

```
clickTime,timeTaken,sampleCount,preClickSamples,samples
20,720500,12000,2000,1280;1284;1284;...
```

- `clickTime`: microseconds for Mouse.press() call (~15-20µs)
- `timeTaken`: total ADC sampling duration in microseconds (pre-click + post-click)
- `sampleCount`: total number of ADC samples
- `preClickSamples`: number of samples collected before the mouse click (pre-click baseline)
- `samples`: semicolon-separated 14-bit ADC values (0-16383)
