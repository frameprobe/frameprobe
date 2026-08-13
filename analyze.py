#!/usr/bin/env python3
"""Latency analyzer with automatic per-row normalized-crossing detection.

For each CSV row: takes the median of the pre-click baseline window and the
median of the capture tail as the two reference levels (medians reject display
flicker dips), then timestamps fixed normalized crossings of that swing:

  t50 — the primary latency, first 5-sample-sustained crossing of 50%. This is
        the standard display-metrology fiducial; flicker never reaches half the
        swing, so it needs no per-hardware tuning.
  t10 — onset, closest to "first visible change". Only reported for rows where
        10% of the swing clears the peak-to-peak noise of the pre-click window
        (QD-OLED flicker on a white baseline sits above 10%, so white->black
        rows on that hardware report t50 but no t10).
  t90 — near-settled; first crossing, no sustain (settled-level flicker
        recrosses 90%). t90 - t10 is the sensor+panel response time.

Both reference levels come from the row itself, so results are independent of
what other rows or files are analyzed alongside. Rows without a real transition
(missed click, slipped sensor) are skipped per-row with a reason; a metric
whose level is not safely above the noise is reported as unavailable for that
row instead of silently moving the crossing point. All ranking stats (mean,
median, percentiles, histogram) are computed from t50 only.

Backlight-PWM displays (e.g. MacBook Pro mini-LED, ~3 kHz strobe) make the lit
screen a full-scale square wave to the photodiode, which corrupts detection in
both directions: white-baseline rows are rejected as no-transition (the strobe
swamps the noise window) and black-baseline rows either never sustain a t50
crossing (the off-phases recross it) or timestamp the first on-pulse instead
of the averaged-luminance midpoint. Every row is therefore checked before
detection: when the noisier reference window holds a strongly periodic
oscillation (autocorrelation >= 0.8 at its strongest local maximum) whose
peak-to-peak reaches past the midpoint of the raw swing — the condition under
which crossing detection breaks — detection runs on a symmetric exactly-one-
period moving average instead, a comb filter that nulls the strobe and its
harmonics without shifting the midpoint crossing of a monotonic edge. All rows
of a strobing display go through the same filter regardless of direction.
Steady and sub-midpoint-flicker (QD-OLED) displays never trip the gate, so
clean results are unchanged, and a genuinely flat row stays flat after
filtering, so missed clicks are still skipped.

Passing -t instead selects the legacy m2p-latency mode: mean baseline, scan
until |sample - baseline| exceeds the fixed threshold, single-sample crossing —
bit-identical to the originally published analysis. After all rows: computes
mean and sample standard deviation (Bessel's correction), matching
m2p-latency's computeStatsMs.

Arguments may be CSV files or folders. A folder is scanned recursively for
.csv files and analyzed as one pooled group: stats are computed across all
clicks from all files, and the margin of error is design-effect adjusted,
treating each file as a session (cluster). Single files get the naive margin
of error, since between-session variance can't be estimated from one session.
"""
import argparse
import csv
import json
import math
import os
import sys
from collections import Counter

# A data row is ~50 KB, uncomfortably close to the 128 KB default. Cap at the
# C long max instead of sys.maxsize: on Windows a long is 32-bit, so passing
# sys.maxsize raises OverflowError.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

Z_95 = 1.96
SETTLED_TAIL = 500  # samples (~12ms): >= 3 flicker periods at 240Hz, median-safe
BASELINE_WINDOW = 200  # pre-click samples for the baseline level
NOISE_WINDOW = 1000  # pre-click samples (~24ms) for noise: covers several flicker periods
MIN_SWING = 50  # ADC counts: floor so near-zero baseline noise can't validate drift
SUSTAIN = 5  # consecutive samples a t10/t50 crossing must hold (timestamps the run's first)
ONSET_FRACTION = 0.10
SETTLED_FRACTION = 0.90
FLICKER_MAX_LAG = 200  # samples (~5ms): period search covers strobes down to ~210Hz
FLICKER_MIN_CORR = 0.8  # PWM windows autocorrelate ~0.99 at the period; steady ones < 0.5


