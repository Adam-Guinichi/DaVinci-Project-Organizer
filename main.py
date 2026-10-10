
import os
import sys
import json
import shutil
import hashlib
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QFileDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QTextEdit,
    QMessageBox, QAbstractItemView, QTabWidget, QFrame,
)

APP_DIR = Path(__file__).resolve().parent
HISTORY_FILE = APP_DIR / "history.jsonl"

VIDEO = {".mp4", ".mov", ".mxf", ".avi", ".mkv", ".webm",
         ".mpg", ".mpeg", ".m4v", ".wmv"}
AUDIO = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".aac",
         ".m4a", ".ogg", ".wma"}
IMAGES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp",
          ".gif", ".webp", ".heic", ".dpx", ".exr"}
PROJECTS = {".drp", ".dra", ".drt", ".drb"}
DOCUMENTS = {".pdf", ".txt", ".md", ".doc", ".docx", ".rtf",
              ".csv", ".xls", ".xlsx", ".ppt", ".pptx"}

MEDIA_EXTENSIONS = VIDEO | AUDIO | IMAGES

def category_for(path):
    ext = path.suffix.lower()
    if ext in VIDEO:
        return "Video"
    if ext in AUDIO:
        return "Audio"
    if ext in IMAGES:
        return "Images"
    if ext in PROJECTS:
        return "Projects"
    if ext in DOCUMENTS:
        return "Documents"
    return "Other"

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def history(action, **details):
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        **details,
    }
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

def make_plan(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()

    if not source.is_dir():
        raise ValueError("The source folder does not exist.")
    if source == destination:
        raise ValueError("Source and destination must be different.")
    if source in destination.parents:
        raise ValueError("Choose a destination outside the source folder.")

    plan = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue

        # Never scan files that are already inside the destination.
        try:
            path.resolve().relative_to(destination)
            continue
        except ValueError:
            pass

        relative = path.relative_to(source)
        category = category_for(path)
        plan.append({
            "source": path,
            "relative": relative,
            "category": category,
            "size": path.stat().st_size,
            "destination": destination / category / relative,
        })

    return sorted(plan, key=lambda item: str(item["relative"]).lower())

# ------------------------------------------------------------
# DaVinci Resolve scripting connection
# ------------------------------------------------------------

def connect_resolve():
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    scripting = (
        program_data
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "Support"
        / "Developer"
        / "Scripting"
    )
    modules = scripting / "Modules"

    if modules.is_dir() and str(modules) not in sys.path:
        sys.path.insert(0, str(modules))

    program_files = Path(
        os.environ.get("ProgramFiles", r"C:\Program Files")
    )
    fusion_library = (
        program_files
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "fusionscript.dll"
    )

    if fusion_library.is_file():
        os.environ.setdefault(
            "RESOLVE_SCRIPT_LIB", str(fusion_library)
        )

    os.environ.setdefault("RESOLVE_SCRIPT_API", str(scripting))

    try:
        import DaVinciResolveScript as dvr
    except Exception as exc:
        raise RuntimeError(
            "Could not load the Resolve scripting module.\n\n"
            "Check that DaVinci Resolve is installed and that its "
            "Developer/Scripting/Modules folder exists.\n\n"
            f"Details: {exc}"
        ) from exc

    try:
        resolve = dvr.scriptapp("Resolve")
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to DaVinci Resolve: {exc}"
        ) from exc

    if resolve is None:
        raise RuntimeError(
            "Resolve returned no connection. Open DaVinci Resolve, "
            "load a project, and check scripting permissions."
        )

    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject()

    if project is None:
        raise RuntimeError(
            "Resolve is connected, but no project is currently open."
        )

    return resolve, manager, project

def read_clip_path(clip):
    try:
        properties = clip.GetClipProperty() or {}
    except Exception:
        properties = {}

    for key in (
        "File Path", "File path", "Full Path",
        "FileName", "File Name", "Clip Path",
    ):
        value = properties.get(key)
        if value:
            return str(value).strip()

    return ""

