# PS3Xploit Resigner GUI — Build Report

Built 2026-11-24 on this VM, to the spec at
`~/workspace/ps3xploit-resigner-gui-spec.md`. Not published anywhere.
**Rebuilt the same day after Duane's field failure -- see the
addendum at the end of this report; it supersedes the
engine-setup parts of the original text.**

(Current deliverables below are the post-field-fix build.
First build, superseded: AppImage 96,793,792 B /
`f21a3255...`; Windows zip 24,847 B / `ab03aa8c...`.)

## Deliverables

| File | Size | SHA-256 |
|---|---|---|
| `PS3XploitResignerGUI-x86_64.AppImage` | 104,518,848 B | `119517dfe3057169600197b13c8277ec7d077256c7c1565606753d573b03b701` |
| `PS3XploitResignerGUI-Windows.zip` | 7,733,562 B | `88c6691f62894341f60a7750b1b1b09a1ec8b43e5b623c82fd1a0b8690933d33` |

(Superseded 2026-11-24 earlier build, pre-netshare-fix:
AppImage 104,514,752 B / `dcb81532...`; Windows zip
7,732,421 B / `335fd53b...`.)

Source: `src/PS3XploitResignerGUI/` (PySide6). Family patterns reused
from the PopFE GUI: Worker-thread pattern, status bar narrating every
phase, settings/state/session-log persistence in the app data dir
(`~/.local/share/ps3xploit-resigner-gui/`), `netshare.py` lifted
byte-identical (verified with `cmp`), first-run engine setup, the
deferred-log-insert + ordered-teardown fixes from PopFE's exit-crash
lesson.

## The app

One screen, one main job: RAP → RIF. act.dat and idps.hex pickers
(paths remembered in settings; contents never stored), a .rap queue
(Add Files / Add Folder / network share, Remove Selected, persisted
across relaunches), an output folder picker, Generate → the engine's
`PKG_RIF-INSTALLER.pkg_signed.pkg` in the output folder. A checkbox
"Also resign packages" (off by default) reveals a .pkg queue;
Generate then also resigns the queued packages DEBUG → HAN style
into the output folder. Every picker offers network-share browsing.

## Engine

PS3Xploit/PS3xploit-resigner **V3.0.0**, downloaded at first run
(never bundled), pinned and hash-verified before extraction:

- Tarball: 5,055,367 B
- SHA-256: `ccdad8beeb92276049505ce9a4d48454cae2d22c2d91c97710fe683af4df8b57`
  (a hash mismatch refuses setup and deletes the download)
- GPL-3.0; the PS3Xploit Team is credited in the README and in the
  app's header line.

The app drives the engine the way `resign_linux.sh` does: inputs
staged in local scratch under the app data dir, `ps3xploit_rifgen_edatresign`
built from `source/src` with make and run per file, `signed_act.dat`
renamed over the staged act.dat, the installer package built with
the engine's own ps3py `pkg.py` machinery, then resigned with
rifgen. No crypto was reimplemented. The Windows package follows
their prebuilt-exe + `pkg_exdata.exe` path instead.

Build note: rifgen's `main.cpp` does not compile under this VM's
g++ 13.3 as shipped (one error — `gettimeofday` undeclared at line
685; modern headers no longer pull `<sys/time.h>` in transitively).
The engine source is **not** modified: the app's build passes the
same fix on the make command line (`-include sys/time.h` in
CFLAGS). With that, rifgen builds clean and runs (banner
"PS3XPLOIT RESIGNER v3").

## Privacy handling (verified in the smokes)

- act.dat / idps.hex are read only from where the user points the
  pickers. Settings contain paths only.
- Staged scratch copies live under the app data dir and are deleted
  after every run, success or failure. Post-smoke sweeps found zero
  act.dat / idps.hex / .rap copies anywhere in the data dir outside
  the engine tree.
- PKG resigning stages copies — the user's original .pkg files are
  never modified (rifgen's own script flow edits in place; the app
  deliberately does not inherit that).

## Fixture proof (synthetic fixtures only)

