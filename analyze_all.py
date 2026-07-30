#!/usr/bin/env python3
"""Chart-JSON wrapper around analyze.py.

Analyzes every direct subfolder of the given folder (each subfolder = one
test case, pooled across its CSV files) and prints chart-ready JSON: the
subfolder names as labels, and median / p5 / p95 as datasets (the median
dataset carries the margin of error as a per-item `error` array), sorted
fastest median first. All stats come from analyze.py's collect_stats; this
script only iterates and assembles the JSON.
"""
import argparse
import json
import os
import sys

from analyze import collect_stats, histogram_counts

BIN_MS = 0.5
DATASETS = [
    ('MEDIAN', 'median_ms'),
    ('P5', 'p5_ms'),
    ('P95', 'p95_ms'),
]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Analyze every subfolder of a folder into chart JSON')
    parser.add_argument('folder', help='folder whose subfolders are test cases')
    parser.add_argument('-t', '--threshold', type=int, default=None,
                        help='fixed ADC delta threshold (legacy mode; default: '
                             'automatic per-row midpoint detection)')
    args = parser.parse_args()
    if args.threshold is not None and args.threshold <= 0:
        parser.error('threshold must be greater than zero')

    if not os.path.isdir(args.folder):
        sys.exit(f"No such folder: {args.folder}")

    results = []
    for entry in sorted(os.scandir(args.folder), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        stats = collect_stats(entry.path, args.threshold)
        if stats is None or not stats['measurements']:
            detail = (f"all {stats['skipped']} rows skipped: {stats['skip_reasons']}"
                      if stats else 'no valid measurements')
            print(f"skipping {entry.path}: {detail}", file=sys.stderr)
            continue
        results.append((entry.name, stats))

    if not results:
        sys.exit(f"No analyzable subfolders in {args.folder}")

    results.sort(key=lambda r: r[1]['median_ms'])

    main = {
        'title': 'placeholder',
        'text': 'placeholder',
        'labels': [name for name, _ in results],
        'datasets': [
            {
                'label': label,
                'data': [round(stats[key], 2) for _, stats in results],
                # error bar ± half-width around each median
                **({'error': [round(stats['moe_ms'], 2) for _, stats in results]}
                   if key == 'median_ms' else {}),
                'tooltipPosition': 'end',
            }
            for label, key in DATASETS
        ],
        'mode': 'horizontal',
        'titleX': 'placeholder',
    }

    # shared bins across all cases so the distributions are comparable
    lo = min(stats['min_ms'] for _, stats in results)
    hi = max(stats['max_ms'] for _, stats in results)
    case_counts = [
        (name, histogram_counts(stats['latencies_ms'], BIN_MS, lo, hi))
        for name, stats in results
    ]
    lo = case_counts[0][1][0]  # snapped to a bin edge
    case_counts = [(name, counts) for name, (_, counts) in case_counts]
    histogram = {
        'title': 'placeholder',
        'text': 'placeholder',
        'binWidthMs': BIN_MS,
        'labels': [f"{lo + i * BIN_MS:.1f}" for i in range(len(case_counts[0][1]))],
        'datasets': [{'label': name, 'data': counts} for name, counts in case_counts],
        'titleX': 'placeholder',
    }

    print(json.dumps({'main': main, 'histogram': histogram}, indent=4))
