"""Engine driver for the PS3Xploit Resigner GUI.

This module sets up and drives the PS3Xploit Resigner
(github.com/PS3Xploit/PS3xploit-resigner, pinned at release
V3.0.0) exactly the way its own resign_linux.sh /
resign_windows.bat do. NO cryptography is reimplemented here:
the engine's own `ps3xploit_rifgen_edatresign` binary turns
RAP files into RIFs and resigns PKGs, and the engine's own
ps3py `pkg.py` (Linux, under python2.7) / `pkg_exdata.exe`
(Windows) builds the RIF installer package.

The engine arrives READY-BUILT (Duane's bare-machine rule,
2026-11-24: "think like i don't have it" -- assume the user
has nothing installed). The app package carries the pinned
V3.0.0 source tarball and a rifgen binary built from that
source against a pinned OpenSSL, linked fully static so it
needs nothing from the host; both are hash-verified before
use, so first-run setup is just an unpack. Downloading the
engine and building rifgen on the user's machine survives
only as a fallback for a missing or damaged carried payload
-- and the field failure that produced this rule (a static
link against a system OpenSSL whose archive silently needs
extra libraries) is exactly what the fallback's link ladder
and error text now handle honestly.

Privacy rules (hard): the user's act.dat and idps.hex are
per-console private files. This module only ever receives
their PATHS from the caller, copies them into a local run
scratch folder for the length of one Generate run, and the
scratch folder is deleted in a finally block on every exit
-- success, failure or cancel. Their contents are never
logged, never written to settings, never bundled.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

# AppRun / the launchers point PS3RESIGN_GUI_DATA_DIR at a
# per-user folder; unpackaged runs default to it too (this
# app's state is small and per-user by nature).
DATA_DIR = Path(os.environ.get(
    "PS3RESIGN_GUI_DATA_DIR",
    str(Path.home() / ".local" / "share"
        / "ps3xploit-resigner-gui") if os.name != "nt"
    else str(Path(os.environ.get("LOCALAPPDATA",
                                  str(Path.home())))
             / "PS3XploitResignerGUI")))
ENGINE_DIR = Path(os.environ.get("PS3RESIGN_GUI_ENGINE_DIR",
                                 str(DATA_DIR / "engine")))
CACHE_DIR = DATA_DIR / "cache"
SCRATCH_DIR = DATA_DIR / "scratch"
SETTINGS_PATH = DATA_DIR / "settings.json"
STATE_PATH = DATA_DIR / "state.json"
SESSION_LOG_PATH = DATA_DIR / "session-log.txt"

ENGINE_VERSION = "V3.0.0"
ENGINE_URL = ("https://github.com/PS3Xploit/PS3xploit-resigner"
              "/archive/refs/tags/V3.0.0.tar.gz")
ENGINE_SHA256 = ("ccdad8beeb92276049505ce9a4d48454cae2d22"
                 "c2d91c97710fe683af4df8b57")
ENGINE_TOP = "PS3xploit-resigner-3.0.0"
RIF_PKG_CONTENTID = "RIF000-INSTALLER_00-0000000000000000"
RIF_PKG_NAME = "PKG_RIF-INSTALLER.pkg"
RIF_PKG_SIGNED_NAME = "PKG_RIF-INSTALLER.pkg_signed.pkg"

# The engine's Makefile flags, plus one forced include: the
# engine's main.cpp uses gettimeofday without including
# <sys/time.h>, which modern toolchains no longer forgive.
# A build-flag workaround only -- the engine source is never
# modified. (Used by the fallback build only; the carried
# binary below is the normal path.)
MAKE_CFLAGS = ("-pipe -fvisibility=hidden -D_GNU_SOURCE -O3 "
               "-static -D_FILE_OFFSET_BITS=64 "
               "-include sys/time.h")
# Same, without -static, for the fallback ladder's dynamic
# link attempts.
MAKE_CFLAGS_DYNAMIC = ("-pipe -fvisibility=hidden "
                       "-D_GNU_SOURCE -O3 "
                       "-D_FILE_OFFSET_BITS=64 "
                       "-include sys/time.h")

# ---------------------------------------------------------------------
# carried engine payload (the bare-machine rule)
#
# The package carries, beside this app (engine-payload/):
#   * the pinned V3.0.0 source tarball -- the exact bytes
#     ENGINE_SHA256 already pins for the download path, so
#     setup needs no network at all;
#   * on Linux, a rifgen binary built from that source on
#     the build machine against OpenSSL 3.5.9 (official
#     source tarball sha256 recorded below), configured
#     vanilla (no zlib / zstd / entropy-provider extras) and
#     linked FULLY STATIC -- `ldd` says "not a dynamic
#     executable", so the host needs no libraries for it;
#   * on Windows, upstream's own prebuilt rifgen exe from
#     inside the pinned tarball, hash-verified the same way.
# Every carried executable is verified against its pin
# before it is installed or run.
CARRIED_DIR = APP_DIR / "engine-payload"
CARRIED_TARBALL = CARRIED_DIR / "ps3xploit-resigner-V3.0.0.tar.gz"
CARRIED_RIFGEN = (CARRIED_DIR / "linux"
                  / "ps3xploit_rifgen_edatresign")
RIFGEN_SHA256 = ("fef64aa7d12ff2d0cfdf47ee3b090580f4655de"
                 "2316641eee6101f7579ef639c")
WINDOWS_RIFGEN_SHA256 = ("970d4f807afa9de6baeb1fabe2741ea9"
                         "d56e1cc043977d46745717463f2609e8")
# Provenance of the carried Linux rifgen's OpenSSL (the app
# never builds OpenSSL; this is build-report data).
OPENSSL_VERSION = "3.5.9"
OPENSSL_TARBALL_SHA256 = ("603f5602e2eef00d77fbd429d34dcd5"
                          "822bb301757a1bc9cdb24c670f1eb859a")


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _noop(_msg):
    pass


def is_windows():
    return os.name == "nt"


# ---------------------------------------------------------------------
# paths inside the engine tree

def rifgen_path():
    if is_windows():
        return ENGINE_DIR / "source" / "pre-compiled" / "windows" \
            / "ps3xploit_rifgen_edatresign.exe"
    return ENGINE_DIR / "source" / "pre-compiled" / "linux" \
        / "ps3xploit_rifgen_edatresign"


def rifgen_src_dir():
    return ENGINE_DIR / "source" / "src"


def ps3py_dir():
    return ENGINE_DIR / "source" / "tools" / "ps3py"


def pkgpy_path():
    return ps3py_dir() / "pkg.py"


def pkg_exdata_path():
    return ENGINE_DIR / "source" / "tools" / "ps3py_exe" \
        / "pkg_exdata.exe"


def engine_tree_present():
    return (ENGINE_DIR / "resign_linux.sh").is_file() \
        and rifgen_src_dir().is_dir()


def engine_ready():
    """The engine tree is downloaded AND the rifgen binary
    for this platform is in place (built on Linux, prebuilt
    on Windows)."""
    if not engine_tree_present():
        return False
    if is_windows():
        return rifgen_path().is_file() \
            and pkg_exdata_path().is_file()
    return rifgen_path().is_file()


def python27_path():
    return shutil.which("python2.7")


def pkgcrypt_ready():
    if is_windows():
        return pkg_exdata_path().is_file()
    return (ps3py_dir() / "pkgcrypt.so").is_file()


# ---------------------------------------------------------------------
# subprocess helper

def _run_stream(cmd, cwd, log, input_text=None, timeout=None,
                proc_holder=None):
    """Run a command, streaming merged output to log() line by
    line; returns the exit code. input_text (if given) is
    written to the child's stdin, which is then closed --
    the engine's tools wait for Enter presses, and the
    engine's own scripts feed them newlines the same way.
    proc_holder (a list) receives the Popen object so a
    cancel can terminate it."""
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    if proc_holder is not None:
        proc_holder.append(proc)

    def _feed():
        try:
            if input_text:
                proc.stdin.write(input_text)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    try:
        for line in proc.stdout:
            log(line.rstrip("\n"))
        return proc.wait(timeout=timeout)
    except Exception:
        proc.kill()
        raise


# ---------------------------------------------------------------------
# first-run setup

def _download_engine(log):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive = CACHE_DIR / "ps3xploit-resigner-V3.0.0.tar.gz"
    if archive.is_file():
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest == ENGINE_SHA256:
            log("Engine archive already downloaded and its "
                "SHA-256 matches the pinned release.")
            return archive
        log("A previously downloaded engine archive does not "
            "match the pinned release hash -- downloading "
            "again.")
        archive.unlink()
    log("Downloading the PS3Xploit Resigner %s source from "
        "the official GitHub repo..." % ENGINE_VERSION)
    req = urllib.request.Request(
        ENGINE_URL, headers={"User-Agent": "PS3XploitResignerGUI"})
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, \
            open(archive, "wb") as out:
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
            total += len(chunk)
    got = digest.hexdigest()
    log("Downloaded %d bytes; SHA-256 %s" % (total, got))
    if got != ENGINE_SHA256:
        archive.unlink(missing_ok=True)
        raise RuntimeError(
            "The downloaded engine archive's SHA-256 does not "
            "match the pinned %s release (%s). The download "
            "was deleted; nothing was installed."
            % (ENGINE_VERSION, ENGINE_SHA256))
    log("SHA-256 matches the pinned release.")
    return archive


def _extract_engine(archive, log):
    if ENGINE_DIR.exists():
        shutil.rmtree(ENGINE_DIR)
    ENGINE_DIR.mkdir(parents=True)
    log("Extracting the engine source...")
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(ENGINE_DIR, filter="data")
    top = ENGINE_DIR / ENGINE_TOP
    if not top.is_dir():
        raise RuntimeError(
            "The engine archive did not contain the expected "
            "%s folder." % ENGINE_TOP)
    for child in top.iterdir():
        shutil.move(str(child), str(ENGINE_DIR / child.name))
    top.rmdir()


def _build_rifgen_linux(log):
    """FALLBACK ONLY: build rifgen on the user's machine.
    The package carries a ready-built rifgen, so this runs
    solely when that carried binary is missing or fails its
    integrity check.

    The engine's Makefile links `-static -lcrypto -lssl`
    and names nothing else. On current Ubuntu/Kubuntu the
    system OpenSSL static archive itself references zlib,
    libzstd and libjitterentropy symbols, so that upstream
    link line fails with undefined references even when
    libssl-dev is installed (Duane's field failure,
    2026-11-24). The ladder below therefore tries, in
    order: the upstream static line; a dynamic link (the
    shared libcrypto carries its own dependencies); a
    dynamic link naming the compression libraries; and a
    dynamic link naming them by exact file name (for
    machines with only the runtime libraries, no -dev
    symlinks). The Makefile's LIBS variable is the append
    point its link rule already provides -- the engine
    source is never modified."""
    src = rifgen_src_dir()
    log("Building ps3xploit_rifgen_edatresign from source "
        "(the engine's own Makefile)...")
    seen = []

    def tap(line):
        seen.append(line)
        log(line)

    _run_stream(["make", "clean"], src, tap)
    attempts = [
        ("the upstream way (static, system OpenSSL)",
         ["make", "CFLAGS=" + MAKE_CFLAGS]),
        ("dynamic, against the shared system OpenSSL",
         ["make", "CFLAGS=" + MAKE_CFLAGS_DYNAMIC,
          "LIBS=-ldl -lpthread"]),
        ("dynamic, naming the compression libraries",
         ["make", "CFLAGS=" + MAKE_CFLAGS_DYNAMIC,
          "LIBS=-lz -lzstd -ldl -lpthread"]),
        ("dynamic, naming the compression libraries by "
         "exact file name",
         ["make", "CFLAGS=" + MAKE_CFLAGS_DYNAMIC,
          "LIBS=-l:libz.so.1 -l:libzstd.so.1 -ldl -lpthread"]),
    ]
    built = src / "ps3xploit_rifgen_edatresign"
    for label, cmd in attempts:
        log("Link attempt: %s..." % label)
        rc = _run_stream(cmd, src, tap)
        if rc == 0 and built.is_file():
            break
        log("That attempt did not produce the tool.")
    else:
        text = "\n".join(seen)
        if "undefined reference" in text \
                or "Failed to link" in text:
            raise RuntimeError(
                "The engine's code compiled fine, but "
                "LINKING it failed on this machine: the "
                "system OpenSSL static library pulls in "
                "extra pieces (the zlib, libzstd and "
                "jitterentropy libraries) that the engine's "
                "Makefile does not name, and every link "
                "variation the app knows was tried (see the "
                "output above). This is NOT a missing "
                "libssl-dev problem -- if that package is "
                "installed, installing it again will not "
                "help. The app package is supposed to carry "
                "a ready-built engine tool so this build "
                "never has to happen; this fallback build "
                "only runs when that carried tool is missing "
                "or damaged, so re-downloading the app "
                "package is the real fix.")
        raise RuntimeError(
            "Building the engine's rifgen tool failed (see "
            "the compiler output above). This fallback build "
            "needs a C/C++ toolchain and the OpenSSL "
            "development headers (on Debian/Ubuntu: "
            "build-essential and libssl-dev). The app "
            "package is supposed to carry a ready-built "
            "engine tool so this build never has to happen; "
            "it only runs when that carried tool is missing "
            "or damaged, so re-downloading the app package "
            "is the real fix.")
    dest_dir = rifgen_path().parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, rifgen_path())
    _run_stream(["make", "clean"], src, tap)
    log("rifgen built: %s (%d bytes)"
        % (rifgen_path(), rifgen_path().stat().st_size))


def _carried_tarball(log):
    """The engine source tarball carried in the package, if
    present and hash-true. Returns its path or None."""
    if not CARRIED_TARBALL.is_file():
        return None
    if _sha256_of(CARRIED_TARBALL) == ENGINE_SHA256:
        return CARRIED_TARBALL
    log("The engine source carried in the app package failed "
        "its SHA-256 check -- falling back to downloading "
        "the engine instead.")
    return None


def _install_carried_rifgen(log):
    """Install the ready-built rifgen carried in the package
    (Linux). Returns True when the carried binary verified
    against its pin and is in place. This is also the repair
    path for an engine folder left half-built by an older
    setup attempt: the tree is already there, only the tool
    was missing."""
    if not CARRIED_RIFGEN.is_file():
        return False
    if _sha256_of(CARRIED_RIFGEN) != RIFGEN_SHA256:
        log("The ready-built engine tool carried in the app "
            "package failed its SHA-256 check -- falling "
            "back to building it on this machine.")
        return False
    dest = rifgen_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CARRIED_RIFGEN, dest)
    dest.chmod(0o755)
    log("Installed the ready-built engine tool carried in "
        "the app package (SHA-256 verified, fully static -- "
        "it needs no libraries from this machine).")
    return True


def _verify_windows_rifgen(log):
    """Upstream's prebuilt Windows rifgen ships inside the
    pinned engine tree; verify it against its pin before it
    is ever run."""
    exe = rifgen_path()
    if _sha256_of(exe) != WINDOWS_RIFGEN_SHA256:
        raise RuntimeError(
            "The engine's prebuilt Windows tool does not "
            "match its pinned SHA-256, so it will not be "
            "run. The engine download was %s from the "
            "official repo; delete the engine folder (%s) "
            "and restart the app to set it up again."
            % (ENGINE_VERSION, ENGINE_DIR))
    log("The engine's prebuilt Windows tool passed its "
        "SHA-256 check.")


def ensure_engine(log=_noop):
    """First-run setup. The package carries the engine
    ready-built (hash-verified), so setup normally just
    unpacks it: no network, no compiler, no system
    libraries. Downloading the engine and building rifgen
    on this machine remain only as fallbacks for a missing
    or damaged carried payload. An engine folder left
    half-built by an older setup attempt (tree present,
    tool missing) is repaired by installing the carried
    tool into it. Returns True when the engine is ready.
    Raises RuntimeError with a plain message on failure."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if engine_ready():
        log("Engine already installed at %s" % ENGINE_DIR)
        return True
    if not engine_tree_present():
        archive = _carried_tarball(log)
        if archive is not None:
            log("Using the PS3Xploit Resigner %s source "
                "carried in the app package (SHA-256 "
                "verified) -- no download needed."
                % ENGINE_VERSION)
        else:
            archive = _download_engine(log)
        _extract_engine(archive, log)
    if is_windows():
        if not rifgen_path().is_file():
            raise RuntimeError(
                "The engine download is missing its prebuilt "
                "Windows rifgen tool (%s)." % rifgen_path())
        _verify_windows_rifgen(log)
        log("Using the engine's prebuilt Windows rifgen tool.")
    else:
        if not rifgen_path().is_file():
            if not _install_carried_rifgen(log):
                _build_rifgen_linux(log)
    if python27_path():
        log("python2.7 found (%s) -- the RIF installer "
            "package step can run on this machine."
            % python27_path())
    else:
        log("NOTE: python2.7 was not found on this machine. "
            "The engine needs it for ONE step -- building "
            "the RIF installer package. RAP files can still "
            "be turned into RIFs and PKGs can still be "
            "resigned without it, but the installer package "
            "step will report this plainly when you Generate.")
    return engine_ready()


