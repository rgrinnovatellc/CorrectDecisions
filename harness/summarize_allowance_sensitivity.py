#!/usr/bin/env python3
"""Recompute every timing-dependent verifier check at wider endpoint allowances."""

import argparse
import csv
import io
import os
from pathlib import Path
import sys

import probe_harness
from summarize_harness_runs import (
    SummaryError,
    load_evidence,
    protocol_qualified,
    validate_campaign_archive,
)


FIELDS = (
    "endpoint_allowance_ms",
    "decision_margin_ms",
    "protocol_qualified_records",
    "records_passing_recomputed_timing_checks",
    "records_with_all_claim_bearing_gaps",
    "minimum_claim_bearing_gap_ms",
    "minimum_gap_beyond_margin_ms",
    "limiting_comparison",
    "limiting_evidence_number",
    "minimum_app_standby_minus_age_upper_ms",
    "minimum_app_standby_minus_minimum_latency_ms",
    "minimum_age_lower_minus_union_upper_ms",
    "minimum_age_lower_minus_additive_upper_ms",
)


def positive_integer(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def publish_csv(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = stream.getvalue().encode()
    if path.is_file() and not path.is_symlink():
        if path.read_bytes() == data:
            return
        raise SummaryError(f"existing output differs from regeneration: {path}")
    try:
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise SummaryError(f"refusing to overwrite {path}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--endpoint-allowance-ms",
        type=positive_integer,
        nargs="+",
        default=(20, 100, 500, 1000),
    )
    parser.add_argument("--decision-margin-ms", type=positive_integer, default=500)
    args = parser.parse_args()
    directory = Path(args.input_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not directory.is_dir() or directory.is_symlink():
        raise SummaryError(f"unsafe or missing input directory: {directory}")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise SummaryError(f"unsafe or missing output directory: {output.parent}")
    records = load_evidence(directory)
    if not validate_campaign_archive(records, directory, 30):
        raise SummaryError("sensitivity input is not an immutable campaign")
    passing = [
        record for record in records if protocol_qualified(record["attempt"])
    ]
    if len(passing) != 30:
        raise SummaryError(
            f"expected 30 protocol-qualified records, found {len(passing)}"
        )
    if args.decision_margin_ms != probe_harness.TOLERANCE_MS:
        raise SummaryError("decision margin must remain fixed at the campaign value")

    original_allowance = probe_harness.CLOCK_TOLERANCE_MS
    rows = []
    try:
        for allowance in args.endpoint_allowance_ms:
            probe_harness.CLOCK_TOLERANCE_MS = allowance
            gap_rows = []
            recomputed_passes = 0
            complete_gap_records = 0
            for record in passing:
                attempt = record["attempt"]
                observations = attempt["observations"]
                core = probe_harness.check_result(
                    observations["schedule"],
                    observations["baseline"],
                    observations["final"],
                    observations["events"],
                    observations["clock_brackets"],
                )
                history = probe_harness.analyze_constraint_history(
                    observations["baseline_job_dump_after_query"],
                    observations["final_job_dump"],
                    observations["events"],
                    observations["clock_brackets"],
                    probe_harness.stats(observations["baseline"]).get(
                        probe_harness.APP_STANDBY, 0
                    ),
                    probe_harness.stats(observations["final"]).get(
                        probe_harness.APP_STANDBY, 0
                    ),
                )
                recomputed_checks = {
                    **core["checks"],
                    **history["checks"],
                }
                if all(recomputed_checks.values()):
                    recomputed_passes += 1
                bounds = core["interval_bounds_ms"]
                final_stats = probe_harness.stats(observations["final"])
                shared = final_stats.get(probe_harness.APP_STANDBY)
                comparator = final_stats.get(probe_harness.MINIMUM_LATENCY)
                gaps = {}
                if shared is not None:
                    gaps["app_standby_minus_age_upper"] = (
                        shared - bounds["job_age_conservative_uptime"]["upper_ms"]
                    )
                if shared is not None and comparator is not None:
                    gaps["app_standby_minus_minimum_latency"] = shared - comparator
                if comparator is not None:
                    gaps["age_lower_minus_union_upper"] = (
                        bounds["job_age_conservative_uptime"]["lower_ms"]
                        - bounds["union"]["upper_ms"]
                    )
                    gaps["age_lower_minus_additive_upper"] = (
                        bounds["job_age_conservative_uptime"]["lower_ms"]
                        - bounds["additive"]["upper_ms"]
                    )
                if len(gaps) == 4:
                    complete_gap_records += 1
                if allowance == original_allowance:
                    if bounds != attempt["analysis"]["interval_bounds_ms"]:
                        raise SummaryError(
                            f"stored bounds do not reproduce in {record['path']}"
                        )
                gap_rows.append((record["number"], gaps))
            flattened = [
                (number, name, value)
                for number, gaps in gap_rows
                for name, value in gaps.items()
            ]
            if flattened:
                limiting_number, limiting_name, minimum_gap = min(
                    flattened, key=lambda value: value[2]
                )
            else:
                limiting_number = limiting_name = minimum_gap = ""
            comparison_names = (
                "app_standby_minus_age_upper",
                "app_standby_minus_minimum_latency",
                "age_lower_minus_union_upper",
                "age_lower_minus_additive_upper",
            )
            minima = {
                name: min(
                    (gaps[name] for _, gaps in gap_rows if name in gaps),
                    default="",
                )
                for name in comparison_names
            }
            rows.append({
                "endpoint_allowance_ms": allowance,
                "decision_margin_ms": args.decision_margin_ms,
                "protocol_qualified_records": len(passing),
                "records_passing_recomputed_timing_checks": recomputed_passes,
                "records_with_all_claim_bearing_gaps": complete_gap_records,
                "minimum_claim_bearing_gap_ms": minimum_gap,
                "minimum_gap_beyond_margin_ms": (
                    minimum_gap - args.decision_margin_ms
                    if minimum_gap != "" else ""
                ),
                "limiting_comparison": limiting_name,
                "limiting_evidence_number": limiting_number,
                "minimum_app_standby_minus_age_upper_ms": minima[
                    "app_standby_minus_age_upper"
                ],
                "minimum_app_standby_minus_minimum_latency_ms": minima[
                    "app_standby_minus_minimum_latency"
                ],
                "minimum_age_lower_minus_union_upper_ms": minima[
                    "age_lower_minus_union_upper"
                ],
                "minimum_age_lower_minus_additive_upper_ms": minima[
                    "age_lower_minus_additive_upper"
                ],
            })
    finally:
        probe_harness.CLOCK_TOLERANCE_MS = original_allowance
    publish_csv(output, rows)
    print(f"Created {output} ({len(rows)} allowance rows)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SummaryError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
