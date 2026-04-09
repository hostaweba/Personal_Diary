#!/usr/bin/env python3
import sys
import os
import base64
import platform
import collections
import json
from typing import Dict, Tuple, Optional, List
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QTextEdit, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QTextBrowser, QLineEdit, QLabel, QScrollArea,
    QInputDialog, QMenu, QFileDialog, QMessageBox, QListWidgetItem, QToolBar,
    QSizePolicy, QStyleOption, QStyle, QDialog, QDialogButtonBox, QStackedWidget,
    QCalendarWidget, QFormLayout, QSpinBox, QComboBox, QCheckBox
)
from PySide6.QtGui import QColor, QPalette, QAction, QFont, QPainter, QTextCharFormat, QPen
from PySide6.QtCore import Qt, QTimer, QSize, QObject, Signal, QEvent, QDate

import markdown2

# Project modules (must exist in your project)
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
PREVIEW_DEBOUNCE_MS = 200

# Markdown
MARKDOWN_EXTRAS = [
    "fenced-code-blocks",
    "code-friendly",
    "tables",
    "strike",
    "task_list",
    "cuddled-lists",
    "footnotes",
    "header-ids",
    "wiki-tables",
    "break-on-newline",
    "nofollow"
]

# Load CSS from external file
try:
    with open("resources/style/style_normal.css", "r", encoding="utf-8") as f:
        MARKDOWN_CSS = f.read()
except FileNotFoundError:
    MARKDOWN_CSS = "body { color: #ECEFF4; font-family: sans-serif; }"

# Tag chip style
TAG_STYLE = """
    QLabel {
        background: rgba(255,255,255,.08);
        color: #E5E9F0;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 12px;
    }
    QLabel:hover { background: rgba(255,255,255,.15); }
"""

# Reusable Scrollbar CSS for Glass UI
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

# ---------- Config Helpers ----------
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"lock_enabled": True, "lock_val": 5, "lock_unit": "Minutes"}

def save_config(config: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

# ---------- Windows blur / acrylic helpers ----------
def enable_windows_blur(win_id) -> None:
    if platform.system().lower() != "windows":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int),
                        ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_uint),
                        ("AnimationId", ctypes.c_int)]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int),
                        ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]

        WCA_ACCENT_POLICY = 19
        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        ACCENT_ENABLE_BLURBEHIND = 3

        user32 = ctypes.windll.user32
        setWindowCompositionAttribute = user32.SetWindowCompositionAttribute
        setWindowCompositionAttribute.restype = wintypes.BOOL

        def apply(accent_state: int):
            accent = ACCENTPOLICY()
            accent.AccentState = accent_state
            accent.GradientColor = 0xCC222222
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = WCA_ACCENT_POLICY
            data.SizeOfData = ctypes.sizeof(accent)
            data.Data = ctypes.addressof(accent)
            hwnd = wintypes.HWND(int(win_id))
            return setWindowCompositionAttribute(hwnd, ctypes.byref(data))

        if not apply(ACCENT_ENABLE_ACRYLICBLURBEHIND):
            apply(ACCENT_ENABLE_BLURBEHIND)
    except Exception:
        pass


# ---------------- Idle Activity Filter ----------------
class ActivityFilter(QObject):
    activity_occurred = Signal()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.KeyPress, QEvent.MouseMove, QEvent.MouseButtonPress):
            self.activity_occurred.emit()
        return super().eventFilter(obj, event)


