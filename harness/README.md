# Campaign and analysis harness

This directory contains maintained tooling for creating and running a new
campaign. The immutable campaign used in the paper is
`campaigns/cp2a-r1-as-20260819T043340Z/`; it retains all 31 raw attempt records,
the fixed pre-run plan, runtime and build provenance, derived outputs, and its
own checksum manifests.

The files at this directory's top level are **rerun tools**, not a claim that
every maintained byte was executed in 2026. The exact acquisition and analysis
source used by the retained campaign is preserved at
`campaigns/cp2a-r1-as-20260819T043340Z/provenance/source-snapshot/` and is bound
by both `source-snapshot.sha256` and the campaign's final `SHA256SUMS`.

Three maintained analysis files remain byte-identical to that executed
snapshot:

- `render_public_table.py`
- `summarize_allowance_sensitivity.py`
- `summarize_harness_runs.py`

Five rerun files contain narrow post-campaign robustness fixes:

| File | Maintained change |
| --- | --- |
| `create_cp2a_campaign.py` | Preserve a failed per-project `git status` command and handle empty output without a misleading pipeline success. |
| `probe_harness.py` | Apply the same source-cleanliness correction during each attempt. |
| `launch_campaign_emulator.py` | Bring pinned-ADB startup into the existing cleanup scope. |
| `run_campaign.py` | Use one fixed `/tmp` lock path for host-wide campaign exclusion. |
| `seal_campaign.py` | Copy the five already plan-bound provenance inputs required by isolated regeneration; the retained campaign records this sealer correction explicitly. |

`SHA256SUMS` binds the eight maintained top-level scripts. The standalone
verifier checks the stated maintained/executed relationships. For offline
review of the existing results, run `make reanalyze` at the artifact root; that
tool executes the exact archived analysis files against temporary copies of the
31 records. For a new acquisition, follow `REPRODUCE.md` and use a new campaign
identifier. Never modify or reseal the retained campaign.
