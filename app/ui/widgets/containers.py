# app/ui/widgets/containers.py
from PySide6.QtWidgets import QWidget, QSizePolicy, QTabBar, QStylePainter, QStyleOptionTab, QStyle
from PySide6.QtCore import QSize, Qt, QRect, QPoint
from PySide6.QtGui import QIcon, QPalette
from app.ui.theme import BG, BORDER, active_theme

class AspectRatioContainer(QWidget):
    """Container that keeps a child at a fixed aspect ratio and only uses the
    height it needs for the current width (no wasted vertical space)."""
    def __init__(self, child: QWidget, ratio_w: int = 16, ratio_h: int = 9, parent=None):
        super().__init__(parent)
        self._child = child
        self._ratio_w = max(1, int(ratio_w))
        self._ratio_h = max(1, int(ratio_h))
        self._child.setParent(self)
        # Tell the layout system we compute height from width.
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        # Container draws its own border to avoid halos (match preview box styling)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._border_px = 1
        self._show_border = True
        self._apply_border_style()
        # Reasonable floor so it never collapses
        self.setMinimumSize(480, 270)

    # --- Qt "height-for-width" plumbing ---
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w: int) -> int:
        return max(self.minimumHeight(), int(w * self._ratio_h / self._ratio_w))

    def sizeHint(self) -> QSize:
        # Width-driven; height will be computed via heightForWidth
        base_w = 720
        return QSize(base_w, self.heightForWidth(base_w))

    def set_aspect(self, w: int, h: int):
        try:
            w = int(w); h = int(h)
        except Exception:
            return
        if w > 0 and h > 0:
            self._ratio_w, self._ratio_h = w, h
            self.updateGeometry()

    def aspect_ratio(self) -> tuple[int, int]:
        return self._ratio_w, self._ratio_h

    def _apply_border_style(self, theme: dict[str, str] | None = None):
        palette = theme or active_theme()
        border_color = palette.get("BORDER", BORDER)
        bg = palette.get("BG", BG)
        border = f"{self._border_px}px solid {border_color}" if self._show_border else "none"
        self.setStyleSheet(f"background: {bg}; border: {border};")

    def set_border_visible(self, on: bool):
        self._show_border = bool(on)
        self._apply_border_style()
        # Relayout to account for changed effective border width
        try:
            self.updateGeometry()
        except Exception:
            pass
        self.update()

    def set_theme(self, theme: dict[str, str]):
        self._apply_border_style(theme)

    def border_visible(self) -> bool:
        return bool(getattr(self, "_show_border", True))

    def resizeEvent(self, e):
        # Fit child to inner rect inside border; if border hidden, don't subtract it
        b = self._border_px if getattr(self, "_show_border", True) else 0
        outer_w = self.width(); outer_h = self.height()
        W = max(1, outer_w - 2*b)
        H = max(1, outer_h - 2*b)
        target_w = W
        target_h = int(W * self._ratio_h / self._ratio_w)
        if target_h > H:
            target_h = H
            target_w = int(H * self._ratio_w / self._ratio_h)
        x = b + (W - target_w) // 2
        y = b + (H - target_h) // 2
        self._child.setGeometry(x, y, target_w, target_h)
        super().resizeEvent(e)


class LeftAlignTabBar(QTabBar):
    """Tab bar that left-aligns text and applies consistent padding."""

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        size.setWidth(max(size.width(), 160))
        return size

    def paintEvent(self, event):
        painter = QStylePainter(self)
        for index in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, index)
            opt.rect = self.tabRect(index)
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)

            text_rect = opt.rect.adjusted(12, 0, -12, 0)
            painter.save()
            role = QPalette.ButtonText if opt.state & QStyle.State_Selected else QPalette.WindowText
            painter.setPen(opt.palette.color(role))
            alignment = Qt.AlignVCenter | Qt.AlignLeft
            offset = 0
            if not opt.icon.isNull():
                icon_size = opt.iconSize if not opt.iconSize.isEmpty() else QSize(16, 16)
                icon_rect = QRect(text_rect.left(), text_rect.center().y() - icon_size.height() // 2, icon_size.width(), icon_size.height())
                opt.icon.paint(painter, icon_rect, Qt.AlignLeft | Qt.AlignVCenter,
                               QIcon.Active if opt.state & QStyle.State_Selected else QIcon.Normal,
                               QIcon.On if opt.state & QStyle.State_Selected else QIcon.Off)
                offset = icon_rect.width() + 6
            painter.drawText(text_rect.adjusted(offset, 0, 0, 0), alignment, opt.text)
            painter.restore()
