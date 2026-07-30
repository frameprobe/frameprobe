# analyze.py output explained

Each value describes the click-to-photon latencies of one file or one pooled folder (all clicks from all its CSV files together).

For each click, the latency is the moment the light level crosses the midpoint (50%) of that click's own dark↔light swing and stays past it for 5 samples (timestamped at the first) — both reference levels are medians measured from the click's samples, so no per-hardware threshold tuning is needed. The same swing also yields two supplementary timestamps per click, t10 (onset) and t90 (near-settled). All headline stats come from the 50% crossing (t50). Passing `-t` instead uses the legacy fixed-delta detection (first single sample more than the given ADC delta away from the mean baseline), which reproduces the originally published numbers exactly.

- **detection** — how latencies were timed. In automatic mode it also reports the signal/noise separation: each click's swing divided by the peak-to-peak noise of its pre-click window. The minimum is the worst click in the set — if it drops toward ~2×, the sensor is barely seeing the transition (reposition it).

- **measurements** — number of clicks with a detected screen change. *skipped* = clicks with no valid transition, broken down by reason: *no-transition* (missed click, slipped sensor — swing within noise), *incomplete* (change still in progress at capture end), *malformed* (unparseable row); they are excluded from all stats.

- **mean ± … (95% CI)** — average latency. The ± is the uncertainty of that average: rerunning the same test would land the mean inside this range 95% of the time. Two cases whose ranges don't overlap are genuinely different. For folders, the margin is widened if the individual sessions disagree with each other.

- **median** — the middle click: half were faster, half slower. Like the mean but immune to a few extreme values.

- **p5** — the fast tail: 5% of clicks were faster than this. Approximates the best-case pipeline latency (click landed at the luckiest moment of the refresh cycle). A robust version of *min*.

- **p95** — the slow tail: 5% of clicks were slower than this. The "feels laggy" number — worst cases players actually notice. Where frame-pacing features should show their effect.

- **spread (p95 − p5)** — consistency: how wide the typical latency range is. Smaller = more predictable feel. More meaningful than sd, which is inflated the same way everywhere.

- **min / max** — single fastest and slowest click. Sanity checks only; each is one sample, so don't base conclusions on them.

- **onset (t10)** — median time to 10% of the swing: the earliest defensible "light started changing" moment, closest to a first-photon latency. Only counted for clicks where 10% of the swing clears the pre-click peak-to-peak noise — on a flickering white QD-OLED baseline that level is inside the flicker, so those clicks report t50 but no t10 (the report says how many). Absolute onset numbers are noise-floor dependent; use t50 for comparisons.

- **response (t10→t90)** — median time from 10% to 90% of the swing: how long the measured transition itself takes. This is sensor + panel combined — on the slow perfboard sensor it is dominated by the amplifier, on the fab PCB it approaches the panel's true response — so it is comparable within one sensor generation only.

- **histogram** — latency distribution in 0.5 ms bins; each row shows a bin's count as a bar. Shows the shape a single number can't: whether the whole block shifts between cases, whether a case has a longer tail, or whether clicks clump at multiples of the 2 ms frame period.
