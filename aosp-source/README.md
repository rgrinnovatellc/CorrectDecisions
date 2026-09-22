# AOSP source inputs and test variants

This directory contains the source material that differs from, or is necessary
to interpret, the pinned AOSP checkout. It is deliberately not a copy of the
entire AOSP tree. The resolved manifests identify every project and revision so
the full source can be obtained from AOSP.

## Pinned source cited by the manuscript

The complete files below are byte-identical snapshots from the pinned
`frameworks/base` revision
`94b4c163b7dfe5ce3607f7bb8456f9573f7de57d`. Together with the existing
`JobStatus.java` snapshot, they cover every AOSP source range explicitly cited
in the accompanying manuscript. Complete files are retained so that the cited
line numbers can be inspected locally without reconstructing an AOSP checkout.

- `AppStandbyController.android-17.0.0_r1.java`:
  `apex/jobscheduler/service/java/com/android/server/usage/AppStandbyController.java`
- `IJobScheduler.android-17.0.0_r1.aidl`:
  `apex/jobscheduler/framework/java/android/app/job/IJobScheduler.aidl`
- `JobScheduler.android-17.0.0_r1.java`:
  `apex/jobscheduler/framework/java/android/app/job/JobScheduler.java`
- `JobSchedulerImpl.android-17.0.0_r1.java`:
  `apex/jobscheduler/framework/java/android/app/JobSchedulerImpl.java`
- `JobSchedulerService.android-17.0.0_r1.java`:
  `apex/jobscheduler/service/java/com/android/server/job/JobSchedulerService.java`
- `JobStatus.android-17.0.0_r1.java`:
  `apex/jobscheduler/service/java/com/android/server/job/controllers/JobStatus.java`
- `PendingJobReasonsInfo.android-17.0.0_r1.java`:
  `apex/jobscheduler/framework/java/android/app/job/PendingJobReasonsInfo.java`
- `SparseLongArray.android-17.0.0_r1.java`:
  `core/java/android/util/SparseLongArray.java`
- `TimeUtils.android-17.0.0_r1.java`:
  `core/java/android/util/TimeUtils.java`

`SHA256SUMS` binds every snapshot. The sealed campaign's existing
`provenance/production-source.sha256` independently binds the campaign-recorded
`JobSchedulerImpl.java`, `JobSchedulerService.java`, and `JobStatus.java`
files. This snapshot set is an audit convenience. Only bindings already
present in the sealed campaign are campaign evidence; the immutable campaign
plan is unchanged.

## Evaluated image

`manifests/android-17.0.0_r1.xml` is the resolved baseline manifest.
`manifests/android-17.0.0_r1-plus-goldfish-overlay.xml` is the configured build
manifest. The only changed project is `device/generic/goldfish`:

- `goldfish/enable-automatic-power-modes.diff` is the complete delta;
- `goldfish/0001-enable-automatic-power-modes.patch` preserves its reviewable
  commit message;
- `goldfish/hotmobile-app-standby.bundle` is a thin bundle preserving the exact
  configured commit and branch tip. It requires the baseline Goldfish parent
  `296e55aa0244e8929e393e00e34471fef2a5d662`, which the baseline manifest
  identifies;
- `goldfish/lostboundaries_app_standby.xml` is the added resource file.

The resource sets the product-policy value used to enable App Standby and the
light- and deep-mode enable flags in `DeviceIdleController`; it does not by
itself place the device in either idle mode. It does not modify JobScheduler
accounting. The framework `JobStatus.java` snapshot is byte-identical to the
pinned `frameworks/base` r1 revision.

## Component-test variants

This directory keeps loose, human-auditable copies of two separately executed
`JobStatusTest` variants:

- `sixteen-test-variant.diff` and
  `JobStatusTest.sixteen-test-variant.java` correspond to the separately sealed
  71+16 complete-class run (87/87 passed).
- `monotonicity.diff` and
  `JobStatusTest.monotonicity-variant.java` are the historical filenames for
  the paper's separate 71+1 *reported-decrease* variant. Its test-only
  commit has r1 as its parent, and its r1/CP2A execution is preserved in a
  separate bundle under `../component-tests/`. The original component bundle
  still preserves an older CP31 pass with a post-hoc source-binding limitation;
  that record is historical rather than the paper's claim-bearing execution.

The seven-test characterization patch and its exact executed source are inside
`../component-tests/hotmobile-component-evidence.tar.gz`, where the bundle's
own manifest and verifier bind them to the 78-pass execution. They are not
duplicated as loose files here. The seven-test, one-test, and historical
16-test variants were executed separately and must not be described as one
combined run.

The pristine test source, framework source, and two `Android.bp` files are
included so the patches and test-module wiring can be audited without copying
the complete AOSP checkout.

Verify every file with:

```sh
(cd aosp-source && sha256sum -c SHA256SUMS)
```
