#!/usr/bin/env python3
import sys
import os
import base64
import platform
import collections
import json
import math
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QTextEdit, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QTextBrowser, QLineEdit, QLabel, QScrollArea,
    QInputDialog, QMenu, QFileDialog, QMessageBox, QListWidgetItem, QToolBar,
    QSizePolicy, QStyleOption, QStyle, QDialog, QDialogButtonBox, QStackedWidget,
    QCalendarWidget, QFormLayout, QSpinBox, QComboBox, QCheckBox, QPushButton
)
from PySide6.QtGui import QColor, QPalette, QAction, QFont, QPainter, QTextCharFormat, QPen, QIcon
from PySide6.QtCore import Qt, QTimer, QSize, QObject, Signal, QEvent, QDate

import markdown2

# Project modules
from crypto import CryptoManager
from database import DatabaseManager
from models import Entry
from utils import encrypt_image_to_file, decrypt_image_from_file

# ---------------- Constants ----------------
APP_TITLE = "Modern Diary"
SALT_FILE = "Data/salt.bin"
VERIFY_FILE = "Data/verify.bin"
CONFIG_FILE = "Data/config.json"
IMAGE_FOLDER = "Data/images"
AUTOSAVE_INTERVAL_MS = 4000
PREVIEW_DEBOUNCE_MS = 150

MARKDOWN_EXTRAS = [
    "fenced-code-blocks", "code-friendly", "tables", "strike", "task_list",
    "cuddled-lists", "footnotes", "header-ids", "wiki-tables", "break-on-newline", "nofollow"
]

try:
    with open("resources/style/style1.css", "r", encoding="utf-8") as f:
        MARKDOWN_CSS = f.read()
except FileNotFoundError:
    MARKDOWN_CSS = "body { color: #ECEFF4; font-family: sans-serif; }"

# Tag chip styles
TAG_STYLE_NORMAL = """
    QLabel { background: rgba(255,255,255,0.05); color: #ECEFF4; padding: 6px 12px; border: 1px solid rgba(255,255,255,0.1); border-radius: 14px; font-size: 12px; }
    QLabel:hover { background: rgba(136,192,208,0.3); border-color: rgba(136,192,208,0.8); }
"""
TAG_STYLE_ACTIVE = """
    QLabel { background: rgba(180, 142, 173, 0.6); color: white; padding: 6px 12px; border: 1px solid #B48EAD; border-radius: 14px; font-size: 12px; font-weight: bold; }
    QLabel:hover { background: rgba(180, 142, 173, 0.8); }
"""

SCROLLBAR_CSS = """
    QScrollBar:vertical { border: none; background: transparent; width: 6px; margin: 0px; }
    QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.2); border-radius: 3px; min-height: 20px; }
    QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.4); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar:horizontal { border: none; background: transparent; height: 6px; margin: 0px; }
    QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 0.2); border-radius: 3px; min-width: 20px; }
    QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 0.4); }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
"""

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"lock_enabled": True, "lock_val": 5, "lock_unit": "Minutes", "show_stats": True}

def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def enable_windows_blur(win_id) -> None:
    if platform.system().lower() != "windows":
        return
    try:
        import ctypes
        from ctypes import wintypes
        
        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int)
            ]
            
        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)
            ]
            
        user32 = ctypes.windll.user32
        setWindowCompositionAttribute = user32.SetWindowCompositionAttribute
        setWindowCompositionAttribute.restype = wintypes.BOOL
        
        def apply(accent_state: int):
            accent = ACCENTPOLICY()
            accent.AccentState, accent.GradientColor = accent_state, 0xCC222222
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute, data.SizeOfData, data.Data = 19, ctypes.sizeof(accent), ctypes.addressof(accent)
            return setWindowCompositionAttribute(wintypes.HWND(int(win_id)), ctypes.byref(data))
            
        if not apply(4):
            apply(3)
    except Exception:
        pass

class ActivityFilter(QObject):
    activity_occurred = Signal()
    
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.KeyPress, QEvent.MouseMove, QEvent.MouseButtonPress):
            self.activity_occurred.emit()
        return super().eventFilter(obj, event)

# ---------- Custom UI Elements ----------
class FlowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def add_widget(self, widget):
        self._items.append(widget)
        widget.setParent(self)
        widget.show()
        self._do_layout()

    def clear(self):
        for w in self._items:
            w.setParent(None)
            w.deleteLater()
        self._items.clear()
        self._do_layout()

    def resizeEvent(self, event):
        self._do_layout()
        super().resizeEvent(event)

    def _do_layout(self):
        x, y, max_h = 0, 0, 0
        spacing = 8
        width = self.width() if self.width() > 0 else 200
        for w in self._items:
            w.adjustSize()
            if x + w.width() > width and x > 0:
                x, y, max_h = 0, y + max_h + spacing, 0
            w.move(x, y)
            x += w.width() + spacing
            max_h = max(max_h, w.height())
        self.setMinimumHeight(y + max_h)

class GlassPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("GlassPanel { background: rgba(30, 32, 36, 0.35); border: 1px solid rgba(255,255,255,0.08); border-top: 1px solid rgba(255,255,255,0.15); border-radius: 16px; }")
        
    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)

