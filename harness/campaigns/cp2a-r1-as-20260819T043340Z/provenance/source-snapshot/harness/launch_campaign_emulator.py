#!/usr/bin/env python3
"""Launch, preflight, or stop the emulator bound to an immutable campaign."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time

import probe_harness


HARNESS_DIR = Path(__file__).resolve().parent
CAMPAIGNS_ROOT = (HARNESS_DIR / "campaigns").resolve()


class LaunchError(RuntimeError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise LaunchError(f"refusing to overwrite {path}") from error


def run(argv, *, environment=None, timeout=60, check=True):
    completed = subprocess.run(
        [str(value) for value in argv],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise LaunchError(
            f"command failed ({completed.returncode}): {argv!r}\n"
            f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
        )
    return completed


def load_plan(supplied_path):
    if supplied_path.is_symlink():
        raise LaunchError("campaign plan must not be a symlink")
    path = supplied_path.resolve()
    if (
        path.name != "campaign-plan.json"
        or path.parent.parent != CAMPAIGNS_ROOT
        or not path.is_file()
    ):
        raise LaunchError("campaign plan is outside the canonical campaign directory")
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LaunchError(f"invalid campaign plan: {error}") from error
    if (
        not isinstance(plan, dict)
        or plan.get("schema") != 1
        or plan.get("campaign_id") != path.parent.name
        or plan.get("selection_rule") != probe_harness.CAMPAIGN_SELECTION_RULE
    ):
        raise LaunchError("campaign plan has an invalid identity or design")
    return path, raw, plan


def planned_tools(plan):
    paths = plan.get("tool_paths")
    hashes = plan.get("tool_sha256")
    if not isinstance(paths, dict) or not isinstance(hashes, dict):
        raise LaunchError("campaign plan does not pin its tools")
    result = {}
    for name, supplied in paths.items():
        path = Path(supplied)
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != hashes.get(name)
        ):
            raise LaunchError(f"campaign tool changed: {name}")
        result[name] = path
    return result


def image_hashes(product_out):
    paths = sorted({
        *product_out.glob("*.img"),
        *product_out.glob("kernel-ranchu*"),
        *(
            product_out / relative
            for relative in probe_harness.IMAGE_PROVENANCE_RELATIVE_PATHS
        ),
    })
    return {
        path.relative_to(product_out).as_posix(): sha256_file(path)
        for path in paths if path.is_file() and not path.is_symlink()
    }


def adb_environment(adb):
    environment = os.environ.copy()
    environment["PATH"] = str(adb.parent) + os.pathsep + environment.get("PATH", "")
    environment.pop("ADB_SERVER_SOCKET", None)
    environment.pop("ANDROID_ADB_SERVER_PORT", None)
    return environment


def adb_server_identity(adb):
    listing = run(
        ["ss", "-ltnp", "sport = :5037"], check=False
    ).stdout
    pids = {int(value) for value in re.findall(r'\bpid=(\d+)\b', listing)}
    if len(pids) != 1:
        raise LaunchError(f"cannot identify one adb listener on port 5037: {listing!r}")
    pid = pids.pop()
    try:
        executable = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    except OSError as error:
        raise LaunchError(f"cannot resolve adb server executable: {error}") from error
    if executable != adb.resolve() or sha256_file(executable) != sha256_file(adb):
        raise LaunchError(f"adb server is not the planned executable: {executable}")
    return {
        "pid": pid,
        "executable": str(executable),
        "sha256": sha256_file(executable),
        "listener": listing.strip(),
    }


def start_pinned_adb(adb):
    environment = adb_environment(adb)
    run([adb, "kill-server"], environment=environment, check=False)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not run(
            ["ss", "-ltnp", "sport = :5037"], check=False
        ).stdout.strip().splitlines()[1:]:
            break
        time.sleep(0.1)
    run([adb, "start-server"], environment=environment)
    identity = adb_server_identity(adb)
    identity["version"] = run([adb, "version"], environment=environment).stdout.strip()
    return environment, identity


def adb(adb_path, environment, serial, *arguments, timeout=60, check=True):
    return run(
        [adb_path, "-s", serial, *arguments],
        environment=environment,
        timeout=timeout,
        check=check,
    )


def shell(adb_path, environment, serial, command, timeout=60):
    return adb(
        adb_path, environment, serial, "shell", command, timeout=timeout
    ).stdout.replace("\r\n", "\n").rstrip("\n")


def process_identity(pid):
    try:
        executable = Path(os.readlink(f"/proc/{pid}/exe")).resolve()
        raw_cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        stat_fields = Path(f"/proc/{pid}/stat").read_text().split()
    except OSError as error:
        raise LaunchError(f"cannot inspect emulator process {pid}: {error}") from error
    if not raw_cmdline or len(stat_fields) < 22:
        raise LaunchError(f"incomplete process identity for emulator PID {pid}")
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


def wait_for_qemu(process, qemu, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    expected_hash = sha256_file(qemu)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LaunchError(
                f"emulator launcher exited before QEMU handoff: {process.returncode}"
            )
        try:
            identity = process_identity(process.pid)
            last = identity
            if (
                Path(identity["executable"]) == qemu
                and identity["executable_sha256"] == expected_hash
            ):
                return identity
        except LaunchError as error:
            last = str(error)
        time.sleep(0.05)
    raise LaunchError(f"emulator did not hand off to planned QEMU: {last!r}")


def require_serial_and_ports_free(adb_path, environment, serial):
    devices = run([adb_path, "devices"], environment=environment).stdout
    if any(line.startswith(f"{serial}\t") for line in devices.splitlines()):
        raise LaunchError(f"planned emulator serial already exists: {serial}")
    port = int(serial.removeprefix("emulator-"))
    listeners = run(["ss", "-ltnH"], check=False).stdout
    for reserved in (port, port + 1):
        if re.search(rf":{reserved}\s", listeners):
            raise LaunchError(f"planned emulator port is already in use: {reserved}")


def terminate_spawned_process(process, initial_identity, qemu):
    if process.poll() is not None:
        return
    current = process_identity(process.pid)
    if (
        current["start_time_ticks"] != initial_identity["start_time_ticks"]
        or Path(current["executable"]) not in {
            Path(initial_identity["executable"]), qemu,
        }
        or os.getpgid(process.pid) != process.pid
    ):
        raise LaunchError("refusing to terminate an unverified emulator process")
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired as error:
        raise LaunchError("verified emulator process did not terminate") from error


def wait_for_ready(adb_path, environment, serial, timeout=420):
    adb(
        adb_path, environment, serial, "wait-for-device", timeout=timeout
    )
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        completed = adb(
            adb_path,
            environment,
            serial,
            "shell",
            "getprop sys.boot_completed",
            timeout=10,
            check=False,
        )
        last = (completed.returncode, completed.stdout, completed.stderr)
        if completed.returncode == 0 and completed.stdout.strip() == "1":
            return
        time.sleep(1)
    raise LaunchError(f"emulator did not complete boot: {last!r}")


def launch(plan_path, raw_plan, plan):
    root = plan_path.parent
    profile = plan.get("launch_profile")
    if not isinstance(profile, dict):
        raise LaunchError("campaign plan has no launch profile")
    tools = planned_tools(plan)
    adb_path = tools["adb"]
    emulator = tools["emulator"]
    qemu = tools["qemu"].resolve()
    serial = profile.get("serial")
    runtime_dir = Path(profile.get("runtime_dir", ""))
    if (
        not isinstance(serial, str)
        or not re.fullmatch(r"emulator-[0-9]+", serial)
        or not runtime_dir.is_absolute()
        or runtime_dir.exists()
        or runtime_dir.is_symlink()
        or profile.get("process_executable") != str(qemu)
    ):
        raise LaunchError("launch profile has an unsafe serial or runtime path")
    outputs = (
        root / "emulator.stdout.log",
        root / "emulator.stderr.log",
        root / "emulator.pid",
        root / "runtime-preflight.json",
        root / "runtime-preflight-error.json",
        root / "emulator-stop.json",
    )
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise LaunchError("campaign launch output already exists")
    if hashlib.sha256(plan_path.read_bytes()).digest() != hashlib.sha256(raw_plan).digest():
        raise LaunchError("campaign plan changed before launch")

    product_out = Path(plan["target"]["product_out"])
    if image_hashes(product_out) != plan.get("image_file_sha256"):
        raise LaunchError("planned build-image set or content changed before launch")
    for device_path, expected_hash in plan.get(
        "build_output_runtime_artifact_sha256", {}
    ).items():
        host_path = product_out / device_path.removeprefix("/")
        if (
            not host_path.is_file()
            or host_path.is_symlink()
            or sha256_file(host_path) != expected_hash
        ):
            raise LaunchError(f"planned runtime output changed: {device_path}")
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
            or sha256_file(path) != overlay_dump_hashes.get(name)
            for name, path in overlay_dump_paths.items()
        )
    ):
        raise LaunchError("static-overlay provenance dumps changed after planning")
    try:
        probe_harness.validate_emulator_zip_provenance(plan, root)
    except probe_harness.RunError as error:
        raise LaunchError(str(error)) from error

    runtime_dir.mkdir(mode=0o700)
    environment, server = start_pinned_adb(adb_path)
    require_serial_and_ports_free(adb_path, environment, serial)
    for key, value in profile.get("environment", {}).items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    environment["PATH"] = str(adb_path.parent) + os.pathsep + environment.get("PATH", "")
    stdout_path, stderr_path = outputs[:2]
    process = None
    initial_identity = None
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                [str(emulator), *profile.get("arguments", [])],
                env=environment,
                cwd=plan["target"]["aosp_root"],
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        initial_identity = process_identity(process.pid)
        qemu_identity = wait_for_qemu(process, qemu)
        publish_json(root / "emulator.pid", {
            **qemu_identity,
            "started_utc": utc_now(),
            "launcher_executable": str(emulator),
            "launcher_arguments": profile.get("arguments", []),
        })
        wait_for_ready(adb_path, environment, serial)
        if process.poll() is not None:
            raise LaunchError(f"emulator exited during boot with {process.returncode}")
        adb(
            adb_path, environment, serial,
            "shell", "am wait-for-broadcast-idle", timeout=120,
        )
        user_state = shell(
            adb_path, environment, serial, "am get-started-user-state 0"
        )
        if "RUNNING_UNLOCKED" not in user_state:
            raise LaunchError(f"user 0 is not unlocked: {user_state!r}")
        props = {
            key: shell(adb_path, environment, serial, f"getprop {key}")
            for key in (
                "ro.build.version.sdk", "ro.build.version.release",
                "ro.build.version.codename", "ro.build.version.preview_sdk",
                "ro.build.version.security_patch", "ro.build.version.incremental",
                "ro.build.fingerprint", "ro.build.id", "ro.build.type",
                "ro.build.user", "ro.build.tags", "ro.product.name",
                "sys.boot_completed",
            )
        }
        target = plan["target"]
        expected = {
            "ro.build.version.sdk": "37",
            "ro.build.version.release": "17",
            "ro.build.version.codename": "REL",
            "ro.build.version.preview_sdk": "0",
            "ro.build.version.security_patch": target["expected_security_patch"],
            "ro.build.version.incremental": probe_harness.EXPECTED_BUILD_INCREMENTAL,
            "ro.build.fingerprint": target["expected_fingerprint"],
            "ro.build.id": target["expected_build_id"],
            "ro.build.type": "userdebug",
            "ro.build.user": "lostboundaries",
            "ro.build.tags": "test-keys",
            "ro.product.name": "sdk_phone64_x86_64",
            "sys.boot_completed": "1",
        }
        if props != expected:
            raise LaunchError(f"runtime properties differ from the plan: {props!r}")
        runtime_hash_output = shell(
            adb_path,
            environment,
            serial,
            "sha256sum " + " ".join(probe_harness.RUNTIME_ARTIFACT_PATHS),
        )
        runtime_hashes = probe_harness.parse_sha256sum(runtime_hash_output)
        if runtime_hashes != plan["build_output_runtime_artifact_sha256"]:
            raise LaunchError("deployed runtime artifacts differ from build outputs")
        automatic_power_modes = {
            "resource_value": shell(
                adb_path, environment, serial,
                "cmd overlay lookup --user 0 android "
                + probe_harness.AUTO_POWER_RESOURCE,
            ).strip(),
            "overlay_list": shell(
                adb_path, environment, serial,
                "cmd overlay list --user 0 android",
            ),
            "app_standby_enabled": shell(
                adb_path, environment, serial,
                "dumpsys usagestats is-app-standby-enabled",
            ).strip(),
            "device_idle_enabled_all": shell(
                adb_path, environment, serial,
                "cmd deviceidle enabled all",
            ).strip(),
            "app_standby_setting": shell(
                adb_path, environment, serial,
                "settings get global app_standby_enabled",
            ).strip(),
            "adaptive_battery_setting": shell(
                adb_path, environment, serial,
                "settings get global adaptive_battery_management_enabled",
            ).strip(),
        }
        enabled_overlay = (
            f"[x] {probe_harness.STATIC_FRAMEWORK_OVERLAY_PACKAGE}"
        )
        automatic_power_modes["static_overlay_enabled"] = any(
            line.strip() == enabled_overlay
            for line in automatic_power_modes["overlay_list"].splitlines()
        )
        automatic_power_modes["fabricated_shell_overlay_absent"] = (
            "com.android.shell:" not in automatic_power_modes["overlay_list"]
        )
        automatic_power_modes["valid"] = (
            automatic_power_modes["resource_value"] == "true"
            and automatic_power_modes["app_standby_enabled"] == "true"
            and automatic_power_modes["device_idle_enabled_all"] == "1"
            and automatic_power_modes["app_standby_setting"] in {"null", "1"}
            and automatic_power_modes["adaptive_battery_setting"] in {"null", "1"}
            and automatic_power_modes["static_overlay_enabled"]
            and automatic_power_modes["fabricated_shell_overlay_absent"]
        )
        if not automatic_power_modes["valid"]:
            raise LaunchError(
                f"automatic-power-mode configuration is invalid: "
                f"{automatic_power_modes!r}"
            )
        jobscheduler = shell(adb_path, environment, serial, "dumpsys jobscheduler")
        flag_lines = [
            line.strip() for line in jobscheduler.splitlines()
            if "android.app.job.get_pending_job_reason_stats_api=" in line
        ]
        if flag_lines != ["android.app.job.get_pending_job_reason_stats_api=true"]:
            raise LaunchError(f"public stats flag is not enabled exactly once: {flag_lines}")
        package_listing = shell(
            adb_path, environment, serial,
            f"pm list packages {probe_harness.APP}",
        )
        if f"package:{probe_harness.APP}" in package_listing:
            raise LaunchError("probe package exists before the campaign")
        battery = shell(adb_path, environment, serial, "dumpsys battery")
        input_suspended = shell(
            adb_path, environment, serial,
            "getprop power.battery_input.suspended",
        ).strip().lower()
        if (
            probe_harness.BATTERY_OVERRIDE_MARKER in battery
            or input_suspended not in {"", "0", "false"}
            or re.search(r"^\s*Dock powered:\s*true\s*$", battery, re.MULTILINE)
        ):
            raise LaunchError("runtime begins with unsafe battery simulation state")
        controller_commands = {
            "battery_charging": shell(
                adb_path, environment, serial,
                "cmd jobscheduler get-battery-charging",
            ),
            "battery_not_low": shell(
                adb_path, environment, serial,
                "cmd jobscheduler get-battery-not-low",
            ),
        }
        preflight = {
            "schema": 1,
            "campaign_id": plan["campaign_id"],
            "campaign_plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
            "completed_utc": utc_now(),
            "emulator_pid": process.pid,
            "emulator_launcher_sha256": sha256_file(emulator),
            "emulator_process": process_identity(process.pid),
            "adb_server": adb_server_identity(adb_path),
            "device_properties": props,
            "boot_id": shell(
                adb_path, environment, serial,
                "cat /proc/sys/kernel/random/boot_id",
            ),
            "runtime_artifact_sha256": runtime_hashes,
            "automatic_power_modes": automatic_power_modes,
            "runtime_api_flag_lines": flag_lines,
            "probe_package_absent": True,
            "user_state": user_state,
            "controller_commands": controller_commands,
            "battery_input_suspended": input_suspended,
            "battery_override_absent": True,
            "initial_adb_server": server,
        }
        if hashlib.sha256(plan_path.read_bytes()).digest() != hashlib.sha256(raw_plan).digest():
            raise LaunchError("campaign plan changed during launch")
        publish_json(root / "runtime-preflight.json", preflight)
    except Exception as error:
        cleanup_error = None
        if process is not None and process.poll() is None:
            try:
                cleanup_identity = initial_identity or process_identity(process.pid)
                if Path(cleanup_identity["executable"]) not in {emulator, qemu}:
                    raise LaunchError(
                        "spawned process does not match the emulator toolchain"
                    )
                terminate_spawned_process(process, cleanup_identity, qemu)
            except Exception as cleanup_exception:
                cleanup_error = (
                    f"{cleanup_exception.__class__.__name__}: {cleanup_exception}"
                )
        publish_json(root / "runtime-preflight-error.json", {
            "schema": 1,
            "campaign_id": plan["campaign_id"],
            "failed_utc": utc_now(),
            "error": f"{error.__class__.__name__}: {error}",
            "cleanup_error": cleanup_error,
        })
        raise
    print(root / "runtime-preflight.json")


def stop(plan_path, raw_plan, plan):
    root = plan_path.parent
    tools = planned_tools(plan)
    adb_path = tools["adb"]
    qemu = tools["qemu"].resolve()
    pid_path = root / "emulator.pid"
    stop_path = root / "emulator-stop.json"
    if (
        stop_path.exists()
        or stop_path.is_symlink()
        or pid_path.is_symlink()
        or not pid_path.is_file()
    ):
        raise LaunchError("campaign emulator PID is missing or already stopped")
    pidfd = None
    try:
        pid_record = json.loads(pid_path.read_bytes())
        pid = int(pid_record["pid"])
        pidfd = os.pidfd_open(pid)
        current_identity = process_identity(pid)
    except (LaunchError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        if pidfd is not None:
            os.close(pidfd)
        raise LaunchError(f"cannot identify the campaign emulator: {error}") from error
    identity_keys = (
        "pid", "executable", "executable_sha256", "cmdline_sha256",
        "arguments", "start_time_ticks",
    )
    recorded_identity = {key: pid_record.get(key) for key in identity_keys}
    try:
        if (
            Path(current_identity["executable"]) != qemu
            or current_identity["executable_sha256"] != sha256_file(qemu)
            or current_identity != recorded_identity
        ):
            raise LaunchError("recorded PID is not the planned QEMU process")
        environment = adb_environment(adb_path)
        serial = plan["launch_profile"]["serial"]
        adb(adb_path, environment, serial, "emu", "kill", check=False)
        poller = select.poll()
        poller.register(pidfd, select.POLLIN)
        if not poller.poll(60_000):
            if process_identity(pid) != recorded_identity:
                raise LaunchError("emulator identity changed before fallback stop")
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            if not poller.poll(10_000):
                raise LaunchError("campaign emulator did not stop")
    finally:
        os.close(pidfd)
    publish_json(stop_path, {
        "schema": 1,
        "campaign_id": plan["campaign_id"],
        "campaign_plan_sha256": hashlib.sha256(raw_plan).hexdigest(),
        "emulator_pid": pid,
        "emulator_process": recorded_identity,
        "stopped_utc": utc_now(),
    })
    print(stop_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-plan", required=True)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    plan_path, raw_plan, plan = load_plan(
        Path(args.campaign_plan).expanduser()
    )
    if args.stop:
        stop(plan_path, raw_plan, plan)
    else:
        launch(plan_path, raw_plan, plan)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LaunchError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
