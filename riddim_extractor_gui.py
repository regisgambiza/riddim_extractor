#!/usr/bin/env python3
"""
Riddim Extractor GUI - Manual processing tool for riddim albums.

Features:
- Manual folder selection and processing
- Real-time execution trace with step-by-step details
- Progress monitoring for ongoing operations
- Success / Failed lists with detailed error reporting
- Year-based organization using audio metadata
- Settings for source/destination paths
- Dark/light modern IDM-inspired theme
- System tray support
- Retry failed items
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QObject,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
    QThread,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPalette,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------- #
# Mapping-Based Uploader import
# --------------------------------------------------------------------------- #
try:
    from riddim_uploader import run_uploader as run_mapping_uploader
    MAPPING_UPLOADER_AVAILABLE = True
except ImportError:
    MAPPING_UPLOADER_AVAILABLE = False

# --------------------------------------------------------------------------- #
# Dependency checking and auto-install
# --------------------------------------------------------------------------- #
def check_and_install_dependencies():
    """Check all critical dependencies and install missing ones.
    
    Validates PySide6, mutagen, and other required packages.
    Attempts to pip-install missing packages. If installation fails,
    shows critical error message and exits the application.
    """
    import sys
    import subprocess
    from pathlib import Path
    
    required_packages = ["PySide6", "mutagen"]
    installed = []
    missing = []
    
    # Check each required package
    for package in required_packages:
        try:
            __import__(package)
            installed.append(package)
        except ImportError:
            missing.append(package)
    
    # Install missing packages
    if missing:
        from PySide6.QtWidgets import QMessageBox, QApplication
        from PySide6.QtCore import Qt
        
        # Create a temporary QApplication if one doesn't exist
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        
        # Show installation dialog
        msg_box = QMessageBox(QMessageBox.Icon.Critical, "Dependency Installation", 
                             f"Installing missing dependencies: {', '.join(missing)}", 
                             QMessageBox.StandardButton.Ok, None)
        msg_box.setWindowModality(Qt.WindowModality.ApplicationModal)
        msg_box.show()
        
        for package in missing:
            try:
                msg_box.setText(f"Installing {package}...")
                app.processEvents()
                
                # Attempt installation
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", package],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    msg_box.setText(
                        f"Failed to install {package}. Error:\n{result.stderr}\n\n"
                        f"Please install manually with: pip install {package}"
                    )
                    msg_box.exec()
                    sys.exit(1)
                else:
                    msg_box.setText(f"Successfully installed {package}")
                    app.processEvents()
            except Exception as e:
                msg_box.setText(f"Error installing {package}: {str(e)}")
                msg_box.exec()
                sys.exit(1)
        
        msg_box.setText(f"All dependencies installed successfully. Restart the application.")
        msg_box.exec()
        sys.exit(0)

# --------------------------------------------------------------------------- #
# Optional validation import (graceful fallback)
# --------------------------------------------------------------------------- #
try:
    from validation import AUDIO_EXTS
    AUDIO_EXTENSIONS = AUDIO_EXTS if isinstance(AUDIO_EXTS, set) else set(AUDIO_EXTS)
except Exception:
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".aiff", ".aif"}

# --------------------------------------------------------------------------- #
# Audio metadata support (mutagen) - checked at startup
# --------------------------------------------------------------------------- #
try:
    from mutagen import File as MutagenFile
    AUDIO_METADATA_AVAILABLE = True
except Exception:
    MutagenFile = None
    AUDIO_METADATA_AVAILABLE = False

# --------------------------------------------------------------------------- #
# Core extractor logic
# --------------------------------------------------------------------------- #

@dataclass
class ExtractResult:
    success: bool
    audio_count: int = 0
    error: str = ""
    folder_name: str = ""
    execution_trace: str = ""


class ExtractorCore:
    """Pure logic class – manual processing only (no monitoring)."""

    def __init__(
        self,
        source_dir: Path,
        dest_dir: Path,
        state_file: Path,
        copy_only: bool = True,
    ):
        self.source_dir = Path(source_dir)
        self.dest_dir = Path(dest_dir)
        self.state_file = Path(state_file)

        self.done: set[str] = set()
        self.failed: set[str] = set()
        self.failed_reasons: dict[str, str] = {}
        self.copy_only = copy_only
        self.imported_years: dict[str, int] = {}

        self._load_state()

    # ---- state -----------------------------------------------------------
    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.done = set(data.get("done", []))
                self.failed = set(data.get("failed", []))
                self.failed_reasons = dict(data.get("failed_reasons", {}))
            except Exception:
                pass

    def save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "done": sorted(self.done),
            "failed": sorted(self.failed),
            "failed_reasons": self.failed_reasons,
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            dir=self.state_file.parent,
            encoding="utf-8",
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.state_file)

    # ---- year mapping import ---------------------------------------------
    def load_year_mapping(self, filepath: Path) -> dict:
        """Load year mappings from a JSON file exported by riddim_agent.

        Returns a dict with:
        - "loaded": number of mappings loaded
        - "skipped": number of folders already in done/failed state
        - "warnings": list of warning messages for skipped folders
        """
        import json

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        mappings = data.get("mappings", {})
        if not isinstance(mappings, dict):
            raise ValueError("Invalid format: 'mappings' must be a dict")

        loaded = 0
        skipped = 0
        warnings = []

        for folder_name, year in mappings.items():
            resolved_path = str((self.source_dir / folder_name).resolve())

            if resolved_path in self.done:
                warnings.append(f"Skipped '{folder_name}': already processed (in done)")
                skipped += 1
                continue
            if resolved_path in self.failed:
                warnings.append(f"Skipped '{folder_name}': previously failed (in failed)")
                skipped += 1
                continue

            self.imported_years[folder_name] = int(year)
            loaded += 1

        return {"loaded": loaded, "skipped": skipped, "warnings": warnings}

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def has_audio_files(folder: Path) -> bool:
        if not folder.is_dir():
            return False
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                return True
        return False

    def get_folder_year(self, folder: Path) -> str:
        """Return year, checking imported mappings first then audio metadata."""
        folder_name = folder.name
        if folder_name in self.imported_years:
            return str(self.imported_years[folder_name])
        return self._detect_year_from_metadata(folder)

    def _detect_year_from_metadata(self, folder: Path) -> str:
        """Read year metadata from audio files; returns most common year or 'Unknown'."""
        if not folder.is_dir():
            return "Unknown"

        if MutagenFile is None:
            return "Unknown"

        year_counts: dict[str, int] = {}

        for audio_path in folder.rglob("*"):
            if audio_path.is_file() and audio_path.suffix.lower() in AUDIO_EXTENSIONS:
                try:
                    audio_file = MutagenFile(str(audio_path), easy=True)
                    if audio_file is None:
                        continue

                    year = None
                    for key in ("TDRC", "TORY", "date", "\xa9day"):
                        if key in audio_file:
                            val = audio_file[key]
                            year = val[0] if isinstance(val, list) and val else None
                            if year:
                                break

                    if not year:
                        try:
                            raw = MutagenFile(str(audio_path))
                            if raw and raw.tags:
                                for k in raw.tags.keys():
                                    if k.startswith("TXXX") and "COPYRIGHT" in str(raw.tags[k]).upper():
                                        import re
                                        m = re.search(r"\b(19|20)\d{2}\b", str(raw.tags[k]))
                                        if m:
                                            year = m.group()
                                            break
                        except Exception:
                            pass

                    if year:
                        year = str(year).strip()[:4]
                        if year.isdigit() and year not in ("",):
                            year_counts[year] = year_counts.get(year, 0) + 1

                except Exception:
                    continue

        if not year_counts:
            import re
            m = re.search(r"\b(19|20)\d{2}\b", folder.name)
            if m:
                return m.group()

        if not year_counts:
            return "Unknown"

        best_year = min(year_counts, key=lambda y: (-year_counts[y], y))
        return best_year

    def place_by_year(self, folder_name: str) -> str:
        """Move/copy folder into year-based subfolder and return the year path component."""
        target = self.dest_dir / folder_name
        if not target.exists():
            return folder_name

        year = self.get_folder_year(target)
        year_dir = self.dest_dir / year
        year_dir.mkdir(parents=True, exist_ok=True)

        new_target = year_dir / folder_name
        if self.copy_only:
            shutil.copytree(str(target), str(new_target), dirs_exist_ok=True)
            shutil.rmtree(str(target))
        else:
            shutil.move(str(target), str(new_target))

        return f"{year}/{folder_name}"

    def already_exists_in_dest(self, name: str) -> bool:
        return (self.dest_dir / name).exists()

    # ---- extraction ------------------------------------------------------
    def extract_zip(self, zip_path: Path) -> ExtractResult:
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        trace = f"  → Extracting ZIP: {zip_path.name}"

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    zf.extractall(tmp_path)
                    trace += "\n  → ZIP contents extracted"

                    top_level = [p for p in tmp_path.iterdir() if p.name != "__MACOSX"]
                    if not top_level:
                        return ExtractResult(True, 0, "Empty zip", zip_path.stem, trace)

                    if len(top_level) == 1 and top_level[0].is_dir():
                        folder_name = top_level[0].name
                        source_folder = top_level[0]
                        trace += f"\n  → Found single folder: {folder_name}"
                    else:
                        folder_name = zip_path.stem
                        wrapper = tmp_path / folder_name
                        wrapper.mkdir(exist_ok=True)
                        for entry in top_level:
                            if self.copy_only:
                                shutil.copy2(str(entry), str(wrapper / entry.name))
                            else:
                                shutil.move(str(entry), str(wrapper / entry.name))
                        source_folder = wrapper
                        trace += f"\n  → Wrapped contents into: {folder_name}"

                    if not self.has_audio_files(source_folder):
                        return ExtractResult(True, 0, "No audio files", folder_name, trace)

                    if self.already_exists_in_dest(folder_name):
                        return ExtractResult(True, 0, "Already in destination", folder_name, trace)

                    year = self.get_folder_year(source_folder)
                    year_dir = self.dest_dir / year
                    year_dir.mkdir(parents=True, exist_ok=True)

                    target = year_dir / folder_name
                    if self.copy_only:
                        shutil.copytree(str(source_folder), str(target))
                        trace += f"\n  → Copied to: {target}"
                    else:
                        shutil.move(str(source_folder), str(target))
                        trace += f"\n  → Moved to: {target}"

                    year_path = f"{year}/{folder_name}"
                    trace += f"\n  → Organized to year path: {year_path}"

                    audio_count = sum(
                        1
                        for f in target.rglob("*")
                        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
                    )
                    trace += f"\n  → Found {audio_count} audio files"
                    return ExtractResult(True, audio_count, "", year_path, trace)

        except zipfile.BadZipFile:
            return ExtractResult(False, 0, "Corrupt zip", zip_path.stem, trace)
        except Exception as e:
            return ExtractResult(False, 0, str(e), zip_path.stem, trace)

    def process_folder(self, folder: Path) -> ExtractResult:
        trace = f"Starting folder processing: {folder.name}"

        zips = sorted(folder.rglob("*.zip"))

        if zips:
            total_audio = 0
            last_name = folder.name
            for zip_path in zips:
                res = self.extract_zip(zip_path)
                if not res.success:
                    return res
                total_audio += res.audio_count
                if res.folder_name:
                    last_name = res.folder_name
                if res.error:
                    trace += f"\n  → ZIP {zip_path.name} note: {res.error} - continuing"

            trace += f"\n  → Total audio files processed: {total_audio}"
            return ExtractResult(True, total_audio, "", last_name, trace)
        else:
            trace += f"\n  → No ZIP files found - copying folder as-is" if self.copy_only else "\n  → No ZIP files found - moving folder as-is"
            if not self.has_audio_files(folder):
                return ExtractResult(True, 0, "Empty folder", folder.name, trace)
            if self.already_exists_in_dest(folder.name):
                return ExtractResult(True, 0, "Already in destination", folder.name, trace)

            year = self.get_folder_year(folder)
            year_dir = self.dest_dir / year
            year_dir.mkdir(parents=True, exist_ok=True)

            target = year_dir / folder.name
            if self.copy_only:
                shutil.copytree(str(folder), str(target))
                trace += f"\n  → Copied folder to: {target}"
            else:
                shutil.move(str(folder), str(target))
                trace += f"\n  → Moved folder to: {target}"

            year_path = f"{year}/{folder.name}"
            trace += f"\n  → Organized to year path: {year_path}"

            audio_count = sum(
                1
                for f in target.rglob("*")
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
            )
            trace += f"\n  → Found {audio_count} audio files"
            return ExtractResult(True, audio_count, "", year_path, trace)

    def force_process(self, folder: Path) -> ExtractResult:
        """Process immediately, ignoring previous state."""
        key = str(folder.resolve())
        try:
            res = self.process_folder(folder)
        except Exception as e:
            res = ExtractResult(False, 0, str(e), folder.name, f"Error during processing: {e}")

        if res.success:
            self.done.add(key)
            self.failed.discard(key)
            self.failed_reasons.pop(key, None)
        else:
            self.failed.add(key)
            self.failed_reasons[key] = res.error
            self.done.discard(key)

        self.save_state()
        return res

    def retry_failed(self, key: str) -> Optional[ExtractResult]:
        """Retry a previously failed folder if it still exists."""
        folder = Path(key)
        if not folder.exists():
            return None
        self.failed.discard(key)
        self.failed_reasons.pop(key, None)
        self.done.discard(key)
        return self.force_process(folder)

    def clear_history(self, which: str = "all") -> None:
        if which in ("all", "done"):
            self.done.clear()
        if which in ("all", "failed"):
            self.failed.clear()
            self.failed_reasons.clear()
        self.save_state()


# --------------------------------------------------------------------------- #
# Processing Worker Thread
# --------------------------------------------------------------------------- #
class ProcessingWorker(QObject):
    """Worker thread for processing folders without blocking the UI."""
    
    # Signals
    started = Signal()
    progress = Signal(int, str)  # current_index, folder_name
    finished = Signal(ExtractResult)
    error = Signal(str)
    completed = Signal()
    
    def __init__(self, core: ExtractorCore):
        super().__init__()
        self.core = core
        self._should_stop = False
        self._folder = None
        self._candidates = None
        self._retry_key = None
    
    @Slot()
    def execute_operation(self):
        """Execute the queued operation in the worker thread."""
        if self._folder is not None:
            self.process_folder(self._folder)
        elif self._candidates is not None:
            self.process_all(self._candidates)
        elif self._retry_key is not None:
            self.retry_failed(self._retry_key)
    
    def process_folder(self, folder: Path):
        """Process a single folder."""
        self.started.emit()
        try:
            res = self.core.force_process(folder)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.completed.emit()
    
    def process_all(self, candidates: list[Path]):
        """Process all folders in a list."""
        self.started.emit()
        try:
            total = len(candidates)
            total_audio = 0
             
            for i, folder in enumerate(candidates):
                if self._should_stop:
                    break
                     
                key = str(folder.resolve())
                self.progress.emit(i + 1, folder.name)
                 
                if key in self.core.done or key in self.core.failed:
                    continue
                     
                res = self.core.force_process(folder)
                 
                if res.success:
                    total_audio += res.audio_count
                 
                self.finished.emit(res)
             
            # Final completion signal with summary
            summary_result = ExtractResult(
                success=True, 
                audio_count=total_audio,
                error="",
                folder_name="Batch Complete",
                execution_trace=f"Processed {total} folders, {total_audio} audio files processed"
            )
            self.finished.emit(summary_result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.completed.emit()
    
    def retry_failed(self, key: str):
        """Retry a single failed folder."""
        self.started.emit()
        try:
            folder = Path(key)
            if not folder.exists():
                self.error.emit("Folder no longer exists")
                self.completed.emit()
                return
                 
            self.core.failed.discard(key)
            self.core.failed_reasons.pop(key, None)
            self.core.done.discard(key)
            
            res = self.core.force_process(folder)
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.completed.emit()
    
    def stop(self):
        """Request stopping of current operation."""
        self._should_stop = True


# --------------------------------------------------------------------------- #
# Main Window
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Riddim Extractor")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 820)

        self.settings = QSettings("RiddimTools", "RiddimExtractor")

        # Defaults
        self.source_dir = Path(self.settings.value("source_dir", "riddim_downloads"))
        self.dest_dir = Path(self.settings.value("dest_dir", r"E:\Music"))
        self.state_file = Path(self.settings.value("state_file", "extract_state.json"))
        self.copy_only = bool(self.settings.value("copy_only", True, type=bool))

        self.core = ExtractorCore(
            self.source_dir,
            self.dest_dir,
            self.state_file,
            copy_only=self.copy_only,
        )

        self.is_processing = False

        self._build_ui()
        self._apply_theme()
        self._load_tables()
        self._update_status_bar()
        self._update_mode_badge()

        # System tray
        self._setup_tray()

        # Worker thread for background processing
        self.thread = QThread()
        self.worker = ProcessingWorker(self.core)
        self.worker.moveToThread(self.thread)
        
        # Connect worker signals to MainWindow slots
        self.worker.started.connect(self._on_worker_started)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.completed.connect(self.thread.quit)
        
        # Restart thread event loop when it finishes
        self.thread.finished.connect(lambda: None)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---- Toolbar -----------------------------------------------------
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.btn_browse_source = QPushButton("📂 Browse Source")
        self.btn_browse_source.setMinimumWidth(130)
        self.btn_browse_source.clicked.connect(self._browse_source)
        toolbar.addWidget(self.btn_browse_source)

        self.btn_process = QPushButton("▶ Process Selected")
        self.btn_process.setObjectName("primaryBtn")
        self.btn_process.setMinimumWidth(130)
        self.btn_process.clicked.connect(self.process_selected)
        toolbar.addWidget(self.btn_process)

        self.btn_process_all = QPushButton("▶ Process All in Source")
        self.btn_process_all.setMinimumWidth(150)
        self.btn_process_all.clicked.connect(self.process_all_in_source)
        toolbar.addWidget(self.btn_process_all)

        toolbar.addSeparator()

        self.btn_retry = QPushButton("↺ Retry Failed")
        self.btn_retry.setToolTip("Retry all currently failed folders")
        self.btn_retry.clicked.connect(self.retry_all_failed)
        toolbar.addWidget(self.btn_retry)

        toolbar.addSeparator()

        self.btn_open_dest = QPushButton("🎵 Music")
        self.btn_open_dest.clicked.connect(lambda: self._open_folder(self.dest_dir))
        toolbar.addWidget(self.btn_open_dest)

        toolbar.addSeparator()

        self.btn_import_years = QPushButton("📥 Import Years")
        self.btn_import_years.setToolTip("Import year mappings from riddim_agent's year_mapping.json")
        self.btn_import_years.clicked.connect(self.import_year_mappings)
        toolbar.addWidget(self.btn_import_years)

        # Mapping-based upload button
        if MAPPING_UPLOADER_AVAILABLE:
            self.btn_upload_mappings = QPushButton("📤 Upload by Mappings")
            self.btn_upload_mappings.setToolTip("Upload folders using external year mappings")
            self.btn_upload_mappings.clicked.connect(self._launch_mapping_uploader)
            toolbar.addWidget(self.btn_upload_mappings)

        toolbar.addSeparator()

        self.btn_settings = QPushButton("⚙ Settings")
        self.btn_settings.clicked.connect(self.show_settings)
        toolbar.addWidget(self.btn_settings)

        # ---- Source path display -----------------------------------------
        src_frame = QFrame()
        src_frame.setObjectName("sourceFrame")
        src_layout = QHBoxLayout(src_frame)
        src_layout.setContentsMargins(8, 4, 8, 4)
        src_lbl = QLabel("Source folder:")
        src_lbl.setStyleSheet("font-weight: 600;")
        src_layout.addWidget(src_lbl)
        self.lbl_source_path = QLabel(str(self.source_dir))
        self.lbl_source_path.setObjectName("pathLabel")
        self.lbl_source_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        src_layout.addWidget(self.lbl_source_path)
        root.addWidget(src_frame)

        # ---- Status strip ------------------------------------------------
        status_frame = QFrame()
        status_frame.setObjectName("statusStrip")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 6, 12, 6)

        self.lbl_status = QLabel("● Ready")
        self.lbl_status.setObjectName("statusLabel")
        status_layout.addWidget(self.lbl_status)

        # Copy/Move mode badge
        self.lbl_mode_badge = QLabel("COPY")
        self.lbl_mode_badge.setStyleSheet(
            "background-color: #34a853; color: white; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;"
        )
        status_layout.addWidget(self.lbl_mode_badge)

        status_layout.addStretch()

        self.lbl_counts = QLabel("Done: 0  |  Failed: 0")
        status_layout.addWidget(self.lbl_counts)

        status_layout.addStretch()

        self.lbl_paths = QLabel(f"→  {self.dest_dir}")
        self.lbl_paths.setObjectName("pathLabel")
        status_layout.addWidget(self.lbl_paths)

        root.addWidget(status_frame)

# ---- Progress bar ------------------------------------------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.lbl_operation = QLabel("No operation in progress.")
        self.lbl_operation.setStyleSheet("color: #5f6368; font-size: 12px;")
        root.addWidget(self.lbl_operation)

        # ---- Main splitter -----------------------------------------------
        splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(splitter, stretch=1)

        # Top: tables
        tables_widget = QWidget()
        tables_layout = QHBoxLayout(tables_widget)
        tables_layout.setContentsMargins(0, 0, 0, 0)

        # Success table
        success_group = QGroupBox("✓ Processed Successfully")
        success_group.setObjectName("successGroup")
        sg_layout = QVBoxLayout(success_group)
        self.table_success = QTableWidget(0, 4)
        self.table_success.setHorizontalHeaderLabels(["Folder", "Path", "Audio Files", "Status"])
        self.table_success.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_success.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_success.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_success.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_success.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_success.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_success.setAlternatingRowColors(True)
        self.table_success.verticalHeader().setVisible(False)
        sg_layout.addWidget(self.table_success)

        btn_clear_done = QPushButton("Clear History")
        btn_clear_done.clicked.connect(lambda: self._clear_history("done"))
        sg_layout.addWidget(btn_clear_done, alignment=Qt.AlignmentFlag.AlignRight)

        # Failed table
        failed_group = QGroupBox("✗ Failed")
        failed_group.setObjectName("failedGroup")
        fg_layout = QVBoxLayout(failed_group)
        self.table_failed = QTableWidget(0, 4)
        self.table_failed.setHorizontalHeaderLabels(["Folder", "Path", "Reason", "Actions"])
        self.table_failed.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_failed.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_failed.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_failed.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_failed.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_failed.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_failed.setAlternatingRowColors(True)
        self.table_failed.verticalHeader().setVisible(False)
        fg_layout.addWidget(self.table_failed)

        btn_clear_failed = QPushButton("Clear History")
        btn_clear_failed.clicked.connect(lambda: self._clear_history("failed"))
        fg_layout.addWidget(btn_clear_failed, alignment=Qt.AlignmentFlag.AlignRight)

        tables_layout.addWidget(success_group, stretch=1)
        tables_layout.addWidget(failed_group, stretch=1)

        splitter.addWidget(tables_widget)

        # Bottom: detailed log
        bottom = QTabWidget()
        bottom.setObjectName("bottomTabs")

        # Detailed log tab
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        bottom.addTab(self.log_view, "📋 Execution Trace")

        # Stats tab
        stats_widget = QWidget()
        stats_layout = QFormLayout(stats_widget)
        self.lbl_stat_done = QLabel("0")
        self.lbl_stat_failed = QLabel("0")
        self.lbl_stat_audio = QLabel("0")
        self.lbl_stat_source = QLabel(str(self.source_dir))
        self.lbl_stat_dest = QLabel(str(self.dest_dir))
        stats_layout.addRow("Successfully processed:", self.lbl_stat_done)
        stats_layout.addRow("Failed:", self.lbl_stat_failed)
        stats_layout.addRow("Total audio files moved:", self.lbl_stat_audio)
        stats_layout.addRow("Source folder:", self.lbl_stat_source)
        stats_layout.addRow("Destination:", self.lbl_stat_dest)
        bottom.addTab(stats_widget, "📊 Stats")

        splitter.addWidget(bottom)
        splitter.setSizes([480, 280])

        # Status bar
        self.statusBar().showMessage("Ready - Click 'Process Selected' to begin")

    def _apply_theme(self):
        """IDM-inspired light theme with modern accents."""
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #f0f2f5;
                color: #1a1a1a;
                font-family: "Segoe UI", "Arial", sans-serif;
                font-size: 13px;
            }
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ffffff, stop:1 #e8eaed);
                border-bottom: 1px solid #c5c9d0;
                spacing: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 4px;
                padding: 6px 14px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #e8f0fe;
                border-color: #1a73e8;
            }
            QPushButton:pressed {
                background-color: #d2e3fc;
            }
            QPushButton:disabled {
                background-color: #f5f5f5;
                color: #9aa0a6;
            }
            QPushButton#primaryBtn {
                background-color: #1a73e8;
                color: white;
                border: none;
                font-weight: 600;
            }
            QPushButton#primaryBtn:hover {
                background-color: #1765cc;
            }
            QPushButton#primaryBtn:disabled {
                background-color: #a8c7fa;
            }
            QFrame#statusStrip {
                background-color: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 6px;
            }
            QLabel#statusLabel {
                font-weight: 600;
                font-size: 14px;
            }
            QLabel#pathLabel {
                color: #5f6368;
                font-size: 12px;
            }
            QFrame#sourceFrame {
                background-color: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 4px;
                margin: 2px 0;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QGroupBox#successGroup {
                border-left: 4px solid #34a853;
            }
            QGroupBox#failedGroup {
                border-left: 4px solid #ea4335;
            }
            QTableWidget {
                background-color: #ffffff;
                border: none;
                gridline-color: #e8eaed;
                selection-background-color: #e8f0fe;
                selection-color: #1a1a1a;
                alternate-background-color: #f8f9fa;
            }
            QHeaderView::section {
                background-color: #f1f3f4;
                border: none;
                border-bottom: 1px solid #c5c9d0;
                border-right: 1px solid #e8eaed;
                padding: 6px 8px;
                font-weight: 600;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 4px;
                font-family: "Consolas", "Courier New", monospace;
            }
            QProgressBar {
                background-color: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 4px;
                text-align: center;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background-color: #1a73e8;
                border-radius: 3px;
            }
            QTabWidget::pane {
                border: 1px solid #c5c9d0;
                background: #ffffff;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #e8eaed;
                border: 1px solid #c5c9d0;
                border-bottom: none;
                padding: 6px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-bottom: 2px solid #1a73e8;
            }
            QStatusBar {
                background: #e8eaed;
                border-top: 1px solid #c5c9d0;
            }
            QLineEdit {
                background: #ffffff;
                border: 1px solid #c5c9d0;
                border-radius: 4px;
                padding: 4px 8px;
                min-height: 24px;
            }
            QLineEdit:focus {
                border-color: #1a73e8;
            }
            """
        )

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Riddim Extractor")
        self.tray.show()
        self.tray.activated.connect(self._tray_activated)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self.activateWindow()

    # ------------------------------------------------------------------ Tables
    def _load_tables(self):
        # Success
        self.table_success.setRowCount(0)
        for key in sorted(self.core.done, reverse=True):
            p = Path(key)
            name = p.name
            row = self.table_success.rowCount()
            self.table_success.insertRow(row)
            self.table_success.setItem(row, 0, QTableWidgetItem(name))

            # Find the year path for display
            found_path = ""
            for year_dir in self.dest_dir.iterdir():
                if year_dir.is_dir():
                    candidate = year_dir / name
                    if candidate.exists():
                        found_path = str(candidate.relative_to(self.dest_dir))
                        break
            else:
                direct = self.dest_dir / name
                if direct.exists():
                    found_path = name

            self.table_success.setItem(row, 1, QTableWidgetItem(found_path))

            self.table_success.setItem(row, 2, QTableWidgetItem("—"))
            self.table_success.setItem(row, 3, QTableWidgetItem("✓"))
            self.table_success.item(row, 3).setForeground(QColor("#34a853"))

        # Failed
        self.table_failed.setRowCount(0)
        for key in sorted(self.core.failed, reverse=True):
            name = Path(key).name
            reason = self.core.failed_reasons.get(key, "Unknown")
            row = self.table_failed.rowCount()
            self.table_failed.insertRow(row)
            self.table_failed.setItem(row, 0, QTableWidgetItem(name))
            self.table_failed.setItem(row, 1, QTableWidgetItem(key))
            self.table_failed.setItem(row, 2, QTableWidgetItem(reason))

            btn = QPushButton("Retry")
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked=False, k=key: self._retry_one(k))
            self.table_failed.setCellWidget(row, 3, btn)

        self._update_counts()

    def _update_counts(self):
        done_n = len(self.core.done)
        failed_n = len(self.core.failed)
        self.lbl_counts.setText(f"Done: {done_n}  |  Failed: {failed_n}")
        self.lbl_stat_done.setText(str(done_n))
        self.lbl_stat_failed.setText(str(failed_n))

    # ------------------------------------------------------------------ Actions
    def _browse_source(self):
        """Open folder dialog to select source directory."""
        d = QFileDialog.getExistingDirectory(self, "Select Source folder", str(self.source_dir))
        if d:
            self.source_dir = Path(d)
            self.core.source_dir = self.source_dir
            self.lbl_source_path.setText(str(self.source_dir))
            self._update_status_bar()
            self._append_log("INFO", f"Source directory set to: {self.source_dir}")

    def process_selected(self):
        """Let user pick one or more folders and process them."""
        if self.is_processing:
            QMessageBox.warning(self, "Busy", "A processing operation is already in progress.")
            return

        if not self.source_dir.exists():
            QMessageBox.critical(self, "Error", f"Source directory does not exist:\n{self.source_dir}")
            return

        from PySide6.QtWidgets import QFileDialog as QFD
        selected = QFD.getExistingDirectory(
            self,
            "Select folder to process",
            str(self.source_dir),
        )
        if not selected:
            return

        folder = Path(selected)
        self._start_processing([folder], operation="single")

    def process_all_in_source(self):
        """Process all unprocessed folders in the source directory."""
        if self.is_processing:
            QMessageBox.warning(self, "Busy", "A processing operation is already in progress.")
            return

        if not self.source_dir.exists():
            QMessageBox.critical(self, "Error", f"Source directory does not exist:\n{self.source_dir}")
            return

        # Find all subdirectories not yet in done/failed state
        candidates = [
            p for p in sorted(self.source_dir.iterdir())
            if p.is_dir() and str(p.resolve()) not in self.core.done and str(p.resolve()) not in self.core.failed
        ]
        if not candidates:
            QMessageBox.information(self, "Process All", "No unprocessed folders found in source directory.")
            return

        self._append_log("INFO", f"Processing {len(candidates)} folder(s) from source directory...")
        self._start_processing(candidates, operation="batch")

    def import_year_mappings(self):
        """Open file dialog to import year mappings from riddim_agent."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Year Mapping File",
            str(self.state_file.parent),
            "JSON files (*.json);;All files (*)"
        )
        if not filepath:
            return

        try:
            result = self.core.load_year_mapping(Path(filepath))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load year mapping file:\n{e}")
            return

        # Show preview dialog
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QTextEdit
        from PySide6.QtCore import Qt

        preview = QDialog(self)
        preview.setWindowTitle("Import Year Mappings Preview")
        preview.setMinimumWidth(500)
        preview.setMinimumHeight(300)

        layout = QVBoxLayout(preview)

        layout.addWidget(QLabel(f"Loaded: {result['loaded']} mappings"))
        layout.addWidget(QLabel(f"Skipped (already processed/failed): {result['skipped']} mappings"))

        if result['warnings']:
            layout.addWidget(QLabel("Warnings:"))
            warnings_text = QTextEdit()
            warnings_text.setReadOnly(True)
            warnings_text.setMaximumHeight(100)
            warnings_text.setPlainText("\n".join(result['warnings'][:10]))  # Limit to first 10 warnings
            layout.addWidget(warnings_text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(preview.accept)
        buttons.rejected.connect(preview.reject)
        layout.addWidget(buttons)

        if preview.exec() == QDialog.DialogCode.Accepted:
            # Apply the mappings: add to done state
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            mappings = data.get("mappings", {})

            # Add imported folders to done state (mark as processed)
            newly_done = 0
            for folder_name in mappings.keys():
                resolved_path = str((self.source_dir / folder_name).resolve())
                if resolved_path not in self.core.done and resolved_path not in self.core.failed:
                    self.core.done.add(resolved_path)
                    newly_done += 1

            # Save the updated state
            self.core.save_state()

            # Refresh UI
            self._load_tables()
            self._update_counts()
            self._append_log("INFO", f"Imported {newly_done} year mappings and marked folders as processed")
            QMessageBox.information(self, "Success", f"Successfully imported {newly_done} year mappings.")
        else:
            # User cancelled - nothing to do, mappings were already loaded into self.imported_years
            # but we don't want to process them since user cancelled
            pass

    def _launch_mapping_uploader(self):
        """Launch the mapping-based upload tool."""
        if not MAPPING_UPLOADER_AVAILABLE:
            QMessageBox.critical(
                self,
                "Error",
                "Mapping uploader module not available.",
            )
            return
        run_mapping_uploader(QApplication.instance(), self.core)

    def _start_processing(self, candidates: list[Path], operation: str = "single"):
        """Start processing folders in a background thread.
        
        Args:
            candidates: List of folders to process
            operation: "single", "batch", or "retry"
        """
        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        
        # Disconnect previous connections to avoid accumulation
        try:
            self.thread.started.disconnect()
        except (RuntimeError, TypeError):
            pass  # No connections to disconnect
        
        # Reset worker parameters
        self.worker._folder = None
        self.worker._candidates = None
        self.worker._retry_key = None
        
        # Set parameters based on operation
        if operation == "single":
            self.worker._folder = candidates[0]
        elif operation == "batch":
            self.worker._candidates = candidates
        elif operation == "retry":
            self.worker._retry_key = str(candidates[0].resolve())
        
        # Connect thread.started to worker.execute_operation()
        self.thread.started.connect(self.worker.execute_operation)
        
        # Reset worker stop flag
        self.worker._should_stop = False
        
        # Start the thread
        self.thread.start()

    def _set_processing_ui(self, processing: bool):
        self.btn_process.setEnabled(not processing)
        self.btn_process_all.setEnabled(not processing)
        self.lbl_status.setText("● Processing" if processing else "● Ready")
        if processing:
            self.lbl_status.setStyleSheet("color: #1a73e8; font-weight: 600;")
        else:
            self.lbl_status.setStyleSheet("color: #5f6368; font-weight: 600;")
        self._update_mode_badge()

    def _update_mode_badge(self):
        mode = "COPY" if self.core.copy_only else "MOVE"
        color = "#34a853" if self.core.copy_only else "#ea4335"
        self.lbl_mode_badge.setText(mode)
        self.lbl_mode_badge.setStyleSheet(
            f"background-color: {color}; color: white; padding: 2px 8px; border-radius: 4px; font-weight: 600; font-size: 11px;"
        )

    # ------------------------------------------------------------------ Worker Handlers
    def _on_worker_started(self):
        """Called when worker starts processing."""
        self.is_processing = True
        self._set_processing_ui(True)
        self.progress_bar.setRange(0, 100)

    def _on_worker_progress(self, index: int, folder_name: str):
        """Called when worker reports progress."""
        self.progress_bar.setValue(index)
        self.lbl_operation.setText(f"Processing: {folder_name}")

    def _on_worker_finished(self, result: ExtractResult):
        """Called when worker finishes a folder."""
        if result.execution_trace:
            for line in result.execution_trace.split("\n"):
                if line.strip():
                    self._append_log("TRACE", line.strip())
        
        if result.success:
            self._append_log("INFO", f"✓ SUCCESS: {result.folder_name} ({result.audio_count} files)")
            if result.error:
                self._append_log("DEBUG", f"  → Note: {result.error}")
        else:
            self._append_log("ERROR", f"✗ FAILED: {result.folder_name} - {result.error}")

    def _on_worker_error(self, error_msg: str):
        """Called when worker encounters an error."""
        self._append_log("ERROR", f"✗ Worker error: {error_msg}")

    def _on_worker_completed(self):
        """Called when worker completes all operations."""
        self.is_processing = False
        self._set_processing_ui(False)
        self.progress_bar.setRange(0, 100)
        self.lbl_operation.setText("No operation in progress.")
        self.statusBar().showMessage("Processing complete")
        self._load_tables()

    def retry_all_failed(self):
        keys = list(self.core.failed)
        if not keys:
            QMessageBox.information(self, "Retry", "No failed items to retry.")
            return
        reply = QMessageBox.question(
            self,
            "Retry Failed",
            f"Retry {len(keys)} failed item(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._append_log("INFO", f"Retrying {len(keys)} failed item(s)...")
        self._start_processing([Path(k) for k in keys], operation="retry")

    def _retry_one(self, key: str):
        folder = Path(key)
        self._append_log("INFO", f"─" * 50)
        self._append_log("INFO", f"Single retry: {folder.name}")
        self._start_processing([folder], operation="retry")

    def _clear_history(self, which: str):
        reply = QMessageBox.question(
            self,
            "Clear History",
            f"Clear {which} history? This only clears the state file, not the music files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.core.clear_history(which)
            self._load_tables()
            self._append_log("INFO", f"Cleared {which} history")

    def show_settings(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumWidth(480)
        layout = QFormLayout(dlg)

        src_edit = QLineEdit(str(self.source_dir))
        dest_edit = QLineEdit(str(self.dest_dir))
        state_edit = QLineEdit(str(self.state_file))
        copy_chk = QCheckBox("Copy instead of Move (default)")
        copy_chk.setChecked(self.copy_only)
        copy_chk.setToolTip("When checked, folders are copied to destination instead of moved")

        def browse_src():
            d = QFileDialog.getExistingDirectory(dlg, "Source folder", str(self.source_dir))
            if d:
                src_edit.setText(d)

        def browse_dest():
            d = QFileDialog.getExistingDirectory(dlg, "Destination folder", str(self.dest_dir))
            if d:
                dest_edit.setText(d)

        src_row = QHBoxLayout()
        src_row.addWidget(src_edit)
        btn_src = QPushButton("…")
        btn_src.setFixedWidth(32)
        btn_src.clicked.connect(browse_src)
        src_row.addWidget(btn_src)

        dest_row = QHBoxLayout()
        dest_row.addWidget(dest_edit)
        btn_dest = QPushButton("…")
        btn_dest.setFixedWidth(32)
        btn_dest.clicked.connect(browse_dest)
        dest_row.addWidget(btn_dest)

        layout.addRow("Source folder:", src_row)
        layout.addRow("Destination:", dest_row)
        layout.addRow("State file:", state_edit)
        layout.addRow("Mode:", copy_chk)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.source_dir = Path(src_edit.text().strip())
            self.dest_dir = Path(dest_edit.text().strip())
            self.state_file = Path(state_edit.text().strip())
            self.copy_only = copy_chk.isChecked()

            self.settings.setValue("source_dir", str(self.source_dir))
            self.settings.setValue("dest_dir", str(self.dest_dir))
            self.settings.setValue("state_file", str(self.state_file))
            self.settings.setValue("copy_only", self.copy_only)

            self.core.source_dir = self.source_dir
            self.core.dest_dir = self.dest_dir
            self.core.state_file = self.state_file
            self.core.copy_only = self.copy_only
            self.core._load_state()

            self.lbl_source_path.setText(str(self.source_dir))
            self.lbl_paths.setText(f"→  {self.dest_dir}")
            self.lbl_stat_source.setText(str(self.source_dir))
            self.lbl_stat_dest.setText(str(self.dest_dir))
            self._update_mode_badge()
            self._load_tables()
            self._update_status_bar()
            self._append_log("INFO", "Settings updated")

    def _open_folder(self, path: Path):
        path = Path(path)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        import os
        import subprocess

        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    # ------------------------------------------------------------------ Logging
    def _append_log(self, level: str, msg: str):
        color = {
            "INFO": "#9cdcfe",
            "WARNING": "#dcdcaa",
            "ERROR": "#f44747",
            "DEBUG": "#6a9955",
            "TRACE": "#c58600",
        }.get(level, "#d4d4d4")
        ts = time.strftime("%H:%M:%S")
        html = f'<span style="color:#808080">[{ts}]</span> <span style="color:{color}">[{level}]</span> {msg}'
        self.log_view.append(html)
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)

    def _update_status_bar(self):
        self.statusBar().showMessage(
            f"Source: {self.source_dir}  |  Dest: {self.dest_dir}  |  State: {self.state_file}"
        )

    def closeEvent(self, event):
        if self.is_processing:
            reply = QMessageBox.question(
                self,
                "Quit",
                "Processing is in progress. Stop and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main():
    check_and_install_dependencies()
    app = QApplication(sys.argv)
    app.setApplicationName("Riddim Extractor")
    app.setOrganizationName("RiddimTools")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()