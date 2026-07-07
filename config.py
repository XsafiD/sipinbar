"""
config.py — Konfigurasi aplikasi SIPINBAR.

Memuat konfigurasi dari environment variables (file .env) dengan
sensible defaults untuk development lokal.
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# Muat variabel dari .env (tidak error jika file tidak ada)
load_dotenv()

# Base directory = folder tempat config.py berada (root project)
BASE_DIR: str = os.path.abspath(os.path.dirname(__file__))


def _resolve_path(path: str) -> str:
    """
    Resolve path relatif menjadi absolute path berbasis BASE_DIR.

    Flask secara default merekam path relatif di `instance/` folder,
    yang membingungkan. Kita paksa absolute path berbasis root project
    agar konsisten lintas environment.
    """
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


class Config:
    """Konfigurasi default untuk aplikasi SIPINBAR."""

    # ── Keamanan ──────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get(
        "SECRET_KEY", "dev-fallback-secret-key-jangan-dipakai-production"
    )

    # ── Database ──────────────────────────────────────────────
    # Resolve ke absolute path agar tidak terjebak di instance/ folder
    _db_path_env: str = os.environ.get("DATABASE_PATH", "database/sipinbar.db")
    _db_path_abs: str = _resolve_path(_db_path_env)
    # Pastikan parent folder ada
    os.makedirs(os.path.dirname(_db_path_abs), exist_ok=True)
    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{_db_path_abs}"
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        # Penting untuk SQLite: aktifkan FK enforcement via SQLAlchemy
        "echo": False,
        "connect_args": {"check_same_thread": False},
    }

    # ── Upload ────────────────────────────────────────────────
    UPLOAD_FOLDER: str = _resolve_path(
        os.environ.get("UPLOAD_FOLDER", "static/img")
    )
    MAX_CONTENT_LENGTH: int = int(
        os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)  # 5 MB
    )
    ALLOWED_EXTENSIONS: set = {"png", "jpg", "jpeg", "webp"}

    # ── Session ───────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(days=1)

    # ── WTF / CSRF ────────────────────────────────────────────
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600  # detik


class TestConfig(Config):
    """Konfigurasi untuk pengujian (in-memory SQLite, CSRF off)."""

    TESTING: bool = True
    # Override setelah Config.__init__ jalan; pakai in-memory DB
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    WTF_CSRF_ENABLED: bool = False
    SECRET_KEY: str = "test-secret-key-sipinbar"
