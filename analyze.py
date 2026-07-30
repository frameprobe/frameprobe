#!/usr/bin/env python3
"""Latency analyzer using m2p-latency's delta-from-baseline threshold approach.

For each CSV row: averages the pre-click baseline, scans post-click samples
until |sample - baseline| exceeds a threshold, and records that as the latency.
After all rows: computes mean and sample standard deviation (Bessel's correction),
matching m2p-latency's computeStatsMs.

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

# A data row is ~50 KB, uncomfortably close to the 128 KB default. Cap at the
# C long max instead of sys.maxsize: on Windows a long is 32-bit, so passing
# sys.maxsize raises OverflowError.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

DEFAULT_THRESHOLD = 1000  # 14-bit ADC units; ~200mV at 3.3V/16383
# The fab PCB swings ~565 (black) to ~3400 (white), and a white QD-OLED screen
# shows per-refresh flicker dips of ~550 ADC units — the threshold must sit
# above the flicker and well below the ~2800-unit transition. Perfboard-era
# captures (e.g. test_run1/) only swing ~390 units total; analyze those with
# the old value: -t 100.
Z_95 = 1.96


def compute_latency(row, threshold):
    """Detect screen change using delta-from-baseline, return latency in µs or None."""
    samples = [int(s) for s in row['samples'].split(';') if s.strip()]
    n = len(samples)
    pre_click = int(row.get('preClickSamples', 0))
    duration_us = int(row['timeTaken'])
    click_us = int(row.get('clickTime', 0))
    # timeTaken includes the Mouse.press() pause, which is not sampling time
    us_per_sample = (duration_us - click_us) / n

    # baseline: average of last 200 pre-click samples (or all pre-click if fewer)
    bl_start = max(0, pre_click - 200)
    bl_end = pre_click
    if bl_end <= bl_start:
        return None
    baseline = sum(samples[bl_start:bl_end]) / (bl_end - bl_start)

    # scan post-click samples for threshold crossing
    for i in range(pre_click, n):
        if abs(samples[i] - baseline) > threshold:
            # first post-click sample is taken click_us after the click fired
            latency_us = click_us + (i - pre_click) * us_per_sample
            return latency_us

    return None


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


def read_latencies(path, threshold):
    """Latencies (µs) and skipped-row count for one CSV file."""
    latencies_us = []
    skipped = 0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            latency = compute_latency(row, threshold)
            if latency is not None:
                latencies_us.append(latency)
            else:
                skipped += 1
    return latencies_us, skipped


def collect_stats(path, threshold):
    """Pooled stats for a CSV file or folder of CSVs.

    Returns a dict with the stats (ms) plus the sorted latency list, or None
    when the path has no CSV files or no valid measurements. Prints nothing.
    """
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

    sessions_us = []
    skipped = 0
    for f in files:
        lats, skip = read_latencies(f, threshold)
        sessions_us.append(lats)
        skipped += skip

    latencies_us = [x for s in sessions_us for x in s]
    if not latencies_us:
        return None

    mean_ms, sd_ms = compute_stats_ms(latencies_us)
    latencies_ms = sorted(l / 1000 for l in latencies_us)
    n = len(latencies_ms)
    median_ms = (latencies_ms[n // 2] if n % 2 else
                 (latencies_ms[n // 2 - 1] + latencies_ms[n // 2]) / 2)
    p5_ms = percentile(latencies_ms, 5)
    p95_ms = percentile(latencies_ms, 95)

    return {
        'label': label,
        'measurements': n,
        'skipped': skipped,
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


def stats_to_json(stats):
    """JSON-friendly copy of a collect_stats dict: rounded, no raw latencies or sd."""
    return {k: round(v, 2) if isinstance(v, float) else v
            for k, v in stats.items() if k not in ('latencies_ms', 'sd_ms')}


def analyze(path, threshold):
    if not os.path.exists(path):
        print(f"No such file or directory: {path}")
        return
    stats = collect_stats(path, threshold)
    if stats is None:
        print(f"No CSV files or valid measurements in {path}")
        return

    print(f"\n{stats['label']}")
    print(f"  measurements: {stats['measurements']} ({stats['skipped']} skipped)")
    print(f"  mean:   {stats['mean_ms']:.2f} ms ± {stats['moe_ms']:.2f} ms (95% CI)")
    print(f"  sd:     {stats['sd_ms']:.2f} ms")
    print(f"  median: {stats['median_ms']:.2f} ms")
    print(f"  p5:     {stats['p5_ms']:.2f} ms")
    print(f"  p95:    {stats['p95_ms']:.2f} ms")
    print(f"  spread: {stats['spread_ms']:.2f} ms (p95 - p5)")
    print(f"  min:    {stats['min_ms']:.2f} ms")
    print(f"  max:    {stats['max_ms']:.2f} ms")
    print()
    print_histogram(stats['latencies_ms'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze latency CSVs (m2p-style)')
    parser.add_argument('files', nargs='+',
                        help='CSV file(s) and/or folder(s); folders are scanned '
                             'recursively and pooled into one result each')
    parser.add_argument('-t', '--threshold', type=int, default=DEFAULT_THRESHOLD,
                        help=f'ADC delta threshold (default: {DEFAULT_THRESHOLD})')
    parser.add_argument('--json', action='store_true',
                        help='print stats as a JSON array instead of the '
                             'human-readable report (paths without data are '
                             'skipped with a note on stderr)')
    args = parser.parse_args()

    if args.json:
        results = []
        for path in args.files:
            stats = collect_stats(path, args.threshold) if os.path.exists(path) else None
            if stats is None:
                print(f"skipping {path}: no valid measurements", file=sys.stderr)
                continue
            results.append(stats_to_json(stats))
        print(json.dumps(results, indent=4))
    else:
        for path in args.files:
            analyze(path, args.threshold)
