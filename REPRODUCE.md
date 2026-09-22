# Reproduction guide

This guide separates validation of the retained evidence from an independent
rerun. The first two workflows are lightweight and deterministic. A full AOSP
build and emulator campaign are optional, expensive, and produce **new**
evidence; they must never overwrite the retained campaign.

## 1. Requirements

### Evidence verification and reanalysis

A fresh GitHub clone requires Git and Git LFS. Once it is materialized, use a
Linux host with Git, GNU Make, Python 3.12 or newer, and GNU `tar`. Neither AOSP,
an Android SDK, nor an emulator is needed. Allow at least 2.5 GB of free space
for a normal materialized Git LFS clone, its local LFS object cache, and
temporary verification and reanalysis files. The materialized working tree
itself is approximately 1.03 GB.

```bash
git lfs install
git lfs pull
make verify-deep
make reanalyze
```

`verify-deep` validates the package, the sealed 31-attempt campaign, both
component bundles, the evaluated APK, the evaluated system-image ZIP, and all
cross-copies. `reanalyze` works in a temporary directory: it uses the exact
analysis source archived with the campaign to reproduce all 28 stored analysis
predicates for each attempt, then recomputes the selected cohort, statistics,
endpoint-allowance sensitivity, and manuscript table cells. It compares all
four generated outputs byte-for-byte with the sealed copies.

### Full AOSP build and end-to-end rerun

Google's current AOSP requirements specify a 64-bit x86 Linux host with glibc
2.17 or newer, at least 64 GB RAM, and at least 400 GB free disk. We recommend
at least 500 GB free disk for this target and a dedicated output directory.
More memory and CPU cores reduce build time but are not correctness
requirements. Hardware-assisted virtualization through KVM is strongly
recommended for the emulator.

The commands below use Bash and additionally require Git, the Android `repo`
tool, GNU Make, Python 3.12 or newer, and `ss` from `iproute2`. The maintained
emulator-stop path requires Linux 5.3 or newer for `os.pidfd_open()` and also
uses `signal.pidfd_send_signal()`. Run a campaign on an isolated host or user
session: launch deliberately restarts the ADB server on its default host port,
5037, to establish the planned server executable, which can interrupt unrelated
ADB devices or sessions.

The retained log records Ubuntu 24.04.4 LTS and a successful `emu_img_zip`
build in 1:34:43. It does not bind the original CPU or RAM, so that duration is
descriptive, not a runtime guarantee. This workflow builds an AOSP emulator
system image; it does not separately compile an Android kernel. The pinned
Goldfish target copies the r1 checkout's prebuilt x86_64 QEMU 6.12 kernel.

Official setup references:

