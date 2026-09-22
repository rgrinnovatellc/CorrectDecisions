# Licensing boundary

This package combines project-authored material with snapshots and binaries
derived from the Android Open Source Project and with immutable evidence
archives that preserve their own notice files.

## Project-authored material

Copyright 2026 Uddhav P. Gautam.

| Material | License | SPDX |
| --- | --- | --- |
| Code: `verify_artifacts.py`, `reanalyze_campaign.py`, `compare_resolved_manifests.py`, the root `Makefile`, the maintained scripts under `harness/`, and the probe application sources under `probe-app/` | Apache License 2.0, in `../LICENSE` | `Apache-2.0` |
| Documentation: `README.md`, `CLAIMS.md`, `REPRODUCE.md`, `CITATION.cff`, this file, and each payload `README.md` | Creative Commons Attribution 4.0 International, in `../LICENSE-DOCS` | `CC-BY-4.0` |
| Data: the retained campaign under `harness/campaigns/`, its provenance records, and the derived CSV outputs | Creative Commons Attribution 4.0 International, in `../LICENSE-DOCS` | `CC-BY-4.0` |

Both license files are byte-exact copies of the canonical upstream texts.

Apache-2.0 is the upstream AOSP license, so the project-authored code and the
pinned AOSP source under `aosp-source/` combine without a compatibility
boundary. Attribution under CC-BY-4.0 is satisfied by citing the accompanying
article and the archived artifact release; `CITATION.cff` records that metadata.

These licenses are declared here rather than in per-file headers. The verifier
checks that the released harness scripts and probe sources are byte-identical to
the sealed copies under
`harness/campaigns/*/provenance/source-snapshot/`, so adding a header to any of
those files would break the execution-provenance claim that the archived
snapshot is what ran.

## Material not licensed by this project

- AOSP-derived source and binaries under `aosp-source/` and `aosp-image/` remain
  subject to the licenses and notices attached to their upstream projects and
  included payloads. The resolved manifests identify the exact upstream projects
  and revisions. No license above is asserted over those files.
- The two component archives under `component-tests/` retain their embedded
  license and notice material and must remain byte-exact for provenance. No
  license above is asserted over their contents.

Public visibility by itself does not grant reuse permission for the material in
this second group.
