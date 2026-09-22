# Claim-to-evidence index

This index directs reviewers to the evidence supporting the paper's principal
source and empirical claims. It does not merge evidence layers that were
executed separately.

| Claim or validation question | Primary evidence | Validation |
| --- | --- | --- |
| The analyzed Android 17 r1 implementation uses the cited reason mapping, updater, getter, and reason-keyed stores. | Complete pinned files under `aosp-source/frameworks-base/`; resolved baseline manifest | `make verify`; inspect the manuscript-cited line ranges locally |
| The evaluated product changed only the Goldfish automatic-power-mode resource relative to the resolved r1 tree, while the framework's `JobStatus.java` remained pinned. | `aosp-source/manifests/`, `aosp-source/goldfish/`, campaign plan and `provenance/production-source.sha256` | `make verify`; inspect the bundle, patch, and configured-manifest difference |
| The seven synthetic-time component characterizations executed against unchanged framework code. | `component-tests/hotmobile-component-evidence.tar.gz` | `make verify-deep`; see the archive's own manifest, source bindings, logs, and verifier |
| A later component query returned a smaller `APP_STANDBY` duration in the separate reported-decrease trace. | `component-tests/hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz` | `make verify-deep`; see its exact test-only commit, APK, results, and verifier |
| The controller-driven campaign retained 31 sequential attempts, selected 30 by predeclared protocol checks, and did not stop or qualify on the eight result checks. | `harness/campaigns/cp2a-r1-as-20260819T043340Z/campaign-plan.json`, `campaign-result.json`, and `runs/evidence*.json` | `make verify` |
| All qualified traces used the same configured image and boot, the installed ordinary-app UID, the intended pending job and dynamic membership, four bounded transitions, and verified cleanup. | The 31 raw attempt records, runtime preflight, plan, result, and campaign checksum manifests | `make verify` |
| All eight result checks held in all 30 protocol-qualified traces, and the reported public values/rankings match the retained statistics. | Raw records plus `runs/30_evidences*.csv`, `allowance_sensitivity.csv`, and `table_values.csv` | `make reanalyze`, which reproduces all 28 attempt-level analysis predicates before regenerating the four derived outputs |
| The released probe APK is the APK recorded by every attempt, and the released probe source is the executed source. | `probe-app/` and the campaign source snapshot/raw records | `make verify` |
| The released emulator ZIP is the evaluated `emu_img_zip` output and its members match the campaign plan. | `aosp-image/` and campaign image-member/source-binding provenance | `make verify` |

Interpretation limits are evidence, too: the component fixtures were not
service-registered; the campaign used one configured emulator boot; a
fresh build need not be byte-identical; and source-guided reconstruction
reproduces the implementation rather than supplying an Android-defined overlap
contract. See the root README and `REPRODUCE.md` before generalizing a result.
