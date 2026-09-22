#!/usr/bin/env python3
# This is a single-run, self-checking Android 17 (API 37) experiment for the
# reason-key boundary loss identified in JobStatus: it builds and installs an ordinary app
# that requests no privileged permissions, puts that app in the Restricted standby bucket,
# shell-injects overlapping charging and battery-not-low states while the production
# BatteryService and JobScheduler controller code executes, calls the public
# getPendingJobReasonStats() API from the scheduling app's UID, and has the app rank the
# complete returned map. It writes one transient evidence.json record containing the raw
# command, state, timing, app, and cleanup observations and independently checks conservative job-age,
# union, contributor-additive, and characterized implementation bounds. A PASS establishes,
# on the recorded image and shell-injected trace, that APP_STANDBY exceeded the maximum
# enqueue-to-query age of the same pending job and became the app's unique top-ranked reason
# even though both interval references rank minimum latency above it; it does not establish
# naturally occurring frequency, OEM preservation, API adoption, or repair correctness. The
# run requires exclusive access to its dedicated emulator because BatteryService has no
# atomic ownership token for shell state overrides.


# Focal controller trace (C = charging, B = battery-not-low): TT -> FT -> FF ->
# FT -> TT. The equivalent mutations are `adb -s SERIAL shell cmd battery ...`;
# Capture.shell() supplies the adb/serial prefix, event() brackets each observed transition,
# and check_result() derives and validates the interval bounds. evidence.json is the complete
# current-run scratch record, not an append-only archive; the campaign runner moves each
# finished record into its non-overwriting campaign run directory. Cleanup cancels/uninstalls
# the dedicated probe and exits only the BatteryService override created by this run, then
# verifies the two relevant JobScheduler controller booleans against their pre-run values.

import argparse
import base64
import datetime as dt
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HARNESS_DIR = Path(__file__).resolve().parent
REPO_DIR = HARNESS_DIR.parent
PROBE_APP_DIR = REPO_DIR / "probe-app"
DEFAULT_AOSP_ROOT = REPO_DIR.parent / "aosp-android17"
DEFAULT_PRODUCT_OUT = (
    DEFAULT_AOSP_ROOT / "out-cp2a-appstandby/target/product/emu64x"
)
APP = "org.lostboundaries.probe"
ACTION = APP + ".COMMAND"
RECEIVER = APP + "/.ProbeReceiver"
JOB_ID = 17001
APP_STANDBY = 2
MINIMUM_LATENCY = 9
EXPECTED_SDK = "37"
EXPECTED_REVISION = "94b4c163b7dfe5ce3607f7bb8456f9573f7de57d"
DEFAULT_EXPECTED_FINGERPRINT = (
    "Android/sdk_phone64_x86_64/emu64x:17/CP2A.260605.016/"
    "lostboundaries-r1-as:userdebug/test-keys"
)
DEFAULT_EXPECTED_BUILD_ID = "CP2A.260605.016"
DEFAULT_EXPECTED_SECURITY_PATCH = "2026-06-05"
EXPECTED_BUILD_INCREMENTAL = "lostboundaries-r1-as"
EXPECTED_BUILD_GOAL = "emu_img_zip"
EXPECTED_BUILD_GOAL_ARTIFACT = "sdk-repo-linux-system-images.zip"
IMAGE_PROVENANCE_RELATIVE_PATHS = (
    EXPECTED_BUILD_GOAL_ARTIFACT,
    "build_fingerprint-sdk_phone64_x86_64.txt",
    "system/build.prop",
    "VerifiedBootParams.textproto",
    "advancedFeatures.ini",
    "kernel_cmdline.txt",
)
EMU_IMG_ZIP_SOURCE_BINDINGS = {
    "x86_64/system.img": "system-qemu.img",
    "x86_64/ramdisk.img": "ramdisk-qemu.img",
    "x86_64/vendor.img": "vendor-qemu.img",
    "x86_64/kernel-ranchu": "kernel-ranchu",
    "x86_64/encryptionkey.img": "encryptionkey.img",
    "x86_64/build.prop": "system/build.prop",
    "x86_64/VerifiedBootParams.textproto": "VerifiedBootParams.textproto",
    "x86_64/advancedFeatures.ini": "advancedFeatures.ini",
    "x86_64/kernel_cmdline.txt": "kernel_cmdline.txt",
}
EXPECTED_DYNAMIC_PARTITIONS_SIZE = 2 * 1024 * 1024 * 1024
EXPECTED_SUPER_PARTITION_SIZE = EXPECTED_DYNAMIC_PARTITIONS_SIZE + 8 * 1024 * 1024
EXPECTED_REPO_MANIFEST_SHA256 = (
    "bb9554ce399669698c26f022500aef7a2d410e2d4e5619ce80f016de4ee7a15f"
)
EXPECTED_BASE_REPO_MANIFEST_SHA256 = (
    "aed6cab4ac2995410b9b9feed2c20629b2b5db42d297ca109232bcdd56c923f1"
)
EXPECTED_GOLDFISH_BASE_REVISION = "296e55aa0244e8929e393e00e34471fef2a5d662"
EXPECTED_GOLDFISH_REVISION = "9e403c2080309c4c549dfd0dad19bfbb17b32afc"
GOLDFISH_OVERLAY_SOURCE_PATH = (
    "phone/overlay/frameworks/base/core/res/res/values/"
    "lostboundaries_app_standby.xml"
)
EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256 = (
    "1d3b86eb1f8d5431232d089b412ef51235c31b2c65faf2cfb7527ea1d31674e9"
)
EXPECTED_GOLDFISH_DIFF_SHA256 = (
    "99d6717836befee92eb5bb7759f6426138bdc73ba39c903417c6b897f17fadf7"
)
BASE_GOLDFISH_MANIFEST_LINE = (
    '  <project name="device/generic/goldfish" '
    'revision="296e55aa0244e8929e393e00e34471fef2a5d662" groups="pdk"/>\n'
)
CONFIGURED_GOLDFISH_MANIFEST_LINE = (
    '  <project name="device/generic/goldfish" '
    'revision="9e403c2080309c4c549dfd0dad19bfbb17b32afc" '
    'upstream="296e55aa0244e8929e393e00e34471fef2a5d662" '
    'dest-branch="296e55aa0244e8929e393e00e34471fef2a5d662" groups="pdk"/>\n'
)
EXPECTED_JOB_STATUS_SHA256 = (
    "2a8fbe2a30f1967d677ebc9303446bd6833cb280bab11f3190a2bdb87450e7ba"
)
PRODUCTION_SOURCE_PATHS = (
    "apex/jobscheduler/framework/java/android/app/JobSchedulerImpl.java",
    "apex/jobscheduler/service/java/com/android/server/job/JobSchedulerService.java",
    "apex/jobscheduler/service/java/com/android/server/job/controllers/BatteryController.java",
    "apex/jobscheduler/service/java/com/android/server/job/controllers/JobStatus.java",
)
STATIC_FRAMEWORK_OVERLAY_PATH = (
    "/vendor/overlay/"
    "framework-res__sdk_phone64_x86_64__auto_generated_rro_vendor.apk"
)
RUNTIME_ARTIFACT_PATHS = (
    "/system/framework/framework-res.apk",
    "/system/framework/framework.jar",
    "/system/framework/services.jar",
    STATIC_FRAMEWORK_OVERLAY_PATH,
    "/apex/com.android.scheduling/javalib/framework-scheduling.jar",
    "/apex/com.android.scheduling/javalib/service-scheduling.jar",
)
AUTO_POWER_RESOURCE = "android:bool/config_enableAutoPowerModes"
STATIC_FRAMEWORK_OVERLAY_PACKAGE = "android.auto_generated_rro_vendor__"
PRE_AGE_SECONDS = 30
INNER_GAP_SECONDS = 2
OVERLAP_SECONDS = 15
FINAL_GAP_SECONDS = 2
TOLERANCE_MS = 500
CLOCK_TOLERANCE_MS = 20
COMMAND_TIMEOUT_SECONDS = 60
BUILD_TIMEOUT_SECONDS = 600
BATTERY_OVERRIDE_MARKER = "(UPDATES STOPPED -- use 'reset' to restart)"
CONSTRAINT_HISTORY_CAPACITY = 10
DEFAULT_EVIDENCE = HARNESS_DIR / "evidence.json"

EVENT_SPECS = (
    (
        "charging_unsatisfied",
        {"charging": True, "battery_not_low": True},
        {"charging": False, "battery_not_low": True},
        2,
    ),
    (
        "battery_not_low_unsatisfied",
        {"charging": False, "battery_not_low": True},
        {"charging": False, "battery_not_low": False},
        0,
    ),
    (
        "battery_not_low_satisfied",
        {"charging": False, "battery_not_low": False},
        {"charging": False, "battery_not_low": True},
        2,
    ),
    (
        "charging_satisfied",
        {"charging": False, "battery_not_low": True},
        {"charging": True, "battery_not_low": True},
        3,
    ),
)

