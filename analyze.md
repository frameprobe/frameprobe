# analyze.py output explained

Each value describes the click-to-photon latencies of one file or one pooled folder (all clicks from all its CSV files together).

For each click, the latency is the moment the light level crosses the midpoint (50%) of that click's own dark↔light swing and stays past it for 5 samples (timestamped at the first) — both reference levels are medians measured from the click's samples, so no per-hardware threshold tuning is needed. The same swing also yields two supplementary timestamps per click, t10 (onset) and t90 (near-settled). All headline stats come from the 50% crossing (t50). Passing `-t` instead uses the legacy fixed-delta detection (first single sample more than the given ADC delta away from the mean baseline), which reproduces the originally published numbers exactly.

- **mode** — which input event the sessions measured: *click* or *move* (read from the metadata comment line newer captures carry). Only shown when at least one file has metadata; files recorded before the metadata line existed are listed as *unknown*, so a pooled folder that mixes tagged and untagged sessions says so instead of claiming a single mode.

- **reference** — only shown with `--from-delivery`: latencies count from the moment the USB host actually picked the click report up off the device, not from the firmware pressing the button. A mouse only hands its click to the PC when the PC polls for it (every 1 ms here), so the default numbers include a random 0–1 ms wait — that's real button-to-photon latency, what a person feels. `--from-delivery` removes exactly that wait (newer captures record it per click), giving a tighter number that isolates the PC + display pipeline — better for A/B-ing displays, but ~0.5 ms lower than what a user experiences. Only captures that recorded the delivery moment can be re-referenced; older files are skipped as *no-delivery*.

- **detection** — how latencies were timed. In automatic mode it also reports the signal/noise separation: each click's swing divided by the peak-to-peak noise of its pre-click window. The minimum is the worst click in the set — if it drops toward ~2×, the sensor is barely seeing the transition (reposition it).

- **measurements** — number of clicks with a detected screen change. *skipped* = clicks with no valid transition, broken down by reason: *no-transition* (missed click, slipped sensor — swing within noise), *incomplete* (change still in progress at capture end), *malformed* (unparseable row), *no-delivery* (the host never picked the click up — device unplugged or host suspended mid-run; or, under `--from-delivery`, a file too old to record delivery); they are excluded from all stats.

- **flicker** — only shown when some clicks were measured through temporal light modulation (TLM). TLM is the umbrella term for any periodic brightness variation of the display: a PWM-strobed backlight (e.g. MacBook Pro mini-LED, ~3 kHz) and a deep OLED per-refresh brightness dip (e.g. QD-OLED at its refresh rate) look identical to the photodiode, so the analyzer names what it measures rather than guessing the cause — the reported frequency tells you which it is (kHz range → likely backlight PWM, ≈ the refresh rate → refresh flicker). Modulation that reaches past the midpoint of the swing corrupts normal crossing detection, so every click is checked before detection: when a reference window oscillates strongly periodically and the oscillation reaches past the midpoint, detection runs on a moving average of exactly one modulation period, which cancels the modulation — so those clicks are measured the same way regardless of direction. The line reports how many clicks this applied to and the modulation frequency. Timing is blurred by at most one modulation period, and the separation figures for these clicks describe the filtered signal. Mild flicker that stays below the midpoint does not trigger this and keeps raw detection.

- **delivery** — only shown for captures that record it: how long each click sat on the device before the host's USB poll picked it up (median, min, max). Expect a median around 0.5 ms spread across 0–1 ms — the physics of 1000 Hz polling. It is a diagnostic, always relative to the press regardless of `--from-delivery`: values hugging 1 ms or beyond suggest the host was polling slowly or the bus was busy. This is exactly the component `--from-delivery` subtracts.

- **mean ± … (95% CI)** — average latency. The ± is the uncertainty of that average: rerunning the same test would land the mean inside this range 95% of the time. Two cases whose ranges don't overlap are genuinely different. For folders, the margin is widened if the individual sessions disagree with each other.

- **median** — the middle click: half were faster, half slower. Like the mean but immune to a few extreme values.

- **p5** — the fast tail: 5% of clicks were faster than this. Approximates the best-case pipeline latency (click landed at the luckiest moment of the refresh cycle). A robust version of *min*.

- **p95** — the slow tail: 5% of clicks were slower than this. The "feels laggy" number — worst cases players actually notice. Where frame-pacing features should show their effect.

- **spread (p95 − p5)** — consistency: how wide the typical latency range is. Smaller = more predictable feel. More meaningful than sd, which is inflated the same way everywhere.

- **min / max** — single fastest and slowest click. Sanity checks only; each is one sample, so don't base conclusions on them.

- **onset (t10)** — median time to 10% of the swing: the earliest defensible "light started changing" moment, closest to a first-photon latency. Only counted for clicks where 10% of the swing clears the pre-click peak-to-peak noise — on a flickering white QD-OLED baseline that level is inside the flicker, so those clicks report t50 but no t10 (the report says how many). Absolute onset numbers are noise-floor dependent; use t50 for comparisons.

- **response (t10→t90)** — median time from 10% to 90% of the swing: how long the measured transition itself takes. This is sensor + panel combined — on the slow perfboard sensor it is dominated by the amplifier, on the fab PCB it approaches the panel's true response — so it is comparable within one sensor generation only.

- **histogram** — latency distribution in 0.5 ms bins; each row shows a bin's count as a bar. Shows the shape a single number can't: whether the whole block shifts between cases, whether a case has a longer tail, or whether clicks clump at multiples of the 2 ms frame period.
