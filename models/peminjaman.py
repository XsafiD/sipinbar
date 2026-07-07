"""
models/peminjaman.py — Model Peminjaman + DetailPeminjaman.

Tabel:
  - `peminjaman` (transaksi induk)
  - `detail_peminjaman` (bridge many-to-many dengan atribut tambahan)

Peran: Transaksi peminjaman barang dari warga, dengan state machine
status yang mengikuti PRD §8.4:
    DIAJUKAN → DISETUJUI → DIPINJAM → DIKEMBALIKAN
                              ↓            ↓
                            DITOLAK     TERLAMBAT → DIKEMBALIKAN (+denda)

Pilar OOP:
  - **Encapsulation**: transisi status hanya via method `setujui()`,
    `tolak()`, `mulai_pinjam()`, `kembalikan()`. Set langsung
    `.status = ...` akan melewati validasi state machine.
  - **Polymorphism**: `hitung_denda()` mendelegasikan per item barang
    ke masing-masing `Barang.hitung_denda()` (yang berbeda per kategori).
"""
from datetime import date, datetime

from models import db, generate_uuid

# ── Konstanta Enum (mengacu arsitektur-db §8.4 & §8.5) ────────
STATUS_PEMINJAMAN = (
    "diajukan",      # baru diajukan warga
    "disetujui",     # admin setujui
    "ditolak",       # admin tolak (final)
    "dipinjam",      # barang diserahkan
    "terlambat",     # lewat jatuh tempo
    "dikembalikan",  # sudah dikembalikan (final)
)
STATUS_FINAL = frozenset({"ditolak", "dikembalikan"})

KONDISI_KEMBALI = ("baik", "rusak_ringan", "rusak_berat")


class Peminjaman(db.Model):
    """Transaksi peminjaman barang (induk)."""

    __tablename__ = "peminjaman"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    kode_peminjaman = db.Column(
        db.String(20), unique=True, nullable=False
    )  # format: PJM-YYYY-NNNN

    # ── Foreign Keys ──────────────────────────────────────────
    warga_id = db.Column(
        db.String(36),
        db.ForeignKey("warga.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_by_admin_id = db.Column(
        db.String(36),
        db.ForeignKey("admin.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Tanggal ───────────────────────────────────────────────
    tanggal_pinjam = db.Column(db.Date, nullable=False)
    tanggal_kembali_rencana = db.Column(db.Date, nullable=False)
    tanggal_kembali_aktual = db.Column(db.Date, nullable=True)

    # ── State & Metadata ──────────────────────────────────────
    status = db.Column(db.String(20), nullable=False, default="diajukan")
    catatan = db.Column(db.Text, nullable=True)
    alasan_penolakan = db.Column(db.Text, nullable=True)
    total_denda_rupiah = db.Column(db.Integer, nullable=False, default=0)

    # ── Audit Trail ───────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    approved_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "tanggal_kembali_rencana > tanggal_pinjam",
            name="ck_peminjaman_tanggal_valid",
        ),
        db.CheckConstraint(
            "total_denda_rupiah >= 0",
            name="ck_peminjaman_total_denda_positive",
        ),
        db.Index("idx_peminjaman_warga_id", "warga_id"),
        db.Index("idx_peminjaman_status", "status"),
        db.Index(
            "idx_peminjaman_tanggal_pinjam_tanggal_kembali_rencana",
            "tanggal_pinjam",
            "tanggal_kembali_rencana",
        ),
    )

    # ── Relationships ─────────────────────────────────────────
    warga = db.relationship(
        "Warga",
        backref=db.backref("peminjaman_list", lazy=True),
        lazy="joined",
    )
    approved_by = db.relationship(
        "Admin",
        backref=db.backref("approved_peminjaman_list", lazy=True),
        lazy="joined",
    )
    detail_list = db.relationship(
        "DetailPeminjaman",
        backref=db.backref("peminjaman", lazy="joined"),
        lazy=True,
        cascade="all, delete-orphan",
    )

    # ── State Machine Transitions ─────────────────────────────
    # Method ini menjadi satu-satunya pintu sah untuk mengubah status.
    def setujui(self, admin_id: str) -> None:
        """Setujui peminjaman oleh admin. Transisi: diajukan → disetujui."""
        if self.status != "diajukan":
            raise ValueError(
                f"Peminjaman berstatus '{self.status}' tidak dapat disetujui"
            )
        self.status = "disetujui"
        self.approved_by_admin_id = admin_id
        self.approved_at = datetime.utcnow()

    def tolak(self, admin_id: str, alasan: str) -> None:
        """Tolak peminjaman. Transisi: diajukan → ditolak (final)."""
        if self.status != "diajukan":
            raise ValueError(
                f"Peminjaman berstatus '{self.status}' tidak dapat ditolak"
            )
        if not alasan or not alasan.strip():
            raise ValueError("Alasan penolakan wajib diisi")
        self.status = "ditolak"
        self.approved_by_admin_id = admin_id
        self.approved_at = datetime.utcnow()
        self.alasan_penolakan = alasan.strip()

    def mulai_pinjam(self) -> None:
        """Tandai barang sudah diserahkan. Transisi: disetujui → dipinjam."""
        if self.status != "disetujui":
            raise ValueError(
                f"Peminjaman berstatus '{self.status}' tidak dapat diproses"
            )
        self.status = "dipinjam"

    def tandai_terlambat(self) -> None:
        """Tandai sebagai terlambat (dipicu scheduler H+ jatuh tempo)."""
        if self.status != "dipinjam":
            raise ValueError(
                f"Peminjaman berstatus '{self.status}' tidak dapat ditandai terlambat"
            )
        self.status = "terlambat"

    def kembalikan(self, tanggal_aktual: date = None) -> None:
        """
        Catat pengembalian. Transisi: dipinjam/terlambat → dikembalikan.

        Otomatis hitung & simpan total denda ke `total_denda_rupiah`.
        """
        if self.status not in ("dipinjam", "terlambat"):
            raise ValueError(
                f"Peminjaman berstatus '{self.status}' tidak dapat dikembalikan"
            )
        self.tanggal_kembali_aktual = tanggal_aktual or date.today()
        # Hitung denda otomatis
        self.total_denda_rupiah = self.hitung_denda()
        self.status = "dikembalikan"

    # ── Query / Logic Helpers ─────────────────────────────────
    @property
    def is_terlambat(self) -> bool:
        """True jika sudah lewat tanggal jatuh tempo dan belum dikembalikan."""
        if self.status in ("dipinjam", "terlambat"):
            return date.today() > self.tanggal_kembali_rencana
        return False

    @property
    def is_final(self) -> bool:
        """True jika sudah mencapai status terminal (ditolak/dikembalikan)."""
        return self.status in STATUS_FINAL

    def get_jumlah_hari_terlambat(self) -> int:
        """Hitung selisih hari keterlambatan (0 jika tepat waktu / belum jatuh tempo)."""
        if self.tanggal_kembali_aktual is None:
            # Belum dikembalikan → cek terhadap hari ini
            ref_date = date.today()
        else:
            ref_date = self.tanggal_kembali_aktual

        delta = ref_date - self.tanggal_kembali_rencana
        return max(0, delta.days)

    # ── Polymorphism: Delegasi hitung denda ke tiap Barang ────
    def hitung_denda(self) -> int:
        """
        Hitung total denda dengan mendelegasikan ke `Barang.hitung_denda()`
        untuk setiap item di `detail_list`.

        Setiap barang akan menggunakan tarif kategori-nya masing-masing.
        """
        hari = self.get_jumlah_hari_terlambat()
        if hari <= 0:
            return 0
        total = 0
        for detail in self.detail_list:
            # Polymorphism: Barang.hitung_denda() bergantung kategori
            total += detail.barang.hitung_denda(hari) * detail.jumlah
        return total

    def get_status_display(self) -> str:
        """Label status untuk display (kapital)."""
        mapping = {
            "diajukan": "Diajukan",
            "disetujui": "Disetujui",
            "ditolak": "Ditolak",
            "dipinjam": "Dipinjam",
            "terlambat": "Terlambat",
            "dikembalikan": "Dikembalikan",
        }
        return mapping.get(self.status, self.status.title())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kode_peminjaman": self.kode_peminjaman,
            "warga_id": self.warga_id,
            "approved_by_admin_id": self.approved_by_admin_id,
            "tanggal_pinjam": self.tanggal_pinjam.isoformat(),
            "tanggal_kembali_rencana": self.tanggal_kembali_rencana.isoformat(),
            "tanggal_kembali_aktual": (
                self.tanggal_kembali_aktual.isoformat()
                if self.tanggal_kembali_aktual
                else None
            ),
            "status": self.status,
            "status_display": self.get_status_display(),
            "total_denda_rupiah": self.total_denda_rupiah,
            "is_terlambat": self.is_terlambat,
            "is_final": self.is_final,
        }

    def __repr__(self) -> str:
        return f"<Peminjaman {self.kode_peminjaman} ({self.status})>"