CAMPAIGN_QUALIFICATION_CHECKS = (
    "automatic_power_modes_stable",
    "app_elapsed_intervals_enclosed_by_uptime_brackets",
    "app_ranker_matches_host_recomputation",
    "baseline_focal_constraints_satisfied",
    "baseline_history_quiescent_across_public_query",
    "baseline_shared_key_present_zero",
    "boot_preserved",
    "callback_count_zero_at_final_query",
    "cleanup_succeeded",
    "dynamic_membership_proven",
    "event_protocol_structurally_valid",
    "job_pending_at_schedule_baseline_and_final",
    "job_state_waiting_not_active",
    "per_job_history_exact_protocol_extension",
    "per_job_transition_times_bound_to_controller_events",
    "public_calls_from_installed_ordinary_app_uid",
    "restricted_bucket_at_baseline_and_final",
    "same_jobstatus_identity",
    "schedule_baseline_events_query_timeline_proven",
    "schedule_contract_proven",
)

CAMPAIGN_SELECTION_RULE = {
    "qualification_target": 30,
    "max_attempts": 40,
    "retain_all_attempts": True,
    "headline_result_based_stopping": False,
    "abort_on_execution_error": True,
    "abort_on_cleanup_failure": True,
}


class RunError(RuntimeError):
    pass


def validate_configured_repo_manifest(manifest):
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    if digest != EXPECTED_REPO_MANIFEST_SHA256:
        raise RunError(
            f"resolved source manifest SHA-256 is {digest}, "
            f"expected {EXPECTED_REPO_MANIFEST_SHA256}"
        )
    if (
        manifest.count(CONFIGURED_GOLDFISH_MANIFEST_LINE) != 1
        or BASE_GOLDFISH_MANIFEST_LINE in manifest
    ):
        raise RunError("configured manifest does not contain the exact goldfish delta")
    baseline = manifest.replace(
        CONFIGURED_GOLDFISH_MANIFEST_LINE,
        BASE_GOLDFISH_MANIFEST_LINE,
        1,
    )
    baseline_digest = hashlib.sha256(baseline.encode()).hexdigest()
    if baseline_digest != EXPECTED_BASE_REPO_MANIFEST_SHA256:
        raise RunError(
            "normalizing the goldfish configuration does not reproduce the "
            "pinned android-17.0.0_r1 manifest"
        )
    return digest


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sum(output):
    parsed = {}
    for line in output.splitlines():
        fields = line.split(None, 1)
        if len(fields) != 2 or re.fullmatch(r"[0-9a-f]{64}", fields[0]) is None:
            raise RunError(f"invalid sha256sum output: {line!r}")
        path = fields[1].strip()
        if path in parsed:
            raise RunError(f"duplicate sha256sum path: {path}")
        parsed[path] = fields[0]
    return parsed