Fixtures: seeded-random dummy act.dat (4,152 B), idps.hex (16 B),
two 16 B .rap files with content-ID-shaped names, one 4,096 B
random-bytes .pkg. Proof trees under `proof/` (`smoke1`, `smoke2`,
`smoke3`).

**Source smoke 1 (happy path + checkbox):** first-run setup
completed in ~7.5 s (download, hash match, rifgen build). Generate:
both RAPs signed (status done; engine log shows its real
reading/writing lines; rifgen produced a 152-byte .rif and a
4,152-byte signed_act.dat per RAP in direct engine test runs). The
installer-package step then stopped with the plain-language reason
(see Caveats — python2.7), and the app reported exactly that: no
installer package claimed, output list empty. The dummy .pkg was
reported failed with its real reason (below). App exit code 0.

**Source smoke 2 (error surfacing):** act.dat pointed at a
nonexistent path → the run stopped before signing with "act.dat was
not found at … — the RIF job needs your act.dat and idps.hex.",
the queued RAP stayed "queued" (not falsely done), outputs empty.

**Relaunch restore (source and packaged):** the queue came back
with per-file statuses intact (done stayed done, failed stayed
failed); the session log restored with its divider line; restored
mid-run entries would come back as "interrupted (app closed)".

**Packaged AppImage smoke (smoke3):** the AppImage itself —
extract-and-run, offscreen, fresh data dir — repeated smoke 1
exactly: packaged first-run setup in 9.3 s, both RAPs done,
`rifs_made: 2`, same plain-language python2.7 stop, dummy .pkg
failed honestly, outputs empty, exit code 0. A second packaged run
under Xvfb with the real xcb platform plugin restored the queue and
exited 0, proving the pruned Qt tree (unused Qt modules removed:
278 MB → 97 MB) still drives the desktop path.

**Output verification:** the runner checks the engine's exit code
AND that each expected output exists and is non-empty before
anything is called done or copied to the output folder. This is
not theoretical: **rifgen segfaults on a garbage .pkg (exit −11)
after writing a `_signed.pkg` file.** The app detects the crash,
discards the partial output, and reports the package as failed
with the reason in the log. A leftover file from a crashed engine
is never reported as success.

## Caveats — read these

1. **python2.7 is required for the installer-package step and is
   not installed on this VM** (no apt candidate exists for it
   here). The engine's own `resign_linux.sh` has the same
   requirement — its `pkg.py` is Python 2 code. On this machine
   the app signs the RIFs, then stops at the packaging step with a
   plain-language explanation. Whether Duane's Kubuntu has
   python2.7 available (or installable) is part of the field
   proof. The RIF-signing step and PKG resigning do not need it.
2. **A full real-RIF proof is still owed and was NOT faked:** it
   needs Duane's real act.dat + idps.hex + a real .rap on his
   machine, ending with `PKG_RIF-INSTALLER.pkg_signed.pkg`
   produced and installed on his PS3. Everything above used
   synthetic fixtures only.
3. **Windows package is code-verified only** — never executed on
   Windows (fleet is Linux-only). It follows the upstream .bat
   flow (prebuilt rifgen exe + pkg_exdata.exe).
