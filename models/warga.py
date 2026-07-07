"""
models/warga.py — Model Warga (peminjam warga desa).

Tabel: `warga`
Peran: Akun peminjam warga desa sekaligus kredensial loginnya.

Pilar OOP:
  - **Encapsulation**: status berubah melalui method (`verifikasi()`,
    `blokir()`, `aktifkan()`) — tidak boleh di-set langsung agar
    transisi state terkontrol (mengacu PRD §8.4 analog untuk warga).
"""
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, generate_uuid, utcnow


class Warga(db.Model):
    """Warga desa yang terdaftar sebagai peminjam barang inventaris."""

    __tablename__ = "warga"

    # ── Primary Key ───────────────────────────────────────────
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)

    # ── Identitas ─────────────────────────────────────────────
    nik = db.Column(db.String(16), unique=True, nullable=False)
    nama_lengkap = db.Column(db.String(100), nullable=False)
    alamat = db.Column(db.Text, nullable=False)
    telepon = db.Column(db.String(15), nullable=False)
    rt_rw = db.Column(db.String(10), nullable=False)  # format: "001/002"

    # ── Auth ──────────────────────────────────────────────────
    # Nullable: di-set saat admin verifikasi (lihat §12 catatan arsitektur-db)
    password_hash = db.Column(db.String(255), nullable=True)

    # ── State / Status ────────────────────────────────────────
    # Enum: 'menunggu' | 'aktif' | 'ditolak' | 'diblokir'
    status = db.Column(db.String(20), nullable=False, default="menunggu")
    alasan_penolakan = db.Column(db.Text, nullable=True)

    # ── Audit Trail ───────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    verified_at = db.Column(db.DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────
    # Satu warga → banyak peminjaman (definisi ada di Peminjaman via FK + backref)
    # Satu warga → banyak notifikasi (definisi ada di Notifikasi via FK + backref)

    # ── Encapsulation: Password Management ────────────────────
    def set_password(self, password_plain: str) -> None:
        """Hash & simpan password warga (dipanggil saat verifikasi oleh admin)."""
        if not password_plain or len(password_plain) < 6:
            raise ValueError("Password minimal 6 karakter")
        self.password_hash = generate_password_hash(password_plain)

    def check_password(self, password_plain: str) -> bool:
        """Verifikasi password warga."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password_plain)

    # ── State Transitions (controlled mutators) ───────────────
    # Mengikuti PRD §8 status: menunggu → aktif | ditolak, aktif → diblokir
    def verifikasi(self, password_plain: str) -> None:
        """
        Verifikasi warga oleh admin.

        Warga berpindah dari status 'menunggu'/'ditolak' → 'aktif'.
        Password awal di-set pada saat ini.
        """
        if self.status not in ("menunggu", "ditolak"):
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diverifikasi"
            )
        self.set_password(password_plain)
        self.status = "aktif"
        self.verified_at = utcnow()
        self.alasan_penolakan = None

    def tolak(self, alasan: str) -> None:
        """Tolak pendaftaran warga dengan alasan."""
        if self.status != "menunggu":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat ditolak"
            )
        if not alasan or not alasan.strip():
            raise ValueError("Alasan penolakan wajib diisi")
        self.status = "ditolak"
        self.alasan_penolakan = alasan.strip()

    def blokir(self) -> None:
        """Blokir warga (tidak dapat login / meminjam)."""
        if self.status != "aktif":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diblokir"
            )
        self.status = "diblokir"

    def aktifkan_kembali(self) -> None:
        """Aktifkan kembali warga yang diblokir."""
        if self.status != "diblokir":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diaktifkan"
            )
        self.status = "aktif"

    # ── Query Helpers ─────────────────────────────────────────
    def get_riwayat_peminjaman(self) -> list:
        """Return list peminjaman milik warga ini (urut terbaru)."""
        # Akses via backref `peminjaman_list` dari relationship Peminjaman.warga
        return sorted(
            self.peminjaman_list,
            key=lambda p: p.created_at,
            reverse=True,
        )

    @property
    def bisa_ajukan_pinjam(self) -> bool:
        """Hanya warga berstatus 'aktif' yang dapat mengajukan peminjaman."""
        return self.status == "aktif"

    # ── Utility ───────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nik": self.nik,
            "nama_lengkap": self.nama_lengkap,
            "alamat": self.alamat,
            "telepon": self.telepon,
            "rt_rw": self.rt_rw,
            "status": self.status,
            "alasan_penolakan": self.alasan_penolakan,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self) -> str:
        return f"<Warga {self.nik} ({self.status})>"
