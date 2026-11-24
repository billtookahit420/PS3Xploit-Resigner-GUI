"""PS3Xploit Resigner GUI -- add games to your PS3 act.dat.

The one job this app does: the PS3Xploit Resigner's RAP -> RIF
flow. Pick your console's act.dat and idps.hex, queue the .rap
files for the games you are adding, and Generate produces the
signed RIF installer package (PKG_RIF-INSTALLER.pkg_signed.pkg)
that you install on the PS3 to register the licenses. An
optional checkbox also resigns queued .pkg files (DEBUG ->
HAN style) with the same engine.

The engine is the PS3Xploit Resigner itself (V3.0.0),
downloaded at first run and driven the way its own scripts
drive it -- no cryptography is reimplemented here.

Engine by the PS3Xploit Team --
https://github.com/PS3Xploit/PS3xploit-resigner (GPL-3.0)
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import netshare  # noqa: E402
import resigner_engine as engine  # noqa: E402

from PySide6.QtCore import Qt, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)


_LOG_DIVIDER = ("----- previous session's log restored above; "
                "this session continues below -----")


class NetworkShareDialog(QDialog):
    """Server + share (+ optional sign-in) for one network
    share, with the remembered shares one click away. The
    dialog only collects the fields; the caller does the
    actual connect (which can take seconds) in a worker.
    Passwords are never stored -- only server/share/username
    are remembered."""

    def __init__(self, parent, shares):
        super().__init__(parent)
        self.setWindowTitle("Connect to a network share")
        self.shares = [dict(s) for s in shares]
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Your game files live on the server, so connect "
            "to one of its SMB shares here. On Linux the share "
            "is mounted for you (no root needed); on Windows "
            "its \\\\SERVER\\share path is used directly.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        if self.shares:
            lay.addWidget(QLabel("Remembered shares:"))
            self.list = QListWidget()
            for s in self.shares:
                self.list.addItem("%s / %s"
                                  % (s.get("server", ""),
                                     s.get("share", "")))
            self.list.currentRowChanged.connect(self._fill)
            self.list.itemDoubleClicked.connect(
                lambda _i: self.accept())
            lay.addWidget(self.list)
            forget = QPushButton("Forget selected share")
            forget.clicked.connect(self._forget)
            lay.addWidget(forget)
        else:
            self.list = None
        form = QFormLayout()
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("192.168.0.102")
        form.addRow("Server:", self.server_edit)
        self.share_edit = QLineEdit()
        self.share_edit.setPlaceholderText("PS3 ARCHIVE")
        form.addRow("Share:", self.share_edit)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText(
            "optional -- blank for a guest share")
        form.addRow("Username:", self.user_edit)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText(
            "optional -- never saved")
        form.addRow("Password:", self.pass_edit)
        lay.addLayout(form)
        brow = QHBoxLayout()
        brow.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        brow.addWidget(cancel)
        connect = QPushButton("Connect")
        connect.setDefault(True)
        connect.clicked.connect(self._connect)
        brow.addWidget(connect)
        lay.addLayout(brow)

    def _fill(self, row):
        if 0 <= row < len(self.shares):
            s = self.shares[row]
            self.server_edit.setText(s.get("server", ""))
            self.share_edit.setText(s.get("share", ""))
            self.user_edit.setText(s.get("username", ""))

    def _forget(self):
        if self.list is None:
            return
        row = self.list.currentRow()
        if 0 <= row < len(self.shares):
            del self.shares[row]
            self.list.takeItem(row)

    def _connect(self):
        if not self.server_edit.text().strip() \
                or not self.share_edit.text().strip():
            QMessageBox.warning(self, "Missing details",
                                "Enter both a server and a "
                                "share name.")
            return
        self.accept()

    def values(self):
        return {
            "server": self.server_edit.text().strip(),
            "share": self.share_edit.text().strip(),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
        }


class Worker(QThread):
    """Runs one engine callable in the background. Workers are
    held in a set on the window until they finish -- letting a
    worker reference be overwritten while it runs is what
    aborted sibling apps, so it is designed out here."""
    log = Signal(str)
    status = Signal(str, int, str)
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn(
                lambda s: self.log.emit(str(s)),
                lambda q, i, s: self.status.emit(
                    str(q), int(i), str(s)))
        except Exception as e:  # noqa: BLE001
            self.done.emit({"error": "%s: %s"
                            % (type(e).__name__, e)})
            return
        self.done.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            "PS3Xploit Resigner GUI -- add games to your "
            "act.dat")
        self.resize(980, 760)
        self.rap_entries = []
        self.pkg_entries = []
        self._workers = set()
        self._runner = None
        self._generating = False
        self._last_summary = None
        self._restoring = False
        self.settings = self._load_settings()

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)

        header = QLabel(
            "<b>PS3Xploit Resigner GUI</b> -- turn .rap "
            "files into a signed RIF installer package "
            "against your PS3's act.dat, adding the games "
            "to your console.")
        header.setWordWrap(True)
        lay.addWidget(header)
        credit = QLabel(
            "Engine: PS3Xploit Resigner by the PS3Xploit "
            "Team -- https://github.com/PS3Xploit/"
            "PS3xploit-resigner (GPL-3.0), downloaded on "
            "first run; this GUI drives it, it does not "
            "replace it.")
        credit.setWordWrap(True)
        lay.addWidget(credit)

        # ---- console files --------------------------------
        lay.addWidget(QLabel("<b>Your console files</b> "
                             "(kept private -- only their "
                             "locations are remembered)"))
        for key, label in (("act_dat", "act.dat:"),
                           ("idps_hex", "idps.hex:")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit = QLineEdit()
            edit.setReadOnly(True)
            row.addWidget(edit, 1)
            browse = QPushButton("Browse...")
            browse.clicked.connect(
                lambda _c=False, k=key: self._browse_console(k))
            row.addWidget(browse)
            net = QPushButton("Network...")
            net.clicked.connect(
                lambda _c=False, k=key: self._net_add(k))
            row.addWidget(net)
            lay.addLayout(row)
            setattr(self, key + "_edit", edit)

        # ---- RAP queue ------------------------------------
        lay.addWidget(QLabel("<b>Games to add (RAP files)</b>"))
        self.rap_table = self._make_table()
        lay.addWidget(self.rap_table, 1)
        lay.addLayout(self._queue_buttons(
            "rap", self._add_rap_files, self._add_rap_folder,
            lambda: self._remove_selected("rap")))

        # ---- optional PKG resign --------------------------
        self.resign_check = QCheckBox(
            "Also resign packages (optional -- off by "
            "default)")
        self.resign_check.toggled.connect(
            self._resign_toggled)
        lay.addWidget(self.resign_check)
        self.pkg_group = QWidget()
        pkg_lay = QVBoxLayout(self.pkg_group)
        pkg_lay.setContentsMargins(0, 0, 0, 0)
        pkg_lay.addWidget(QLabel(
            "<b>Packages to resign (DEBUG -> HAN style)</b>"))
        self.pkg_table = self._make_table()
        pkg_lay.addWidget(self.pkg_table, 1)
        pkg_lay.addLayout(self._queue_buttons(
            "pkg", self._add_pkg_files, self._add_pkg_folder,
            lambda: self._remove_selected("pkg")))
        self.pkg_group.setVisible(False)
        lay.addWidget(self.pkg_group, 1)

        # ---- output ---------------------------------------
        orow = QHBoxLayout()
        orow.addWidget(QLabel("<b>Output folder:</b>"))
        self.output_edit = QLineEdit()
        orow.addWidget(self.output_edit, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_output())
        orow.addWidget(browse)
        browse_net = QPushButton("Network...")
        browse_net.clicked.connect(
            lambda: self._net_add("output"))
        orow.addWidget(browse_net)
        lay.addLayout(orow)

        # ---- generate row ---------------------------------
        grow = QHBoxLayout()
        grow.addStretch(1)
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self._generate)
        grow.addWidget(self.generate_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        grow.addWidget(self.cancel_btn)
        lay.addLayout(grow)

        # ---- log ------------------------------------------
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        lay.addWidget(self.log_view, 1)

        # ---- status bar -----------------------------------
        self.stage_label = QLabel("Starting...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(200)
        self.progress_bar.setMaximumWidth(300)
        status_bar = self.statusBar()
        status_bar.addWidget(self.stage_label, 1)
        status_bar.addPermanentWidget(self.progress_bar)

        self._smoke_cfg = None
        self._apply_settings()
        self._restore_state()
        self._restore_session_log()
        if engine.engine_ready():
            self._set_stage("Ready -- engine found.")
            self.log("PS3Xploit Resigner engine found at %s"
                     % engine.ENGINE_DIR)
        else:
            self._set_stage("First-run setup: starting...")
            self._set_progress_busy()
            self.log("The PS3Xploit Resigner engine is not "
                     "installed yet in %s -- starting "
                     "first-run setup. The package carries a "
                     "ready-built engine, so this normally "
                     "just unpacks it -- no downloads, no "
                     "compiling. Watch this log."
                     % engine.ENGINE_DIR)
            self._start_setup()
        self._smoke_maybe_start()

    # -------------------------------------------------- util
    def log(self, msg):
        self.log_view.appendPlainText(str(msg))
        try:
            engine.DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(engine.SESSION_LOG_PATH, "a") as fh:
                fh.write(str(msg) + "\n")
        except OSError:
            pass
        sink = getattr(self, "_smoke_log_sink", None)
        if sink is not None:
            try:
                with open(sink, "a") as fh:
                    fh.write(str(msg) + "\n")
            except OSError:
                pass

    def _set_stage(self, text):
        self.stage_label.setText(text)

    def _set_progress_busy(self):
        self.progress_bar.setRange(0, 0)

    def _set_progress(self, done, total):
        if total and total > 0:
            self.progress_bar.setRange(0, int(total))
            self.progress_bar.setValue(
                max(0, min(int(done), int(total))))
        else:
            self._set_progress_busy()

    def _reset_progress(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

    def _start_worker(self, worker):
        self._workers.add(worker)
        worker.log.connect(self.log)
        worker.finished.connect(
            lambda w=worker: self._workers.discard(w))
        worker.start()
        return worker

    # ------------------------------------------------ settings
    def _load_settings(self):
        try:
            return json.loads(engine.SETTINGS_PATH.read_text())
        except Exception:  # noqa: BLE001
            return {}

    def _save_settings(self):
        data = {
            "act_dat_path": self.act_dat_edit.text().strip(),
            "idps_hex_path": self.idps_hex_edit.text().strip(),
            "output_dir": self.output_edit.text().strip(),
            "resign_pkgs": self.resign_check.isChecked(),
            "last_add_dir": self.settings.get(
                "last_add_dir", ""),
            "network_shares": self.settings.get(
                "network_shares", []),
        }
        self.settings.update(data)
        try:
            engine.DATA_DIR.mkdir(parents=True, exist_ok=True)
            engine.SETTINGS_PATH.write_text(
                json.dumps(data, indent=2))
        except OSError:
            pass

    def _apply_settings(self):
        self.act_dat_edit.setText(
            self.settings.get("act_dat_path", ""))
        self.idps_hex_edit.setText(
            self.settings.get("idps_hex_path", ""))
        self.output_edit.setText(
            self.settings.get("output_dir", ""))
        self.resign_check.setChecked(
            bool(self.settings.get("resign_pkgs", False)))
        self._resign_toggled(self.resign_check.isChecked())

    # ------------------------------------------------ state
    def _save_state(self):
        if self._restoring:
            return
        data = {"raps": self.rap_entries,
                "pkgs": self.pkg_entries}
        try:
            engine.DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = engine.STATE_PATH.with_name(
                engine.STATE_PATH.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, engine.STATE_PATH)
        except OSError:
            pass

    def _restore_state(self):
        try:
            saved = json.loads(engine.STATE_PATH.read_text())
        except Exception:  # noqa: BLE001
            return
        self._restoring = True
        try:
            for entry in saved.get("raps", []):
                self._restore_entry("rap", entry)
            for entry in saved.get("pkgs", []):
                self._restore_entry("pkg", entry)
        finally:
            self._restoring = False
        total = len(self.rap_entries) + len(self.pkg_entries)
        if total:
            self.log("Restored %d queued file(s) from the "
                     "previous session." % total)

    def _restore_entry(self, queue, entry):
        entry = dict(entry)
        if entry.get("status") in ("signing", "resigning"):
            entry["status"] = "interrupted (app closed)"
        entry.setdefault("status", "queued")
        self._append_row(queue, entry)

    def _restore_session_log(self):
        try:
            path = engine.SESSION_LOG_PATH
            if not path.is_file():
                return
            text = path.read_text(errors="replace")
            lines = text.splitlines()
            if len(lines) > 3000:
                lines = lines[-3000:]
                path.write_text("\n".join(lines) + "\n")
                text = "\n".join(lines)
            if not text.strip():
                return
            self._restored_log_text = text
            # The divider goes into the FILE now so the file
            # keeps true session order; the view catches up
            # from a zero-delay timer (filling the view
            # during __init__ crashes this PySide build in
            # its exit teardown -- the PopFE lesson).
            with open(path, "a") as fh:
                fh.write(_LOG_DIVIDER + "\n")
            QTimer.singleShot(0, self._show_restored_log)
        except OSError:
            pass

    def _show_restored_log(self):
        text = getattr(self, "_restored_log_text", None)
        if text:
            cursor = self.log_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.insertText(text.rstrip("\n") + "\n"
                              + _LOG_DIVIDER + "\n")
            self._restored_log_text = None

    # ------------------------------------------------ tables
    def _make_table(self):
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["File", "Status"])
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        return table

    def _queue_buttons(self, queue, add_files, add_folder,
                       remove):
        row = QHBoxLayout()
        b = QPushButton("Add Files...")
        b.clicked.connect(add_files)
        row.addWidget(b)
        b = QPushButton("Add Folder...")
        b.clicked.connect(add_folder)
        row.addWidget(b)
        net_btn = QToolButton()
        net_btn.setText("Network Share...")
        net_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(net_btn)
        for label, what in (
                ("Add Files from a share...",
                 queue + "_files"),
                ("Add Folder from a share...",
                 queue + "_folder")):
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _c=False, w=what: self._net_add(w))
        net_btn.setMenu(menu)
        row.addWidget(net_btn)
        b = QPushButton("Remove Selected")
        b.clicked.connect(remove)
        row.addWidget(b)
        row.addStretch(1)
        return row

    def _table_for(self, queue):
        return self.rap_table if queue == "rap" \
            else self.pkg_table

    def _entries_for(self, queue):
        return self.rap_entries if queue == "rap" \
            else self.pkg_entries

    def _append_row(self, queue, entry):
        entries = self._entries_for(queue)
        entries.append(entry)
        table = self._table_for(queue)
        row = table.rowCount()
        table.insertRow(row)
        item = QTableWidgetItem(Path(entry["path"]).name)
        item.setToolTip(entry["path"])
        table.setItem(row, 0, item)
        table.setItem(row, 1, QTableWidgetItem(
            entry.get("status", "queued")))
        if not self._restoring:
            self._save_state()

    def add_paths(self, queue, paths):
        """Append files to a queue (dialogs and the smoke
        hook both come through here)."""
        ext = ".rap" if queue == "rap" else ".pkg"
        added = 0
        for p in paths:
            p = str(p)
            if not p.lower().endswith(ext):
                continue
            if any(e["path"] == p
                   for e in self._entries_for(queue)):
                continue
            self._append_row(queue, {"path": p,
                                     "status": "queued"})
            added += 1
        if added:
            self._set_stage("Queued %d file(s). Ready."
                            % added)
        return added

    def add_folder(self, queue, folder):
        """Add every matching file at the TOP level of a
        folder (the engine's own input folders are flat)."""
        ext = ".rap" if queue == "rap" else ".pkg"
        try:
            files = sorted(
                str(p) for p in Path(folder).iterdir()
                if p.is_file()
                and p.suffix.lower() == ext)
        except OSError:
            files = []
        if not files:
            self.log("No %s files found in %s" % (ext, folder))
        return self.add_paths(queue, files)

    def _remove_selected(self, queue):
        if self._generating:
            return
        table = self._table_for(queue)
        entries = self._entries_for(queue)
        rows = sorted({i.row() for i in
                       table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)
            del entries[row]
        if rows:
            self._save_state()

    # ------------------------------------------------ pickers
    def _browse_console(self, key, start=None):
        label = "act.dat" if key == "act_dat" else "idps.hex"
        if start is None:
            start = self.settings.get("last_add_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose your %s" % label, start,
            "%s (%s);;All files (*)" % (label, label))
        if path:
            self.settings["last_add_dir"] = str(
                Path(path).parent)
            getattr(self, key + "_edit").setText(path)
            self._save_settings()

    def _browse_output(self, start=None):
        if start is None:
            start = self.output_edit.text().strip() \
                or self.settings.get("last_add_dir", "")
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the output folder", start)
        if folder:
            self.output_edit.setText(folder)
            self._save_settings()

    def _pick_files(self, queue, start=None):
        ext = "*.rap" if queue == "rap" else "*.pkg"
        label = "RAP" if queue == "rap" else "PKG"
        if start is None:
            start = self.settings.get("last_add_dir", "")
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add %s files" % label, start,
            "%s files (%s);;All files (*)" % (label, ext))
        if files:
            self.settings["last_add_dir"] = str(
                Path(files[0]).parent)
            self.add_paths(queue, files)

    def _pick_folder(self, queue, start=None):
        if start is None:
            start = self.settings.get("last_add_dir", "")
        folder = QFileDialog.getExistingDirectory(
            self, "Add a folder of files", start)
        if folder:
            self.settings["last_add_dir"] = folder
            self.add_folder(queue, folder)

    def _add_rap_files(self, start=None):
        self._pick_files("rap", start)

    def _add_rap_folder(self, start=None):
        self._pick_folder("rap", start)

    def _add_pkg_files(self, start=None):
        self._pick_files("pkg", start)

    def _add_pkg_folder(self, start=None):
        self._pick_folder("pkg", start)

    # ------------------------------------------------ network
    def _remember_share(self, vals):
        shares = [s for s in self.settings.get(
            "network_shares", [])
            if not (s.get("server", "").lower()
                    == vals["server"].lower()
                    and s.get("share", "").lower()
                    == vals["share"].lower())]
        shares.append({"server": vals["server"],
                       "share": vals["share"],
                       "username": vals["username"]})
        self.settings["network_shares"] = shares[-12:]
        self._save_settings()

    def _net_add(self, what):
        """Connect to a network share, then run the matching
        picker starting INSIDE the share. `what` is one of:
        act_dat, idps_hex, output, rap_files, rap_folder,
        pkg_files, pkg_folder."""
        dlg = NetworkShareDialog(
            self, self.settings.get("network_shares", []))
        if dlg.exec() != QDialog.Accepted:
            self.settings["network_shares"] = dlg.shares
            self._save_settings()
            return
        self.settings["network_shares"] = dlg.shares
        vals = dlg.values()
        self._set_stage("Connecting to \\\\%s\\%s ..."
                        % (vals["server"], vals["share"]))
        self._set_progress_busy()

        def fn(log, status):
            root = netshare.connect(
                vals["server"], vals["share"],
                vals["username"], vals["password"], log)
            return {"root": root}

        worker = Worker(fn)
        worker.done.connect(
            lambda result: self._net_connected(result, vals,
                                               what))
        self._start_worker(worker)

    def _net_connected(self, result, vals, what):
        self._reset_progress()
        if not isinstance(result, dict) or result.get("error") \
                or not result.get("root"):
            msg = (result.get("error") if isinstance(
                result, dict) else None) \
                or "the share did not answer"
            msg = msg.split(": ", 1)[-1] if msg.startswith(
                "NetShareError") else msg
            self._set_stage("Network share failed -- see "
                            "the log.")
            self.log("Network share \\\\%s\\%s failed: %s"
                     % (vals["server"], vals["share"], msg))
            QMessageBox.warning(self, "Network share", msg)
            return
        root = result["root"]
        self._remember_share(vals)
        self.log("Network share \\\\%s\\%s ready at %s"
                 % (vals["server"], vals["share"], root))
        self._set_stage("Share ready -- pick from %s" % root)
        if what == "output":
            self._browse_output(start=root)
        elif what in ("act_dat", "idps_hex"):
            self._browse_console(what, start=root)
        elif what == "rap_files":
            self._add_rap_files(start=root)
        elif what == "rap_folder":
            self._add_rap_folder(start=root)
        elif what == "pkg_files":
            self._add_pkg_files(start=root)
        elif what == "pkg_folder":
            self._add_pkg_folder(start=root)

    # ------------------------------------------------ setup
    def _start_setup(self):
        self._set_stage("First-run setup: downloading and "
                        "building the engine...")
        self._set_progress_busy()

        def fn(log, status):
            status("setup", -1, "First-run setup: "
                                "downloading the engine...")
            ok = engine.ensure_engine(log)
            return {"ok": ok}

        worker = Worker(fn)
        worker.status.connect(self._setup_status)
        worker.done.connect(self._setup_done)
        self._start_worker(worker)

    def _setup_status(self, queue, idx, text):
        if idx == -1:
            self._set_stage(text)

    def _setup_done(self, result):
        self._reset_progress()
        if isinstance(result, dict) and result.get("ok"):
            self._set_stage("Ready -- engine installed.")
            self.log("Engine setup finished -- ready.")
        elif isinstance(result, dict) and result.get("error"):
            self._set_stage("Setup hit an error -- see "
                            "the log.")
            self.log("Engine setup hit an error: %s"
                     % result["error"])
        else:
            self._set_stage("Setup did not complete -- see "
                            "the log.")
            self.log("Engine setup did not complete "
                     "cleanly; see the log above.")

    # ------------------------------------------------ generate
    def _resign_toggled(self, checked):
        self.pkg_group.setVisible(bool(checked))

    def _generate(self):
        if self._generating:
            return
        raps = list(self.rap_entries)
        pkgs = list(self.pkg_entries) \
            if self.resign_check.isChecked() else []
        if not raps and not pkgs:
            QMessageBox.information(
                self, "Nothing queued",
                "Queue at least one .rap file (or check "
                "'Also resign packages' and queue a .pkg).")
            return
        outdir = self.output_edit.text().strip()
        if not outdir:
            QMessageBox.warning(
                self, "No output folder",
                "Choose an output folder first -- that is "
                "where the finished package(s) are written.")
            return
        if raps:
            missing = []
            if not self.act_dat_edit.text().strip():
                missing.append("act.dat")
            if not self.idps_hex_edit.text().strip():
                missing.append("idps.hex")
            if missing:
                QMessageBox.warning(
                    self, "Console files not chosen",
                    "The RIF job needs your %s -- pick them "
                    "at the top of the window first."
                    % " and ".join(missing))
                return
        if not engine.engine_ready():
            self.log("The engine is not ready yet -- "
                     "running setup first. Press Generate "
                     "again when the log says the engine "
                     "is ready.")
            self._start_setup()
            return
        self._save_settings()
        self._save_state()
        job = {
            "act_dat": self.act_dat_edit.text().strip(),
            "idps_hex": self.idps_hex_edit.text().strip(),
            "raps": raps,
            "pkgs": pkgs,
            "outdir": outdir,
        }
        runner = engine.GenerateRunner()
        self._runner = runner
        self._generating = True
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        total = len(raps) + len(pkgs)
        self._set_progress(0, total)
        self._set_stage("Generating...")

        def fn(log, status):
            return runner.run(job, log, status)

        worker = Worker(fn)
        worker.status.connect(self._entry_status)
        worker.done.connect(self._generate_done)
        self._start_worker(worker)

    def _entry_status(self, queue, idx, text):
        table = self._table_for(queue)
        if 0 <= idx < table.rowCount():
            item = table.item(idx, 1)
            if item:
                item.setText(text)
        entries = self._entries_for(queue)
        if 0 <= idx < len(entries):
            self._set_stage("%s %d: %s -- %s"
                            % ("Signing" if queue == "rap"
                               else "Resigning",
                               idx + 1,
                               Path(entries[idx]["path"]).name,
                               text))
        finished = sum(
            1 for e in self.rap_entries + self.pkg_entries
            if e.get("status") in ("done", "failed",
                                   "cancelled"))
        self._set_progress(
            finished,
            len(self.rap_entries)
            + (len(self.pkg_entries)
               if self.resign_check.isChecked() else 0))
        self._save_state()

    def _generate_done(self, result):
        self._generating = False
        self._runner = None
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        for queue in ("rap", "pkg"):
            table = self._table_for(queue)
            for i, entry in enumerate(
                    self._entries_for(queue)):
                if i < table.rowCount():
                    item = table.item(i, 1)
                    if item:
                        item.setText(entry.get("status", ""))
        self._save_state()
        if isinstance(result, dict) and result.get("error"):
            self._set_stage("Generation error -- see "
                            "the log.")
            self._reset_progress()
            if self._smoke_cfg is None:
                QMessageBox.critical(self, "Generation error",
                                     result["error"])
            else:
                self.log("Generation error: %s"
                         % result["error"])
            return
        if not isinstance(result, dict):
            self._set_stage("Finished.")
            return
        self._last_summary = result
        lines = []
        if result.get("rif_pkg"):
            lines.append("RIF installer package: %s"
                         % result["rif_pkg"])
        if result.get("rif_error"):
            lines.append("RIF job FAILED: %s"
                         % result["rif_error"])
        for dest in result.get("pkgs_done", []):
            lines.append("Resigned package: %s" % dest)
        failed = result.get("failed", [])
        if failed:
            lines.append("FAILED: %d" % len(failed))
            for name, reason in failed:
                lines.append("  - %s: %s" % (name, reason))
        if result.get("cancelled"):
            lines.append("Cancelled before finishing.")
        text = "\n".join(lines) if lines else "Nothing ran."
        ok = bool(result.get("rif_pkg")
                  or result.get("pkgs_done")) \
            and not failed and not result.get("rif_error")
        self._set_stage("Finished: " + (
            "all jobs done." if ok else
            "finished with problems -- see the log."))
        self._reset_progress()
        if self._smoke_cfg is not None:
            self.log("Batch summary: "
                     + text.replace("\n", "; "))
            return
        if ok:
            QMessageBox.information(self, "Finished", text)
        else:
            QMessageBox.warning(self, "Finished with "
                                      "problems", text)

    def _cancel(self):
        if self._runner is not None:
            self.log("Cancelling -- the current engine step "
                     "is stopped and the rest of the queue "
                     "will be reported as cancelled. The "
                     "local scratch (with the act.dat / "
                     "idps.hex copies) is deleted either "
                     "way.")
            self._runner.cancel()
        self.cancel_btn.setEnabled(False)

    def closeEvent(self, event):
        self._save_settings()
        self._save_state()
        if self._runner is not None:
            self._runner.cancel()
        super().closeEvent(event)

    # ------------------------------------------------ smoke
    # Scripted end-to-end run, ONLY active when the
    # environment variable PS3RESIGN_GUI_SMOKE points at a
    # scenario JSON. It drives the same methods the buttons
    # drive (never the file dialogs), records the queues,
    # screenshots the window, and writes a state JSON at the
    # end. Normal runs never see any of this.
    def _smoke_maybe_start(self):
        cfg_path = os.environ.get("PS3RESIGN_GUI_SMOKE")
        if not cfg_path:
            return
        try:
            cfg = json.loads(Path(cfg_path).read_text())
        except Exception:  # noqa: BLE001
            return
        self._smoke_cfg = cfg
        if cfg.get("log_out"):
            self._smoke_log_sink = cfg["log_out"]
        self._smoke_state = {}
        self._smoke_phase = "setup"
        self._smoke_t0 = time.time()
        self._smoke_timer = QTimer(self)
        self._smoke_timer.timeout.connect(self._smoke_tick)
        self._smoke_timer.start(300)
        self.log("SMOKE: scripted run started.")

    def _smoke_shot(self, name):
        shots = (self._smoke_cfg or {}).get("shots_dir")
        if not shots:
            return
        try:
            Path(shots).mkdir(parents=True, exist_ok=True)
            self.grab().save(str(Path(shots) / (name + ".png")))
        except Exception:  # noqa: BLE001
            pass

    def _smoke_snapshot(self):
        def snap(entries):
            return [{"path": e["path"],
                     "status": e.get("status", "")}
                    for e in entries]
        return {"raps": snap(self.rap_entries),
                "pkgs": snap(self.pkg_entries)}

    def _smoke_finish(self):
        self._smoke_state["stage_final"] = \
            self.stage_label.text()
        self._smoke_state["queue_final"] = \
            self._smoke_snapshot()
        self._smoke_state["summary"] = self._last_summary
        outdir = (self._smoke_cfg or {}).get("output_dir")
        if outdir and Path(outdir).is_dir():
            self._smoke_state["outputs"] = [
                {"name": p.name, "size": p.stat().st_size}
                for p in sorted(Path(outdir).iterdir())
                if p.is_file()]
        out = (self._smoke_cfg or {}).get("state_out")
        if out:
            try:
                Path(out).write_text(json.dumps(
                    self._smoke_state, indent=2))
            except OSError:
                pass
        self.log("SMOKE: done.")
        QApplication.quit()

    def _smoke_tick(self):
        cfg = self._smoke_cfg
        if cfg is None:
            return
        if time.time() - self._smoke_t0 > cfg.get(
                "total_timeout_s", 1800):
            self._smoke_state["timeout"] = True
            self._smoke_state["phase_at_timeout"] = \
                self._smoke_phase
            self._smoke_finish()
            return
        if self._smoke_phase == "setup":
            if engine.engine_ready() and not self._workers:
                self._smoke_state["setup_seconds"] = round(
                    time.time() - self._smoke_t0, 1)
                self._smoke_state["queue_at_start"] = \
                    self._smoke_snapshot()
                self._smoke_shot("01-after-setup")
                self._smoke_phase = "apply"
            return
        if self._smoke_phase == "apply":
            if cfg.get("act_dat"):
                self.act_dat_edit.setText(cfg["act_dat"])
            if cfg.get("idps_hex"):
                self.idps_hex_edit.setText(cfg["idps_hex"])
            if cfg.get("output_dir"):
                self.output_edit.setText(cfg["output_dir"])
            if cfg.get("resign_pkgs"):
                self.resign_check.setChecked(True)
            self.add_paths("rap", cfg.get("raps", []))
            self.add_paths("pkg", cfg.get("pkgs", []))
            self._smoke_state["queue_after_adds"] = \
                self._smoke_snapshot()
            self._smoke_shot("02-after-adds")
            self._smoke_phase = "generate" \
                if cfg.get("generate", True) else "finish"
            return
        if self._smoke_phase == "generate":
            self._generate()
            self._smoke_phase = "wait_done"
            return
        if self._smoke_phase == "wait_done":
            if not self._generating and not self._workers:
                self._smoke_shot("03-after-generate")
                self._smoke_phase = "finish"
            return
        if self._smoke_phase == "finish":
            self._smoke_finish()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    code = app.exec()
    # Orderly teardown: close and destroy the window while
    # the application object is still alive. Leaving every
    # widget for the interpreter's exit sweep to destroy
    # crashes this PySide build (SIGBUS in the binding
    # teardown) once a session has restored state to destroy.
    win.close()
    win.deleteLater()
    app.processEvents()
    del win
    del app
    return code


if __name__ == "__main__":
    raise SystemExit(main())
