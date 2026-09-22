# Correct Decisions, Incorrect Diagnostic Reports — artifact

This directory is a standalone reviewer package for the accompanying article on
shared-label duration accounting in Android 17's JobScheduler. It is intended
to become the root of a fresh public artifact repository; it contains no
dependency on the manuscript-development repository or its Git history.

The package preserves the pinned AOSP source inputs, exact evaluated emulator
image and probe APK, two self-verifying component-test archives, all 31 retained campaign attempts, the fixed campaign plan, exact executed source snapshots,
maintained rerun tools, and portable verification and reanalysis programs. It
does not include unpublished cross-domain work, planning notes, manuscript
backups, or unrelated build products.

## Quick verification

Materialize the two Git LFS objects, then run the deep verifier and the portable
reanalysis:

```sh
git lfs install
git lfs pull
make verify-deep
make reanalyze
```

A fresh GitHub clone requires Git and Git LFS. Once both large objects are
materialized, these commands need Linux, GNU Make, Python 3.12 or newer, Git,
and GNU `tar`; they do **not** need AOSP, an Android SDK, or an emulator. A
successful run establishes the following internal consistency:

- all payload, source, image, component, probe, and campaign checksums match;
- the image ZIP contains its 20 recorded members;
- all 31 raw attempts match the campaign index and one retained boot;
- 30 attempts meet the 20 fixed protocol-qualification predicates;
- the recorded history/event checks cover all 124 focal transitions;
- both component archives pass their internal verifiers; and
- all 28 stored attempt-level analysis predicates reproduce for each raw
  record, after which the selected cohort, statistics, sensitivity analysis,
  and table values regenerate byte-for-byte.

Local hashes detect corruption relative to this package. The public release's
fixed Git tag and archival deposit provide the external trust anchor.
Run these checks on the pristine release before generating a new campaign or
probe build; except for top-level `.git` metadata, the verifier rejects files
outside the fixed release inventory.

## Evidence map

| Evidence | Location | Scope |
| --- | --- | --- |
| Pinned Android 17 r1 source and configured product delta | `aosp-source/` | Resolved manifests, complete AOSP source files cited by line range, Goldfish commit bundle/diff/resource, and component-test variants |
| Evaluated emulator image | `aosp-image/` | Exact 918,679,516-byte `emu_img_zip` output; not the complete acquisition-time `PRODUCT_OUT` |
| Component characterization | `component-tests/hotmobile-component-evidence.tar.gz` | Seven added `JobStatusTest` methods and their executed results, plus clearly separated historical records |
| Reported-duration decrease | `component-tests/hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz` | Separate 71+1 test-only variant, exact test APK, and two invocations on one fresh CP2A boot |
| Controller-driven public-API campaign (one emulator boot) | `harness/campaigns/cp2a-r1-as-20260819T043340Z/` | Every raw record from 31 attempts, including the 30 protocol-qualified traces |
| Exact executed campaign source | `harness/campaigns/cp2a-r1-as-20260819T043340Z/provenance/source-snapshot/` | Acquisition and analysis files captured before the retained campaign |
| Maintained rerun tooling | `harness/` | Same workflow with narrow post-campaign robustness corrections documented in `harness/README.md` |
| Probe application | `probe-app/` | Exact source snapshot and the APK installed in every retained attempt |

`CLAIMS.md` maps the principal empirical claims to their evidence and validation
commands. Each payload directory also has a focused README and checksum
manifest.

## Reviewer workflows

| Goal | Command or starting point | AOSP/emulator required? |
| --- | --- | --- |
| Fast integrity and campaign validation | `make verify` | No |
| Deep validation, including both component verifiers | `make verify-deep` | No |
| Recompute all campaign-derived CSV/table outputs | `make reanalyze` | No |
| Inspect every cited AOSP source range and product delta | `aosp-source/README.md` | No |
| Independently rebuild and rerun | `REPRODUCE.md` | Yes |

The retained campaign must remain immutable. A full rerun uses the pinned
configuration but creates a new campaign identifier and new evidence.

