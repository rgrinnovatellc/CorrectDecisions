#!/usr/bin/env python3
"""Portably regenerate and compare the sealed campaign's derived outputs.

The archived aggregate validator mixes portable archive checks with live
dereferences of tools at absolute paths on the original host.  This reviewer
tool first runs the independent standalone verifier, which authenticates the
fixed campaign bytes and validates the archived records and provenance.  It
then substitutes that aggregate validator as a whole, executes the exact
archived analysis modules on temporary copies of all 31 raw records, and
compares every generated output byte-for-byte with the sealed output.  It
never writes to the retained campaign.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
CAMPAIGN = ROOT / "harness/campaigns/cp2a-r1-as-20260819T043340Z"
SNAPSHOT_HARNESS = CAMPAIGN / "provenance/source-snapshot/harness"
EXPECTED_OUTPUTS = {
    "runs/30_evidences.csv": "runs/30_evidences.csv",
    "runs/30_evidences_statistics.csv": "runs/30_evidences_statistics.csv",
    "allowance_sensitivity.csv": "allowance_sensitivity.csv",
    "table_values.csv": "table_values.csv",
}


class ReplayError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ReplayError(f"missing or unsafe regular file: {path}")


@contextmanager
def command_line(*values: str):
    previous = sys.argv
    sys.argv = [previous[0], *values]
    try:
        yield
    finally:
        sys.argv = previous


def run_package_verifier(deep: bool) -> None:
    command = [sys.executable, "-I", str(ROOT / "verify_artifacts.py")]
    if deep:
        command.append("--deep")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise ReplayError("package verification failed; reanalysis was not run")


def load_exact_modules():
    expected = {
        "probe_harness.py",
        "render_public_table.py",
        "summarize_allowance_sensitivity.py",
        "summarize_harness_runs.py",
    }
    for name in expected:
        require_regular(SNAPSHOT_HARNESS / name)
    sys.path.insert(0, str(SNAPSHOT_HARNESS))
    try:
        summary = importlib.import_module("summarize_harness_runs")
        # The standalone verifier has independently checked the anchored plan,
        # result, manifests, raw records, source/tool bindings, image, and
        # amendment.  The archived aggregate gate cannot run on another host
        # because it also dereferences original-host absolute tool paths, so it
        # is substituted as a whole for this portable replay.
        summary.validate_campaign_archive = (
            lambda records, directory, pass_count: True
        )
        sensitivity = importlib.import_module("summarize_allowance_sensitivity")
        renderer = importlib.import_module("render_public_table")
    finally:
        sys.path.pop(0)
    for module in (summary, summary.probe_harness, sensitivity, renderer):
        source = Path(module.__file__).resolve()
        if source.parent != SNAPSHOT_HARNESS:
            raise ReplayError(f"analysis module did not load from snapshot: {source}")
    return summary, sensitivity, renderer


def copy_raw_records(destination: Path) -> None:
    source = CAMPAIGN / "runs"
    destination.mkdir(parents=True)
    records = sorted(
        source.glob("evidence*.json"),
        key=lambda path: int(path.stem.removeprefix("evidence")),
    )
    if len(records) != 31:
        raise ReplayError(f"expected 31 raw records, found {len(records)}")
    for record in records:
        require_regular(record)
        shutil.copy2(record, destination / record.name)


def recompute_attempt_analyses(summary, runs: Path) -> tuple[int, int]:
    """Recreate the 28 stored analysis predicates from raw attempt fields."""
    probe = summary.probe_harness
    records = summary.load_evidence(runs)
    check_count: int | None = None
    for record in records:
        attempt = record["attempt"]
        observations = attempt["observations"]
        schedule = observations["schedule"]
        baseline = observations["baseline"]
        final = observations["final"]
        events = observations["events"]
        clocks = observations["clock_brackets"]
        before_dump = observations["baseline_job_dump_before_query"]
        after_dump = observations["baseline_job_dump_after_query"]
        final_dump = observations["final_job_dump"]

        analysis = probe.check_result(
            schedule, baseline, final, events, clocks
        )
        analysis["checks"]["restricted_bucket_at_baseline_and_final"] = (
            observations["baseline_bucket"] == 45
            and observations["final_bucket"] == 45
        )
        before_modes = attempt["automatic_power_modes_before"]
        after_modes = attempt["automatic_power_modes_after"]
        analysis["checks"]["automatic_power_modes_stable"] = (
            before_modes == after_modes and before_modes["valid"]
        )
        analysis["checks"]["dynamic_membership_proven"] = (
            probe.dump_proves_membership(before_dump)
            and probe.dump_proves_membership(after_dump)
            and probe.dump_proves_membership(final_dump)
        )
        analysis["checks"]["same_jobstatus_identity"] = (
            probe.job_identity(before_dump) is not None
            and probe.job_identity(before_dump)
            == probe.job_identity(after_dump)
            == probe.job_identity(final_dump)
        )
        before_history = probe.constraint_history_signature(before_dump)
        after_history = probe.constraint_history_signature(after_dump)
        analysis["baseline_constraint_history_before_query"] = before_history
        analysis["baseline_constraint_history_after_query"] = after_history
        analysis["checks"]["baseline_history_quiescent_across_public_query"] = (
            before_history == after_history
        )
        history = probe.analyze_constraint_history(
            after_dump,
            final_dump,
            events,
            clocks,
            probe.stats(baseline).get(probe.APP_STANDBY, 0),
            probe.stats(final).get(probe.APP_STANDBY, 0),
        )
        analysis["per_job_constraint_history"] = history
        analysis["checks"].update(history["checks"])
        app_id = attempt["app_uid"] % 100_000
        analysis["checks"]["public_calls_from_installed_ordinary_app_uid"] = (
            10_000 <= app_id <= 19_999
            and all(
                value.get("uid") == attempt["app_uid"]
                for value in (schedule, baseline, final)
            )
        )
        analysis["checks"]["boot_preserved"] = (
            attempt["boot_id_after"] == attempt["boot_id_before"]
        )
        job_state = observations["final_job_state"].split()
        analysis["checks"]["job_state_waiting_not_active"] = (
            ("waiting" in job_state or "pending" in job_state)
            and "active" not in job_state
            and "ready" not in job_state
        )
        cleanup_checks = attempt["cleanup"]["checks"]
        cleanup_succeeded = bool(cleanup_checks) and all(cleanup_checks.values())
        analysis["checks"]["cleanup_succeeded"] = cleanup_succeeded
        analysis["passed"] = all(analysis["checks"].values())

        stored = attempt.get("analysis")
        if analysis != stored:
            differing = sorted(
                key
                for key in set(analysis) | set(stored or {})
                if analysis.get(key) != (stored or {}).get(key)
            )
            raise ReplayError(
                f"raw analysis does not reproduce for evidence{record['number']}: "
                f"{differing}"
            )
        current_count = len(analysis["checks"])
        if check_count is None:
            check_count = current_count
        elif current_count != check_count:
            raise ReplayError("attempt-level analysis-check count is inconsistent")
    if check_count is None:
        raise ReplayError("no attempt-level analyses were reproduced")
    return len(records), check_count


def compare_outputs(replay_root: Path) -> None:
    for generated_relative, retained_relative in EXPECTED_OUTPUTS.items():
        generated = replay_root / generated_relative
        retained = CAMPAIGN / retained_relative
        require_regular(generated)
        require_regular(retained)
        if generated.read_bytes() != retained.read_bytes():
            raise ReplayError(
                "regenerated output differs from sealed output: "
                f"{retained_relative} "
                f"({sha256(generated)} != {sha256(retained)})"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also extract and execute both component-bundle verifiers first",
    )
    args = parser.parse_args()
    run_package_verifier(args.deep)
    summary, sensitivity, renderer = load_exact_modules()
    with tempfile.TemporaryDirectory(prefix="lostboundaries-reanalysis-") as raw:
        replay_root = Path(raw)
        runs = replay_root / "runs"
        copy_raw_records(runs)
        recomputed_attempts, check_count = recompute_attempt_analyses(summary, runs)
        try:
            with command_line(
                "--input-dir", str(runs), "--pass-count", "30",
                "--require-campaign",
            ):
                if summary.main() != 0:
                    raise ReplayError("cohort/statistics regeneration failed")
            with command_line(
                "--input-dir", str(runs),
                "--output", str(replay_root / "allowance_sensitivity.csv"),
            ):
                if sensitivity.main() != 0:
                    raise ReplayError("allowance-sensitivity regeneration failed")
            with command_line(
                "--statistics", str(runs / "30_evidences_statistics.csv"),
                "--output", str(replay_root / "table_values.csv"),
            ):
                if renderer.main() != 0:
                    raise ReplayError("table-value regeneration failed")
        except (
            summary.SummaryError,
            sensitivity.SummaryError,
            renderer.RenderError,
        ) as error:
            raise ReplayError(f"archived analysis failed: {error}") from error
        compare_outputs(replay_root)
    print("PASS: all four derived campaign outputs reproduce byte-for-byte")
    print(
        f"  raw analysis predicates: {check_count} checks x "
        f"{recomputed_attempts} attempts"
    )
    print("  protocol-qualified cohort: 30")
    print("  compared outputs: 30_evidences.csv, statistics, sensitivity, table")
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    try:
        raise SystemExit(main())
    except (OSError, ReplayError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
