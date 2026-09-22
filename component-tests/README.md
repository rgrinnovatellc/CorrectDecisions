# Component-test evidence

This directory preserves two separate, self-verifying component artifacts.

`hotmobile-component-evidence.tar.gz` is the original paper-scoped snapshot.
Its filename, embedded six-page manuscript, and archive-scoped prose retain an
earlier project designation; the sealed checksum manifests bind these filenames,
so they must not be renamed. For the accompanying article, this bundle supplies
the exact seven-test characterization evidence; its embedded manuscript is not
that article. The bundle contains three evidence layers:

- a fresh seven-addition characterization run;
- the digest-bound 16-addition, 87/87-pass historical run retained for
  provenance rather than a result of the accompanying article;
- the older monotonicity record, with a focused pass and a complete-class CP31
  run containing 68 passes and four pre-existing assumption skips.

That CP31 execution-to-source binding is explicitly post hoc: its logs do not
contain the Git revision or test-source digest, and its executed APK is
unavailable. The record remains immutable historical evidence.

`hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz` is the paper's
claim-bearing *reported-decrease* artifact; `monotonicity` is its retained
historical identifier. Its 71+1 test-only commit has the pinned r1
`frameworks/base` commit as its parent. On one fresh, wiped CP2A boot, the focal
test passed alone and in the complete-class run. The complete class had 68
passes, four pre-existing flag-conditioned assumption skips, and no failures or
ignores. Both invocations freshly installed the same archived APK. The fixtures
were unregistered, so this remains component evidence rather than a public-API
execution.

The paper's seven-test and one-test variants were not combined: no 79-test
execution (71 upstream tests plus seven plus one) is claimed. The historical
16-test variant was also executed separately. The framework's `JobStatus.java` is unchanged in every variant.

The reported-decrease bundle's verifier requires Python 3.12 or newer and Git.

From the artifact root, verify both outer archives, extract them, and run
their self-contained verifiers:

```sh
(cd component-tests && sha256sum -c SHA256SUMS)

component_dir="$PWD/component-tests"
component_archive="$component_dir/hotmobile-component-evidence.tar.gz"
component_tmp="$(mktemp -d)"
tar -xzf "$component_archive" -C "$component_tmp"
python3 -I \
  "$component_tmp/hotmobile-component-evidence/verify_artifact.py"

decrease_archive="$component_dir/"\
"hotmobile-monotonicity-r1-cp2a-20260820T000350Z.tar.gz"
decrease_tmp="$(mktemp -d)"
tar -xzf "$decrease_archive" -C "$decrease_tmp"
python3 -I \
  "$decrease_tmp/hotmobile-monotonicity-r1-cp2a-20260820T000350Z/verify.py" \
  "$decrease_archive"
```

The raw CP31 Atest records in the original bundle are unredacted. Their targeted
scan found no credential-shaped secret, but they retain local paths, emulator
identifiers, and ordinary emulator-network data. The claim-bearing r1 artifact
excludes irrelevant device and host logs, normalizes retained text paths,
records each raw input's digest, and keeps the APK, test-result JSON, sources,
and patch byte-exact.

In the immutable test, “lifetime total decreased” refers to returned durations,
not to an observed decrease of the private stored total. The test's explicit
nonconsecutive comparison is 9 at `q=19` versus 1 at `q=21`. The same passing
trace also returned 10 at `q=20`, so its consecutive `q=20` and `q=21` queries
produced the 10-to-1 decrease reported in the paper. The bound source files
retain their historical wording.
