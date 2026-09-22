# Evaluated Android system-image package

`sdk-repo-linux-system-images.zip` is the exact 918,679,516-byte `emu_img_zip`
output from the evaluated build. It is a standard x86_64 emulator system-image
package containing the kernel, system, vendor, ramdisk, verified boot metadata,
and package metadata. It is not the complete dedicated AOSP output directory,
which also contains intermediates and unpacked images. The recorded launch
instead used separately bound `PRODUCT_OUT` files, including the initial
`userdata.img` and other build outputs not present in the ZIP.

This is a locally built, debuggable test-key image and is not suitable for a
production device. It uses the `cp2a` release configuration and carries build
ID `CP2A.260605.016`, but it is not an official Google-distributed CP2A binary.
Its `frameworks/base` project is exactly `android-17.0.0_r1`. The configured
source manifest differs from the r1 manifest only by the Goldfish commit that
adds `android:bool/config_enableAutoPowerModes=true`; that product
configuration enables the App Standby policy exercised by the experiment
without modifying the focal JobScheduler implementation.

The ZIP is configured for Git LFS because it is 918,679,516 bytes. After it is
published, run `git lfs pull` before verification. Check it with:

```sh
(cd aosp-image && sha256sum -c SHA256SUMS)
unzip -tq aosp-image/sdk-repo-linux-system-images.zip
```

The sealed campaign records the hash of every ZIP member. It also records
explicit AOSP build-output mappings for nine members. Those records are in:

- `harness/campaigns/cp2a-r1-as-20260819T043340Z/provenance/emu-img-zip-members.sha256`
- `harness/campaigns/cp2a-r1-as-20260819T043340Z/provenance/emu-img-zip-source-bindings.json`
- `harness/campaigns/cp2a-r1-as-20260819T043340Z/provenance/image-files.sha256`

The package makes the evaluated image available without retaining the complete
AOSP output tree. Recreating a new sealed campaign still requires an AOSP
checkout and build output because campaign creation independently binds the
resolved source manifest, product configuration, framework sources, installed
artifacts, emulator executable, and build outputs.
