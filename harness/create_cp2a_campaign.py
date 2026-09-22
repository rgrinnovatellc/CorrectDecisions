#!/usr/bin/env python3
"""Create an immutable pre-run plan and provenance bundle for an r1 campaign."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import probe_harness


HARNESS_DIR = Path(__file__).resolve().parent
REPO_DIR = HARNESS_DIR.parent
EXPECTED_DYNAMIC_PARTITIONS_SIZE = probe_harness.EXPECTED_DYNAMIC_PARTITIONS_SIZE
EXPECTED_SUPER_PARTITION_SIZE = probe_harness.EXPECTED_SUPER_PARTITION_SIZE


class PlanError(RuntimeError):
    pass


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv, *, cwd=None):
    completed = subprocess.run(
        [str(value) for value in argv],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise PlanError(
            f"command failed ({completed.returncode}): {argv!r}\n"
            f"{completed.stderr}"
        )
    return completed.stdout


def publish_bytes(path, data):
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise PlanError(f"refusing to overwrite {path}") from error


def publish_text(path, value):
    publish_bytes(path, value.encode())


def publish_json(path, value):
    publish_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def hash_map(paths, base=None):
    result = {}
    for path in sorted(paths):
        key = path.relative_to(base).as_posix() if base is not None else str(path)
        result[key] = sha256(path)
    return result


def sha256_lines(values):
    return "".join(f"{digest}  {path}\n" for path, digest in values.items())


def validate_emulator_zip(product_out, archive):
    """Bind the packaged emulator tree to its staging tree and raw images."""
    staging_root = product_out / "emulator/x86_64"
    if not staging_root.is_dir() or staging_root.is_symlink():
        raise PlanError(f"missing regular emulator staging tree: {staging_root}")
    staged_files = {}
    for path in sorted(staging_root.rglob("*")):
        if path.is_symlink():
            raise PlanError(f"emulator staging tree contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise PlanError(f"emulator staging entry is not a regular file: {path}")
        member = "x86_64/" + path.relative_to(staging_root).as_posix()
        staged_files[member] = path

    member_hashes = {}
    try:
        with zipfile.ZipFile(archive) as zipped:
            infos = zipped.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise PlanError("emulator image ZIP contains duplicate members")
            for info in infos:
                member = PurePosixPath(info.filename)
                if (
                    member.is_absolute()
                    or member.parts[:1] != ("x86_64",)
                    or any(part in {"", ".", ".."} for part in member.parts)
                    or info.filename != member.as_posix()
                    or "\\" in info.filename
                    or bool(info.flag_bits & 0x1)
                    or not stat.S_ISREG(info.external_attr >> 16)
                ):
                    raise PlanError(
                        f"emulator image ZIP contains an unsafe/nonregular member: "
                        f"{info.filename!r}"
                    )
                digest = hashlib.sha256()
                with zipped.open(info, "r") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                member_hashes[info.filename] = digest.hexdigest()
    except zipfile.BadZipFile as error:
        raise PlanError(f"invalid emulator image ZIP: {archive}: {error}") from error

    if set(member_hashes) != set(staged_files):
        raise PlanError(
            "emulator image ZIP members differ from the complete staging tree"
        )
    staging_hashes = {
        member: sha256(path) for member, path in staged_files.items()
    }
    if member_hashes != staging_hashes:
        raise PlanError("emulator image ZIP bytes differ from the staging tree")

    source_bindings = dict(probe_harness.EMU_IMG_ZIP_SOURCE_BINDINGS)
    for member, relative_source in source_bindings.items():
        source = product_out / relative_source
        if not source.is_file() or source.is_symlink():
            raise PlanError(f"missing regular emulator ZIP source: {source}")
        if member_hashes.get(member) != sha256(source):
            raise PlanError(
                f"emulator ZIP member {member} differs from {relative_source}"
            )
    return member_hashes, source_bindings


def main():
    sdk_adb = Path.home() / "Android/Sdk/platform-tools/adb"
    default_adb = sdk_adb if sdk_adb.is_file() else Path(
        shutil.which("adb") or "/usr/lib/android-sdk/platform-tools/adb"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument(
        "--aosp-root",
        default=str(REPO_DIR.parent / "aosp-android17"),
    )
    parser.add_argument(
        "--product-out",
        default=str(
            REPO_DIR.parent
            / "aosp-android17/out-cp2a-appstandby/target/product/emu64x"
        ),
    )
    parser.add_argument("--serial", default="emulator-5584")
    parser.add_argument("--emulator-port", type=int, default=5584)
    parser.add_argument(
        "--emulator",
        default=str(
            REPO_DIR.parent
            / "aosp-android17/prebuilts/android-emulator/linux-x86_64/emulator"
        ),
    )
    parser.add_argument("--adb", default=str(default_adb))
    args = parser.parse_args()

    supplied_campaign_root = Path(args.campaign_root).expanduser()
    if supplied_campaign_root.is_symlink():
        raise PlanError(
            f"campaign root must not be a symlink: {supplied_campaign_root}"
        )
    campaign_root = supplied_campaign_root.resolve()
    aosp = Path(args.aosp_root).expanduser().resolve()
    product_out = Path(args.product_out).expanduser().resolve()
    emulator = Path(args.emulator).expanduser().resolve()
    qemu = (
        emulator.parent / "qemu/linux-x86_64/qemu-system-x86_64-headless"
    ).resolve()
    adb = Path(args.adb).expanduser().resolve()
    campaign_id = campaign_root.name
    supplied_campaigns_root = HARNESS_DIR / "campaigns"
    if supplied_campaigns_root.is_symlink():
        raise PlanError(
            f"campaign parent must not be a symlink: {supplied_campaigns_root}"
        )
    supplied_campaigns_root.mkdir(exist_ok=True)
    campaigns_root = supplied_campaigns_root.resolve()
    if campaign_root.parent != campaigns_root:
        raise PlanError(f"campaign root must be directly under {campaigns_root}")
    if not re.fullmatch(r"cp2a-r1-as-[0-9]{8}T[0-9]{6}Z", campaign_id):
        raise PlanError("campaign root must end in cp2a-r1-as-YYYYMMDDTHHMMSSZ")
    if campaign_root.exists() or campaign_root.is_symlink():
        raise PlanError(f"refusing existing campaign root: {campaign_root}")
    if args.serial != f"emulator-{args.emulator_port}":
        raise PlanError("emulator serial must match the planned console port")
    if not product_out.is_dir():
        raise PlanError(f"missing product output: {product_out}")
    for tool in (emulator, qemu, adb):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise PlanError(f"missing executable: {tool}")

    fingerprint_file = (
        product_out / "build_fingerprint-sdk_phone64_x86_64.txt"
    )
    fingerprint = fingerprint_file.read_text().strip()
    if fingerprint != probe_harness.DEFAULT_EXPECTED_FINGERPRINT:
        raise PlanError(
            f"build fingerprint is {fingerprint!r}, expected "
            f"{probe_harness.DEFAULT_EXPECTED_FINGERPRINT!r}"
        )
    build_prop = product_out / "system/build.prop"
    if not build_prop.is_file():
        raise PlanError("build has not produced system/build.prop")
    props = {}
    for line in build_prop.read_text(errors="replace").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            props[key] = value
    expected_props = {
        "ro.build.version.release": "17",
        "ro.build.version.codename": "REL",
        "ro.build.version.sdk": "37",
        "ro.build.version.preview_sdk": "0",
        "ro.build.version.incremental": probe_harness.EXPECTED_BUILD_INCREMENTAL,
        "ro.build.version.security_patch": "2026-06-05",
        "ro.build.id": "CP2A.260605.016",
        "ro.build.type": "userdebug",
        "ro.build.user": "lostboundaries",
        "ro.build.tags": "test-keys",
    }
    if any(props.get(key) != value for key, value in expected_props.items()):
        raise PlanError("system build properties do not match the final CP2A target")
    out_dir = product_out.parents[2]
    release_config = (
        out_dir
        / "soong/release-config/"
        "release_config-sdk_phone64_x86_64-cp2a.varmk"
    )
    if (
        not release_config.is_file()
        or not release_config.read_text(errors="replace").startswith(
            "# TARGET_RELEASE=cp2a\n"
        )
    ):
        raise PlanError("generated build metadata does not select TARGET_RELEASE=cp2a")
    super_misc_info = (
        product_out
        / "obj/PACKAGING/superimage_debug_intermediates/misc_info.txt"
    )
    if not super_misc_info.is_file():
        raise PlanError("build has not produced super-image configuration metadata")
    super_props = {}
    for line in super_misc_info.read_text(errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            super_props[key] = value
    expected_super_props = {
        "super_emulator_dynamic_partitions_group_size": str(
            EXPECTED_DYNAMIC_PARTITIONS_SIZE
        ),
        "super_super_device_size": str(EXPECTED_SUPER_PARTITION_SIZE),
        "super_partition_size": str(EXPECTED_SUPER_PARTITION_SIZE),
    }
    if any(
        super_props.get(key) != value
        for key, value in expected_super_props.items()
    ):
        raise PlanError(
            "emulator dynamic-partition capacity does not match the recorded "
            "2-GiB build override"
        )

    frameworks_base = aosp / "frameworks/base"
    goldfish = aosp / "device/generic/goldfish"
    manifest = run(["repo", "manifest", "-r"], cwd=aosp)
    try:
        manifest_sha256 = probe_harness.validate_configured_repo_manifest(manifest)
    except probe_harness.RunError as error:
        raise PlanError(str(error)) from error
    revision = run(
        ["git", "-C", frameworks_base, "rev-parse", "HEAD"]
    ).strip()
    if revision != probe_harness.EXPECTED_REVISION:
        raise PlanError("frameworks/base revision does not match r1")
    goldfish_revision = run(
        ["git", "-C", goldfish, "rev-parse", "HEAD"]
    ).strip()
    goldfish_parent = run(
        ["git", "-C", goldfish, "rev-parse", "HEAD^"]
    ).strip()
    if (
        goldfish_revision != probe_harness.EXPECTED_GOLDFISH_REVISION
        or goldfish_parent != probe_harness.EXPECTED_GOLDFISH_BASE_REVISION
    ):
        raise PlanError("goldfish configuration is not the pinned one-commit delta")
    goldfish_name_status = run(
        [
            "git", "-C", goldfish, "diff", "--name-status",
            goldfish_parent, goldfish_revision,
        ]
    ).strip()
    if goldfish_name_status != f"A\t{probe_harness.GOLDFISH_OVERLAY_SOURCE_PATH}":
        raise PlanError("goldfish commit does not add only the pinned overlay source")
    goldfish_diff = run(
        [
            "git", "-C", goldfish, "diff", "--binary",
            goldfish_parent, goldfish_revision,
        ]
    )
    goldfish_diff_sha256 = hashlib.sha256(goldfish_diff.encode()).hexdigest()
    overlay_source = goldfish / probe_harness.GOLDFISH_OVERLAY_SOURCE_PATH
    overlay_source_sha256 = sha256(overlay_source)
    if (
        goldfish_diff_sha256 != probe_harness.EXPECTED_GOLDFISH_DIFF_SHA256
        or overlay_source_sha256
        != probe_harness.EXPECTED_GOLDFISH_OVERLAY_SOURCE_SHA256
    ):
        raise PlanError("goldfish overlay source or commit diff does not match")
    production_status = run(
        [
            "git", "-C", frameworks_base, "status", "--porcelain", "--",
            *probe_harness.PRODUCTION_SOURCE_PATHS,
        ]
    )
    if production_status.strip():
        raise PlanError("audited production source paths are modified")
    full_checkout_status = run(
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
    if full_checkout_status.strip():
        raise PlanError(
            "AOSP checkout must be completely clean before campaign planning: "
            f"{full_checkout_status!r}"
        )
    production_paths = [
        frameworks_base / relative
        for relative in probe_harness.PRODUCTION_SOURCE_PATHS
    ]
    production_hashes = hash_map(production_paths, frameworks_base)
    if (
        production_hashes[probe_harness.PRODUCTION_SOURCE_PATHS[-1]]
        != probe_harness.EXPECTED_JOB_STATUS_SHA256
    ):
        raise PlanError("JobStatus.java does not match the pinned source")

    runtime_outputs = {
        device_path: product_out / device_path.removeprefix("/")
        for device_path in probe_harness.RUNTIME_ARTIFACT_PATHS
    }
    missing_runtime = [
        str(path) for path in runtime_outputs.values()
        if not path.is_file() or path.is_symlink()
    ]
    if missing_runtime:
        raise PlanError(f"missing runtime build outputs: {missing_runtime}")
    runtime_hashes = {
        device_path: sha256(path)
        for device_path, path in runtime_outputs.items()
    }
    aapt2 = out_dir / "host/linux-x86/bin/aapt2"
    if not aapt2.is_file() or not os.access(aapt2, os.X_OK):
        raise PlanError(f"missing build-output aapt2: {aapt2}")
    static_overlay = runtime_outputs[probe_harness.STATIC_FRAMEWORK_OVERLAY_PATH]
    overlay_badging = run([aapt2, "dump", "badging", static_overlay])
    required_badging = (
        "package: name='android.auto_generated_rro_vendor__'",
        "minSdkVersion:'37'",
        "targetSdkVersion:'37'",
        "overlay: targetPackage='android' priority='0' isStatic='true'",
    )
    if any(value not in overlay_badging for value in required_badging):
        raise PlanError("generated framework overlay manifest is not the pinned static RRO")
    overlay_resources = run([aapt2, "dump", "resources", static_overlay])
    marker = "bool/config_enableAutoPowerModes"
    if overlay_resources.count(marker) != 1:
        raise PlanError("generated framework overlay must contain the automatic-power resource once")
    resource_lines = overlay_resources.splitlines()
    marker_index = next(
        index for index, line in enumerate(resource_lines) if marker in line
    )
    following_resource = next(
        (
            index for index in range(marker_index + 1, len(resource_lines))
            if resource_lines[index].lstrip().startswith("resource ")
        ),
        len(resource_lines),
    )
    resource_values = [
        line.strip()
        for line in resource_lines[marker_index + 1:following_resource]
        if re.fullmatch(r"\([^)]*\) .+", line.strip()) is not None
    ]
    if resource_values != ["() true"]:
        raise PlanError("generated automatic-power resource is not exactly true")
    overlay_manifest = run(
        [aapt2, "dump", "xmltree", static_overlay, "--file", "AndroidManifest.xml"]
    )
    overlay_dump_hashes = {
        "badging": hashlib.sha256(overlay_badging.encode()).hexdigest(),
        "resources": hashlib.sha256(overlay_resources.encode()).hexdigest(),
        "manifest": hashlib.sha256(overlay_manifest.encode()).hexdigest(),
    }

    image_paths = sorted(
        {
            *product_out.glob("*.img"),
            *product_out.glob("kernel-ranchu*"),
            *(
                product_out / relative
                for relative in probe_harness.IMAGE_PROVENANCE_RELATIVE_PATHS
            ),
        }
    )
    image_symlinks = [str(path) for path in image_paths if path.is_symlink()]
    if image_symlinks:
        raise PlanError(f"build-image provenance paths contain symlinks: {image_symlinks}")
    image_paths = [path for path in image_paths if path.is_file()]
    if not any(path.name == "system-qemu.img" for path in image_paths):
        raise PlanError("build has not produced system-qemu.img")
    super_image = product_out / "super.img"
    if (
        not super_image.is_file()
        or super_image.stat().st_size != EXPECTED_SUPER_PARTITION_SIZE
    ):
        raise PlanError("super.img does not match the recorded partition capacity")
    for required_image in (product_out / "kernel-ranchu", product_out / "userdata.img"):
        if not required_image.is_file():
            raise PlanError(f"build has not produced required image: {required_image}")
    build_goal_archive = product_out / probe_harness.EXPECTED_BUILD_GOAL_ARTIFACT
    if not build_goal_archive.is_file():
        raise PlanError("build has not produced the emu_img_zip goal artifact")
    image_hashes = hash_map(image_paths, product_out)

    build_log = out_dir / "lostboundaries-build.log"
    build_log_tail = b""
    if build_log.is_file():
        with build_log.open("rb") as stream:
            stream.seek(max(0, build_log.stat().st_size - 256 * 1024))
            build_log_tail = stream.read().lower()
    if b"build completed successfully" not in build_log_tail:
        raise PlanError("dedicated CP2A build log has no success marker")

    zip_member_hashes, zip_source_bindings = validate_emulator_zip(
        product_out, build_goal_archive
    )

    campaign_root.mkdir()
    provenance = campaign_root / "provenance"
    provenance.mkdir()
    publish_text(provenance / "repo-manifest.xml", manifest)
    publish_text(
        provenance / "base-repo-manifest.xml",
        manifest.replace(
            probe_harness.CONFIGURED_GOLDFISH_MANIFEST_LINE,
            probe_harness.BASE_GOLDFISH_MANIFEST_LINE,
            1,
        ),
    )
    publish_text(provenance / "repo-status.txt", run(["repo", "status"], cwd=aosp))
    publish_text(provenance / "repo-porcelain.txt", full_checkout_status)
    publish_text(
        provenance / "frameworks-base.diff",
        run(["git", "-C", frameworks_base, "diff", "--binary", "HEAD"]),
    )
    publish_text(provenance / "goldfish.diff", goldfish_diff)
    publish_text(
        provenance / "goldfish-commit.txt",
        run(["git", "-C", goldfish, "show", "--no-patch", "--format=fuller", "HEAD"]),
    )
    publish_bytes(
        provenance / "goldfish-overlay-source.xml",
        overlay_source.read_bytes(),
    )
    publish_text(
        provenance / "production-source.sha256",
        sha256_lines(production_hashes),
    )
    publish_text(
        provenance / "image-files.sha256",
        sha256_lines(image_hashes),
    )
    publish_text(
        provenance / "emu-img-zip-members.sha256",
        sha256_lines(zip_member_hashes),
    )
    publish_json(
        provenance / "emu-img-zip-source-bindings.json",
        zip_source_bindings,
    )
    publish_text(
        provenance / "build-output-runtime-artifacts.sha256",
        sha256_lines(runtime_hashes),
    )
    publish_text(provenance / "static-overlay-badging.txt", overlay_badging)
    publish_text(provenance / "static-overlay-resources.txt", overlay_resources)
    publish_text(provenance / "static-overlay-manifest.txt", overlay_manifest)
    with (provenance / "build.log").open("xb") as destination:
        with build_log.open("rb") as source:
            shutil.copyfileobj(source, destination)
        destination.flush()
        os.fsync(destination.fileno())

    tool_paths = {
        "adb": adb,
        "aapt2": aapt2,
        "emulator": emulator,
        "qemu": qemu,
        "python": Path(sys.executable).resolve(),
        "create_campaign": HARNESS_DIR / "create_cp2a_campaign.py",
        "launch_campaign": HARNESS_DIR / "launch_campaign_emulator.py",
        "probe_harness": HARNESS_DIR / "probe_harness.py",
        "run_campaign": HARNESS_DIR / "run_campaign.py",
        "seal_campaign": HARNESS_DIR / "seal_campaign.py",
        "summarizer": HARNESS_DIR / "summarize_harness_runs.py",
        "sensitivity_summarizer": (
            HARNESS_DIR / "summarize_allowance_sensitivity.py"
        ),
        "table_renderer": HARNESS_DIR / "render_public_table.py",
        "makefile": REPO_DIR / "Makefile",
    }
    tool_hashes = {name: sha256(path) for name, path in tool_paths.items()}
    publish_text(provenance / "toolchain.sha256", sha256_lines(tool_hashes))
    publish_text(
        provenance / "emulator-version.txt", run([emulator, "-version"])
    )
    publish_text(provenance / "adb-version.txt", run([adb, "version"]))

    snapshot_root = provenance / "source-snapshot"
    snapshot_root.mkdir()
    snapshot_sources = set(probe_harness.source_paths())
    snapshot_sources.update(
        path for name, path in tool_paths.items()
        if name not in {"adb", "aapt2", "emulator", "qemu", "python"}
    )
    snapshot_hashes = {}
    for source in sorted(snapshot_sources):
        source = source.resolve()
        try:
            relative = source.relative_to(REPO_DIR)
        except ValueError as error:
            raise PlanError(f"source snapshot escapes the repository: {source}") from error
        destination = snapshot_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        publish_bytes(destination, source.read_bytes())
        snapshot_hashes[relative.as_posix()] = sha256(destination)
    publish_text(
        provenance / "source-snapshot.sha256",
        sha256_lines(snapshot_hashes),
    )

    runtime_dir = Path("/tmp") / f"lostboundaries-{campaign_id}"
    if runtime_dir.exists() or runtime_dir.is_symlink():
        raise PlanError(f"planned emulator runtime path already exists: {runtime_dir}")
    emulator_args = [
        "-port", str(args.emulator_port),
        "-kernel", str(product_out / "kernel-ranchu"),
        "-datadir", str(runtime_dir),
        "-data", str(runtime_dir / "userdata-qemu.img"),
        "-initdata", str(product_out / "userdata.img"),
        "-wipe-data", "-no-cache", "-no-metrics",
        "-no-window", "-no-audio", "-no-boot-anim", "-no-snapshot",
        "-read-only", "-gpu", "swiftshader_indirect",
    ]
    launch = {
        "executable": str(emulator),
        "process_executable": str(qemu),
        "adb": str(adb),
        "arguments": emulator_args,
        "serial": args.serial,
        "runtime_dir": str(runtime_dir),
        "environment": {
            "ANDROID_BUILD_TOP": str(aosp),
            "ANDROID_PRODUCT_OUT": str(product_out),
            "ANDROID_HOME": None,
            "ANDROID_SDK_ROOT": None,
        },
    }
    publish_json(provenance / "launch-profile.json", launch)
    build_configuration = {
        "base_aosp_tag": "android-17.0.0_r1",
        "build_id": "CP2A.260605.016",
        "build_number": props["ro.build.version.incremental"],
        "build_username": props["ro.build.user"],
        "build_tags": props["ro.build.tags"],
        "platform_version": props["ro.build.version.release"],
        "platform_codename": props["ro.build.version.codename"],
        "platform_sdk": int(props["ro.build.version.sdk"]),
        "platform_security_patch": props["ro.build.version.security_patch"],
        "release_config": "cp2a",
        "device_configuration": "goldfish automatic-power-mode resource overlay",
        "goldfish_base_revision": goldfish_parent,
        "goldfish_revision": goldfish_revision,
        "goldfish_overlay_source_path": probe_harness.GOLDFISH_OVERLAY_SOURCE_PATH,
        "goldfish_overlay_source_sha256": overlay_source_sha256,
        "goldfish_diff_sha256": goldfish_diff_sha256,
        "automatic_power_mode_resource": probe_harness.AUTO_POWER_RESOURCE,
        "automatic_power_mode_expected_value": True,
        "static_framework_overlay_package": (
            probe_harness.STATIC_FRAMEWORK_OVERLAY_PACKAGE
        ),
        "static_framework_overlay_path": (
            probe_harness.STATIC_FRAMEWORK_OVERLAY_PATH
        ),
        "static_framework_overlay_dump_sha256": overlay_dump_hashes,
        "target_product": "sdk_phone64_x86_64",
        "target_build_variant": "userdebug",
        "build_goal": probe_harness.EXPECTED_BUILD_GOAL,
        "build_goal_artifact": probe_harness.EXPECTED_BUILD_GOAL_ARTIFACT,
        "build_goal_zip_member_count": len(zip_member_hashes),
        "build_goal_zip_member_sha256": zip_member_hashes,
        "build_goal_zip_source_bindings": zip_source_bindings,
        "emulator_dynamic_partitions_size": EXPECTED_DYNAMIC_PARTITIONS_SIZE,
        "super_partition_size": EXPECTED_SUPER_PARTITION_SIZE,
        "product_out": str(product_out),
        "fingerprint": fingerprint,
        "build_log_sha256": sha256(build_log),
    }
    publish_json(provenance / "build-configuration.json", build_configuration)
    with (provenance / "release-config.varmk").open("xb") as destination:
        with release_config.open("rb") as source:
            shutil.copyfileobj(source, destination)
    with (provenance / "super-image-misc-info.txt").open("xb") as destination:
        with super_misc_info.open("rb") as source:
            shutil.copyfileobj(source, destination)

    plan = {
        "schema": 1,
        "campaign_id": campaign_id,
        "created_utc": utc_now(),
        "target": {
            "base_aosp_tag": "android-17.0.0_r1",
            "release_config": "cp2a",
            "target_product": "sdk_phone64_x86_64",
            "target_build_variant": "userdebug",
            "build_goal": probe_harness.EXPECTED_BUILD_GOAL,
            "build_goal_artifact": probe_harness.EXPECTED_BUILD_GOAL_ARTIFACT,
            "emulator_dynamic_partitions_size": (
                EXPECTED_DYNAMIC_PARTITIONS_SIZE
            ),
            "super_partition_size": EXPECTED_SUPER_PARTITION_SIZE,
            "expected_fingerprint": fingerprint,
            "expected_build_id": "CP2A.260605.016",
            "expected_security_patch": "2026-06-05",
            "frameworks_base_revision": revision,
            "resolved_manifest_sha256": manifest_sha256,
            "base_resolved_manifest_sha256": (
                probe_harness.EXPECTED_BASE_REPO_MANIFEST_SHA256
            ),
            "goldfish_base_revision": goldfish_parent,
            "goldfish_revision": goldfish_revision,
            "goldfish_overlay_source_path": (
                probe_harness.GOLDFISH_OVERLAY_SOURCE_PATH
            ),
            "goldfish_overlay_source_sha256": overlay_source_sha256,
            "goldfish_diff_sha256": goldfish_diff_sha256,
            "automatic_power_mode_resource": probe_harness.AUTO_POWER_RESOURCE,
            "automatic_power_mode_expected_value": True,
            "static_framework_overlay_package": (
                probe_harness.STATIC_FRAMEWORK_OVERLAY_PACKAGE
            ),
            "static_framework_overlay_path": (
                probe_harness.STATIC_FRAMEWORK_OVERLAY_PATH
            ),
            "production_job_status_sha256": (
                probe_harness.EXPECTED_JOB_STATUS_SHA256
            ),
            "aosp_root": str(aosp),
            "product_out": str(product_out),
        },
        "protocol_seconds": {
            "pre_age": probe_harness.PRE_AGE_SECONDS,
            "inner_gap": probe_harness.INNER_GAP_SECONDS,
            "overlap": probe_harness.OVERLAP_SECONDS,
            "final_gap": probe_harness.FINAL_GAP_SECONDS,
        },
        "clock_tolerance_ms": probe_harness.CLOCK_TOLERANCE_MS,
        "tolerance_ms": probe_harness.TOLERANCE_MS,
        "selection_rule": probe_harness.CAMPAIGN_SELECTION_RULE,
        "qualification_checks": list(
            probe_harness.CAMPAIGN_QUALIFICATION_CHECKS
        ),
        "harness_source_sha256": probe_harness.source_hash(),
        "build_output_runtime_artifact_sha256": runtime_hashes,
        "build_goal_zip_member_sha256": zip_member_hashes,
        "build_goal_zip_source_bindings": zip_source_bindings,
        "static_framework_overlay_dump_sha256": overlay_dump_hashes,
        "image_file_sha256": image_hashes,
        "tool_sha256": tool_hashes,
        "tool_paths": {name: str(path) for name, path in tool_paths.items()},
        "source_snapshot_sha256": snapshot_hashes,
        "launch_profile": launch,
    }
    plan_path = campaign_root / "campaign-plan.json"
    publish_json(plan_path, plan)
    for path in provenance.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for directory in sorted(
        (path for path in provenance.rglob("*") if path.is_dir()), reverse=True
    ):
        directory.chmod(0o555)
    provenance.chmod(0o555)
    plan_path.chmod(0o444)
    print(plan_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (PlanError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