def ensure_pkgcrypt(log=_noop):
    """Build ps3py's pkgcrypt extension with python2.7 (the
    script's own step), once. Returns (ok, reason). On
    Windows the prebuilt pkg_exdata.exe is used instead and
    this is always ok."""
    if is_windows():
        return (pkg_exdata_path().is_file(),
                "" if pkg_exdata_path().is_file()
                else "pkg_exdata.exe is missing from the "
                     "engine download.")
    if (ps3py_dir() / "pkgcrypt.so").is_file():
        return True, ""
    py27 = python27_path()
    if not py27:
        return False, (
            "python2.7 is not installed on this machine, and "
            "the engine's package builder (ps3py pkg.py) "
            "needs it. The RIF files themselves were "
            "generated fine -- only the installer package "
            "could not be built. Install python2.7 (with "
            "its development headers) and Generate again, "
            "or run the engine's resign_linux.sh on a "
            "machine that has it.")
    log("Building ps3py's pkgcrypt extension with "
        "python2.7 (one-time engine setup)...")
    try:
        rc = _run_stream([py27, "setup.py", "build"],
                         ps3py_dir(), log, timeout=600)
    except Exception as e:  # noqa: BLE001
        return False, "pkgcrypt build failed: %s" % e
    built = sorted(ps3py_dir().glob("build/lib.*/pkgcrypt.so"))
    if rc != 0 or not built:
        return False, (
            "Building ps3py's pkgcrypt extension failed "
            "(see the output above). It needs python2.7 "
            "with its development headers (on Debian/Ubuntu "
            "of the python2 era: python2.7-dev). The RIF "
            "files themselves were generated fine -- only "
            "the installer package could not be built.")
    shutil.copy2(built[0], ps3py_dir() / "pkgcrypt.so")
    log("pkgcrypt built and installed beside pkg.py.")
    return True, ""


