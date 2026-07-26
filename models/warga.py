"""
models/warga.py — Model Warga (peminjam warga desa).

Tabel: `warga`
Peran: Akun peminjam warga desa sekaligus kredensial loginnya.

Pilar OOP:
  - **Encapsulation**: status berubah melalui method (`activate()`,
    `blokir()`, `unblock()`, `update_data()`) — tidak boleh di-set langsung agar
    transisi state terkontrol.
  - **State Machine**: Status transition: data_only → aktif → diblokir

Ref: SIPINBAR v2.0.0 - Username-based authentication
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
    # Username untuk login (UNIQUE, nullable untuk data_only)
    username = db.Column(db.String(50), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)

    # ── State / Status ────────────────────────────────────────
    # Enum: 'data_only' | 'aktif' | 'diblokir'
    # - data_only: Master data saja, belum bisa login
    # - aktif: Sudah diaktivasi dengan username & password, bisa login
    # - diblokir: Pernah aktif tapi diblokir admin
    status = db.Column(db.String(20), nullable=False, default="data_only")

    # ── Audit Trail ───────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    activated_at = db.Column(db.DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────
    # Satu warga → banyak peminjaman (definisi ada di Peminjaman via FK + backref)
    # Satu warga → banyak notifikasi (definisi ada di Notifikasi via FK + backref)

    # ── Encapsulation: Password Management ────────────────────
    def set_password(self, password_plain: str) -> None:
        """Hash & simpan password warga."""
        if not password_plain or len(password_plain) < 6:
            raise ValueError("Password minimal 6 karakter")
        self.password_hash = generate_password_hash(password_plain)

    def check_password(self, password_plain: str) -> bool:
        """Verifikasi password warga."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password_plain)

    # ── State Transitions (controlled mutators) ───────────────
    def activate(self, username: str, password_plain: str) -> None:
        """
        Aktivasi akun warga dari data_only menjadi aktif.

        Transisi status: data_only → aktif
        Username dan password di-set pada saat ini.

        Args:
            username: Username untuk login (unique, 3-50 karakter)
            password_plain: Password untuk login (minimal 6 karakter)

        Raises:
            ValueError: Jika status tidak data_only, username sudah ada,
                        atau password tidak valid
        """
        if self.status != "data_only":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diaktivasi. "
                "Hanya status 'data_only' yang bisa diaktivasi."
            )

        if not username or len(username) < 3 or len(username) > 50:
            raise ValueError("Username harus 3-50 karakter")

        # Cek username unik (di-model juga ada constraint, tapi kita validasi dulu)
        existing = Warga.query.filter_by(username=username).first()
        if existing is not None and existing.id != self.id:
            raise ValueError(f"Username '{username}' sudah digunakan")

        self.set_password(password_plain)
        self.username = username
        self.status = "aktif"
        self.activated_at = utcnow()

    def update_data(
        self,
        nama_lengkap: str = None,
        alamat: str = None,
        telepon: str = None,
        rt_rw: str = None
    ) -> None:
        """
        Update data warga (field identitas, BUKAN auth fields).

        Method ini untuk update data identitas saja, tidak mengubah username,
        password, atau status.

        Args:
            nama_lengkap: Nama lengkap baru (opsional)
            alamat: Alamat baru (opsional)
            telepon: Telepon baru (opsional)
            rt_rw: RT/RW baru (opsional)
        """
        if nama_lengkap is not None:
            self.nama_lengkap = nama_lengkap
        if alamat is not None:
            self.alamat = alamat
        if telepon is not None:
            self.telepon = telepon
        if rt_rw is not None:
            self.rt_rw = rt_rw

        # Trigger updated_at via onupdate
        db.session.add(self)

    def blokir(self) -> None:
        """
        Blokir warga aktif (tidak dapat login / meminjam).

        Transisi status: aktif → diblokir
        """
        if self.status != "aktif":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diblokir. "
                "Hanya status 'aktif' yang dapat diblokir."
            )
        self.status = "diblokir"

    def unblock(self) -> None:
        """
        Aktifkan kembali warga yang diblokir.

        Transisi status: diblokir → aktif
        """
        if self.status != "diblokir":
            raise ValueError(
                f"Warga dengan status '{self.status}' tidak dapat diaktifkan kembali. "
                "Hanya status 'diblokir' yang dapat diaktifkan."
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

    def is_data_only(self) -> bool:
        """Cek apakah warga masih status data_only (belum bisa login)."""
        return self.status == "data_only"

    # ── Utility ───────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Serialisasi data warga ke dict (tanpa password_hash)."""
        return {
            "id": self.id,
            "nik": self.nik,
            "nama_lengkap": self.nama_lengkap,
            "alamat": self.alamat,
            "telepon": self.telepon,
            "rt_rw": self.rt_rw,
            "username": self.username,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }

    def __repr__(self) -> str:
        username_display = self.username if self.username else "(no username)"
        return f"<Warga {self.nik} ({self.status}) - {username_display}>"
