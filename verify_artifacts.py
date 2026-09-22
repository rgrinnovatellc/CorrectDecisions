#!/usr/bin/env python3
"""Verify the artifact for Correct Decisions, Incorrect Diagnostic Reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT
CAMPAIGN = ROOT / "harness/campaigns/cp2a-r1-as-20260819T043340Z"
EXPECTED_CAMPAIGN_ID = "cp2a-r1-as-20260819T043340Z"
EXPECTED_BOOT_ID = "fa884bc6-f149-4d23-889a-2e44cb175e92"
EXPECTED_CAMPAIGN_PLAN_SHA256 = (
    "582ae8927a78e2d5e77b7cb15c7fc623e110bf705a0304f8cb4169e0906b77de"
)
EXPECTED_CAMPAIGN_RESULT_SHA256 = (
    "ad74c2bd0955b409e895b74b0423bb3efea7b316ab50f63c92acf98d7416bdfe"
)
EXPECTED_CAMPAIGN_MANIFEST_SHA256 = (
    "3c1c36727a1f12d34f1ab6545a58d4e7e619dd30a8a3aadb7fb7eeb321b968ac"
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
EXPECTED_QUALIFICATION_CHECKS = (
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
EXPECTED_SELECTION_RULE = {
    "qualification_target": 30,
    "max_attempts": 40,
    "retain_all_attempts": True,
    "headline_result_based_stopping": False,
    "abort_on_execution_error": True,
    "abort_on_cleanup_failure": True,
}
EXPECTED_PROTOCOL_SECONDS = {
    "pre_age": 30,
    "inner_gap": 2,
    "overlap": 15,
    "final_gap": 2,
}
EXPECTED_RESULT_CHECKS = {
    "app_ranker_unique_app_standby",
    "comparator_matches_job_age",
    "per_job_collapsed_prediction_equals_public_value",
    "public_ranking_reversal",
    "public_shared_exceeds_maximum_job_age",
    "reference_ranking_additive",
    "reference_ranking_union",
    "shared_matches_collapsed_model",
}
EXPECTED_CAMPAIGN_SOURCE_PATHS = (
    "probe-app/settings.gradle.kts",
    "probe-app/build.gradle.kts",
    "probe-app/gradle.properties",
    "probe-app/app/build.gradle.kts",
    "probe-app/app/src/main/AndroidManifest.xml",
    "probe-app/app/src/main/java/org/lostboundaries/probe/ProbeReceiver.java",
    "probe-app/app/src/main/java/org/lostboundaries/probe/HoldJobService.java",
    "harness/probe_harness.py",
)
EXPECTED_FOCAL_TRANSITIONS = (
    "charging_unsatisfied",
    "battery_not_low_unsatisfied",
    "battery_not_low_satisfied",
    "charging_satisfied",
)
EXPECTED_FOCAL_MASK_LOW_BITS = (0x2, 0x0, 0x2, 0x3)
EXPECTED_CONSTRAINT_HISTORY_ENTRIES = 10
_DUMPSYS_DURATION_RE = re.compile(
    r"^(?P<sign>[+-])"
    r"(?:(?P<days>\d+)d)?"
    r"(?:(?P<hours>\d+)h)?"
    r"(?:(?P<minutes>\d+)m)?"
    r"(?:(?P<seconds>\d+)s)?"
    r"(?P<milliseconds>\d+)ms$"
)
EXPECTED_COMPONENT_BUNDLES = {
    "hotmobile-component-evidence.tar.gz": (
        "fa7ffd7d2e01a7352dd3926ba1aa1571dafa4c1ea23ccbc7d08efc4b334dd76f",
        "hotmobile-component-evidence",
        "verify_artifact.py",
        False,
    ),
    "hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz": (
        "c77e6efb2caa5906f2c7ce4a1d51fff86ff567d7e963db13cf8ee68093e170ea",
        "hotmobile-monotonicity-r1-cp2a-20260820T000350Z",
        "verify.py",
        True,
    ),
}
EXPECTED_ARTIFACT_MANIFEST_SHA256 = {
    "aosp-image": (
        "3041599047b99c14669ac4964234bb3816cb7d7533bac5da845be1d25f60d60c"
    ),
    "aosp-source": (
        "29a9859e999602a920a20c681a48a7574c297a72a308cf8f86ca6a1de225b501"
    ),
    "component-tests": (
        "dc7469e951e8d1f5a4488d4555f7ff5526425c6adeda545f40da34292e02e641"
    ),
    "probe-app": (
        "9442b8fdf3d70026d7e4cff43361a27f7bf81ff6f341f2f698316bd0f7dd26d5"
    ),
}
EXPECTED_MAINTAINED_HARNESS_FILES = {
    "create_cp2a_campaign.py",
    "launch_campaign_emulator.py",
    "probe_harness.py",
    "render_public_table.py",
    "run_campaign.py",
    "seal_campaign.py",
    "summarize_allowance_sensitivity.py",
    "summarize_harness_runs.py",
}
EXPECTED_EXECUTED_IDENTICAL_HARNESS_FILES = {
    "render_public_table.py",
    "summarize_allowance_sensitivity.py",
    "summarize_harness_runs.py",
}
EXPECTED_MAINTAINED_CHANGED_HARNESS_FILES = (
    EXPECTED_MAINTAINED_HARNESS_FILES
    - EXPECTED_EXECUTED_IDENTICAL_HARNESS_FILES
)
EXPECTED_PROBE_SOURCE_FILES = {
    "app/build.gradle.kts",
    "app/src/main/AndroidManifest.xml",
    "app/src/main/java/org/lostboundaries/probe/HoldJobService.java",
    "app/src/main/java/org/lostboundaries/probe/ProbeReceiver.java",
    "build.gradle.kts",
    "gradle.properties",
    "settings.gradle.kts",
}
EXPECTED_POST_ACQUISITION_ADDITIONS = {
    "post-acquisition-sealing/PRE_AMENDMENT_SHA256SUMS",
    "post-acquisition-sealing/amendment.json",
    "post-acquisition-sealing/executed-sealer.py",
    "post-acquisition-sealing/planned-sealer.py",
    "post-acquisition-sealing/sealer-fix.diff",
}


class VerificationError(RuntimeError):
    pass


# Editor, operating-system, and build-tool droppings that a reviewer's own
# tooling may leave inside this package. Opening the directory in an IDE or a
# file browser must not be reportable as an integrity failure, so these are
# excluded from inventory comparisons and listed in the summary instead.
IGNORED_INVENTORY_DIRECTORIES = frozenset(
    {
        ".gradle",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".vscode",
        "__pycache__",
    }
)
IGNORED_INVENTORY_FILENAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
IGNORED_INVENTORY_ENTRIES: set[str] = set()

LFS_POINTER_MAGIC = b"version https://git-lfs.github.com/spec/v1"


def is_lfs_pointer(path: Path) -> bool:
    """Report whether ``path`` still holds an unmaterialized Git LFS pointer."""
    try:
        if path.stat().st_size > 1024:
            return False
        with path.open("rb") as stream:
            return stream.read(len(LFS_POINTER_MAGIC)) == LFS_POINTER_MAGIC
    except OSError:
        return False


def ignored_inventory_root(path: Path) -> str | None:
    """Return the entry to report when ``path`` is reviewer tooling, else None.

    Nested paths collapse to their outermost ignored directory so that one
    stray cache tree is reported once rather than once per contained file.
    """
    parts = path.relative_to(ROOT).parts
    if not parts:
        return None
    for index, part in enumerate(parts):
        if part in IGNORED_INVENTORY_DIRECTORIES:
            return PurePosixPath(*parts[: index + 1]).as_posix() + "/"
    if parts[-1] in IGNORED_INVENTORY_FILENAMES:
        return PurePosixPath(*parts).as_posix()
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"missing or unsafe regular file: {path}")


def require_same_file(left: Path, right: Path, description: str) -> None:
    require_regular(left)
    require_regular(right)
    if (
        left.stat().st_size != right.stat().st_size
        or sha256(left) != sha256(right)
    ):
        raise VerificationError(f"cross-copy mismatch: {description}")


def parse_sha256_manifest(
    path: Path, *, allow_legacy_leading_dot: bool = False
) -> dict[str, str]:
    require_regular(path)
    entries: dict[str, str] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line:
            continue
        try:
            digest, relative = line.split(None, 1)
        except ValueError as exc:
            raise VerificationError(f"malformed {path}:{number}") from exc
        relative = relative.removeprefix("*").strip()
        if allow_legacy_leading_dot and relative.startswith("./"):
            relative = relative[2:]
        pure = PurePosixPath(relative)
        if (
            len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or pure.is_absolute()
            or ".." in pure.parts
            or relative != pure.as_posix()
            or relative == "."
            or relative in entries
        ):
            raise VerificationError(f"unsafe or duplicate {path}:{number}")
        entries[relative] = digest
    if not entries:
        raise VerificationError(f"empty checksum manifest: {path}")
    return entries


def parse_device_sha256_text(value: object, description: str) -> dict[str, str]:
    """Parse the retained ``sha256sum`` form for absolute device paths."""
    if not isinstance(value, str):
        raise VerificationError(f"invalid {description}")
    entries: dict[str, str] = {}
    for number, line in enumerate(value.splitlines(), 1):
        if not line:
            continue
        try:
            digest, device_path = line.split(None, 1)
        except ValueError as exc:
            raise VerificationError(
                f"malformed {description} line {number}"
            ) from exc
        device_path = device_path.removeprefix("*").strip()
        pure = PurePosixPath(device_path)
        if (
            len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or not pure.is_absolute()
            or ".." in pure.parts
            or device_path != pure.as_posix()
            or device_path in entries
        ):
            raise VerificationError(
                f"unsafe or duplicate {description} line {number}"
            )
        entries[device_path] = digest
    if not entries:
        raise VerificationError(f"empty {description}")
    return entries


def campaign_source_hash(snapshot: Path) -> str:
    """Reproduce the acquisition harness's ordered eight-file source digest."""
    digest = hashlib.sha256()
    for relative in EXPECTED_CAMPAIGN_SOURCE_PATHS:
        path = snapshot / relative
        require_regular(path)
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def require_exact_release_inventory(expected_files: set[str]) -> None:
    """Reject package entries omitted from the root manifest.

    A reviewer may initialize this directory as a Git repository, so only the
    repository's own top-level ``.git`` entry is outside this inventory.
    """
    actual_files: set[str] = set()
    for current, directories, files in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == ROOT:
            directories[:] = [name for name in directories if name != ".git"]
            files = [name for name in files if name != ".git"]
        for name in directories:
            if name in IGNORED_INVENTORY_DIRECTORIES:
                relative = (current_path / name).relative_to(ROOT).as_posix()
                IGNORED_INVENTORY_ENTRIES.add(f"{relative}/")
        directories[:] = [
            name
            for name in directories
            if name not in IGNORED_INVENTORY_DIRECTORIES
        ]
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise VerificationError(f"unsafe release symlink: {path}")
        for name in files:
            path = current_path / name
            relative = path.relative_to(ROOT).as_posix()
            if name in IGNORED_INVENTORY_FILENAMES:
                IGNORED_INVENTORY_ENTRIES.add(relative)
                continue
            if path.is_symlink() or not path.is_file():
                raise VerificationError(f"unsafe release entry: {path}")
            actual_files.add(relative)
    if actual_files != expected_files:
        raise VerificationError(
            "release inventory mismatch: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"unexpected={sorted(actual_files - expected_files)}"
        )


