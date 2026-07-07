"""
models/__init__.py — Inisialisasi layer Model untuk SIPINBAR.

Mendefinisikan:
  - `db`: instance tunggal SQLAlchemy (di-import oleh semua model file)
  - `generate_uuid()`: helper untuk UUID v4 string sebagai PK
  - Import semua model class agar ter-register di SQLAlchemy metadata

Pilar OOP yang terlihat di sini:
  - **Encapsulation**: akses field diatur via @property di tiap class
  - **Inheritance**: class `Barang` mewarisi `BarangBase` (ABC) — lihat barang.py
  - **Polymorphism**: `Barang.hitung_denda()` berbeda per kategori (delegate)
  - **Abstraction**: kontrak method abstract di `base.py`

Pola impor (catatan untuk developer lain):
  File model selalu mengimpor `db` dan `generate_uuid` dari sini:
      from models import db, generate_uuid
"""
import uuid
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

# Instance tunggal SQLAlchemy — di-init di app.py via db.init_app(app)
db: SQLAlchemy = SQLAlchemy()


def generate_uuid() -> str:
    """Generate UUID v4 string (36 karakter) untuk Primary Key."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return current UTC datetime sebagai **naive** datetime.

    Drop-in replacement untuk ``datetime.utcnow()`` yang deprecated sejak
    Python 3.12. Mengembalikan datetime naive (tanpa tzinfo) agar konsisten
    dengan kolom ``db.DateTime`` SQLAlchemy yang menyimpan naive datetime
    di SQLite.

    **Penting untuk anti-spam notifikasi**: semua ``created_at`` memakai
    UTC via helper ini. Filter anti-spam di ``NotifikasiService`` juga
    wajib memakai ``utcnow().date()`` (bukan ``date.today()`` yang local)
    agar perbandingan calendar-day konsisten — mismatch UTC vs local
    adalah root cause bug T-INT-07 (anti-spam gagal di rentang 00:00–07:00
    UTC+N).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Register semua model ke SQLAlchemy.metadata ───────────────
# Import di akhir agar `db` & `generate_uuid` sudah terdefinisi saat
# model file mengimpornya kembali (menghindari circular import).
from models.admin import Admin                 # noqa: E402,F401
from models.warga import Warga                 # noqa: E402,F401
from models.barang import Kategori, Barang     # noqa: E402,F401
from models.peminjaman import (                # noqa: E402,F401
    Peminjaman,
    DetailPeminjaman,
)
from models.notifikasi import (                # noqa: E402,F401
    Notifikasi,
    NotifikasiInApp,
)
from models.laporan import (                   # noqa: E402,F401
    LaporanPeminjaman,
    LaporanInventaris,
)

__all__ = [
    "db",
    "generate_uuid",
    # Model classes
    "Admin",
    "Warga",
    "Kategori",
    "Barang",
    "Peminjaman",
    "DetailPeminjaman",
    "Notifikasi",
    "NotifikasiInApp",
    "LaporanPeminjaman",
    "LaporanInventaris",
]