class StatBox(GlassPanel):
    def __init__(self, title: str, value: str, icon: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(65)
        self.setMaximumHeight(80)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(15)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 24px; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setAlignment(Qt.AlignVCenter)
        
        self.val_lbl = QLabel(str(value))
        self.val_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ECEFF4; background: transparent;")
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #88C0D0; background: transparent; text-transform: uppercase; letter-spacing: 1px;")
        
        text_layout.addWidget(self.val_lbl)
        text_layout.addWidget(title_lbl)

        layout.addWidget(icon_lbl)
        layout.addLayout(text_layout)
        layout.addStretch()

    def update_value(self, new_val):
        self.val_lbl.setText(str(new_val))

class TimelineHeatmap(QWidget):
    dateClicked = Signal(QDate)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMaximumHeight(140)
        self.setMouseTracking(True)
        self.counts = {}
        self.selected_date = None
        self.hovered_date = None
        self.x_offset = 35
        self.y_offset = 30
        self._recalculate_dates()

    def _recalculate_dates(self):
        self.today = QDate.currentDate()
        self.start_date = self.today.addDays(-364)
        while self.start_date.dayOfWeek() != 7:
            self.start_date = self.start_date.addDays(-1)

    def set_data(self, entries: List[dict]):
        self._recalculate_dates()
        self.counts.clear()
        for r in entries:
            d_str = r.get("created_at") or r.get("updated_at")
            if d_str:
                try:
                    dt = datetime.strptime(str(d_str).split(".")[0].replace("T", " ").replace("Z", ""), "%Y-%m-%d %H:%M:%S")
                    qdate = QDate(dt.year, dt.month, dt.day)
                    self.counts[qdate] = self.counts.get(qdate, 0) + 1
                except Exception:
                    pass
        self.update()

    def set_selected_date(self, date: QDate):
        self.selected_date = date
        self.update()

    def _get_date_at_pos(self, pos) -> Optional[QDate]:
        avail_w, avail_h = self.width() - self.x_offset - 10, self.height() - self.y_offset - 10
        if avail_w <= 0 or avail_h <= 0:
            return None
        
        step = max(4, min(avail_w / 53.0, avail_h / 7.0))
        dynamic_x = max(self.x_offset, (self.width() - (53 * step)) / 2)
        col, row = int((pos.x() - dynamic_x) // step), int((pos.y() - self.y_offset) // step)
        
        if 0 <= col < 53 and 0 <= row < 7:
            target = self.start_date.addDays(col * 7 + row)
            if target <= self.today:
                return target
        return None

    def mouseMoveEvent(self, event):
        date = self._get_date_at_pos(event.position().toPoint())
        if date != self.hovered_date:
            self.hovered_date = date
            if date:
                self.setToolTip(f"{date.toString('MMM d, yyyy')}\n{self.counts.get(date, 0)} entries")
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setToolTip("")
                self.setCursor(Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        date = self._get_date_at_pos(event.position().toPoint())
        if date:
            self.selected_date = date
            self.dateClicked.emit(date)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        avail_w, avail_h = self.width() - self.x_offset - 10, self.height() - self.y_offset - 10
        step = max(4, min(avail_w / 53.0, avail_h / 7.0)) 
        cell_size = step * 0.75 
        dynamic_x = max(self.x_offset, (self.width() - (53 * step)) / 2)
        
        painter.setPen(QColor(236, 239, 244, 130))
        painter.setFont(QFont("Segoe UI", 8))
        
        text_x = dynamic_x - 30
        painter.drawText(int(text_x), int(self.y_offset + 1 * step + cell_size), "Mon")
        painter.drawText(int(text_x), int(self.y_offset + 3 * step + cell_size), "Wed")
        painter.drawText(int(text_x), int(self.y_offset + 5 * step + cell_size), "Fri")

        current_month = -1
        for i in range(53 * 7):
            current_date = self.start_date.addDays(i)
            if current_date > self.today:
                break
                
            col, row = i // 7, i % 7
            x, y = dynamic_x + col * step, self.y_offset + row * step

            if row == 0 and current_date.month() != current_month:
                current_month = current_date.month()
                if col > 1:
                    painter.setPen(QColor(236, 239, 244, 180))
                    painter.drawText(int(x), self.y_offset - 8, current_date.toString("MMM"))

            count = self.counts.get(current_date, 0)
            color = QColor(255, 255, 255, 12) if count == 0 else QColor(136, 192, 208, min(255, 60 + count * 50))
            
            pen = QPen(Qt.NoPen)
            if current_date == self.selected_date:
                pen = QPen(QColor(236, 239, 244, 255), max(1, cell_size * 0.1))
            elif current_date == self.hovered_date:
                color = color.lighter(130)
                pen = QPen(QColor(255, 255, 255, 100), 1)

            painter.setPen(pen)
            painter.setBrush(color)
            painter.drawRoundedRect(int(x), int(y), int(cell_size), int(cell_size), max(1, int(cell_size * 0.2)), max(1, int(cell_size * 0.2)))

# ---------- Dialogs ----------
class GlassInputDialog(QDialog):
    """Beautiful Custom Input Dialog replacing QInputDialog"""
    def __init__(self, title_text, label_text, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(340, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.panel = GlassPanel(self)
        self.panel.setStyleSheet("""
            GlassPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(43, 35, 51, 0.96), stop:1 rgba(20, 22, 26, 0.98));
            border: 1px solid rgba(255, 255, 255, 0.08); border-top: 1px solid rgba(136, 192, 208, 0.6); border-radius: 16px; }
        """)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(25, 25, 25, 25)

        title = QLabel(title_text)
        title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 32px; color: #88C0D0; background: transparent; margin-bottom: 5px;")
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(label_text)
        self.input_field.setStyleSheet("QLineEdit { background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 12px; color: #ECEFF4; font-size: 14px; } QLineEdit:focus { border: 1px solid rgba(136, 192, 208, 0.8); background: rgba(0, 0, 0, 0.6); }")
        panel_layout.addWidget(self.input_field)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 15, 0, 0)
        
        btn_cancel = QPushButton("Cancel")
        btn_ok = QPushButton("OK")

        btn_style = "QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px; color: #ECEFF4; font-weight: bold; text-transform: uppercase; } QPushButton:hover { background: rgba(136, 192, 208, 0.2); border-color: #88C0D0; color: #88C0D0; }"
        btn_cancel.setStyleSheet(btn_style)
        btn_ok.setStyleSheet(btn_style)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self.accept)
        self.input_field.returnPressed.connect(self.accept)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        panel_layout.addLayout(btn_layout)

        layout.addWidget(self.panel)

    def get_text(self):
        return self.input_field.text()

class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(400, 520)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.panel = GlassPanel(self)
        self.panel.setStyleSheet("""
            GlassPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(43, 35, 51, 0.96), stop:1 rgba(20, 22, 26, 0.98));
            border: 1px solid rgba(255, 255, 255, 0.08); border-top: 1px solid rgba(136, 192, 208, 0.6); border-radius: 16px; }
        """)

        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("Keyboard Shortcuts")
        title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 38px; color: #88C0D0; background: transparent; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)

        shortcuts = [
            ("Ctrl + N", "New Entry"),
            ("Ctrl + S", "Save Entry"),
            ("Del", "Delete Selected Entry"),
            ("Ctrl + F", "Focus Search Bar"),
            ("Ctrl + T", "Add New Tag"),
            ("Ctrl + B", "Toggle Sidebar Pane"),
            ("Ctrl + E", "Toggle Editor/Preview View"),
            ("F11", "Toggle Focus Mode (Fullscreen)"),
            ("F10", "Toggle Ribbon (Toolbar)"),
            ("F1", "Show Help Menu")
        ]

        form = QFormLayout()
        form.setSpacing(12)
        
        for key, desc in shortcuts:
            lbl_key = QLabel(key)
            lbl_key.setStyleSheet("color: #EBCB8B; font-weight: bold; font-family: 'Consolas', monospace; font-size: 13px; background: rgba(255,255,255,0.05); padding: 4px 8px; border-radius: 4px;")
            lbl_desc = QLabel(desc)
            lbl_desc.setStyleSheet("color: #ECEFF4; font-size: 14px; font-family: 'Segoe UI'; margin-left: 10px;")
            form.addRow(lbl_key, lbl_desc)

        panel_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 20, 0, 0)
        btn_close = QPushButton("Got it")
        btn_close.setStyleSheet("QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px; color: #ECEFF4; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; } QPushButton:hover { background: rgba(136, 192, 208, 0.2); border-color: #88C0D0; color: #88C0D0; }")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        
        panel_layout.addLayout(btn_layout)
        layout.addWidget(self.panel)

class SettingsDialog(QDialog):
    def __init__(self, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(360, 400)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.panel = GlassPanel(self)
        self.panel.setStyleSheet("""
            GlassPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(43, 35, 51, 0.96), stop:1 rgba(20, 22, 26, 0.98));  
            border: 1px solid rgba(255, 255, 255, 0.08); border-top: 1px solid rgba(136, 192, 208, 0.6); border-radius: 16px; }
        """)
        
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("Preferences")
        title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 38px; color: #88C0D0; background: transparent; margin-bottom: 20px;")
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(15)

        self.enable_lock_cb = QCheckBox("Enable Auto-Lock")
        self.enable_lock_cb.setChecked(current_config.get("lock_enabled", True))
        self.enable_lock_cb.setStyleSheet("color: #ECEFF4; font-size: 14px; background: transparent;")

        self.show_stats_cb = QCheckBox("Show Live Word Count")
        self.show_stats_cb.setChecked(current_config.get("show_stats", True))
        self.show_stats_cb.setStyleSheet("color: #ECEFF4; font-size: 14px; background: transparent;")
        
        spin_style = "QSpinBox, QComboBox { background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 6px; color: #ECEFF4; font-size: 13px; }"
        self.val_spinbox = QSpinBox()
        self.val_spinbox.setRange(1, 1000)
        self.val_spinbox.setValue(current_config.get("lock_val", 5))
        self.val_spinbox.setStyleSheet(spin_style)
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Seconds", "Minutes"])
        self.unit_combo.setCurrentText(current_config.get("lock_unit", "Minutes"))
        self.unit_combo.setStyleSheet(spin_style)

        lbl1 = QLabel("Timeout:")
        lbl1.setStyleSheet("color: #81A1C1; font-size: 13px; background: transparent;")
        
        lbl2 = QLabel("Unit:")
        lbl2.setStyleSheet("color: #81A1C1; font-size: 13px; background: transparent;")

        form.addRow(self.enable_lock_cb)
        form.addRow(self.show_stats_cb)
        form.addRow(lbl1, self.val_spinbox)
        form.addRow(lbl2, self.unit_combo)
        panel_layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 20, 0, 0)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_save = QPushButton("Save")
        
        btn_style = "QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 10px; color: #ECEFF4; font-weight: bold; text-transform: uppercase; } QPushButton:hover { background: rgba(136, 192, 208, 0.2); border-color: #88C0D0; color: #88C0D0; }"
        self.btn_cancel.setStyleSheet(btn_style)
        self.btn_save.setStyleSheet(btn_style)
        
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        panel_layout.addLayout(btn_layout)
        layout.addWidget(self.panel)

    def get_config(self) -> dict:
        return {
            "lock_enabled": self.enable_lock_cb.isChecked(),
            "lock_val": self.val_spinbox.value(),
            "lock_unit": self.unit_combo.currentText(),
            "show_stats": self.show_stats_cb.isChecked()
        }

class UnlockDialog(QDialog):
    def __init__(self, parent=None, is_startup=True):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(380, 360) 
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.panel = GlassPanel(self)
        self.panel.setStyleSheet("""
            GlassPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(43, 35, 51, 0.96), stop:0.5 rgba(35, 45, 55, 0.92), stop:1 rgba(20, 22, 26, 0.98));  
            border: 1px solid rgba(255, 255, 255, 0.08); border-top: 1px solid rgba(180, 142, 173, 0.6); border-left: 1px solid rgba(136, 192, 208, 0.4); border-radius: 16px; }
        """)
        
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(35, 40, 35, 40)
        panel_layout.setAlignment(Qt.AlignCenter)
        panel_layout.setSpacing(15)
        
        title_text = "Welcome Back" if is_startup else "Authentication"
        title = QLabel(title_text)
        title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 46px; color: #ECEFF4; background: transparent; margin-bottom: -5px;")
        title.setAlignment(Qt.AlignCenter)

        subtitle_text = "Please enter your master key" if is_startup else "The application is currently locked"
        subtitle = QLabel(subtitle_text)
        subtitle.setStyleSheet("font-family: 'Segoe UI', sans-serif; font-size: 12px; color: #81A1C1; background: transparent; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 20px;")
        subtitle.setAlignment(Qt.AlignCenter)
        
        self.pw_input = QLineEdit()
        self.pw_input.setEchoMode(QLineEdit.Password)
        self.pw_input.setPlaceholderText("Master Password")
        self.pw_input.setAlignment(Qt.AlignCenter)
        self.pw_input.setStyleSheet("QLineEdit { background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 14px; color: #ECEFF4; font-size: 15px; letter-spacing: 4px; } QLineEdit:focus { border: 1px solid rgba(136, 192, 208, 0.8); background: rgba(0, 0, 0, 0.6); }")
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_layout.setContentsMargins(0, 15, 0, 0)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_unlock = QPushButton("Unlock")
        
        btn_style = "QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; padding: 12px; color: #ECEFF4; font-weight: bold; font-size: 13px; text-transform: uppercase; } QPushButton:pressed { background: rgba(0, 0, 0, 0.3); }"
        self.btn_cancel.setStyleSheet(btn_style + "QPushButton:hover { background: rgba(255, 255, 255, 0.1); color: #D8DEE9; }")
        self.btn_unlock.setStyleSheet(btn_style + "QPushButton:hover { background: rgba(136, 192, 208, 0.2); border-color: #88C0D0; color: #88C0D0; }")
        
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_unlock.clicked.connect(self.accept)
        self.pw_input.returnPressed.connect(self.btn_unlock.click)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_unlock)
        
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)
        panel_layout.addWidget(self.pw_input)
        panel_layout.addLayout(btn_layout)
        layout.addWidget(self.panel)
        
    def get_password(self):
        return self.pw_input.text()