def verify_manifest(
    directory: Path,
    manifest_name: str = "SHA256SUMS",
    *,
    allow_legacy_leading_dot: bool = False,
) -> int:
    entries = parse_sha256_manifest(
        directory / manifest_name,
        allow_legacy_leading_dot=allow_legacy_leading_dot,
    )
    for relative, expected in entries.items():
        target = directory / relative
        require_regular(target)
        if is_lfs_pointer(target):
            raise VerificationError(
                f"{target} is an unmaterialized Git LFS pointer rather than the "
                "payload it names; run `git lfs install && git lfs pull` in the "
                "repository root, then re-run this verifier"
            )
        actual = sha256(target)
        if actual != expected:
            raise VerificationError(
                f"digest mismatch: {target} ({actual} != {expected})"
            )
    return len(entries)


def verify_release_manifest() -> int:
    entries = parse_sha256_manifest(ROOT / "SHA256SUMS")
    required = {
        ".gitattributes",
        ".gitignore",
        "CITATION.cff",
        "CLAIMS.md",
        "compare_resolved_manifests.py",
        "LICENSES/README.md",
        "Makefile",
        "README.md",
        "REPRODUCE.md",
        "harness/SHA256SUMS",
        "probe-app/SHA256SUMS",
        "reanalyze_campaign.py",
        "verify_artifacts.py",
    }
    if not required <= set(entries):
        raise VerificationError(
            "release manifest omits required package files: "
            f"{sorted(required - set(entries))}"
        )
    require_exact_release_inventory(set(entries) | {"SHA256SUMS"})
    return verify_manifest(ROOT)


