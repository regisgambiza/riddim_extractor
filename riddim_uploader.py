#!/usr/bin/env python3
"""
Riddim Uploader - Mapping-based upload feature.

This module implements a standalone workflow for uploading folders using
external JSON mappings. It creates a separate window/interface that runs
sequentially: select mappings file, source folder, destination folder,
and confirmation. It reuses the core ExtractorCore for copy/move operations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from PySide6.QtWidgets import QProgressBar, QLabel
from PySide6.QtCore import QTimer

from riddim_extractor_gui import ExtractorCore, check_and_install_dependencies


class UploaderWindow(QMainWindow):
    """Standalone mapping-based upload tool.

    Features:
    - Step 1: Select year_mapping.json from riddim_agent
    - Step 2: Select source folder (where folders exist)
    - Step 3: Select destination folder
    - Step 4: Confirmation dialog with stats and sample mappings
    - Process: For each mapping, copy/move source folder to Dest/YYYY/FolderName
    - Skips missing source folders (logs warning)
    - Skips folders already in core.done/core.failed state
    """

    def __init__(self, core: ExtractorCore):
        super().__init__()
        self.core = core
        self.mappings: dict[str, int] = {}
        self.source_dir: Optional[Path] = None
        self.dest_dir: Optional[Path] = None

        self.setWindowTitle("Riddim Uploader")
        self.setMinimumSize(500, 400)
        self.resize(520, 420)

        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Title
        title_label = QLabel("Upload by Year Mappings")
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title_label)

        # Step 1: Load Mappings File
        self.btn_load_mappings = QPushButton("1. Select Year Mapping File (year_mapping.json)")
        self.btn_load_mappings.clicked.connect(self._load_mappings_file)
        root.addWidget(self.btn_load_mappings)

        self.lbl_mappings_info = QLabel("Not loaded")
        self.lbl_mappings_info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(self.lbl_mappings_info)

        # Step 2: Source folder
        self.btn_select_source = QPushButton("2. Select Source Folder")
        self.btn_select_source.clicked.connect(self._select_source_folder)
        self.btn_select_source.setEnabled(False)
        root.addWidget(self.btn_select_source)

        self.lbl_source_info = QLabel("Not selected")
        self.lbl_source_info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(self.lbl_source_info)

        # Step 3: Destination folder
        self.btn_select_dest = QPushButton("3. Select Destination Folder")
        self.btn_select_dest.clicked.connect(self._select_destination_folder)
        self.btn_select_dest.setEnabled(False)
        root.addWidget(self.btn_select_dest)

        self.lbl_dest_info = QLabel("Not selected")
        self.lbl_dest_info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(self.lbl_dest_info)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        # Status label
        self.lbl_status = QLabel("Step 1: Load year mapping file")
        self.lbl_status.setStyleSheet("color: #5f6368; font-size: 12px;")
        root.addWidget(self.lbl_status)

        # Buttons at bottom
        btn_layout = QHBoxLayout()

        self.btn_upload = QPushButton("Upload")
        self.btn_upload.clicked.connect(self._upload)
        self.btn_upload.setEnabled(False)
        btn_layout.addWidget(self.btn_upload)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_cancel)

        root.addLayout(btn_layout)

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #f8f9fa;
                color: #1a1a1a;
                font-family: "Segoe UI", "Arial", sans-serif;
                font-size: 12px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 8px 14px;
                min-height: 20px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border-color: #94a3b8;
            }
            QPushButton:pressed {
                background-color: #e2e8f0;
            }
            QPushButton:disabled {
                background-color: #f3f4f6;
                color: #9ca3af;
                border-color: #e5e7eb;
            }
            QPushButton:default {
                background-color: #3b82f6;
                color: white;
                border: none;
                font-weight: 600;
            }
            QPushButton:default:hover {
                background-color: #2563eb;
            }
            QLabel {
                color: #374151;
            }
            QProgressBar {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 2px;
            }
            """
        )

    def _load_mappings_file(self):
        """Step 1: Load year_mapping.json from riddim_agent."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Year Mapping File",
            str(Path.home),
            "JSON files (*.json);;All files (*)",
        )
        if not filepath:
            return

        try:
            # Re-use ExtractorCore.load_year_mapping for state management
            result = self.core.load_year_mapping(Path(filepath))
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.mappings = data.get("mappings", {})

            if not self.mappings:
                QMessageBox.warning(
                    self,
                    "No Mappings",
                    "The selected file does not contain any mappings.",
                )
                return

            # Update UI
            loaded_count = result["loaded"]
            self.lbl_mappings_info.setText(
                f"Loaded {len(self.mappings)} mappings ({loaded_count} new, "
                f"{result['skipped']} already processed/failed)"
            )

            if result["warnings"]:
                warnings = "\n".join(result["warnings"][:5])  # limit to 5 warnings
                if len(result["warnings"]) > 5:
                    warnings += f"\n...and {len(result['warnings']) - 5} more warnings."
                self._show_message(
                    "Warnings while loading mappings:", warnings, "WARNING"
                )

            self.btn_select_source.setEnabled(True)
            self.lbl_status.setText("Step 2: Select source folder")

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load year mapping file:\n{e}",
            )
            self.mappings.clear()
            self.btn_load_mappings.setText("1. Select Year Mapping File (year_mapping.json)")

    def _select_source_folder(self):
        """Step 2: Select source folder where your riddim folders are located."""
        if not self.mappings:
            QMessageBox.warning(
                self,
                "No Mappings",
                "Please load a year mapping file first.",
            )
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Source Folder",
            str(Path.home),
        )
        if not folder:
            return

        self.source_dir = Path(folder)
        if not self.source_dir.exists():
            QMessageBox.critical(
                self,
                "Error",
                f"Source folder does not exist:\n{self.source_dir}",
            )
            self.source_dir = None
            return

        self.lbl_source_info.setText(str(self.source_dir))
        self.btn_select_dest.setEnabled(True)
        self.lbl_status.setText("Step 3: Select destination folder")

    def _select_destination_folder(self):
        """Step 3: Select destination where organized folders will be created."""
        if not self.mappings:
            QMessageBox.warning(
                self,
                "No Mappings",
                "Please load a year mapping file first.",
            )
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Destination Folder",
            str(Path.home),
        )
        if not folder:
            return

        self.dest_dir = Path(folder)
        if not self.dest_dir.exists():
            QMessageBox.critical(
                self,
                "Error",
                f"Destination folder does not exist:\n{self.dest_dir}",
            )
            self.dest_dir = None
            return

        self.lbl_dest_info.setText(str(self.dest_dir))
        self.btn_upload.setEnabled(True)
        self.lbl_status.setText("Step 4: Click 'Upload' to proceed")

    def _show_message(self, title: str, message: str, level: str = "INFO"):
        """Show a simple message dialog with proper styling."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)

        if level == "WARNING":
            msg_box.setIcon(QMessageBox.Icon.Warning)
        elif level == "ERROR":
            msg_box.setIcon(QMessageBox.Icon.Critical)
        else:
            msg_box.setIcon(QMessageBox.Icon.Information)

        msg_box.exec()

    def _upload(self):
        """Step 4: Perform the upload using mappings.

        Creates Dest/YYYY/FolderName for each mapping where source folder exists.
        Skips missing mapped folders (logs warning).
        Reuses core.copy_only for copy vs move behavior.
        """
        if not self.mappings:
            QMessageBox.warning(
                self,
                "No Mappings",
                "Please load a year mapping file first.",
            )
            return
        if not self.source_dir or not self.source_dir.exists():
            QMessageBox.warning(
                self,
                "Error",
                "Source folder is not set or does not exist.",
            )
            return
        if not self.dest_dir or not self.dest_dir.exists():
            QMessageBox.warning(
                self,
                "Error",
                "Destination folder is not set or does not exist.",
            )
            return

        # Build summary for confirmation
        valid_mappings = 0
        missing_folders = 0
        skipped_processed = 0
        for folder_name in self.mappings:
            source_folder = self.source_dir / folder_name
            if not source_folder.exists():
                missing_folders += 1
                continue
            resolved = str(source_folder.resolve())
            if resolved in self.core.done or resolved in self.core.failed:
                skipped_processed += 1
                continue
            valid_mappings += 1

        mode = "COPY" if self.core.copy_only else "MOVE"
        summary = (
            f"Year Mappings Upload Summary:\n"
            f"• Total mappings: {len(self.mappings)}\n"
            f"• Will process: {valid_mappings}\n"
            f"• Missing source folders: {missing_folders}\n"
            f"• Already processed/failed: {skipped_processed}\n"
            f"• Copy mode: {mode}\n"
            f"\n"
            f"Sample mappings:\n"
        )
        for i, (folder, year) in enumerate(list(self.mappings.items())[:5]):
            status = "✓" if (self.source_dir / folder).exists() else "✗"
            summary += f"  {status} {folder} → {self.dest_dir / year}/{folder}\n"

        if len(self.mappings) > 5:
            summary += f"  ...and {len(self.mappings) - 5} more\n"

        reply = QMessageBox.question(
            self,
            "Confirm Upload",
            summary + "\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Execute upload
        self.btn_upload.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setValue(0)

        self.lbl_status.setText("Uploading...")

        # Process in batches to keep UI responsive
        total = len(self.mappings)
        processed = 0
        success_count = 0
        failed_count = 0
        log_lines = []

        def process_batch():
            nonlocal processed, success_count, failed_count
            current_batch = 0

            def process_next():
                nonlocal current_batch

                if current_batch >= len(self.mappings):
                    self._finish_upload(success_count, failed_count, log_lines)
                    return

                folder_name = list(self.mappings.keys())[current_batch]
                year = self.mappings[folder_name]

                source_folder = self.source_dir / folder_name
                resolved = str(source_folder.resolve())

                # Check if we should skip this one
                if not source_folder.exists():
                    log_lines.append(
                        f"[WARN] Skipping '{folder_name}': source folder does not exist"
                    )
                    current_batch += 1
                    self._update_progress(current_batch, total)
                    QTimer.singleShot(0, process_next)
                    return

                if resolved in self.core.done:
                    log_lines.append(
                        f"[INFO] Skipping '{folder_name}': already processed"
                    )
                    current_batch += 1
                    self._update_progress(current_batch, total)
                    QTimer.singleShot(0, process_next)
                    return

                if resolved in self.core.failed:
                    log_lines.append(
                        f"[WARN] Skipping '{folder_name}': previously failed"
                    )
                    current_batch += 1
                    self._update_progress(current_batch, total)
                    QTimer.singleShot(0, process_next)
                    return

                try:
                    # Direct copy/move from source to dest/year/folder
                    year_dir = self.dest_dir / year
                    year_dir.mkdir(parents=True, exist_ok=True)
                    target = year_dir / folder_name

                    if self.core.copy_only:
                        # Copy mode: copy to destination, then remove from source
                        shutil.copytree(str(source_folder), str(target), dirs_exist_ok=True)
                        shutil.rmtree(str(source_folder))
                    else:
                        # Move mode: move directly
                        shutil.move(str(source_folder), str(target))

                    year_path = f"{year}/{folder_name}"

                    log_lines.append(
                        f"[INFO] Success: {folder_name} -> {year_path} ({len(list(target.rglob('*')))} files)"
                    )

                    success_count += 1

                except Exception as e:
                    log_lines.append(
                        f"[ERROR] ✗ Failed: {folder_name} - {str(e)}"
                    )
                    failed_count += 1
                    # Also add to failed state
                    self.core.failed.add(resolved)
                    self.core.failed_reasons[resolved] = str(e)

                processed += 1
                current_batch += 1

                self._update_progress(current_batch, total)

                QTimer.singleShot(0, process_next)

            process_next()

        # Start processing after UI updates
        QTimer.singleShot(100, process_batch)

    def _update_progress(self, current: int, total: int):
        if total == 0:
            self.progress_bar.setValue(100)
            return
        value = min(100, int((current / total) * 100))
        self.progress_bar.setValue(value)
        self.lbl_status.setText(f"Processing: {current}/{total} folders")

    def _finish_upload(self, success_count: int, failed_count: int, log_lines: list[str]):
        """Finalization after upload completes."""
        # Save core state
        self.core.save_state()

        # Update UI
        self.progress_bar.setValue(100)
        self.btn_upload.setEnabled(False)

        # Add log messages
        log_summary = []
        if success_count:
            log_summary.append(f"✓ Successfully processed {success_count} folder(s)")
        if failed_count:
            log_summary.append(f"✗ Failed to process {failed_count} folder(s)")
        if log_lines:
            log_summary.extend(log_lines)

        # Show summary in a message box
        message = "\n".join(log_summary)
        self._show_message("Upload Complete", message, "INFO")

        # Reset UI
        self.btn_select_source.setEnabled(False)
        self.btn_select_dest.setEnabled(False)
        self.btn_load_mappings.setEnabled(True)
        self.lbl_mappings_info.setText("Not loaded")
        self.lbl_source_info.setText("Not selected")
        self.lbl_dest_info.setText("Not selected")
        self.lbl_status.setText("Ready - Step 1: Load year mapping file")

        # Close uploader window
        self.close()


def run_uploader(app: QApplication, core: ExtractorCore):
    """Launch the mapping-based upload tool.

    Creates a new UploaderWindow instance and shows it. The uploader
    manages its own lifecycle.

    Args:
        app: The main application instance (used for processEvents)
        core: The shared ExtractorCore instance
    """
    uploader = UploaderWindow(core)
    uploader.show()
    return uploader