- [AOSP hardware and software requirements](https://source.android.com/docs/setup/start/requirements)
- [Download AOSP source](https://source.android.com/docs/setup/download)
- [Build AOSP](https://source.android.com/docs/setup/build/building)
- [Build an AVD system image](https://source.android.com/docs/setup/test/avd)
- [Android Emulator acceleration](https://developer.android.com/studio/run/emulator-acceleration)

## 2. Pinned configuration

```text
Build ID                      CP2A.260605.016
AOSP tag                      android-17.0.0_r1
frameworks/base               94b4c163b7dfe5ce3607f7bb8456f9573f7de57d
Baseline manifest SHA-256     aed6cab4ac2995410b9b9feed2c20629b2b5db42d297ca109232bcdd56c923f1
Goldfish base                 296e55aa0244e8929e393e00e34471fef2a5d662
Goldfish configured commit    9e403c2080309c4c549dfd0dad19bfbb17b32afc
Configured manifest SHA-256   bb9554ce399669698c26f022500aef7a2d410e2d4e5619ce80f016de4ee7a15f
Product / release / variant   sdk_phone64_x86_64 / cp2a / userdebug
Build username / number       lostboundaries / lostboundaries-r1-as
Dynamic-partition override    BOARD_EMULATOR_DYNAMIC_PARTITIONS_SIZE=2147483648
Evaluated image ZIP SHA-256   8203d66999b2a8511021f420a6e98f56d58808fd1308e37b1ec1d3ff8f23574d
```

## 3. Obtain and configure the source

Set paths to this artifact root and to a new AOSP checkout:

```bash
export ARTIFACT_ROOT=/path/to/decisions-fail-loudly-artifact
export AOSP_ROOT=/path/to/aosp-android17
mkdir -p "$AOSP_ROOT"
cd "$AOSP_ROOT"

repo init --partial-clone --no-use-superproject \
  -u https://android.googlesource.com/platform/manifest \
  -b android-17.0.0_r1
repo sync -c -j8
```

Verify the focal revision and resolved baseline manifest. The semantic
comparison ignores XML whitespace, attribute order, and element order while
requiring every resolved entry and nested copy/link directive to match; this
avoids treating a different `repo` serializer as a source-tree difference:

```bash
test "$(git -C frameworks/base rev-parse HEAD)" = \
  94b4c163b7dfe5ce3607f7bb8456f9573f7de57d
repo manifest -r > /tmp/android-17.0.0_r1.xml
python3 "$ARTIFACT_ROOT/compare_resolved_manifests.py" \
  "$ARTIFACT_ROOT/aosp-source/manifests/android-17.0.0_r1.xml" \
  /tmp/android-17.0.0_r1.xml
```

Restore the exact configured Goldfish commit from the included thin bundle:

```bash
git -C device/generic/goldfish fetch \
  "$ARTIFACT_ROOT/aosp-source/goldfish/hotmobile-app-standby.bundle" \
  refs/heads/hotmobile-app-standby:refs/heads/hotmobile-app-standby
git -C device/generic/goldfish switch hotmobile-app-standby
test "$(git -C device/generic/goldfish rev-parse HEAD)" = \
  9e403c2080309c4c549dfd0dad19bfbb17b32afc
```

Confirm that no additional source change is present and that the configured
manifest and production `JobStatus.java` match the retained anchors:

```bash
checkout_status="$(repo forall -c '
  status=$(git status --porcelain=v1 --untracked-files=all) || exit $?
  if [ -n "$status" ]; then
    printf "%s\n" "$status" | sed "s|^|$REPO_PATH:|"
  fi
')" || exit $?
test -z "$checkout_status"

repo manifest -r > /tmp/android-17.0.0_r1-plus-goldfish-overlay.xml
python3 "$ARTIFACT_ROOT/compare_resolved_manifests.py" \
  "$ARTIFACT_ROOT/aosp-source/manifests/android-17.0.0_r1-plus-goldfish-overlay.xml" \
  /tmp/android-17.0.0_r1-plus-goldfish-overlay.xml
test "$(sha256sum frameworks/base/apex/jobscheduler/service/java/com/android/server/job/controllers/JobStatus.java | cut -d' ' -f1)" = \
  2a8fbe2a30f1967d677ebc9303446bd6833cb280bab11f3190a2bdb87450e7ba
```

The complete resolved manifests, source snapshots, Goldfish commit bundle,
patch, diff, and resource file are under `aosp-source/`.

## 4. Build the emulator image

Use a dedicated output directory and the recorded product metadata:

```bash
cd "$AOSP_ROOT"
export OUT_DIR="$AOSP_ROOT/out-cp2a-appstandby"
export BUILD_USERNAME=lostboundaries
export BUILD_NUMBER=lostboundaries-r1-as
export BOARD_EMULATOR_DYNAMIC_PARTITIONS_SIZE=2147483648
mkdir -p "$OUT_DIR"

source build/envsetup.sh
lunch sdk_phone64_x86_64 cp2a userdebug
set -o pipefail
m -j16 emu_img_zip 2>&1 | tee "$OUT_DIR/lostboundaries-build.log"
test "${PIPESTATUS[0]}" -eq 0
```

The package is written to:

```text
$OUT_DIR/target/product/emu64x/sdk-repo-linux-system-images.zip
```

The exact evaluated ZIP is retained under `aosp-image/`. A fresh build should
match the pinned source and product configuration, but it is not expected to be
byte-identical because AOSP embeds build-time and host metadata. The retained
ZIP is also not a complete `PRODUCT_OUT`: campaign creation requires the fresh
product output, including the initial `userdata.img`, as well as the pinned
emulator binary and an ADB binary that the new plan will identify and hash.

## 5. Probe application

`probe-app/` contains the exact seven source/build files archived by the
campaign and the exact APK installed in all 31 attempts. The APK is sufficient
for binary inspection. Before every attempt, the maintained campaign harness
invokes the offline `:app:assembleDebug` task and installs the resulting APK.

The retained command log establishes Gradle 9.6.1 in offline mode. The source
fixes Android Gradle Plugin 9.3.1 and compile/target API 37. The Java runtime,
Android SDK packages and location, and dependency cache were not plan-hashed
compiler inputs. Therefore the exact APK is preserved and verifiable as
evidence, while a fresh source build is a toolchain-informed rerun rather than
a claim of byte-identical compilation.

Provision JDK 21, Android SDK API 37, Android SDK Platform-Tools, Gradle 9.6.1,
and the AGP 9.3.1 dependencies. The retained campaign used ADB 1.0.41,
Platform-Tools build 37.0.0-14910828, with SHA-256
`00108217733707a40debfc92c86d4232fd6e68870be5966515d74c071193ea90`.
A new plan records and checks the ADB binary supplied for that rerun. Populate
the dependency cache once with network access, then verify the offline build
required by the harness:

```bash
export ANDROID_SDK_ROOT=/path/to/android-sdk
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export JAVA_HOME=/path/to/jdk-21
export GRADLE=/path/to/gradle-9.6.1/bin/gradle
export PATH="$JAVA_HOME/bin:$ANDROID_SDK_ROOT/platform-tools:$PATH"

cd "$ARTIFACT_ROOT/probe-app"
"$GRADLE" --no-daemon :app:assembleDebug
"$GRADLE" --offline --no-daemon :app:assembleDebug
```

## 6. Run a new end-to-end campaign

Return to the artifact root and define the rebuilt product and the tools that
the new plan will identify and hash:

```bash
cd "$ARTIFACT_ROOT"
export PRODUCT_OUT="$OUT_DIR/target/product/emu64x"
export ADB="$ANDROID_SDK_ROOT/platform-tools/adb"
export EMULATOR="$AOSP_ROOT/prebuilts/android-emulator/linux-x86_64/emulator"
export SERIAL=emulator-5584
export CAMPAIGN_ID="cp2a-r1-as-$(date -u +%Y%m%dT%H%M%SZ)"
export CAMPAIGN_ROOT="$ARTIFACT_ROOT/harness/campaigns/$CAMPAIGN_ID"
export CAMPAIGN_PLAN="$CAMPAIGN_ROOT/campaign-plan.json"

python3 -B harness/create_cp2a_campaign.py \
  --campaign-root "$CAMPAIGN_ROOT" \
  --aosp-root "$AOSP_ROOT" \
  --product-out "$PRODUCT_OUT" \
  --serial "$SERIAL" \
  --emulator-port 5584 \
  --emulator "$EMULATOR" \
  --adb "$ADB"
```

Plan creation fails on an unexpected source, build, image, runtime tool, or
destination. After it succeeds:

```bash
make HARNESS_CAMPAIGN_PLAN="$CAMPAIGN_PLAN" \
     HARNESS_SERIAL="$SERIAL" campaign-launch

set +e
make HARNESS_CAMPAIGN_PLAN="$CAMPAIGN_PLAN" \
     HARNESS_SERIAL="$SERIAL" campaign-run
campaign_status=$?
set -e

make HARNESS_CAMPAIGN_PLAN="$CAMPAIGN_PLAN" \
     HARNESS_SERIAL="$SERIAL" campaign-stop
test "$campaign_status" -eq 0

make HARNESS_CAMPAIGN_PLAN="$CAMPAIGN_PLAN" campaign-outputs
make HARNESS_CAMPAIGN_PLAN="$CAMPAIGN_PLAN" campaign-seal
```

The fixed selection rule retains every attempt until 30 protocol-qualified
traces are collected or 40 attempts have run; result-check outcomes do not
control qualification or stopping. Preserve an incomplete campaign for
diagnosis. Never delete a nonqualifying attempt, reuse an identifier, modify
the sealed campaign, or substitute a new run for the paper's evidence.

## 7. Rerun the component tests

First verify and extract each retained component bundle as described in
`component-tests/README.md`. The `atest` invocations below require a running
compatible emulator. The
public-campaign workflow above stops its emulator, so do not reuse that stopped
campaign directory. Before applying a component patch, repeat the plan-creation
and `campaign-launch` steps with a new component-only campaign identifier; the
launch starts another wiped CP2A emulator. Stop that emulator after the test
invocations. If reproducing both retained component executions, use separate
clean branches and separate wiped boots.

For the primary seven-test variant, create a clean branch at the pinned
`frameworks/base` revision and apply only its patch:

```bash
component_tmp="$(mktemp -d)"
tar -xzf "$ARTIFACT_ROOT/component-tests/hotmobile-component-evidence.tar.gz" \
  -C "$component_tmp"
primary_patch="$component_tmp/hotmobile-component-evidence/"\
"artifact/tests/0001-hotmobile-seven-result-tests.patch"

cd "$AOSP_ROOT/frameworks/base"
git switch -c lostboundaries-component-rerun \
  94b4c163b7dfe5ce3607f7bb8456f9573f7de57d
git apply --check "$primary_patch"
git apply "$primary_patch"
git diff --check

cd "$AOSP_ROOT"
atest -s "$SERIAL" \
  FrameworksMockingServicesTests_com_android_server_job:com.android.server.job.controllers.JobStatusTest
```

The archived primary run used the CP2A.260605.016
`sdk_phone64_x86_64`/`userdebug` substrate with API 37 and fingerprint
`Android/sdk_phone64_x86_64/emu64x:Baklava/CP2A.260605.016/eng.upgaut:userdebug/test-keys`.
The instructions above produce a newly built CP2A rerun, not that historical
fingerprint or APK byte-for-byte.

The primary variant has 71 upstream and seven added tests. The separate
reported-decrease artifact records a 71+1 variant; rerun it from another clean
branch by applying `aosp-source/frameworks-base/monotonicity.diff`, then run
the same two invocations recorded by that artifact:

```bash
TF_PREPARER_INCREMENTAL_SETUP=false atest -i -t -s "$SERIAL" \
  FrameworksMockingServicesTests_com_android_server_job:\
com.android.server.job.controllers.JobStatusTest#\
testPendingReasonStats_samePublicReasonDurationDecreasesWithoutResetCharacterization

TF_PREPARER_INCREMENTAL_SETUP=false atest -i -t -s "$SERIAL" \
  FrameworksMockingServicesTests_com_android_server_job:\
com.android.server.job.controllers.JobStatusTest
```

Do not combine the variants or describe separate executions as one run.