# ---------------- Reusable UI pieces ----------------
class GlassPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            GlassPanel {
                background: rgba(30, 32, 36, 0.25);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 16px;
            }
        """)

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)


class TimelineHeatmap(QWidget):
    """Dynamic, horizontally scaling GitHub-style timeline"""
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
        while self.start_date.dayOfWeek() != 7: # Align to Sunday
            self.start_date = self.start_date.addDays(-1)

    def set_data(self, entries: List[dict]):
        self._recalculate_dates()
        self.counts.clear()
        for r in entries:
            d_str = r.get("created_at") or r.get("updated_at")
            if d_str:
                try:
                    clean_str = str(d_str).split(".")[0].replace("T", " ").replace("Z", "")
                    dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                    qdate = QDate(dt.year, dt.month, dt.day)
                    self.counts[qdate] = self.counts.get(qdate, 0) + 1
                except Exception:
                    pass
        self.update()

    def set_selected_date(self, date: QDate):
        self.selected_date = date
        self.update()

    def _get_date_at_pos(self, pos) -> Optional[QDate]:
        avail_w = self.width() - self.x_offset - 10
        if avail_w <= 0: return None
        step = avail_w / 53.0
        
        col = int((pos.x() - self.x_offset) // step)
        row = int((pos.y() - self.y_offset) // step)
        if 0 <= col < 53 and 0 <= row < 7:
            target = self.start_date.addDays(col * 7 + row)
            if target <= self.today:
                return target
        return None

    def mouseMoveEvent(self, event):
        # FIXED: Using event.position().toPoint() instead of event.pos()
        date = self._get_date_at_pos(event.position().toPoint())
        if date != self.hovered_date:
            self.hovered_date = date
            if date:
                count = self.counts.get(date, 0)
                self.setToolTip(f"{date.toString('MMM d, yyyy')}\n{count} entries")
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setToolTip("")
                self.setCursor(Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        # FIXED: Using event.position().toPoint() instead of event.pos()
        date = self._get_date_at_pos(event.position().toPoint())
        if date:
            self.selected_date = date
            self.dateClicked.emit(date)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        avail_w = self.width() - self.x_offset - 10
        step = max(4, avail_w / 53.0) 
        cell_size = step * 0.75 
        
        painter.setPen(QColor(236, 239, 244, 130))
        painter.setFont(QFont("Segoe UI", 8))
        
        painter.drawText(5, int(self.y_offset + 1 * step + cell_size), "Mon")
        painter.drawText(5, int(self.y_offset + 3 * step + cell_size), "Wed")
        painter.drawText(5, int(self.y_offset + 5 * step + cell_size), "Fri")

        current_month = -1
        for i in range(53 * 7):
            current_date = self.start_date.addDays(i)
            if current_date > self.today:
                break
                
            col, row = i // 7, i % 7
            x = self.x_offset + col * step
            y = self.y_offset + row * step

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


class SettingsDialog(QDialog):
    def __init__(self, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setStyleSheet("color: #ECEFF4; background: rgba(46, 52, 64, 0.95); border-radius: 8px;")
        layout = QFormLayout(self)

        self.enable_lock_cb = QCheckBox("Enable Auto-Lock")
        self.enable_lock_cb.setChecked(current_config.get("lock_enabled", True))
        
        self.val_spinbox = QSpinBox()
        self.val_spinbox.setMinimum(1)
        self.val_spinbox.setMaximum(1000)
        self.val_spinbox.setValue(current_config.get("lock_val", 5))
        self.val_spinbox.setStyleSheet("background: rgba(255,255,255,0.1); color: white;")
        
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Seconds", "Minutes"])
        self.unit_combo.setCurrentText(current_config.get("lock_unit", "Minutes"))
        self.unit_combo.setStyleSheet("background: rgba(255,255,255,0.1); color: white;")

        layout.addRow(self.enable_lock_cb)
        layout.addRow("Lock Timeout:", self.val_spinbox)
        layout.addRow("Time Unit:", self.unit_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_config(self) -> dict:
        return {
            "lock_enabled": self.enable_lock_cb.isChecked(),
            "lock_val": self.val_spinbox.value(),
            "lock_unit": self.unit_combo.currentText()
        }


class EntryCard(QWidget):
    def __init__(self, title: str, updated: str, tags: Optional[List[str]] = None, category_name: Optional[str] = None):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(2)

        self.title_lbl = QLabel()
        tfont = QFont()
        tfont.setBold(True)
        tfont.setPointSize(11)
        self.title_lbl.setFont(tfont)
        self.title_lbl.setStyleSheet("color: #ECEFF4;")
        
        raw_title = title or "Untitled"
        metrics = self.title_lbl.fontMetrics()
        elided_title = metrics.elidedText(raw_title, Qt.TextElideMode.ElideRight, 220)
        self.title_lbl.setText(elided_title)
        self.title_lbl.setToolTip(raw_title)
        root.addWidget(self.title_lbl)

        date_lbl = QLabel(updated or "—")
        date_lbl.setStyleSheet("color: rgba(236,239,244,0.65); font-size: 11px;")
        root.addWidget(date_lbl)

        if category_name:
            cat_lbl = QLabel(f"Category: {category_name}")
            cat_lbl.setStyleSheet("color: #A3BE8C; font-size: 10px;")
            root.addWidget(cat_lbl)

        if tags:
            raw_tags = ", ".join(tags)
            tags_lbl = QLabel()
            tags_lbl.setStyleSheet("color: #88c0d0; font-size: 10px;")
            tag_metrics = tags_lbl.fontMetrics()
            elided_tags = tag_metrics.elidedText(raw_tags, Qt.TextElideMode.ElideRight, 220)
            tags_lbl.setText(elided_tags)
            tags_lbl.setToolTip(raw_tags)
            root.addWidget(tags_lbl)

        self.setStyleSheet("""
            EntryCard {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 12px;
            }
            EntryCard:hover { background: rgba(255,255,255,0.10); }
        """)


class TagChip(QLabel):
    def __init__(self, text: str, on_click):
        super().__init__(text)
        self.setStyleSheet(TAG_STYLE)
        self.setCursor(Qt.PointingHandCursor)
        self.mousePressEvent = lambda event: on_click(text)


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
        
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 900)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")

        self._build_ui()
        self._build_toolbar()
        self._setup_timers()
        self._setup_menus()

        self.load_tags()
        self.load_entries(keep_selection=False)
        enable_windows_blur(self.winId())

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

        side.addWidget(QLabel("<b style='color:#E5E9F0;'>Tags</b>"))
        self.tag_scroll = QScrollArea(widgetResizable=True)
        self.tag_scroll.setFrameShape(QScrollArea.NoFrame)
        self.tag_scroll.setStyleSheet(f"QScrollArea {{ background: transparent; }} {SCROLLBAR_CSS}")
        self.tag_scroll.setMaximumHeight(160) 
        
        tag_holder = QWidget()
        self.tag_layout = QVBoxLayout(tag_holder)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.addStretch()
        self.tag_scroll.setWidget(tag_holder)
        side.addWidget(self.tag_scroll, 0)

        self.search_bar = QLineEdit(placeholderText="Search (title, tags, content)…")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.15);
                border-radius: 12px; padding: 8px 10px; color: #E5E9F0;
            }
            QLineEdit:focus { border-color: rgba(136,192,208,.8); background: rgba(255,255,255,.12); }
        """)
        self.search_bar.textChanged.connect(self.search_entries)
        side.addWidget(self.search_bar)

        self.entry_list = QListWidget()
        self.entry_list.setFrameShape(QListWidget.NoFrame)
        self.entry_list.setSpacing(8)
        self.entry_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.entry_list.viewport().setStyleSheet("background: transparent;")
        self.entry_list.setStyleSheet(f"QListWidget {{ background: transparent; outline: none; }} {SCROLLBAR_CSS}")
        self.entry_list.itemClicked.connect(self._on_list_item_clicked)
        side.addWidget(self.entry_list, 1)

        # ---------------- RIGHT STACK ----------------
        self.right_stack = QStackedWidget()
        outer_layout.addWidget(self.right_stack, 7)

        # -- View 0: Empty State --
        self.empty_widget = GlassPanel()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_icon = QLabel("📝")
        empty_icon.setStyleSheet("font-size: 48px; color: rgba(255,255,255,0.2);")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_lbl = QLabel("Select an entry or create a new one")
        empty_lbl.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 14px;")
        empty_lbl.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_lbl)
        self.right_stack.addWidget(self.empty_widget)

        # -- View 1: Editor/Preview Splitter --
        self.editor_widget = GlassPanel()
        editor_layout = QVBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(12, 12, 12, 12)
        self.splitter = QSplitter(Qt.Vertical)

        self.text_editor = QTextEdit()
        self.text_editor.setPlaceholderText("# Title\n\nStart writing…")
        self.text_editor.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px; padding: 15px; selection-background-color: rgba(136,192,208,.3);
            }} {SCROLLBAR_CSS}
        """)

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet(f"""
            QTextBrowser {{
                background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px; color: #ECEFF4; padding: 10px;
            }} {SCROLLBAR_CSS}
        """)

        self.splitter.addWidget(self.text_editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([600, 400])
        editor_layout.addWidget(self.splitter)
        self.right_stack.addWidget(self.editor_widget)

        editor_scroll = self.text_editor.verticalScrollBar()
        preview_scroll = self.preview.verticalScrollBar()
        editor_scroll.valueChanged.connect(preview_scroll.setValue)
        preview_scroll.valueChanged.connect(editor_scroll.setValue)

        # -- View 2: Unified Activity Dashboard --
        self.dashboard_pane = QWidget()
        dash_layout = QVBoxLayout(self.dashboard_pane)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(14)

        # TOP: Calendar, Archive & List
        top_layout = QHBoxLayout()
        top_layout.setSpacing(14)
        
        # Left - Active Months Archive
        self.archive_panel = GlassPanel()
        self.archive_panel.setMaximumWidth(220)
        archive_layout = QVBoxLayout(self.archive_panel)
        archive_layout.setContentsMargins(15, 15, 15, 15)
        
        archive_label = QLabel("📅 Activity Archive")
        archive_label.setStyleSheet("color: #E5E9F0; font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        archive_layout.addWidget(archive_label)

        self.archive_list = QListWidget()
        self.archive_list.setFrameShape(QListWidget.NoFrame)
        self.archive_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; color: #ECEFF4; border: none; outline: none; }}
            QListWidget::item {{ padding: 10px; border-radius: 8px; margin-bottom: 4px; }}
            QListWidget::item:selected {{ background: rgba(136,192,208,0.4); color: white; font-weight: bold; }}
            QListWidget::item:hover:!selected {{ background: rgba(255,255,255,0.08); }}
            {SCROLLBAR_CSS}
        """)
        self.archive_list.itemClicked.connect(self._on_archive_month_clicked)
        archive_layout.addWidget(self.archive_list)
        top_layout.addWidget(self.archive_panel, 1)

        # Middle - Calendar Glass Panel
        self.cal_wrapper = GlassPanel()
        cal_wrap_layout = QVBoxLayout(self.cal_wrapper)
        cal_wrap_layout.setContentsMargins(15, 15, 15, 15)

        self.calendar_widget = QCalendarWidget()
        self.calendar_widget.setGridVisible(False)
        self.calendar_widget.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar_widget.setStyleSheet("""
            QCalendarWidget QWidget { alternate-background-color: transparent; }
            QCalendarWidget > QWidget { background-color: transparent; }
            
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background-color: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            QCalendarWidget QToolButton {
                color: #ECEFF4; background: transparent;
                border-radius: 4px; font-weight: bold; padding: 4px;
            }
            QCalendarWidget QToolButton:hover { background: rgba(255, 255, 255, 0.1); }
            QCalendarWidget QToolButton::menu-indicator { image: none; }
            
            QCalendarWidget QMenu { 
                background-color: rgba(46, 52, 64, 0.95); 
                color: #ECEFF4; border-radius: 4px; border: 1px solid rgba(255,255,255,0.1);
            }
            
            QCalendarWidget QSpinBox {
                background: rgba(255, 255, 255, 0.05); color: #ECEFF4;
                border-radius: 4px; padding: 2px;
                selection-background-color: rgba(136, 192, 208, 0.6);
            }
            QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button { subcontrol-origin: border; width: 0px; }
            
            QCalendarWidget QAbstractItemView:enabled {
                color: #ECEFF4; background-color: transparent;
                selection-background-color: rgba(136, 192, 208, 0.6);
                selection-color: #ffffff; outline: none;
            }
            QCalendarWidget QAbstractItemView:disabled { color: rgba(236, 239, 244, 0.2); }
            
            QTableView QHeaderView::section {
                background-color: transparent; color: #88C0D0;
                font-weight: bold; padding: 4px; border: none;
            }
        """)
        self.calendar_widget.clicked.connect(self._on_dashboard_date_clicked)
        cal_wrap_layout.addWidget(self.calendar_widget)
        top_layout.addWidget(self.cal_wrapper, 2)

        # Right - Day Details Glass Panel
        self.details_panel = GlassPanel()
        td_layout = QVBoxLayout(self.details_panel)
        td_layout.setContentsMargins(15, 15, 15, 15)
        
        self.dash_date_label = QLabel("Select a date")
        self.dash_date_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #A3BE8C; margin-bottom: 8px;")
        td_layout.addWidget(self.dash_date_label)

        self.dash_entry_list = QListWidget()
        self.dash_entry_list.setFrameShape(QListWidget.NoFrame)
        self.dash_entry_list.setSpacing(8)
        self.dash_entry_list.setStyleSheet(f"QListWidget {{ background: transparent; outline: none; }} {SCROLLBAR_CSS}")
        self.dash_entry_list.itemClicked.connect(self._on_dash_list_item_clicked)
        td_layout.addWidget(self.dash_entry_list)
        top_layout.addWidget(self.details_panel, 2)

        dash_layout.addLayout(top_layout, 1)

        # BOTTOM: Full Timeline Heatmap (No Scrollbars needed)
        self.heatmap_wrapper = GlassPanel()
        hw_layout = QVBoxLayout(self.heatmap_wrapper)
        hw_layout.setContentsMargins(15, 10, 15, 10)
        
        heatmap_title = QLabel("Activity Timeline")
        heatmap_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #88C0D0; margin-bottom: 5px;")
        hw_layout.addWidget(heatmap_title)
        
        self.timeline_widget = TimelineHeatmap()
        self.timeline_widget.dateClicked.connect(self._on_dashboard_date_clicked)
        hw_layout.addWidget(self.timeline_widget)
        
        dash_layout.addWidget(self.heatmap_wrapper, 0)

        self.right_stack.addWidget(self.dashboard_pane)
        self.right_stack.setCurrentIndex(0)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setStyleSheet("""
            QToolBar {
                background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12);
                border-radius: 10px; margin: 6px; padding: 4px;
            }
            QToolButton { color: #E5E9F0; padding: 6px 10px; }
            QToolButton:hover { background: rgba(255,255,255,.08); border-radius: 8px; }
        """)
        self.addToolBar(Qt.TopToolBarArea, tb)

        act_new = QAction("New", self, triggered=self.new_entry, shortcut="Ctrl+N")
        act_save = QAction("Save", self, triggered=self.save_entry, shortcut="Ctrl+S")
        act_del = QAction("Delete", self, triggered=self.delete_entry)
        act_img = QAction("Add Image", self, triggered=self.add_image)
        act_tag = QAction("Add Tag", self, triggered=self.add_tag)
        act_dash = QAction("Dashboard", self, triggered=self.open_dashboard)
        self.act_focus = QAction("Focus Mode", self, triggered=self.toggle_focus, shortcut="Ctrl+F")
        act_settings = QAction("Settings", self, triggered=self.open_settings)

        for a in (act_new, act_save, act_del, act_img, act_tag, act_dash, self.act_focus, act_settings):
            tb.addAction(a)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #A3BE8C; font-size: 11px; padding-right: 15px; font-weight: bold;")
        tb.addWidget(self.status_label)

    def _setup_timers(self):
        self.autosave_timer = QTimer(interval=AUTOSAVE_INTERVAL_MS, timeout=self.auto_save)
        self.autosave_timer.start()

        self.preview_timer = QTimer(singleShot=True, timeout=self.update_preview)
        self.text_editor.textChanged.connect(self.schedule_preview)

        # Idle Lock
        self.lock_timer = QTimer(self)
        self.lock_timer.timeout.connect(self.lock_app)
        self.apply_lock_timer_settings()

        self.activity_filter = ActivityFilter()
        self.activity_filter.activity_occurred.connect(self.reset_lock_timer)
        QApplication.instance().installEventFilter(self.activity_filter)

    def _setup_menus(self):
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

    def toggle_focus(self):
        self.focus_mode = not self.focus_mode
        self.sidebar.setVisible(not self.focus_mode)
        
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
            self.show_status("Settings Saved")

    # ---------- Idle Lock ----------
    def apply_lock_timer_settings(self):
        self.lock_timer.stop()
        if not self.app_config.get("lock_enabled", True): return
        val = self.app_config.get("lock_val", 5)
        unit = self.app_config.get("lock_unit", "Minutes")
        ms = val * 60 * 1000 if unit == "Minutes" else val * 1000
        self.lock_timer.setInterval(ms)
        self.lock_timer.start()

    def reset_lock_timer(self):
        if self.lock_timer.isActive(): self.lock_timer.start()

    def lock_app(self):
        self.lock_timer.stop()
        self.hide() 
        
        while True:
            pw, ok = QInputDialog.getText(None, "App Locked", "Enter master password to unlock:", QLineEdit.Password)
            if not ok: sys.exit(0)
            
            try:
                with open(SALT_FILE, "rb") as f: salt = f.read()
                with open(VERIFY_FILE, "rb") as f: token = f.read()
                test_crypto = CryptoManager(pw, salt)
                if test_crypto.decrypt(token) == b"DIARY_VERIFIED": break
            except Exception:
                QMessageBox.warning(None, "Error", "Incorrect password")
                
        self.show()
        self.apply_lock_timer_settings()

    # ---------- Preview ----------
    def schedule_preview(self):
        self.preview_timer.start(PREVIEW_DEBOUNCE_MS)

    def update_preview(self):
        fmt = getattr(self.current_entry, "format", "markdown") if self.current_entry else "markdown"
        text = self.text_editor.toPlainText()

        for uid, (_, _, b64) in self.entry_images.items():
            text = text.replace(f"(image://{uid})", f"(data:image/png;base64,{b64})")
            text = text.replace(f"image://{uid}", f"data:image/png;base64,{b64})")

        if fmt == "text":
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe = safe.replace("\n", "<br>")
            styled = f"<html><head><meta charset='utf-8'><style>{MARKDOWN_CSS}</style></head><body><pre style='font-family:inherit;border:none'>{safe}</pre></body></html>"
            self.preview.setHtml(styled)
        else:
            html = markdown2.markdown(text, extras=MARKDOWN_EXTRAS)
            styled = f"<html><head><meta charset='utf-8'><style>{MARKDOWN_CSS}</style></head><body>{html}</body></html>"
            self.preview.setHtml(styled)

    # ---------- Tags ----------
    def load_tags(self):
        while self.tag_layout.count() > 1:
            item = self.tag_layout.takeAt(0)
            if w := item.widget(): w.deleteLater()

        tag_set = set()
        try:
            all_tags = []
            if hasattr(self.db, "get_all_tags"):
                try: all_tags = list(self.db.get_all_tags())
                except Exception: pass
            rows = []
            try: rows = list(self.db.get_entries())
            except Exception: pass
                
            for r in rows:
                try: tlist = self.db.get_entry_tags(r["id"])
                except Exception: tlist = r.get("tags") or []
                for t in (tlist or []):
                    if t: tag_set.add(t)
                        
            for t in all_tags:
                if t and t in tag_set: tag_set.add(t)
        except Exception:
            pass

        tags_sorted = sorted(tag_set, key=lambda s: s.lower())
        for tag in tags_sorted:
            chip = TagChip(tag, self._toggle_tag_filter)
            self.tag_layout.insertWidget(self.tag_layout.count() - 1, chip)

    def _toggle_tag_filter(self, tag: str):
        if tag in self.active_tags: self.active_tags.remove(tag)
        else: self.active_tags.add(tag)
        self.load_entries(keep_selection=True)

    # ---------- Entry List Helpers ----------
    def _create_entry_item(self, row: dict, tags: List[str], category_name: Optional[str] = None, target_list: QListWidget = None) -> QListWidgetItem:
        if target_list is None: target_list = self.entry_list

        item = QListWidgetItem()
        item.setData(Qt.UserRole, row["id"])
        item.setSizeHint(QSize(100, 64))

        raw_date = row.get("updated_at") or row.get("created_at") or ""
        display_date = "—"
        if raw_date:
            try:
                clean_str = str(raw_date).split(".")[0].replace("T", " ").replace("Z", "")
                dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                display_date = dt.strftime("%b %d, %Y %I:%M %p")
            except Exception:
                display_date = str(raw_date)[:16]

        card = EntryCard(row.get("title") or "Untitled", display_date, tags, category_name)
        card.setStyleSheet(card.styleSheet() + "EntryCard { background: rgba(255,255,255,0.09); }")
        
        target_list.addItem(item)
        target_list.setItemWidget(item, card)
        return item

    def _stable_sort(self, rows: List[dict]) -> List[dict]:
        key = lambda r: r.get("updated_at") or r.get("created_at") or ""
        return sorted(rows, key=key, reverse=self.sort_desc)

    def _preserve_selection_and_scroll(self):
        selected_id = self.entry_list.currentItem().data(Qt.UserRole) if self.entry_list.currentItem() else None
        scroll = self.entry_list.verticalScrollBar().value()
        return selected_id, scroll

    def _restore_selection_and_scroll(self, selected_id, scroll):
        if selected_id is not None:
            for i in range(self.entry_list.count()):
                it = self.entry_list.item(i)
                if it.data(Qt.UserRole) == selected_id:
                    self.entry_list.setCurrentItem(it)
                    break
        self.entry_list.verticalScrollBar().setValue(scroll)

    # FIXED: Added the missing _select_in_list method back
    def _select_in_list(self, entry_id: int):
        for i in range(self.entry_list.count()):
            item = self.entry_list.item(i)
            if item.data(Qt.UserRole) == entry_id:
                self.entry_list.setCurrentItem(item)
                break

    # ---------- Entries ----------
    def load_entries(self, keep_selection: bool = True, search_text: Optional[str] = None):
        selected_id, scroll = (None, 0)
        if keep_selection: selected_id, scroll = self._preserve_selection_and_scroll()

        try: rows = [dict(r) for r in self.db.get_entries()]
        except Exception: rows = []
            
        filtered: List[dict] = []
        q = (search_text or "").strip().lower()

        for r in rows:
            try: tags = self.db.get_entry_tags(r["id"])
            except Exception: tags = r.get("tags") or []

            if self.active_tags and not self.active_tags.intersection(tags): continue

            if q:
                title = (r.get("title") or "").lower()
                tag_hit = any(q in (t or "").lower() for t in tags)
                try: content = self.crypto.decrypt(r["content"]).decode(errors="ignore").lower()
                except Exception: content = ""
                if not (q in title or tag_hit or q in content): continue

            cat_name = None
            try:
                cid = r.get("category_id") or r.get("category")
                if cid and hasattr(self.db, "get_category"):
                    cat = self.db.get_category(cid)
                    if isinstance(cat, dict): cat_name = cat.get("name")
                    elif isinstance(cat, (list, tuple)): cat_name = cat[1]
            except Exception: cat_name = None

            r["__tags"] = tags
            r["__category_name"] = cat_name
            filtered.append(r)

        filtered = self._stable_sort(filtered)
        self.entries_cache = filtered

        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        for r in filtered: self._create_entry_item(r, r["__tags"], r.get("__category_name"))
        self.entry_list.blockSignals(False)

        self.load_tags()
        self.update_dashboards()

        if keep_selection: self._restore_selection_and_scroll(selected_id, scroll)

    def _find_row(self, entry_id: int) -> Optional[dict]:
        for r in self.entries_cache:
            if r["id"] == entry_id: return r
        try:
            for r in self.db.get_entries():
                rd = dict(r)
                if rd["id"] == entry_id: return rd
        except Exception: pass
        return None

    def _on_list_item_clicked(self, item: QListWidgetItem):
        if not item: return
        self.right_stack.setCurrentIndex(1)
        entry_id = item.data(Qt.UserRole)
        row = self._find_row(entry_id)
        if not row: return

        try: tags = self.db.get_entry_tags(row["id"])
        except Exception: tags = row.get("tags") or []

        try: images_meta = self.db.get_entry_images(row["id"])
        except Exception: images_meta = []

        self.entry_images = {}
        for uid, name in images_meta:
            try:
                decrypted_bytes = decrypt_image_from_file(self.crypto, uid)
                b64 = base64.b64encode(decrypted_bytes).decode()
                self.entry_images[uid] = (name, decrypted_bytes, b64)
            except Exception: pass

        try: content = self.crypto.decrypt(row["content"]).decode(errors="ignore")
        except Exception: content = ""

        fmt = row.get("format") or "markdown"
        category_id = row.get("category_id") or row.get("category") or None

        self.current_entry = Entry(
            row["id"], row.get("title"), content,
            row.get("created_at"), row.get("updated_at"),
            tags, list(self.entry_images.items()), None
        )
        setattr(self.current_entry, "format", fmt)
        setattr(self.current_entry, "category_id", category_id)
        setattr(self.current_entry, "content", content)

        self.text_editor.blockSignals(True)
        self.text_editor.setPlainText(content)
        self.text_editor.blockSignals(False)
        self.update_preview()

    # ---------- Unified Dashboard Logic ----------
    def open_dashboard(self):
        self.right_stack.setCurrentIndex(2)

    def update_dashboards(self):
        # 1. Update Timeline
        self.timeline_widget.set_data(self.entries_cache)
        
        # 2. Update Calendar formatting
        for d in self.formatted_dates:
            self.calendar_widget.setDateTextFormat(d, QTextCharFormat())
        self.formatted_dates.clear()

        day_counts = collections.Counter()
        month_counts = collections.Counter()
        
        for r in self.entries_cache:
            d_str = r.get("created_at") or r.get("updated_at")
            if d_str:
                try:
                    clean_str = str(d_str).split(".")[0].replace("T", " ").replace("Z", "")
                    dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                    day_counts[QDate(dt.year, dt.month, dt.day)] += 1
                    month_counts[(dt.year, dt.month)] += 1
                except Exception:
                    pass

        # Apply Heatmap to Calendar
        for qdate, count in day_counts.items():
            fmt = QTextCharFormat()
            alpha = min(255, 80 + count * 40)
            fmt.setBackground(QColor(136, 192, 208, alpha))
            fmt.setForeground(QColor(255, 255, 255))
            fmt.setFontWeight(QFont.Bold)
            self.calendar_widget.setDateTextFormat(qdate, fmt)
            self.formatted_dates.append(qdate)
            
        # Update Archive
        self.archive_list.clear()
        sorted_months = sorted(month_counts.keys(), reverse=True)
        for year, month in sorted_months:
            month_name = QDate(year, month, 1).toString("MMMM yyyy")
            count = month_counts[(year, month)]
            item = QListWidgetItem(f"{month_name}  [{count}]")
            item.setData(Qt.UserRole, (year, month))
            self.archive_list.addItem(item)

    def _on_archive_month_clicked(self, item: QListWidgetItem):
        year, month = item.data(Qt.UserRole)
        self.calendar_widget.setCurrentPage(year, month)

    def _on_dashboard_date_clicked(self, date: QDate):
        # Synchronize both widgets
        self.timeline_widget.set_selected_date(date)
        
        self.calendar_widget.blockSignals(True)
        self.calendar_widget.setSelectedDate(date)
        self.calendar_widget.blockSignals(False)

        # Update List
        self.dash_entry_list.clear()
        matched = []
        for r in self.entries_cache:
            d_str = r.get("created_at") or r.get("updated_at")
            if d_str:
                try:
                    clean_str = str(d_str).split(".")[0].replace("T", " ").replace("Z", "")
                    dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                    if dt.year == date.year() and dt.month == date.month() and dt.day == date.day():
                        matched.append(r)
                except Exception:
                    pass
                    
        count = len(matched)
        date_str = date.toString("MMMM d, yyyy")
        self.dash_date_label.setText(f"{count} Entries on {date_str}")
                    
        for r in matched:
            self._create_entry_item(r, r.get("__tags", []), r.get("__category_name"), target_list=self.dash_entry_list)

    def _on_dash_list_item_clicked(self, item: QListWidgetItem):
        entry_id = item.data(Qt.UserRole)
        self._select_in_list(entry_id)
        main_item = self.entry_list.currentItem()
        if main_item:
            self._on_list_item_clicked(main_item)

    # ---------- Entry Operations ----------
    def new_entry(self):
        self.right_stack.setCurrentIndex(1)
        self.current_entry = None
        self.entry_images.clear()
        self.text_editor.clear()
        self.preview.clear()

    def save_entry(self):
        content = self.text_editor.toPlainText()
        if not content.strip(): return

        title = (content.split("\n")[0][:100] or "Untitled").strip()
        images_data = [(uid, name) for uid, (name, _, _) in self.entry_images.items()]
        tags = getattr(self.current_entry, "tags", [])
        enc_content = self.crypto.encrypt(content.encode())

        if self.current_entry and getattr(self.current_entry, "id", None):
            entry_id = self.current_entry.id
            old_content = getattr(self.current_entry, "content", "")
            old_title = getattr(self.current_entry, "title", "")
            old_images = [uid for uid, _ in getattr(self.current_entry, "images", [])]

            changed = (content != old_content or title != old_title or [uid for uid, _ in images_data] != old_images)
            if changed:
                try: self.db.update_entry(entry_id, title, enc_content, tags, images_data, update_timestamp=True)
                except TypeError: self.db.update_entry(entry_id, title, enc_content, tags, images_data)

            self.current_entry.title = title
            self.current_entry.content = content
            self.current_entry.images = list(self.entry_images.items())

        else:
            try: entry_id = self.db.add_entry(title, enc_content, tags, images_data)
            except Exception as e: return

            self.current_entry = Entry(
                id=entry_id, title=title, content=content,
                created_at=None, updated_at=None, tags=tags,
                images=list(self.entry_images.items()),
            )

        current_search = self.search_bar.text()
        self.load_entries(keep_selection=True, search_text=current_search)
        if getattr(self.current_entry, "id", None):
            self._select_in_list(self.current_entry.id)
        self.show_status("Saved")

    def delete_entry(self):
        if not self.current_entry: return
        if QMessageBox.question(self, "Confirm Delete", "Delete this entry?") == QMessageBox.Yes:
            try: self.db.delete_entry(self.current_entry.id)
            except Exception: pass
            self.current_entry = None
            self.entry_images.clear()
            self.text_editor.clear()
            self.preview.clear()
            self.right_stack.setCurrentIndex(0)
            self.load_entries(keep_selection=False)

    def add_image(self):
        if not self.current_entry:
            QMessageBox.warning(self, "No Entry", "Create or select an entry first")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select Image")
        if path:
            try:
                uid, name = encrypt_image_to_file(self.crypto, path)
                decrypted_bytes = decrypt_image_from_file(self.crypto, uid)
                b64 = base64.b64encode(decrypted_bytes).decode()
                self.entry_images[uid] = (name, decrypted_bytes, b64)
                self.text_editor.append(f"![{name}](image://{uid})")
                self.update_preview()
            except Exception:
                QMessageBox.warning(self, "Image Error", "Failed to add image.")

    def add_tag(self):
        if not self.current_entry or not getattr(self.current_entry, "id", None):
            QMessageBox.warning(self, "No Entry", "Create or select an entry first")
            return

        tag, ok = QInputDialog.getText(self, "Add Tag", "Enter tag:")
        if ok and (tag := tag.strip()):
            if tag not in self.current_entry.tags:
                self.current_entry.tags.append(tag)
                self._persist_tags(self.current_entry)
                self.load_tags()
                self.load_entries(keep_selection=True)

    def _persist_tags(self, entry: Entry):
        if not entry or not getattr(entry, "id", None): return
        try:
            if hasattr(self.db, "set_entry_tags"): self.db.set_entry_tags(entry.id, entry.tags)
            else:
                images_data = [(uid, name) for uid, (name, _, _) in getattr(entry, "images", [])]
                try: self.db.update_entry(entry.id, getattr(entry, "title", "Untitled"), self.crypto.encrypt(getattr(entry, "content", "").encode()), entry.tags, images_data, update_timestamp=False)
                except TypeError: self.db.update_entry(entry.id, getattr(entry, "title", "Untitled"), self.crypto.encrypt(getattr(entry, "content", "").encode()), entry.tags, images_data)
        except Exception: pass

    def edit_tags_dialog(self):
        if not self.current_entry:
            QMessageBox.warning(self, "No Entry", "Select an entry first")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Tags")
        layout = QVBoxLayout(dlg)

        listw = QListWidget()
        for t in list(self.current_entry.tags): listw.addItem(t)
        layout.addWidget(listw)

        btns = QDialogButtonBox()
        add_btn = btns.addButton("Add", QDialogButtonBox.ActionRole)
        edit_btn = btns.addButton("Edit", QDialogButtonBox.ActionRole)
        remove_btn = btns.addButton("Remove", QDialogButtonBox.ActionRole)
        close_btn = btns.addButton(QDialogButtonBox.Close)
        layout.addWidget(btns)

        def on_add():
            t, ok = QInputDialog.getText(dlg, "Add Tag", "Tag:")
            if ok and (tt := t.strip()):
                if tt not in [listw.item(i).text() for i in range(listw.count())]: listw.addItem(tt)
        def on_edit():
            it = listw.currentItem()
            if not it: return
            newt, ok = QInputDialog.getText(dlg, "Edit Tag", "Tag:", text=it.text())
            if ok and (nt := newt.strip()): it.setText(nt)
        def on_remove():
            it = listw.currentItem()
            if it: listw.takeItem(listw.row(it))

        add_btn.clicked.connect(on_add)
        edit_btn.clicked.connect(on_edit)
        remove_btn.clicked.connect(on_remove)
        close_btn.clicked.connect(dlg.accept)

        if dlg.exec() == QDialog.Accepted:
            new_tags = [listw.item(i).text() for i in range(listw.count())]
            self.current_entry.tags = new_tags
            self._persist_tags(self.current_entry)
            self.load_tags()
            self.load_entries(keep_selection=True)

    def refresh_entries(self):
        current_search = self.search_bar.text()
        self.load_entries(keep_selection=True, search_text=current_search)
        self.show_status("List Refreshed")

    def toggle_sort(self):
        self.sort_desc = not self.sort_desc
        self.act_sort.setText("Sort: Updated ↓" if self.sort_desc else "Sort: Updated ↑")
        self.load_entries(keep_selection=True)

    def search_entries(self, text: str):
        self.load_entries(keep_selection=True, search_text=text)

    def auto_save(self):
        if self.text_editor.toPlainText().strip():
            self.save_entry()
            self.show_status("")

    # ---------- Context menus ----------
    def _show_entry_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("New Entry", self.new_entry)
        menu.addAction("Save Entry", self.save_entry)
        menu.addAction("Delete Entry", self.delete_entry)
        menu.addSeparator()

        menu.addAction("Create Category...", self._create_category_from_menu)
        move_menu = menu.addMenu("Move to Category")
        try: cats = self.db.get_categories()
        except Exception: cats = []

        if not cats:
            act = move_menu.addAction("(no categories)")
            act.setEnabled(False)
        else:
            for cid, name in cats:
                act = move_menu.addAction(name)
                act.triggered.connect(lambda checked=False, _cid=cid: self._move_selected_entry_to_category(_cid))

        menu.addSeparator()
        menu.addAction("Refresh", self.refresh_entries)
        menu.addAction("Toggle Sort", self.toggle_sort)
        menu.exec(self.entry_list.mapToGlobal(pos))

    def _create_category_from_menu(self):
        name, ok = QInputDialog.getText(self, "Create Category", "Category name:")
        if ok and (n := name.strip()):
            try: self.db.add_category(n)
            except Exception: pass
            self.load_entries(keep_selection=True)
            QMessageBox.information(self, "Category", f"Category '{n}' created.")

    def _move_selected_entry_to_category(self, category_id: int):
        it = self.entry_list.currentItem()
        if not it or not self.current_entry: return
        entry_id = it.data(Qt.UserRole)
        try: self.db.update_entry_category(entry_id, category_id)
        except Exception: pass
        self.load_entries(keep_selection=True)

    def _show_editor_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Add Image", self.add_image)
        menu.addAction("Add Tag", self.add_tag)
        menu.addAction("Edit Tags…", self.edit_tags_dialog)

        fmt_menu = menu.addMenu("Set Format")
        fmt_menu.addAction("Markdown", lambda: self._set_format_for_current("markdown"))
        fmt_menu.addAction("Text", lambda: self._set_format_for_current("text"))

        menu.addSeparator()
        menu.addAction("Save Entry", self.save_entry)
        menu.exec(self.text_editor.mapToGlobal(pos))

    def _set_format_for_current(self, fmt: str):
        if not self.current_entry:
            self.current_entry = Entry(None, None, "", None, None, [], [], None)
            setattr(self.current_entry, "content", "")
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

    pw, ok = QInputDialog.getText(None, "Master Password", "Enter master password:", QLineEdit.Password)
    if not ok or not pw:
        sys.exit(0)

    crypto = CryptoManager(pw, salt)
    db = DatabaseManager() 
    
    if not os.path.exists(SALT_FILE):
        with open(SALT_FILE, "wb") as f:
            try: f.write(crypto.salt)
            except Exception: pass

    if not os.path.exists(VERIFY_FILE):
        try:
            entries = list(db.get_entries())
            if entries: crypto.decrypt(entries[0]["content"])
        except Exception:
            QMessageBox.critical(None, "Access Denied", "Incorrect master password for existing data!")
            sys.exit(1)
            
        with open(VERIFY_FILE, "wb") as f:
            f.write(crypto.encrypt(b"DIARY_VERIFIED"))
    else:
        with open(VERIFY_FILE, "rb") as f:
            encrypted_token = f.read()
        try:
            if crypto.decrypt(encrypted_token) != b"DIARY_VERIFIED":
                raise Exception("Mismatch")
        except Exception:
            QMessageBox.critical(None, "Access Denied", "Incorrect master password!")
            sys.exit(1) 

    window = DiaryApp(crypto, db)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
