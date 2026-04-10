import sqlite3
import os
from datetime import datetime

DB_FILE = "Data/diary.db"

class DatabaseManager:
    def __init__(self):
        os.makedirs("Data", exist_ok=True)
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        
        # Entries table
        c.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content BLOB,
            created_at TEXT,
            updated_at TEXT,
            category TEXT
        )
        """)
        
        # Tags table
        c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
        """)
        
        # Entry-Tag relation
        c.execute("""
        CREATE TABLE IF NOT EXISTS entry_tags (
            entry_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY(entry_id, tag_id),
            FOREIGN KEY(entry_id) REFERENCES entries(id),
            FOREIGN KEY(tag_id) REFERENCES tags(id)
        )
        """)
        
        # Images table
        c.execute("""
        CREATE TABLE IF NOT EXISTS entry_images (
            entry_id INTEGER,
            uuid TEXT,
            name TEXT,
            PRIMARY KEY(entry_id, uuid),
            FOREIGN KEY(entry_id) REFERENCES entries(id)
        )
        """)
        
        # Categories table
        c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
        """)
        
        self.conn.commit()

    def clean_orphaned_tags(self):
        """MAGIC SWEEPER: Automatically deletes tags from the master database if no entry is using them."""
        c = self.conn.cursor()
        c.execute("""
            DELETE FROM tags 
            WHERE id NOT IN (SELECT DISTINCT tag_id FROM entry_tags)
        """)
        self.conn.commit()

    # ---------------- Entry Operations ----------------
    def add_entry(self, title, content, tags=None, images=None, category=None):
        tags = tags or []
        images = images or []
        now = datetime.now().isoformat()
        
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO entries (title, content, created_at, updated_at, category) VALUES (?,?,?,?,?)",
            (title, content, now, now, category)
        )
        entry_id = c.lastrowid
        
        self._update_tags(entry_id, tags)
        self._update_images(entry_id, images)
        self.conn.commit()
        return entry_id

    def update_entry(self, entry_id, title, content, tags=None, images=None, category=None, update_timestamp=True):
        tags = tags or []
        images = images or []
        c = self.conn.cursor()
        
        if update_timestamp:
            now = datetime.now().isoformat()
            c.execute(
                "UPDATE entries SET title=?, content=?, updated_at=?, category=? WHERE id=?",
                (title, content, now, category, entry_id)
            )
        else:
            c.execute(
                "UPDATE entries SET title=?, content=?, category=? WHERE id=?",
                (title, content, category, entry_id)
            )
            
        self._update_tags(entry_id, tags)
        self._update_images(entry_id, images)
        self.conn.commit()

    def delete_entry(self, entry_id):
        c = self.conn.cursor()
        c.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        c.execute("DELETE FROM entry_tags WHERE entry_id=?", (entry_id,))
        c.execute("DELETE FROM entry_images WHERE entry_id=?", (entry_id,))
        self.conn.commit()
        self.clean_orphaned_tags()  # Triggers sweeper after entry deletion

    def get_entries(self):
        c = self.conn.cursor()
        c.execute("SELECT * FROM entries ORDER BY updated_at DESC")
        return c.fetchall()

    # ---------------- Tag Operations ----------------
    def get_all_tags(self):
        c = self.conn.cursor()
        c.execute("SELECT name FROM tags ORDER BY name ASC")
        return [row["name"] for row in c.fetchall()]

    def get_entry_tags(self, entry_id):
        c = self.conn.cursor()
        c.execute("""
        SELECT t.name FROM tags t
        JOIN entry_tags et ON t.id = et.tag_id
        WHERE et.entry_id=?
        """, (entry_id,))
        return [row["name"] for row in c.fetchall()]

    def _update_tags(self, entry_id, tags):
        c = self.conn.cursor()
        c.execute("DELETE FROM entry_tags WHERE entry_id=?", (entry_id,))
        for tag in tags:
            c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            c.execute("SELECT id FROM tags WHERE name=?", (tag,))
            tag_id = c.fetchone()["id"]
            c.execute("INSERT INTO entry_tags (entry_id, tag_id) VALUES (?,?)", (entry_id, tag_id))
            
        self.conn.commit()
        self.clean_orphaned_tags()  # Triggers sweeper after updating tags

    def set_entry_tags(self, entry_id, tags):
        """Directly overwrites tags for an entry from main.py"""
        self._update_tags(entry_id, tags)

    def delete_tag(self, tag_name):
        """Forcefully deletes a tag everywhere globally"""
        c = self.conn.cursor()
        c.execute("SELECT id FROM tags WHERE name=?", (tag_name,))
        row = c.fetchone()
        
        if row:
            tag_id = row["id"]
            c.execute("DELETE FROM entry_tags WHERE tag_id=?", (tag_id,))
            c.execute("DELETE FROM tags WHERE id=?", (tag_id,))
            self.conn.commit()

    # ---------------- Image Operations ----------------
    def _update_images(self, entry_id, images):
        c = self.conn.cursor()
        c.execute("DELETE FROM entry_images WHERE entry_id=?", (entry_id,))
        for uid, name in images:
            c.execute(
                "INSERT INTO entry_images (entry_id, uuid, name) VALUES (?,?,?)",
                (entry_id, uid, name)
            )

    def get_entry_images(self, entry_id):
        c = self.conn.cursor()
        c.execute("SELECT uuid, name FROM entry_images WHERE entry_id=?", (entry_id,))
        return [(row["uuid"], row["name"]) for row in c.fetchall()]

    # ---------------- Category Operations ----------------
    def add_category(self, name):
        c = self.conn.cursor()
        c.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        self.conn.commit()

    def get_categories(self):
        c = self.conn.cursor()
        c.execute("SELECT id, name FROM categories ORDER BY name ASC")
        return [(row["id"], row["name"]) for row in c.fetchall()]

    def get_category(self, identifier):
        """Fetches a specific category by its ID or Name for the UI."""
        c = self.conn.cursor()
        if isinstance(identifier, int) or str(identifier).isdigit():
            c.execute("SELECT id, name FROM categories WHERE id=?", (int(identifier),))
        else:
            c.execute("SELECT id, name FROM categories WHERE name=?", (identifier,))
            
        row = c.fetchone()
        return (row["id"], row["name"]) if row else None

    def update_entry_category(self, entry_id, category_id):
        """Moves an entry to a new category, or removes it if category_id is None"""
        c = self.conn.cursor()
        
        if category_id is None:
            # Handles the "Move to None" action
            c.execute(
                "UPDATE entries SET category=NULL, updated_at=? WHERE id=?",
                (datetime.now().isoformat(), entry_id)
            )
        else:
            c.execute("SELECT name FROM categories WHERE id=?", (category_id,))
            row = c.fetchone()
            if row:
                category_name = row["name"]
                c.execute(
                    "UPDATE entries SET category=?, updated_at=? WHERE id=?",
                    (category_name, datetime.now().isoformat(), entry_id)
                )
                
        self.conn.commit()

    def delete_category(self, category_id):
        """Deletes a folder and removes its reference from all associated entries"""
        c = self.conn.cursor()
        
        # First, find the category name so we can un-link the entries safely
        c.execute("SELECT name FROM categories WHERE id=?", (category_id,))
        row = c.fetchone()
        
        if row:
            category_name = row["name"]
            # Set all entries in this category to NULL (no category)
            c.execute("UPDATE entries SET category=NULL WHERE category=?", (category_name,))
            
        # Delete the actual category
        c.execute("DELETE FROM categories WHERE id=?", (category_id,))
        self.conn.commit()