def inspect_resolve():
    resolve, manager, project = connect_resolve()
    media_pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    items = []
    seen_folders = set()

    def walk(folder, parent_name=""):
        name = folder.GetName() or "Unnamed folder"
        folder_name = "/".join(
            part for part in (parent_name, name) if part
        )

        for clip in folder.GetClipList() or []:
            path = read_clip_path(clip)
            exists = False

            if path:
                try:
                    exists = Path(path).is_file()
                except (OSError, ValueError):
                    pass

            if not path:
                status = "UNKNOWN"
                display_path = "(Path unavailable)"
            else:
                status = "OK" if exists else "MISSING"
                display_path = path

            items.append({
                "name": clip.GetName() or "Unnamed clip",
                "folder": folder_name,
                "path": display_path,
                "status": status,
                "_clip": clip,
            })

        for subfolder in folder.GetSubFolderList() or []:
            try:
                identifier = subfolder.GetUniqueId()
            except Exception:
                identifier = id(subfolder)

            if identifier not in seen_folders:
                seen_folders.add(identifier)
                walk(subfolder, folder_name)

    walk(media_pool.GetRootFolder())

    # This is an inferred media location, NOT the Resolve project
    # database/storage location.
    existing_parent_folders = []
    for item in items:
        if item["status"] == "OK":
            try:
                existing_parent_folders.append(
                    str(Path(item["path"]).resolve().parent)
                )
            except (OSError, ValueError):
                pass

    media_folder = None
    if existing_parent_folders:
        try:
            media_folder = os.path.commonpath(existing_parent_folders)
        except ValueError:
            pass

    return {
        "resolve": resolve,
        "manager": manager,
        "project_object": project,
        "project": project.GetName(),
        "timeline": (
            timeline.GetName() if timeline else "(No active timeline)"
        ),
        "items": items,
        "total": len(items),
        "missing": sum(i["status"] == "MISSING" for i in items),
        "unknown": sum(i["status"] == "UNKNOWN" for i in items),
        "media_folder": media_folder,
    }

# ------------------------------------------------------------
# Background file copying
# ------------------------------------------------------------

class CopyWorker(QThread):
    progress = Signal(int, int)
    message = Signal(str)
    completed = Signal(dict)

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def run(self):
        results = {
            "copied": 0,
            "identical": 0,
            "conflicts": 0,
            "errors": 0,
        }

        total = len(self.plan)

        for index, item in enumerate(self.plan, 1):
            src = item["source"]
            dst = item["destination"]

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)

                if dst.exists():
                    identical = (
                        dst.is_file()
                        and src.stat().st_size == dst.stat().st_size
                        and sha256(src) == sha256(dst)
                    )

                    if identical:
                        results["identical"] += 1
                        self.message.emit(f"Already identical: {dst}")
                        history(
                            "skip_identical",
                            source=str(src),
                            destination=str(dst),
                        )
                    else:
                        results["conflicts"] += 1
                        self.message.emit(
                            f"Conflict; existing file untouched: {dst}"
                        )
                        history(
                            "conflict",
                            source=str(src),
                            destination=str(dst),
                        )
                else:
                    shutil.copy2(src, dst)

                    if (
                        src.stat().st_size != dst.stat().st_size
                        or sha256(src) != sha256(dst)
                    ):
                        dst.unlink(missing_ok=True)
                        raise IOError("SHA-256 copy verification failed.")

                    results["copied"] += 1
                    self.message.emit(f"Copied and verified: {dst}")
                    history(
                        "copy",
                        source=str(src),
                        destination=str(dst),
                    )

            except Exception as exc:
                results["errors"] += 1
                self.message.emit(f"ERROR: {src}: {exc}")
                history(
                    "error",
                    source=str(src),
                    destination=str(dst),
                    error=str(exc),
                )

            self.progress.emit(index, total)

        self.completed.emit(results)

# ------------------------------------------------------------
# Main window
# ------------------------------------------------------------

class OrganizerWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DaVinci Project Organizer")
        self.resize(1350, 850)
        self.setMinimumSize(950, 620)

        self.source = APP_DIR / "test_media"
        self.destination = APP_DIR / "organized_media"
        self.plan = []
        self.worker = None
        self.report = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 14, 16, 14)

        title = QLabel("DaVinci Project Organizer")
        title.setStyleSheet("font-size:24px;font-weight:700;")
        outer.addWidget(title)

        subtitle = QLabel(
            "Organize media, inspect Resolve, relink clips, and back up projects."
        )
        subtitle.setStyleSheet("color:#aab4c6;")
        outer.addWidget(subtitle)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.build_organizer_tab()
        self.build_resolve_tab()

        outer.addWidget(QLabel("ACTIVITY LOG"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(115)
        outer.addWidget(self.log)

        self.add_log("Ready.")
        self.scan_files()

    def add_log(self, message):
        if hasattr(self, "log"):
            self.log.append(
                f"[{datetime.now():%H:%M:%S}] {message}"
            )

    def configure_table(self, table):
        table.setAlternatingRowColors(True)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.verticalHeader().setVisible(False)

    def build_organizer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        paths = QHBoxLayout()

        source_layout = QVBoxLayout()
        source_layout.addWidget(QLabel("SOURCE FOLDER"))
        self.source_label = QLabel(str(self.source))
        self.source_label.setWordWrap(True)
        source_layout.addWidget(self.source_label)
        choose_source = QPushButton("Choose Source")
        choose_source.clicked.connect(self.choose_source)
        source_layout.addWidget(choose_source)

        dest_layout = QVBoxLayout()
        dest_layout.addWidget(QLabel("DESTINATION FOLDER"))
        self.dest_label = QLabel(str(self.destination))
        self.dest_label.setWordWrap(True)
        dest_layout.addWidget(self.dest_label)
        choose_dest = QPushButton("Choose Destination")
        choose_dest.clicked.connect(self.choose_destination)
        dest_layout.addWidget(choose_dest)

        paths.addLayout(source_layout, 1)
        paths.addLayout(dest_layout, 1)
        layout.addLayout(paths)

        actions = QHBoxLayout()
        scan_button = QPushButton("Scan Files")
        scan_button.clicked.connect(self.scan_files)
        actions.addWidget(scan_button)

        self.copy_button = QPushButton("Copy and Verify")
        self.copy_button.clicked.connect(self.start_copy)
        self.copy_button.setEnabled(False)
        actions.addWidget(self.copy_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.count_label = QLabel("No files scanned.")
        layout.addWidget(self.count_label)

        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(
            ["Category", "Relative file", "Size", "Destination"]
        )
        self.configure_table(self.file_table)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.file_table, 1)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.tabs.addTab(tab, "Organizer")

    def build_resolve_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.resolve_status = QLabel("Not connected to Resolve.")
        self.resolve_status.setWordWrap(True)
        layout.addWidget(self.resolve_status)

        info = QHBoxLayout()
        info.addWidget(QLabel("Project:"))
        self.project_label = QLabel("—")
        self.project_label.setWordWrap(True)
        info.addWidget(self.project_label, 1)

        info.addWidget(QLabel("Timeline:"))
        self.timeline_label = QLabel("—")
        info.addWidget(self.timeline_label, 1)
        layout.addLayout(info)

        layout.addWidget(QLabel(
            "Inferred media folder (not the project-storage folder):"
        ))
        self.media_folder_label = QLabel("Not detected.")
        self.media_folder_label.setWordWrap(True)
        layout.addWidget(self.media_folder_label)

        use_folder = QPushButton("Use Detected Media Folder as Source")
        use_folder.clicked.connect(self.use_media_folder)
        layout.addWidget(use_folder)
        self.use_folder_button = use_folder
        self.use_folder_button.setEnabled(False)

        warning = QLabel(
            "Resolve projects may be stored in database libraries. "
            "The actual project-storage folder cannot always be discovered "
            "through the scripting API. Export a .drp backup instead."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#aab4c6;")
        layout.addWidget(warning)

        buttons = QHBoxLayout()

        refresh = QPushButton("Detect / Refresh Project")
        refresh.clicked.connect(self.detect_project)
        buttons.addWidget(refresh)

        self.import_button = QPushButton("Import Organized Media")
        self.import_button.clicked.connect(self.import_media)
        self.import_button.setEnabled(False)
        buttons.addWidget(self.import_button)

        self.relink_button = QPushButton("Relink Missing Clips")
        self.relink_button.clicked.connect(self.relink_media)
        self.relink_button.setEnabled(False)
        buttons.addWidget(self.relink_button)

        self.save_button = QPushButton("Save Project")
        self.save_button.clicked.connect(self.save_project)
        self.save_button.setEnabled(False)
        buttons.addWidget(self.save_button)

        self.backup_button = QPushButton("Export .DRP Backup")
        self.backup_button.clicked.connect(self.export_backup)
        self.backup_button.setEnabled(False)
        buttons.addWidget(self.backup_button)

        layout.addLayout(buttons)

        self.resolve_table = QTableWidget(0, 4)
        self.resolve_table.setHorizontalHeaderLabels(
            ["Clip", "Media Pool folder", "File path", "Status"]
        )
        self.configure_table(self.resolve_table)
        header = self.resolve_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.resolve_table, 1)

        self.tabs.addTab(tab, "DaVinci Resolve")

    # --------------------------------------------------------
    # Organizer actions
    # --------------------------------------------------------

    def choose_source(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Source Folder", str(self.source)
        )
        if folder:
            self.source = Path(folder)
            self.source_label.setText(folder)
            self.scan_files()

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Destination Folder", str(self.destination)
        )
        if folder:
            self.destination = Path(folder)
            self.dest_label.setText(folder)
            self.scan_files()

    def scan_files(self):
        try:
            self.plan = make_plan(self.source, self.destination)
        except Exception as exc:
            self.plan = []
            self.file_table.setRowCount(0)
            self.copy_button.setEnabled(False)
            self.count_label.setText(f"Scan failed: {exc}")
            self.add_log(f"Scan failed: {exc}")
            return

        self.file_table.setUpdatesEnabled(False)
        self.file_table.setRowCount(len(self.plan))

        for row, item in enumerate(self.plan):
            values = [
                item["category"],
                str(item["relative"]),
                f'{item["size"] / (1024 * 1024):.2f} MB',
                str(item["destination"]),
            ]
            for column, value in enumerate(values):
                self.file_table.setItem(
                    row, column, QTableWidgetItem(value)
                )

        self.file_table.setUpdatesEnabled(True)
        self.copy_button.setEnabled(bool(self.plan))
        self.progress.setValue(0)
        self.count_label.setText(
            f"{len(self.plan)} files found. "
            "Existing files will never be overwritten."
        )
        self.add_log(f"Scan complete: {len(self.plan)} files.")

    def start_copy(self):
        if not self.plan:
            QMessageBox.information(
                self, "No files", "Scan a source folder first."
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm Copy",
            "Copy and verify all planned files?\n\n"
            "Existing files will not be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.copy_button.setEnabled(False)
        self.worker = CopyWorker(self.plan)
        self.worker.progress.connect(self.update_progress)
        self.worker.message.connect(self.add_log)
        self.worker.completed.connect(self.copy_finished)
        self.worker.start()

    def update_progress(self, current, total):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(current)

    def copy_finished(self, result):
        self.copy_button.setEnabled(bool(self.plan))
        message = (
            f"Copied and verified: {result['copied']}\n"
            f"Already identical: {result['identical']}\n"
            f"Conflicts skipped: {result['conflicts']}\n"
            f"Errors: {result['errors']}"
        )
        self.add_log(message.replace("\n", " | "))
        QMessageBox.information(self, "Copy Complete", message)
        self.scan_files()

    # --------------------------------------------------------
    # Resolve actions
    # --------------------------------------------------------

    def detect_project(self):
        try:
            self.report = inspect_resolve()
        except Exception as exc:
            self.report = None
            self.resolve_status.setText("Connection failed.")
            self.add_log(f"Resolve connection failed: {exc}")
            QMessageBox.warning(self, "Resolve Connection", str(exc))
            return

        report = self.report
        self.project_label.setText(report["project"])
        self.timeline_label.setText(report["timeline"])
        self.resolve_status.setText(
            f"Connected. Media Pool items: {report['total']} | "
            f"Missing: {report['missing']} | "
            f"Unknown paths: {report['unknown']}"
        )
        self.media_folder_label.setText(
            report["media_folder"] or "No common folder inferred."
        )
        self.use_folder_button.setEnabled(
            bool(report["media_folder"])
            and Path(report["media_folder"]).is_dir()
        )

        for button in (
            self.import_button,
            self.relink_button,
            self.save_button,
            self.backup_button,
        ):
            button.setEnabled(True)

        self.resolve_table.setRowCount(len(report["items"]))
        for row, item in enumerate(report["items"]):
            values = [
                item["name"], item["folder"], item["path"], item["status"]
            ]
            for column, value in enumerate(values):
                self.resolve_table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

        self.add_log(
            f"Connected to project: {report['project']} "
            f"({report['total']} Media Pool items)."
        )

    def ensure_report(self):
        if self.report is None:
            self.detect_project()
        return self.report

    def use_media_folder(self):
        if not self.report:
            return
        folder = self.report.get("media_folder")
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(
                self, "Folder unavailable",
                "The inferred media folder is not available."
            )
            return

        self.source = Path(folder)
        self.source_label.setText(folder)
        self.tabs.setCurrentIndex(0)
        self.scan_files()

    def import_media(self):
        report = self.ensure_report()
        if not report:
            return

        root = self.destination
        if not root.is_dir():
            QMessageBox.warning(
                self, "Destination Missing",
                f"Organizer destination does not exist:\n{root}"
            )
            return

        files = sorted(
            path for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
        )
        if not files:
            QMessageBox.information(
                self, "No Media",
                f"No supported media files found in:\n{root}"
            )
            return

        # Exclude paths already present in the Media Pool when Resolve
        # exposes the original path. Unknown paths cannot be deduplicated.
        existing_paths = set()
        for item in report["items"]:
            path = item["path"]
            if path and not path.startswith("("):
                try:
                    existing_paths.add(
                        os.path.normcase(str(Path(path).resolve()))
                    )
                except (OSError, ValueError):
                    pass

        new_files = []
        for path in files:
            try:
                normalized = os.path.normcase(str(path.resolve()))
            except (OSError, ValueError):
                normalized = os.path.normcase(str(path))
            if normalized not in existing_paths:
                new_files.append(str(path))

        if not new_files:
            QMessageBox.information(
                self, "Nothing to Import",
                "All supported destination files already appear to be "
                "referenced by their current paths, or no new files were found."
            )
            return

        answer = QMessageBox.question(
            self, "Confirm Import",
            f"Import {len(new_files)} files into the open Resolve project's "
            f"Media Pool?\n\nSource:\n{root}\n\n"
            "This modifies the open project. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            media_pool = report["project_object"].GetMediaPool()
            imported = media_pool.ImportMedia(new_files)
            count = len(imported or [])
            self.add_log(
                f"Import requested: {len(new_files)} files; "
                f"Resolve returned {count} items."
            )
            QMessageBox.information(
                self, "Import Result",
                f"Files submitted: {len(new_files)}\n"
                f"Items returned: {count}\n\n"
                "Refresh the report to inspect the Media Pool."
            )
            self.detect_project()
        except Exception as exc:
            self.add_log(f"Media import failed: {exc}")
            QMessageBox.warning(self, "Import Failed", str(exc))

    def relink_media(self):
        report = self.ensure_report()
        if not report:
            return

        root = self.destination
        if not root.is_dir():
            QMessageBox.warning(
                self, "Destination Missing",
                f"Organizer destination does not exist:\n{root}"
            )
            return

        # Build a case-insensitive index of destination filenames.
        candidates = {}
        for path in root.rglob("*"):
            if path.is_file():
                candidates.setdefault(path.name.casefold(), []).append(path)

        matches = []
        ambiguous = 0

        for item in report["items"]:
            if item["status"] != "MISSING":
                continue

            old_path = item["path"]
            if not old_path or old_path.startswith("("):
                continue

            filename = Path(old_path).name.casefold()
            found = candidates.get(filename, [])

            if len(found) == 1:
                matches.append((item, found[0]))
            elif len(found) > 1:
                ambiguous += 1

        if not matches:
            QMessageBox.information(
                self, "Nothing to Relink",
                "No missing clips had a unique filename match in the "
                f"destination folder.\n\nAmbiguous matches skipped: {ambiguous}"
            )
            return

        preview = "\n".join(
            f"{item['name']} → {target}"
            for item, target in matches[:10]
        )
        if len(matches) > 10:
            preview += f"\n... and {len(matches) - 10} more"

        answer = QMessageBox.question(
            self, "Confirm Relink",
            f"Relink {len(matches)} missing clips?\n\n{preview}\n\n"
            f"Ambiguous matches skipped: {ambiguous}\n\n"
            "Resolve's relink operation uses the destination folder and "
            "matching media filenames. Review the matches carefully before "
            "continuing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        media_pool = report["project_object"].GetMediaPool()
        succeeded = 0
        failed = 0

        for item, target in matches:
            try:
                # The API expects MediaPoolItem objects and a folder path.
                result = media_pool.RelinkClips(
                    [item["_clip"]], str(target.parent)
                )
                if result is False:
                    failed += 1
                    self.add_log(f"Resolve did not confirm relink: {item['name']}")
                else:
                    succeeded += 1
                    self.add_log(
                        f"Relink requested: {item['name']} → {target.parent}"
                    )
            except Exception as exc:
                failed += 1
                self.add_log(f"Relink error for {item['name']}: {exc}")

        QMessageBox.information(
            self, "Relink Finished",
            f"Relink calls completed without reported errors: {succeeded}\n"
            f"Failed calls: {failed}\n"
            f"Ambiguous matches skipped: {ambiguous}\n\n"
            "Refresh and verify the clip status in Resolve. Save only after "
            "confirming the media is linked correctly."
        )
        self.detect_project()

    def save_project(self):
        report = self.ensure_report()
        if not report:
            return

        answer = QMessageBox.question(
            self, "Confirm Save",
            f"Save the open Resolve project '{report['project']}'?\n\n"
            "This saves to Resolve's current project library.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            result = report["manager"].SaveProject()
            if result is False:
                raise RuntimeError("Resolve returned a failure result.")
            self.add_log(f"Save command completed for {report['project']}.")
            QMessageBox.information(
                self, "Save Project",
                "The SaveProject command completed. Check Resolve to "
                "confirm the project is saved."
            )
        except Exception as exc:
            self.add_log(f"Project save failed: {exc}")
            QMessageBox.warning(
                self, "Save Failed",
                f"Could not save through the scripting API:\n\n{exc}\n\n"
                "Try saving manually in Resolve with Ctrl+S."
            )

    def export_backup(self):
        report = self.ensure_report()
        if not report:
            return

        default_name = "".join(
            c if c not in '<>:"/\\|?*' else "_"
            for c in report["project"]
        )
        default_path = str(Path.home() / f"{default_name}.drp")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Resolve Project Backup",
            default_path,
            "DaVinci Resolve Project (*.drp)",
        )
        if not path:
            return
        if not path.lower().endswith(".drp"):
            path += ".drp"

        answer = QMessageBox.question(
            self, "Confirm Backup Export",
            f"Export '{report['project']}' to:\n\n{path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            result = report["manager"].ExportProject(
                report["project"], path
            )
            if result is False:
                raise RuntimeError("Resolve returned a failure result.")

            # Check whether the file is present before reporting success.
            if not Path(path).is_file():
                raise RuntimeError(
                    "Resolve returned without an error, but the .drp "
                    "file was not found at the selected path."
                )

            history(
                "resolve_backup",
                project=report["project"],
                destination=path,
            )
            self.add_log(f"Project backup created: {path}")
            QMessageBox.information(
                self, "Backup Exported",
                f"Backup file found:\n{path}"
            )
        except Exception as exc:
            self.add_log(f"Backup export failed: {exc}")
            QMessageBox.warning(self, "Export Failed", str(exc))

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    app.setStyleSheet("""
        QWidget {
            background-color: #171a21;
            color: #e8eaf0;
            font-family: Segoe UI;
            font-size: 10pt;
        }
        QTabWidget::pane {
            border: 1px solid #343a48;
        }
        QTabBar::tab {
            background: #252a35;
            padding: 10px 18px;
            margin-right: 3px;
        }
        QTabBar::tab:selected {
            background: #3a4560;
        }
        QPushButton {
            background: #303747;
            border: 1px solid #485166;
            border-radius: 5px;
            padding: 8px 12px;
        }
        QPushButton:hover {
            background: #414d66;
        }
        QPushButton:disabled {
            color: #777d89;
            background: #20232b;
        }
        QTableWidget, QTextEdit {
            background: #1d212a;
            alternate-background-color: #242a35;
            gridline-color: #363d4b;
            selection-background-color: #3c4d78;
        }
        QHeaderView::section {
            background: #292f3c;
            padding: 7px;
            border: none;
        }
        QProgressBar {
            border: 1px solid #40495a;
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            background: #637af5;
        }
    """)

    window = OrganizerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()