def verify_campaign_source_and_tool_bindings(
    plan: dict,
) -> tuple[str, dict[str, str]]:
    """Bind the fixed plan to its archived source and tool inventories."""
    provenance = CAMPAIGN / "provenance"
    snapshot = provenance / "source-snapshot"
    snapshot_manifest = parse_sha256_manifest(
        provenance / "source-snapshot.sha256"
    )
    if plan.get("source_snapshot_sha256") != snapshot_manifest:
        raise VerificationError(
            "campaign plan differs from its source-snapshot manifest"
        )
    require_exact_inventory(snapshot, set(snapshot_manifest), "campaign source snapshot")
    for relative, expected in snapshot_manifest.items():
        target = snapshot / relative
        require_regular(target)
        if sha256(target) != expected:
            raise VerificationError(
                f"campaign source-snapshot digest mismatch: {relative}"
            )

    tool_manifest = parse_sha256_manifest(provenance / "toolchain.sha256")
    tool_hashes = plan.get("tool_sha256")
    tool_paths = plan.get("tool_paths")
    if tool_hashes != tool_manifest:
        raise VerificationError("campaign plan differs from its toolchain manifest")
    if not isinstance(tool_paths, dict) or set(tool_paths) != set(tool_manifest):
        raise VerificationError("campaign plan tool paths and hashes disagree")
    snapshot_tools = {
        "Makefile": "makefile",
        "harness/create_cp2a_campaign.py": "create_campaign",
        "harness/launch_campaign_emulator.py": "launch_campaign",
        "harness/probe_harness.py": "probe_harness",
        "harness/render_public_table.py": "table_renderer",
        "harness/run_campaign.py": "run_campaign",
        "harness/seal_campaign.py": "seal_campaign",
        "harness/summarize_allowance_sensitivity.py": "sensitivity_summarizer",
        "harness/summarize_harness_runs.py": "summarizer",
    }
    if any(
        snapshot_manifest.get(source) != tool_manifest.get(tool)
        for source, tool in snapshot_tools.items()
    ):
        raise VerificationError(
            "campaign source snapshot and recorded tool hashes disagree"
        )

    source_digest = campaign_source_hash(snapshot)
    if plan.get("harness_source_sha256") != source_digest:
        raise VerificationError(
            "campaign plan differs from the archived eight-file source digest"
        )

    runtime_artifacts = plan.get("build_output_runtime_artifact_sha256")
    runtime_manifest_path = provenance / "build-output-runtime-artifacts.sha256"
    require_regular(runtime_manifest_path)
    recorded_runtime_artifacts = parse_device_sha256_text(
        runtime_manifest_path.read_text(),
        "build-output runtime-artifact manifest",
    )
    if (
        not isinstance(runtime_artifacts, dict)
        or runtime_artifacts != recorded_runtime_artifacts
    ):
        raise VerificationError(
            "campaign runtime-artifact provenance differs from plan"
        )

    overlay_dumps = {
        "badging": provenance / "static-overlay-badging.txt",
        "manifest": provenance / "static-overlay-manifest.txt",
        "resources": provenance / "static-overlay-resources.txt",
    }
    overlay_hashes = plan.get("static_framework_overlay_dump_sha256")
    if (
        not isinstance(overlay_hashes, dict)
        or set(overlay_hashes) != set(overlay_dumps)
        or any(sha256(path) != overlay_hashes[name]
               for name, path in overlay_dumps.items())
    ):
        raise VerificationError("campaign static-overlay provenance differs from plan")

    bindings_path = provenance / "emu-img-zip-source-bindings.json"
    require_regular(bindings_path)
    bindings = json.loads(bindings_path.read_text())
    image_files = plan.get("image_file_sha256")
    archive_members = plan.get("build_goal_zip_member_sha256")
    if (
        not isinstance(bindings, dict)
        or not bindings
        or not isinstance(image_files, dict)
        or not isinstance(archive_members, dict)
        or any(
            archive_members.get(member) is None
            or archive_members.get(member) != image_files.get(source)
            for member, source in bindings.items()
        )
    ):
        raise VerificationError("campaign image source bindings differ from plan")
    return source_digest, runtime_artifacts


def verify_post_acquisition_amendment(
    final_entries: dict[str, str], plan_sha256: str, result: dict
) -> int:
    amendment_dir = CAMPAIGN / "post-acquisition-sealing"
    pre_manifest = amendment_dir / "PRE_AMENDMENT_SHA256SUMS"
    pre_entries = parse_sha256_manifest(
        pre_manifest, allow_legacy_leading_dot=True
    )
    if (
        len(pre_entries) != 84
        or any(final_entries.get(path) != digest
               for path, digest in pre_entries.items())
        or set(final_entries) - set(pre_entries)
        != EXPECTED_POST_ACQUISITION_ADDITIONS
        or set(pre_entries) - set(final_entries)
    ):
        raise VerificationError("campaign pre/post-amendment manifests disagree")

    amendment_path = amendment_dir / "amendment.json"
    amendment = json.loads(amendment_path.read_text())
    planned = amendment.get("planned_sealer")
    executed = amendment.get("executed_sealer")
    recorded_pre = amendment.get("pre_amendment_manifest")
    stop_path = CAMPAIGN / "emulator-stop.json"
    stop = json.loads(stop_path.read_text())
    require_same_file(
        amendment_dir / "planned-sealer.py",
        CAMPAIGN / "provenance/source-snapshot/harness/seal_campaign.py",
        "planned sealer versus acquisition source snapshot",
    )
    require_same_file(
        amendment_dir / "executed-sealer.py",
        ARTIFACTS / "harness/seal_campaign.py",
        "executed corrective sealer versus maintained release copy",
    )
    if (
        amendment.get("schema") != 1
        or amendment.get("campaign_id") != EXPECTED_CAMPAIGN_ID
        or amendment.get("campaign_plan_sha256") != plan_sha256
        or amendment.get("campaign_result_sha256")
        != EXPECTED_CAMPAIGN_RESULT_SHA256
        or amendment.get("campaign_finished_utc") != result.get("finished_utc")
        or amendment.get("emulator_stop_record_sha256") != sha256(stop_path)
        or amendment.get("emulator_stopped_utc") != stop.get("stopped_utc")
        or not isinstance(planned, dict)
        or planned.get("path") != "harness/seal_campaign.py"
        or planned.get("sha256")
        != sha256(amendment_dir / "planned-sealer.py")
        or planned.get("exit_code") != 2
        or not isinstance(executed, dict)
        or executed.get("archive_path")
        != "post-acquisition-sealing/executed-sealer.py"
        or executed.get("sha256")
        != sha256(amendment_dir / "executed-sealer.py")
        or not isinstance(recorded_pre, dict)
        or recorded_pre.get("path")
        != "post-acquisition-sealing/PRE_AMENDMENT_SHA256SUMS"
        or recorded_pre.get("sha256") != sha256(pre_manifest)
        or recorded_pre.get("file_count") != len(pre_entries)
    ):
        raise VerificationError("campaign sealing amendment is inconsistent")
    return len(pre_entries)