# ---------------------------------------------------------------------
# the Generate run

class GenerateRunner:
    """One Generate run, mirroring resign_linux.sh /
    resign_windows.bat step for step, but staged in LOCAL
    scratch (never on a share, never on the originals) and
    with every claimed output verified on disk afterwards.

    job = {
      "act_dat": path or "", "idps_hex": path or "",
      "raps": [entry, ...], "pkgs": [entry, ...],
      "outdir": path,
    } where each entry is a dict with at least "path" and
    "status" -- the SAME dicts the window shows, mutated in
    place like the family's other runners.
    status(queue, idx, text) is called as entries move.
    """

    def __init__(self):
        self._cancel = threading.Event()
        self._procs = []

    def cancel(self):
        self._cancel.set()
        for proc in list(self._procs):
            try:
                if proc.poll() is None:
                    proc.terminate()
            except OSError:
                pass

    # -- helpers ------------------------------------------------

    def _rifgen(self, args, cwd, log, timeout):
        self._procs.clear()
        return _run_stream(
            [str(rifgen_path())] + [str(a) for a in args],
            cwd, log, input_text="\n\n", timeout=timeout,
            proc_holder=self._procs)

    @staticmethod
    def _verified(path):
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    # -- main ---------------------------------------------------

    def run(self, job, log=_noop, status=None):
        status = status or (lambda _q, _i, _s: None)
        outdir = Path(job["outdir"])
        outdir.mkdir(parents=True, exist_ok=True)
        summary = {"rif_pkg": None, "rifs_made": 0,
                   "pkgs_done": [], "failed": [],
                   "cancelled": False, "rif_error": None}
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        scratch = Path(SCRATCH_DIR / ("run-%d" % os.getpid()))
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        try:
            if job["raps"]:
                self._run_rif_job(job, scratch, outdir,
                                  summary, log, status)
            if job["pkgs"] and not self._cancel.is_set():
                self._run_pkg_job(job, scratch, outdir,
                                  summary, log, status)
            summary["cancelled"] = self._cancel.is_set()
            return summary
        finally:
            # The scratch holds copies of act.dat / idps.hex:
            # it goes away on EVERY exit.
            shutil.rmtree(scratch, ignore_errors=True)

    def _run_rif_job(self, job, scratch, outdir, summary,
                     log, status):
        raps = job["raps"]
        # ---- stage (the script's input/ folders, localised)
        for src, name in ((job["act_dat"], "act.dat"),
                          (job["idps_hex"], "idps.hex")):
            if not src or not Path(src).is_file():
                summary["rif_error"] = (
                    "%s was not found at %s -- the RIF job "
                    "needs your act.dat and idps.hex."
                    % (name, src or "(not chosen)"))
                log("FAILED: " + summary["rif_error"])
                return
            shutil.copy2(src, scratch / name)
        staged = []
        seen = set()
        for i, entry in enumerate(raps):
            name = Path(entry["path"]).name
            if name in seen:
                entry["status"] = "failed"
                status("rap", i, "failed")
                summary["failed"].append(
                    (name, "two queued RAP files share this "
                           "name; the engine works by file "
                           "name, so one of them cannot be "
                           "processed"))
                continue
            seen.add(name)
            shutil.copy2(entry["path"], scratch / name)
            staged.append((i, entry, name))
        if summary["failed"]:
            summary["rif_error"] = (
                "The RIF job stopped before signing: a "
                "queued RAP file could not be staged (see "
                "above). No installer package was made, so "
                "no game is silently dropped.")
            log("FAILED: " + summary["rif_error"])
            return

        # ---- sign each RAP (rifgen reads act.dat/idps.hex
        # from its cwd and writes <name>.rif beside the RAP)
        for i, entry, name in staged:
            if self._cancel.is_set():
                entry["status"] = "cancelled"
                status("rap", i, "cancelled")
                continue
            status("rap", i, "signing")
            entry["status"] = "signing"
            log("Signing %s ..." % name)
            try:
                rc = self._rifgen([scratch / name], scratch,
                                  log, timeout=300)
            except Exception as e:  # noqa: BLE001
                entry["status"] = "failed"
                status("rap", i, "failed")
                summary["failed"].append(
                    (name, "the engine errored: %s" % e))
                continue
            if rc != 0:
                # The engine can crash on a corrupt file
                # AFTER leaving an output behind -- a file
                # existing is not success when the engine
                # itself did not finish.
                entry["status"] = "failed"
                status("rap", i, "failed")
                summary["failed"].append(
                    (name, "the engine exited with code %s "
                           "on this file (a corrupt or "
                           "wrong-format RAP is the usual "
                           "cause)" % rc))
                (scratch / name).unlink(missing_ok=True)
                continue
            rif = scratch / (Path(name).stem + ".rif")
            if self._verified(rif):
                entry["status"] = "done"
                status("rap", i, "done")
                summary["rifs_made"] += 1
                log("  -> %s (%d bytes)"
                    % (rif.name, rif.stat().st_size))
            else:
                entry["status"] = "failed"
                status("rap", i, "failed")
                summary["failed"].append(
                    (name, "the engine did not produce a RIF "
                           "for this file (its output above "
                           "says why -- a corrupt or wrong RAP "
                           "file is the usual cause)"))
            # the script removes each RAP copy once signed
            (scratch / name).unlink(missing_ok=True)
        if self._cancel.is_set():
            return
        if summary["failed"]:
            summary["rif_error"] = (
                "The RIF job stopped: %d of %d RAP file(s) "
                "failed (see the log). No installer package "
                "was made, so no game is silently dropped."
                % (len(summary["failed"]), len(staged)))
            log("FAILED: " + summary["rif_error"])
            return

        # ---- the re-signed act.dat
        signed_act = scratch / "signed_act.dat"
        if not self._verified(signed_act):
            summary["rif_error"] = (
                "The engine did not produce signed_act.dat, "
                "so the installer package cannot be built.")
            log("FAILED: " + summary["rif_error"])
            return
        (scratch / "act.dat").unlink(missing_ok=True)
        (scratch / "idps.hex").unlink(missing_ok=True)
        signed_act.rename(scratch / "act.dat")

        # ---- build the installer package (engine machinery)
        ok, reason = ensure_pkgcrypt(log)
        if not ok:
            summary["rif_error"] = reason
            log("FAILED: " + reason)
            return
        pkg_out = scratch / RIF_PKG_NAME
        log("Building the RIF installer package...")
        try:
            if is_windows():
                rc = _run_stream(
                    [str(pkg_exdata_path()), "--contentid",
                     RIF_PKG_CONTENTID, str(scratch) + os.sep,
                     str(pkg_out)],
                    ENGINE_DIR, log, timeout=900,
                    proc_holder=self._procs)
            else:
                rc = _run_stream(
                    [python27_path(), str(pkgpy_path()),
                     "--contentid", RIF_PKG_CONTENTID,
                     str(scratch) + os.sep, str(pkg_out)],
                    ENGINE_DIR, log, timeout=900,
                    proc_holder=self._procs)
        except Exception as e:  # noqa: BLE001
            summary["rif_error"] = (
                "Building the installer package errored: %s"
                % e)
            log("FAILED: " + summary["rif_error"])
            return
        if rc != 0 or not self._verified(pkg_out):
            summary["rif_error"] = (
                "The package builder did not produce %s "
                "(exit code %s) -- see its output above."
                % (RIF_PKG_NAME, rc))
            log("FAILED: " + summary["rif_error"])
            return

        # ---- resign the installer package and deliver it
        log("Resigning the installer package...")
        try:
            rc = self._rifgen([pkg_out], scratch, log,
                              timeout=900)
            if rc != 0:
                summary["rif_error"] = (
                    "Resigning the installer package failed: "
                    "the engine exited with code %s." % rc)
                log("FAILED: " + summary["rif_error"])
                return
        except Exception as e:  # noqa: BLE001
            summary["rif_error"] = (
                "Resigning the installer package errored: %s"
                % e)
            log("FAILED: " + summary["rif_error"])
            return
        signed_pkg = scratch / RIF_PKG_SIGNED_NAME
        if not self._verified(signed_pkg):
            summary["rif_error"] = (
                "The engine did not produce %s after "
                "resigning -- see its output above."
                % RIF_PKG_SIGNED_NAME)
            log("FAILED: " + summary["rif_error"])
            return
        dest = outdir / RIF_PKG_SIGNED_NAME
        shutil.copy2(signed_pkg, dest)
        if not self._verified(dest):
            summary["rif_error"] = (
                "Copying %s into the output folder failed."
                % RIF_PKG_SIGNED_NAME)
            log("FAILED: " + summary["rif_error"])
            return
        summary["rif_pkg"] = str(dest)
        log("RIF installer package ready: %s (%d bytes)"
            % (dest, dest.stat().st_size))

    def _run_pkg_job(self, job, scratch, outdir, summary,
                     log, status):
        for i, entry in enumerate(job["pkgs"]):
            if self._cancel.is_set():
                entry["status"] = "cancelled"
                status("pkg", i, "cancelled")
                continue
            name = Path(entry["path"]).name
            status("pkg", i, "resigning")
            entry["status"] = "resigning"
            log("Resigning %s ..." % name)
            staged = scratch / name
            try:
                shutil.copy2(entry["path"], staged)
            except OSError as e:
                entry["status"] = "failed"
                status("pkg", i, "failed")
                summary["failed"].append(
                    (name, "could not copy the package into "
                           "local scratch: %s" % e))
                continue
            try:
                rc = self._rifgen([staged], scratch, log,
                                  timeout=3600)
            except Exception as e:  # noqa: BLE001
                entry["status"] = "failed"
                status("pkg", i, "failed")
                summary["failed"].append(
                    (name, "the engine errored: %s" % e))
                staged.unlink(missing_ok=True)
                continue
            if rc != 0:
                # rifgen can segfault on a malformed package
                # AFTER writing a _signed.pkg -- never call
                # that a success.
                entry["status"] = "failed"
                status("pkg", i, "failed")
                summary["failed"].append(
                    (name, "the engine exited with code %s "
                           "on this package (it crashes on "
                           "malformed packages; a corrupt or "
                           "not-really-a-PKG file is the "
                           "usual cause) -- the partial "
                           "output it left behind was "
                           "discarded" % rc))
                staged.unlink(missing_ok=True)
                (scratch / (name + "_signed.pkg")).unlink(
                    missing_ok=True)
                continue
            signed = scratch / (name + "_signed.pkg")
            if self._verified(signed):
                dest = outdir / (name + "_signed.pkg")
                shutil.copy2(signed, dest)
                if self._verified(dest):
                    entry["status"] = "done"
                    status("pkg", i, "done")
                    summary["pkgs_done"].append(str(dest))
                    log("  -> %s (%d bytes)"
                        % (dest.name, dest.stat().st_size))
                else:
                    entry["status"] = "failed"
                    status("pkg", i, "failed")
                    summary["failed"].append(
                        (name, "copying the resigned package "
                               "into the output folder "
                               "failed"))
            else:
                entry["status"] = "failed"
                status("pkg", i, "failed")
                summary["failed"].append(
                    (name, "the engine did not produce a "
                           "resigned package for this file "
                           "(its output above says why -- a "
                           "corrupt or already-retail package "
                           "is the usual cause)"))
            staged.unlink(missing_ok=True)
            signed.unlink(missing_ok=True)
