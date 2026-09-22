#!/usr/bin/env python3
"""Render the manuscript's public-result cells from a statistics CSV."""

import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
import io
import os
from pathlib import Path
import sys


ROWS = (
    ("app_standby_public", "final_app_standby_ms"),
    ("minimum_latency_public", "final_minimum_latency_ms"),
    ("job_age_upper", "job_age_conservative_upper_ms"),
    ("union_upper", "union_reference_upper_ms"),
    ("additive_upper", "additive_reference_upper_ms"),
    ("app_standby_minus_age_upper", "app_standby_minus_age_upper_ms"),
    (
        "app_standby_minus_minimum_latency",
        "app_standby_minus_minimum_latency_ms",
    ),
    (
        "minimum_latency_minus_additive_upper",
        "minimum_latency_minus_additive_upper_ms",
    ),
    ("updater_reconstruction_residual", "public_minus_exact_prediction_ms"),
)
FIELDS = ("key", "metric", "n", "median_s", "min_s", "max_s", "latex_cell")


class RenderError(RuntimeError):
    pass


def seconds(value):
    return str(
        (Decimal(value) / Decimal(1000)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--statistics", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.statistics).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise RenderError(f"unsafe or missing statistics CSV: {source}")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise RenderError(f"unsafe or missing output directory: {output.parent}")
    with source.open(newline="") as stream:
        by_metric = {row["metric"]: row for row in csv.DictReader(stream)}
    rows = []
    for key, metric in ROWS:
        row = by_metric.get(metric)
        if row is None or row.get("unit") != "ms":
            raise RenderError(f"missing or invalid metric row: {metric}")
        try:
            count = int(row["n"])
        except (KeyError, TypeError, ValueError) as error:
            raise RenderError(f"invalid sample count for metric: {metric}") from error
        if not 0 <= count <= 30:
            raise RenderError(f"out-of-range sample count for metric: {metric}")
        if count:
            median = seconds(row["median"])
            minimum = seconds(row["min"])
            maximum = seconds(row["max"])
            latex = rf"\({median}\ [{minimum},{maximum}]\)"
            if count != 30:
                latex += rf" \((n={count}/30)\)"
        else:
            median = minimum = maximum = ""
            latex = r"\(\mathrm{absent}\ (0/30)\)"
        rows.append({
            "key": key,
            "metric": metric,
            "n": str(count),
            "median_s": median,
            "min_s": minimum,
            "max_s": maximum,
            "latex_cell": latex,
        })
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = buffer.getvalue().encode()
    if output.is_file() and not output.is_symlink():
        if output.read_bytes() == data:
            print(f"Verified {output} ({len(rows)} manuscript rows)")
            return 0
        raise RenderError(f"existing output differs from regeneration: {output}")
    try:
        with output.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise RenderError(f"refusing to overwrite {output}") from error
    print(f"Created {output} ({len(rows)} manuscript rows)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RenderError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
