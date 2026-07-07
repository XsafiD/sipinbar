"""
models/admin.py — Model Admin (operator desa).

Tabel: `admin`
Peran: Akun operator desa yang mengelola sistem.

Pilar OOP:
  - **Encapsulation**: password disimpan sebagai `password_hash`
    (private), akses melalui method `set_password()` & `check_password()`.
"""
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, generate_uuid, utcnow


class Admin(db.Model):
    """Akun operator/pegawai desa yang mengelola sistem SIPINBAR."""

    __tablename__ = "admin"

    # ── Primary Key ───────────────────────────────────────────
    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)

    # ── Auth ──────────────────────────────────────────────────
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # ── Profil ────────────────────────────────────────────────
    nama_lengkap = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="admin")
    is_aktif = db.Column(db.Boolean, nullable=False, default=True)

    # ── Audit Trail ───────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    last_login_at = db.Column(db.DateTime)

    # ── Relationships ─────────────────────────────────────────
    # Satu admin bisa approve banyak peminjaman (lihat Peminjaman.approved_by_admin_id)
    # Di-deklarasikan via backref di Peminjaman.approved_by.

    # ── Encapsulation: Password Management ────────────────────
    def set_password(self, password_plain: str) -> None:
        """
        Hash dan simpan password.

        Tidak pernah menyimpan plain-text — menggunakan
        werkzeug.security.generate_password_hash (PBKDF2-SHA256).
        """
        if not password_plain or len(password_plain) < 6:
            raise ValueError("Password minimal 6 karakter")
        self.password_hash = generate_password_hash(password_plain)

    def check_password(self, password_plain: str) -> bool:
        """Verifikasi password terhadap hash yang tersimpan."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password_plain)

    # ── Utility ───────────────────────────────────────────────
    def update_last_login(self) -> None:
        """Catat timestamp login terakhir (dipanggil saat login berhasil)."""
        self.last_login_at = utcnow()

    def to_dict(self) -> dict:
        """Serialisasi ke dict (tanpa password_hash)."""
        return {
            "id": self.id,
            "username": self.username,
            "nama_lengkap": self.nama_lengkap,
            "role": self.role,
            "is_aktif": self.is_aktif,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }

    def __repr__(self) -> str:
        return f"<Admin {self.username}>"
