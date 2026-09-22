# Probe application

`lostboundaries-probe-debug.apk` is the exact 26,291-byte APK hashed by every
retained attempt in the controller-driven public-API campaign. Its SHA-256 is
`8539b05bb91c4bcf1d3251a12fad133f2f0a65f7cf878974cd50776a9149d75b`,
its package name is `org.lostboundaries.probe`, and it targets API 37. The seven
source/build files in this directory are byte-identical to the source snapshot
archived before acquisition.

The manifest declares no `uses-permission` entries. Its receiver uses
`android.permission.DUMP` as a sender-side delivery gate, and its job service
requires `android.permission.BIND_JOB_SERVICE`; neither declaration grants
either permission to the app. Shell commands control emulator state, while the
schedule, query, and cancellation calls execute inside this installed package
under its ordinary app UID.

Verify the binary with:

```sh
(cd probe-app && sha256sum -c SHA256SUMS)
```

The standalone verifier additionally checks every source cross-copy and that
this digest is the only probe-APK digest recorded across all 31 retained
attempts. The campaign used Gradle 9.6.1 offline, while AGP 9.3.1 and API 37
are fixed in the source. See `../REPRODUCE.md` for the compiler-toolchain
limitation. This is a debuggable research probe, not a production application.
