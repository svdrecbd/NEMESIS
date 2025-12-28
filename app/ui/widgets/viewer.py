# app/ui/widgets/viewer.py
from PySide6.QtWidgets import (
    QWidget, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, 
    QVBoxLayout, QSizePolicy, QGraphicsProxyWidget
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QRect
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage, QIcon
from app.ui.theme import BG, SCROLLBAR, SUBTXT
from app.core.logger import APP_LOGGER
from .containers import AspectRatioContainer

class ZoomView(QGraphicsView):
    firstFrame = Signal()
    def __init__(self, bg_color: str = "#000", parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._scene.addItem(self._pix)
        # Visuals
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self._bg_color = bg_color
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # Ensure full repaint on first draw to avoid seams on some GPUs
        try:
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        except Exception:
            pass
        # Scrollbars auto-hide behavior
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setVisible(False)
        self.verticalScrollBar().setVisible(False)
        # Ensure the view never paints its own frame/border; keep viewport transparent
        self._base_qss = (
            "QGraphicsView { border: none; background: transparent; }\n"
            "QGraphicsView::viewport { background: transparent; border: none; }\n"
        )
        self._scrollbar_qss = (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {SCROLLBAR}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {SCROLLBAR}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )
        try:
            self.setStyleSheet(self._base_qss)
            self.viewport().setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass
        self._scrollbar_style_applied = False
        # State
        self._has_image = False
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 8.0
        self._emitted_first = False
        self._last_pix_size = QSize()
        self._pending_refit = False
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        # Enable pinch gesture across platforms
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

    def _build_scrollbar_qss(self, color: str) -> str:
        return (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )

    def set_theme(self, theme: dict[str, str]):
        bg_color = theme.get("BG", self._bg_color)
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception as e:
            APP_LOGGER.error(f"Error setting background brush in ZoomView: {e}")
        try:
            if self._scrollbar_style_applied:
                self.setStyleSheet(self._base_qss + self._scrollbar_qss)
            else:
                self.setStyleSheet(self._base_qss)
            self.viewport().setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass

    def set_image(self, pix: QPixmap):
        has_pix = hasattr(pix, "isNull") and not pix.isNull()
        size_changed = False
        if has_pix:
            new_size = pix.size()
            if new_size != self._last_pix_size:
                self._last_pix_size = QSize(new_size)
                size_changed = True
        else:
            self._last_pix_size = QSize()
        self._pix.setPixmap(pix)
        if not has_pix:
            self._has_image = False
            return
        needs_refit = False
        if self._pending_refit:
            needs_refit = True
        elif not self._has_image:
            needs_refit = True
        elif size_changed and abs(self._zoom - 1.0) < 1e-3:
            needs_refit = True
        self._has_image = True
        if needs_refit:
            self._refit_view()
        self._pending_refit = False
        # Emit firstFrame once, on the first real pixmap
        if not self._emitted_first and hasattr(pix, 'isNull') and not pix.isNull():
            self._emitted_first = True
            try:
                self.firstFrame.emit()
            except Exception:
                pass
        # Style thin scrollbars (once) without reintroducing a view border
        if not self._scrollbar_style_applied:
            try:
                self.setStyleSheet(self._base_qss + self._scrollbar_qss)
                self.viewport().setStyleSheet("background: transparent; border: none;")
            except Exception as e:
                APP_LOGGER.error(f"Error applying scrollbar style in ZoomView.set_image: {e}")
            self._scrollbar_style_applied = True

    def reset_first_frame(self):
        """Allow the next real pixmap to emit firstFrame again and refit view."""
        current = self._pix.pixmap()
        has_pix = hasattr(current, "isNull") and not current.isNull() if current is not None else False
        self._emitted_first = False
        self._pending_refit = True
        self._last_pix_size = QSize()
        if has_pix:
            self._has_image = True
        else:
            self._has_image = False
            try:
                self.resetTransform()
            except Exception as e:
                APP_LOGGER.error(f"Error resetting transform in ZoomView.reset_first_frame: {e}")
            self._zoom = 1.0

    def _zoom_by(self, factor: float):
        new_zoom = max(self._min_zoom, min(self._zoom * factor, self._max_zoom))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        real = new_zoom / self._zoom
        self.scale(real, real)
        self._zoom = new_zoom
        self._show_scrollbars_temporarily()

    def event(self, ev):
        # macOS: QNativeGestureEvent for pinch
        if ev.type() == QEvent.NativeGesture:
            try:
                # Some bindings expose gestureType/value on the event
                gtype = getattr(ev, 'gestureType', None)
                if callable(gtype):
                    gtype = gtype()
                val = getattr(ev, 'value', None)
                if callable(val):
                    val = val()
            except Exception as e:
                APP_LOGGER.error(f"Error processing NativeGesture in ZoomView.event: {e}")
                pass
        # Cross-platform: QPinchGesture via gesture events
        if ev.type() == QEvent.Gesture:
            try:
                pinch = ev.gesture(Qt.PinchGesture)
                if pinch is not None:
                    sf = getattr(pinch, 'scaleFactor', None)
                    if callable(sf):
                        sf = sf()
                    if sf:
                        self._zoom_by(float(sf))
                        ev.accept()
                        return True
            except Exception as e:
                APP_LOGGER.error(f"Error processing QEvent.Gesture in ZoomView.event: {e}")
                pass
        return super().event(ev)

    def wheelEvent(self, e):
        # Two-finger scroll pans the view; scrollbars are hidden
        try:
            dx = e.angleDelta().x()
            dy = e.angleDelta().y()
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            if h: h.setValue(h.value() - dx)
            if v: v.setValue(v.value() - dy)
            e.accept()
            self._show_scrollbars_temporarily()
            return
        except Exception:
            pass
        return super().wheelEvent(e)

    def mousePressEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mouseReleaseEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Keep initial fit; if user has zoomed, don't override
        if self._has_image and abs(self._zoom - 1.0) < 1e-3:
            self._refit_view()

    def _refit_view(self):
        try:
            self.fitInView(self._pix, Qt.KeepAspectRatio)
            self._zoom = 1.0
        except Exception:
            pass
    def drawForeground(self, painter: QPainter, rect):
        super().drawForeground(painter, rect)
        if not self._has_image:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QColor(SUBTXT))
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            text = "Video Preview"
            br = painter.boundingRect(rect, Qt.AlignCenter, text)
            painter.drawText(br, Qt.AlignCenter, text)
            painter.restore()
    def _show_scrollbars_temporarily(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(True)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(True)
            self._sb_timer.start(700)
        except Exception:
            pass

    def _hide_scrollbars(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(False)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(False)
        except Exception:
            pass

class AppZoomView(QGraphicsView):
    def __init__(self, bg_color: str = "#000", parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._proxy: QGraphicsProxyWidget | None = None
        self._content: QWidget | None = None
        self._base_size: QSize = QSize(0, 0)
        self._bg_color = bg_color
        # Visuals
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        try:
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        except Exception:
            pass
        try:
            self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        except Exception:
            pass
        # Scrollbars: thin, auto-hide
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setVisible(False)
        self.verticalScrollBar().setVisible(False)
        self._scrollbar_style = self._build_scrollbar_style(SCROLLBAR)
        self._apply_scrollbar_style()
        # State
        self._scale = 1.0
        self._min_scale = 1.0
        self._max_scale = 1.35
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        self._content_fits = True
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

    def _build_scrollbar_style(self, color: str) -> str:
        return (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )

    def _apply_scrollbar_style(self):
        try:
            self.setStyleSheet(self._scrollbar_style)
        except Exception:
            pass

    def set_theme(self, theme: dict[str, str]):
        bg_color = theme.get("BG", self._bg_color)
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self._bg_color = bg_color
        self._scrollbar_style = self._build_scrollbar_style(theme.get("SCROLLBAR", SCROLLBAR))
        self._apply_scrollbar_style()

    def set_content(self, w: QWidget):
        self._scene.clear()
        self._proxy = self._scene.addWidget(w)
        self._content = w
        self.resetTransform()
        self._scale = 1.0
        # Establish a fixed base content size to prevent reflow on zoom
        hint = w.sizeHint()
        if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
            hint = w.minimumSizeHint()
        if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
            hint = QSize(1200, 720)
        self._base_size = hint
        self._apply_geometry_to_proxy()
        self._update_interaction_state()

    def set_scale(self, s: float):
        s = max(self._min_scale, min(s, self._max_scale))
        self._scale = s
        self.resetTransform()
        self.scale(s, s)
        if s > 1.0 + 1e-3:
            self._show_scrollbars_temporarily()
        else:
            self._hide_scrollbars()
        self._update_interaction_state()

    def zoom_by(self, factor: float):
        self.set_scale(self._scale * factor)

    def event(self, ev):
        if ev.type() == QEvent.NativeGesture:
            try:
                gtype = getattr(ev, 'gestureType', None)
                if callable(gtype): gtype = gtype()
                val = getattr(ev, 'value', None)
                if callable(val): val = val()
                if gtype == Qt.NativeGestureType.Zoom and val is not None:
                    factor = 1.0 + (float(val) * 0.5)
                    factor = max(0.7, min(factor, 1.3))
                    self.zoom_by(factor)
                    ev.accept(); return True
            except Exception:
                pass
        if ev.type() == QEvent.Gesture:
            try:
                pinch = ev.gesture(Qt.PinchGesture)
                if pinch is not None:
                    sf = getattr(pinch, 'scaleFactor', None)
                    if callable(sf): sf = sf()
                    if sf:
                        self.zoom_by(float(sf))
                        ev.accept(); return True
            except Exception:
                pass
        return super().event(ev)

    def wheelEvent(self, e):
        # Two-finger scroll pans; reveal scrollbars temporarily
        try:
            h = self.horizontalScrollBar(); v = self.verticalScrollBar()
            has_scroll_range = ((h and h.maximum() > 0) or (v and v.maximum() > 0))
            if self._scale <= 1.0 + 1e-3 and not has_scroll_range:
                return super().wheelEvent(e)
            pd = e.pixelDelta(); ad = e.angleDelta()
            dx = pd.x() if not pd.isNull() else ad.x()
            dy = pd.y() if not pd.isNull() else ad.y()
            if h:
                h.setValue(h.value() - dx)
            if v:
                v.setValue(v.value() - dy)
            e.accept()
            self._show_scrollbars_temporarily()
            return
        except Exception:
            pass
        return super().wheelEvent(e)

    def _show_scrollbars_temporarily(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(True)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(True)
            if getattr(self, "_content_fits", True):
                self._sb_timer.start(700)
        except Exception:
            pass

    def _hide_scrollbars(self):
        try:
            if not getattr(self, "_content_fits", True):
                return
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(False)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(False)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Reflow content only when window resizes; pinch zoom does not trigger reflow
        self._apply_geometry_to_proxy()
        self._update_interaction_state()

    def _apply_geometry_to_proxy(self):
        try:
            if not self._proxy:
                return
            if not self._content or not self._proxy:
                return
            vp = self.viewport().size()
            # Always size the embedded content to the current viewport on resize
            hint = self._content.minimumSizeHint()
            if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
                hint = self._content.sizeHint()
            min_w = max(1, hint.width())
            min_h = max(1, hint.height())
            w = max(min_w, int(vp.width()))
            h = max(min_h, int(vp.height()))
            self._proxy.setPos(0, 0)
            self._proxy.resize(w, h)
            self._scene.setSceneRect(0, 0, w, h)
        except Exception:
            pass

    def _update_interaction_state(self):
        try:
            vp = self.viewport().size()
            sr = self._scene.sceneRect()
            fits_w = sr.width() <= vp.width() + 0.5
            fits_h = sr.height() <= vp.height() + 0.5
            content_fits = fits_w and fits_h
            self._content_fits = content_fits
            if self._scale <= 1.0 + 1e-3 and content_fits:
                self.setDragMode(QGraphicsView.NoDrag)
                if self.horizontalScrollBar():
                    self.horizontalScrollBar().setRange(0, 0)
                    self.horizontalScrollBar().setVisible(False)
                if self.verticalScrollBar():
                    self.verticalScrollBar().setRange(0, 0)
                    self.verticalScrollBar().setVisible(False)
            else:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                if self.horizontalScrollBar():
                    self.horizontalScrollBar().setVisible(True)
                if self.verticalScrollBar():
                    self.verticalScrollBar().setVisible(True)
        except Exception:
            pass

class PinnedPreviewWindow(QWidget):
    """Floating always-on-top preview window."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NEMESIS Preview — Pop-out")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = ZoomView(bg_color=BG)
        self.container = AspectRatioContainer(self.view, 16, 9)
        layout.addWidget(self.container)
        self.resize(420, 236)

    def set_theme(self, theme: dict[str, str]):
        try:
            self.view.set_theme(theme)
        except Exception:
            pass
        try:
            self.container.set_theme(theme)
        except Exception:
            pass

    def set_pixmap(self, pixmap: QPixmap):
        self.view.set_image(pixmap)

    def set_aspect(self, w: int, h: int):
        self.container.set_aspect(w, h)

    def set_border_visible(self, on: bool):
        self.container.set_border_visible(on)

    def reset_first_frame(self):
        self.view.reset_first_frame()

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)
