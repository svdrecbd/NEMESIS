# app/main.py
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTabWidget, QPushButton, QMenu, QStyleFactory, QTabBar, QToolButton
)
from PySide6.QtCore import Qt, Slot, QPoint, QObject
from PySide6.QtGui import QIcon

from app.core.paths import LOGO_PATH, FONT_PATH
from app.core.version import APP_VERSION
from app.ui.theme import (
    build_stylesheet, active_theme, set_active_theme,
    BG, TEXT, MID, BORDER, ACCENT
)
from app.ui.tabs.run_tab import RunTab, ResourceRegistry
from app.ui.tabs.dashboard import DashboardTab
from app.core.logger import APP_LOGGER
from app.ui.widgets.viewer import AppZoomView
from app.ui.widgets.containers import LeftAlignTabBar

_APP_ICON = None
_FONT_FAMILY = "Typestar OCR Regular"
APP_DEFAULT_SIZE = (1520, 940)
APP_MIN_SIZE = (1280, 780)
APP_ICON_SIZES = (16, 32, 64, 128, 256)
TAB_CLOSE_BUTTON_SIZE = 12
TAB_CLOSE_FONT_PX = 10
CORNER_BTN_MARGIN_PX = 6
CORNER_BTN_PADDING_PX = (4, 12)
APP_FONT_PT = 11
ICON_ALPHA_THRESHOLD = 10

def _apply_global_font(app: QApplication):
    """Load Typestar OCR and apply as app default if present."""
    from PySide6.QtGui import QFontDatabase, QFont
    global _FONT_FAMILY
    fid = QFontDatabase.addApplicationFont(str(FONT_PATH))
    if fid != -1:
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            _FONT_FAMILY = fams[0]
            app.setFont(QFont(_FONT_FAMILY, APP_FONT_PT))

