"""
models/notifikasi.py — Model Notifikasi + NotifikasiInApp.

Tabel: `notifikasi`
Peran: Pesan in-app pengingat & info status untuk warga.

Pilar OOP:
  - **Abstraction**: `NotifikasiBase` (ABC) mendefinisikan kontrak
    `kirim()` & `get_preview()`.
  - **Inheritance + Polymorphism**: `NotifikasiInApp` mengimplementasikan
    ABC untuk kanal in-app. Kelas turunan lain (mis. NotifikasiEmail,
    NotifikasiWhatsApp) bisa ditambah tanpa mengubah caller.
"""
from typing import Optional, cast

from models import db, generate_uuid, utcnow
from models.base import NotifikasiBase

# ── Konstanta Enum (arsitektur-db §8.6) ───────────────────────
TIPE_NOTIFIKASI = ("pengingat", "info", "peringatan")

# Mapping ikon UI (saran visual)
IKON_TIPE = {
    "pengingat": "bell",         # 🔔
    "info": "info",              # ℹ️
    "peringatan": "alert",       # ⚠️
}


class Notifikasi(db.Model):
    """Pesan notifikasi in-app (tersimpan di DB)."""

    __tablename__ = "notifikasi"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)

    # ── Foreign Keys ──────────────────────────────────────────
    peminjaman_id = db.Column(
        db.String(36),
        db.ForeignKey("peminjaman.id", ondelete="SET NULL"),
        nullable=True,  # nullable: boleh notifikasi umum tanpa peminjaman
    )
    warga_id = db.Column(
        db.String(36),
        db.ForeignKey("warga.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Konten ────────────────────────────────────────────────
    tipe = db.Column(db.String(20), nullable=False)
    judul = db.Column(db.String(100), nullable=False)
    pesan = db.Column(db.Text, nullable=False)

    # ── Status Baca ───────────────────────────────────────────
    is_dibaca = db.Column(db.Boolean, nullable=False, default=False)
    dibaca_at = db.Column(db.DateTime, nullable=True)

    # ── Audit ─────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.Index(
            "idx_notifikasi_warga_id_is_dibaca",
            "warga_id",
            "is_dibaca",
        ),
        db.Index("idx_notifikasi_peminjaman_id", "peminjaman_id"),
    )

    # ── Encapsulation ─────────────────────────────────────────
    def tandai_dibaca(self) -> None:
        """Tandai notifikasi sebagai sudah dibaca (idempoten)."""
        if not self.is_dibaca:
            self.is_dibaca = True
            self.dibaca_at = utcnow()

    def get_ikon(self) -> str:
        """Ikon UI yang sesuai dengan tipe notifikasi."""
        return IKON_TIPE.get(self.tipe, "info")

    def get_preview(self) -> str:
        """Preview singkat untuk list UI."""
        max_len = 80
        if len(self.pesan) <= max_len:
            return self.pesan
        return self.pesan[: max_len - 1] + "…"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "peminjaman_id": self.peminjaman_id,
            "warga_id": self.warga_id,
            "tipe": self.tipe,
            "ikon": self.get_ikon(),
            "judul": self.judul,
            "pesan": self.pesan,
            "preview": self.get_preview(),
            "is_dibaca": self.is_dibaca,
            "dibaca_at": self.dibaca_at.isoformat() if self.dibaca_at else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Notifikasi [{self.tipe}] {self.judul}>"


class NotifikasiInApp(NotifikasiBase):
    """
    Builder/Service class untuk membuat & menyimpan notifikasi in-app.

    Tidak menyimpan state sendiri — bekerja sebagai *factory* yang
    mengkonstruksi instance `Notifikasi`, lalu menyimpan ke DB.

    Memenuhi kontrak `NotifikasiBase` (ABC).

    Usage:
        >>> n = NotifikasiInApp(
        ...     warga_id=warga.id,
        ...     tipe='pengingat',
        ...     judul='Pengingat Pengembalian',
        ...     pesan='Barang jatuh tempo besok',
        ...     peminjaman_id=pem.id,
        ... )
        >>> saved = n.kirim()   # flush ke session, return Notifikasi instance
    """

    def __init__(
        self,
        warga_id: str,
        tipe: str,
        judul: str,
        pesan: str,
        peminjaman_id: Optional[str] = None,
    ) -> None:
        if tipe not in TIPE_NOTIFIKASI:
            raise ValueError(
                f"Tipe tidak valid. Pilihan: {', '.join(TIPE_NOTIFIKASI)}"
            )
        if not judul.strip():
            raise ValueError("Judul tidak boleh kosong")
        if not pesan.strip():
            raise ValueError("Pesan tidak boleh kosong")

        self._data = {
            "warga_id": warga_id,
            "peminjaman_id": peminjaman_id,
            "tipe": tipe,
            "judul": judul.strip(),
            "pesan": pesan.strip(),
        }
        self._instance: Notifikasi | None = None

    def kirim(self) -> "Notifikasi":
        """Simpan notifikasi ke DB session dan return instance."""
        if self._instance is not None:
            # Idempoten: tidak dobel-insert jika sudah dikirim
            return self._instance
        self._instance = Notifikasi(**self._data)
        db.session.add(self._instance)
        db.session.flush()  # dapat ID tanpa commit
        return self._instance

    def get_preview(self) -> str:
        """Preview singkat sebelum/not-after kirim."""
        pesan = cast(str, self._data["pesan"])
        if len(pesan) <= 80:
            return pesan
        return pesan[:79] + "…"

    @property
    def instance(self) -> "Notifikasi | None":
        """Akses instance Notifikasi yang tersimpan (None jika belum kirim)."""
        return self._instance