## Exact source versus maintained tools

All seven released probe-source files are byte-identical to the executed source
snapshot. Three top-level analysis scripts are also byte-identical. Five
top-level harness scripts contain small operational corrections made after
acquisition; none rewrites the retained evidence. `harness/README.md` states
each difference, and the verifier checks the exact unchanged/changed file set.
The archived snapshot—not the maintained copy—is the authority for what ran.
The artifact-root `Makefile` is a post-acquisition standalone interface; the
different Makefile used during acquisition is retained in that snapshot.

## Rebuilding Android

Full reproduction is optional and substantially more expensive than artifact
verification. Google's current minimum is a 64-bit x86 Linux host with 64 GB
RAM and 400 GB free disk; `REPRODUCE.md` recommends at least 500 GB free disk
for this target and gives the complete pinned checkout, configuration, build,
probe, component-test, launch, acquisition, analysis, and sealing procedure.

This experiment built an AOSP emulator system image; it did not separately
compile an Android kernel. The target uses AOSP's pinned prebuilt x86_64 QEMU
6.12 kernel. The retained image build completed in 1:34:43 on the recorded
Ubuntu 24.04.4 LTS host, but CPU and RAM were not sealed, so that time is not a
runtime guarantee.

## Scope and limitations

- The seven-test characterization, one-test reported-decrease variant, and
  historical 16-test variant are separate executions and must not be combined.
- The component fixtures were not registered with `JobSchedulerService`; their
  returned-duration behavior is component evidence, not public-API reachability.
- The campaign establishes repeatability on one configured emulator image,
  process, and boot, not prevalence across boots, devices, vendors, or releases.
- The exact image ZIP is retained, but a new fully validated campaign requires a
  rebuilt complete `PRODUCT_OUT` and its initial user-data image.
- The probe's exact APK is retained. Gradle 9.6.1, AGP 9.3.1, and API 37 are
  documented, but the original Java/SDK/dependency-cache inputs were not all
  plan-hashed; `REPRODUCE.md` states this source-build limitation explicitly.
- Immutable logs retain author identity and original absolute host paths. This
  package is not anonymized and suits a non-anonymous review or public-release
  path.

## Public release and citation

Create the public GitHub repository directly from this directory so that the
paths above remain valid. The included `.gitattributes` stores the evaluated
image and the 66 MB reported-decrease archive with Git LFS. Publish a fixed
version tag, test a fresh clone with LFS materialized, and archive a fully
materialized release snapshot on a preservation service such as Zenodo. Verify
that the archival copy contains the large-file contents rather than LFS pointer
files, then cite its DOI in the manuscript's Data Availability statement.

`CITATION.cff` supplies provisional citation metadata and deliberately omits a
DOI and release version. Choose the project-authored-material licenses and set
the release version before creating the final root `SHA256SUMS` and tag. If the
preservation service supports DOI reservation, reserve the DOI and add it to
the citation metadata before that step; otherwise, do not invent one.

After staging the intended release files in the new repository, regenerate the
root manifest from the tracked files, then rerun both validation workflows:

```bash
manifest_tmp="$(mktemp)"
while IFS= read -r -d '' path; do
  test "$path" = SHA256SUMS || sha256sum -- "$path"
done < <(git ls-files -z) | LC_ALL=C sort -k2 > "$manifest_tmp"
mv -- "$manifest_tmp" SHA256SUMS
chmod 0644 SHA256SUMS
git add -- SHA256SUMS
make verify-deep
make reanalyze
```

Commit and tag only after those commands pass, push both Git LFS objects, and
test another fresh clone. Never move a published tag. A later metadata or file
change is a new release with a regenerated manifest.

## Licensing and contact

AOSP-derived files retain their upstream notices and licenses; the component
archives preserve their own notice material. `LICENSES/README.md` records the
current licensing boundary. A repository-wide license for project-authored
code, documentation, and data remains an explicit author decision and must be
added before claiming permission for reuse.

Artifact questions may be directed to Uddhav P. Gautam at `upgautam@vt.edu`.
