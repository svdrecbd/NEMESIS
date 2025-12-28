# app/ui/tabs/dashboard.py
import json
import csv
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, 
    QListWidget, QListWidgetItem, QAbstractItemView, QSizePolicy, 
    QFrame, QComboBox, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices

from app.core.runlib import RunLibrary, RunSummary
from app.core.analyzer import RunAnalyzer
from app.core.paths import RUNS_DIR
from app.ui.widgets.chart import LiveChart
from app.ui.theme import active_theme, BG, BORDER, TEXT, MID, ACCENT

ROOT_MARGIN_PX = 12
ROOT_SPACING_PX = 12
DETAIL_PANEL_SPACING_PX = 10
LIST_PANEL_SPACING_PX = 6
HEADER_SPACING_PX = 6
CHART_CONTROLS_TOP_MARGIN_PX = 4
CHART_CONTROLS_SPACING_PX = 6
PALETTE_ROW_SPACING_PX = 6
ACTION_ROW_SPACING_PX = 8
CHART_FRAME_BORDER_PX = 1
FONT_FAMILY_FALLBACK = "Typestar OCR Regular"
SECONDS_PER_MIN = 60.0
MS_PER_SEC = 1000.0

class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.setAutoFillBackground(True)
        self.library = RunLibrary(RUNS_DIR)
        self.current_summary: Optional[RunSummary] = None
        self.current_times: list[float] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(ROOT_MARGIN_PX, ROOT_MARGIN_PX, ROOT_MARGIN_PX, ROOT_MARGIN_PX)
        root.setSpacing(ROOT_SPACING_PX)

        # Run list
        list_panel = QVBoxLayout()
        list_panel.setContentsMargins(0, 0, 0, 0)
        list_panel.setSpacing(LIST_PANEL_SPACING_PX)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(HEADER_SPACING_PX)
        header_label = QLabel("Runs")
        header_label.setStyleSheet("font-weight:bold;")
        header.addWidget(header_label)
        header.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_runs)
        header.addWidget(self.refresh_btn)
        list_panel.addLayout(header)

        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.run_list.itemSelectionChanged.connect(self._on_run_selected)
        list_panel.addWidget(self.run_list, 1)

        root.addLayout(list_panel, 0)

        # Detail / chart panel
        detail_panel = QVBoxLayout()
        detail_panel.setContentsMargins(0, 0, 0, 0)
        detail_panel.setSpacing(DETAIL_PANEL_SPACING_PX)

        self.info_label = QLabel("Select a run to inspect logs and metrics.")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        detail_panel.addWidget(self.info_label)

        # Chart reuse LiveChart
        self.chart_frame = QFrame()
        self.chart_frame.setStyleSheet(
            f"background: {BG}; border: {CHART_FRAME_BORDER_PX}px solid {BORDER};"
        )
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chart_layout = QVBoxLayout(self.chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        
        # Font handling is tricky if font DB isn't loaded, but Chart handles fallback
        font_family = FONT_FAMILY_FALLBACK # Best effort assumption
        self.chart = LiveChart(font_family=font_family, theme=active_theme())
        
        chart_layout.addWidget(self.chart.canvas)
        chart_controls = QHBoxLayout()
        chart_controls.setContentsMargins(0, CHART_CONTROLS_TOP_MARGIN_PX, 0, 0)
        chart_controls.setSpacing(CHART_CONTROLS_SPACING_PX)
        self.long_mode_combo = QComboBox()
        self.long_mode_combo.addItem("Tap Raster", "taps")
        self.long_mode_combo.addItem("Contraction Heatmap", "contraction")
        self.long_mode_combo.currentIndexChanged.connect(self._on_chart_long_mode_changed)
        self.long_mode_combo.setVisible(False)
        chart_controls.addWidget(self.long_mode_combo)
        palette_label = QLabel("Heatmap palette:")
        self.chart_palette_combo = QComboBox()
        for palette in LiveChart.PALETTES:
            self.chart_palette_combo.addItem(palette.capitalize(), palette)
        idx_palette = self.chart_palette_combo.findData(self.chart.heatmap_palette)
        if idx_palette != -1:
            self.chart_palette_combo.setCurrentIndex(idx_palette)
        self.chart_palette_combo.currentIndexChanged.connect(self._on_chart_palette_changed)
        self.chart_palette_combo.setEnabled(self.chart.heatmap_active())
        palette_box = QWidget()
        palette_box_layout = QHBoxLayout(palette_box)
        palette_box_layout.setContentsMargins(0, 0, 0, 0)
        palette_box_layout.setSpacing(PALETTE_ROW_SPACING_PX)
        palette_box_layout.addWidget(palette_label)
        palette_box_layout.addWidget(self.chart_palette_combo)
        self.chart_palette_box = palette_box
        palette_box.setVisible(self.chart.heatmap_active())
        self.chart_export_btn = QPushButton("Export Plot…")
        self.chart_export_btn.clicked.connect(self._export_plot_image)
        self.chart_export_btn.setEnabled(False)
        chart_controls.addWidget(palette_box)
        chart_controls.addStretch(1)
        chart_controls.addWidget(self.chart_export_btn)
        chart_layout.addLayout(chart_controls)
        self.chart.add_long_mode_listener(self._on_chart_long_mode_state)
        self.chart.add_heatmap_listener(self._on_chart_heatmap_mode_changed)
        detail_panel.addWidget(self.chart_frame, 1)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(ACTION_ROW_SPACING_PX)
        self.open_btn = QPushButton("Open Folder")
        self.open_btn.clicked.connect(self._open_run_folder)
        self.analyze_btn = QPushButton("Analyze Run")
        self.analyze_btn.clicked.connect(self._analyze_run)
        self.export_btn = QPushButton("Export CSV…")
        self.export_btn.clicked.connect(self._export_run_csv)
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.clicked.connect(self._delete_run)
        for btn in (self.open_btn, self.analyze_btn, self.export_btn, self.delete_btn):
            btn.setEnabled(False)
        action_row.addWidget(self.open_btn)
        action_row.addWidget(self.analyze_btn)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.delete_btn)
        action_row.addStretch(1)
        detail_panel.addLayout(action_row)

        root.addLayout(detail_panel, 1)

        self.refresh_runs()
        self.set_theme(active_theme())

    # Run list management

    def _analyze_run(self):
        summary = self.current_summary
        if not summary:
            return
        
        self.info_label.setText(f"Analyzing {summary.run_id}...")
        
        analyzer = RunAnalyzer(summary.path)
        results = analyzer.analyze()
        
        if results:
            self.info_label.setText(f"Analysis complete for {summary.run_id}.\n" 
                                    f"Processed {len(results['taps'])} taps.")
            QMessageBox.information(self, "Analysis Complete", 
                                    f"Successfully analyzed {len(results['taps'])} taps.\n"
                                    f"Saved to {summary.path / 'analysis.json'}")
            # Here we could reload the chart with the new data if we parse analysis.json
        else:
            self.info_label.setText("Analysis failed. Check logs.")
            QMessageBox.warning(self, "Analysis Failed", "Could not analyze run. Ensure tracking.csv exists.")

    def refresh_runs(self, *_args, select_run: Optional[str] = None):
        current_target = select_run or (self.current_summary.run_id if self.current_summary else None)
        self.run_list.blockSignals(True)
        self.run_list.clear()
        runs = self.library.list_runs()
        target_row = 0
        for idx, summary in enumerate(runs):
            item = QListWidgetItem(summary.run_id)
            item.setData(Qt.UserRole, summary)
            self.run_list.addItem(item)
            if current_target and (summary.run_id == current_target or summary.path.name == current_target):
                target_row = idx
        self.run_list.blockSignals(False)
        if runs:
            self.run_list.setCurrentRow(target_row)
        else:
            self._set_current_summary(None)

    def _on_run_selected(self):
        items = self.run_list.selectedItems()
        count = len(items)
        self.open_btn.setEnabled(count == 1)
        self.analyze_btn.setEnabled(count == 1)
        self.export_btn.setEnabled(count >= 1)
        self.delete_btn.setEnabled(count >= 1)
        if hasattr(self, "chart_export_btn"):
            self.chart_export_btn.setEnabled(count == 1)
        if count == 0:
            self._set_current_summary(None)
            return
        if count == 1:
            item = items[0]
            summary = item.data(Qt.UserRole) if item else None
            self._set_current_summary(summary)
            return
        summaries = [item.data(Qt.UserRole) for item in items if item and item.data(Qt.UserRole)]
        self.current_summary = None
        self.current_times = []
        self.chart.reset()
        self.chart.set_contraction_heatmap(None)
        if not summaries:
            self.info_label.setText("Select a run to inspect logs and metrics.")
            return
        sample_ids = ", ".join(s.run_id for s in summaries[:4])
        if len(summaries) > 4:
            sample_ids += ", …"
        self.info_label.setText(
            f"{len(summaries)} runs selected. Export creates tap logs for each run; Delete removes their folders.\n"
            f"Selected preview: {sample_ids}"
        )

    def _set_current_summary(self, summary: Optional[RunSummary]):
        self.current_summary = summary
        self.current_times = []
        if summary is None:
            self.info_label.setText("Select a run to inspect logs and metrics.")
            self.chart.reset()
            self.chart.set_contraction_heatmap(None)
            if hasattr(self, "chart_export_btn"):
                self.chart_export_btn.setEnabled(False)
            return

        self.export_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.info_label.setText(self._format_summary(summary))
        heatmap = self._load_contraction_heatmap(summary)
        self.chart.set_contraction_heatmap(heatmap)
        self.current_times = self._load_run_times(summary)
        if self.current_times:
            self.chart.set_times(self.current_times)
        else:
            self.chart.reset()
        if hasattr(self, "chart_export_btn"):
            self.chart_export_btn.setEnabled(True)

    def _selected_summaries(self) -> list[RunSummary]:
        summaries: list[RunSummary] = []
        for item in self.run_list.selectedItems():
            if not item:
                continue
            summary = item.data(Qt.UserRole)
            if isinstance(summary, RunSummary):
                summaries.append(summary)
        return summaries

    def _format_summary(self, summary: RunSummary) -> str:
        parts = [f"<b>{summary.run_id}</b>"]
        if summary.started_at:
            parts.append(f"Started: {summary.started_at}")
        if summary.duration_s is not None:
            parts.append(f"Duration: {summary.duration_s / SECONDS_PER_MIN:.1f} min")
        if summary.taps_count is not None:
            parts.append(f"Taps: {summary.taps_count}")
        if summary.mode:
            if summary.mode == "Periodic" and summary.period_sec:
                parts.append(f"Mode: Periodic ({summary.period_sec:.2f}s)")
            elif summary.mode == "Poisson" and summary.lambda_rpm:
                parts.append(f"Mode: Poisson ({summary.lambda_rpm:.2f}/min)")
            else:
                parts.append(f"Mode: {summary.mode}")
        if summary.stepsize is not None:
            parts.append(f"Stepsize: {summary.stepsize}")
        if summary.serial_port:
            parts.append(f"Serial: {summary.serial_port}")
        return "<br>".join(parts)

    def _load_run_times(self, summary: RunSummary) -> list[float]:
        taps_path = summary.path / "taps.csv"
        times: list[float] = []
        if not taps_path.exists():
            return times
        try:
            with taps_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                first_host = None
                for row in reader:
                    t_ms = float(row.get("t_host_ms", 0.0))
                    if first_host is None:
                        first_host = t_ms
                    times.append((t_ms - first_host) / MS_PER_SEC)
        except Exception:
            return []
        return times

    def _on_chart_long_mode_state(self, active: bool):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        combo.blockSignals(True)
        if active:
            view = self.chart.long_run_view()
            idx = combo.findData(view)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            combo.setVisible(True)
        else:
            combo.setCurrentIndex(0)
            combo.setVisible(False)
        combo.blockSignals(False)

    def _on_chart_long_mode_changed(self, index: int):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        if not combo.isVisible():
            return
        view = combo.itemData(index)
        if not view:
            return
        self.chart.set_long_run_view(str(view))


    def _load_contraction_heatmap(self, summary: RunSummary):
        analysis_path = summary.path / "analysis.json"
        if analysis_path.exists():
            try:
                with analysis_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                matrix = data.get("contraction_heatmap")
                if isinstance(matrix, list):
                    return matrix
            except Exception:
                pass
        csv_path = summary.path / "contraction_heatmap.csv"
        if csv_path.exists():
            try:
                rows: list[list[float]] = []
                with csv_path.open("r", encoding="utf-8", newline="") as fh:
                    reader = csv.reader(fh)
                    for row in reader:
                        if row:
                            rows.append([float(value) for value in row])
                if rows:
                    return rows
            except Exception:
                pass
        return None

    def _on_chart_palette_changed(self, index: int):
        data = self.chart_palette_combo.itemData(index)
        if not data:
            return
        self.chart.set_heatmap_palette(str(data))

    def _on_chart_heatmap_mode_changed(self, active: bool):
        if hasattr(self, "chart_palette_box"):
            self.chart_palette_box.setVisible(active)
        if hasattr(self, "chart_palette_combo"):
            self.chart_palette_combo.setEnabled(active)

    def _export_plot_image(self):
        summary = self.current_summary
        if summary is None:
            QMessageBox.information(self, "Dashboard", "Select a run first.")
            return
        default_path = summary.path / f"{summary.run_id}_plot.png"
        dest, _ = QFileDialog.getSaveFileName(
            self, 
            "Export plot", 
            str(default_path),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)"
        )
        if not dest:
            return
        try:
            self.chart.save(dest)
        except Exception as exc:
            QMessageBox.warning(self, "Export Plot", f"Failed to export plot: {exc}")
            return
        QMessageBox.information(self, "Export Plot", f"Plot exported → {dest}")

    # Actions

    def _open_run_folder(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select a run first.")
            return
        target = summaries[0]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.path.resolve())))

    def _export_run_csv(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select at least one run to export.")
            return
        if len(summaries) == 1:
            summary = summaries[0]
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Export taps.csv",
                str(summary.path / "taps.csv"),
                "CSV Files (*.csv)",
            )
            if not dest:
                return
            try:
                shutil.copy2(summary.path / "taps.csv", dest)
            except Exception as exc:
                QMessageBox.warning(self, "Export", f"Failed to export CSV: {exc}")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if not dest_dir:
            return
        export_root = Path(dest_dir)
        failures: list[str] = []
        exported = 0
        for summary in summaries:
            src = summary.path / "taps.csv"
            if not src.exists():
                failures.append(f"{summary.run_id}: taps.csv missing")
                continue
            dest_path = export_root / f"{summary.run_id}.csv"
            try:
                shutil.copy2(src, dest_path)
                exported += 1
            except Exception as exc:
                failures.append(f"{summary.run_id}: {exc}")
        if failures:
            QMessageBox.warning(self, "Export", "Some exports failed:\n" + "\n".join(failures[:6]))
        if exported:
            QMessageBox.information(self, "Export", f"Exported {exported} CSV files to {export_root}")

    def _delete_run(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select at least one run to delete.")
            return
        if len(summaries) == 1:
            summary = summaries[0]
            prompt = f"Delete run '{summary.run_id}'? This cannot be undone."
        else:
            prompt = f"Delete {len(summaries)} runs? This cannot be undone."
        resp = QMessageBox.question(
            self,
            "Delete Run",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        failures: list[str] = []
        deleted = 0
        for summary in summaries:
            try:
                shutil.rmtree(summary.path)
                deleted += 1
            except Exception as exc:
                failures.append(f"{summary.run_id}: {exc}")
        if failures:
            QMessageBox.warning(self, "Delete", "Some deletions failed:\n" + "\n".join(failures[:6]))
        if deleted:
            self.refresh_runs()

    def set_theme(self, theme: dict[str, str]):
        bg = theme.get("BG", BG)
        text = theme.get("TEXT", TEXT)
        accent = theme.get("ACCENT", ACCENT)
        border = theme.get("BORDER", BORDER)
        mid = theme.get("MID", MID)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(bg))
        self.setPalette(pal)
        self.info_label.setStyleSheet(f"color: {text};")
        self.chart_frame.setStyleSheet(f"background: {bg}; border: 1px solid {border};")
        list_style = (
            f"QListWidget {{background: {mid}; color: {text}; border: 1px solid {border};}}\n"
            f"QListWidget::item:selected {{background: {accent}; color: {bg}; border: 1px solid {accent};}}"
        )
        self.run_list.setStyleSheet(list_style.strip())
        button_style = (
            f"QPushButton {{background: {mid}; color: {text}; border: 1px solid {theme.get('BUTTON_BORDER', border)}; padding: 4px 10px; border-radius: 0px;}}\n"
            f"QPushButton:hover {{background: {accent}; color: {bg}; border-color: {accent}; border-radius: 0px;}}"
        )
        for btn in (self.refresh_btn, self.open_btn, self.analyze_btn, self.export_btn, self.delete_btn):
            btn.setStyleSheet(button_style.strip())
        self.chart.set_theme(theme)
