#!/usr/bin/env python3
"""Verify and make a completed campaign bundle tamper-evident and read-only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from run_campaign import image_hashes
from summarize_harness_runs import load_evidence, validate_campaign_archive


class SealError(RuntimeError):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", required=True)
    args = parser.parse_args()
    supplied_root = Path(args.campaign_root).expanduser()
    if supplied_root.is_symlink():
        raise SealError(f"campaign root must not be a symlink: {supplied_root}")
    root = supplied_root.resolve()
    campaigns_root = (Path(__file__).resolve().parent / "campaigns").resolve()
    if (
        supplied_root.absolute() != root
        or not root.is_dir()
        or root.parent != campaigns_root
        or re.fullmatch(r"cp2a-r1-as-[0-9]{8}T[0-9]{6}Z", root.name) is None
    ):
        raise SealError(f"unsafe or missing campaign root: {root}")
    seal_path = root / "SHA256SUMS"
    if seal_path.exists() or seal_path.is_symlink():
        raise SealError(f"refusing existing seal: {seal_path}")
    plan_path = root / "campaign-plan.json"
    try:
        raw_plan = plan_path.read_bytes()
        plan = json.loads(raw_plan)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SealError(f"invalid campaign plan: {error}") from error
    records = load_evidence(root / "runs")
    if not validate_campaign_archive(records, root / "runs", 30):
        raise SealError("archive is not a completed immutable campaign")
    required = (
        root / "runs/30_evidences.csv",
        root / "runs/30_evidences_statistics.csv",
        root / "allowance_sensitivity.csv",
        root / "table_values.csv",
        root / "campaign-result.json",
        root / "runner.log",
        root / "emulator.stdout.log",
        root / "emulator.stderr.log",
        root / "runtime-preflight.json",
        root / "emulator.pid",
        root / "emulator-stop.json",
    )
    missing = [
        str(path) for path in required
        if not path.is_file() or path.is_symlink()
    ]
    if missing:
        raise SealError(f"campaign outputs are missing: {missing}")
    try:
        pid_record = json.loads((root / "emulator.pid").read_bytes())
        stop_record = json.loads((root / "emulator-stop.json").read_bytes())
        preflight = json.loads((root / "runtime-preflight.json").read_bytes())
        emulator_pid = int(pid_record["pid"])
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        raise SealError(f"invalid emulator lifecycle record: {error}") from error
    plan_sha256 = hashlib.sha256(raw_plan).hexdigest()
    identity_keys = (
        "pid", "executable", "executable_sha256", "cmdline_sha256",
        "arguments", "start_time_ticks",
    )
    pid_identity = {key: pid_record.get(key) for key in identity_keys}
    automatic_power_modes = preflight.get("automatic_power_modes")
    qemu = Path(plan.get("tool_paths", {}).get("qemu", "")).resolve()
    if (
        stop_record.get("schema") != 1
        or stop_record.get("campaign_id") != plan.get("campaign_id")
        or stop_record.get("campaign_plan_sha256") != plan_sha256
        or stop_record.get("emulator_pid") != emulator_pid
        or stop_record.get("emulator_process") != pid_identity
        or preflight.get("emulator_pid") != emulator_pid
        or preflight.get("emulator_process") != pid_identity
        or not isinstance(automatic_power_modes, dict)
        or automatic_power_modes.get("valid") is not True
        or automatic_power_modes.get("resource_value") != "true"
        or automatic_power_modes.get("app_standby_enabled") != "true"
        or automatic_power_modes.get("device_idle_enabled_all") != "1"
        or automatic_power_modes.get("static_overlay_enabled") is not True
        or automatic_power_modes.get("fabricated_shell_overlay_absent") is not True
        or Path(pid_identity.get("executable", "")) != qemu
        or pid_identity.get("executable_sha256")
        != plan.get("tool_sha256", {}).get("qemu")
    ):
        raise SealError("emulator lifecycle records do not describe one process")
    if Path(f"/proc/{emulator_pid}").exists():
        try:
            live_start = int(
                Path(f"/proc/{emulator_pid}/stat").read_text().split()[21]
            )
        except (OSError, ValueError, IndexError) as error:
            raise SealError(f"cannot inspect reused emulator PID: {error}") from error
        if live_start == pid_identity["start_time_ticks"]:
            raise SealError("campaign emulator is still running")
    product_out = Path(plan["target"]["product_out"])
    if image_hashes(product_out) != plan.get("image_file_sha256"):
        raise SealError("build-image set or content changed after plan creation")
    for device_path, expected in plan.get(
        "build_output_runtime_artifact_sha256", {}
    ).items():
        path = product_out / device_path.removeprefix("/")
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise SealError(f"runtime build output changed: {device_path}")
    snapshot_root = root / "provenance/source-snapshot"
    snapshot_hashes = plan.get("source_snapshot_sha256")
    if not isinstance(snapshot_hashes, dict) or not snapshot_hashes:
        raise SealError("campaign plan omits its portable source snapshot")
    for relative, expected in snapshot_hashes.items():
        path = snapshot_root / relative
        if not path.is_file() or path.is_symlink() or sha256(path) != expected:
            raise SealError(f"source snapshot changed: {relative}")
    overlay_dump_hashes = plan.get("static_framework_overlay_dump_sha256")
    overlay_dump_paths = {
        "badging": root / "provenance/static-overlay-badging.txt",
        "manifest": root / "provenance/static-overlay-manifest.txt",
        "resources": root / "provenance/static-overlay-resources.txt",
    }
    if (
        not isinstance(overlay_dump_hashes, dict)
        or set(overlay_dump_hashes) != set(overlay_dump_paths)
        or any(
            not path.is_file()
            or path.is_symlink()
            or sha256(path) != overlay_dump_hashes.get(name)
            for name, path in overlay_dump_paths.items()
        )
    ):
        raise SealError("static-overlay provenance dumps changed after planning")

    with tempfile.TemporaryDirectory(prefix="lostboundaries-seal-") as temporary:
        regenerated_root = Path(temporary) / root.name
        regenerated_runs = regenerated_root / "runs"
        regenerated_runs.mkdir(parents=True)
        shutil.copy2(root / "campaign-plan.json", regenerated_root)
        shutil.copy2(root / "campaign-result.json", regenerated_root)
        shutil.copy2(root / "runtime-preflight.json", regenerated_root)
        for record in records:
            shutil.copy2(record["path"], regenerated_runs / record["path"].name)
        python = Path(plan["tool_paths"]["python"])
        commands = (
            [
                python, "-B", plan["tool_paths"]["summarizer"],
                "--input-dir", regenerated_runs,
                "--pass-count", "30", "--require-campaign",
            ],
            [
                python, "-B", plan["tool_paths"]["sensitivity_summarizer"],
                "--input-dir", regenerated_runs,
                "--output", regenerated_root / "allowance_sensitivity.csv",
            ],
            [
                python, "-B", plan["tool_paths"]["table_renderer"],
                "--statistics", regenerated_runs / "30_evidences_statistics.csv",
                "--output", regenerated_root / "table_values.csv",
            ],
        )
        for command in commands:
            completed = subprocess.run(
                [str(value) for value in command],
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode != 0:
                raise SealError(
                    f"cannot regenerate derived evidence: {completed.stderr}"
                )
        comparisons = (
            (root / "runs/30_evidences.csv", regenerated_runs / "30_evidences.csv"),
            (
                root / "runs/30_evidences_statistics.csv",
                regenerated_runs / "30_evidences_statistics.csv",
            ),
            (
                root / "allowance_sensitivity.csv",
                regenerated_root / "allowance_sensitivity.csv",
            ),
            (root / "table_values.csv", regenerated_root / "table_values.csv"),
        )
        for retained, regenerated in comparisons:
            if retained.read_bytes() != regenerated.read_bytes():
                raise SealError(f"derived output is not reproducible: {retained}")
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path != seal_path
    )
    symlinks = [path for path in root.rglob("*") if path.is_symlink()]
    if symlinks:
        raise SealError(f"campaign archive contains symlinks: {symlinks}")
    lines = [
        f"{sha256(path)}  {path.relative_to(root).as_posix()}\n"
        for path in files
    ]
    try:
        with seal_path.open("x") as stream:
            stream.writelines(lines)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise SealError(f"refusing existing seal: {seal_path}") from error
    for path in [*files, seal_path]:
        path.chmod(0o444)
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), reverse=True
    ):
        directory.chmod(0o555)
    root.chmod(0o555)
    print(f"Sealed {root} ({len(files) + 1} files)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SealError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