def require_exact_inventory(
    directory: Path, expected_files: set[str], description: str
) -> None:
    expected_directories = {
        str(parent)
        for relative in expected_files
        for parent in PurePosixPath(relative).parents
        if str(parent) != "."
    }
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        ignored_root = ignored_inventory_root(path)
        if ignored_root is not None:
            IGNORED_INVENTORY_ENTRIES.add(ignored_root)
            continue
        if path.is_symlink():
            raise VerificationError(f"unsafe {description} symlink: {path}")
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_directories.add(relative)
        else:
            raise VerificationError(f"unsafe {description} entry: {path}")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise VerificationError(
            f"{description} inventory mismatch: {directory}: "
            f"missing_files={sorted(expected_files - actual_files)}, "
            f"unexpected_files={sorted(actual_files - expected_files)}, "
            "missing_directories="
            f"{sorted(expected_directories - actual_directories)}, "
            "unexpected_directories="
            f"{sorted(actual_directories - expected_directories)}"
        )


def verify_artifact_inventory() -> int:
    # The root release inventory already permits only top-level .git metadata.
    # The checks below additionally enforce every immutable payload inventory.
    for name in (*EXPECTED_ARTIFACT_MANIFEST_SHA256, "harness"):
        path = ARTIFACTS / name
        if path.is_symlink() or not path.is_dir():
            raise VerificationError(f"missing or unsafe package directory: {path}")
    for name in ("README.md", "verify_artifacts.py"):
        require_regular(ARTIFACTS / name)

    payload_count = 0
    for name, expected_manifest_sha256 in EXPECTED_ARTIFACT_MANIFEST_SHA256.items():
        directory = ARTIFACTS / name
        if directory.is_symlink() or not directory.is_dir():
            raise VerificationError(
                f"missing or unsafe artifact directory: {directory}"
            )
        manifest_path = directory / "SHA256SUMS"
        require_regular(manifest_path)
        if sha256(manifest_path) != expected_manifest_sha256:
            raise VerificationError(
                f"unexpected checksum manifest: {manifest_path}"
            )
        entries = parse_sha256_manifest(manifest_path)
        expected_files = set(entries) | {"README.md", "SHA256SUMS"}
        require_exact_inventory(directory, expected_files, "artifact")
        payload_count += len(entries)
    return payload_count


def verify_reproduction_sources() -> tuple[int, int, int]:
    harness_dir = ROOT / "harness"
    harness_manifest = parse_sha256_manifest(harness_dir / "SHA256SUMS")
    if set(harness_manifest) != EXPECTED_MAINTAINED_HARNESS_FILES:
        raise VerificationError("maintained harness manifest is unexpected")
    verify_manifest(harness_dir)
    actual_scripts = {
        path.name
        for path in harness_dir.glob("*.py")
        if path.is_file() and not path.is_symlink()
    }
    if actual_scripts != EXPECTED_MAINTAINED_HARNESS_FILES:
        raise VerificationError("maintained harness script inventory is unexpected")

    snapshot = CAMPAIGN / "provenance/source-snapshot"
    executed_harness = snapshot / "harness"
    for name in EXPECTED_MAINTAINED_HARNESS_FILES:
        current = harness_dir / name
        executed = executed_harness / name
        require_regular(current)
        require_regular(executed)
        identical = sha256(current) == sha256(executed)
        if identical != (name in EXPECTED_EXECUTED_IDENTICAL_HARNESS_FILES):
            expected = (
                "identical" if name in EXPECTED_EXECUTED_IDENTICAL_HARNESS_FILES
                else "different"
            )
            raise VerificationError(
                f"maintained/executed harness relation changed: {name} "
                f"(expected {expected})"
            )

    probe_dir = ROOT / "probe-app"
    probe_manifest = parse_sha256_manifest(probe_dir / "SHA256SUMS")
    if set(probe_manifest) != EXPECTED_PROBE_SOURCE_FILES | {
        "lostboundaries-probe-debug.apk"
    }:
        raise VerificationError("probe source/binary manifest is unexpected")
    for relative in EXPECTED_PROBE_SOURCE_FILES:
        require_same_file(
            probe_dir / relative,
            snapshot / "probe-app" / relative,
            f"released probe source versus executed snapshot: {relative}",
        )
    return (
        len(harness_manifest),
        len(EXPECTED_EXECUTED_IDENTICAL_HARNESS_FILES),
        len(EXPECTED_PROBE_SOURCE_FILES),
    )


def verify_image() -> tuple[int, int]:
    image_dir = ARTIFACTS / "aosp-image"
    archive = image_dir / "sdk-repo-linux-system-images.zip"
    require_regular(archive)
    if archive.stat().st_size < 1_000_000:
        prefix = archive.read_bytes()[:64]
        if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise VerificationError("system-image ZIP is an LFS pointer; run `git lfs pull`")
    verify_manifest(image_dir)
    expected_members = parse_sha256_manifest(
        CAMPAIGN / "provenance/emu-img-zip-members.sha256"
    )
    plan = json.loads((CAMPAIGN / "campaign-plan.json").read_text())
    if plan.get("build_goal_zip_member_sha256") != expected_members:
        raise VerificationError(
            "campaign-plan ZIP members differ from the sealed member manifest"
        )
    actual_members: dict[str, str] = {}
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            name = info.filename
            pure = PurePosixPath(name)
            if (
                name in actual_members
                or pure.is_absolute()
                or ".." in pure.parts
                or info.is_dir()
                or info.flag_bits & 0x1
                or ((info.external_attr >> 16) & 0o170000) == 0o120000
            ):
                raise VerificationError(f"unsafe ZIP member: {name}")
            digest = hashlib.sha256()
            with package.open(info) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            actual_members[name] = digest.hexdigest()
    if actual_members != expected_members:
        raise VerificationError("system-image ZIP members differ from the sealed campaign")
    return archive.stat().st_size, len(actual_members)