class EditTagsDialog(QDialog):
    def __init__(self, current_tags: List[str], parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(340, 440)
        self.final_tags = list(current_tags)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.panel = GlassPanel(self)
        self.panel.setStyleSheet("""
            GlassPanel { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(43, 35, 51, 0.96), stop:1 rgba(20, 22, 26, 0.98));  
            border: 1px solid rgba(255, 255, 255, 0.08); border-top: 1px solid rgba(180, 142, 173, 0.6); border-radius: 16px; }
        """)
        
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(25, 25, 25, 25)
        
        title = QLabel("Edit Entry Tags")
        title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 34px; color: #B48EAD; background: transparent; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(title)

        self.listw = QListWidget()
        self.listw.setStyleSheet(f"""
            QListWidget {{ background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; color: #ECEFF4; padding: 5px; outline: none; }}
            QListWidget::item {{ padding: 8px; border-radius: 4px; }}
            QListWidget::item:selected {{ background: rgba(180, 142, 173, 0.4); }}
            {SCROLLBAR_CSS}
        """)
        for t in self.final_tags:
            self.listw.addItem(t)
            
        panel_layout.addWidget(self.listw)

        btn_style = "QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 6px; padding: 6px; color: #ECEFF4; font-weight: bold; } QPushButton:hover { background: rgba(180, 142, 173, 0.3); border-color: #B48EAD; color: white; }"

        controls_layout = QHBoxLayout()
        btn_add = QPushButton("Add")
        btn_edit = QPushButton("Edit")
        btn_remove = QPushButton("Remove")
        
        for b in (btn_add, btn_edit, btn_remove):
            b.setStyleSheet(btn_style)
            
        controls_layout.addWidget(btn_add)
        controls_layout.addWidget(btn_edit)
        controls_layout.addWidget(btn_remove)
        panel_layout.addLayout(controls_layout)

        def on_add():
            dlg = GlassInputDialog("Add Tag", "Tag name...", self)
            if dlg.exec() == QDialog.Accepted and (tt := dlg.get_text().strip()) and tt not in [self.listw.item(i).text() for i in range(self.listw.count())]:
                self.listw.addItem(tt)
                
        def on_edit():
            if self.listw.currentItem():
                dlg = GlassInputDialog("Edit Tag", "Tag name...", self)
                dlg.input_field.setText(self.listw.currentItem().text())
                if dlg.exec() == QDialog.Accepted and (t := dlg.get_text().strip()):
                    self.listw.currentItem().setText(t)
                    
        def on_remove():
            if self.listw.currentItem():
                self.listw.takeItem(self.listw.row(self.listw.currentItem()))

        btn_add.clicked.connect(on_add)
        btn_edit.clicked.connect(on_edit)
        btn_remove.clicked.connect(on_remove)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 15, 0, 0)
        
        btn_cancel = QPushButton("Cancel")
        btn_save = QPushButton("Save Tags")
        
        btn_cancel.setStyleSheet(btn_style)
        btn_save.setStyleSheet(btn_style.replace("#B48EAD", "#88C0D0"))
        
        btn_cancel.clicked.connect(self.reject)
        
        def save_and_close():
            self.final_tags = [self.listw.item(i).text() for i in range(self.listw.count())]
            self.accept()
            
        btn_save.clicked.connect(save_and_close)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        panel_layout.addLayout(btn_layout)
        layout.addWidget(self.panel)