4. **Network-share browsing** uses the family's netshare.py
   (byte-identical to PopFE's proven module), but this VM has no
   FUSE/GVFS, so a live authenticated mount could not be exercised
   here; Duane's rig is the final proof for that path, same as the
   rest of the family.
5. The AppImage bundles the host distro's Python 3.12 + PySide6
   (Qt modules the app never imports were pruned; both the
   offscreen and Xvfb/xcb packaged smokes pass on the pruned
   tree).

---

## ADDENDUM 2026-11-24 — field failure and the bare-machine redesign

**What happened in the field.** Duane ran the first build's
AppImage on his Kubuntu machine. First-run setup downloaded
the engine (5,055,367 B, SHA-256 matched the pin), extracted
it, and rifgen **compiled** fully — then the **link failed**
and setup stopped with the app's plain-language error. His
log's undefined references all come out of the static
`libcrypto.a` on his system: `jent_entropy_collector_alloc`
/ `jent_read_entropy` / `jent_entropy_init_ex`
(jitterentropy), `inflate` / `deflate` / `compress` /
`uncompress` / `zError` (zlib), and the `ZSTD_*` set
(libzstd). The app's error text then pointed at installing
`libssl-dev` — which he already had.

**Root cause (one line).** The engine's Makefile links
`-static -lcrypto -lssl` and names nothing else, but current
Ubuntu's OpenSSL static archive is built with direct zlib,
libzstd and libjitterentropy references baked in, so the
upstream link line cannot resolve it on a stock machine.

**Why this VM didn't catch it.** This VM is Ubuntu 24.04 /
OpenSSL 3.0.13, whose `libcrypto.a` carries none of those
references — its zlib member is an empty stub (verified with
`nm`: zero undefined symbols; force-pulling that member into
the engine's link still produces no undefined references,
and the app's exact make line links cleanly here). The exact
failure is therefore **not reproducible on this VM**; Duane's
machine runs gcc 15 with a newer Ubuntu OpenSSL build. The
fix is proven by construction (a dependency-free static
archive, verified symbol by symbol) and by the forced-static
link below, not by reproducing his link error.

**Duane's direction (the rule behind the fix).** First:
"have it download whatever it needs for it to run like we
did with everything else." Then, superseding that as the
primary path: **"think like i don't have it"** — assume the
user's machine has NOTHING: no compiler, no make, no dev
libraries. Compiling anything on the user's machine is out
as the primary path. This is now the family's standing
bare-machine rule.

**The new design — the engine ships ready-built.**

- On this VM, OpenSSL **3.5.9** (official GitHub release
  tarball, 53,279,637 B, sha256
  `603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a`,
  verified against the release's own `.sha256` file) was
  built static with a vanilla configuration (`no-shared
  no-tests no-zlib no-zstd`). Its `libcrypto.a` was verified
  to hold **zero** undefined zlib / zstd / jitterentropy
  references.
- rifgen was built from the pinned V3.0.0 source against
  that OpenSSL (command-line flags only, engine source
  untouched, as before) and linked fully static:
  7,044,416 B, sha256
  `fef64aa7d12ff2d0cfdf47ee3b090580f4655de2316641eee6101f7579ef639c`.
  `file` reports "statically linked"; `ldd` reports **"not
  a dynamic executable"** — the binary needs nothing from
  the host. Run directly against the dummy fixtures it
  produced the same 152-byte `.rif` and 4,152-byte
  `signed_act.dat` as the system-built tool.
- Both packages now carry an `engine-payload/` folder: the
  pinned V3.0.0 source tarball (the same bytes the old
  download path verified) plus that rifgen binary. First-run
  setup verifies both SHA-256 pins and simply unpacks them:
  no network, no compiler, no system libraries. On Windows
  the engine tree's own prebuilt exe is used, now also
  verified against a recorded pin (sha256
  `970d4f807afa9de6baeb1fabe2741ea9d56e1cc043977d46745717463f2609e8`).
- **Repair of Duane's existing state:** his data dir holds
  a half-built engine tree from the failed setup (tree
  present, tool missing, stray object files). The new setup
  detects exactly that and installs the carried tool into
  the tree — his next launch of the fixed AppImage lands on
  "engine ready" (proven in smoke5, seeded to match).
- **Fallback kept:** if the carried payload is missing or
  fails its hash check, the old download path runs, and the
  build climbs a link ladder — upstream static → dynamic →
  dynamic naming `-lz -lzstd` → dynamic naming
  `-l:libz.so.1 -l:libzstd.so.1` — appended after `-lcrypto`
  through the Makefile's own `LIBS` variable (its link rule
  is `$(CC) $(CFLAGS) $(OBJS) -o $(OS_TARGET) $(LDFLAGS)
  $(LIBS)`; `CFLAGS`/`LDFLAGS`/`LIBS` are all command-line
  overridable, which is also how the existing
  `-include sys/time.h` workaround is passed). The ladder
  was exercised on this VM (attempt 1 succeeds here, as
  before). The setup error text was corrected: a link
  failure with undefined references now says the code
  compiled fine, that the system OpenSSL archive needs
  libraries the Makefile doesn't name, that reinstalling
  libssl-dev will not help, and that the real fix is the
  carried tool / a fresh copy of the package.
- GPL note: the engine now ships inside the package. Its
  source is carried in the package itself as the pinned
  V3.0.0 tarball, the PS3Xploit Team credit is unchanged in
  the app header and README, and the README names the
  official repo as the source. The spec has a matching
  addendum recording this design change.

**Proof of the new build (this VM, synthetic fixtures only).**

- Source-level: fresh data dir → carried setup completed,
  engine ready, installed rifgen hash matches its pin.
  Seeded half-built data dir → carried tool installed,
  engine ready. Neither path touched the network or a
  compiler.
- **Packaged smoke4 (fresh data dir)** — proof/smoke4: the
  rebuilt AppImage, extract-and-run, offscreen. Setup took
  **0.3 s** (first build's packaged setup: ~9.3 s; Duane's:
  failed). The log contains zero download lines and zero
  compiler output. Both RAPs signed (152-byte RIFs,
  `rifs_made: 2`); the installer-package step stopped with
  the same plain python2.7 reason as before (VM caveat 1 —
  unchanged, and still the owed field check on Duane's
  machine); the dummy PKG failed honestly (engine segfault,
  partial output discarded); outputs empty; exit 0.
- **Packaged smoke5 (simulated Duane state)** —
  proof/smoke5: same run against the seeded half-built data
  dir. Setup repaired it in 0.3 s, "Engine setup finished —
  ready", the rifgen in place hashes to the carried pin,
  same signing results, exit 0.
- Privacy sweep after both smokes: zero act.dat / idps.hex
  / .rap copies anywhere in the data dirs outside the
  engine tree; scratch empty. Every promise in the spec —
  hash pins, staged-scratch privacy, output verification —
  stands unchanged.

---

## Addendum — 2026-11-24: netshare "Location is already mounted" fix

Duane hit this in the field in the PS2 Native app (same
shared netshare module; the Resigner copy is patched here
too): browsing to a share that was ALREADY mounted popped
"could not mount smb://... : gio: ... Location is already
mounted" and the browse failed.

**Cause.** In `app/netshare.py`, `connect_linux()` first
tries `find_mount()` (a strict server+share match against
the GVFS mount directory names). When the existing mount
was created under a different spelling of the server (an
alias / hostname vs address), the strict match misses,
`gio mount` runs and answers "Location is already
mounted" with a non-zero exit, and -- the mount still
invisible to the strict matcher -- the code fell through
to its fatal-error raise, surfacing gio's success-state
message as if it were a failure.

**Fix (netshare.py only; the pending-prompt credential
handling in `_gio_mount` is untouched).**

- `_is_already_mounted(out)`: case-insensitive
  `already\s+mounted` match on gio's output (wording has
  varied across glib versions).
- In `connect_linux()`, when that matches, the new
  `_resolve_existing_mount(server, share)` runs BEFORE
  the poll loop / error path; on success the browse
  continues with the existing mount path and the log
  says "Network share already mounted at ...".
- `_resolve_existing_mount()` layers: (1) `find_mount()`
  as given; (2) `gio mount -l` -- for each listed SMB
  mount whose share matches, retry `find_mount()` with
  the host that mount was really created with; (3) a
  share-only scan of the gvfs directory, accepted only
  when exactly one SMB mount carries that share name.
- If resolution also fails, the previous behaviour is
  unchanged (poll loop, then the plain error).

**Proof (this VM -- no GVFS/FUSE here, so a stub-gio
harness; live-GVFS proof remains Duane's rig).**
`tests/test_netshare.py` (new): a fake `gio` on PATH +
a fake gvfs root. 5/5 pass: already-mounted resolved
via the `gio mount -l` listing; already-mounted resolved
via the share-only scan with an empty listing;
already-mounted canonical name still takes the fast
path; the Domain-then-Password prompt regression
(WORKGROUP lands in Domain, the password in Password,
under the "Enter password for share..." header); a
genuine failure still raises NetShareError. The patched
module was verified present inside both rebuilt
packages. The same patch is specified for the family
polish pass in
`~/workspace/netshare-already-mounted-fix-2026-11-24.md`.