def validate_emulator_zip_provenance(plan, campaign_root):
    member_hashes = plan.get("build_goal_zip_member_sha256")
    source_bindings = plan.get("build_goal_zip_source_bindings")
    if (
        not isinstance(member_hashes, dict)
        or not member_hashes
        or any(
            not isinstance(member, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest or "") is None
            for member, digest in member_hashes.items()
        )
        or source_bindings != EMU_IMG_ZIP_SOURCE_BINDINGS
        or not set(source_bindings).issubset(member_hashes)
    ):
        raise RunError("campaign plan does not bind the emulator package members")
    members_path = campaign_root / "provenance/emu-img-zip-members.sha256"
    bindings_path = (
        campaign_root / "provenance/emu-img-zip-source-bindings.json"
    )
    if (
        not members_path.is_file()
        or members_path.is_symlink()
        or not bindings_path.is_file()
        or bindings_path.is_symlink()
    ):
        raise RunError("emulator package provenance files are missing or unsafe")
    try:
        archived_members = parse_sha256sum(members_path.read_text())
        archived_bindings = json.loads(bindings_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunError(f"invalid emulator package provenance: {error}") from error
    if archived_members != member_hashes or archived_bindings != source_bindings:
        raise RunError("emulator package provenance files differ from the plan")


def automatic_power_mode_state(capture):
    state = {
        "resource_value": capture.shell(
            "cmd", "overlay", "lookup", "--user", "0",
            "android", AUTO_POWER_RESOURCE,
        ).strip(),
        "overlay_list": capture.shell(
            "cmd", "overlay", "list", "--user", "0", "android"
        ),
        "app_standby_enabled": capture.shell(
            "dumpsys", "usagestats", "is-app-standby-enabled"
        ).strip(),
        "device_idle_enabled_all": capture.shell(
            "cmd", "deviceidle", "enabled", "all"
        ).strip(),
        "app_standby_setting": capture.shell(
            "settings", "get", "global", "app_standby_enabled"
        ).strip(),
        "adaptive_battery_setting": capture.shell(
            "settings", "get", "global", "adaptive_battery_management_enabled"
        ).strip(),
    }
    enabled_overlay = f"[x] {STATIC_FRAMEWORK_OVERLAY_PACKAGE}"
    state["static_overlay_enabled"] = any(
        line.strip() == enabled_overlay for line in state["overlay_list"].splitlines()
    )
    state["fabricated_shell_overlay_absent"] = (
        "com.android.shell:" not in state["overlay_list"]
    )
    state["valid"] = (
        state["resource_value"] == "true"
        and state["app_standby_enabled"] == "true"
        and state["device_idle_enabled_all"] == "1"
        and state["app_standby_setting"] in {"null", "1"}
        and state["adaptive_battery_setting"] in {"null", "1"}
        and state["static_overlay_enabled"]
        and state["fabricated_shell_overlay_absent"]
    )
    if not state["valid"]:
        raise RunError(f"automatic-power-mode configuration is invalid: {state!r}")
    return state


def load_campaign_plan(path, expected_fingerprint, expected_build_id,
                       expected_security_patch, aosp_root, product_out,
                       serial):
    raw = path.read_bytes()
    try:
        plan = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunError(f"invalid campaign plan {path}: {error}") from error
    if not isinstance(plan, dict) or plan.get("schema") != 1:
        raise RunError("campaign plan must be a schema-1 JSON object")
    target = plan.get("target")
    selection = plan.get("selection_rule")
    expected_target = {
        "base_aosp_tag": "android-17.0.0_r1",
        "release_config": "cp2a",
        "target_product": "sdk_phone64_x86_64",
        "target_build_variant": "userdebug",
        "build_goal": EXPECTED_BUILD_GOAL,
        "build_goal_artifact": EXPECTED_BUILD_GOAL_ARTIFACT,
        "emulator_dynamic_partitions_size": EXPECTED_DYNAMIC_PARTITIONS_SIZE,
        "super_partition_size": EXPECTED_SUPER_PARTITION_SIZE,
        "expected_fingerprint": expected_fingerprint,
        "expected_build_id": expected_build_id,
        "expected_security_patch": expected_security_patch,
        "frameworks_base_revision": EXPECTED_REVISION,
        "resolved_manifest_sha256": EXPECTED_REPO_MANIFEST_SHA256,
        "base_resolved_manifest_sha256": EXPECTED_BASE_REPO_MANIFEST_SHA256,
        "goldfish_base_revision": EXPECTED_GOLDFISH_BASE_REVISION,
        "goldfish_revision": EXPECTED_GOLDFISH_REVISION,
        "goldfish_overlay_source_path": GOLDFISH_OVERLAY_SOURCE_PATH,
        "goldfish_overlay_source_sha256": (
            EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256
        ),
        "goldfish_diff_sha256": EXPECTED_GOLDFISH_DIFF_SHA256,
        "automatic_power_mode_resource": AUTO_POWER_RESOURCE,
        "automatic_power_mode_expected_value": True,
        "static_framework_overlay_package": STATIC_FRAMEWORK_OVERLAY_PACKAGE,
        "static_framework_overlay_path": STATIC_FRAMEWORK_OVERLAY_PATH,
        "production_job_status_sha256": EXPECTED_JOB_STATUS_SHA256,
        "aosp_root": str(aosp_root),
        "product_out": str(product_out),
    }
    if not isinstance(target, dict) or any(
        target.get(key) != value for key, value in expected_target.items()
    ):
        raise RunError("campaign target does not match the configured r1 build")
    if plan.get("protocol_seconds") != {
        "pre_age": PRE_AGE_SECONDS,
        "inner_gap": INNER_GAP_SECONDS,
        "overlap": OVERLAP_SECONDS,
        "final_gap": FINAL_GAP_SECONDS,
    }:
        raise RunError("campaign plan protocol does not match the harness")
    if (
        plan.get("clock_tolerance_ms") != CLOCK_TOLERANCE_MS
        or plan.get("tolerance_ms") != TOLERANCE_MS
    ):
        raise RunError("campaign plan tolerances do not match the harness")
    if not isinstance(selection, dict) or selection != CAMPAIGN_SELECTION_RULE:
        raise RunError("campaign plan does not contain the fixed selection rule")
    if plan.get("qualification_checks") != list(CAMPAIGN_QUALIFICATION_CHECKS):
        raise RunError("campaign plan does not contain the fixed qualification rule")
    if plan.get("harness_source_sha256") != source_hash():
        raise RunError("campaign plan does not identify the current harness source")
    overlay_dumps = plan.get("static_framework_overlay_dump_sha256")
    if (
        not isinstance(overlay_dumps, dict)
        or set(overlay_dumps) != {"badging", "manifest", "resources"}
        or any(
            re.fullmatch(r"[0-9a-f]{64}", value or "") is None
            for value in overlay_dumps.values()
        )
    ):
        raise RunError("campaign plan does not bind the generated static overlay dumps")
    validate_emulator_zip_provenance(plan, path.parent)
    campaign_id = plan.get("campaign_id")
    if not isinstance(campaign_id, str) or not re.fullmatch(
        r"cp2a-r1-as-[0-9]{8}T[0-9]{6}Z", campaign_id
    ):
        raise RunError("campaign plan has an invalid campaign ID")
    launch_profile = plan.get("launch_profile")
    if (
        not isinstance(launch_profile, dict)
        or launch_profile.get("serial") != serial
    ):
        raise RunError("campaign serial does not match its launch profile")
    return plan, hashlib.sha256(raw).hexdigest()


def source_paths():
    return (
        PROBE_APP_DIR / "settings.gradle.kts",
        PROBE_APP_DIR / "build.gradle.kts",
        PROBE_APP_DIR / "gradle.properties",
        PROBE_APP_DIR / "app/build.gradle.kts",
        PROBE_APP_DIR / "app/src/main/AndroidManifest.xml",
        PROBE_APP_DIR
        / "app/src/main/java/org/lostboundaries/probe/ProbeReceiver.java",
        PROBE_APP_DIR
        / "app/src/main/java/org/lostboundaries/probe/HoldJobService.java",
        Path(__file__).resolve(),
    )


def source_hash():
    digest = hashlib.sha256()
    for path in source_paths():
        digest.update(str(path.relative_to(REPO_DIR)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def find_gradle():
    configured = os.environ.get("GRADLE")
    candidates = [configured] if configured else []
    for version in ("9.6.1", "9.5.0"):
        candidates += glob.glob(str(
            Path.home() / f".gradle/wrapper/dists/gradle-{version}-bin/*/"
            f"gradle-{version}/bin/gradle"
        ))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RunError("Gradle 9.5+ is not available; set GRADLE to its executable")


class Capture:
    def __init__(self, serial):
        self.serial = serial
        self.commands = []

    @staticmethod
    def _output_text(value):
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return str(value)

    def run(
        self, argv, *, check=True, cwd=None,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    ):
        argv = [str(item) for item in argv]
        resolved_cwd = str(Path(cwd).resolve() if cwd is not None else Path.cwd())
        started = utc_now()
        start_ns = time.monotonic_ns()
        try:
            completed = subprocess.run(
                argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=timeout_seconds,
            )
            row = {
                "seq": len(self.commands) + 1,
                "argv": argv,
                "cwd": resolved_cwd,
                "timeout_seconds": timeout_seconds,
                "started_utc": started,
                "finished_utc": utc_now(),
                "host_elapsed_ms": (
                    time.monotonic_ns() - start_ns
                ) // 1_000_000,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timed_out": False,
                "launch_error": None,
            }
        except subprocess.TimeoutExpired as error:
            row = {
                "seq": len(self.commands) + 1,
                "argv": argv,
                "cwd": resolved_cwd,
                "timeout_seconds": timeout_seconds,
                "started_utc": started,
                "finished_utc": utc_now(),
                "host_elapsed_ms": (
                    time.monotonic_ns() - start_ns
                ) // 1_000_000,
                "exit_code": None,
                "stdout": self._output_text(error.stdout),
                "stderr": self._output_text(error.stderr),
                "timed_out": True,
                "launch_error": None,
            }
        except OSError as error:
            row = {
                "seq": len(self.commands) + 1,
                "argv": argv,
                "cwd": resolved_cwd,
                "timeout_seconds": timeout_seconds,
                "started_utc": started,
                "finished_utc": utc_now(),
                "host_elapsed_ms": (
                    time.monotonic_ns() - start_ns
                ) // 1_000_000,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "launch_error": f"{error.__class__.__name__}: {error}",
            }
        self.commands.append(row)
        if check and row["exit_code"] != 0:
            if row["timed_out"]:
                detail = f"timed out after {timeout_seconds} seconds"
            elif row["launch_error"]:
                detail = row["launch_error"]
            else:
                detail = row["stderr"].strip()
            raise RunError(
                f"command {row['seq']} failed ({row['exit_code']}): "
                f"{' '.join(row['argv'])}: {detail}"
            )
        return row["stdout"].strip()

    def adb(
        self, *args, check=True, timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    ):
        return self.run(
            ["adb", "-s", self.serial, *args], check=check,
            timeout_seconds=timeout_seconds,
        )

    def shell(
        self, *args, check=True, timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    ):
        return self.adb(
            "shell", *args, check=check, timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _remaining_seconds(deadline):
        if deadline is None:
            return COMMAND_TIMEOUT_SECONDS
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunError("controller observation deadline expired")
        return max(0.001, remaining)

    def uptime_ms(self, *, deadline=None):
        output = self.shell(
            "cat", "/proc/uptime",
            timeout_seconds=self._remaining_seconds(deadline),
        )
        try:
            return round(float(output.split()[0]) * 1000)
        except Exception as error:
            raise RunError(f"invalid /proc/uptime output: {output!r}") from error

    @staticmethod
    def parse_bool(output, label):
        value = output.strip().lower()
        if value not in {"true", "false"}:
            raise RunError(f"invalid {label} controller value: {output!r}")
        return value == "true"

    def battery_state(self, *, deadline=None):
        return {
            "charging": self.parse_bool(
                self.shell(
                    "cmd", "jobscheduler", "get-battery-charging",
                    timeout_seconds=self._remaining_seconds(deadline),
                ),
                "charging",
            ),
            "battery_not_low": self.parse_bool(
                self.shell(
                    "cmd", "jobscheduler", "get-battery-not-low",
                    timeout_seconds=self._remaining_seconds(deadline),
                ),
                "battery-not-low",
            ),
        }

    def wait_battery(self, expected, timeout_seconds=10):
        deadline = time.monotonic() + timeout_seconds
        samples = []
        consecutive = 0
        while time.monotonic() < deadline:
            state = self.battery_state(deadline=deadline)
            observed = self.uptime_ms(deadline=deadline)
            samples.append({"uptime_ms": observed, **state})
            if all(state[key] == value for key, value in expected.items()):
                consecutive += 1
                if consecutive == 2:
                    return state, observed, samples
            else:
                consecutive = 0
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        raise RunError(f"battery controller did not reach {expected}; samples={samples}")

    def app(self, command):
        # ProbeReceiver performs schedule, query, and cancel inside the app UID. For
        # query it calls getPendingJobReasonStats(), serializes the complete map, and
        # computes its maximum and ties before returning one Base64-encoded JSON result.
        output = self.shell(
            "am", "broadcast", "--receiver-foreground", "-a", ACTION,
            "-n", RECEIVER, "--es", "cmd", command,
        )
        matches = re.findall(r"data=\"?(LB64:[A-Za-z0-9+/=]+)\"?", output)
        if len(matches) != 1:
            raise RunError(f"app returned no unique machine result: {output!r}")
        try:
            value = json.loads(base64.b64decode(matches[0][5:]).decode())
        except Exception as error:
            raise RunError("app returned malformed machine result") from error
        if not value.get("success"):
            raise RunError(f"app command {command!r} failed: {value}")
        return value


def event(capture, name, mutations, before_expected, after_expected):
    before = capture.battery_state()
    if before != before_expected:
        raise RunError(f"{name} pre-state is {before}, expected {before_expected}")
    lower = capture.uptime_ms()
    mutation_rows = []
    for mutation in mutations:
        capture.shell(*mutation)
        mutation_rows.append(capture.commands[-1]["seq"])
    after, upper, samples = capture.wait_battery(after_expected)
    return {
        "name": name,
        "lower_uptime_ms": lower,
        "upper_uptime_ms": upper,
        "before": before,
        "after": after,
        "mutation_command_seqs": mutation_rows,
        "poll_samples": samples,
    }


def stats(result):
    return {int(code): int(value) for code, value in result["stats_ms"].items()}


def get_bucket(capture):
    output = capture.shell("am", "get-standby-bucket", "--user", "0", APP)
    match = re.search(r"(?:^|\s)(\d+)(?:\s|$)", output)
    if not match:
        raise RunError(f"cannot parse standby bucket: {output!r}")
    return int(match.group(1))


def package_is_installed(capture):
    output = capture.shell("pm", "list", "packages", APP)
    return any(line.strip() == f"package:{APP}" for line in output.splitlines())


def get_job_dump(capture):
    return capture.shell(
        f"dumpsys jobscheduler {APP} | "
        f"sed -n '/^  JOB #.*\\/{JOB_ID}:/,/^$/p'"
    )


def dump_proves_membership(value):
    return all(fragment in value for fragment in (
        "Requires: charging=false batteryNotLow=false deviceIdle=true",
        "Required constraints: TIMING_DELAY IDLE",
        "Dynamic constraints: CHARGING BATTERY_NOT_LOW IDLE",
        "Standby bucket: RESTRICTED",
    ))


def job_identity(value):
    match = re.search(r"^JOB #[^:]+:\s+(\S+)\s+", value, re.MULTILINE)
    return match.group(1) if match else None


_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])"
    r"(?:(?P<days>\d+)d)?"
    r"(?:(?P<hours>\d+)h)?"
    r"(?:(?P<minutes>\d+)m)?"
    r"(?:(?P<seconds>\d+)s)?"
    r"(?P<milliseconds>\d+)ms$"
)


def parse_duration_ms(token):
    if token == "0":
        return 0
    match = _DURATION_RE.fullmatch(token)
    if not match:
        raise RunError(f"cannot parse dumpsys duration: {token!r}")
    value = (
        int(match.group("days") or 0) * 86_400_000
        + int(match.group("hours") or 0) * 3_600_000
        + int(match.group("minutes") or 0) * 60_000
        + int(match.group("seconds") or 0) * 1_000
        + int(match.group("milliseconds"))
    )
    return value if match.group("sign") == "+" else -value


def constraint_history_entries(value):
    if "Constraint history:" not in value:
        raise RunError("job dump has no constraint history")
    section = value.split("Constraint history:", 1)[1].split("Tracking:", 1)[0]
    entries = []
    for line in section.splitlines():
        match = re.match(
            r"^\s*(\S+)\s+=.*\[(0x[0-9a-fA-F]+)\]\s*$", line
        )
        if match:
            entries.append({
                "relative_to_dump_ms": parse_duration_ms(match.group(1)),
                "mask": int(match.group(2), 16),
            })
    if not entries:
        raise RunError("job dump has an empty or unparseable constraint history")
    return entries


def enqueue_relative_to_dump_ms(value):
    match = re.search(r"^\s*Enqueue time:\s*(\S+)\s*$", value, re.MULTILINE)
    if not match:
        raise RunError("job dump has no parseable enqueue time")
    return parse_duration_ms(match.group(1))


def constraint_history_signature(value):
    enqueue_relative = enqueue_relative_to_dump_ms(value)
    return [
        {
            "offset_from_enqueue_ms": (
                entry["relative_to_dump_ms"] - enqueue_relative
            ),
            "mask": entry["mask"],
        }
        for entry in constraint_history_entries(value)
    ]


def validate_event_protocol(events):
    if len(events) != len(EVENT_SPECS):
        raise RunError(f"expected four focal events, found {len(events)}")
    all_mutation_seqs = []
    for value, (name, before, after, _) in zip(events, EVENT_SPECS):
        if value.get("name") != name:
            raise RunError(f"unexpected event name: {value.get('name')!r}")
        if value.get("before") != before or value.get("after") != after:
            raise RunError(f"event {name!r} does not contain its required state change")
        lower = value.get("lower_uptime_ms")
        upper = value.get("upper_uptime_ms")
        if (
            not isinstance(lower, int) or isinstance(lower, bool)
            or not isinstance(upper, int) or isinstance(upper, bool)
            or lower > upper
        ):
            raise RunError(f"event {name!r} has an invalid time bracket")
        samples = value.get("poll_samples")
        if not isinstance(samples, list) or len(samples) < 2:
            raise RunError(f"event {name!r} lacks two confirming controller polls")
        sample_times = [sample.get("uptime_ms") for sample in samples]
        if (
            any(not isinstance(item, int) or isinstance(item, bool)
                for item in sample_times)
            or sample_times != sorted(sample_times)
            or lower > sample_times[0]
            or sample_times[-1] != upper
        ):
            raise RunError(f"event {name!r} has invalid poll timestamps")
        for sample in samples[-2:]:
            observed = {
                "charging": sample.get("charging"),
                "battery_not_low": sample.get("battery_not_low"),
            }
            if observed != after:
                raise RunError(f"event {name!r} lacks a stable terminal state")
        mutation_seqs = value.get("mutation_command_seqs")
        if (
            not isinstance(mutation_seqs, list) or not mutation_seqs
            or any(not isinstance(item, int) or isinstance(item, bool)
                   for item in mutation_seqs)
            or any(left >= right for left, right in zip(
                mutation_seqs, mutation_seqs[1:]
            ))
        ):
            raise RunError(f"event {name!r} has invalid mutation command references")
        all_mutation_seqs.extend(mutation_seqs)
    if any(left >= right for left, right in zip(
        all_mutation_seqs, all_mutation_seqs[1:]
    )):
        raise RunError("event mutation command references are out of order")
    return True


def analyze_constraint_history(
    baseline_dump, final_dump, events, clock_brackets,
    baseline_shared, final_shared,
):
    baseline_entries = constraint_history_entries(baseline_dump)
    final_entries = constraint_history_entries(final_dump)
    baseline_masks = [entry["mask"] for entry in baseline_entries]
    final_masks = [entry["mask"] for entry in final_entries]
    baseline_focal_constraints_satisfied = baseline_masks[-1] & 0x3 == 0x3
    high_bits = baseline_masks[-1] & ~0x3
    focal_masks = [high_bits | spec[3] for spec in EVENT_SPECS]
    expected_final_masks = (
        baseline_masks + focal_masks
    )[-CONSTRAINT_HISTORY_CAPACITY:]
    exact_extension = (
        baseline_focal_constraints_satisfied
        and final_masks == expected_final_masks
    )

    focal_entries = final_entries[-len(EVENT_SPECS):]
    enqueue_relative = enqueue_relative_to_dump_ms(final_dump)
    offsets = [
        entry["relative_to_dump_ms"] - enqueue_relative
        for entry in focal_entries
    ]
    increasing_offsets = (
        len(offsets) == len(EVENT_SPECS)
        and all(left < right for left, right in zip(offsets, offsets[1:]))
    )
    schedule_lower = clock_brackets["schedule_lower_uptime_ms"]
    schedule_upper = clock_brackets["schedule_upper_uptime_ms"]
    transition_bounds = []
    transitions_bound = exact_extension and increasing_offsets
    for offset, event_value, spec in zip(offsets, events, EVENT_SPECS):
        allowed_lower = (
            event_value["lower_uptime_ms"] - CLOCK_TOLERANCE_MS
            - (schedule_upper + CLOCK_TOLERANCE_MS)
        )
        allowed_upper = (
            event_value["upper_uptime_ms"] + CLOCK_TOLERANCE_MS
            - (schedule_lower - CLOCK_TOLERANCE_MS)
        )
        contained = (
            allowed_lower <= offset <= allowed_upper
        )
        transitions_bound = transitions_bound and contained
        transition_bounds.append({
            "name": spec[0],
            "offset_from_enqueue_ms": offset,
            "allowed_offset_lower_ms": allowed_lower,
            "allowed_offset_upper_ms": allowed_upper,
            "controller_lower_uptime_ms": event_value["lower_uptime_ms"],
            "controller_upper_uptime_ms": event_value["upper_uptime_ms"],
            "offset_inside_uptime_difference_bound": contained,
        })

    dumpsys_durations = None
    collapsed_prediction = None
    model_inputs_proven = (
        exact_extension and increasing_offsets and transitions_bound
        and len(offsets) == len(EVENT_SPECS)
    )
    if model_inputs_proven:
        union_exact = offsets[3] - offsets[0]
        nested_exact = offsets[2] - offsets[1]
        dumpsys_durations = {
            "union_ms": union_exact,
            "nested_battery_not_low_ms": nested_exact,
            "contributor_additive_ms": union_exact + nested_exact,
        }
        collapsed_prediction = baseline_shared + nested_exact + offsets[3]
    model_matches = (
        collapsed_prediction is not None
        and final_shared == collapsed_prediction
    )
    return {
        "baseline_masks": [hex(mask) for mask in baseline_masks],
        "final_masks": [hex(mask) for mask in final_masks],
        "expected_final_masks": [hex(mask) for mask in expected_final_masks],
        "enqueue_relative_to_dump_ms": enqueue_relative,
        "transitions": transition_bounds,
        "dumpsys_derived_reference_ms": dumpsys_durations,
        "collapsed_prediction_ms": collapsed_prediction,
        "checks": {
            "baseline_focal_constraints_satisfied": (
                baseline_focal_constraints_satisfied
            ),
            "per_job_history_exact_protocol_extension": exact_extension,
            "per_job_transition_times_bound_to_controller_events": transitions_bound,
            "per_job_collapsed_prediction_equals_public_value": model_matches,
        },
    }


def check_result(schedule, baseline, final, events, clock_brackets):
    """Compute conservative reference/model bounds and the public ranking checks.

    If E is enqueue, B0 is the baseline APP_STANDBY total, Co/Cc are the
    charging open/close times, and Bo/Bc are the nested battery-not-low
    open/close times, then union = Cc-Co, contributor-additive =
    (Cc-Co)+(Bc-Bo), and the characterized current implementation is
    B0+(Bc-Bo)+(Cc-E). The final term contains the job-age-sized fallback that
    the experiment is designed to expose. Outer /proc/uptime brackets keep
    these primary bounds in one clock domain; app elapsed-time brackets are
    retained as an independent compatibility and age check.
    """
    validate_event_protocol(events)
    c_open, b_open, b_close, c_close = events
    s0 = int(schedule["schedule_before_elapsed_ms"])
    s1 = int(schedule["schedule_after_elapsed_ms"])
    bq0 = int(baseline["query_before_elapsed_ms"])
    bq1 = int(baseline["query_after_elapsed_ms"])
    q0 = int(final["query_before_elapsed_ms"])
    q1 = int(final["query_after_elapsed_ms"])
    final_stats = stats(final)
    baseline_stats = stats(baseline)
    shared = final_stats.get(APP_STANDBY, 0)
    comparator = final_stats.get(MINIMUM_LATENCY, 0)

    def lower(value):
        return int(value) - CLOCK_TOLERANCE_MS

    def upper(value):
        return int(value) + CLOCK_TOLERANCE_MS

    schedule_lower = clock_brackets["schedule_lower_uptime_ms"]
    schedule_upper = clock_brackets["schedule_upper_uptime_ms"]
    baseline_lower = clock_brackets["baseline_lower_uptime_ms"]
    baseline_upper = clock_brackets["baseline_upper_uptime_ms"]
    final_lower = clock_brackets["final_lower_uptime_ms"]
    final_upper = clock_brackets["final_upper_uptime_ms"]

    union = {
        "lower_ms": (
            lower(c_close["lower_uptime_ms"])
            - upper(c_open["upper_uptime_ms"])
        ),
        "upper_ms": (
            upper(c_close["upper_uptime_ms"])
            - lower(c_open["lower_uptime_ms"])
        ),
    }
    nested = {
        "lower_ms": (
            lower(b_close["lower_uptime_ms"])
            - upper(b_open["upper_uptime_ms"])
        ),
        "upper_ms": (
            upper(b_close["upper_uptime_ms"])
            - lower(b_open["lower_uptime_ms"])
        ),
    }
    additive = {
        "lower_ms": union["lower_ms"] + nested["lower_ms"],
        "upper_ms": union["upper_ms"] + nested["upper_ms"],
    }
    age = {
        "lower_ms": lower(final_lower) - upper(schedule_upper),
        "upper_ms": upper(final_upper) - lower(schedule_lower),
    }
    app_elapsed_age = {
        "lower_ms": q0 - s1,
        "upper_ms": q1 - s0,
    }
    collapsed = {
        "lower_ms": (
            baseline_stats.get(APP_STANDBY, 0)
            + nested["lower_ms"]
            + lower(c_close["lower_uptime_ms"])
            - upper(schedule_upper)
        ),
        "upper_ms": (
            baseline_stats.get(APP_STANDBY, 0)
            + nested["upper_ms"]
            + upper(c_close["upper_uptime_ms"])
            - lower(schedule_lower)
        ),
    }
    timeline = (
        schedule_lower <= schedule_upper < baseline_lower <= baseline_upper
        <= c_open["lower_uptime_ms"] <= c_open["upper_uptime_ms"]
        < b_open["lower_uptime_ms"] <= b_open["upper_uptime_ms"]
        < b_close["lower_uptime_ms"] <= b_close["upper_uptime_ms"]
        < c_close["lower_uptime_ms"] <= c_close["upper_uptime_ms"]
        <= final_lower <= final_upper
    )
    app_intervals_enclosed = (
        lower(schedule_lower) <= s0 <= s1 <= upper(schedule_upper)
        and lower(baseline_lower) <= bq0 <= bq1 <= upper(baseline_upper)
        and lower(final_lower) <= q0 <= q1 <= upper(final_upper)
    )
    maximum_codes = [int(code) for code in final.get("max_codes", [])]
    host_maximum = max(final_stats.values()) if final_stats else 0
    host_maximum_codes = sorted(
        code for code, value in final_stats.items() if value == host_maximum
    )
    checks = {
        "baseline_shared_key_present_zero": (
            APP_STANDBY in baseline_stats
            and baseline_stats[APP_STANDBY] == 0
        ),
        "event_protocol_structurally_valid": True,
        "schedule_baseline_events_query_timeline_proven": timeline,
        "schedule_contract_proven": (
            schedule.get("schedule_result") == 1
            and schedule.get("job_id") == JOB_ID
            and schedule.get("minimum_latency_ms", 0)
            > age["upper_ms"] + TOLERANCE_MS
            and schedule.get("requires_device_idle") is True
            and schedule.get("requires_charging") is False
            and schedule.get("requires_battery_not_low") is False
            and schedule.get("persisted") is False
        ),
        "app_elapsed_intervals_enclosed_by_uptime_brackets": (
            app_intervals_enclosed
        ),
        "reference_ranking_union": age["lower_ms"] > union["upper_ms"] + TOLERANCE_MS,
        "reference_ranking_additive": (
            age["lower_ms"] > additive["upper_ms"] + TOLERANCE_MS
        ),
        "comparator_matches_job_age": (
            age["lower_ms"] - TOLERANCE_MS <= comparator
            <= age["upper_ms"] + TOLERANCE_MS
            and app_elapsed_age["lower_ms"] - TOLERANCE_MS <= comparator
            <= app_elapsed_age["upper_ms"] + TOLERANCE_MS
        ),
        "shared_matches_collapsed_model": (
            collapsed["lower_ms"] - TOLERANCE_MS <= shared
            <= collapsed["upper_ms"] + TOLERANCE_MS
        ),
        "public_shared_exceeds_maximum_job_age": (
            shared > age["upper_ms"] + TOLERANCE_MS
        ),
        "public_ranking_reversal": shared > comparator + TOLERANCE_MS,
        "app_ranker_unique_app_standby": (
            final.get("unique_argmax") is True
            and final.get("argmax_code") == APP_STANDBY
            and maximum_codes == [APP_STANDBY]
        ),
        "app_ranker_matches_host_recomputation": (
            int(final.get("max_duration_ms", -1)) == host_maximum
            and maximum_codes == host_maximum_codes
        ),
        "job_pending_at_schedule_baseline_and_final": (
            schedule.get("pending") is True
            and baseline.get("pending") is True
            and final.get("pending") is True
        ),
        "callback_count_zero_at_final_query": final.get("callback_count") == 0,
    }
    return {
        "reported_ms": {
            "app_standby": shared,
            "minimum_latency": comparator,
            "app_standby_minus_age_upper": shared - age["upper_ms"],
            "app_standby_minus_minimum_latency": shared - comparator,
        },
        "interval_bounds_ms": {
            "union": union,
            "additive": additive,
            "job_age_conservative_uptime": age,
            "job_age_app_elapsed": app_elapsed_age,
            "collapsed_implementation": collapsed,
        },
        "host_ranker": {
            "max_duration_ms": host_maximum,
            "max_codes": host_maximum_codes,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def write_evidence(attempt, evidence):
    document = {
        "schema": 1,
        "experiment": "public-api-controller-ranking",
        "attempts": [attempt],
    }
    if not evidence.parent.is_dir() or evidence.parent.is_symlink():
        raise RunError(f"unsafe or missing evidence directory: {evidence.parent}")
    temporary = evidence.with_suffix(evidence.suffix + ".new")
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    try:
        os.link(temporary, evidence, follow_symlinks=False)
    except FileExistsError as error:
        raise RunError(f"refusing to overwrite evidence: {evidence}") from error
    temporary.unlink()
    directory_fd = os.open(evidence.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", "emulator-5584"))
    parser.add_argument(
        "--expected-fingerprint",
        default=os.environ.get(
            "HARNESS_EXPECTED_FINGERPRINT", DEFAULT_EXPECTED_FINGERPRINT
        ),
    )
    parser.add_argument(
        "--expected-build-id",
        default=os.environ.get("HARNESS_EXPECTED_BUILD_ID", DEFAULT_EXPECTED_BUILD_ID),
    )
    parser.add_argument(
        "--expected-security-patch",
        default=os.environ.get(
            "HARNESS_EXPECTED_SECURITY_PATCH", DEFAULT_EXPECTED_SECURITY_PATCH
        ),
    )
    parser.add_argument(
        "--evidence",
        default=os.environ.get("HARNESS_EVIDENCE", str(DEFAULT_EVIDENCE)),
    )
    parser.add_argument(
        "--aosp-product-out",
        default=os.environ.get(
            "ANDROID_PRODUCT_OUT",
            str(DEFAULT_PRODUCT_OUT),
        ),
    )
    parser.add_argument(
        "--aosp-root",
        default=os.environ.get("ANDROID_BUILD_TOP", str(DEFAULT_AOSP_ROOT)),
    )
    parser.add_argument(
        "--campaign-plan",
        default=os.environ.get("HARNESS_CAMPAIGN_PLAN"),
    )
    args = parser.parse_args()
    supplied_evidence = Path(args.evidence).expanduser()
    supplied_campaign_plan = (
        Path(args.campaign_plan).expanduser()
        if args.campaign_plan is not None
        else None
    )
    evidence = supplied_evidence.resolve()
    aosp = Path(args.aosp_root).expanduser().resolve()
    product_out = Path(args.aosp_product_out).expanduser().resolve()
    campaign_plan_path = (
        supplied_campaign_plan.resolve()
        if supplied_campaign_plan is not None
        else None
    )
    if campaign_plan_path is not None:
        evidence_new = evidence.with_suffix(evidence.suffix + ".new")
        if (
            supplied_evidence.is_symlink()
            or supplied_campaign_plan.is_symlink()
            or not campaign_plan_path.is_file()
            or campaign_plan_path.parent.is_symlink()
            or evidence.parent != campaign_plan_path.parent
            or evidence.name != ".attempt-evidence.json"
            or evidence.exists()
            or evidence.is_symlink()
            or evidence_new.exists()
            or evidence_new.is_symlink()
        ):
            raise RunError("campaign evidence and plan paths are not safely confined")
    capture = Capture(args.serial)
    attempt = {
        "schema": 1,
        "started_utc": utc_now(),
        "serial": args.serial,
        "protocol_seconds": {
            "pre_age": PRE_AGE_SECONDS,
            "inner_gap": INNER_GAP_SECONDS,
            "overlap": OVERLAP_SECONDS,
            "final_gap": FINAL_GAP_SECONDS,
        },
        "tolerance_ms": TOLERANCE_MS,
        "clock_tolerance_ms": CLOCK_TOLERANCE_MS,
    }
    installed = False
    app_cleanup_needed = False
    battery_cleanup_needed = False
    initial_controller_state = None
    campaign_plan = None
    campaign_plan_sha256 = None
    if campaign_plan_path is not None:
        attempt["campaign"] = {
            "plan": str(campaign_plan_path),
            "plan_loaded": False,
        }
    try:
        if campaign_plan_path is not None:
            campaign_plan, campaign_plan_sha256 = load_campaign_plan(
                campaign_plan_path,
                args.expected_fingerprint,
                args.expected_build_id,
                args.expected_security_patch,
                aosp,
                product_out,
                args.serial,
            )
            attempt["campaign"].update({
                "id": campaign_plan["campaign_id"],
                "plan_loaded": True,
                "plan_sha256": campaign_plan_sha256,
            })
        if capture.adb("get-state") != "device":
            raise RunError("target is not in adb device state")
        props = {
            key: capture.shell("getprop", key)
            for key in (
                "ro.build.version.sdk", "ro.build.version.release",
                "ro.build.version.codename", "ro.build.version.security_patch",
                "ro.build.version.incremental", "ro.build.version.preview_sdk",
                "ro.build.fingerprint", "ro.build.id", "ro.build.type",
                "ro.build.user", "ro.build.tags",
                "ro.product.name", "ro.boot.qemu.avd_name",
            )
        }
        attempt["device"] = props
        if props["ro.build.version.sdk"] != EXPECTED_SDK:
            raise RunError(f"requires API 37, found {props['ro.build.version.sdk']}")
        if (
            props["ro.build.version.release"] != "17"
            or props["ro.build.version.codename"] != "REL"
            or props["ro.build.version.preview_sdk"] != "0"
        ):
            raise RunError("runtime is not the final Android 17 release configuration")
        if props["ro.build.type"] != "userdebug":
            raise RunError("runtime is not the required userdebug build")
        if (
            props["ro.build.user"] != "lostboundaries"
            or props["ro.build.tags"] != "test-keys"
            or props["ro.build.version.incremental"] != EXPECTED_BUILD_INCREMENTAL
        ):
            raise RunError("runtime does not have the planned local build identity")
        if props["ro.product.name"] != "sdk_phone64_x86_64":
            raise RunError("runtime product does not match the configured target")
        if props["ro.build.fingerprint"] != args.expected_fingerprint:
            raise RunError("runtime fingerprint does not match the configured target")
        if props["ro.build.id"] != args.expected_build_id:
            raise RunError("runtime build ID does not match the configured target")
        if props["ro.build.version.security_patch"] != args.expected_security_patch:
            raise RunError("runtime security patch does not match the configured target")
        boot_before = capture.shell("cat", "/proc/sys/kernel/random/boot_id")
        attempt["boot_id_before"] = boot_before
        package_preexisting = package_is_installed(capture)
        attempt["package_preflight_absent"] = not package_preexisting
        if package_preexisting:
            raise RunError(
                "dedicated probe package is already installed; refusing to overwrite it"
            )

        frameworks_base = aosp / "frameworks/base"
        revision = capture.run(
            ["git", "-C", frameworks_base, "rev-parse", "HEAD"]
        )
        if revision != EXPECTED_REVISION:
            raise RunError(
                f"frameworks/base revision is {revision}, "
                f"expected {EXPECTED_REVISION}"
            )
        capture.run(["repo", "manifest", "-r"], cwd=aosp)
        manifest_sha256 = validate_configured_repo_manifest(
            capture.commands[-1]["stdout"]
        )
        goldfish = aosp / "device/generic/goldfish"
        goldfish_revision = capture.run(
            ["git", "-C", goldfish, "rev-parse", "HEAD"]
        )
        goldfish_parent = capture.run(
            ["git", "-C", goldfish, "rev-parse", "HEAD^"]
        )
        if (
            goldfish_revision != EXPECTED_GOLDFISH_REVISION
            or goldfish_parent != EXPECTED_GOLDFISH_BASE_REVISION
        ):
            raise RunError("goldfish configuration revision is not the pinned one-commit delta")
        goldfish_name_status = capture.run(
            [
                "git", "-C", goldfish, "diff", "--name-status",
                EXPECTED_GOLDFISH_BASE_REVISION, goldfish_revision,
            ]
        )
        if goldfish_name_status != f"A\t{GOLDFISH_OVERLAY_SOURCE_PATH}":
            raise RunError("goldfish configuration commit does not add only the pinned overlay")
        capture.run(
            [
                "git", "-C", goldfish, "diff", "--binary",
                EXPECTED_GOLDFISH_BASE_REVISION, goldfish_revision,
            ]
        )
        goldfish_diff_sha256 = hashlib.sha256(
            capture.commands[-1]["stdout"].encode()
        ).hexdigest()
        overlay_source = goldfish / GOLDFISH_OVERLAY_SOURCE_PATH
        overlay_source_sha256 = sha256(overlay_source)
        if (
            goldfish_diff_sha256 != EXPECTED_GOLDFISH_DIFF_SHA256
            or overlay_source_sha256 != EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256
        ):
            raise RunError("goldfish overlay source or commit diff does not match the plan")
        full_checkout_status = capture.run(
            [
                "repo", "forall", "-c",
                "status=$(git status --porcelain=v1 --untracked-files=all) "
                "|| exit $?; "
                "if [ -n \"$status\" ]; then "
                "printf '%s\\n' \"$status\" | sed \"s|^|$REPO_PATH\\t|\"; "
                "fi",
            ],
            cwd=aosp,
        )
        if full_checkout_status:
            raise RunError(
                "AOSP checkout is not clean at acquisition time: "
                f"{full_checkout_status!r}"
            )
        production_status = capture.run(
            [
                "git", "-C", frameworks_base, "status", "--porcelain", "--",
                *PRODUCTION_SOURCE_PATHS,
            ]
        )
        if production_status:
            raise RunError(
                "production JobScheduler source paths are modified: "
                f"{production_status!r}"
            )
        job_status_path = frameworks_base / PRODUCTION_SOURCE_PATHS[-1]
        job_status_sha256 = sha256(job_status_path)
        if job_status_sha256 != EXPECTED_JOB_STATUS_SHA256:
            raise RunError(
                f"production JobStatus SHA-256 is {job_status_sha256}, "
                f"expected {EXPECTED_JOB_STATUS_SHA256}"
            )
        local_artifact_paths = {
            device_path: product_out / device_path.removeprefix("/")
            for device_path in RUNTIME_ARTIFACT_PATHS
        }
        missing_artifacts = [
            str(path) for path in local_artifact_paths.values()
            if not path.is_file() or path.is_symlink()
        ]
        if missing_artifacts:
            raise RunError(f"missing local build artifacts: {missing_artifacts}")
        local_artifact_sha256 = {
            device_path: sha256(local_path)
            for device_path, local_path in local_artifact_paths.items()
        }
        if (
            campaign_plan is not None
            and campaign_plan.get("build_output_runtime_artifact_sha256")
            != local_artifact_sha256
        ):
            raise RunError(
                "local runtime artifacts do not match the pre-run campaign plan"
            )
        gradle = find_gradle()
        capture.run(
            [gradle, "--offline", "--no-daemon", ":app:assembleDebug"],
            cwd=PROBE_APP_DIR, timeout_seconds=BUILD_TIMEOUT_SECONDS,
        )
        apk = PROBE_APP_DIR / "app/build/outputs/apk/debug/app-debug.apk"
        if not apk.is_file():
            raise RunError("Gradle did not produce the debug APK")
        attempt["build"] = {
            "frameworks_base_revision": revision,
            "resolved_repo_manifest_sha256": manifest_sha256,
            "base_resolved_repo_manifest_sha256": (
                EXPECTED_BASE_REPO_MANIFEST_SHA256
            ),
            "goldfish_base_revision": goldfish_parent,
            "goldfish_revision": goldfish_revision,
            "goldfish_overlay_source_path": GOLDFISH_OVERLAY_SOURCE_PATH,
            "goldfish_overlay_source_sha256": overlay_source_sha256,
            "goldfish_diff_sha256": goldfish_diff_sha256,
            "production_job_status_sha256": job_status_sha256,
            "full_source_checkout_clean": True,
            "production_source_paths_clean": True,
            "aosp_root": str(aosp),
            "product_out": str(product_out),
            "build_output_artifact_sha256": local_artifact_sha256,
            "source_sha256": source_hash(),
            "apk_sha256": sha256(apk),
            "compile_sdk": 37,
            "target_sdk": 37,
            "min_sdk": 37,
        }
        # Install the ordinary probe app on the verified API-37 emulator.
        package_preinstall_absent = not package_is_installed(capture)
        attempt["package_preinstall_absent"] = package_preinstall_absent
        if not package_preinstall_absent:
            raise RunError(
                "dedicated probe package appeared during the build; refusing to overwrite it"
            )
        app_cleanup_needed = True
        capture.adb("install", "-t", apk)
        installed = True
        uid_output = capture.shell("pm", "list", "packages", "-U", APP)
        uid_match = re.search(r"uid:(\d+)", uid_output)
        if not uid_match:
            raise RunError(f"cannot resolve app UID: {uid_output!r}")
        attempt["app_uid"] = int(uid_match.group(1))
        runtime_artifact_output = capture.shell(
            "sha256sum", *RUNTIME_ARTIFACT_PATHS,
        )
        attempt["runtime_artifact_sha256"] = runtime_artifact_output
        runtime_artifact_sha256 = parse_sha256sum(runtime_artifact_output)
        attempt["runtime_artifact_sha256_by_path"] = runtime_artifact_sha256
        if runtime_artifact_sha256 != local_artifact_sha256:
            raise RunError(
                "runtime framework artifacts do not match the pinned build outputs"
            )
        api_flag = capture.shell(
            "dumpsys jobscheduler | sed -n "
            "'/android.app.job.get_pending_job_reason_stats_api=/p'"
        )
        if "android.app.job.get_pending_job_reason_stats_api=true" not in api_flag:
            raise RunError(f"public stats API flag is not enabled: {api_flag!r}")
        attempt["runtime_api_flag"] = api_flag
        automatic_power_modes_before = automatic_power_mode_state(capture)
        attempt["automatic_power_modes_before"] = automatic_power_modes_before

        # BatteryService has no ownership token. Under the required exclusive-device
        # precondition, this immediate preflight ensures we only reset our own override.
        attempt["battery_before"] = capture.shell("dumpsys", "battery")
        battery_input_suspended_before = capture.shell(
            "getprop", "power.battery_input.suspended"
        ).strip().lower()
        attempt["battery_input_suspended_before"] = (
            battery_input_suspended_before
        )
        if BATTERY_OVERRIDE_MARKER in attempt["battery_before"]:
            raise RunError(
                "BatteryService simulation is already active; refusing to overwrite it"
            )
        if battery_input_suspended_before not in {"", "0", "false"}:
            raise RunError(
                "battery input is already suspended; refusing to alter that state"
            )
        if re.search(
            r"^\s*Dock powered:\s*true\s*$",
            attempt["battery_before"], re.MULTILINE | re.IGNORECASE,
        ):
            raise RunError(
                "dock power is active and cannot be restored reliably by battery reset"
            )
        initial_controller_state = capture.battery_state()
        attempt["controller_state_before"] = initial_controller_state

        # Set this before the first mutation: even a command that later reports an
        # error may already have frozen BatteryService's externally supplied state.
        battery_cleanup_needed = True
        for command in (
            ("cmd", "battery", "unplug", "-f"),
            ("cmd", "battery", "set", "-f", "level", "100"),
            ("cmd", "battery", "set", "-f", "ac", "1"),
            ("cmd", "battery", "set", "-f", "status", "2"),
        ):
            capture.shell(*command)
        _, _, setup_samples = capture.wait_battery(
            {"charging": True, "battery_not_low": True}
        )
        attempt["setup_controller_samples"] = setup_samples
        # Standby buckets are package state; Restricted then adds the focal dynamic
        # charging and battery-not-low constraints to this package's pending job.
        capture.shell(
            "am", "set-standby-bucket", "--user", "0", APP, "restricted"
        )
        if get_bucket(capture) != 45:
            raise RunError("package did not enter the Restricted standby bucket")

        schedule_lower_uptime_ms = capture.uptime_ms()
        schedule = capture.app("schedule")
        schedule_upper_uptime_ms = capture.uptime_ms()
        time.sleep(PRE_AGE_SECONDS)
        baseline_job_dump_before_query = get_job_dump(capture)
        baseline_lower_uptime_ms = capture.uptime_ms()
        baseline = capture.app("query")
        baseline_upper_uptime_ms = capture.uptime_ms()
        baseline_job_dump_after_query = get_job_dump(capture)
        bucket_baseline = get_bucket(capture)
        if bucket_baseline != 45:
            raise RunError("package left the Restricted bucket before focal events")
        events = []
        events.append(event(
            capture, "charging_unsatisfied",
            [
                ("cmd", "battery", "set", "-f", "status", "3"),
                ("cmd", "battery", "unplug", "-f"),
            ],
            {"charging": True, "battery_not_low": True},
            {"charging": False, "battery_not_low": True},
        ))
        time.sleep(INNER_GAP_SECONDS)
        events.append(event(
            capture, "battery_not_low_unsatisfied",
            [("cmd", "battery", "set", "-f", "level", "5")],
            {"charging": False, "battery_not_low": True},
            {"charging": False, "battery_not_low": False},
        ))
        time.sleep(OVERLAP_SECONDS)
        events.append(event(
            capture, "battery_not_low_satisfied",
            [("cmd", "battery", "set", "-f", "level", "100")],
            {"charging": False, "battery_not_low": False},
            {"charging": False, "battery_not_low": True},
        ))
        time.sleep(FINAL_GAP_SECONDS)
        events.append(event(
            capture, "charging_satisfied",
            [
                ("cmd", "battery", "set", "-f", "ac", "1"),
                ("cmd", "battery", "set", "-f", "status", "2"),
            ],
            {"charging": False, "battery_not_low": True},
            {"charging": True, "battery_not_low": True},
        ))
        final_lower_uptime_ms = capture.uptime_ms()
        final = capture.app("query")
        final_upper_uptime_ms = capture.uptime_ms()
        final_job_dump = get_job_dump(capture)
        final_job_state = capture.shell(
            "cmd", "jobscheduler", "get-job-state", "--user", "0", APP, str(JOB_ID)
        )
        bucket_final = get_bucket(capture)
        automatic_power_modes_after = automatic_power_mode_state(capture)
        attempt["automatic_power_modes_after"] = automatic_power_modes_after
        boot_after = capture.shell("cat", "/proc/sys/kernel/random/boot_id")
        attempt["observations"] = {
            "schedule": schedule,
            "baseline": baseline,
            "baseline_job_dump_before_query": baseline_job_dump_before_query,
            "baseline_job_dump_after_query": baseline_job_dump_after_query,
            "baseline_bucket": bucket_baseline,
            "events": events,
            "final": final,
            "final_job_dump": final_job_dump,
            "final_job_state": final_job_state,
            "final_bucket": bucket_final,
            "clock_brackets": {
                "schedule_lower_uptime_ms": schedule_lower_uptime_ms,
                "schedule_upper_uptime_ms": schedule_upper_uptime_ms,
                "baseline_lower_uptime_ms": baseline_lower_uptime_ms,
                "baseline_upper_uptime_ms": baseline_upper_uptime_ms,
                "final_lower_uptime_ms": final_lower_uptime_ms,
                "final_upper_uptime_ms": final_upper_uptime_ms,
            },
        }
        analysis = check_result(
            schedule, baseline, final, events,
            attempt["observations"]["clock_brackets"],
        )
        analysis["checks"]["restricted_bucket_at_baseline_and_final"] = (
            bucket_baseline == 45 and bucket_final == 45
        )
        analysis["checks"]["automatic_power_modes_stable"] = (
            automatic_power_modes_before == automatic_power_modes_after
            and automatic_power_modes_before["valid"]
        )
        analysis["checks"]["dynamic_membership_proven"] = (
            dump_proves_membership(baseline_job_dump_before_query)
            and dump_proves_membership(baseline_job_dump_after_query)
            and dump_proves_membership(final_job_dump)
        )
        analysis["checks"]["same_jobstatus_identity"] = (
            job_identity(baseline_job_dump_before_query) is not None
            and job_identity(baseline_job_dump_before_query)
            == job_identity(baseline_job_dump_after_query)
            == job_identity(final_job_dump)
        )
        baseline_history_before = constraint_history_signature(
            baseline_job_dump_before_query
        )
        baseline_history_after = constraint_history_signature(
            baseline_job_dump_after_query
        )
        analysis["baseline_constraint_history_before_query"] = (
            baseline_history_before
        )
        analysis["baseline_constraint_history_after_query"] = (
            baseline_history_after
        )
        analysis["checks"]["baseline_history_quiescent_across_public_query"] = (
            baseline_history_before == baseline_history_after
        )
        history_analysis = analyze_constraint_history(
            baseline_job_dump_after_query,
            final_job_dump,
            events,
            attempt["observations"]["clock_brackets"],
            stats(baseline).get(APP_STANDBY, 0),
            stats(final).get(APP_STANDBY, 0),
        )
        analysis["per_job_constraint_history"] = history_analysis
        analysis["checks"].update(history_analysis["checks"])
        app_id = attempt["app_uid"] % 100_000
        analysis["checks"]["public_calls_from_installed_ordinary_app_uid"] = (
            10_000 <= app_id <= 19_999
            and all(
                value.get("uid") == attempt["app_uid"]
                for value in (schedule, baseline, final)
            )
        )
        analysis["checks"]["boot_preserved"] = boot_after == boot_before
        job_state_tokens = final_job_state.split()
        analysis["checks"]["job_state_waiting_not_active"] = (
            ("waiting" in job_state_tokens or "pending" in job_state_tokens)
            and "active" not in job_state_tokens
            and "ready" not in job_state_tokens
        )
        final_source_sha256 = source_hash()
        final_local_artifact_sha256 = {
            device_path: sha256(local_path)
            for device_path, local_path in local_artifact_paths.items()
        }
        if final_source_sha256 != attempt["build"]["source_sha256"]:
            raise RunError("harness or probe source changed during the attempt")
        if (
            any(path.is_symlink() for path in local_artifact_paths.values())
            or final_local_artifact_sha256 != local_artifact_sha256
        ):
            raise RunError("local runtime build outputs changed during the attempt")
        attempt["build"]["source_sha256_after"] = final_source_sha256
        attempt["build"]["build_output_artifact_sha256_after"] = (
            final_local_artifact_sha256
        )
        analysis["passed"] = all(analysis["checks"].values())
        attempt["boot_id_after"] = boot_after
        attempt["analysis"] = analysis
        attempt["outcome"] = "PASS" if analysis["passed"] else "FAIL"
    except Exception as error:
        attempt["outcome"] = "ERROR"
        attempt["error"] = f"{error.__class__.__name__}: {error}"
    finally:
        cleanup = {"command_seqs": [], "checks": {}}
        cleanup_start_seq = len(capture.commands) + 1
        if installed:
            try:
                cancel_result = capture.app("cancel")
                cleanup["cancel_result"] = cancel_result
                cleanup["checks"]["job_cancelled"] = (
                    cancel_result.get("success") is True
                    and cancel_result.get("pending") is False
                )
            except Exception as error:
                cleanup["cancel_error"] = f"{error.__class__.__name__}: {error}"
                cleanup["checks"]["job_cancelled"] = False

        if battery_cleanup_needed:
            reset_output = capture.shell(
                "cmd", "battery", "reset", "-f", check=False
            )
            reset_row = capture.commands[-1]
            cleanup["battery_reset_output"] = reset_output
            cleanup["checks"]["battery_override_exit_command_succeeded"] = (
                reset_row["exit_code"] == 0
                and re.fullmatch(r"-?\d+", reset_output.strip()) is not None
            )
            if initial_controller_state is not None:
                try:
                    restored, restored_at, restore_samples = capture.wait_battery(
                        initial_controller_state
                    )
                    cleanup["controller_after_reset"] = restored
                    cleanup["controller_restored_at_uptime_ms"] = restored_at
                    cleanup["controller_restore_samples"] = restore_samples
                    cleanup["checks"]["relevant_controller_state_restored"] = (
                        restored == initial_controller_state
                    )
                except Exception as error:
                    cleanup["controller_restore_error"] = (
                        f"{error.__class__.__name__}: {error}"
                    )
                    cleanup["checks"]["relevant_controller_state_restored"] = False
            else:
                cleanup["checks"]["relevant_controller_state_restored"] = False

            battery_after = capture.shell("dumpsys", "battery", check=False)
            battery_after_row = capture.commands[-1]
            input_suspended_after = capture.shell(
                "getprop", "power.battery_input.suspended", check=False
            ).strip().lower()
            input_suspended_after_row = capture.commands[-1]
            cleanup["battery_after_reset"] = battery_after
            cleanup["battery_input_suspended_after"] = input_suspended_after
            cleanup["checks"]["battery_override_cleared"] = (
                battery_after_row["exit_code"] == 0
                and BATTERY_OVERRIDE_MARKER not in battery_after
                and input_suspended_after_row["exit_code"] == 0
                and input_suspended_after in {"", "0", "false"}
            )

        if app_cleanup_needed:
            capture.adb("shell", "pm", "uninstall", APP, check=False)
            uninstall_row = capture.commands[-1]
            uninstall_succeeded = (
                uninstall_row["exit_code"] == 0
                and "Success" in uninstall_row["stdout"]
            )
            cleanup["checks"]["app_uninstall_command_succeeded"] = (
                uninstall_succeeded
            )

            package_listing = capture.shell("pm", "list", "packages", APP, check=False)
            package_row = capture.commands[-1]
            app_absent = (
                package_row["exit_code"] == 0
                and f"package:{APP}" not in package_listing
            )
            cleanup["checks"]["app_absent"] = app_absent

            jobs_after = capture.shell("dumpsys", "jobscheduler", APP, check=False)
            jobs_row = capture.commands[-1]
            cleanup["checks"]["job_absent"] = (
                jobs_row["exit_code"] == 0
                and re.search(rf"JOB #[^\n]*/{JOB_ID}:", jobs_after) is None
            )

        if app_cleanup_needed or battery_cleanup_needed:
            cleanup["command_seqs"] = list(
                range(cleanup_start_seq, len(capture.commands) + 1)
            )
        cleanup_succeeded = bool(cleanup["checks"]) and all(cleanup["checks"].values())
        cleanup["succeeded"] = cleanup_succeeded
        attempt["cleanup"] = cleanup
        if "analysis" in attempt:
            attempt["analysis"]["checks"]["cleanup_succeeded"] = cleanup_succeeded
            attempt["analysis"]["passed"] = all(
                attempt["analysis"]["checks"].values()
            )
            attempt["outcome"] = (
                "PASS" if attempt["analysis"]["passed"] else "FAIL"
            )
        if campaign_plan_sha256 is not None:
            try:
                current_plan_sha256 = sha256(campaign_plan_path)
            except OSError as error:
                current_plan_sha256 = None
                plan_error = f"cannot re-read campaign plan: {error}"
            else:
                plan_error = "campaign plan changed during the attempt"
            attempt["campaign"]["plan_sha256_after"] = current_plan_sha256
            attempt["campaign"]["plan_unchanged"] = (
                current_plan_sha256 == campaign_plan_sha256
            )
            if current_plan_sha256 != campaign_plan_sha256:
                attempt["outcome"] = "ERROR"
                attempt["error"] = f"RunError: {plan_error}"
        attempt["finished_utc"] = utc_now()
        attempt["commands"] = capture.commands
        write_evidence(attempt, evidence)

    summary = {"outcome": attempt["outcome"], "evidence": str(evidence)}
    if "analysis" in attempt:
        summary.update(attempt["analysis"].get("reported_ms", {}))
    if "error" in attempt:
        summary["error"] = attempt["error"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if attempt["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
