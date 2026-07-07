"""
models/barang.py — Model Kategori + Barang.

Tabel: `kategori`, `barang`
Peran:
  - Kategori: klasifikasi barang + tarif denda per hari
  - Barang: inventaris barang yang dapat dipinjam

Pilar OOP (terkonsentrasi di file ini):
  - **Inheritance**: `Barang` mewarisi `BarangBase` (ABC) → barang WAJIB
    punya method `hitung_denda()` dan `get_info()`.
  - **Polymorphism**: implementasi `hitung_denda()` mendelegasikan ke
    `kategori.tarif_denda_per_hari`. Kategori berbeda → denda berbeda.
    Caller code tidak perlu tahu kategori apa — cukup panggil `.hitung_denda()`.
  - **Encapsulation**: `set_kondisi()` & `set_status()` memvalidasi input.
"""
from models import db, generate_uuid, utcnow
from models.base import BarangBase

# ── Konstanta Enum (mengacu arsitektur-db §8) ─────────────────
KONDISI_BARANG = ("baik", "perlu_perbaikan", "rusak")
STATUS_BARANG = ("tersedia", "dipinjam", "perbaikan", "dihapus")


class Kategori(db.Model):
    """Klasifikasi barang yang menentukan tarif denda per hari."""

    __tablename__ = "kategori"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    nama = db.Column(db.String(50), unique=True, nullable=False)
    tarif_denda_per_hari = db.Column(db.Integer, nullable=False)  # Rupiah
    deskripsi = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────
    barang_list = db.relationship(
        "Barang",
        backref=db.backref("kategori", lazy="joined"),
        lazy=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "tarif_denda_per_hari >= 0",
            name="ck_kategori_tarif_denda_positive",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nama": self.nama,
            "tarif_denda_per_hari": self.tarif_denda_per_hari,
            "deskripsi": self.deskripsi,
        }

    def __repr__(self) -> str:
        return f"<Kategori {self.nama}>"


class Barang(db.Model, BarangBase):
    """
    Inventaris barang yang dapat dipinjam.

    Mengimplementasikan `BarangBase` (ABC) — wajib mengoverride
    `hitung_denda()` dan `get_info()`.
    """

    __tablename__ = "barang"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    nama = db.Column(db.String(100), nullable=False)
    kategori_id = db.Column(
        db.String(36),
        db.ForeignKey("kategori.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jumlah_unit = db.Column(db.Integer, nullable=False, default=1)
    kondisi = db.Column(db.String(20), nullable=False, default="baik")
    status = db.Column(db.String(20), nullable=False, default="tersedia")
    deskripsi = db.Column(db.Text, nullable=True)
    foto_path = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    # Soft delete: NULL = aktif; diisi timestamp = "dihapus"
    deleted_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("jumlah_unit > 0", name="ck_barang_jumlah_unit_positive"),
        db.Index("idx_barang_nama", "nama"),
        db.Index("idx_barang_kategori_id", "kategori_id"),
        db.Index("idx_barang_status", "status"),
    )

    # ── Encapsulation: Controlled Mutators ────────────────────
    def set_kondisi(self, kondisi_baru: str) -> None:
        """Ubah kondisi barang dengan validasi nilai enum."""
        if kondisi_baru not in KONDISI_BARANG:
            raise ValueError(
                f"Kondisi tidak valid. Pilihan: {', '.join(KONDISI_BARANG)}"
            )
        self.kondisi = kondisi_baru
        # Sinkron status: rusak → tidak boleh 'tersedia'
        if kondisi_baru == "rusak" and self.status == "tersedia":
            self.status = "perbaikan"

    def set_status(self, status_baru: str) -> None:
        """Ubah status barang dengan validasi nilai enum."""
        if status_baru not in STATUS_BARANG:
            raise ValueError(
                f"Status tidak valid. Pilihan: {', '.join(STATUS_BARANG)}"
            )
        self.status = status_baru

    def soft_delete(self) -> None:
        """Tandai barang sebagai dihapus (tidak benar-benar dihapus)."""
        self.deleted_at = utcnow()
        self.status = "dihapus"

    @property
    def is_deleted(self) -> bool:
        """True jika barang sudah di-soft-delete."""
        return self.deleted_at is not None

    # ── Pilar OOP: Implementasi BarangBase (ABC) ──────────────
    def hitung_denda(self, hari_terlambat: int) -> int:
        """
        Hitung denda keterlambatan berdasarkan tarif kategori.

        **Polymorphism**: tarif diambil dari relasi `self.kategori`,
        sehingga barang elektronik, furniture, dan peralatan akan
        menghasilkan denda berbeda untuk jumlah hari yang sama —
        tanpa caller perlu tahu jenisnya.
        """
        if hari_terlambat <= 0:
            return 0
        return hari_terlambat * self.kategori.tarif_denda_per_hari

    def get_info(self) -> dict:
        """Ringkasan info barang untuk display."""
        return {
            "id": self.id,
            "nama": self.nama,
            "kategori": self.kategori.nama if self.kategori else None,
            "jumlah_unit": self.jumlah_unit,
            "kondisi": self.kondisi,
            "status": self.status,
            "foto_path": self.foto_path,
            "is_deleted": self.is_deleted,
        }

    def to_dict(self) -> dict:
        return {
            **self.get_info(),
            "kategori_id": self.kategori_id,
            "deskripsi": self.deskripsi,
            "tarif_denda_per_hari": (
                self.kategori.tarif_denda_per_hari if self.kategori else None
            ),
        }

    def __repr__(self) -> str:
        return f"<Barang {self.nama} ({self.status})>"
