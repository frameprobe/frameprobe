# Test setup

## Hardware

- Mainboard: B450 GAMING PRO CARBON AC
- CPU: AMD Ryzen 7 5800X3D (16) @ 4.55 GHz
- GPU: NVIDIA GeForce RTX 4070 SUPER
- RAM: 2x8GB DDR4, 3200 MHz
- Monitor: MSI MAG 272QP QD-OLED X50 (500 Hz)
- Only one screen was connected to the system during the test

## Software

```sh
{
    echo "date: $(date -I)"
    echo "kernel: $(uname -r)"
    pacman -Q kwin
    pacman -Q xorg-server
    pacman -Q nvidia-utils
    pacman -Q proton-cachyos
    scxctl get
  } | tee versions.txt
```

Output:

```
date: 2026-07-12
kernel: 7.1.3-2-cachyos
kwin 6.7.2-1.1
xorg-server 21.1.24-1.1
nvidia-utils 610.43.03-1
proton-cachyos-native 1:11.0.20260602-3
no scx scheduler running
```

The test was done based on commit `7bc3f05` of frameprobe.

## System Settings

- 500 Hz
- Flip mode:
  - X11: On (via `nvidia-settings`)
  - Wayland: confirmed to be on (see below how)
- If VRR was tested:
  - X11: Enabled via `nvidia-settings` (changing this requires a reboot)
  - Wayland: Enabled via KDE Settings Menu (no reboot needed)
- `showcompositing` was off on Wayland (see [here](https://www.reddit.com/r/linux_gaming/comments/1u1z4qf/kde_kwin_patches_aiming_to_optimize_gaming/oqvlwdb/))


Flip mode (direct scanout) vs Blit mode (compositing) on Wayland: There is setting on Wayland, it decides itself if it composits a frame or uses direct scanout.\
To make sure the game is running in flip mode: Open "Kwin Debug Console" (it's a GUI tool) and in the "Effects" tab, enable `showcompositing`. Then make sure the game is fully focused and the only thing on screen in fullscreen mode. If there's no red border visible around the edged of the game, it's on Flip mode.

### dxvk

In all cases, the following is set in `dxvk.conf`:

```conf
d3d11.cachedDynamicResources = "c"
```

Depending on the test, an optimal `dxvk.conf` was setup:
- If VRR was off, `dxgi.maxFrameRate` was capped to 500 fps (the screens refresh rate)
- If VRR was on and `PROTON_DXVK_LOWLATENCY` was off, `dxgi.maxFrameRate` was capped to 497 fps (slightly below screen refresh rate)
- If VRR was on and `PROTON_DXVK_LOWLATENCY` was on, the following was used to utilize the low latency VRR frame pacing

```conf
# see https://github.com/netborg-afps/dxvk-low-latency
dxgi.maxFrameRate = 480
dxvk.lowLatencyOffset = 70
dxvk.framePace = "low-latency-vrr-500"
dxvk.lowLatencyAllowCpuFramesOverlap = False
```

## Game Settings

Test was done in Diabotical.

Settings:

- Everything Video Setting as low as possible
- 100% Render resolution
- Native resolution (2560×1440)
- Vsync off

## Methodology

- Close unnecessary Software
- Launch game
- Start a wipeout match, Map: wo_wellspring
- Move to a specific spot, put mouse on specific landmark
- Run the test case (100 clicks, runs for about 2 minutes)
- Once the test is done, start the next test case iteration

- Ingame conditions: No bots, no other players, no movement, no round restarts. It is basically just a static scene that will stay like this indefinitely.
- System conditions: During the test run, nothing else should be running and no significant other processes run on the system.

To start the test via frameprobe:

```sh
uv run main.py
clicks 100
start
```

## Special test case: PROTON_ENABLE_WAYLAND

The setting "Enable wine-wayland" in Heroic Launcher corresponds to `PROTON_ENABLE_WAYLAND`. If not otherwise noted, all tests were done with `PROTON_ENABLE_WAYLAND=1` (native Wayland, no use of XWayland)

- `PROTON_ENABLE_WAYLAND=1` implies native Wayland
- `PROTON_ENABLE_WAYLAND=0` implies XWayland

## Setup notes

```sh
cd /home/hst/Games/Heroic/Diabotical/
cp diabotical.exe-TESTLATENCY diabotical.exe
```

In diabotical:
- `/bind mouse_left testlatency`
- Setup hud with accent box

```sh
cp diabotical.exe-ORIG diabotical.exe
```

Ingame: `/bind mouse_left attack`

## Ideas

Future test run ideas:

1. Testing different kernel schedulers:

```sh
sudo scxctl start --sched cosmos --mode gaming
sudo scxctl start --sched lavd --mode gaming
sudo scxctl stop
```

2. Compare against: https://themaister.net/blog/2026/07/02/my-side-quest-measuring-input-latency-with-vk_ext_present_timing/

3. Try different compositors (niri)