"""Tests for app/netshare.py, driven by a stub `gio`.

This VM has no GVFS/FUSE, so the harness fakes both sides
of the real thing:

* a stub `gio` executable on PATH whose behaviour is set
  by $FAKE_GIO_MODE (already / prompt / fail), and which
  answers `gio mount -l` with $FAKE_GIO_LIST_URI;
* a fake GVFS mount root under a temp XDG_RUNTIME_DIR,
  populated with `smb-share:server=...,share=...`
  directories shaped exactly like the real ones.

Covered:

* the 2026-11-24 field bug -- the share is ALREADY
  mounted, but under a different spelling of the server
  (an alias), so find_mount()'s strict match misses it,
  `gio mount` answers "Location is already mounted",
  and the old code raised that as a fatal error. The
  browse must now proceed to the existing mount path,
  resolved (a) via the `gio mount -l` listing and
  (b) via the share-only gvfs scan when the listing is
  empty.
* the credential-prompt fix stays intact: gio asks
  Domain FIRST, then Password, under a header line that
  itself contains the word "password"; WORKGROUP must
  land in the Domain prompt and the password in the
  Password prompt.
* a genuine mount failure still raises NetShareError.
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent
           / "src" / "PS3XploitResignerGUI" / "app"))

import netshare  # noqa: E402

FAKE_GIO = r"""#!/bin/bash
if [ "$1" = "mount" ] && [ "$2" = "-l" ]; then
  if [ -n "$FAKE_GIO_LIST_URI" ]; then
    echo "Mount(0): share on server -> $FAKE_GIO_LIST_URI"
    echo "  Type: GProxyMount (GProxyVolumeMonitor)"
  fi
  exit 0
fi
if [ "$1" = "mount" ]; then
  url="$2"
  case "$FAKE_GIO_MODE" in
    already)
      echo "gio: $url: Location is already mounted" >&2
      exit 1 ;;
    prompt)
      echo "Enter password for share “PS2 ARCHIVE” on 192.168.0.102:"
      printf "Domain: "
      read -r a1
      printf "Password: "
      read -r a2
      printf "%s\n%s\n" "$a1" "$a2" > "$FAKE_GIO_ANSWERS"
      mkdir -p "$XDG_RUNTIME_DIR/gvfs/$FAKE_GIO_MOUNTNAME"
      exit 0 ;;
    fail)
      echo "gio: $url: Connection refused" >&2
      exit 1 ;;
  esac
fi
exit 2
"""

SERVER = "192.168.0.102"
ALIAS = "fileserver"
SHARE = "PS2 ARCHIVE"
CANON_MOUNT = "smb-share:server=%s,share=ps2 archive" % SERVER
ALIAS_MOUNT = "smb-share:server=%s,share=ps2 archive" % ALIAS


class NetShareHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(
            prefix="netshare-test-"))
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        gio = self.bindir / "gio"
        gio.write_text(FAKE_GIO)
        gio.chmod(gio.stat().st_mode | stat.S_IXUSR)
        self.runtime = self.tmp / "runtime"
        self.gvfs = self.runtime / "gvfs"
        self.gvfs.mkdir(parents=True)
        self.answers = self.tmp / "answers.txt"
        self._saved_env = dict(os.environ)
        os.environ["PATH"] = "%s:%s" % (
            self.bindir, self._saved_env.get("PATH", ""))
        os.environ["XDG_RUNTIME_DIR"] = str(self.runtime)
        os.environ["FAKE_GIO_ANSWERS"] = str(self.answers)
        os.environ["FAKE_GIO_MOUNTNAME"] = CANON_MOUNT

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def mode(self, mode, list_uri=""):
        os.environ["FAKE_GIO_MODE"] = mode
        os.environ["FAKE_GIO_LIST_URI"] = list_uri

    def add_mount(self, name):
        path = self.gvfs / name
        path.mkdir()
        return str(path)

    # -- the field bug ------------------------------------
    def test_already_mounted_resolved_via_gio_list(self):
        want = self.add_mount(ALIAS_MOUNT)
        self.mode("already",
                  "smb://billtookahit420@%s/PS2%%20ARCHIVE/"
                  % ALIAS)
        # strict match must miss (alias server), proving
        # the browse really goes through gio + the resolver
        self.assertIsNone(netshare.find_mount(SERVER, SHARE))
        got = netshare.connect(SERVER, SHARE,
                               "billtookahit420", "pw")
        self.assertEqual(got, want)
        self.assertTrue(Path(got).is_dir())

    def test_already_mounted_resolved_via_share_scan(self):
        want = self.add_mount(ALIAS_MOUNT)
        self.mode("already", "")
        got = netshare.connect(SERVER, SHARE,
                               "billtookahit420", "pw")
        self.assertEqual(got, want)

    def test_already_mounted_canonical_still_fast_path(self):
        want = self.add_mount(CANON_MOUNT)
        self.mode("already", "")
        got = netshare.connect(SERVER, SHARE,
                               "billtookahit420", "pw")
        self.assertEqual(got, want)

    # -- credential prompts (regression) ------------------
    def test_domain_then_password_prompts(self):
        self.mode("prompt")
        got = netshare.connect(SERVER, SHARE,
                               "billtookahit420", "s3cret")
        self.assertEqual(got, str(self.gvfs / CANON_MOUNT))
        answers = self.answers.read_text().splitlines()
        self.assertEqual(answers, ["WORKGROUP", "s3cret"])

    # -- genuine failure still fails ----------------------
    def test_real_failure_raises(self):
        self.mode("fail")
        with self.assertRaises(netshare.NetShareError):
            netshare.connect(SERVER, SHARE,
                             "billtookahit420", "pw")


if __name__ == "__main__":
    unittest.main(verbosity=2)