def flicker_period(window):
    """Dominant oscillation period of a sample window in samples, or None.

    Overlap-unbiased normalized autocorrelation (each lag's sum is scaled by
    its own term count, so long periods aren't penalized), searched only at
    local maxima: r decays monotonically from lag 0 before the first dip, so
    without that restriction the small-lag shoulder of a slow strobe (e.g.
    lag 2 of a 100-sample period) outscores the fundamental. Integer
    multiples of the period score essentially the same as the fundamental, so
    among local maxima within 2% of the best the smallest lag wins.
    """
    mean = sum(window) / len(window)
    d = [x - mean for x in window]
    energy = sum(x * x for x in d)
    if energy == 0:
        return None
    # one extra lag past max_lag so a period of exactly max_lag still has the
    # right-hand neighbor the local-maximum test needs
    max_lag = min(FLICKER_MAX_LAG, len(d) // 2)
    r = [sum(d[i] * d[i + lag] for i in range(len(d) - lag))
         / (len(d) - lag) / (energy / len(d))
         for lag in range(1, max_lag + 2)]
    peaks = [(k + 1, r[k]) for k in range(1, len(r) - 1)
             if r[k - 1] < r[k] >= r[k + 1]]
    if not peaks:
        return None
    best_r = max(pr for _, pr in peaks)
    if best_r < FLICKER_MIN_CORR:
        return None
    return min(lag for lag, pr in peaks if pr >= best_r * 0.98)


def comb_filtered(samples, period):
    """Symmetric moving average over exactly one flicker period.

    A window of exactly one period nulls the strobe fundamental and all its
    harmonics. Odd periods use a plain centered box; even periods average the
    two boxes offset ±half a sample (equivalent to half-weight end taps), so
    the kernel stays both exactly one period long and symmetric — a widened
    odd box would leave a phase-dependent residual, an uncentered even box
    would shift every crossing by half a sample. Truncated at the array ends.
    """
    n = len(samples)
    prefix = [0]
    for x in samples:
        prefix.append(prefix[-1] + x)

    def box_mean(i, lo_off, hi_off):
        a, b = max(0, i + lo_off), min(n, i + hi_off)
        return (prefix[b] - prefix[a]) / (b - a)

    half = period // 2
    if period % 2:
        return [box_mean(i, -half, half + 1) for i in range(n)]
    return [(box_mean(i, -half, half) + box_mean(i, -half + 1, half + 1)) / 2
            for i in range(n)]


def compute_crossings(row, threshold=None):
    """Per-row transition metrics: (metrics, None) or (None, skip_reason).

    threshold=None (normalized mode) yields
        {'t50_us', 't10_us', 't90_us', 'separation'}
    where t50_us is the primary latency (always present), t10_us/t90_us are
    None when unavailable for this row, and separation = |swing| / pre-click
    noise peak-to-peak. Rows recovered through backlight PWM additionally
    carry 'flicker_period_us' (the strobe period), with all metrics computed
    on the comb-filtered signal. threshold=int is the legacy fixed-delta scan
    and yields {'t50_us'} only. Skip reasons: 'malformed', 'no-transition'
    (swing within noise), 'incomplete' (t50 not reached before capture end),
    'no-crossing' (legacy mode).
    """
    try:
        samples = [int(s) for s in row['samples'].split(';') if s.strip()]
        pre_click = int(row.get('preClickSamples', 0))
        duration_us = int(row['timeTaken'])
        click_us = int(row.get('clickTime', 0))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, 'malformed'
    n = len(samples)
    if n == 0 or not 0 < pre_click < n:
        return None, 'malformed'
    # timeTaken includes the Mouse.press() pause, which is not sampling time
    us_per_sample = (duration_us - click_us) / n

    if threshold is not None:
        # legacy mode: mean baseline, first single sample past a fixed delta —
        # kept bit-identical to the originally published analysis
        bl_start = max(0, pre_click - BASELINE_WINDOW)
        baseline = sum(samples[bl_start:pre_click]) / (pre_click - bl_start)
        for i in range(pre_click, n):
            if abs(samples[i] - baseline) > threshold:
                # first post-click sample is taken click_us after the click fired
                return {'t50_us': click_us + (i - pre_click) * us_per_sample}, None
        return None, 'no-crossing'

    def to_us(index):
        # the first post-click sample is taken click_us after the click fired
        return click_us + (index - pre_click) * us_per_sample

    def detect(sig):
        # reference levels are medians so a flicker dip in the window can't drag them
        bl_window = sorted(sig[max(0, pre_click - BASELINE_WINDOW):pre_click])
        baseline = bl_window[len(bl_window) // 2]
        tail = sorted(sig[max(pre_click, n - SETTLED_TAIL):])
        settled = tail[len(tail) // 2]
        swing = settled - baseline

        noise_window = sig[max(0, pre_click - NOISE_WINDOW):pre_click]
        noise_pp = max(noise_window) - min(noise_window)
        # no real transition (missed click, slipped sensor, drift within noise)
        if abs(swing) <= max(MIN_SWING, 2 * noise_pp):
            return None, 'no-transition'

        def crossing_index(fraction, sustain, start):
            level = baseline + swing * fraction
            run = 0
            for i in range(start, n):
                beyond = sig[i] >= level if swing > 0 else sig[i] <= level
                run = run + 1 if beyond else 0
                if run >= sustain:
                    # the run's first sample: the sustain requirement filters
                    # spikes but must not add latency
                    return i - run + 1
            return None

        i50 = crossing_index(0.5, SUSTAIN, pre_click)
        if i50 is None:
            # transition still in progress at capture end
            return None, 'incomplete'
        # onset only when 10% of the swing clears the pre-click peak-to-peak noise
        # (QD-OLED flicker on a white baseline exceeds it: t10 stays unavailable
        # for those rows rather than the level silently moving). Any sustained t50
        # run also crosses the shallower 10% level, so i10 <= i50 always.
        i10 = (crossing_index(ONSET_FRACTION, SUSTAIN, pre_click)
               if abs(swing) * ONSET_FRACTION > noise_pp else None)
        # settled-level flicker recrosses 90%, so first crossing, no sustain — but
        # searched from the t50 crossing, so an isolated early spike can't yield
        # t90 < t50 (a negative response time)
        i90 = crossing_index(SETTLED_FRACTION, 1, i50)
        return {
            't50_us': to_us(i50),
            't10_us': to_us(i10) if i10 is not None else None,
            't90_us': to_us(i90) if i90 is not None else None,
            'separation': abs(swing) / max(1, noise_pp),
        }, None

    # Backlight-PWM strobe check, independent of whether raw detection would
    # succeed: on a strobing display, raw detection fails one direction
    # (lit-baseline swing drowns in "noise", black-baseline crossings never
    # sustain through the off-phases) but can pass the other when an on-pulse
    # lasts >= SUSTAIN samples — timestamping the first pulse instead of the
    # averaged-luminance midpoint. Every row of a strobing display must go
    # through the same filter, so the gate is a property of the signal: a
    # strongly periodic oscillation whose peak-to-peak reaches past the
    # midpoint of the raw swing (only then can it corrupt crossing
    # detection). Sub-midpoint flicker (QD-OLED) stays on the raw path.
    pre_w = samples[max(0, pre_click - NOISE_WINDOW):pre_click]
    tail_w = samples[max(pre_click, n - NOISE_WINDOW):]
    osc = max(pre_w, tail_w, key=lambda w: max(w) - min(w))
    # the cheap peak-to-peak gate runs first: on a clean display the
    # oscillation never reaches half the swing, so the O(window * max_lag)
    # autocorrelation is skipped for nearly every row
    bl_w = sorted(samples[max(0, pre_click - BASELINE_WINDOW):pre_click])
    tail = sorted(samples[max(pre_click, n - SETTLED_TAIL):])
    raw_swing = tail[len(tail) // 2] - bl_w[len(bl_w) // 2]
    if max(osc) - min(osc) > abs(raw_swing) / 2:
        period = flicker_period(osc)
        if period is not None:
            metrics, reason = detect(comb_filtered(samples, period))
            if metrics is not None:
                metrics['flicker_period_us'] = period * us_per_sample
            return metrics, reason
    return detect(samples)


def compute_latency(row, threshold=None):
    """Primary latency (t50 midpoint, or legacy delta) in µs, or None."""
    metrics, _ = compute_crossings(row, threshold)
    return metrics['t50_us'] if metrics else None


def compute_stats_ms(latencies_us):
    """Mean and sample standard deviation in ms (mirrors m2p computeStatsMs)."""
    n = len(latencies_us)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return latencies_us[0] / 1000.0, 0.0

    mean_us = sum(latencies_us) / n
    variance_us = sum((x - mean_us) ** 2 for x in latencies_us) / (n - 1)
    sd_us = math.sqrt(variance_us)

    return mean_us / 1000.0, sd_us / 1000.0


def percentile(ordered, p):
    """p-th percentile of an ascending-sorted list, linear interpolation."""
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def histogram_counts(latencies_ms, bin_ms=0.5, lo=None, hi=None):
    """Bin counts over [lo, hi] (default: data range), edges snapped to bin_ms.

    Returns (lo, counts) with lo snapped down to a bin edge. Pass explicit
    lo/hi to get identical bins across multiple datasets.
    """
    lo = latencies_ms[0] if lo is None else lo
    hi = latencies_ms[-1] if hi is None else hi
    lo = math.floor(lo / bin_ms) * bin_ms
    hi = math.ceil(hi / bin_ms) * bin_ms
    bins = max(1, round((hi - lo) / bin_ms))
    counts = [0] * bins
    for x in latencies_ms:
        counts[min(int((x - lo) / bin_ms), bins - 1)] += 1
    return lo, counts


def bar_char():
    """'█' if stdout can encode it, else '#'.

    Redirected stdout on Windows uses the locale codepage (cp1252), which has
    no block character.
    """
    try:
        '█'.encode(sys.stdout.encoding or 'utf-8')
    except (UnicodeEncodeError, LookupError):
        return '#'
    return '█'


def print_histogram(latencies_ms, bin_ms=0.5, max_width=50):
    """ASCII histogram; 0.5ms bins resolve humps at the 2ms frame period."""
    lo, counts = histogram_counts(latencies_ms, bin_ms)
    peak = max(counts)
    block = bar_char()
    for i, c in enumerate(counts):
        bar = block * round(c / peak * max_width)
        print(f"  {lo + i * bin_ms:5.1f} ms |{bar:<{max_width}} {c}")


def margin_of_error_ms(sessions_us):
    """95% margin of error of the mean, in ms.

    sessions_us: list of per-file latency lists (µs). Naive CI (1.96·sd/√n),
    inflated by √(design effect) when ≥2 sessions allow estimating
    between-session variance via one-way ANOVA. Sessions that drift produce a
    wider margin; statistically identical sessions leave the naive CI intact.
    """
    all_us = [x for s in sessions_us for x in s]
    n = len(all_us)
    if n < 2:
        return 0.0
    _, sd_ms = compute_stats_ms(all_us)
    naive_ms = Z_95 * sd_ms / math.sqrt(n)

    sessions = [s for s in sessions_us if s]
    k = len(sessions)
    if k < 2 or n <= k:
        return naive_ms

    grand = sum(all_us) / n
    means = [sum(s) / len(s) for s in sessions]
    ss_between = sum(len(s) * (m - grand) ** 2 for s, m in zip(sessions, means))
    ss_within = sum(sum((x - m) ** 2 for x in s) for s, m in zip(sessions, means))
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n - k)
    if ms_within == 0:
        return naive_ms

    m_avg = n / k
    icc = max(0.0, (ms_between - ms_within) / (ms_between + (m_avg - 1) * ms_within))
    deff = 1 + (m_avg - 1) * icc
    return naive_ms * math.sqrt(deff)


def read_rows(path, threshold):
    """Per-row metric dicts, skip-reason counts and session metadata for one
    CSV file. Metadata comes from '#' comment lines (written by main.py from
    the firmware's META line, e.g. '# mode=move,distance=500,...'); files
    predating the metadata line simply yield an empty dict."""
    records = []
    skip_reasons = Counter()
    meta = {}
    with open(path, newline='', encoding='utf-8') as f:
        def data_lines():
            for line in f:
                if line.startswith('#'):
                    for part in line[1:].strip().split(','):
                        if '=' in part:
                            k, v = part.split('=', 1)
                            meta[k.strip()] = v.strip()
                    continue
                yield line
        reader = csv.DictReader(data_lines())
        for row in reader:
            metrics, reason = compute_crossings(row, threshold)
            if metrics is not None:
                records.append(metrics)
            else:
                skip_reasons[reason] += 1
    return records, skip_reasons, meta


def collect_stats(path, threshold=None):
    """Pooled stats for a CSV file or folder of CSVs.

    Returns a dict with the stats (ms) plus the sorted latency list, or None
    when the path has no CSV files or no valid measurements. Prints nothing.
    All ranking stats (mean, median, p5/p95, histogram) come from t50; onset
    (t10) and sensor+panel response (t90 - t10) are supplementary medians over
    the rows where those levels are safely above the noise. When rows exist
    but none are valid, returns a diagnostic dict with measurements == 0 and
    the skip reasons instead of the full stats.
    """
    if threshold is not None and threshold <= 0:
        raise ValueError("threshold must be greater than zero")
    if os.path.isdir(path):
        files = sorted(
            os.path.join(root, name)
            for root, _, names in os.walk(path)
            for name in names
            if name.endswith('.csv')
        )
        label = f"{path} ({len(files)} files)"
    else:
        files = [path]
        label = path
    if not files:
        return None

    sessions = []
    skip_reasons = Counter()
    modes = set()
    any_meta = False
    for f in files:
        recs, reasons, meta = read_rows(f, threshold)
        sessions.append(recs)
        skip_reasons += reasons
        if meta:
            any_meta = True
        # 'unknown' marks pre-metadata files pooled with tagged ones, so a
        # mixed folder can't silently claim a single mode
        modes.add(meta.get('mode', 'unknown'))

    records = [r for s in sessions for r in s]
    if not records:
        if skip_reasons:
            # keep the diagnostics: every row was read but none was usable
            return {
                'label': label,
                'detection': ('midpoint' if threshold is None
                              else f'legacy threshold {threshold}'),
                'measurements': 0,
                'skipped': sum(skip_reasons.values()),
                'skip_reasons': dict(skip_reasons),
            }
        return None

    sessions_us = [[r['t50_us'] for r in s] for s in sessions]
    latencies_us = [r['t50_us'] for r in records]

    mean_ms, sd_ms = compute_stats_ms(latencies_us)
    latencies_ms = sorted(l / 1000 for l in latencies_us)
    n = len(latencies_ms)
    median_ms = (latencies_ms[n // 2] if n % 2 else
                 (latencies_ms[n // 2 - 1] + latencies_ms[n // 2]) / 2)
    p5_ms = percentile(latencies_ms, 5)
    p95_ms = percentile(latencies_ms, 95)

    stats = {
        'label': label,
        'detection': ('midpoint' if threshold is None
                      else f'legacy threshold {threshold}'),
        'measurements': n,
        **({'mode': ', '.join(sorted(modes))} if any_meta else {}),
        'skipped': sum(skip_reasons.values()),
        'skip_reasons': dict(skip_reasons),
        'mean_ms': mean_ms,
        'moe_ms': margin_of_error_ms(sessions_us),
        'sd_ms': sd_ms,
        'median_ms': median_ms,
        'p5_ms': p5_ms,
        'p95_ms': p95_ms,
        'spread_ms': p95_ms - p5_ms,
        'min_ms': latencies_ms[0],
        'max_ms': latencies_ms[-1],
        'latencies_ms': latencies_ms,
    }

    if threshold is None:
        onsets = sorted(r['t10_us'] / 1000 for r in records
                        if r['t10_us'] is not None)
        responses = sorted((r['t90_us'] - r['t10_us']) / 1000 for r in records
                           if r['t10_us'] is not None and r['t90_us'] is not None)
        separations = sorted(r['separation'] for r in records)
        flicker_periods = sorted(r['flicker_period_us'] for r in records
                                 if r.get('flicker_period_us') is not None)
        stats.update({
            'onset_median_ms': percentile(onsets, 50) if onsets else None,
            'onset_n': len(onsets),
            'response_median_ms': percentile(responses, 50) if responses else None,
            'response_n': len(responses),
            'separation_min': separations[0],
            'separation_median': percentile(separations, 50),
            'flicker_n': len(flicker_periods),
            'flicker_period_us': (percentile(flicker_periods, 50)
                                  if flicker_periods else None),
        })
    return stats


def stats_to_json(stats):
    """JSON-friendly copy of a collect_stats dict: rounded, no raw latencies or sd."""
    return {k: round(v, 2) if isinstance(v, float) else v
            for k, v in stats.items()
            if k not in ('latencies_ms', 'sd_ms') and v != {}}


def analyze(path, threshold):
    if not os.path.exists(path):
        print(f"No such file or directory: {path}")
        return
    stats = collect_stats(path, threshold)
    if stats is None:
        print(f"No CSV files or measurements in {path}")
        return
    if not stats['measurements']:
        reasons = ', '.join(f"{v} {k}" for k, v in sorted(stats['skip_reasons'].items()))
        print(f"\n{stats['label']}\n  no valid measurements "
              f"({stats['skipped']} rows skipped: {reasons})")
        return

    print(f"\n{stats['label']}")
    if stats.get('mode'):
        print(f"  mode:   {stats['mode']}")
    if 'separation_min' in stats:
        print(f"  detection: t50 midpoint of each row's swing "
              f"({SUSTAIN}-sample sustained crossing); signal/noise separation "
              f"min {stats['separation_min']:.0f}x, "
              f"median {stats['separation_median']:.0f}x")
    else:
        print(f"  detection: {stats['detection']} ADC (fixed delta, "
              f"single-sample crossing)")
    if stats['skipped']:
        reasons = ', '.join(f"{v} {k}" for k, v in sorted(stats['skip_reasons'].items()))
        print(f"  measurements: {stats['measurements']} ({stats['skipped']} skipped: {reasons})")
    else:
        print(f"  measurements: {stats['measurements']} (0 skipped)")
    if stats.get('flicker_n'):
        print(f"  flicker: {stats['flicker_n']} rows detected through backlight "
              f"PWM (~{1e3 / stats['flicker_period_us']:.1f} kHz strobe, "
              f"one-period comb filter)")
    print(f"  mean:   {stats['mean_ms']:.2f} ms ± {stats['moe_ms']:.2f} ms (95% CI)")
    print(f"  sd:     {stats['sd_ms']:.2f} ms")
    print(f"  median: {stats['median_ms']:.2f} ms")
    print(f"  p5:     {stats['p5_ms']:.2f} ms")
    print(f"  p95:    {stats['p95_ms']:.2f} ms")
    print(f"  spread: {stats['spread_ms']:.2f} ms (p95 - p5)")
    print(f"  min:    {stats['min_ms']:.2f} ms")
    print(f"  max:    {stats['max_ms']:.2f} ms")
    if stats.get('onset_n'):
        no_t10 = stats['measurements'] - stats['onset_n']
        note = f"; t10 within noise on {no_t10} rows" if no_t10 else ""
        print(f"  onset:  {stats['onset_median_ms']:.2f} ms median "
              f"(t10, {stats['onset_n']} rows{note})")
    elif 'onset_n' in stats:
        print("  onset:  unavailable (t10 within noise on all rows)")
    if stats.get('response_n'):
        print(f"  response: {stats['response_median_ms']:.2f} ms median "
              f"(t10→t90 sensor+panel, {stats['response_n']} rows)")
    print()
    print_histogram(stats['latencies_ms'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze latency CSVs (m2p-style)')
    parser.add_argument('files', nargs='+',
                        help='CSV file(s) and/or folder(s); folders are scanned '
                             'recursively and pooled into one result each')
    parser.add_argument('-t', '--threshold', type=int, default=None,
                        help='fixed ADC delta threshold (legacy mode; default: '
                             'automatic per-row midpoint detection)')
    parser.add_argument('--json', action='store_true',
                        help='print stats as a JSON array instead of the '
                             'human-readable report (paths without data are '
                             'skipped with a note on stderr)')
    args = parser.parse_args()
    if args.threshold is not None and args.threshold <= 0:
        parser.error('threshold must be greater than zero')

    if args.json:
        results = []
        for path in args.files:
            stats = collect_stats(path, args.threshold) if os.path.exists(path) else None
            if stats is None or not stats['measurements']:
                detail = (f"all {stats['skipped']} rows skipped: {stats['skip_reasons']}"
                          if stats else 'no valid measurements')
                print(f"skipping {path}: {detail}", file=sys.stderr)
                continue
            results.append(stats_to_json(stats))
        print(json.dumps(results, indent=4))
    else:
        for path in args.files:
            analyze(path, args.threshold)
