#!/usr/bin/env python3
"""Create deterministic CSV summaries from an immutable harness-run archive."""

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
from collections import Counter

import probe_harness
from probe_harness import (
    AUTO_POWER_RESOURCE,
    CAMPAIGN_QUALIFICATION_CHECKS,
    CAMPAIGN_SELECTION_RULE,
    EXPECTED_BASE_REPO_MANIFEST_SHA256,
    EXPECTED_BUILD_INCREMENTAL,
    EXPECTED_GOLDFISH_BASE_REVISION,
    EXPECTED_GOLDFISH_DIFF_SHA256,
    EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256,
    EXPECTED_GOLDFISH_REVISION,
    EXPECTED_JOB_STATUS_SHA256,
    EXPECTED_REPO_MANIFEST_SHA256,
    EXPECTED_REVISION,
    GOLDFISH_OVERLAY_SOURCE_PATH,
    STATIC_FRAMEWORK_OVERLAY_PACKAGE,
    STATIC_FRAMEWORK_OVERLAY_PATH,
)


HARNESS_DIR = Path(__file__).resolve().parent
REPO_DIR = HARNESS_DIR.parent
EVIDENCE_NAME = re.compile(r"evidence([1-9][0-9]*)\.json")

LEGACY_EXPECTED_ANALYSIS_CHECKS = {
    "app_elapsed_intervals_enclosed_by_uptime_brackets",
    "app_ranker_matches_host_recomputation",
    "app_ranker_unique_app_standby",
    "baseline_focal_constraints_satisfied",
    "baseline_history_quiescent_across_public_query",
    "baseline_shared_zero",
    "boot_preserved",
    "callback_count_zero_at_final_query",
    "cleanup_succeeded",
    "comparator_matches_job_age",
    "dynamic_membership_proven",
    "event_protocol_structurally_valid",
    "job_pending_at_schedule_baseline_and_final",
    "job_state_waiting_not_active",
    "per_job_collapsed_prediction_equals_public_value",
    "per_job_history_exact_protocol_extension",
    "per_job_transition_times_bound_to_controller_events",
    "public_calls_from_installed_ordinary_app_uid",
    "public_ranking_reversal",
    "public_shared_exceeds_maximum_job_age",
    "reference_ranking_additive",
    "reference_ranking_union",
    "restricted_bucket_at_baseline_and_final",
    "same_jobstatus_identity",
    "schedule_baseline_events_query_timeline_proven",
    "schedule_contract_proven",
    "shared_matches_collapsed_model",
}

CAMPAIGN_EXPECTED_ANALYSIS_CHECKS = (
    LEGACY_EXPECTED_ANALYSIS_CHECKS
    - {"baseline_shared_zero"}
    | {"automatic_power_modes_stable", "baseline_shared_key_present_zero"}
)

EXPECTED_CLEANUP_CHECKS = {
    "app_absent",
    "app_uninstall_command_succeeded",
    "battery_override_cleared",
    "battery_override_exit_command_succeeded",
    "job_absent",
    "job_cancelled",
    "relevant_controller_state_restored",
}

# Fixed before the CP2A campaign. These checks establish the intended trace,
# measurement integrity, and zero focal baseline without conditioning inclusion
# on any headline over-age, model-fit, or ranking result.
QUALIFICATION_ANALYSIS_CHECKS = set(CAMPAIGN_QUALIFICATION_CHECKS)

TRANSITION_NAMES = (
    "charging_unsatisfied",
    "battery_not_low_unsatisfied",
    "battery_not_low_satisfied",
    "charging_satisfied",
)

CAMPAIGN_RAW_FIELDS = (
    "accepted_run_index",
    "evidence_number",
    "evidence_file",
    "evidence_sha256",
    "campaign_id",
    "campaign_plan_sha256",
    "outcome",
    "protocol_qualified",
    "strict_pass",
    "failed_qualification_checks",
    "failed_result_checks",
    "started_utc",
    "finished_utc",
    "run_duration_ms",
    "app_uid",
    "command_count",
    "analysis_true_checks",
    "cleanup_true_checks",
    "baseline_app_standby_present",
    "baseline_app_standby_ms",
    "baseline_device_idle_present",
    "baseline_device_idle_ms",
    "baseline_minimum_latency_present",
    "baseline_minimum_latency_ms",
    "final_app_standby_present",
    "final_app_standby_ms",
    "final_device_idle_present",
    "final_device_idle_ms",
    "final_minimum_latency_present",
    "final_minimum_latency_ms",
    "final_device_state_present",
    "final_device_state_ms",
    "final_job_scheduler_optimization_present",
    "final_job_scheduler_optimization_ms",
    "final_quota_present",
    "final_quota_ms",
    "job_age_conservative_lower_ms",
    "job_age_conservative_upper_ms",
    "job_age_app_clock_lower_ms",
    "job_age_app_clock_upper_ms",
    "union_reference_lower_ms",
    "union_reference_upper_ms",
    "additive_reference_lower_ms",
    "additive_reference_upper_ms",
    "collapsed_prediction_lower_ms",
    "collapsed_prediction_upper_ms",
    "app_standby_minus_age_upper_ms",
    "app_standby_minus_minimum_latency_ms",
    "minimum_latency_minus_union_upper_ms",
    "minimum_latency_minus_additive_upper_ms",
    "history_union_ms",
    "history_nested_battery_not_low_ms",
    "history_contributor_additive_ms",
    "history_collapsed_prediction_ms",
    "public_minus_exact_prediction_ms",
    "charging_unsatisfied_offset_ms",
    "battery_not_low_unsatisfied_offset_ms",
    "battery_not_low_satisfied_offset_ms",
    "charging_satisfied_offset_ms",
    "final_callback_count",
    "final_pending",
    "aosp_revision",
    "repo_manifest_sha256",
    "production_job_status_sha256",
    "source_sha256",
    "apk_sha256",
    "device_fingerprint",
    "device_build_id",
    "device_incremental",
    "device_security_patch",
    "boot_id",
)

