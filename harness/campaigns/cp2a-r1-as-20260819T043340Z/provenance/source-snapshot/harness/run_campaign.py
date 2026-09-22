#!/usr/bin/env python3
"""Run a campaign to a target independent of its headline findings."""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import probe_harness
from probe_harness import CAMPAIGN_SELECTION_RULE, IMAGE_PROVENANCE_RELATIVE_PATHS
from summarize_harness_runs import (
    failed_result_checks,
    protocol_qualified,
    qualification_failures,
    strict_pass,
)


HARNESS_DIR = Path(__file__).resolve().parent
REPO_DIR = HARNESS_DIR.parent
PROBE_HARNESS = HARNESS_DIR / "probe_harness.py"


class CampaignError(RuntimeError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_hashes(product_out):
    paths = sorted({
        *product_out.glob("*.img"),
        *product_out.glob("kernel-ranchu*"),
        *(
            product_out / relative
            for relative in IMAGE_PROVENANCE_RELATIVE_PATHS
        ),
    })
    return {
        path.relative_to(product_out).as_posix(): sha256_file(path)
        for path in paths if path.is_file() and not path.is_symlink()
    }


def adb_server(adb_path):
    completed = subprocess.run(
        ["ss", "-ltnp", "sport = :5037"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pids = {int(value) for value in re.findall(r"\bpid=(\d+)\b", completed.stdout)}
    if completed.returncode != 0 or len(pids) != 1:
        raise CampaignError("cannot identify one adb server on port 5037")
    pid = pids.pop()
    try:
        executable = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    except OSError as error:
        raise CampaignError(f"cannot inspect adb server: {error}") from error
    if executable != adb_path.resolve() or sha256_file(executable) != sha256_file(adb_path):
        raise CampaignError(f"adb server is not the planned executable: {executable}")
    return {"pid": pid, "executable": str(executable), "sha256": sha256_file(executable)}


def process_identity(pid):
    try:
        executable = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
        raw_cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        stat_fields = Path(f"/proc/{pid}/stat").read_text().split()
    except OSError as error:
        raise CampaignError(f"cannot inspect emulator process: {error}") from error
    if not raw_cmdline or len(stat_fields) < 22:
        raise CampaignError("emulator process identity is incomplete")
    return {
        "pid": pid,
        "executable": str(executable),
        "executable_sha256": sha256_file(executable),
        "cmdline_sha256": hashlib.sha256(raw_cmdline).hexdigest(),
        "arguments": [
            os.fsdecode(value)
            for value in raw_cmdline.split(b"\0")
            if value
        ],
        "start_time_ticks": int(stat_fields[21]),
    }


def publish_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise CampaignError(f"refusing to overwrite {path}") from error


def load_plan(path):
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CampaignError(f"invalid campaign plan: {error}") from error
    if not isinstance(plan, dict) or plan.get("schema") != 1:
        raise CampaignError("campaign plan must be a schema-1 object")
    target = plan.get("target")
    selection = plan.get("selection_rule")
    if not isinstance(target, dict) or not isinstance(selection, dict):
        raise CampaignError("campaign plan omits target or selection rule")
    if selection != CAMPAIGN_SELECTION_RULE:
        raise CampaignError("campaign plan does not contain the fixed selection rule")
    return raw, plan


def load_attempt(path):
    try:
        document = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CampaignError(f"invalid attempt record {path}: {error}") from error
    if (
        not isinstance(document, dict)
        or document.get("schema") != 1
        or document.get("experiment") != "public-api-controller-ranking"
        or not isinstance(document.get("attempts"), list)
        or len(document["attempts"]) != 1
    ):
        raise CampaignError(f"invalid attempt envelope: {path}")
    attempt = document["attempts"][0]
    if (
        not isinstance(attempt, dict)
        or attempt.get("schema") != 1
        or attempt.get("outcome") not in {"PASS", "FAIL", "ERROR"}
    ):
        raise CampaignError(f"invalid attempt object: {path}")
    return attempt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-plan", required=True)
    parser.add_argument(
        "--serial", default=os.environ.get("ANDROID_SERIAL", "emulator-5584")
    )
    args = parser.parse_args()

    supplied_plan_path = Path(args.campaign_plan).expanduser()
    if supplied_plan_path.is_symlink():
        raise CampaignError("campaign plan must not be a symlink")
    plan_path = supplied_plan_path.resolve()
    if plan_path.name != "campaign-plan.json":
        raise CampaignError("campaign plan must use its canonical filename")
    raw_plan, plan = load_plan(plan_path)
    plan_sha256 = sha256_bytes(raw_plan)
    campaign_root = plan_path.parent
    runs_dir = campaign_root / "runs"
    scratch = campaign_root / ".attempt-evidence.json"
    scratch_new = scratch.with_suffix(scratch.suffix + ".new")
    result_path = campaign_root / "campaign-result.json"
    runner_log_path = campaign_root / "runner.log"
    if any(path.exists() or path.is_symlink() for path in (
        runs_dir, scratch, scratch_new, result_path, runner_log_path
    )):
        raise CampaignError("campaign output already exists; refusing to overwrite it")

    lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / (
        "lostboundaries-public-campaign.lock"
    )
    lock_stream = lock_path.open("a+")
    try:
        fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise CampaignError("another public campaign is already running") from error

    target = plan["target"]
    launch_profile = plan.get("launch_profile")
    if (
        not isinstance(launch_profile, dict)
        or launch_profile.get("serial") != args.serial
    ):
        raise CampaignError("runner serial does not match the launch profile")
    tool_paths = plan.get("tool_paths")
    tool_sha256 = plan.get("tool_sha256")
    if not isinstance(tool_paths, dict) or not isinstance(
        tool_paths.get("adb"), str
    ) or not isinstance(tool_sha256, dict):
        raise CampaignError("campaign plan does not pin its toolchain")
    for name, supplied_path in tool_paths.items():
        path = Path(supplied_path)
        if not path.is_file() or sha256_file(path) != tool_sha256.get(name):
            raise CampaignError(f"campaign tool does not match the plan: {name}")
    snapshot_hashes = plan.get("source_snapshot_sha256")
    snapshot_root = campaign_root / "provenance/source-snapshot"
    if not isinstance(snapshot_hashes, dict) or not snapshot_hashes:
        raise CampaignError("campaign plan has no portable source snapshot")
    for relative, expected in snapshot_hashes.items():
        path = snapshot_root / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected
        ):
            raise CampaignError(f"campaign source snapshot changed: {relative}")
    overlay_dump_hashes = plan.get("static_framework_overlay_dump_sha256")
    overlay_dump_paths = {
        "badging": campaign_root / "provenance/static-overlay-badging.txt",
        "manifest": campaign_root / "provenance/static-overlay-manifest.txt",
        "resources": campaign_root / "provenance/static-overlay-resources.txt",
    }
    if (
        not isinstance(overlay_dump_hashes, dict)
        or set(overlay_dump_hashes) != set(overlay_dump_paths)
        or any(
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != overlay_dump_hashes.get(name)
            for name, path in overlay_dump_paths.items()
        )
    ):
        raise CampaignError("static-overlay provenance dumps changed after planning")
    try:
        probe_harness.validate_emulator_zip_provenance(plan, campaign_root)
    except probe_harness.RunError as error:
        raise CampaignError(str(error)) from error
    adb_path = Path(tool_paths["adb"])
    if not adb_path.is_file() or not os.access(adb_path, os.X_OK):
        raise CampaignError(f"campaign adb executable is unavailable: {adb_path}")
    python_path = Path(tool_paths.get("python", ""))
    if (
        not python_path.is_file()
        or not os.access(python_path, os.X_OK)
        or python_path.resolve() != Path(sys.executable).resolve()
    ):
        raise CampaignError("campaign runner does not use the planned Python")
    product_out = Path(target["product_out"])
    if image_hashes(product_out) != plan.get("image_file_sha256"):
        raise CampaignError("planned build-image set or content changed")
    for device_path, expected in plan.get(
        "build_output_runtime_artifact_sha256", {}
    ).items():
        path = product_out / device_path.removeprefix("/")
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != expected
        ):
            raise CampaignError(f"planned runtime output changed: {device_path}")
    preflight_path = campaign_root / "runtime-preflight.json"
    pid_path = campaign_root / "emulator.pid"
    if (
        not preflight_path.is_file()
        or preflight_path.is_symlink()
        or not pid_path.is_file()
        or pid_path.is_symlink()
    ):
        raise CampaignError("verified runtime preflight is missing")
    try:
        preflight = json.loads(preflight_path.read_bytes())
        pid_record = json.loads(pid_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CampaignError(f"invalid runtime preflight: {error}") from error
    if not isinstance(preflight, dict) or not isinstance(pid_record, dict):
        raise CampaignError("runtime preflight or emulator PID record is not an object")
    identity_keys = (
        "pid", "executable", "executable_sha256", "cmdline_sha256",
        "arguments", "start_time_ticks",
    )
    planned_process = {key: pid_record.get(key) for key in identity_keys}
    automatic_power_modes = preflight.get("automatic_power_modes")
    try:
        emulator_pid = int(pid_record["pid"])
    except (KeyError, TypeError, ValueError) as error:
        raise CampaignError(f"invalid emulator PID record: {error}") from error
    qemu_path = Path(tool_paths.get("qemu", "")).resolve()
    if (
        preflight.get("schema") != 1
        or preflight.get("campaign_id") != plan["campaign_id"]
        or preflight.get("campaign_plan_sha256") != plan_sha256
        or preflight.get("runtime_artifact_sha256")
        != plan.get("build_output_runtime_artifact_sha256")
        or preflight.get("probe_package_absent") is not True
        or preflight.get("battery_override_absent") is not True
        or not isinstance(automatic_power_modes, dict)
        or automatic_power_modes.get("valid") is not True
        or automatic_power_modes.get("resource_value") != "true"
        or automatic_power_modes.get("app_standby_enabled") != "true"
        or automatic_power_modes.get("device_idle_enabled_all") != "1"
        or automatic_power_modes.get("static_overlay_enabled") is not True
        or automatic_power_modes.get("fabricated_shell_overlay_absent") is not True
        or not isinstance(preflight.get("boot_id"), str)
        or preflight.get("emulator_pid") != emulator_pid
        or preflight.get("emulator_process") != planned_process
        or Path(planned_process.get("executable", "")) != qemu_path
        or planned_process.get("executable_sha256") != tool_sha256.get("qemu")
        or process_identity(emulator_pid) != planned_process
    ):
        raise CampaignError("runtime preflight does not match the campaign plan")
    initial_adb_server = adb_server(adb_path)
    selection = plan["selection_rule"]
    qualification_target = selection["qualification_target"]
    max_attempts = selection["max_attempts"]
    runs_dir.mkdir()
    started_utc = utc_now()
    attempts = []
    qualified_count = 0
    strict_pass_count = 0
    campaign_boot_id = preflight["boot_id"]
    campaign_error = None

    with runner_log_path.open("xb") as runner_log:
        def report(message):
            line = f"{utc_now()} {message}\n"
            sys.stdout.write(line)
            sys.stdout.flush()
            runner_log.write(line.encode())
            runner_log.flush()
            os.fsync(runner_log.fileno())

        try:
            report(
                f"campaign {plan['campaign_id']} started; "
                f"qualification_target={qualification_target}, "
                f"max_attempts={max_attempts}, "
                "headline_result_based_stopping=false"
            )
            for number in range(1, max_attempts + 1):
                if sha256_bytes(plan_path.read_bytes()) != plan_sha256:
                    raise CampaignError("campaign plan changed before an attempt")
                if adb_server(adb_path)["sha256"] != initial_adb_server["sha256"]:
                    raise CampaignError("adb server changed during the campaign")
                if process_identity(emulator_pid) != planned_process:
                    raise CampaignError("emulator process changed during the campaign")
                command = [
                    str(python_path),
                    "-B",
                    str(PROBE_HARNESS),
                    "--serial", args.serial,
                    "--expected-fingerprint", target["expected_fingerprint"],
                    "--expected-build-id", target["expected_build_id"],
                    "--expected-security-patch", target["expected_security_patch"],
                    "--evidence", str(scratch),
                    "--aosp-root", target["aosp_root"],
                    "--aosp-product-out", target["product_out"],
                    "--campaign-plan", str(plan_path),
                ]
                report(
                    f"attempt {number}/{max_attempts} starting "
                    f"({qualified_count}/{qualification_target} qualified; "
                    f"{strict_pass_count} headline passes)"
                )
                environment = os.environ.copy()
                environment["ANDROID_SERIAL"] = args.serial
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                environment["PATH"] = (
                    str(adb_path.parent)
                    + os.pathsep
                    + environment.get("PATH", "")
                )
                environment.pop("ADB_SERVER_SOCKET", None)
                environment.pop("ANDROID_ADB_SERVER_PORT", None)
                completed = subprocess.run(
                    command,
                    cwd=REPO_DIR,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if scratch_new.exists():
                    raise CampaignError("harness left an incomplete attempt record")
                if not scratch.is_file() or scratch.stat().st_size == 0:
                    raise CampaignError("harness produced no attempt record")
                attempt = load_attempt(scratch)
                campaign = attempt.get("campaign", {})
                outcome = attempt.get("outcome")
                if (
                    attempt.get("serial") != args.serial
                    or campaign.get("id") != plan["campaign_id"]
                    or campaign.get("plan_sha256") != plan_sha256
                    or campaign.get("plan_sha256_after") != plan_sha256
                    or campaign.get("plan_unchanged") is not True
                    or completed.returncode
                    != ({"PASS": 0, "FAIL": 1, "ERROR": 1}[outcome])
                ):
                    raise CampaignError("attempt result disagrees with its invocation")
                target_path = runs_dir / f"evidence{number}.json"
                if target_path.exists() or target_path.is_symlink():
                    raise CampaignError(f"refusing existing attempt: {target_path}")
                os.replace(scratch, target_path)
                qualified = protocol_qualified(attempt)
                passed = strict_pass(attempt)
                failed_qualification = qualification_failures(attempt)
                failed_results = failed_result_checks(attempt)
                boot_before = attempt.get("boot_id_before")
                boot_after = attempt.get("boot_id_after")
                if (
                    boot_before != campaign_boot_id
                    or boot_after != campaign_boot_id
                ):
                    raise CampaignError("attempt does not share the campaign boot")
                attempts.append(
                    {
                        "number": number,
                        "outcome": outcome,
                        "protocol_qualified": qualified,
                        "strict_pass": passed,
                        "failed_qualification_checks": failed_qualification,
                        "failed_result_checks": failed_results,
                        "record": target_path.relative_to(campaign_root).as_posix(),
                        "record_sha256": sha256_bytes(target_path.read_bytes()),
                        "harness_exit_code": completed.returncode,
                    }
                )
                report(
                    f"attempt {number} outcome={outcome}, "
                    f"protocol_qualified={qualified}, strict_pass={passed}; "
                    f"stdout={completed.stdout.strip()!r}, "
                    f"stderr={completed.stderr.strip()!r}"
                )
                cleanup = attempt.get("cleanup")
                if not isinstance(cleanup, dict) or cleanup.get("succeeded") is not True:
                    raise CampaignError("attempt cleanup did not succeed")
                if outcome == "ERROR":
                    raise CampaignError("harness reported an execution error")
                if qualified:
                    qualified_count += 1
                if passed:
                    strict_pass_count += 1
                if qualified_count == qualification_target:
                    break
            if qualified_count != qualification_target:
                raise CampaignError(
                    f"only {qualified_count}/{qualification_target} protocol-qualified "
                    f"attempts after the fixed maximum of {max_attempts}"
                )
            if sha256_bytes(plan_path.read_bytes()) != plan_sha256:
                raise CampaignError("campaign plan changed after acquisition")
            report(
                f"qualification target reached after {len(attempts)} attempts; "
                f"strict_passes={strict_pass_count}"
            )
        except Exception as error:
            campaign_error = f"{error.__class__.__name__}: {error}"
            report(f"campaign stopped: {campaign_error}")

    result = {
        "schema": 1,
        "campaign_id": plan["campaign_id"],
        "campaign_plan_sha256": plan_sha256,
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "qualification_target": qualification_target,
        "max_attempts": max_attempts,
        "protocol_qualified_count": qualified_count,
        "strict_pass_count": strict_pass_count,
        "boot_id": campaign_boot_id,
        "adb_server": initial_adb_server,
        "attempt_count": len(attempts),
        "completed": (
            campaign_error is None
            and qualified_count == qualification_target
            and len(attempts) <= max_attempts
        ),
        "error": campaign_error,
        "attempts": attempts,
    }
    publish_json(result_path, result)
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CampaignError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
