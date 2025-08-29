#!/usr/bin/env python3
import sys
import os
import base64
import platform
from typing import Dict, Tuple, Optional, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QTextEdit, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QTextBrowser, QLineEdit, QLabel, QScrollArea,
    QInputDialog, QMenu, QFileDialog, QMessageBox, QListWidgetItem, QToolBar,
    QSizePolicy, QStyleOption, QStyle, QDialog, QDialogButtonBox, QListWidget
)
from PySide6.QtGui import QColor, QPalette, QAction, QFont, QPainter
from PySide6.QtCore import Qt, QTimer, QSize

import markdown2

# Project modules (must exist in your project)
from crypto import CryptoManager
from database import DatabaseManager
from models import Entry
from utils import encrypt_image_to_file, decrypt_image_from_file

# ---------------- Constants ----------------
APP_TITLE = "Modern Diary"
SALT_FILE = "Data/salt.bin"
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
with open("resources/style/style_normal.css", "r", encoding="utf-8") as f:
    MARKDOWN_CSS = f.read()


# Tag chip style (no unsupported properties)
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


# ---------------- Reusable UI pieces ----------------
class GlassPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            GlassPanel {
                background: rgba(30, 32, 36, 0.6);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 16px;
            }
        """)

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)


class EntryCard(QWidget):
    def __init__(self, title: str, updated: str, tags: Optional[List[str]] = None, category_name: Optional[str] = None):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(2)

        title_lbl = QLabel(title or "Untitled")
        tfont = QFont()
        tfont.setBold(True)
        tfont.setPointSize(11)
        title_lbl.setFont(tfont)
        title_lbl.setStyleSheet("color: #ECEFF4;")
        root.addWidget(title_lbl)

        date_lbl = QLabel(updated or "—")
        date_lbl.setStyleSheet("color: rgba(236,239,244,0.65); font-size: 11px;")
        root.addWidget(date_lbl)

        if category_name:
            cat_lbl = QLabel(f"Category: {category_name}")
            cat_lbl.setStyleSheet("color: #A3BE8C; font-size: 10px;")
            root.addWidget(cat_lbl)

        if tags:
            tags_lbl = QLabel(", ".join(tags))
            tags_lbl.setStyleSheet("color: #88c0d0; font-size: 10px;")
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
    """Clickable tag chip."""
    def __init__(self, text: str, on_click):
        super().__init__(text)
        self.setStyleSheet(TAG_STYLE)
        self.mousePressEvent = lambda event: on_click(text)


# ---------------- Main Application ----------------
class DiaryApp(QMainWindow):
    def __init__(self, crypto: CryptoManager, db: DatabaseManager):
        super().__init__()
        self.crypto = crypto
        self.db = db

        self.current_entry: Optional[Entry] = None
        self.entry_images: Dict[str, Tuple[str, bytes, str]] = {}  # uid -> (name, bytes, b64)
        self.active_tags: set[str] = set()
        self.entries_cache: List[dict] = []  # current filtered+sorted rows
        self.sort_desc: bool = True          # sort by updated_at desc
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 900)

        # Transparent window (glass panels paint backgrounds)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("QMainWindow { background: transparent; }")

        self._build_ui()
        self._build_toolbar()
        self._setup_timers()
        self._setup_menus()

        # Load persistent UI data
        self.load_tags()
        self.load_entries(keep_selection=False)

        # Enable Windows acrylic/blur if available
        enable_windows_blur(self.winId())

    # ---------- UI ----------
    def _build_ui(self):
        # Outer glass background
        self.outer = GlassPanel()
        self.setCentralWidget(self.outer)
        outer_layout = QHBoxLayout(self.outer)
        outer_layout.setContentsMargins(14, 14, 14, 14)
        outer_layout.setSpacing(14)

        # Sidebar glass
        self.sidebar = GlassPanel()
        outer_layout.addWidget(self.sidebar, 3)  # keep UI ratio as before (sidebar smaller)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(10)

        # Tags title + tag list area
        side.addWidget(QLabel("<b style='color:#E5E9F0;'>Tags</b>"))
        self.tag_scroll = QScrollArea(widgetResizable=True)
        self.tag_scroll.setFrameShape(QScrollArea.NoFrame)
        self.tag_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        tag_holder = QWidget()
        self.tag_layout = QVBoxLayout(tag_holder)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.addStretch()
        self.tag_scroll.setWidget(tag_holder)
        side.addWidget(self.tag_scroll)

        # Search
        self.search_bar = QLineEdit(placeholderText="Search (title, tags, content)…")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background: rgba(255,255,255,.08);
                border: 1px solid rgba(255,255,255,.15);
                border-radius: 12px; padding: 8px 10px; color: #E5E9F0;
            }
            QLineEdit:focus { border-color: rgba(136,192,208,.8); background: rgba(255,255,255,.12); }
        """)
        self.search_bar.textChanged.connect(self.search_entries)
        side.addWidget(self.search_bar)

        # Entry list
        self.entry_list = QListWidget()
        self.entry_list.setFrameShape(QListWidget.NoFrame)
        self.entry_list.setAlternatingRowColors(False)
        self.entry_list.setUniformItemSizes(True)
        self.entry_list.setSpacing(8)
        self.entry_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        # Slightly tinted viewport so cards are visible even on very transparent windows
        self.entry_list.viewport().setStyleSheet(
            "background: rgba(12, 14, 18, 0.12); border-radius: 12px;"
        )
        self.entry_list.setStyleSheet("""
            QListWidget {
                background: transparent; color: #ECEFF4; border: none;
            }
            QListWidget::item { margin: 2px 0; }
            QListWidget::item:selected { background: transparent; }
        """)
        self.entry_list.itemClicked.connect(self._on_list_item_clicked)
        # Put entries below search + tags (same UX as before)
        side.addWidget(self.entry_list, 1)

        # Right pane (editor + preview)
        self.right = GlassPanel()
        outer_layout.addWidget(self.right, 7)
        right_layout = QVBoxLayout(self.right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        # Split editor/preview
        self.splitter = QSplitter(Qt.Vertical)

        # Editor
        self.text_editor = QTextEdit()
        self.text_editor.setPlaceholderText("# Title\n\nStart writing…")
        self.text_editor.setStyleSheet("""
            QTextEdit {
                background: rgba(255,255,255,.04);
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px; color: #ECEFF4; padding: 10px;
                selection-background-color: rgba(136,192,208,.3);
            }
        """)

        # Preview
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.setStyleSheet("""
            QTextBrowser {
                background: rgba(255,255,255,.04);
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px; color: #ECEFF4; padding: 10px;
            }
        """)

        self.splitter.addWidget(self.text_editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([600, 400])
        right_layout.addWidget(self.splitter, 1)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setStyleSheet("""
            QToolBar {
                background: rgba(255,255,255,.05);
                border: 1px solid rgba(255,255,255,.12);
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
        act_refresh = QAction("Refresh", self, triggered=self.refresh_entries)
        self.act_sort = QAction("Sort: Updated ↓", self, triggered=self.toggle_sort)

        for a in (act_new, act_save, act_del, act_img, act_tag, act_refresh, self.act_sort):
            tb.addAction(a)

    def _setup_timers(self):
        # Autosave
        self.autosave_timer = QTimer(interval=AUTOSAVE_INTERVAL_MS, timeout=self.auto_save)
        self.autosave_timer.start()

        # Debounced preview
        self.preview_timer = QTimer(singleShot=True, timeout=self.update_preview)
        self.text_editor.textChanged.connect(self.schedule_preview)

    def _setup_menus(self):
        # Context menus
        self.entry_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.entry_list.customContextMenuRequested.connect(self._show_entry_context_menu)

        self.text_editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text_editor.customContextMenuRequested.connect(self._show_editor_context_menu)

        self.tag_scroll.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tag_scroll.customContextMenuRequested.connect(self._show_tag_context_menu)

    # ---------- Preview ----------
    def schedule_preview(self):
        self.preview_timer.start(PREVIEW_DEBOUNCE_MS)

    def update_preview(self):
        # Determine format: default to markdown
        fmt = getattr(self.current_entry, "format", "markdown") if self.current_entry else "markdown"
        # If no current_entry, try to remember last chosen via text-editor placeholder (no stored UI control),
        # but to keep UI/UX unchanged we choose markdown for preview by default.
        text = self.text_editor.toPlainText()

        # Replace custom image scheme with base64 inline
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
        """
        Rebuild the tag panel from tags currently used in entries.
        This ensures tags that are no longer used by any entry disappear.
        """
        # Clear all except the final stretch
        while self.tag_layout.count() > 1:
            item = self.tag_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        # Collect tags from all entries via db.get_entry_tags where possible
        tag_set = set()
        try:
            # If DB provides direct listing of tags, prefer that (but still verify usage)
            all_tags = []
            if hasattr(self.db, "get_all_tags"):
                try:
                    all_tags = list(self.db.get_all_tags())
                except Exception:
                    all_tags = []
            # If DB doesn't have get_all_tags or to ensure tags correspond to entries,
            # scan entries and call get_entry_tags
            rows = []
            try:
                rows = list(self.db.get_entries())
            except Exception:
                rows = []
            for r in rows:
                try:
                    tlist = self.db.get_entry_tags(r["id"])
                except Exception:
                    tlist = r.get("tags") or []
                for t in (tlist or []):
                    if t:
                        tag_set.add(t)
            # as a fallback include all_tags from DB if they exist and are used
            for t in all_tags:
                if t and t in tag_set:
                    tag_set.add(t)
        except Exception:
            tag_set = set()

        # Sort tags for stable order
        tags_sorted = sorted(tag_set, key=lambda s: s.lower())
        for tag in tags_sorted:
            chip = TagChip(tag, self._toggle_tag_filter)
            self.tag_layout.insertWidget(self.tag_layout.count() - 1, chip)

    def _toggle_tag_filter(self, tag: str):
        if tag in self.active_tags:
            self.active_tags.remove(tag)
        else:
            self.active_tags.add(tag)
        self.load_entries(keep_selection=True)

    # ---------- Entry List Helpers ----------
    def _create_entry_item(self, row: dict, tags: List[str], category_name: Optional[str] = None) -> QListWidgetItem:
        """Create a QListWidgetItem + EntryCard widget."""
        item = QListWidgetItem()
        item.setData(Qt.UserRole, row["id"])
        item.setSizeHint(QSize(100, 64))

        card = EntryCard(row.get("title") or "Untitled",
                         row.get("updated_at") or row.get("created_at") or "—",
                         tags, category_name)
        card.setStyleSheet(card.styleSheet() + "EntryCard { background: rgba(255,255,255,0.09); }")
        self.entry_list.addItem(item)
        self.entry_list.setItemWidget(item, card)
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

    # ---------- Entries ----------
    def load_entries(self, keep_selection: bool = True, search_text: Optional[str] = None):
        """Rebuild list with optional search; keeps list order stable on selection."""
        selected_id, scroll = (None, 0)
        if keep_selection:
            selected_id, scroll = self._preserve_selection_and_scroll()

        try:
            rows = [dict(r) for r in self.db.get_entries()]
        except Exception:
            rows = []
        filtered: List[dict] = []
        q = (search_text or "").strip().lower()

        for r in rows:
            try:
                tags = self.db.get_entry_tags(r["id"])
            except Exception:
                tags = r.get("tags") or []

            if self.active_tags and not self.active_tags.intersection(tags):
                continue

            # Search: title, tags, decrypted content
            if q:
                title = (r.get("title") or "").lower()
                tag_hit = any(q in (t or "").lower() for t in tags)
                try:
                    content = self.crypto.decrypt(r["content"]).decode(errors="ignore").lower()
                except Exception:
                    content = ""
                if not (q in title or tag_hit or q in content):
                    continue

            # category name resolution (if DB supports categories)
            cat_name = None
            try:
                cid = r.get("category_id") or r.get("category")
                if cid and hasattr(self.db, "get_category"):
                    cat = self.db.get_category(cid)
                    if isinstance(cat, dict):
                        cat_name = cat.get("name")
                    elif isinstance(cat, (list, tuple)):
                        cat_name = cat[1]
            except Exception:
                cat_name = None

            r["__tags"] = tags
            r["__category_name"] = cat_name
            filtered.append(r)

        filtered = self._stable_sort(filtered)
        self.entries_cache = filtered

        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        for r in filtered:
            self._create_entry_item(r, r["__tags"], r.get("__category_name"))
        self.entry_list.blockSignals(False)

        # rebuild tags panel (keeps tags consistent)
        self.load_tags()

        if keep_selection:
            self._restore_selection_and_scroll(selected_id, scroll)

    def _find_row(self, entry_id: int) -> Optional[dict]:
        for r in self.entries_cache:
            if r["id"] == entry_id:
                return r
        try:
            for r in self.db.get_entries():
                rd = dict(r)
                if rd["id"] == entry_id:
                    return rd
        except Exception:
            pass
        return None

    def _on_list_item_clicked(self, item: QListWidgetItem):
        """Load entry content without changing list order or position."""
        if not item:
            return
        entry_id = item.data(Qt.UserRole)
        row = self._find_row(entry_id)
        if not row:
            return

        try:
            tags = self.db.get_entry_tags(row["id"])
        except Exception:
            tags = row.get("tags") or []

        try:
            images_meta = self.db.get_entry_images(row["id"])
        except Exception:
            images_meta = []

        self.entry_images = {}
        for uid, name in images_meta:
            try:
                decrypted_bytes = decrypt_image_from_file(self.crypto, uid)
                b64 = base64.b64encode(decrypted_bytes).decode()
                self.entry_images[uid] = (name, decrypted_bytes, b64)
            except Exception:
                pass

        try:
            content = self.crypto.decrypt(row["content"]).decode(errors="ignore")
        except Exception:
            content = ""

        fmt = row.get("format") or "markdown"
        category_id = row.get("category_id") or row.get("category") or None

        self.current_entry = Entry(
            row["id"], row.get("title"), content,
            row.get("created_at"), row.get("updated_at"),
            tags, list(self.entry_images.items()), None
        )
        # store metadata on Entry object for UI usage
        setattr(self.current_entry, "format", fmt)
        setattr(self.current_entry, "category_id", category_id)
        setattr(self.current_entry, "content", content)

        self.text_editor.blockSignals(True)
        self.text_editor.setPlainText(content)
        self.text_editor.blockSignals(False)
        self.update_preview()

    # ---------- Entry Operations ----------
    def new_entry(self):
        self.current_entry = None
        self.entry_images.clear()
        self.text_editor.clear()
        self.preview.clear()

    def save_entry(self):
        content = self.text_editor.toPlainText()
        if not content.strip():
            return

        title = (content.split("\n")[0][:100] or "Untitled").strip()
        images_data = [(uid, name) for uid, (name, _, _) in self.entry_images.items()]
        tags = getattr(self.current_entry, "tags", [])
        enc_content = self.crypto.encrypt(content.encode())

        # For existing entry
        if self.current_entry and getattr(self.current_entry, "id", None):
            entry_id = self.current_entry.id

            old_content = getattr(self.current_entry, "content", "")
            old_title = getattr(self.current_entry, "title", "")
            old_images = [uid for uid, _ in getattr(self.current_entry, "images", [])]

            changed = (
                content != old_content or
                title != old_title or
                [uid for uid, _ in images_data] != old_images
            )

            if changed:
                try:
                    self.db.update_entry(
                        entry_id,
                        title,
                        enc_content,
                        tags,
                        images_data,
                        update_timestamp=True
                    )
                except TypeError:
                    self.db.update_entry(entry_id, title, enc_content, tags, images_data)

            # Update in-memory entry
            self.current_entry.title = title
            self.current_entry.content = content
            self.current_entry.images = list(self.entry_images.items())

        else:
            # New entry
            try:
                entry_id = self.db.add_entry(title, enc_content, tags, images_data)
            except Exception as e:
                print(f"Failed to add entry: {e}")
                return

            self.current_entry = Entry(
                id=entry_id,
                title=title,
                content=content,
                created_at=None,
                updated_at=None,
                tags=tags,
                images=list(self.entry_images.items()),
            )

        self.load_entries(keep_selection=True)
        if getattr(self.current_entry, "id", None):
            self._select_in_list(self.current_entry.id)





    def _select_in_list(self, entry_id: int):
        """Select entry in QListWidget by ID."""
        for i in range(self.entry_list.count()):
            item = self.entry_list.item(i)
            if item.data(Qt.UserRole) == entry_id:
                self.entry_list.setCurrentItem(item)
                break

    def delete_entry(self):
        if not self.current_entry:
            return
        if QMessageBox.question(self, "Confirm Delete", "Delete this entry?") == QMessageBox.Yes:
            try:
                self.db.delete_entry(self.current_entry.id)
            except Exception:
                pass
            self.current_entry = None
            self.entry_images.clear()
            self.text_editor.clear()
            self.preview.clear()
            # reload entries; load_tags() will recompute tags and remove unused ones
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
        if not entry or not getattr(entry, "id", None):
            return

        try:
            if hasattr(self.db, "set_entry_tags"):
                self.db.set_entry_tags(entry.id, entry.tags)
            else:
                images_data = [(uid, name) for uid, (name, _, _) in getattr(entry, "images", [])]
                try:
                    self.db.update_entry(
                        entry.id,
                        getattr(entry, "title", "Untitled"),
                        self.crypto.encrypt(getattr(entry, "content", "").encode()),
                        entry.tags,
                        images_data,
                        update_timestamp=False  # prevents date/time update
                    )
                except TypeError:
                    self.db.update_entry(
                        entry.id,
                        getattr(entry, "title", "Untitled"),
                        self.crypto.encrypt(getattr(entry, "content", "").encode()),
                        entry.tags,
                        images_data
                    )
        except Exception as e:
            print(f"Failed to persist tags: {e}")


    def edit_tags_dialog(self):
        """Dialog to add/edit/remove tags for current entry."""
        if not self.current_entry:
            QMessageBox.warning(self, "No Entry", "Select an entry first")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit Tags")
        layout = QVBoxLayout(dlg)

        listw = QListWidget()
        for t in list(self.current_entry.tags):
            listw.addItem(t)
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
                if tt not in [listw.item(i).text() for i in range(listw.count())]:
                    listw.addItem(tt)

        def on_edit():
            it = listw.currentItem()
            if not it:
                return
            newt, ok = QInputDialog.getText(dlg, "Edit Tag", "Tag:", text=it.text())
            if ok and (nt := newt.strip()):
                it.setText(nt)

        def on_remove():
            it = listw.currentItem()
            if it:
                listw.takeItem(listw.row(it))

        add_btn.clicked.connect(on_add)
        edit_btn.clicked.connect(on_edit)
        remove_btn.clicked.connect(on_remove)
        close_btn.clicked.connect(dlg.accept)

        if dlg.exec() == QDialog.Accepted:
            new_tags = [listw.item(i).text() for i in range(listw.count())]
            self.current_entry.tags = new_tags
            self._persist_tags(self.current_entry)  # pass Entry object
            # reload UI lists and tag panel
            self.load_tags()
            self.load_entries(keep_selection=True)


    def refresh_entries(self):
        self.load_entries(keep_selection=True)

    def toggle_sort(self):
        self.sort_desc = not self.sort_desc
        self.act_sort.setText("Sort: Updated ↓" if self.sort_desc else "Sort: Updated ↑")
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

        # Create category action
        menu.addAction("Create Category...", self._create_category_from_menu)

        # Move to category submenu
        move_menu = menu.addMenu("Move to Category")
        try:
            cats = self.db.get_categories()
        except Exception:
            cats = []

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
            try:
                self.db.add_category(n)
            except Exception:
                pass
            self.load_entries(keep_selection=True)
            QMessageBox.information(self, "Category", f"Category '{n}' created.")


    def _move_selected_entry_to_category(self, category_id: int):
        it = self.entry_list.currentItem()
        if not it or not self.current_entry:
            return
        entry_id = it.data(Qt.UserRole)
        try:
            self.db.update_entry_category(entry_id, category_id)
        except Exception:
            pass
        # reload entries and tags
        self.load_entries(keep_selection=True)


    def _show_editor_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Add Image", self.add_image)
        menu.addAction("Add Tag", self.add_tag)
        menu.addAction("Edit Tags…", self.edit_tags_dialog)

        # Format submenu (keeps UI minimal)
        fmt_menu = menu.addMenu("Set Format")
        fmt_menu.addAction("Markdown", lambda: self._set_format_for_current("markdown"))
        fmt_menu.addAction("Text", lambda: self._set_format_for_current("text"))

        menu.addSeparator()
        menu.addAction("Save Entry", self.save_entry)
        menu.exec(self.text_editor.mapToGlobal(pos))

    def _set_format_for_current(self, fmt: str):
        if not self.current_entry:
            # set preview-only behaviour for new entry by storing temporary attribute
            self.current_entry = Entry(None, None, "", None, None, [], [], None)
            setattr(self.current_entry, "content", "")
        setattr(self.current_entry, "format", fmt)
        # Update preview immediately
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

    # Global palette tuned for glass
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(0, 0, 0, 0))  # transparent; glass panels paint themselves
    pal.setColor(QPalette.WindowText, Qt.white)
    pal.setColor(QPalette.Base, QColor(30, 32, 36))
    pal.setColor(QPalette.Text, Qt.white)
    pal.setColor(QPalette.Button, QColor(50, 50, 50))
    pal.setColor(QPalette.ButtonText, Qt.white)
    app.setPalette(pal)

    pw, ok = QInputDialog.getText(None, "Master Password", "Enter master password:", QLineEdit.Password)
    if not ok or not pw:
        return

    crypto = CryptoManager(pw, salt)
    if not os.path.exists(SALT_FILE):
        with open(SALT_FILE, "wb") as f:
            # write salt if CryptoManager provides it
            try:
                f.write(crypto.salt)
            except Exception:
                pass

    db = DatabaseManager()
    window = DiaryApp(crypto, db)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
