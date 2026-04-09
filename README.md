# 📔 Personal Diary

**Personal Diary** is a secure, aesthetically focused desktop application built with **PySide6**. It combines a modern "Glass-morphism" user interface with military-grade encryption to provide a private space for your thoughts, photos, and daily reflections.

## ✨ Key Features

* **Glass UI Aesthetic:** A semi-transparent, modern interface with customizable Markdown themes.
* **Military-Grade Security:** * **Argon2id** key derivation for robust password hashing.
    * **AES-128 (Fernet)** encryption for all entry content and image files.
    * Zero-footprint RAM management (sensitive keys are deleted after derivation).
* **GitHub-Style Heatmap:** Visualize your writing consistency over the past year.
* **Rich Media Support:** Securely attach images to entries; images are encrypted on disk and decrypted only during viewing.
* **Markdown Preview:** Write in Markdown and view rendered output with custom CSS themes (Normal and Cursive/Handwriting).
* **Auto-Lock:** The application automatically locks after a period of inactivity to protect your data.

## 🛠️ Tech Stack

* **Frontend:** PySide6 (Qt for Python)
* **Database:** SQLite3
* **Security:** `cryptography` (Fernet), `argon2-cffi`
* **Imaging:** Pillow (PIL)
* **Formatting:** Markdown

## 📂 Project Structure

```text
├── Data/                 # Created at runtime (Stores DB and encrypted images)
├── resources/
│   └── style/
│       ├── style_normal.css  # Modern Sans-Serif theme
│       └── style1.css        # Cursive Handwriting theme
├── crypto.py             # Encryption logic (Argon2id + Fernet)
├── database.py           # SQLite schema and entry management
├── models.py             # Data models (Entry class)
├── utils.py              # Image processing and encryption helpers
└── main.py               # Main application logic and UI
```

## 🚀 Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/hostaweba/Personal_Diary.git
    cd Personal_Diary
    ```

2.  **Install dependencies:**
    ```bash
    pip install PySide6 cryptography argon2-cffi Pillow markdown
    ```

3.  **Run the application:**
    ```bash
    python main.py
    ```

## 🔐 Security Architecture

Lumina Diary prioritizes data integrity and privacy:
* **Database:** Entry content is stored as encrypted BLOBs. Even with access to the `.db` file, content is unreadable without the master password.
* **Images:** Attached images are renamed to UUIDs and encrypted with `.enc` extensions. They are never stored in a raw state within the project directory.
* **Memory:** The `CryptoManager` derived key is never stored as an instance variable to mitigate the risk of memory scraping.

## 🎨 Customizing Themes

The application supports custom Markdown rendering via CSS. You can modify the look of your entries by editing the files in `resources/style/`:
* **`style_normal.css`**: Best for a clean, professional look.
* **`style1.css`**: Uses the "Dancing Script" font for a traditional journal feel.