class EntryCard(QWidget):
    def __init__(self, title: str, updated: str, tags: Optional[List[str]] = None, category_name: Optional[str] = None):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Dynamic Magical Glass Highlighting across the entire card
        if category_name:
            glass_themes = [
                ("rgba(191, 97, 106, 0.25)", "rgba(191, 97, 106, 0.05)", "rgba(191, 97, 106, 0.5)"), # Red
                ("rgba(208, 135, 112, 0.25)", "rgba(208, 135, 112, 0.05)", "rgba(208, 135, 112, 0.5)"), # Orange
                ("rgba(235, 203, 139, 0.25)", "rgba(235, 203, 139, 0.05)", "rgba(235, 203, 139, 0.5)"), # Yellow
                ("rgba(163, 190, 140, 0.25)", "rgba(163, 190, 140, 0.05)", "rgba(163, 190, 140, 0.5)"), # Green
                ("rgba(180, 142, 173, 0.25)", "rgba(180, 142, 173, 0.05)", "rgba(180, 142, 173, 0.5)"), # Purple
                ("rgba(136, 192, 208, 0.25)", "rgba(136, 192, 208, 0.05)", "rgba(136, 192, 208, 0.5)"), # Cyan
                ("rgba(129, 161, 193, 0.25)", "rgba(129, 161, 193, 0.05)", "rgba(129, 161, 193, 0.5)")  # Blue
            ]
            theme = glass_themes[len(category_name) % len(glass_themes)]
            
            self.setStyleSheet(f"""
                EntryCard {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {theme[0]}, stop:1 {theme[1]});
                    border: 1px solid {theme[2]};
                    border-top: 1px solid rgba(255,255,255,0.2);
                    border-left: 1px solid rgba(255,255,255,0.1);
                    border-radius: 12px;
                }}
            """)
        else:
            self.setStyleSheet("EntryCard { background: transparent; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)

        self.title_lbl = QLabel()
        tfont = QFont()
        tfont.setBold(True)
        tfont.setPointSize(11)
        self.title_lbl.setFont(tfont)
        self.title_lbl.setStyleSheet("color: #ECEFF4; background: transparent; border: none;")
        
        raw_title = title or "Untitled"
        metrics = self.title_lbl.fontMetrics()
        self.title_lbl.setText(metrics.elidedText(raw_title, Qt.TextElideMode.ElideRight, 220))
        self.title_lbl.setToolTip(raw_title)
        root.addWidget(self.title_lbl)

        date_lbl = QLabel(updated or "—")
        date_lbl.setStyleSheet("color: rgba(236,239,244,0.5); font-size: 11px; background: transparent; border: none;")
        root.addWidget(date_lbl)

        if tags:
            raw_tags = " • ".join(tags)
            tags_lbl = QLabel()
            tags_lbl.setStyleSheet("color: #88C0D0; font-size: 10px; background: transparent; border: none;")
            tags_lbl.setText(tags_lbl.fontMetrics().elidedText(raw_tags, Qt.TextElideMode.ElideRight, 220))
            tags_lbl.setToolTip(raw_tags)
            root.addWidget(tags_lbl)

class TagChip(QLabel):
    def __init__(self, text: str, on_click, on_right_click):
        super().__init__(text)
        self._text = text
        self._on_click = on_click
        self._on_right_click = on_right_click
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click(self._text)
        elif event.button() == Qt.RightButton:
            self._on_right_click(self._text, event.globalPosition().toPoint())

# ---------------- Main Application ----------------
class DiaryApp(QMainWindow):
    def __init__(self, crypto: CryptoManager, db: DatabaseManager):
        super().__init__()
        self.crypto = crypto
        self.db = db

        self.app_config = load_config()
        self.current_entry: Optional[Entry] = None
        self.entry_images: Dict[str, Tuple[str, bytes, str]] = {}
        self.active_tags: set[str] = set()
        self.entries_cache: List[dict] = []
        self.formatted_dates: List[QDate] = []
        self.sort_desc: bool = True
        self.focus_mode: bool = False
        self.view_mode: int = 0  # 0: Split, 1: Editor Only, 2: Preview Only
        self.active_folder_name = None 
        
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 900)
        self.setWindowIcon(QIcon("resources/icons/icon.png")) 

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")

        self._build_ui()
        self._build_toolbar()
        self._setup_timers()
        self._setup_menus()

        self._cleanup_orphaned_images() 
        self._update_folder_list()
        self.load_tags()
        self.load_entries(keep_selection=False)
        enable_windows_blur(self.winId())

    def _cleanup_orphaned_images(self):
        # Disabled entirely to ensure the app never deletes images
        pass

    # ---------- UI ----------
    def _build_ui(self):
        self.outer = QWidget() 
        self.outer.setStyleSheet("background: transparent;")
        
        self.setCentralWidget(self.outer)
        outer_layout = QHBoxLayout(self.outer)
        outer_layout.setContentsMargins(14, 14, 14, 14)
        outer_layout.setSpacing(14)

        # ---------------- SIDEBAR ----------------
        self.sidebar = GlassPanel()
        outer_layout.addWidget(self.sidebar, 3)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(10)

        side.addWidget(QLabel("<b style='color:#E5E9F0;'>Quick Tags</b>"))
        self.tag_scroll = QScrollArea(widgetResizable=True)
        self.tag_scroll.setFrameShape(QScrollArea.NoFrame)
        self.tag_scroll.setStyleSheet(f"QScrollArea {{ background: transparent; }} {SCROLLBAR_CSS}")
        self.tag_scroll.setFixedHeight(85) 
        
        self.tag_holder = FlowWidget()
        self.tag_scroll.setWidget(self.tag_holder)
        side.addWidget(self.tag_scroll, 0)

        self.search_bar = QLineEdit(placeholderText="Search your thoughts...")
        self.search_bar.setStyleSheet("QLineEdit { background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.10); border-radius: 12px; padding: 10px 12px; color: #E5E9F0; font-size: 13px; } QLineEdit:focus { border-color: rgba(136,192,208,.6); background: rgba(255,255,255,.08); }")
        self.search_bar.textChanged.connect(self.search_entries)
        side.addWidget(self.search_bar)

        self.entry_list = QListWidget()
        self.entry_list.setFrameShape(QListWidget.NoFrame)
        self.entry_list.setSpacing(8)
        self.entry_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.entry_list.viewport().setStyleSheet("background: transparent;")
        self.entry_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; outline: none; border: none; }}
            QListWidget::item {{ border-radius: 12px; margin-bottom: 4px; }}
            QListWidget::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(180, 142, 173, 0.35), stop:0.5 rgba(255, 255, 255, 0.20), stop:1 rgba(136, 192, 208, 0.35)); border: 1px solid rgba(180, 142, 173, 0.4); border-top: 1px solid rgba(255, 255, 255, 0.5); border-left: 1px solid rgba(255, 255, 255, 0.3); }}
            QListWidget::item:hover:!selected {{ background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.05); }}
            {SCROLLBAR_CSS}
        """)
        self.entry_list.itemClicked.connect(self._on_list_item_clicked)
        side.addWidget(self.entry_list, 1)

        # ---------------- RIGHT STACK ----------------
        self.right_stack = QStackedWidget()
        outer_layout.addWidget(self.right_stack, 7)

        self.empty_widget = GlassPanel()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        
        empty_box = QWidget()
        eb_layout = QVBoxLayout(empty_box)
        eb_layout.setAlignment(Qt.AlignCenter)
        eb_layout.setSpacing(10)
        
        empty_title = QLabel("Ready to write?")
        empty_title.setStyleSheet("font-family: 'Dancing Script', cursive; font-size: 42px; color: #E5E9F0;")
        
        empty_lbl = QLabel("Select an entry from the list or start a new one.")
        empty_lbl.setStyleSheet("color: #81A1C1; font-size: 14px; letter-spacing: 0.5px;")
        
        eb_layout.addWidget(empty_title, alignment=Qt.AlignCenter)
        eb_layout.addWidget(empty_lbl, alignment=Qt.AlignCenter)
        empty_layout.addWidget(empty_box)
        self.right_stack.addWidget(self.empty_widget)

        self.editor_widget = GlassPanel()
        editor_layout = QVBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(12, 12, 12, 12)
        
        self.splitter = QSplitter(Qt.Horizontal) 

        self.text_editor = QTextEdit()
        self.text_editor.setPlaceholderText("# Title\n\nCapture your thoughts here...")
        self.text_editor.setStyleSheet(f"QTextEdit {{ background: rgba(20, 22, 26, 0.4); border: 1px solid rgba(255,255,255,.05); border-radius: 12px; padding: 20px; selection-background-color: rgba(180, 142, 173, 0.4); color: #ECEFF4; font-size: 15px; line-height: 1.5; }} {SCROLLBAR_CSS}")
        self.text_editor.textChanged.connect(self.schedule_preview)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet(f"QTextBrowser {{ background: rgba(255,255,255,.02); border: 1px solid rgba(255,255,255,.05); border-radius: 12px; color: #ECEFF4; padding: 15px; }} {SCROLLBAR_CSS}")
        
        self.splitter.addWidget(self.text_editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([500, 500])
        editor_layout.addWidget(self.splitter, 1)
        
        self.editor_footer = QLabel("0 Words  •  0 min read")
        self.editor_footer.setStyleSheet("color: rgba(236,239,244,0.4); font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        self.editor_footer.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor_layout.addWidget(self.editor_footer, 0)
        self.editor_footer.setVisible(self.app_config.get("show_stats", True))
        
        self.right_stack.addWidget(self.editor_widget)

        editor_scroll = self.text_editor.verticalScrollBar()
        preview_scroll = self.preview.verticalScrollBar()
        editor_scroll.valueChanged.connect(self._sync_scroll_to_preview)
        preview_scroll.valueChanged.connect(self._sync_scroll_to_editor)

        self.dashboard_pane = QWidget()
        dash_layout = QVBoxLayout(self.dashboard_pane)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(14)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(14)
        
        self.archive_panel = GlassPanel()
        self.archive_panel.setMaximumWidth(220)
        archive_layout = QVBoxLayout(self.archive_panel)
        archive_layout.setContentsMargins(15, 15, 15, 15)
        
        archive_label = QLabel("📅 Archive")
        archive_label.setStyleSheet("color: #E5E9F0; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        archive_layout.addWidget(archive_label)

        self.archive_list = QListWidget()
        self.archive_list.setFrameShape(QListWidget.NoFrame)
        self.archive_list.setStyleSheet(f"QListWidget {{ background: transparent; color: #ECEFF4; border: none; outline: none; }} QListWidget::item {{ padding: 10px; border-radius: 8px; margin-bottom: 4px; }} QListWidget::item:selected {{ background: rgba(180, 142, 173, 0.4); color: white; font-weight: bold; }} QListWidget::item:hover:!selected {{ background: rgba(255,255,255,0.08); }} {SCROLLBAR_CSS}")
        self.archive_list.itemClicked.connect(self._on_archive_month_clicked)
        archive_layout.addWidget(self.archive_list)
        top_layout.addWidget(self.archive_panel, 1)

        self.cal_wrapper = GlassPanel()
        cal_wrap_layout = QVBoxLayout(self.cal_wrapper)
        cal_wrap_layout.setContentsMargins(15, 15, 15, 15)

        self.calendar_widget = QCalendarWidget()
        self.calendar_widget.setGridVisible(False)
        self.calendar_widget.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar_widget.setStyleSheet("""
            QCalendarWidget QWidget { alternate-background-color: transparent; } QCalendarWidget > QWidget { background-color: transparent; }
            QCalendarWidget QWidget#qt_calendar_navigationbar { background-color: rgba(255, 255, 255, 0.04); border-bottom: 1px solid rgba(255, 255, 255, 0.1); border-top-left-radius: 12px; border-top-right-radius: 12px; padding: 4px; }
            QCalendarWidget QToolButton { color: #ECEFF4; background: transparent; border-radius: 6px; font-weight: bold; padding: 6px; font-size: 14px; }
            QCalendarWidget QToolButton:hover { background: rgba(255, 255, 255, 0.08); } QCalendarWidget QToolButton::menu-indicator { image: none; }
            QCalendarWidget QMenu { background-color: rgba(43, 35, 51, 0.95); color: #ECEFF4; border-radius: 8px; border: 1px solid rgba(180, 142, 173, 0.5); }
            QCalendarWidget QSpinBox { background: rgba(255, 255, 255, 0.05); color: #ECEFF4; border-radius: 6px; padding: 4px; selection-background-color: rgba(180, 142, 173, 0.6); }
            QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button { width: 0px; }
            QTableView QHeaderView::section { background-color: transparent; color: #B48EAD; font-weight: bold; padding: 6px; border: none; }
            QCalendarWidget QAbstractItemView:enabled { color: #ECEFF4; background-color: rgba(0, 0, 0, 0.15); selection-color: #ffffff; outline: none; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }
            QCalendarWidget QAbstractItemView:disabled { color: rgba(236, 239, 244, 0.2); }
            QCalendarWidget QAbstractItemView::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(180, 142, 173, 0.4), stop:0.5 rgba(255, 255, 255, 0.25), stop:1 rgba(136, 192, 208, 0.4)); border: 1px solid rgba(180, 142, 173, 0.5); border-radius: 6px; }
            QCalendarWidget QAbstractItemView::item:hover:!selected { background: rgba(255, 255, 255, 0.08); border-radius: 6px; }
        """)
        self.calendar_widget.clicked.connect(self._on_dashboard_date_clicked)
        cal_wrap_layout.addWidget(self.calendar_widget)
        top_layout.addWidget(self.cal_wrapper, 2)

        self.details_panel = GlassPanel()
        td_layout = QVBoxLayout(self.details_panel)
        td_layout.setContentsMargins(15, 15, 15, 15)
        
        self.dash_date_label = QLabel("Select a date")
        self.dash_date_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #B48EAD; margin-bottom: 8px;")
        td_layout.addWidget(self.dash_date_label)

        self.dash_entry_list = QListWidget()
        self.dash_entry_list.setFrameShape(QListWidget.NoFrame)
        self.dash_entry_list.setSpacing(8)
        self.dash_entry_list.setStyleSheet(f"QListWidget {{ background: transparent; outline: none; border: none; }} QListWidget::item {{ border-radius: 12px; margin-bottom: 4px; }} QListWidget::item:selected {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(180, 142, 173, 0.35), stop:0.5 rgba(255, 255, 255, 0.20), stop:1 rgba(136, 192, 208, 0.35)); border: 1px solid rgba(180, 142, 173, 0.4); border-top: 1px solid rgba(255, 255, 255, 0.5); border-left: 1px solid rgba(255, 255, 255, 0.3); }} QListWidget::item:hover:!selected {{ background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.05); }} {SCROLLBAR_CSS}")
        self.dash_entry_list.itemClicked.connect(self._on_dash_list_item_clicked)
        
        td_layout.addWidget(self.dash_entry_list)
        top_layout.addWidget(self.details_panel, 2)

        dash_layout.addLayout(top_layout, 1)

        self.bottom_row = QWidget()
        bottom_layout = QHBoxLayout(self.bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(14)
        
        self.heatmap_wrapper = GlassPanel()
        hw_layout = QVBoxLayout(self.heatmap_wrapper)
        hw_layout.setContentsMargins(15, 10, 15, 10)
        
        heatmap_title = QLabel("Activity Timeline")
        heatmap_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #88C0D0; margin-bottom: 5px;")
        hw_layout.addWidget(heatmap_title)
        
        self.timeline_widget = TimelineHeatmap()
        self.timeline_widget.dateClicked.connect(self._on_dashboard_date_clicked)
        hw_layout.addWidget(self.timeline_widget)
        
        self.right_stats = QWidget()
        right_stats_layout = QVBoxLayout(self.right_stats)
        right_stats_layout.setContentsMargins(0, 0, 0, 0)
        right_stats_layout.setSpacing(10)
        
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()
        row1.setSpacing(10)
        row2.setSpacing(10)
        
        self.stat_entries = StatBox("Total Entries", "0", "📝")
        self.stat_words = StatBox("Total Words", "0", "✒️")
        self.stat_tags = StatBox("Unique Tags", "0", "🏷️")
        self.stat_streak = StatBox("Writing Streak", "0 Days", "🔥")
        
        row1.addWidget(self.stat_entries)
        row1.addWidget(self.stat_words)
        row2.addWidget(self.stat_tags)
        row2.addWidget(self.stat_streak)
        
        right_stats_layout.addLayout(row1)
        right_stats_layout.addLayout(row2)
        self.right_stats.setVisible(False)
        
        bottom_layout.addWidget(self.heatmap_wrapper, 3) 
        bottom_layout.addWidget(self.right_stats, 2)     
        
        dash_layout.addWidget(self.bottom_row, 0)
        self.right_stack.addWidget(self.dashboard_pane)
        self.right_stack.setCurrentIndex(0)

    # --- Interaction Logic ---
    def _sync_scroll_to_preview(self):
        if getattr(self, '_syncing_scroll', False):
            return 
        e_scroll = self.text_editor.verticalScrollBar()
        p_scroll = self.preview.verticalScrollBar()
        if e_scroll.maximum() <= 0 or p_scroll.maximum() <= 0:
            return
            
        self._syncing_scroll = True
        p_scroll.setValue(int((e_scroll.value() / e_scroll.maximum()) * p_scroll.maximum()))
        self._syncing_scroll = False

    def _sync_scroll_to_editor(self):
        if getattr(self, '_syncing_scroll', False):
            return
        e_scroll = self.text_editor.verticalScrollBar()
        p_scroll = self.preview.verticalScrollBar()
        if e_scroll.maximum() <= 0 or p_scroll.maximum() <= 0:
            return
            
        self._syncing_scroll = True
        e_scroll.setValue(int((p_scroll.value() / p_scroll.maximum()) * e_scroll.maximum()))
        self._syncing_scroll = False

    def _build_toolbar(self):
        self.tb = QToolBar("Main")
        self.tb.setMovable(False)
        self.tb.setStyleSheet("""
            QToolBar { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); border-radius: 10px; margin: 6px; padding: 4px; }
            QToolButton { color: #E5E9F0; padding: 6px 12px; font-weight: bold; }
            QToolButton:hover { background: rgba(180, 142, 173, 0.3); border-radius: 8px; color: white; }
        """)
        self.addToolBar(Qt.TopToolBarArea, self.tb)

        self.folder_combo = QComboBox()
        self.folder_combo.setStyleSheet("""
            QComboBox { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 4px 10px; color: #ECEFF4; font-weight: bold; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView { background: rgba(43, 35, 51, 0.95); color: #ECEFF4; selection-background-color: rgba(180, 142, 173, 0.4); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; }
        """)
        self.folder_combo.currentIndexChanged.connect(self._on_folder_changed)
        self.tb.addWidget(self.folder_combo)

        act_new = QAction("New", self, triggered=self.new_entry, shortcut="Ctrl+N")
        act_save = QAction("Save", self, triggered=self.save_entry, shortcut="Ctrl+S")
        act_del = QAction("Delete", self, triggered=self.delete_entry, shortcut="Del")
        act_img = QAction("Image", self, triggered=self.add_image)
        act_tag = QAction("Tag", self, triggered=self.add_tag, shortcut="Ctrl+T")
        
        self.act_view = QAction("Toggle View", self, triggered=self.toggle_preview_view, shortcut="Ctrl+E")
        self.act_focus = QAction("Focus Mode", self, triggered=self.toggle_focus, shortcut="F11")
        self.act_sidebar = QAction("Toggle Pane", self, triggered=self.toggle_sidebar, shortcut="Ctrl+B")
        
        self.act_ribbon = self.tb.toggleViewAction()
        self.act_ribbon.setText("Toggle Ribbon")
        self.act_ribbon.setShortcut("F10")
        
        act_search = QAction("Search", self, shortcut="Ctrl+F")
        act_search.triggered.connect(self.search_bar.setFocus)
        
        act_help = QAction("Help", self, triggered=self.open_help, shortcut="F1")
        act_dash = QAction("Dashboard", self, triggered=self.open_dashboard)
        act_settings = QAction("Settings", self, triggered=self.open_settings)

        all_actions = [act_new, act_save, act_del, act_img, act_tag, self.act_view, self.act_focus, self.act_sidebar, self.act_ribbon, act_help, act_dash, act_settings, act_search]
        for a in all_actions:
            if a not in (self.act_ribbon, act_search):
                self.tb.addAction(a)
            self.addAction(a) 

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.tb.addWidget(spacer)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #A3BE8C; font-size: 11px; padding-right: 15px; font-weight: bold;")
        self.tb.addWidget(self.status_label)

    def _setup_timers(self):
        # Explicitly connect the autosave timer
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self.autosave_timer.timeout.connect(self.auto_save)
        self.autosave_timer.start()
        
        # Explicitly connect the preview debounce timer
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
        
        self.lock_timer = QTimer(self)
        self.lock_timer.timeout.connect(self.lock_app)
        
        self.apply_lock_timer_settings()
        self.activity_filter = ActivityFilter()
        self.activity_filter.activity_occurred.connect(self.reset_lock_timer)
        QApplication.instance().installEventFilter(self.activity_filter)

    def _setup_menus(self):
        menu_style = """
            QMenu { background-color: rgba(35, 40, 48, 0.95); color: #ECEFF4; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; padding: 5px; }
            QMenu::item { padding: 8px 24px; border-radius: 4px; }
            QMenu::item:selected { background-color: rgba(180, 142, 173, 0.4); color: white; }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.1); margin: 4px 10px; }
        """
        self.setStyleSheet(self.styleSheet() + menu_style)
        
        self.entry_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.entry_list.customContextMenuRequested.connect(self._show_entry_context_menu)
        
        self.text_editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_editor.customContextMenuRequested.connect(self._show_editor_context_menu)
        
        self.tag_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_scroll.customContextMenuRequested.connect(self._show_tag_context_menu)

    # ---------- Status, Focus & Settings ----------
    def show_status(self, text: str):
        self.status_label.setText(f"♡ {text}")
        QTimer.singleShot(2500, lambda: self.status_label.setText(""))

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_preview_view(self):
        self.view_mode = (self.view_mode + 1) % 3
        if self.view_mode == 0:
            self.text_editor.setVisible(True)
            self.preview.setVisible(True)
            self.act_view.setText("View: Split")
        elif self.view_mode == 1:
            self.text_editor.setVisible(True)
            self.preview.setVisible(False)
            self.act_view.setText("View: Editor")
        elif self.view_mode == 2:
            self.text_editor.setVisible(False)
            self.preview.setVisible(True)
            self.act_view.setText("View: Preview")
            
    def toggle_focus(self):
        self.focus_mode = not self.focus_mode
        self.sidebar.setVisible(not self.focus_mode)
        self.right_stats.setVisible(self.focus_mode)
        
        if self.focus_mode:
            self.act_focus.setText("Exit Focus")
            self.showFullScreen()
        else:
            self.act_focus.setText("Focus Mode")
            self.showNormal()

    def open_settings(self):
        dlg = SettingsDialog(self.app_config, self)
        if dlg.exec() == QDialog.Accepted:
            self.app_config = dlg.get_config()
            save_config(self.app_config)
            self.apply_lock_timer_settings()
            
            show = self.app_config.get("show_stats", True)
            self.editor_footer.setVisible(show)
            if show:
                self.update_preview()
            self.show_status("Settings Saved")

    def open_help(self):
        HelpDialog(self).exec()

    # ---------- Idle Lock ----------
    def apply_lock_timer_settings(self):
        self.lock_timer.stop()
        if not self.app_config.get("lock_enabled", True):
            return
        val = self.app_config.get("lock_val", 5)
        unit = self.app_config.get("lock_unit", "Minutes")
        self.lock_timer.setInterval(val * 60000 if unit == "Minutes" else val * 1000)
        self.lock_timer.start()

    def reset_lock_timer(self):
        if self.lock_timer.isActive():
            self.lock_timer.start()

    def lock_app(self):
        self.lock_timer.stop()
        self.hide() 
        while True:
            unlock_screen = UnlockDialog(self, is_startup=False)
            if unlock_screen.exec() != QDialog.Accepted:
                sys.exit(0)
            try:
                with open(SALT_FILE, "rb") as f:
                    salt = f.read()
                with open(VERIFY_FILE, "rb") as f:
                    token = f.read()
                if CryptoManager(unlock_screen.get_password(), salt).decrypt(token) == b"DIARY_VERIFIED":
                    break
            except Exception:
                QMessageBox.warning(None, "Error", "Incorrect password")
        self.show()
        self.apply_lock_timer_settings()

    # ---------- Folder Management ----------
    def _update_folder_list(self):
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItem("📂 All Folders", None)
        try:
            if hasattr(self.db, "get_categories"):
                for cid, name in self.db.get_categories():
                    self.folder_combo.addItem(f"📁 {name}", name)
                    if self.active_folder_name == name:
                        self.folder_combo.setCurrentIndex(self.folder_combo.count() - 1)
        except Exception:
            pass
        self.folder_combo.blockSignals(False)

    def _on_folder_changed(self, index):
        self.active_folder_name = self.folder_combo.itemData(index)
        self.load_entries(keep_selection=False)

    # ---------- Preview & Accurate Stats ----------
    def schedule_preview(self):
        self.preview_timer.start(PREVIEW_DEBOUNCE_MS)

    def update_preview(self):
        e_scroll = self.text_editor.verticalScrollBar()
        p_scroll = self.preview.verticalScrollBar()
        e_val, e_max = e_scroll.value(), e_scroll.maximum()
        
        is_at_bottom = (e_max > 0 and e_val >= e_max - 5)

        fmt = getattr(self.current_entry, "format", "markdown") if self.current_entry else "markdown"
        text = self.text_editor.toPlainText()

        for uid, (_, _, b64) in self.entry_images.items():
            text = text.replace(f"(image://{uid})", f"(data:image/png;base64,{b64})")
            text = text.replace(f"image://{uid}", f"data:image/png;base64,{b64})")

        if fmt == "text":
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            html = f"<html><head><style>{MARKDOWN_CSS}</style></head><body><pre style='font-family:inherit;border:none'>{safe}</pre></body></html>"
        else:
            html = f"<html><head><style>{MARKDOWN_CSS}</style></head><body>{markdown2.markdown(text, extras=MARKDOWN_EXTRAS)}</body></html>"

        self._syncing_scroll = True
        p_scroll.blockSignals(True)
        
        self.preview.setHtml(html)

        # Handle word count stats
        if self.app_config.get("show_stats", True):
            rendered_text = self.preview.toPlainText().strip()
            words = len(rendered_text.split()) if rendered_text else 0
            if words == 0:
                time_str = "0 min read"
            elif words < 100:
                time_str = "< 1 min read"
            else:
                time_str = f"{math.ceil(words / 200)} min read"
            self.editor_footer.setText(f"{words:,} Words  •  {time_str}")

        # Async layout recalculation
        def apply_scroll():
            if is_at_bottom:
                p_scroll.setValue(p_scroll.maximum())
            elif e_scroll.maximum() > 0:
                p_scroll.setValue(int((e_val / e_scroll.maximum()) * p_scroll.maximum()))
            p_scroll.blockSignals(False)
            self._syncing_scroll = False

        # Give the layout engine 20ms to process the new HTML and calculate maximum scroll height
        QTimer.singleShot(20, apply_scroll) 

        if self.app_config.get("show_stats", True):
            rendered_text = self.preview.toPlainText().strip()
            words = len(rendered_text.split()) if rendered_text else 0
            if words == 0:
                time_str = "0 min read"
            elif words < 100:
                time_str = "< 1 min read"
            else:
                time_str = f"{math.ceil(words / 200)} min read"
            self.editor_footer.setText(f"{words:,} Words  •  {time_str}")

        e_scroll.setValue(e_val)
        if e_scroll.maximum() > 0:
            p_scroll.setValue(int((e_val / e_scroll.maximum()) * p_scroll.maximum()))
        self._syncing_scroll = False

    # ---------- Tags ----------
    def load_tags(self):
        self.tag_holder.clear()
        tag_set = set()
        try:
            if hasattr(self.db, "get_all_tags"):
                try:
                    tag_set.update([t for t in self.db.get_all_tags() if t])
                except Exception:
                    pass
            for r in self.db.get_entries():
                try:
                    tlist = self.db.get_entry_tags(r["id"])
                except Exception:
                    tlist = r.get("tags") or []
                tag_set.update([t for t in (tlist or []) if t])
        except Exception:
            pass

        for tag in sorted(tag_set, key=lambda s: s.lower()):
            chip = TagChip(tag, self._toggle_tag_filter, self._show_tag_chip_context_menu)
            chip.setStyleSheet(TAG_STYLE_ACTIVE if tag in self.active_tags else TAG_STYLE_NORMAL)
            self.tag_holder.add_widget(chip)

    def _toggle_tag_filter(self, tag: str):
        if tag in self.active_tags:
            self.active_tags.remove(tag)
        else:
            self.active_tags.add(tag)
        self.load_entries(keep_selection=True)

    def _show_tag_chip_context_menu(self, tag: str, pos):
        menu = QMenu(self)
        menu.addAction(f"Delete '{tag}' Globally", lambda: self._delete_tag_globally(tag))
        menu.exec(pos)

    def _delete_tag_globally(self, tag: str):
        if QMessageBox.question(self, "Confirm Global Delete", f"Permanently delete the tag '{tag}' from all entries?") == QMessageBox.Yes:
            if tag in self.active_tags:
                self.active_tags.remove(tag)
            try:
                if hasattr(self.db, "delete_tag"):
                    self.db.delete_tag(tag)
                for db_row in self.db.get_entries():
                    r = dict(db_row)
                    tags = self.db.get_entry_tags(r["id"]) if hasattr(self.db, "get_entry_tags") else (r.get("tags") or [])
                    if tag in tags:
                        tags.remove(tag)
                        if hasattr(self.db, "set_entry_tags"):
                            self.db.set_entry_tags(r["id"], tags)
                        else:
                            imgs = self.db.get_entry_images(r["id"]) if hasattr(self.db, "get_entry_images") else []
                            try:
                                self.db.update_entry(r["id"], r.get("title", ""), r.get("content", b""), tags, imgs, update_timestamp=False)
                            except TypeError:
                                self.db.update_entry(r["id"], r.get("title", ""), r.get("content", b""), tags, imgs)
            except Exception:
                pass
            self.load_tags()
            self.load_entries(keep_selection=True)
            self.show_status(f"Deleted Tag: {tag}")

    # ---------- Entry Helpers ----------
    def _create_entry_item(self, row: dict, tags: List[str], category_name: Optional[str] = None, target_list: QListWidget = None) -> QListWidgetItem:
        if target_list is None:
            target_list = self.entry_list
            
        item = QListWidgetItem()
        item.setData(Qt.UserRole, row["id"])
        item.setSizeHint(QSize(100, 68))
        raw_date = row.get("updated_at") or row.get("created_at") or ""
        
        try:
            display_date = datetime.strptime(str(raw_date).split(".")[0].replace("T", " ").replace("Z", ""), "%Y-%m-%d %H:%M:%S").strftime("%b %d, %Y %I:%M %p")
        except Exception:
            display_date = str(raw_date)[:16] or "—"
            
        target_list.addItem(item)
        target_list.setItemWidget(item, EntryCard(row.get("title"), display_date, tags, category_name))
        return item

    def _stable_sort(self, rows: List[dict]) -> List[dict]:
        return sorted(rows, key=lambda r: r.get("updated_at") or r.get("created_at") or "", reverse=self.sort_desc)

    def _preserve_selection_and_scroll(self):
        return (
            self.entry_list.currentItem().data(Qt.UserRole) if self.entry_list.currentItem() else None, 
            self.entry_list.verticalScrollBar().value()
        )

    def _select_in_list(self, entry_id: int):
        for i in range(self.entry_list.count()):
            if self.entry_list.item(i).data(Qt.UserRole) == entry_id:
                self.entry_list.setCurrentItem(self.entry_list.item(i))
                break

    # ---------- Entries ----------
    def load_entries(self, keep_selection: bool = True, search_text: Optional[str] = None):
        selected_id, scroll = self._preserve_selection_and_scroll() if keep_selection else (None, 0)
        try:
            rows = [dict(r) for r in self.db.get_entries()]
        except Exception:
            rows = []
            
        filtered, q = [], (search_text or "").strip().lower()

        for r in rows:
            try:
                cat_name = self.db.get_category(r.get("category_id") or r.get("category"))[1] if hasattr(self.db, "get_category") else r.get("category")
            except Exception:
                cat_name = r.get("category")
            
            if self.active_folder_name is not None and cat_name != self.active_folder_name:
                continue

            try:
                tags = self.db.get_entry_tags(r["id"])
            except Exception:
                tags = r.get("tags") or []

            if self.active_tags and not self.active_tags.intersection(tags):
                continue

            if q:
                if not (q in (r.get("title") or "").lower() or any(q in (t or "").lower() for t in tags)):
                    try:
                        content = self.crypto.decrypt(r["content"]).decode(errors="ignore").lower()
                    except Exception:
                        content = ""
                    if q not in content:
                        continue

            r["__tags"], r["__category_name"] = tags, cat_name
            filtered.append(r)

        self.entries_cache = self._stable_sort(filtered)
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        
        for r in self.entries_cache:
            self._create_entry_item(r, r["__tags"], r["__category_name"])
            
        self.entry_list.blockSignals(False)
        self.load_tags()
        self.update_dashboards()

        if keep_selection and selected_id is not None:
            self._select_in_list(selected_id)
            self.entry_list.verticalScrollBar().setValue(scroll)

    def _on_list_item_clicked(self, item: QListWidgetItem):
        if not item:
            return
            
        self.right_stack.setCurrentIndex(1)
        entry_id = item.data(Qt.UserRole)
        row = next((r for r in self.entries_cache if r["id"] == entry_id), None)
        if not row:
            return

        try:
            tags = self.db.get_entry_tags(row["id"])
        except Exception:
            tags = row.get("tags") or []
        
        self.entry_images.clear()
        try:
            for uid, name in self.db.get_entry_images(row["id"]):
                try:
                    decrypted_bytes = decrypt_image_from_file(self.crypto, uid)
                    self.entry_images[uid] = (name, decrypted_bytes, base64.b64encode(decrypted_bytes).decode())
                except Exception:
                    pass
        except Exception:
            pass

        try:
            content = self.crypto.decrypt(row["content"]).decode(errors="ignore")
        except Exception:
            content = ""

        self.current_entry = Entry(row["id"], row.get("title"), content, row.get("created_at"), row.get("updated_at"), tags, list(self.entry_images.items()), None)
        setattr(self.current_entry, "format", row.get("format") or "markdown")
        setattr(self.current_entry, "category_id", row.get("category_id") or row.get("category") or None)
        setattr(self.current_entry, "content", content)

        self.text_editor.blockSignals(True)
        self.text_editor.setPlainText(content)
        self.text_editor.blockSignals(False)
        self.update_preview()

    # ---------- Unified Dashboard Logic ----------
    def open_dashboard(self):
        self.right_stack.setCurrentIndex(2)

    def update_dashboards(self):
        self.timeline_widget.set_data(self.entries_cache)
        for d in self.formatted_dates:
            self.calendar_widget.setDateTextFormat(d, QTextCharFormat())
        self.formatted_dates.clear()

        day_counts, month_counts = collections.Counter(), collections.Counter()
        total_words, unique_tags, active_dates = 0, set(), set()
        
        for r in self.entries_cache:
            try:
                total_words += len(self.crypto.decrypt(r["content"]).decode(errors="ignore").split())
            except Exception:
                pass

            unique_tags.update(r.get("__tags", []))

            if d_str := (r.get("created_at") or r.get("updated_at")):
                try:
                    dt = datetime.strptime(str(d_str).split(".")[0].replace("T", " ").replace("Z", ""), "%Y-%m-%d %H:%M:%S")
                    qdate = QDate(dt.year, dt.month, dt.day)
                    day_counts[qdate] += 1
                    month_counts[(dt.year, dt.month)] += 1
                    active_dates.add(dt.date()) 
                except Exception:
                    pass

        streak = 0
        if active_dates:
            sorted_dates, today = sorted(list(active_dates), reverse=True), datetime.now().date()
            if sorted_dates[0] in (today, today - timedelta(days=1)):
                streak = 1
                for i in range(1, len(sorted_dates)):
                    if (sorted_dates[i-1] - sorted_dates[i]).days == 1:
                        streak += 1
                    else:
                        break

        self.stat_entries.update_value(len(self.entries_cache))
        self.stat_words.update_value(f"{total_words:,}")
        self.stat_tags.update_value(len(unique_tags))
        self.stat_streak.update_value(f"{streak} Days")

        for qdate, count in day_counts.items():
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(180, 142, 173, min(255, 80 + count * 40)))
            fmt.setForeground(QColor(255, 255, 255))
            fmt.setFontWeight(QFont.Bold)
            self.calendar_widget.setDateTextFormat(qdate, fmt)
            self.formatted_dates.append(qdate)
            
        self.archive_list.clear()
        for year, month in sorted(month_counts.keys(), reverse=True):
            item = QListWidgetItem(f"{QDate(year, month, 1).toString('MMMM yyyy')}  [{month_counts[(year, month)]}]")
            item.setData(Qt.UserRole, (year, month))
            self.archive_list.addItem(item)

    def _on_archive_month_clicked(self, item: QListWidgetItem):
        y, m = item.data(Qt.UserRole)
        self.calendar_widget.setCurrentPage(y, m)

    def _on_dashboard_date_clicked(self, date: QDate):
        self.timeline_widget.set_selected_date(date)
        self.calendar_widget.blockSignals(True)
        self.calendar_widget.setSelectedDate(date)
        self.calendar_widget.blockSignals(False)

        self.dash_entry_list.clear()
        matched = []
        for r in self.entries_cache:
            if d_str := (r.get("created_at") or r.get("updated_at")):
                try:
                    dt = datetime.strptime(str(d_str).split(".")[0].replace("T", " ").replace("Z", ""), "%Y-%m-%d %H:%M:%S")
                    if dt.year == date.year() and dt.month == date.month() and dt.day == date.day():
                        matched.append(r)
                except Exception:
                    pass
                    
        self.dash_date_label.setText(f"{len(matched)} Entries on {date.toString('MMMM d, yyyy')}")
        for r in matched:
            self._create_entry_item(r, r.get("__tags", []), r.get("__category_name"), self.dash_entry_list)

    def _on_dash_list_item_clicked(self, item: QListWidgetItem):
        self._select_in_list(item.data(Qt.UserRole))
        if self.entry_list.currentItem():
            self._on_list_item_clicked(self.entry_list.currentItem())

    # ---------- Entry Operations ----------
    def new_entry(self):
        self.right_stack.setCurrentIndex(1)
        self.current_entry = None
        self.entry_images.clear()
        self.text_editor.clear()
        self.preview.clear()

    def save_entry(self):
        content = self.text_editor.toPlainText()
        if not content.strip():
            return
        
        # Disabled image deletion logic
        orphans = [uid for uid in self.entry_images.keys() if f"image://{uid}" not in content]
        for uid in orphans:
            self.entry_images.pop(uid, None)

        title = (content.split("\n")[0][:100] or "Untitled").strip()
        images_data = [(uid, name) for uid, (name, _, _) in self.entry_images.items()]
        tags = getattr(self.current_entry, "tags", [])
        enc_content = self.crypto.encrypt(content.encode())

        if self.current_entry and getattr(self.current_entry, "id", None):
            if content != getattr(self.current_entry, "content", "") or title != getattr(self.current_entry, "title", "") or [u for u, _ in images_data] != [u for u, _ in getattr(self.current_entry, "images", [])]:
                try:
                    self.db.update_entry(self.current_entry.id, title, enc_content, tags, images_data, update_timestamp=True)
                except TypeError:
                    self.db.update_entry(self.current_entry.id, title, enc_content, tags, images_data)
            self.current_entry.title, self.current_entry.content, self.current_entry.images = title, content, list(self.entry_images.items())
        else:
            try:
                entry_id = self.db.add_entry(title, enc_content, tags, images_data)
                self.current_entry = Entry(id=entry_id, title=title, content=content, created_at=None, updated_at=None, tags=tags, images=list(self.entry_images.items()))
            except Exception:
                return

        self.load_entries(keep_selection=True, search_text=self.search_bar.text())
        if getattr(self.current_entry, "id", None):
            self._select_in_list(self.current_entry.id)
        self.show_status("")

    def delete_entry(self):
        if not self.current_entry:
            return
        if QMessageBox.question(self, "Confirm", "Delete entry?") == QMessageBox.Yes:
            try:
                self.db.delete_entry(self.current_entry.id)
            except Exception:
                pass
            
            self.current_entry = None
            self.entry_images.clear()
            self.text_editor.clear()
            self.preview.clear()
            self.right_stack.setCurrentIndex(0)
            self.load_entries(keep_selection=False)

    def add_image(self):
        if not self.current_entry:
            return QMessageBox.warning(self, "No Entry", "Create or select an entry")
        
        path = QFileDialog.getOpenFileName(self, "Select Image")[0]
        if path:
            try:
                uid, name = encrypt_image_to_file(self.crypto, path)
                decrypted_bytes = decrypt_image_from_file(self.crypto, uid)
                self.entry_images[uid] = (name, decrypted_bytes, base64.b64encode(decrypted_bytes).decode())
                self.text_editor.append(f"![{name}](image://{uid})")
                self.update_preview()
            except Exception:
                QMessageBox.warning(self, "Error", "Failed to add image")

    def add_tag(self):
        if not self.current_entry or not getattr(self.current_entry, "id", None):
            return QMessageBox.warning(self, "No Entry", "Create or select an entry")
            
        dlg = GlassInputDialog("Add Tag", "Enter tag name...", self)
        if dlg.exec() == QDialog.Accepted and (tag := dlg.get_text().strip()) and tag not in self.current_entry.tags:
            self.current_entry.tags.append(tag)
            self._persist_tags(self.current_entry)
            self.load_tags()
            self.load_entries(keep_selection=True)

    def _persist_tags(self, entry: Entry):
        if not entry or not getattr(entry, "id", None):
            return
        try:
            if hasattr(self.db, "set_entry_tags"):
                self.db.set_entry_tags(entry.id, entry.tags)
            else:
                try:
                    self.db.update_entry(entry.id, getattr(entry, "title", "Untitled"), self.crypto.encrypt(getattr(entry, "content", "").encode()), entry.tags, [(u, n) for u, (n, _, _) in getattr(entry, "images", [])], update_timestamp=False)
                except TypeError:
                    self.db.update_entry(entry.id, getattr(entry, "title", "Untitled"), self.crypto.encrypt(getattr(entry, "content", "").encode()), entry.tags, [(u, n) for u, (n, _, _) in getattr(entry, "images", [])])
        except Exception:
            pass

    def edit_tags_dialog(self):
        if not self.current_entry:
            return QMessageBox.warning(self, "No Entry", "Select an entry")
            
        dlg = EditTagsDialog(self.current_entry.tags, self)
        if dlg.exec() == QDialog.Accepted:
            self.current_entry.tags = dlg.final_tags
            self._persist_tags(self.current_entry)
            self.load_tags()
            self.load_entries(keep_selection=True)

    def refresh_entries(self):
        self.load_entries(keep_selection=True, search_text=self.search_bar.text())
        self.show_status("Refreshed")

    def toggle_sort(self):
        self.sort_desc = not self.sort_desc
        self.load_entries(keep_selection=True)

    def search_entries(self, text: str):
        self.load_entries(keep_selection=True, search_text=text)

    def auto_save(self):
        if self.text_editor.toPlainText().strip():
            self.save_entry()

    # ---------- Context menus ----------
    def _show_entry_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("New Entry", self.new_entry)
        menu.addAction("Save Entry", self.save_entry)
        menu.addAction("Delete Entry", self.delete_entry)
        menu.addSeparator()
        
        menu.addAction("Create Folder...", self._create_category_from_menu)
        menu.addAction("Delete Current Folder...", self._delete_current_folder)
        
        move_menu = menu.addMenu("Move to Folder")
        cats = self.db.get_categories() if hasattr(self.db, "get_categories") else []
        
        # New feature: Move to None (Remove from folder)
        move_menu.addAction("None (Remove from folder)").triggered.connect(
            lambda checked=False: self._move_selected_entry_to_category(None)
        )
        
        if cats:
            move_menu.addSeparator()
            for cid, name in cats:
                move_menu.addAction(name).triggered.connect(
                    lambda checked=False, _c=cid: self._move_selected_entry_to_category(_c)
                )
                
        menu.addSeparator()
        menu.addAction("Refresh", self.refresh_entries)
        menu.addAction("Toggle Sort", self.toggle_sort)
        menu.exec(self.entry_list.mapToGlobal(pos))

    def _create_category_from_menu(self):
        dlg = GlassInputDialog("Create Folder", "Folder name...", self)
        if dlg.exec() == QDialog.Accepted and (n := dlg.get_text().strip()):
            try: 
                self.db.add_category(n)
                self._update_folder_list()
                self.load_entries(keep_selection=True)
                self.show_status("Folder created")
            except Exception:
                pass

    def _delete_current_folder(self):
        if not self.active_folder_name:
            QMessageBox.information(self, "No Folder", "Please select a specific folder from the top toolbar first.")
            return

        if QMessageBox.question(self, "Delete Folder", f"Are you sure you want to delete the folder '{self.active_folder_name}'?\n\nEntries inside will NOT be deleted, but will be removed from this folder.", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            cats = self.db.get_categories() if hasattr(self.db, "get_categories") else []
            cat_id = next((cid for cid, name in cats if name == self.active_folder_name), None)

            if cat_id is not None:
                # 1. Prevent Foreign Key crashes by safely moving all entries out of this folder first
                for r in self.entries_cache:
                    if r.get("__category_name") == self.active_folder_name:
                        try:
                            self.db.update_entry_category(r["id"], None)
                        except Exception:
                            try: self.db.update_entry_category(r["id"], 0)
                            except Exception: pass

                # 2. Attempt standard deletion
                success = False
                if hasattr(self.db, "delete_category"):
                    try:
                        self.db.delete_category(cat_id)
                        success = True
                    except Exception as e:
                        print(f"Error calling delete_category: {e}")
                
                # 3. Fallback: Direct SQLite execution if delete_category is missing in database.py
                if not success and hasattr(self.db, "conn"):
                    try:
                        cur = self.db.conn.cursor()
                        cur.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
                        self.db.conn.commit()
                        success = True
                    except Exception as e:
                        print(f"Fallback database deletion failed: {e}")

                if success:
                    self.active_folder_name = None
                    self._update_folder_list()
                    self.load_entries(keep_selection=False)
                    self.show_status("Folder deleted")
                else:
                    QMessageBox.warning(self, "Error", "Could not delete folder. Please ensure your DatabaseManager has a 'delete_category(category_id)' method implemented.")

    def _move_selected_entry_to_category(self, category_id):
        if self.entry_list.currentItem() and self.current_entry:
            entry_id = self.entry_list.currentItem().data(Qt.UserRole)
            success = False
            
            try:
                self.db.update_entry_category(entry_id, category_id)
                success = True
            except Exception as e:
                # Fallback: Some databases require 0 or "" instead of None for "No Category"
                for fallback in [0, ""]:
                    if not success:
                        try:
                            self.db.update_entry_category(entry_id, fallback)
                            success = True
                        except Exception:
                            pass
                            
            if success:
                self.load_entries(keep_selection=True)
                self.show_status("Moved entry")
            else:
                QMessageBox.warning(self, "Database Error", "Failed to clear the folder. Ensure your database.py supports setting the category to None/NULL.")

    

    def _show_editor_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Add Image", self.add_image)
        menu.addAction("Add Tag", self.add_tag)
        menu.addAction("Edit Tags…", self.edit_tags_dialog)
        
        fm = menu.addMenu("Format")
        fm.addAction("Markdown", lambda: self._set_format_for_current("markdown"))
        fm.addAction("Text", lambda: self._set_format_for_current("text"))
        
        menu.addSeparator()
        menu.addAction("Save Entry", self.save_entry)
        menu.exec(self.text_editor.mapToGlobal(pos))

    def _set_format_for_current(self, fmt: str):
        if not self.current_entry:
            self.current_entry = Entry(None, None, "", None, None, [], [], None)
        setattr(self.current_entry, "format", fmt)
        self.update_preview()

    def _show_tag_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Clear Filters", self._clear_tag_filters)
        menu.exec(self.tag_scroll.mapToGlobal(pos))

    def _clear_tag_filters(self):
        self.active_tags.clear()
        self.load_entries(keep_selection=True)

# ---------------- Main ----------------
def main():
    os.makedirs(IMAGE_FOLDER, exist_ok=True)
    
    salt = None
    if os.path.exists(SALT_FILE):
        with open(SALT_FILE, "rb") as f:
            salt = f.read()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(0, 0, 0, 0))
    pal.setColor(QPalette.WindowText, Qt.white)
    pal.setColor(QPalette.Base, QColor(30, 32, 36))
    pal.setColor(QPalette.Text, Qt.white)
    pal.setColor(QPalette.Button, QColor(50, 50, 50))
    pal.setColor(QPalette.ButtonText, Qt.white)
    app.setPalette(pal)

    unlock_screen = UnlockDialog(is_startup=True)
    if unlock_screen.exec() != QDialog.Accepted:
        sys.exit(0)
        
    pw = unlock_screen.get_password()
    if not pw:
        sys.exit(0)

    crypto = CryptoManager(pw, salt)
    db = DatabaseManager() 
    
    if not os.path.exists(SALT_FILE):
        try:
            with open(SALT_FILE, "wb") as f:
                f.write(crypto.salt)
        except Exception:
            pass

    if not os.path.exists(VERIFY_FILE):
        try:
            entries = list(db.get_entries())
            if entries:
                crypto.decrypt(entries[0]["content"])
        except Exception:
            QMessageBox.critical(None, "Denied", "Incorrect master password for existing data!")
            sys.exit(1)
            
        with open(VERIFY_FILE, "wb") as f:
            f.write(crypto.encrypt(b"DIARY_VERIFIED"))
    else:
        try:
            with open(VERIFY_FILE, "rb") as f:
                if crypto.decrypt(f.read()) != b"DIARY_VERIFIED":
                    raise Exception
        except Exception:
            QMessageBox.critical(None, "Denied", "Incorrect master password!")
            sys.exit(1) 

    window = DiaryApp(crypto, db)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
