# PS3Xploit Resigner GUI

Add games to your PS3's **act.dat** without touching a
command line.

This is a graphical front-end for the **PS3Xploit Resigner**
by the PS3Xploit Team. It does the one job the Resigner is
most often used for — the **RAP → RIF** flow:

1. Pick your console's **act.dat** and **idps.hex**.
2. Queue the **.rap** files for the games you are adding
   (files, a whole folder, or straight off a network share).
3. Pick an output folder and press **Generate**.
4. Install the resulting
   **PKG_RIF-INSTALLER.pkg_signed.pkg** on your PS3 — the
   licenses are registered into your act.dat.

An optional checkbox, **"Also resign packages"** (off by
default), additionally resigns queued `.pkg` files
DEBUG → HAN style with the same engine.

## The engine

The GUI reimplements **no** cryptography. The engine
arrives **ready-built inside this package** — the app
assumes your machine has nothing installed and needs
nothing from it. On first run the app unpacks the
PS3Xploit Resigner **V3.0.0** source it carries (the exact
release from the official repo,
https://github.com/PS3Xploit/PS3xploit-resigner, verified
against a pinned SHA-256), installs the ready-built
`ps3xploit_rifgen_edatresign` it carries beside it
(Linux: built from that source against OpenSSL 3.5.9 and
linked fully static, so it needs no libraries from your
machine; Windows: the engine's own prebuilt `.exe`,
hash-verified the same way), and then drives the engine
exactly the way the engine's own `resign_linux.sh` /
`resign_windows.bat` do. The installer package is built
with the engine's ps3py `pkg.py`. Downloading the engine
and building rifgen on your machine survive only as a
fallback if the carried engine is ever missing or damaged.

The engine is GPL-3.0 (see Credits); its source is the
pinned V3.0.0 release, available from the official repo
above and carried in this package as
`engine-payload/ps3xploit-resigner-V3.0.0.tar.gz`.

### One honest requirement

The engine's package builder (`pkg.py`) runs under
**python2.7** — that is the Resigner's own design, on every
platform's script. The RAP → RIF signing itself and PKG
resigning do not need it, but building the installer
package does. If python2.7 (with its development headers)
is not installed, the app says so in plain language in the
log when you Generate; nothing is silently skipped and no
success is claimed for a package that was not built.

## Your private files

`act.dat` and `idps.hex` are **your per-console private
files**. This app:

- reads them only from where you point it;
- remembers only their **paths** in its settings;
- copies them into a local scratch folder only for the
  length of a Generate run, and **deletes that scratch in
  all cases** — success, failure, or cancel;
- never logs their contents, never bundles them, never
  sends them anywhere.

Network share passwords are likewise never stored (only
server / share / username are remembered).

## Queues, log, status

- The RAP/PKG queues and the session log are saved to disk
  as you work and restored on the next launch — a power cut
  no longer loses your place. Anything that was mid-signing
  when the app died comes back honestly marked
  *interrupted (app closed)*.
- The status bar narrates every phase; no work is silent.
- Every output the app reports as done has been checked on
  disk (exists, non-empty) — an engine exit code of 0 is
  never taken as proof on its own.

Data lives in `~/.local/share/ps3xploit-resigner-gui/` on
Linux and `%LOCALAPPDATA%\PS3XploitResignerGUI` on Windows.

## Running

- **Linux AppImage**: `chmod +x
  PS3XploitResignerGUI-x86_64.AppImage` and run it. (On a
  system without FUSE/libfuse2, run it with
  `--appimage-extract-and-run`.)
- **From source / Windows zip**: run
  `ps3xploit-resigner-gui.sh` (Linux) or
  `ps3xploit-resigner-gui.bat` (Windows). The first run
  creates a Python venv and installs PySide6.

First launch unpacks the ready-built engine the package
carries — watch the log; it takes a few seconds, needs no
network and no compiler.

## Credits

- **PS3Xploit Team** — the Resigner engine: HAN tools by W,
  escortd3w, bguerville and habib; resign scripts by Caio
  Oliveira, after CaptainCPS-X's PKG script; ps3py by the
  PSL1GHT team. GPL-3.0.
  https://github.com/PS3Xploit/PS3xploit-resigner
- GUI by billtookahit420, in the converter-app family
  (same skeleton as the Pop-fe GUI).

## Honesty notes

- The Windows package is **code-verified only**: the build
  fleet is Linux-only, so the Windows path has not been
  executed. The Linux AppImage is the verified build.
- A full real-RIF run needs *your* real act.dat / idps.hex
  on *your* machine; the packaged build was verified with
  synthetic fixture files (see BUILD-REPORT.md).