def command_log_valid(attempt: dict) -> bool:
    commands = attempt.get("commands")
    return (
        isinstance(commands, list)
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


def parse_dumpsys_duration_ms(token: str) -> int:
    if token == "0":
        return 0
    match = _DUMPSYS_DURATION_RE.fullmatch(token)
    if match is None:
        raise VerificationError(f"cannot parse dumpsys duration: {token!r}")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    milliseconds = int(match.group("milliseconds"))
    if hours >= 24 or minutes >= 60 or seconds >= 60 or milliseconds >= 1_000:
        raise VerificationError(f"nonnormalized dumpsys duration: {token!r}")
    value = (
        days * 86_400_000
        + hours * 3_600_000
        + minutes * 60_000
        + seconds * 1_000
        + milliseconds
    )
    if value > 2**63 - 1:
        raise VerificationError(f"out-of-range dumpsys duration: {token!r}")
    return value if match.group("sign") == "+" else -value


def final_history_offsets(final_job_dump: str, record: str) -> list[int]:
    if (
        final_job_dump.count("Constraint history:") != 1
        or final_job_dump.count("Tracking:") != 1
    ):
        raise VerificationError(f"missing constraint history: {record}")
    section = final_job_dump.split("Constraint history:", 1)[1].split(
        "Tracking:", 1
    )[0]
    entries: list[tuple[int, int]] = []
    for line in section.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(
            r"\s*(\S+)\s+=.*\[(0x[0-9a-fA-F]+)\]\s*", line
        )
        if match is None:
            raise VerificationError(f"malformed constraint history: {record}")
        entries.append(
            (parse_dumpsys_duration_ms(match.group(1)), int(match.group(2), 16))
        )
    enqueue_matches = re.findall(
        r"^\s*Enqueue time:\s*(\S+)\s*$", final_job_dump, re.MULTILINE
    )
    if (
        len(entries) != EXPECTED_CONSTRAINT_HISTORY_ENTRIES
        or len(enqueue_matches) != 1
    ):
        raise VerificationError(f"incomplete constraint history: {record}")

    focal_entries = entries[-len(EXPECTED_FOCAL_TRANSITIONS):]
    prefocal_mask = entries[-len(EXPECTED_FOCAL_TRANSITIONS) - 1][1]
    high_bits = prefocal_mask & ~0x3
    expected_masks = tuple(
        high_bits | low_bits for low_bits in EXPECTED_FOCAL_MASK_LOW_BITS
    )
    if (
        prefocal_mask != high_bits | 0x3
        or tuple(mask for _, mask in focal_entries) != expected_masks
    ):
        raise VerificationError(f"unexpected focal constraint masks: {record}")

    enqueue_relative = parse_dumpsys_duration_ms(enqueue_matches[0])
    if enqueue_relative > 0 or any(relative > 0 for relative, _ in entries):
        raise VerificationError(f"future-relative constraint history: {record}")
    offsets = [relative - enqueue_relative for relative, _ in focal_entries]
    if offsets[0] <= 0 or any(
        left >= right for left, right in zip(offsets, offsets[1:])
    ):
        raise VerificationError(f"invalid focal history offsets: {record}")
    return offsets


def verify_history_event_containment(attempt: dict, record: str) -> int:
    observations = attempt.get("observations")
    analysis = attempt.get("analysis")
    schedule = (
        observations.get("schedule") if isinstance(observations, dict) else None
    )
    events = observations.get("events") if isinstance(observations, dict) else None
    per_job_history = (
        analysis.get("per_job_constraint_history")
        if isinstance(analysis, dict)
        else None
    )
    transitions = (
        per_job_history.get("transitions")
        if isinstance(per_job_history, dict)
        else None
    )
    final_job_dump = (
        observations.get("final_job_dump")
        if isinstance(observations, dict)
        else None
    )
    if (
        not isinstance(schedule, dict)
        or not isinstance(events, list)
        or not isinstance(transitions, list)
        or not isinstance(final_job_dump, str)
        or len(events) != len(EXPECTED_FOCAL_TRANSITIONS)
        or len(transitions) != len(EXPECTED_FOCAL_TRANSITIONS)
        or not all(isinstance(value, dict) for value in events)
        or not all(isinstance(value, dict) for value in transitions)
        or tuple(value.get("name") for value in events)
        != EXPECTED_FOCAL_TRANSITIONS
        or tuple(value.get("name") for value in transitions)
        != EXPECTED_FOCAL_TRANSITIONS
    ):
        raise VerificationError(
            f"malformed history/event containment inputs: {record}"
        )

    history_offsets = final_history_offsets(final_job_dump, record)
    schedule_before = schedule.get("schedule_before_elapsed_ms")
    schedule_after = schedule.get("schedule_after_elapsed_ms")
    if (
        type(schedule_before) is not int
        or type(schedule_after) is not int
        or schedule_before < 0
        or schedule_before > schedule_after
    ):
        raise VerificationError(f"invalid app scheduling bracket: {record}")

    for event, transition, history_offset in zip(
        events, transitions, history_offsets
    ):
        event_lower = event.get("lower_uptime_ms")
        event_upper = event.get("upper_uptime_ms")
        recorded_offset = transition.get("offset_from_enqueue_ms")
        if (
            type(event_lower) is not int
            or type(event_upper) is not int
            or type(recorded_offset) is not int
            or event_lower < 0
            or event_lower > event_upper
        ):
            raise VerificationError(
                f"invalid history/event containment values: {record} "
                f"({event['name']})"
            )
        if recorded_offset != history_offset:
            raise VerificationError(
                f"history offset mismatch: {record} ({event['name']}): "
                f"raw dump gives {history_offset} ms, analysis records "
                f"{recorded_offset} ms"
            )
        derived_lower = schedule_before + history_offset
        derived_upper = schedule_after + history_offset
        if not (event_lower <= derived_lower <= derived_upper <= event_upper):
            raise VerificationError(
                f"history/event containment failed: {record} ({event['name']}): "
                f"derived elapsed-realtime interval [{derived_lower}, {derived_upper}] ms "
                f"is outside raw event uptime bracket [{event_lower}, {event_upper}] ms"
            )
    return len(transitions)


def attempt_disposition(
    attempt: dict, qualification_checks: list[str]
) -> tuple[bool, bool, list[str], list[str]]:
    analysis = attempt.get("analysis")
    checks = analysis.get("checks") if isinstance(analysis, dict) else None
    cleanup = attempt.get("cleanup")
    cleanup_checks = cleanup.get("checks") if isinstance(cleanup, dict) else None
    failures: list[str] = []
    if attempt.get("outcome") not in {"PASS", "FAIL"} or "error" in attempt:
        failures.append("execution_completed_without_error")
    expected_analysis_checks = set(qualification_checks) | EXPECTED_RESULT_CHECKS
    if not isinstance(checks, dict) or set(checks) != expected_analysis_checks:
        failures.append("analysis_check_schema_complete")
    else:
        failures.extend(key for key in qualification_checks if checks.get(key) is not True)
    if not isinstance(cleanup, dict) or cleanup.get("succeeded") is not True:
        failures.append("cleanup_succeeded")
    if not isinstance(cleanup_checks, dict) or set(cleanup_checks) != EXPECTED_CLEANUP_CHECKS:
        failures.append("cleanup_check_schema_complete")
    else:
        failures.extend(
            f"cleanup:{key}"
            for key, value in cleanup_checks.items()
            if value is not True
        )
    if attempt.get("boot_id_before") != attempt.get("boot_id_after"):
        failures.append("boot_preserved")
    if not command_log_valid(attempt):
        failures.append("command_log_complete_and_successful")
    failures = sorted(set(failures))
    result_failures = (
        ["analysis_unavailable"]
        if not isinstance(checks, dict)
        else sorted(
            key
            for key, value in checks.items()
            if key not in set(qualification_checks) and value is not True
        )
    )
    strict = (
        attempt.get("outcome") == "PASS"
        and "error" not in attempt
        and isinstance(analysis, dict)
        and analysis.get("passed") is True
        and isinstance(checks, dict)
        and set(checks) == expected_analysis_checks
        and all(value is True for value in checks.values())
        and isinstance(cleanup, dict)
        and cleanup.get("succeeded") is True
        and isinstance(cleanup_checks, dict)
        and set(cleanup_checks) == EXPECTED_CLEANUP_CHECKS
        and all(value is True for value in cleanup_checks.values())
        and attempt.get("boot_id_before") == attempt.get("boot_id_after")
        and command_log_valid(attempt)
    )
    return not failures, strict, failures, result_failures


def verify_campaign() -> tuple[int, int, int, int]:
    if sha256(CAMPAIGN / "SHA256SUMS") != EXPECTED_CAMPAIGN_MANIFEST_SHA256:
        raise VerificationError("sealed campaign manifest anchor is unexpected")
    final_entries = parse_sha256_manifest(CAMPAIGN / "SHA256SUMS")
    require_exact_inventory(
        CAMPAIGN,
        set(final_entries) | {"SHA256SUMS"},
        "sealed campaign",
    )
    final_count = verify_manifest(CAMPAIGN)
    pre_manifest = CAMPAIGN / "post-acquisition-sealing/PRE_AMENDMENT_SHA256SUMS"
    pre_count = verify_manifest(
        CAMPAIGN,
        str(pre_manifest.relative_to(CAMPAIGN)),
        allow_legacy_leading_dot=True,
    )
    plan_path = CAMPAIGN / "campaign-plan.json"
    plan_raw = plan_path.read_bytes()
    plan = json.loads(plan_raw)
    plan_sha256 = hashlib.sha256(plan_raw).hexdigest()
    if plan_sha256 != EXPECTED_CAMPAIGN_PLAN_SHA256:
        raise VerificationError("sealed campaign plan anchor is unexpected")
    if not isinstance(plan, dict):
        raise VerificationError("sealed campaign plan is not an object")
    qualification_checks = plan.get("qualification_checks")
    if (
        plan.get("schema") != 1
        or plan.get("campaign_id") != EXPECTED_CAMPAIGN_ID
        or qualification_checks != list(EXPECTED_QUALIFICATION_CHECKS)
        or plan.get("selection_rule") != EXPECTED_SELECTION_RULE
        or plan.get("clock_tolerance_ms") != 20
        or plan.get("tolerance_ms") != 500
        or plan.get("protocol_seconds") != EXPECTED_PROTOCOL_SECONDS
    ):
        raise VerificationError("sealed campaign plan is unexpected")
    source_digest, runtime_artifacts = verify_campaign_source_and_tool_bindings(plan)
    result_path = CAMPAIGN / "campaign-result.json"
    if sha256(result_path) != EXPECTED_CAMPAIGN_RESULT_SHA256:
        raise VerificationError("sealed campaign result anchor is unexpected")
    result = json.loads(result_path.read_text())
    if not isinstance(result, dict):
        raise VerificationError("sealed campaign result is not an object")
    if (
        result.get("schema") != 1
        or result.get("campaign_id") != EXPECTED_CAMPAIGN_ID
        or result.get("campaign_plan_sha256") != plan_sha256
        or result.get("completed") is not True
        or result.get("error") is not None
        or result.get("qualification_target") != 30
        or result.get("max_attempts") != 40
        or result.get("boot_id") != EXPECTED_BOOT_ID
        or result.get("attempt_count") != 31
        or result.get("protocol_qualified_count") != 30
        or result.get("strict_pass_count") != 30
    ):
        raise VerificationError("sealed campaign result summary is unexpected")
    if verify_post_acquisition_amendment(final_entries, plan_sha256, result) != pre_count:
        raise VerificationError("campaign pre-amendment file count is inconsistent")
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 31:
        raise VerificationError("sealed campaign attempt index is incomplete")
    preflight = json.loads((CAMPAIGN / "runtime-preflight.json").read_text())
    if not isinstance(preflight, dict):
        raise VerificationError("sealed campaign runtime preflight is not an object")
    automatic_power_modes = preflight.get("automatic_power_modes")
    if (
        preflight.get("schema") != 1
        or preflight.get("campaign_id") != EXPECTED_CAMPAIGN_ID
        or preflight.get("campaign_plan_sha256") != plan_sha256
        or preflight.get("boot_id") != EXPECTED_BOOT_ID
        or preflight.get("runtime_artifact_sha256") != runtime_artifacts
        or not isinstance(automatic_power_modes, dict)
        or automatic_power_modes.get("valid") is not True
    ):
        raise VerificationError("sealed campaign runtime preflight is unexpected")
    qualified_count = 0
    strict_count = 0
    contained_transition_count = 0
    apk_digests: set[str] = set()
    qualified_dispositions: list[bool] = []
    for expected_number, index in enumerate(attempts, 1):
        expected_record = f"runs/evidence{expected_number}.json"
        if index.get("number") != expected_number or index.get("record") != expected_record:
            raise VerificationError("campaign attempt index is not contiguous")
        record_path = CAMPAIGN / expected_record
        require_regular(record_path)
        if sha256(record_path) != index.get("record_sha256"):
            raise VerificationError(f"attempt index digest mismatch: {expected_record}")
        document = json.loads(record_path.read_text())
        raw_attempts = document.get("attempts")
        if (
            document.get("schema") != 1
            or document.get("experiment") != "public-api-controller-ranking"
            or not isinstance(raw_attempts, list)
            or len(raw_attempts) != 1
        ):
            raise VerificationError(f"invalid raw attempt wrapper: {expected_record}")
        attempt = raw_attempts[0]
        campaign = attempt.get("campaign")
        if (
            attempt.get("outcome") != index.get("outcome")
            or attempt.get("boot_id_before") != EXPECTED_BOOT_ID
            or attempt.get("boot_id_after") != EXPECTED_BOOT_ID
            or not isinstance(campaign, dict)
            or campaign.get("id") != EXPECTED_CAMPAIGN_ID
            or campaign.get("plan_sha256") != plan_sha256
            or campaign.get("plan_sha256_after") != plan_sha256
            or campaign.get("plan_unchanged") is not True
        ):
            raise VerificationError(f"raw attempt provenance mismatch: {expected_record}")
        qualified, strict, failed_qualification, failed_result = attempt_disposition(
            attempt, qualification_checks
        )
        if (
            index.get("protocol_qualified") is not qualified
            or index.get("strict_pass") is not strict
            or index.get("failed_qualification_checks") != failed_qualification
            or index.get("failed_result_checks") != failed_result
        ):
            raise VerificationError(f"attempt disposition mismatch: {expected_record}")
        qualified_count += int(qualified)
        strict_count += int(strict)
        qualified_dispositions.append(qualified)
        contained_transition_count += verify_history_event_containment(
            attempt, expected_record
        )
        build = attempt.get("build")
        if not isinstance(build, dict):
            raise VerificationError(f"attempt build provenance is missing: {expected_record}")
        if (
            build.get("source_sha256") != source_digest
            or build.get("source_sha256_after") != source_digest
            or build.get("build_output_artifact_sha256") != runtime_artifacts
            or build.get("build_output_artifact_sha256_after") != runtime_artifacts
            or attempt.get("runtime_artifact_sha256_by_path") != runtime_artifacts
            or parse_device_sha256_text(
                attempt.get("runtime_artifact_sha256"),
                f"runtime-artifact observation in {expected_record}",
            )
            != runtime_artifacts
        ):
            raise VerificationError(
                f"attempt source/runtime provenance mismatch: {expected_record}"
            )
        apk_digests.add(build.get("apk_sha256"))
    if qualified_count != 30 or strict_count != 30:
        raise VerificationError("raw campaign cohort counts are unexpected")
    if (
        not qualified_dispositions
        or qualified_dispositions[-1] is not True
        or sum(qualified_dispositions[:-1]) != 29
        or len(qualified_dispositions) > EXPECTED_SELECTION_RULE["max_attempts"]
    ):
        raise VerificationError(
            "campaign did not stop when the fixed qualification target was reached"
        )
    if contained_transition_count != 124:
        raise VerificationError("raw campaign transition count is unexpected")
    copied_apk = ARTIFACTS / "probe-app/lostboundaries-probe-debug.apk"
    if apk_digests != {sha256(copied_apk)}:
        raise VerificationError("released probe APK differs from the campaign")
    target = plan.get("target")
    if not isinstance(target, dict):
        raise VerificationError("sealed campaign target is missing")
    source_bindings = {
        ARTIFACTS / "aosp-source/manifests/android-17.0.0_r1.xml":
            target.get("base_resolved_manifest_sha256"),
        ARTIFACTS / "aosp-source/manifests/android-17.0.0_r1-plus-goldfish-overlay.xml":
            target.get("resolved_manifest_sha256"),
        ARTIFACTS / "aosp-source/frameworks-base/JobStatus.android-17.0.0_r1.java":
            target.get("production_job_status_sha256"),
        ARTIFACTS / "aosp-source/goldfish/enable-automatic-power-modes.diff":
            target.get("goldfish_diff_sha256"),
        ARTIFACTS / "aosp-source/goldfish/lostboundaries_app_standby.xml":
            target.get("goldfish_overlay_source_sha256"),
    }
    if any(sha256(path) != expected for path, expected in source_bindings.items()):
        raise VerificationError("released AOSP source inputs differ from the campaign plan")
    production_sources = parse_sha256_manifest(
        CAMPAIGN / "provenance/production-source.sha256"
    )
    campaign_source_copies = {
        "apex/jobscheduler/framework/java/android/app/JobSchedulerImpl.java":
            ARTIFACTS / (
                "aosp-source/frameworks-base/"
                "JobSchedulerImpl.android-17.0.0_r1.java"
            ),
        "apex/jobscheduler/service/java/com/android/server/job/"
        "JobSchedulerService.java": ARTIFACTS / (
            "aosp-source/frameworks-base/"
            "JobSchedulerService.android-17.0.0_r1.java"
        ),
        "apex/jobscheduler/service/java/com/android/server/job/controllers/"
        "JobStatus.java": ARTIFACTS / (
            "aosp-source/frameworks-base/JobStatus.android-17.0.0_r1.java"
        ),
    }
    for upstream_path, copied_path in campaign_source_copies.items():
        if (
            production_sources.get(upstream_path) is None
            or sha256(copied_path) != production_sources[upstream_path]
        ):
            raise VerificationError(
                "released source snapshot differs from sealed campaign provenance: "
                f"{upstream_path}"
            )
    image_archive = ARTIFACTS / "aosp-image/sdk-repo-linux-system-images.zip"
    if sha256(image_archive) != plan.get("image_file_sha256", {}).get(image_archive.name):
        raise VerificationError("released system-image ZIP differs from the campaign plan")
    return final_count, pre_count, len(attempts), contained_transition_count


def verify_component_bundles(deep: bool) -> int:
    component_dir = ARTIFACTS / "component-tests"
    manifest = parse_sha256_manifest(component_dir / "SHA256SUMS")
    expected_digests = {
        name: metadata[0] for name, metadata in EXPECTED_COMPONENT_BUNDLES.items()
    }
    if manifest != expected_digests:
        raise VerificationError("component-bundle manifest is unexpected")
    verify_manifest(component_dir)
    if not deep:
        return 0
    tar = shutil.which("tar")
    if tar is None:
        raise VerificationError("deep verification requires GNU tar")
    executed = 0
    for archive_name, (_, root_name, verifier_name, verify_archive) in (
        EXPECTED_COMPONENT_BUNDLES.items()
    ):
        archive = component_dir / archive_name
        with tempfile.TemporaryDirectory(
            prefix="lostboundaries-component-"
        ) as temporary:
            destination = Path(temporary)
            names: set[str] = set()
            with tarfile.open(archive, "r:gz") as package:
                members = package.getmembers()
                if not members:
                    raise VerificationError(f"empty component bundle: {archive_name}")
                for member in members:
                    pure = PurePosixPath(member.name)
                    if (
                        not member.name
                        or member.name in names
                        or pure.is_absolute()
                        or ".." in pure.parts
                        or not pure.parts
                        or pure.parts[0] != root_name
                        or not (member.isfile() or member.isdir())
                    ):
                        raise VerificationError(
                            f"unsafe component member in {archive_name}: {member.name}"
                        )
                    names.add(member.name)
            # GNU tar preserves the nanosecond mtimes bound by the older raw
            # inventory. Both archives were constrained above to one relative
            # tree containing only regular files and directories.
            extracted = subprocess.run(
                [tar, "-xzf", str(archive), "-C", str(destination)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if extracted.returncode != 0:
                raise VerificationError(
                    f"component extraction failed ({archive_name}):\n"
                    + extracted.stdout
                )
            verifier = destination / root_name / verifier_name
            require_regular(verifier)
            command = [sys.executable, "-I", str(verifier)]
            if verify_archive:
                command.append(str(archive))
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if completed.returncode != 0:
                raise VerificationError(
                    f"component verifier failed ({archive_name}):\n"
                    + completed.stdout.rstrip()
                )
            source_dir = ARTIFACTS / "aosp-source/frameworks-base"
            extracted_root = destination / root_name
            if archive_name == "hotmobile-component-evidence.tar.gz":
                component_source_manifest = json.loads(
                    (
                        extracted_root / "artifact/source/MANIFEST.json"
                    ).read_text()
                )
                component_source_hashes = {
                    entry.get("artifact_path"): entry.get("full_sha256")
                    for entry in component_source_manifest.get("files", [])
                    if isinstance(entry, dict)
                }
                component_source_copies = {
                    "IJobScheduler.aidl.txt":
                        "IJobScheduler.android-17.0.0_r1.aidl",
                    "JobScheduler.java.txt":
                        "JobScheduler.android-17.0.0_r1.java",
                    "JobSchedulerImpl.java.txt":
                        "JobSchedulerImpl.android-17.0.0_r1.java",
                    "JobSchedulerService.java.txt":
                        "JobSchedulerService.android-17.0.0_r1.java",
                    "JobStatus.java.txt": "JobStatus.android-17.0.0_r1.java",
                }
                for archived_name, copied_name in component_source_copies.items():
                    copied_path = source_dir / copied_name
                    require_regular(copied_path)
                    if (
                        component_source_hashes.get(archived_name) is None
                        or sha256(copied_path)
                        != component_source_hashes[archived_name]
                    ):
                        raise VerificationError(
                            "released source snapshot differs from original "
                            f"component source manifest: {copied_name}"
                        )
                require_same_file(
                    source_dir / "JobStatusTest.android-17.0.0_r1.java",
                    extracted_root / "artifact/tests/JobStatusTest.pre-patch.java",
                    "pristine JobStatusTest versus original component bundle",
                )
                nested_archive = (
                    extracted_root
                    / "artifact/evidence/historical-run/sealed-16-test-run.tar.gz"
                )
                require_regular(nested_archive)
                expected_nested = {
                    "0001-sixteen-test-historical.patch":
                        source_dir / "sixteen-test-variant.diff",
                    "raw/JobStatus.java": (
                        source_dir / "JobStatus.android-17.0.0_r1.java"
                    ),
                    "raw/JobStatusTest.java": (
                        source_dir
                        / "JobStatusTest.sixteen-test-variant.java"
                    ),
                }
                with tarfile.open(nested_archive, "r:gz") as nested:
                    for member_name, external in expected_nested.items():
                        try:
                            member = nested.getmember(member_name)
                        except KeyError as exc:
                            raise VerificationError(
                                f"missing historical component member: {member_name}"
                            ) from exc
                        if not member.isfile():
                            raise VerificationError(
                                f"unsafe historical component member: {member_name}"
                            )
                        stream = nested.extractfile(member)
                        if stream is None:
                            raise VerificationError(
                                f"unreadable historical component member: {member_name}"
                            )
                        digest = hashlib.sha256()
                        with stream:
                            for block in iter(
                                lambda: stream.read(1024 * 1024), b""
                            ):
                                digest.update(block)
                        require_regular(external)
                        if (
                            member.size != external.stat().st_size
                            or digest.hexdigest() != sha256(external)
                        ):
                            raise VerificationError(
                                "cross-copy mismatch: historical component "
                                f"member {member_name}"
                            )
            elif archive_name == (
                "hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz"
            ):
                archive_source = extracted_root / "provenance/source"
                cross_copies = {
                    "JobStatus.java": "JobStatus.android-17.0.0_r1.java",
                    "JobStatusTest.pristine.java":
                        "JobStatusTest.android-17.0.0_r1.java",
                    "JobStatusTest.executed.java":
                        "JobStatusTest.monotonicity-variant.java",
                    "monotonicity.patch": "monotonicity.diff",
                    "mockingservicestests.Android.bp":
                        "mockingservicestests.Android.bp",
                    "service-jobscheduler.Android.bp":
                        "service-jobscheduler.Android.bp",
                }
                for archived_name, external_name in cross_copies.items():
                    require_same_file(
                        archive_source / archived_name,
                        source_dir / external_name,
                        f"reported-decrease bundle source {archived_name}",
                    )
            executed += 1
    return executed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deep",
        action="store_true",
        help="extract the component bundles and run their internal verifiers",
    )
    args = parser.parse_args()
    try:
        release_files = verify_release_manifest()
        payload_count = verify_artifact_inventory()
        source_count = verify_manifest(ARTIFACTS / "aosp-source")
        probe_count = verify_manifest(ARTIFACTS / "probe-app")
        image_bytes, image_members = verify_image()
        component_verifiers = verify_component_bundles(args.deep)
        (
            campaign_files,
            pre_files,
            attempts,
            contained_transitions,
        ) = verify_campaign()
        (
            maintained_harness_files,
            executed_identical_files,
            probe_source_files,
        ) = verify_reproduction_sources()
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile,
            tarfile.TarError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: standalone artifacts are internally consistent")
    print(f"  release manifest: {release_files} files")
    print(f"  artifact payload inventory: {payload_count} files")
    print(f"  AOSP source inputs: {source_count} files")
    print(f"  probe application: {probe_count} files")
    print(f"  emulator package: {image_bytes} bytes, {image_members} members")
    print(
        "  sealed campaign manifest: "
        f"{campaign_files} entries ({pre_files} pre-amendment entries)"
    )
    print(
        f"  campaign attempts: {attempts} retained, "
        "30 protocol-qualified, 30 strict passes"
    )
    print(
        "  history/event containment: "
        f"{contained_transitions} focal transitions across all "
        f"{attempts} retained attempts"
    )
    print(
        "  maintained harness: "
        f"{maintained_harness_files} scripts "
        f"({executed_identical_files} byte-identical analysis scripts)"
    )
    print(f"  executed probe source: {probe_source_files} files")
    print(f"  component verifiers executed: {component_verifiers}")
    if IGNORED_INVENTORY_ENTRIES:
        print(
            "  ignored reviewer tooling artifacts: "
            f"{len(IGNORED_INVENTORY_ENTRIES)} "
            f"({', '.join(sorted(IGNORED_INVENTORY_ENTRIES))})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