CAMPAIGN_ONLY_RAW_FIELDS = {
    "campaign_id", "campaign_plan_sha256", "outcome", "protocol_qualified",
    "strict_pass", "failed_qualification_checks", "failed_result_checks",
    "baseline_app_standby_present", "baseline_device_idle_present",
    "baseline_minimum_latency_present", "final_app_standby_present",
    "final_device_idle_present", "final_minimum_latency_present",
    "final_device_state_present", "final_job_scheduler_optimization_present",
    "final_quota_present", "repo_manifest_sha256",
    "production_job_status_sha256", "device_build_id", "device_incremental",
    "device_security_patch",
}

LEGACY_RAW_FIELDS = tuple(
    field for field in CAMPAIGN_RAW_FIELDS
    if field not in CAMPAIGN_ONLY_RAW_FIELDS
)

STAT_FIELDS = (
    "metric",
    "metric_group",
    "unit",
    "n",
    "sum",
    "min",
    "p05",
    "q1",
    "median",
    "mean",
    "trimmed_mean_10pct",
    "q3",
    "p95",
    "max",
    "range",
    "iqr",
    "mode_values",
    "mode_frequency",
    "population_variance",
    "population_stddev",
    "sample_variance",
    "sample_stddev",
    "median_absolute_deviation",
    "coefficient_of_variation_percent",
    "quantile_method",
)

STAT_METRICS = (
    ("run_duration_ms", "operational", "ms"),
    ("command_count", "operational", "count"),
    ("baseline_app_standby_ms", "public_api_baseline", "ms"),
    ("baseline_device_idle_ms", "public_api_baseline", "ms"),
    ("baseline_minimum_latency_ms", "public_api_baseline", "ms"),
    ("final_app_standby_ms", "public_api_final", "ms"),
    ("final_device_idle_ms", "public_api_final", "ms"),
    ("final_minimum_latency_ms", "public_api_final", "ms"),
    ("job_age_conservative_lower_ms", "job_age", "ms"),
    ("job_age_conservative_upper_ms", "job_age", "ms"),
    ("job_age_app_clock_lower_ms", "job_age", "ms"),
    ("job_age_app_clock_upper_ms", "job_age", "ms"),
    ("union_reference_lower_ms", "interval_reference", "ms"),
    ("union_reference_upper_ms", "interval_reference", "ms"),
    ("additive_reference_lower_ms", "interval_reference", "ms"),
    ("additive_reference_upper_ms", "interval_reference", "ms"),
    ("collapsed_prediction_lower_ms", "implementation_prediction", "ms"),
    ("collapsed_prediction_upper_ms", "implementation_prediction", "ms"),
    ("app_standby_minus_age_upper_ms", "headline_margin", "ms"),
    ("app_standby_minus_minimum_latency_ms", "headline_margin", "ms"),
    ("minimum_latency_minus_union_upper_ms", "reference_margin", "ms"),
    ("minimum_latency_minus_additive_upper_ms", "reference_margin", "ms"),
    ("history_union_ms", "history_exact", "ms"),
    ("history_nested_battery_not_low_ms", "history_exact", "ms"),
    ("history_contributor_additive_ms", "history_exact", "ms"),
    ("history_collapsed_prediction_ms", "history_exact", "ms"),
    ("public_minus_exact_prediction_ms", "model_residual", "ms"),
    ("charging_unsatisfied_offset_ms", "transition_offset", "ms"),
    ("battery_not_low_unsatisfied_offset_ms", "transition_offset", "ms"),
    ("battery_not_low_satisfied_offset_ms", "transition_offset", "ms"),
    ("charging_satisfied_offset_ms", "transition_offset", "ms"),
)


class SummaryError(RuntimeError):
    pass