def build_app_icon():
    from PySide6.QtGui import QImage, QPixmap, QPainter
    from PySide6.QtCore import QRect
    try:
        image = QImage(str(LOGO_PATH))
        if image.isNull():
            return None
        width = image.width()
        height = image.height()
        min_x, min_y = width, height
        max_x, max_y = -1, -1
        for y in range(height):
            for x in range(width):
                if image.pixelColor(x, y).alpha() > ICON_ALPHA_THRESHOLD:
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y
        if min_x > max_x or min_y > max_y:
            cropped = image
        else:
            rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            cropped = image.copy(rect)
        size = max(cropped.width(), cropped.height())
        square = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        square.fill(Qt.transparent)
        painter = QPainter(square)
        try:
            painter.drawImage(
                (size - cropped.width()) // 2,
                (size - cropped.height()) // 2,
                cropped
            )
        finally:
            painter.end()
        base_pix = QPixmap.fromImage(square)
        icon = QIcon()
        for target in APP_ICON_SIZES:
            icon.addPixmap(base_pix.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return icon
    except Exception as e:
        APP_LOGGER.error(f"Icon error: {e}")
        return None

class App(QWidget):
    def __init__(self):
        super().__init__()
        global _APP_ICON
        self.setWindowTitle(f"NEMESIS {APP_VERSION} — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States")
        if _APP_ICON is not None:
            self.setWindowIcon(_APP_ICON)
        self.resize(*APP_DEFAULT_SIZE)
        self.setMinimumSize(*APP_MIN_SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.resource_registry = ResourceRegistry()
        self._run_tab_counter = 1
        self._run_tab_custom_names = {}
        self._data_tabs = []
        self._data_tab_custom_names = {}

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.setTabsClosable(True)
        try:
            self.tab_widget.tabCloseRequested.connect(self._handle_tab_close_requested)
        except Exception:
            pass
        try:
            self.tab_widget.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        except Exception:
            pass
        tab_bar = LeftAlignTabBar()
        self.tab_widget.setTabBar(tab_bar)
        tab_bar.setDrawBase(False)
        tab_bar.setElideMode(Qt.ElideNone)

        run_tab = RunTab(resource_registry=self.resource_registry)
        self._register_run_tab(run_tab)
        self.tab_widget.addTab(run_tab, self._format_run_tab_title(self._run_tab_counter))
        self._run_tab_custom_names[run_tab] = None
        self._run_tab_counter += 1

        self._create_dashboard_tab(initial=True)
        self.tab_widget.setCurrentIndex(0)
        self._refresh_tab_close_buttons()

        self.new_tab_btn = QPushButton("+ Tab")
        self.new_tab_btn.setCursor(Qt.PointingHandCursor)
        self.new_tab_btn.setToolTip("Open a new tab")
        self.new_tab_btn.clicked.connect(self._show_new_tab_menu)
        self.tab_widget.setCornerWidget(self.new_tab_btn, Qt.TopRightCorner)
        self._apply_theme_to_corner_button()
        
        # Wrap everything in zoom view
        contentw = QWidget()
        content_layout = QVBoxLayout(contentw)
        content_layout.setContentsMargins(0,0,0,0)
        content_layout.addWidget(self.tab_widget)
        
        self.app_view = AppZoomView(bg_color=BG)
        self.app_view.set_content(contentw)
        
        layout.addWidget(self.app_view)
        
        self._tab_chord_active = False
        self._tab_chord_triggered = False

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        key = event.key()
        is_cmd = bool(modifiers & Qt.MetaModifier)
        is_ctrl = bool(modifiers & Qt.ControlModifier)
        is_alt = bool(modifiers & Qt.AltModifier)
        handled = False
        if is_cmd or is_ctrl:
            if self._tab_chord_active and key in (Qt.Key_R, Qt.Key_F):
                if key == Qt.Key_R:
                    self._create_run_tab()
                else:
                    self._create_dashboard_tab()
                self._tab_chord_active = False
                self._tab_chord_triggered = True
                handled = True
            elif key == Qt.Key_T:
                self._tab_chord_active = True
                self._tab_chord_triggered = False
                handled = True
            elif key == Qt.Key_W:
                self._close_current_tab_with_prompt()
                handled = True
            elif is_alt and key in (Qt.Key_Left, Qt.Key_Right):
                self._cycle_tabs(-1 if key == Qt.Key_Left else 1)
                handled = True
            else:
                if self._tab_chord_active:
                    self._tab_chord_active = False
                    self._tab_chord_triggered = False
        else:
            if self._tab_chord_active:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
        if handled:
            event.accept()
            return
        widget = self.tab_widget.currentWidget()
        if isinstance(widget, RunTab):
            widget.keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = event.key()
        if self._tab_chord_active and key == Qt.Key_T:
            if not self._tab_chord_triggered:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
                self._show_new_tab_menu()
            else:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
            event.accept()
            return
        if key in (Qt.Key_Meta, Qt.Key_Control):
            self._tab_chord_active = False
            self._tab_chord_triggered = False
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        for idx in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(idx)
            if isinstance(widget, RunTab):
                try:
                    widget.shutdown()
                except Exception:
                    pass
        super().closeEvent(event)

    def _register_run_tab(self, tab: RunTab):
        try:
            tab.runCompleted.connect(self._on_run_completed)
        except Exception:
            pass
        try:
            tab.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass
        try:
            tab.apply_theme_external(active_theme()["BG"]) # Simplification, logic handled in tab
        except Exception:
            pass

    @Slot(str, str)
    def _on_run_completed(self, run_id: str, run_path: str):
        if self._data_tabs:
            try:
                self._data_tabs[0].refresh_runs(select_run=run_id)
            except Exception:
                pass

    @Slot(str)
    def _on_theme_changed(self, name: str):
        self._propagate_theme(name, source=self.sender())

    def _propagate_theme(self, name: str, source: QObject | None = None):
        set_active_theme(name) # Update global state
        QApplication.instance().setStyleSheet(build_stylesheet(_FONT_FAMILY, 1.0))
        for idx in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(idx)
            if isinstance(widget, RunTab) and widget is not source:
                try:
                    widget.apply_theme_external(name)
                except Exception:
                    pass
            elif isinstance(widget, DashboardTab):
                try:
                    widget.set_theme(active_theme())
                except Exception:
                    pass
        self._apply_theme_to_corner_button()
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is not None:
            tab_bar.setDrawBase(False)
            tab_bar.setElideMode(Qt.ElideNone)
            tab_bar.update()
        self._update_tab_close_button_styles()

    def _format_run_tab_title(self, index: int) -> str:
        return f"Run {index}"

    def _format_dashboard_tab_title(self, index: int) -> str:
        return f"Data {index}"

    @Slot()
    def _show_new_tab_menu(self):
        menu = QMenu(self)
        action_run = menu.addAction("Run Tab")
        action_dash = menu.addAction("Data Tab")
        global_pos = self.new_tab_btn.mapToGlobal(QPoint(self.new_tab_btn.width(), self.new_tab_btn.height()))
        chosen = menu.exec(global_pos)
        if chosen is action_run:
            self._create_run_tab()
        elif chosen is action_dash:
            self._create_dashboard_tab()

    def _create_run_tab(self):
        tab = RunTab(resource_registry=self.resource_registry)
        self._register_run_tab(tab)
        # Simple insert logic
        insert_index = self.tab_widget.count()
        self.tab_widget.insertTab(insert_index, tab, self._format_run_tab_title(self._run_tab_counter))
        self.tab_widget.setCurrentWidget(tab)
        self._run_tab_custom_names[tab] = None
        self._run_tab_counter += 1
        self._refresh_tab_close_buttons()

    def _create_dashboard_tab(self, initial: bool = False):
        tab = DashboardTab()
        try:
            tab.set_theme(active_theme())
        except Exception:
            pass
        self._data_tabs.append(tab)
        self._data_tab_custom_names[tab] = None
        default_title = self._format_dashboard_tab_title(len(self._data_tabs))
        self.tab_widget.addTab(tab, default_title)
        if not initial:
            self.tab_widget.setCurrentWidget(tab)
        self._refresh_tab_close_buttons()
        return tab

    @Slot(int)
    def _handle_tab_close_requested(self, index: int):
        self._request_close_tab(index, prompt=True)

    def _request_close_tab(self, index: int, prompt: bool = True):
        if self.tab_widget.count() <= 1:
            return
        widget = self.tab_widget.widget(index)
        if widget is None:
            return
        if isinstance(widget, RunTab):
            try:
                widget.shutdown()
            except Exception:
                pass
        self.tab_widget.removeTab(index)
        if isinstance(widget, RunTab):
            self._run_tab_custom_names.pop(widget, None)
        elif isinstance(widget, DashboardTab):
            if widget in self._data_tabs:
                self._data_tabs.remove(widget)
            self._data_tab_custom_names.pop(widget, None)
        if widget is not None:
            widget.deleteLater()
        self._refresh_tab_close_buttons()

    def _close_current_tab_with_prompt(self):
        index = self.tab_widget.currentIndex()
        self._request_close_tab(index, prompt=True)

    def _cycle_tabs(self, direction: int):
        count = self.tab_widget.count()
        if count <= 1:
            return
        current = self.tab_widget.currentIndex()
        next_index = (current + direction) % count
        self.tab_widget.setCurrentIndex(next_index)

    def _refresh_tab_close_buttons(self):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        total = self.tab_widget.count()
        for idx in range(total):
            widget = self.tab_widget.widget(idx)
            if widget is None:
                continue
            if total <= 1:
                tab_bar.setTabButton(idx, QTabBar.RightSide, None)
                continue
            self._ensure_close_button(idx, widget)
        self._update_run_tab_titles()
        self._update_data_tab_titles()
        self._update_tab_close_button_styles()
        self._apply_theme_to_corner_button()

    def _ensure_close_button(self, index: int, widget: QWidget):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        button = tab_bar.tabButton(index, QTabBar.RightSide)
        if not isinstance(button, QToolButton):
            button = QToolButton(tab_bar)
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setText("×")
            button.setToolTip("Close tab")
            button.clicked.connect(lambda _=False, w=widget: self._request_close_widget(w))
            tab_bar.setTabButton(index, QTabBar.RightSide, button)
        self._style_tab_close_button(button)

    def _style_tab_close_button(self, button: QToolButton):
        theme = active_theme()
        button.setFixedSize(TAB_CLOSE_BUTTON_SIZE, TAB_CLOSE_BUTTON_SIZE)
        button.setStyleSheet(
            "QToolButton {"
            "border: none;"
            "background: transparent;"
            f"color: {theme.get('TEXT', TEXT)};"
            f"font-size: {TAB_CLOSE_FONT_PX}px;"
            "padding: 0px;"
            "margin: 0px;"
            "}"
            "QToolButton:hover {"
            f"background: {theme.get('ACCENT', ACCENT)};"
            f"color: {theme.get('BG', BG)};"
            "border-radius: 0px;"
            "}"
        )

    def _update_tab_close_button_styles(self):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        for idx in range(self.tab_widget.count()):
            button = tab_bar.tabButton(idx, QTabBar.RightSide)
            if isinstance(button, QToolButton):
                self._style_tab_close_button(button)

    def _request_close_widget(self, widget: QWidget):
        idx = self.tab_widget.indexOf(widget)
        if idx != -1:
            self._request_close_tab(idx, prompt=True)

    def _update_data_tab_titles(self):
        pass # simplified

    def _update_run_tab_titles(self):
        pass # simplified

    def _apply_theme_to_corner_button(self):
        if not hasattr(self, "new_tab_btn") or self.new_tab_btn is None:
            return
        theme = active_theme()
        border = theme.get("BUTTON_BORDER", BORDER)
        text = theme.get("TEXT", TEXT)
        base = theme.get("MID", MID)
        accent = theme.get("ACCENT", ACCENT)
        base_bg = base
        hover_fg = theme.get("BG", BG)
        style = f"""
        QPushButton {{
            margin: {CORNER_BTN_MARGIN_PX}px;
            padding: {CORNER_BTN_PADDING_PX[0]}px {CORNER_BTN_PADDING_PX[1]}px;
            border-radius: 0px;
            border: 1px solid {border};
            background: {base_bg};
            color: {text};
        }}
        QPushButton:hover {{
            background: {accent};
            color: {hover_fg};
            border-color: {accent};
        }}
        """
        self.new_tab_btn.setStyleSheet(style.strip())
        self._update_tab_close_button_styles()

    def _on_tab_double_clicked(self, index: int):
        pass

def main():
    app = QApplication(sys.argv)
    _apply_global_font(app)
    try:
        app.setStyle(QStyleFactory.create("Fusion"))
    except Exception:
        pass
    app.setStyleSheet(build_stylesheet(_FONT_FAMILY, 1.0))
    global _APP_ICON
    try:
        _APP_ICON = build_app_icon()
        if _APP_ICON is not None:
            app.setWindowIcon(_APP_ICON)
    except Exception:
        _APP_ICON = None
    w = App()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