class DetailPeminjaman(db.Model):
    """Item barang dalam satu transaksi peminjaman (tabel bridge)."""

    __tablename__ = "detail_peminjaman"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    peminjaman_id = db.Column(
        db.String(36),
        db.ForeignKey("peminjaman.id", ondelete="CASCADE"),
        nullable=False,
    )
    barang_id = db.Column(
        db.String(36),
        db.ForeignKey("barang.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jumlah = db.Column(db.Integer, nullable=False, default=1)
    kondisi_kembali = db.Column(
        db.String(20), nullable=True
    )  # diisi saat pengembalian

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "peminjaman_id",
            "barang_id",
            name="uq_detail_peminjaman_peminjaman_id_barang_id",
        ),
        db.CheckConstraint("jumlah > 0", name="ck_detail_peminjaman_jumlah_positive"),
        db.Index("idx_detail_peminjaman_peminjaman_id", "peminjaman_id"),
        db.Index("idx_detail_peminjaman_barang_id", "barang_id"),
    )

    # ── Relationships ─────────────────────────────────────────
    barang = db.relationship(
        "Barang",
        backref=db.backref("detail_peminjaman_list", lazy=True),
        lazy="joined",
    )

    def set_kondisi_kembali(self, kondisi: str) -> None:
        """Catat kondisi barang saat dikembalikan."""
        if kondisi not in KONDISI_KEMBALI:
            raise ValueError(
                f"Kondisi kembali tidak valid. Pilihan: {', '.join(KONDISI_KEMBALI)}"
            )
        self.kondisi_kembali = kondisi

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "peminjaman_id": self.peminjaman_id,
            "barang_id": self.barang_id,
            "barang_nama": self.barang.nama if self.barang else None,
            "jumlah": self.jumlah,
            "kondisi_kembali": self.kondisi_kembali,
        }

    def __repr__(self) -> str:
        return (
            f"<DetailPeminjaman peminjaman={self.peminjaman_id} "
            f"barang={self.barang_id} jumlah={self.jumlah}>"
        )