def positive_integer(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SummaryError(f"invalid UTC timestamp: {value!r}")
    try:
        return dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SummaryError(f"invalid UTC timestamp: {value!r}") from error


def strict_pass(attempt):
    analysis = attempt.get("analysis")
    cleanup = attempt.get("cleanup")
    analysis_checks = analysis.get("checks") if isinstance(analysis, dict) else None
    cleanup_checks = cleanup.get("checks") if isinstance(cleanup, dict) else None
    commands = attempt.get("commands")
    return (
        attempt.get("outcome") == "PASS"
        and "error" not in attempt
        and isinstance(analysis, dict)
        and analysis.get("passed") is True
        and isinstance(analysis_checks, dict)
        and (
            set(analysis_checks) == CAMPAIGN_EXPECTED_ANALYSIS_CHECKS
            if isinstance(attempt.get("campaign"), dict)
            else frozenset(analysis_checks) in {
                frozenset(LEGACY_EXPECTED_ANALYSIS_CHECKS),
                frozenset(CAMPAIGN_EXPECTED_ANALYSIS_CHECKS),
            }
        )
        and all(value is True for value in analysis_checks.values())
        and isinstance(cleanup, dict)
        and cleanup.get("succeeded") is True
        and isinstance(cleanup_checks, dict)
        and set(cleanup_checks) == EXPECTED_CLEANUP_CHECKS
        and all(value is True for value in cleanup_checks.values())
        and attempt.get("boot_id_before") == attempt.get("boot_id_after")
        and isinstance(commands, list)
        and bool(commands)
        and [command.get("seq") for command in commands]
        == list(range(1, len(commands) + 1))
        and all(
            command.get("exit_code") == 0
            and command.get("timed_out") is False
            and command.get("launch_error") is None
            for command in commands
        )
    )


def qualification_failures(attempt):
    analysis = attempt.get("analysis")
    cleanup = attempt.get("cleanup")
    analysis_checks = analysis.get("checks") if isinstance(analysis, dict) else None
    cleanup_checks = cleanup.get("checks") if isinstance(cleanup, dict) else None
    commands = attempt.get("commands")
    failures = []
    if attempt.get("outcome") not in {"PASS", "FAIL"} or "error" in attempt:
        failures.append("execution_completed_without_error")
    if (
        not isinstance(analysis_checks, dict)
        or set(analysis_checks) != CAMPAIGN_EXPECTED_ANALYSIS_CHECKS
    ):
        failures.append("analysis_check_schema_complete")
    else:
        failures.extend(
            key for key in CAMPAIGN_QUALIFICATION_CHECKS
            if analysis_checks.get(key) is not True
        )
    if not isinstance(cleanup, dict) or cleanup.get("succeeded") is not True:
        failures.append("cleanup_succeeded")
    if (
        not isinstance(cleanup_checks, dict)
        or set(cleanup_checks) != EXPECTED_CLEANUP_CHECKS
    ):
        failures.append("cleanup_check_schema_complete")
    else:
        failures.extend(
            f"cleanup:{key}" for key, value in cleanup_checks.items()
            if value is not True
        )
    if attempt.get("boot_id_before") != attempt.get("boot_id_after"):
        failures.append("boot_preserved")
    if (
        not isinstance(commands, list)
        or not commands
        or [command.get("seq") for command in commands]
        != list(range(1, len(commands) + 1))
        or any(
            command.get("exit_code") != 0
            or command.get("timed_out") is not False
            or command.get("launch_error") is not None
            for command in commands
        )
    ):
        failures.append("command_log_complete_and_successful")
    return sorted(set(failures))


def protocol_qualified(attempt):
    return not qualification_failures(attempt)


def failed_result_checks(attempt):
    analysis = attempt.get("analysis")
    checks = analysis.get("checks") if isinstance(analysis, dict) else None
    if not isinstance(checks, dict):
        return ["analysis_unavailable"]
    return sorted(
        key for key, value in checks.items()
        if key not in QUALIFICATION_ANALYSIS_CHECKS and value is not True
    )


def display_path(path):
    try:
        return path.resolve().relative_to(REPO_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_evidence(directory):
    numbered = []
    for path in directory.iterdir():
        match = EVIDENCE_NAME.fullmatch(path.name)
        if path.name.startswith("evidence") and path.suffix == ".json" and not match:
            raise SummaryError(f"noncanonical evidence filename: {path.name}")
        if match:
            if not path.is_file() or path.is_symlink():
                raise SummaryError(f"evidence path is not a regular file: {path}")
            numbered.append((int(match.group(1)), path))
    numbered.sort()
    if not numbered:
        raise SummaryError(f"no numbered evidence JSON files found in {directory}")
    numbers = [number for number, _ in numbered]
    expected = list(range(1, numbers[-1] + 1))
    if numbers != expected:
        raise SummaryError(
            f"evidence numbering must be contiguous from 1; found {numbers}"
        )

    records = []
    for number, path in numbered:
        raw = path.read_bytes()
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SummaryError(f"invalid JSON in {path}: {error}") from error
        if not isinstance(document, dict):
            raise SummaryError(f"top-level JSON is not an object: {path}")
        if document.get("schema") != 1:
            raise SummaryError(f"unexpected evidence schema in {path}")
        if document.get("experiment") != "public-api-controller-ranking":
            raise SummaryError(f"unexpected experiment in {path}")
        attempts = document.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 1:
            raise SummaryError(f"expected exactly one attempt in {path}")
        attempt = attempts[0]
        if not isinstance(attempt, dict) or attempt.get("schema") != 1:
            raise SummaryError(f"invalid attempt in {path}")
        if attempt.get("outcome") not in {"PASS", "FAIL", "ERROR"}:
            raise SummaryError(f"invalid attempt outcome in {path}")
        records.append(
            {
                "number": number,
                "path": path,
                "raw": raw,
                "attempt": attempt,
            }
        )
    return records


def require_consistent_cohort(records):
    campaign_mode = any(
        isinstance(record["attempt"].get("campaign"), dict)
        for record in records
    )

    def signature(attempt):
        build = attempt.get("build", {})
        device = attempt.get("device", {})
        campaign = attempt.get("campaign", {})
        revision = build.get(
            "frameworks_base_revision",
            build.get("source_oracle_frameworks_base_revision"),
        )
        runtime_artifacts = attempt.get(
            "runtime_artifact_sha256_by_path",
            attempt.get("runtime_artifact_sha256", {}),
        )
        return (
            attempt.get("serial"),
            attempt.get("boot_id_before"),
            attempt.get("boot_id_after"),
            device.get("ro.build.version.sdk"),
            device.get("ro.build.version.release"),
            device.get("ro.build.version.codename"),
            device.get("ro.build.version.preview_sdk"),
            device.get("ro.build.version.security_patch"),
            device.get("ro.build.fingerprint"),
            device.get("ro.build.id"),
            device.get("ro.build.version.incremental"),
            device.get("ro.build.type"),
            device.get("ro.product.name"),
            revision,
            build.get("resolved_repo_manifest_sha256"),
            build.get("base_resolved_repo_manifest_sha256"),
            build.get("goldfish_base_revision"),
            build.get("goldfish_revision"),
            build.get("goldfish_overlay_source_path"),
            build.get("goldfish_overlay_source_sha256"),
            build.get("goldfish_diff_sha256"),
            build.get("production_job_status_sha256"),
            build.get("production_source_paths_clean"),
            json.dumps(build.get("build_output_artifact_sha256", {}), sort_keys=True),
            build.get("source_sha256"),
            build.get("apk_sha256"),
            attempt.get("runtime_api_flag"),
            json.dumps(runtime_artifacts, sort_keys=True),
            json.dumps(attempt.get("automatic_power_modes_before", {}), sort_keys=True),
            json.dumps(attempt.get("automatic_power_modes_after", {}), sort_keys=True),
            json.dumps(attempt.get("protocol_seconds", {}), sort_keys=True),
            attempt.get("tolerance_ms"),
            attempt.get("clock_tolerance_ms"),
            campaign.get("id") if campaign_mode else "legacy",
            campaign.get("plan_sha256") if campaign_mode else "legacy",
            campaign.get("plan_sha256_after") if campaign_mode else "legacy",
            campaign.get("plan_unchanged") if campaign_mode else True,
        )

    expected = signature(records[0]["attempt"])
    required_indices = (
        tuple(range(len(expected)))
        if campaign_mode
        else (0, 1, 2, 3, 8, 9, 13, 24, 25, 26, 27, 30, 31, 32)
    )
    if any(expected[index] in {None, "", "{}"} for index in required_indices):
        raise SummaryError("cohort records have incomplete campaign provenance")
    if expected[3] != "37":
        raise SummaryError("cohort records are not from the required API-37 setup")
    if expected[26] != "android.app.job.get_pending_job_reason_stats_api=true":
        raise SummaryError("public pending-reason-stats API flag is not enabled")
    for digest in (expected[24], expected[25]):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise SummaryError("cohort records contain an invalid SHA-256 value")
    if campaign_mode:
        if any(not isinstance(record["attempt"].get("campaign"), dict) for record in records):
            raise SummaryError("campaign provenance is missing from some records")
        if (
            expected[4:8] != ("17", "REL", "0", "2026-06-05")
            or expected[9] != "CP2A.260605.016"
            or expected[11:13] != ("userdebug", "sdk_phone64_x86_64")
            or expected[13] != EXPECTED_REVISION
            or expected[14] != EXPECTED_REPO_MANIFEST_SHA256
            or expected[15] != EXPECTED_BASE_REPO_MANIFEST_SHA256
            or expected[16] != EXPECTED_GOLDFISH_BASE_REVISION
            or expected[17] != EXPECTED_GOLDFISH_REVISION
            or expected[18] != GOLDFISH_OVERLAY_SOURCE_PATH
            or expected[19] != EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256
            or expected[20] != EXPECTED_GOLDFISH_DIFF_SHA256
            or expected[21] != EXPECTED_JOB_STATUS_SHA256
            or expected[22] is not True
            or expected[23] != expected[27]
            or expected[26] != "android.app.job.get_pending_job_reason_stats_api=true"
            or json.loads(expected[28]).get("valid") is not True
            or expected[28] != expected[29]
            or expected[-1] is not True
            or expected[-2] != expected[-3]
        ):
            raise SummaryError("cohort records do not match the pinned r1 campaign")
    if any(signature(record["attempt"]) != expected for record in records[1:]):
        raise SummaryError("cohort records do not share one campaign provenance")


def validate_campaign_archive(records, directory, pass_count):
    campaign_records = [
        record for record in records
        if isinstance(record["attempt"].get("campaign"), dict)
    ]
    if not campaign_records:
        return False
    if len(campaign_records) != len(records):
        raise SummaryError("campaign provenance is missing from some attempt records")
    campaign_root = directory.parent
    plan_path = campaign_root / "campaign-plan.json"
    result_path = campaign_root / "campaign-result.json"
    preflight_path = campaign_root / "runtime-preflight.json"
    if (
        plan_path.is_symlink()
        or result_path.is_symlink()
        or preflight_path.is_symlink()
        or not plan_path.is_file()
        or not result_path.is_file()
        or not preflight_path.is_file()
    ):
        raise SummaryError("campaign plan or result is missing or unsafe")
    raw_plan = plan_path.read_bytes()
    plan_sha256 = sha256_bytes(raw_plan)
    try:
        plan = json.loads(raw_plan)
        result = json.loads(result_path.read_bytes())
        preflight = json.loads(preflight_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SummaryError(f"invalid campaign plan/result JSON: {error}") from error
    selection = plan.get("selection_rule") if isinstance(plan, dict) else None
    if (
        plan.get("schema") != 1
        or selection != CAMPAIGN_SELECTION_RULE
        or plan.get("qualification_checks")
        != list(CAMPAIGN_QUALIFICATION_CHECKS)
        or pass_count != 30
        or not 30 <= len(records) <= 40
    ):
        raise SummaryError(
            "campaign does not contain the fixed, headline-independent cohort"
        )
    target = plan.get("target")
    if (
        not isinstance(target, dict)
        or target.get("base_aosp_tag") != "android-17.0.0_r1"
        or target.get("release_config") != "cp2a"
        or target.get("target_product") != "sdk_phone64_x86_64"
        or target.get("target_build_variant") != "userdebug"
        or target.get("expected_build_id") != "CP2A.260605.016"
        or target.get("expected_security_patch") != "2026-06-05"
        or target.get("frameworks_base_revision") != EXPECTED_REVISION
        or target.get("resolved_manifest_sha256")
        != EXPECTED_REPO_MANIFEST_SHA256
        or target.get("base_resolved_manifest_sha256")
        != EXPECTED_BASE_REPO_MANIFEST_SHA256
        or target.get("goldfish_base_revision")
        != EXPECTED_GOLDFISH_BASE_REVISION
        or target.get("goldfish_revision") != EXPECTED_GOLDFISH_REVISION
        or target.get("goldfish_overlay_source_path")
        != GOLDFISH_OVERLAY_SOURCE_PATH
        or target.get("goldfish_overlay_source_sha256")
        != EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256
        or target.get("goldfish_diff_sha256") != EXPECTED_GOLDFISH_DIFF_SHA256
        or target.get("automatic_power_mode_resource") != AUTO_POWER_RESOURCE
        or target.get("automatic_power_mode_expected_value") is not True
        or target.get("static_framework_overlay_package")
        != STATIC_FRAMEWORK_OVERLAY_PACKAGE
        or target.get("static_framework_overlay_path")
        != STATIC_FRAMEWORK_OVERLAY_PATH
        or target.get("production_job_status_sha256")
        != EXPECTED_JOB_STATUS_SHA256
        or not isinstance(target.get("expected_fingerprint"), str)
        or not isinstance(target.get("aosp_root"), str)
        or not isinstance(target.get("product_out"), str)
    ):
        raise SummaryError("campaign plan does not identify the pinned CP2A/r1 target")
    tool_paths = plan.get("tool_paths")
    tool_hashes = plan.get("tool_sha256")
    if not isinstance(tool_paths, dict) or not isinstance(tool_hashes, dict):
        raise SummaryError("campaign plan does not identify its toolchain")
    for name, supplied_path in tool_paths.items():
        path = Path(supplied_path)
        if (
            not path.is_file()
            or path.is_symlink()
            or sha256_file(path) != tool_hashes.get(name)
        ):
            raise SummaryError(f"campaign tool does not match its plan: {name}")
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
        raise SummaryError("static-overlay provenance dumps do not match the plan")
    try:
        probe_harness.validate_emulator_zip_provenance(plan, campaign_root)
    except probe_harness.RunError as error:
        raise SummaryError(str(error)) from error
    campaign_id = plan.get("campaign_id")
    if campaign_id != campaign_root.name:
        raise SummaryError("campaign ID does not match its archive directory")
    created = parse_utc(plan.get("created_utc"))
    automatic_power_modes = preflight.get("automatic_power_modes", {})
    if (
        not isinstance(preflight, dict)
        or preflight.get("schema") != 1
        or preflight.get("campaign_id") != campaign_id
        or preflight.get("campaign_plan_sha256") != plan_sha256
        or not isinstance(preflight.get("boot_id"), str)
        or not isinstance(automatic_power_modes, dict)
        or automatic_power_modes.get("valid") is not True
    ):
        raise SummaryError("runtime preflight does not match the campaign plan")
    for record in records:
        attempt = record["attempt"]
        campaign = attempt["campaign"]
        if (
            campaign.get("id") != campaign_id
            or campaign.get("plan_loaded") is not True
            or campaign.get("plan_sha256") != plan_sha256
            or campaign.get("plan_sha256_after") != plan_sha256
            or campaign.get("plan_unchanged") is not True
            or parse_utc(attempt.get("started_utc")) <= created
            or attempt.get("device", {}).get("ro.build.fingerprint")
            != target["expected_fingerprint"]
            or attempt.get("device", {}).get("ro.build.user") != "lostboundaries"
            or attempt.get("device", {}).get("ro.build.tags") != "test-keys"
            or attempt.get("device", {}).get("ro.build.version.incremental")
            != EXPECTED_BUILD_INCREMENTAL
            or attempt.get("build", {}).get("full_source_checkout_clean") is not True
            or attempt.get("build", {}).get("aosp_root") != target["aosp_root"]
            or attempt.get("boot_id_before") != preflight["boot_id"]
            or attempt.get("boot_id_after") != preflight["boot_id"]
        ):
            raise SummaryError("attempt does not match the immutable campaign plan")
    qualified_count = sum(
        protocol_qualified(record["attempt"]) for record in records
    )
    strict_count = sum(strict_pass(record["attempt"]) for record in records)
    if (
        not isinstance(result, dict)
        or result.get("schema") != 1
        or result.get("campaign_id") != campaign_id
        or result.get("campaign_plan_sha256") != plan_sha256
        or result.get("completed") is not True
        or result.get("error") is not None
        or result.get("qualification_target") != 30
        or result.get("max_attempts") != 40
        or result.get("protocol_qualified_count") != qualified_count
        or result.get("strict_pass_count") != strict_count
        or result.get("attempt_count") != len(records)
        or result.get("boot_id") != preflight["boot_id"]
        or qualified_count != 30
        or protocol_qualified(records[-1]["attempt"]) is not True
        or sum(
            protocol_qualified(record["attempt"]) for record in records[:-1]
        ) != 29
    ):
        raise SummaryError("post-run campaign result does not match the archive")
    result_attempts = result.get("attempts")
    if not isinstance(result_attempts, list) or len(result_attempts) != len(records):
        raise SummaryError("campaign result omits retained attempts")
    for record, result_attempt in zip(records, result_attempts):
        if (
            not isinstance(result_attempt, dict)
            or result_attempt.get("number") != record["number"]
            or result_attempt.get("outcome") != record["attempt"].get("outcome")
            or result_attempt.get("protocol_qualified")
            != protocol_qualified(record["attempt"])
            or result_attempt.get("strict_pass") != strict_pass(record["attempt"])
            or result_attempt.get("failed_qualification_checks")
            != qualification_failures(record["attempt"])
            or result_attempt.get("failed_result_checks")
            != failed_result_checks(record["attempt"])
            or result_attempt.get("record_sha256")
            != sha256_bytes(record["raw"])
        ):
            raise SummaryError("campaign result disagrees with a retained attempt")
    return True


def make_raw_row(record, accepted_index):
    attempt = record["attempt"]
    analysis = attempt["analysis"]
    cleanup = attempt["cleanup"]
    observations = attempt["observations"]
    baseline = observations["baseline"]["stats_ms"]
    final_observation = observations["final"]
    final = final_observation["stats_ms"]
    bounds = analysis["interval_bounds_ms"]
    history = analysis["per_job_constraint_history"]
    reference = history["dumpsys_derived_reference_ms"]
    transitions = history["transitions"]
    by_name = {transition.get("name"): transition for transition in transitions}
    build = attempt.get("build", {})
    campaign = attempt.get("campaign", {})
    device = attempt.get("device", {})
    if len(transitions) != 4 or set(by_name) != set(TRANSITION_NAMES):
        raise SummaryError(
            f"expected the four named transitions in {record['path']}"
        )
    transitions = [by_name[name] for name in TRANSITION_NAMES]
    started = parse_utc(attempt["started_utc"])
    finished = parse_utc(attempt["finished_utc"])
    duration_us = (finished - started) // dt.timedelta(microseconds=1)
    duration_ms = (duration_us + 500) // 1000
    def optional_value(mapping, code):
        value = mapping.get(str(code))
        return int(value) if value is not None else None

    baseline_app_standby = optional_value(baseline, 2)
    baseline_device_idle = optional_value(baseline, 8)
    baseline_minimum_latency = optional_value(baseline, 9)
    app_standby = optional_value(final, 2)
    device_idle = optional_value(final, 8)
    minimum_latency = optional_value(final, 9)
    device_state = optional_value(final, 12)
    optimization = optional_value(final, 13)
    quota = optional_value(final, 14)
    age_upper = int(bounds["job_age_conservative_uptime"]["upper_ms"])
    union_upper = int(bounds["union"]["upper_ms"])
    additive_upper = int(bounds["additive"]["upper_ms"])
    collapsed_prediction = int(history["collapsed_prediction_ms"])
    reported = analysis["reported_ms"]
    if (
        app_standby is not None
        and int(reported["app_standby_minus_age_upper"])
        != app_standby - age_upper
    ):
        raise SummaryError(f"stored age margin disagrees with raw values: {record['path']}")
    if (
        app_standby is not None
        and minimum_latency is not None
        and
        int(reported["app_standby_minus_minimum_latency"])
        != app_standby - minimum_latency
    ):
        raise SummaryError(
            f"stored ranking margin disagrees with raw values: {record['path']}"
        )
    return {
        "accepted_run_index": accepted_index,
        "evidence_number": record["number"],
        "evidence_file": (
            f"runs/{record['path'].name}"
            if campaign.get("id")
            else display_path(record["path"])
        ),
        "evidence_sha256": sha256_bytes(record["raw"]),
        "campaign_id": campaign.get("id", ""),
        "campaign_plan_sha256": campaign.get("plan_sha256", ""),
        "outcome": attempt.get("outcome", ""),
        "protocol_qualified": str(protocol_qualified(attempt)).lower(),
        "strict_pass": str(strict_pass(attempt)).lower(),
        "failed_qualification_checks": ";".join(
            qualification_failures(attempt)
        ),
        "failed_result_checks": ";".join(failed_result_checks(attempt)),
        "started_utc": attempt["started_utc"],
        "finished_utc": attempt["finished_utc"],
        "run_duration_ms": duration_ms,
        "app_uid": attempt["app_uid"],
        "command_count": len(attempt["commands"]),
        "analysis_true_checks": sum(
            value is True for value in analysis["checks"].values()
        ),
        "cleanup_true_checks": sum(
            value is True for value in cleanup["checks"].values()
        ),
        "baseline_app_standby_present": str(
            baseline_app_standby is not None
        ).lower(),
        "baseline_app_standby_ms": (
            baseline_app_standby if baseline_app_standby is not None else ""
        ),
        "baseline_device_idle_present": str(
            baseline_device_idle is not None
        ).lower(),
        "baseline_device_idle_ms": (
            baseline_device_idle if baseline_device_idle is not None else ""
        ),
        "baseline_minimum_latency_present": str(
            baseline_minimum_latency is not None
        ).lower(),
        "baseline_minimum_latency_ms": (
            baseline_minimum_latency
            if baseline_minimum_latency is not None else ""
        ),
        "final_app_standby_present": str(app_standby is not None).lower(),
        "final_app_standby_ms": app_standby,
        "final_device_idle_present": str(device_idle is not None).lower(),
        "final_device_idle_ms": device_idle if device_idle is not None else "",
        "final_minimum_latency_present": str(
            minimum_latency is not None
        ).lower(),
        "final_minimum_latency_ms": minimum_latency,
        "final_device_state_present": str(device_state is not None).lower(),
        "final_device_state_ms": device_state if device_state is not None else "",
        "final_job_scheduler_optimization_present": str(
            optimization is not None
        ).lower(),
        "final_job_scheduler_optimization_ms": (
            optimization if optimization is not None else ""
        ),
        "final_quota_present": str(quota is not None).lower(),
        "final_quota_ms": quota if quota is not None else "",
        "job_age_conservative_lower_ms": int(
            bounds["job_age_conservative_uptime"]["lower_ms"]
        ),
        "job_age_conservative_upper_ms": age_upper,
        "job_age_app_clock_lower_ms": int(
            bounds["job_age_app_elapsed"]["lower_ms"]
        ),
        "job_age_app_clock_upper_ms": int(
            bounds["job_age_app_elapsed"]["upper_ms"]
        ),
        "union_reference_lower_ms": int(bounds["union"]["lower_ms"]),
        "union_reference_upper_ms": union_upper,
        "additive_reference_lower_ms": int(bounds["additive"]["lower_ms"]),
        "additive_reference_upper_ms": additive_upper,
        "collapsed_prediction_lower_ms": int(
            bounds["collapsed_implementation"]["lower_ms"]
        ),
        "collapsed_prediction_upper_ms": int(
            bounds["collapsed_implementation"]["upper_ms"]
        ),
        "app_standby_minus_age_upper_ms": (
            app_standby - age_upper if app_standby is not None else ""
        ),
        "app_standby_minus_minimum_latency_ms": (
            app_standby - minimum_latency
            if app_standby is not None and minimum_latency is not None else ""
        ),
        "minimum_latency_minus_union_upper_ms": (
            minimum_latency - union_upper
            if minimum_latency is not None else ""
        ),
        "minimum_latency_minus_additive_upper_ms": (
            minimum_latency - additive_upper
            if minimum_latency is not None else ""
        ),
        "history_union_ms": int(reference["union_ms"]),
        "history_nested_battery_not_low_ms": int(
            reference["nested_battery_not_low_ms"]
        ),
        "history_contributor_additive_ms": int(
            reference["contributor_additive_ms"]
        ),
        "history_collapsed_prediction_ms": collapsed_prediction,
        "public_minus_exact_prediction_ms": (
            app_standby - collapsed_prediction
            if app_standby is not None else ""
        ),
        "charging_unsatisfied_offset_ms": int(
            transitions[0]["offset_from_enqueue_ms"]
        ),
        "battery_not_low_unsatisfied_offset_ms": int(
            transitions[1]["offset_from_enqueue_ms"]
        ),
        "battery_not_low_satisfied_offset_ms": int(
            transitions[2]["offset_from_enqueue_ms"]
        ),
        "charging_satisfied_offset_ms": int(
            transitions[3]["offset_from_enqueue_ms"]
        ),
        "final_callback_count": int(final_observation["callback_count"]),
        "final_pending": str(final_observation["pending"]).lower(),
        "aosp_revision": build.get(
            "frameworks_base_revision",
            build.get("source_oracle_frameworks_base_revision"),
        ),
        "repo_manifest_sha256": build.get("resolved_repo_manifest_sha256", ""),
        "production_job_status_sha256": build.get(
            "production_job_status_sha256", ""
        ),
        "source_sha256": build["source_sha256"],
        "apk_sha256": build["apk_sha256"],
        "device_fingerprint": device["ro.build.fingerprint"],
        "device_build_id": device.get("ro.build.id", ""),
        "device_incremental": device.get("ro.build.version.incremental", ""),
        "device_security_patch": device.get(
            "ro.build.version.security_patch", ""
        ),
        "boot_id": attempt["boot_id_before"],
    }


def format_number(value):
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return ""
    if abs(value - round(value)) < 5e-13:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def linear_quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (
        (ordered[upper] - ordered[lower]) * (position - lower)
    )


def make_stat_row(raw_rows, metric, group, unit):
    values = [
        int(row[metric]) for row in raw_rows
        if row.get(metric) not in {None, ""}
    ]
    if not values:
        return {
            "metric": metric,
            "metric_group": group,
            "unit": unit,
            "n": 0,
            "sum": 0,
            **{
                field: "" for field in STAT_FIELDS
                if field not in {
                    "metric", "metric_group", "unit", "n", "sum",
                    "quantile_method",
                }
            },
            "quantile_method": "linear_(n-1)*p",
        }
    ordered = sorted(values)
    median = statistics.median(values)
    trim_count = math.floor(len(values) * 0.10)
    trimmed = ordered[trim_count : len(values) - trim_count]
    frequencies = Counter(values)
    mode_frequency = max(frequencies.values())
    modes = (
        sorted(value for value, count in frequencies.items() if count == mode_frequency)
        if mode_frequency > 1
        else []
    )
    q1 = linear_quantile(values, 0.25)
    q3 = linear_quantile(values, 0.75)
    mean = statistics.mean(values)
    return {
        "metric": metric,
        "metric_group": group,
        "unit": unit,
        "n": len(values),
        "sum": sum(values),
        "min": min(values),
        "p05": format_number(linear_quantile(values, 0.05)),
        "q1": format_number(q1),
        "median": format_number(median),
        "mean": format_number(mean),
        "trimmed_mean_10pct": format_number(statistics.mean(trimmed)),
        "q3": format_number(q3),
        "p95": format_number(linear_quantile(values, 0.95)),
        "max": max(values),
        "range": max(values) - min(values),
        "iqr": format_number(q3 - q1),
        "mode_values": ";".join(str(value) for value in modes),
        "mode_frequency": mode_frequency,
        "population_variance": format_number(statistics.pvariance(values)),
        "population_stddev": format_number(statistics.pstdev(values)),
        "sample_variance": (
            format_number(statistics.variance(values)) if len(values) > 1 else ""
        ),
        "sample_stddev": (
            format_number(statistics.stdev(values)) if len(values) > 1 else ""
        ),
        "median_absolute_deviation": format_number(
            statistics.median(abs(value - median) for value in values)
        ),
        "coefficient_of_variation_percent": (
            format_number(statistics.stdev(values) / mean * 100)
            if mean != 0 and len(values) > 1
            else ""
        ),
        "quantile_method": "linear_(n-1)*p",
    }


def csv_bytes(fieldnames, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=fieldnames, extrasaction="raise", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def publish_exclusive(path, data):
    if path.is_file() and not path.is_symlink():
        if path.read_bytes() == data:
            return
        raise SummaryError(f"existing output differs from regeneration: {path}")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise SummaryError(f"refusing to overwrite existing output: {path}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir", default=str(HARNESS_DIR / "harness_runs")
    )
    parser.add_argument("--pass-count", type=positive_integer, default=30)
    parser.add_argument("--require-campaign", action="store_true")
    args = parser.parse_args()

    supplied_directory = Path(args.input_dir).expanduser()
    if supplied_directory.is_symlink():
        raise SummaryError(f"input directory must not be a symlink: {supplied_directory}")
    if not supplied_directory.is_absolute():
        directory = (Path.cwd() / supplied_directory).resolve()
    else:
        directory = supplied_directory.resolve()
    if not directory.is_dir():
        raise SummaryError(f"input directory is not a regular directory: {directory}")

    raw_output = directory / f"{args.pass_count}_evidences.csv"
    stat_output = directory / f"{args.pass_count}_evidences_statistics.csv"
    for output in (raw_output, stat_output):
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise SummaryError(f"unsafe existing output: {output}")

    records = load_evidence(directory)
    campaign_mode = validate_campaign_archive(
        records, directory, args.pass_count
    )
    if args.require_campaign and not campaign_mode:
        raise SummaryError("input archive is not an immutable campaign")
    passing = [
        record for record in records
        if (
            protocol_qualified(record["attempt"])
            if campaign_mode
            else strict_pass(record["attempt"])
        )
    ]
    outcomes = Counter(record["attempt"]["outcome"] for record in records)
    if len(passing) != args.pass_count:
        raise SummaryError(
            f"expected exactly {args.pass_count} cohort records, found "
            f"{len(passing)} across {len(records)} attempts "
            f"(PASS={outcomes['PASS']}, FAIL={outcomes['FAIL']}, "
            f"ERROR={outcomes['ERROR']})"
        )
    raw_hashes = [sha256_bytes(record["raw"]) for record in passing]
    starts = [record["attempt"].get("started_utc") for record in passing]
    if len(set(raw_hashes)) != len(raw_hashes) or len(set(starts)) != len(starts):
        raise SummaryError("cohort evidence records are not one-to-one")
    windows = [
        (
            parse_utc(record["attempt"]["started_utc"]),
            parse_utc(record["attempt"]["finished_utc"]),
        )
        for record in passing
    ]
    if any(start > finish for start, finish in windows):
        raise SummaryError("cohort evidence contains a reversed time window")
    if any(previous[1] > current[0] for previous, current in zip(windows, windows[1:])):
        raise SummaryError("cohort evidence windows overlap or are out of order")
    require_consistent_cohort(records if campaign_mode else passing)
    raw_rows = [
        make_raw_row(record, index)
        for index, record in enumerate(passing, start=1)
    ]
    stat_rows = [
        make_stat_row(raw_rows, metric, group, unit)
        for metric, group, unit in STAT_METRICS
    ]

    raw_fields = CAMPAIGN_RAW_FIELDS if campaign_mode else LEGACY_RAW_FIELDS
    serialized_raw_rows = [
        {field: row.get(field, "") for field in raw_fields}
        for row in raw_rows
    ]
    raw_data = csv_bytes(raw_fields, serialized_raw_rows)
    stat_data = csv_bytes(STAT_FIELDS, stat_rows)
    publish_exclusive(raw_output, raw_data)
    publish_exclusive(stat_output, stat_data)
    print(
        f"Created {raw_output} ({len(raw_rows)} cohort rows from "
        f"{len(records)} retained attempts; "
        f"strict headline passes={sum(strict_pass(row['attempt']) for row in records)})"
    )
    print(f"Created {stat_output} ({len(stat_rows)} metric rows)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SummaryError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
