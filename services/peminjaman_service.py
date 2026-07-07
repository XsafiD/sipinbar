"""
services/peminjaman_service.py — Business logic modul Peminjaman.

Mengelola:
  - Pengajuan peminjaman oleh warga (anti double-booking + validasi stok)
  - State machine transaksi: diajukan → disetujui → dipinjam → dikembalikan
    (dengan cabang ditolak & terlambat)
  - Proses pengembalian + perhitungan denda (polymorphism via Barang.hitung_denda)
  - Query/filter peminjaman (per warga, per status, terlambat)
  - Generate kode peminjaman human-readable format ``PJM-YYYY-NNNN``

Pilar OOP yang terlihat:
  - **Encapsulation**: transisi status didelegasikan ke method model
    (`Peminjaman.setujui()`, `.tolak()`, `.mulai_pinjam()`, `.kembalikan()`).
    Service tidak pernah set `peminjaman.status = ...` secara langsung,
    sehingga invariant state machine (PRD §8.4) terjaga.
  - **Polymorphism**: perhitungan denda mendelegasikan ke
    `Barang.hitung_denda()` per item — tiap kategori punya tarif sendiri.
    Service tidak perlu tahu jenis kategori.
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    peminjaman di layer controller, menyembunyikan detail query overlap
    anti double-booking & aturan bisnis (BR-01 s/d BR-05).

Refs: SRS §4.3, PRD FR-03 & state diagram §8.4, arsitektur-db §5.5 & §5.6,
      TODO T-PJM-01 & T-PJM-02
"""
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import func

from models import db
from models.barang import Barang
from models.peminjaman import (
    KONDISI_KEMBALI,
    Peminjaman,
    DetailPeminjaman,
    STATUS_PEMINJAMAN,
)
from models.warga import Warga

# Status peminjaman yang berarti barang "sedang aktif dipinjam" — dipakai
# untuk cek anti double-booking. `dikembalikan`/`ditolak` TIDAK termasuk
# karena barang sudah dibebaskan.
STATUS_AKTIF_DIPINJAM = frozenset(
    {"diajukan", "disetujui", "dipinjam", "terlambat"}
)


class PeminjamanService:
    """Service layer untuk modul Peminjaman."""

    # ── Generate Kode Peminjaman (T-PJM-02) ───────────────────
    def _generate_kode_peminjaman(self) -> str:
        """
        Generate kode unik format ``PJM-YYYY-NNNN``.

        Sequence diambil dari nomor urut terbesar di tahun berjalan + 1,
        sehingga monoton naik meski ada peminjaman yang dibatalkan/ditolak
        (data peminjaman bersifat permanen untuk audit trail).

        Returns:
            Kode peminjaman, mis. ``PJM-2026-0001``.
        """
        year = date.today().year
        prefix = f"PJM-{year}-"
        # Ambil kode terakhir di tahun ini (urutan desc lexicographic cocok
        # karena NNNN zero-padded 4 digit).
        last_kode = (
            db.session.query(db.func.max(Peminjaman.kode_peminjaman))
            .filter(Peminjaman.kode_peminjaman.like(f"{prefix}%"))
            .scalar()
        )
        if last_kode:
            try:
                seq = int(last_kode.rsplit("-", 1)[-1]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    # ── Create: Ajukan Peminjaman (T-PJM-01) ──────────────────
    def ajukan(
        self,
        warga_id: str,
        items: List[dict],
        tgl_pinjam: date,
        tgl_kembali: date,
        catatan: Optional[str] = None,
    ) -> Peminjaman:
        """
        Ajukan peminjaman baru oleh warga.

        Validasi (mengacu SRS §4.3.2 & BR-01 s/d BR-05):
          - ``warga_id`` merujuk warga berstatus ``'aktif'`` (BR-01)
          - ``tgl_kembali > tgl_pinjam`` (tanggal valid)
          - ``items`` tidak kosong & tiap item:
              * ``barang_id`` valid & barang tidak di-soft-delete / tidak
                sedang perbaikan
              * ``jumlah > 0`` dan ``<= barang.jumlah_unit`` (stok)
              * tidak ada duplikat ``barang_id`` dalam satu pengajuan
          - Anti double-booking: untuk tiap barang, total jumlah di
            peminjaman aktif yang overlap rentang tanggal + jumlah yang
            diajukan <= ``barang.jumlah_unit`` (BR-03)

        Args:
            warga_id: ID warga pengaju.
            items: List dict ``{"barang_id": str, "jumlah": int}``.
            tgl_pinjam: Tanggal mulai pinjam.
            tgl_kembali: Tanggal rencana pengembalian.
            catatan: Catatan opsional dari warga.

        Raises:
            ValueError: Jika salah satu validasi gagal.

        Returns:
            Instance ``Peminjaman`` (sudah commit, status ``'diajukan'``).
        """
        # ── Validasi warga ───────────────────────────────────────
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")
        if not warga.bisa_ajukan_pinjam:
            raise ValueError(
                f"Warga berstatus '{warga.status}' tidak dapat mengajukan peminjaman"
            )

        # ── Validasi tanggal ─────────────────────────────────────
        tgl_pinjam = self._coerce_date(tgl_pinjam, "tanggal_pinjam")
        tgl_kembali = self._coerce_date(tgl_kembali, "tanggal_kembali")
        if tgl_kembali <= tgl_pinjam:
            raise ValueError(
                "Tanggal kembali harus setelah tanggal pinjam"
            )

        # ── Validasi items ───────────────────────────────────────
        if not items:
            raise ValueError("Minimal satu barang harus dipinjam")

        seen_barang = set()
        validated_items = []
        for idx, item in enumerate(items):
            barang_id = (item.get("barang_id") or "").strip() if isinstance(item, dict) else None
            if not barang_id:
                raise ValueError(f"Item ke-{idx + 1}: barang_id wajib diisi")

            if barang_id in seen_barang:
                raise ValueError(
                    f"Barang dengan ID '{barang_id}' didaftarkan lebih dari sekali"
                )
            seen_barang.add(barang_id)

            barang = db.session.get(Barang, barang_id)
            if barang is None or barang.is_deleted:
                raise ValueError(f"Barang tidak ditemukan (id: {barang_id})")
            if barang.status == "perbaikan":
                raise ValueError(f"Barang '{barang.nama}' sedang dalam perbaikan")
            if barang.status == "dihapus":
                raise ValueError(f"Barang '{barang.nama}' tidak tersedia")

            try:
                jumlah = int(item.get("jumlah", 0))
            except (TypeError, ValueError):
                raise ValueError(
                    f"Item ke-{idx + 1}: jumlah harus berupa angka"
                )
            if jumlah <= 0:
                raise ValueError(
                    f"Item ke-{idx + 1}: jumlah harus > 0"
                )
            if jumlah > barang.jumlah_unit:
                raise ValueError(
                    f"Jumlah {jumlah} melebihi stok '{barang.nama}' "
                    f"({barang.jumlah_unit} unit)"
                )

            # Anti double-booking (BR-03)
            if not self.validate_availability(
                barang_id, tgl_pinjam, tgl_kembali, jumlah=jumlah
            ):
                raise ValueError(
                    f"Barang '{barang.nama}' tidak tersedia pada rentang "
                    f"tanggal tersebut (bentrok dengan peminjaman lain)"
                )

            validated_items.append((barang, jumlah))

        # ── Buat Peminjaman + Detail ─────────────────────────────
        kode = self._generate_kode_peminjaman()
        peminjaman = Peminjaman(
            kode_peminjaman=kode,
            warga_id=warga_id,
            tanggal_pinjam=tgl_pinjam,
            tanggal_kembali_rencana=tgl_kembali,
            status="diajukan",
            catatan=(catatan or "").strip() or None,
        )
        db.session.add(peminjaman)
        db.session.flush()  # dapat peminjaman.id tanpa commit penuh

        for barang, jumlah in validated_items:
            detail = DetailPeminjaman(
                peminjaman_id=peminjaman.id,
                barang_id=barang.id,
                jumlah=jumlah,
            )
            db.session.add(detail)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return peminjaman

    # ── State Transitions (delegate ke model) ─────────────────
    def setujui(self, peminjaman_id: str, admin_id: str) -> Peminjaman:
        """
        Setujui peminjaman oleh admin. Transisi: diajukan → disetujui.

        Raises:
            ValueError: Jika peminjaman tidak ditemukan atau state ilegal.
        """
        peminjaman = self._get(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")
        peminjaman.setujui(admin_id)  # state machine validate
        db.session.commit()
        return peminjaman

    def tolak(
        self, peminjaman_id: str, admin_id: str, alasan: str
    ) -> Peminjaman:
        """
        Tolak peminjaman oleh admin. Transisi: diajukan → ditolak (final).

        Raises:
            ValueError: Jika peminjaman tidak ditemukan, state ilegal,
                        atau alasan kosong.
        """
        peminjaman = self._get(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")
        peminjaman.tolak(admin_id, alasan)  # state machine validate
        db.session.commit()
        return peminjaman

    def mulai_pinjam(self, peminjaman_id: str) -> Peminjaman:
        """
        Tandai barang sudah diserahkan. Transisi: disetujui → dipinjam.

        Raises:
            ValueError: Jika peminjaman tidak ditemukan atau state ilegal.
        """
        peminjaman = self._get(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")
        peminjaman.mulai_pinjam()  # state machine validate
        db.session.commit()
        return peminjaman

    def proses_pengembalian(
        self,
        peminjaman_id: str,
        kondisi_map: Optional[dict] = None,
        tanggal_aktual: Optional[date] = None,
    ) -> dict:
        """
        Proses pengembalian barang.

        Untuk tiap detail, catat ``kondisi_kembali`` dari ``kondisi_map``
        (key: ``barang_id``, value: salah satu ``KONDISI_KEMBALI``).
        Default ``'baik'`` jika tidak disebut.

        Setelah semua kondisi tercatat, panggil ``Peminjaman.kembalikan()``
        yang otomatis menghitung ``total_denda_rupiah`` via polymorphism.

        Args:
            peminjaman_id: ID peminjaman.
            kondisi_map: Dict opsional ``{barang_id: kondisi_str}``.
            tanggal_aktual: Tanggal pengembalian aktual (default: hari ini).
                           Disediakan untuk test/edge-case (mis. backdate).

        Raises:
            ValueError: Jika peminjaman tidak ditemukan, state ilegal,
                        atau kondisi_kembali tidak valid.

        Returns:
            Dict berisi:
              - ``peminjaman``: instance Peminjaman yang sudah diupdate
              - ``denda``: total denda rupiah (int)
              - ``terlambat``: bool
              - ``hari_terlambat``: int
        """
        peminjaman = self._get(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")

        kondisi_map = kondisi_map or {}

        # Validasi & set kondisi_kembali per detail
        for detail in peminjaman.detail_list:
            kondisi = kondisi_map.get(detail.barang_id, "baik")
            detail.set_kondisi_kembali(kondisi)  # validate enum

        # Delegate ke model: set tanggal_aktual, hitung denda, ubah status
        peminjaman.kembalikan(tanggal_aktual=tanggal_aktual)
        db.session.commit()

        hari_terlambat = peminjaman.get_jumlah_hari_terlambat()
        return {
            "peminjaman": peminjaman,
            "denda": peminjaman.total_denda_rupiah,
            "terlambat": hari_terlambat > 0,
            "hari_terlambat": hari_terlambat,
        }

    # ── Read / Query ──────────────────────────────────────────
    def get_by_id(self, peminjaman_id: str) -> Optional[Peminjaman]:
        """Return peminjaman by ID, atau None."""
        return self._get(peminjaman_id)

    def get_all(self, filters: Optional[dict] = None) -> List[Peminjaman]:
        """
        Return list peminjaman, urut terbaru dibuat.

        Filter yang didukung:
          - ``status``: salah satu dari ``STATUS_PEMINJAMAN`` (validasi enum)
          - ``warga_id``: filter by warga
          - ``q``: search by kode_peminjaman (case-insensitive LIKE)
        """
        filters = filters or {}
        query = Peminjaman.query

        status = filters.get("status")
        if status:
            if status not in STATUS_PEMINJAMAN:
                raise ValueError(
                    f"Status filter tidak valid. Pilihan: "
                    f"{', '.join(STATUS_PEMINJAMAN)}"
                )
            query = query.filter(Peminjaman.status == status)

        warga_id = filters.get("warga_id")
        if warga_id:
            query = query.filter(Peminjaman.warga_id == warga_id)

        search = (filters.get("q") or "").strip()
        if search:
            query = query.filter(
                Peminjaman.kode_peminjaman.ilike(f"%{search}%")
            )

        return query.order_by(Peminjaman.created_at.desc()).all()

    def get_by_warga(self, warga_id: str) -> List[Peminjaman]:
        """Return semua peminjaman milik warga tertentu, urut terbaru."""
        return (
            Peminjaman.query
            .filter(Peminjaman.warga_id == warga_id)
            .order_by(Peminjaman.created_at.desc())
            .all()
        )

    def get_terlambat(self) -> List[Peminjaman]:
        """
        Return peminjaman aktif (status ``'dipinjam'``) yang sudah lewat
        jatuh tempo tapi belum dikembalikan.
        """
        today = date.today()
        return (
            Peminjaman.query
            .filter(Peminjaman.status == "dipinjam")
            .filter(Peminjaman.tanggal_kembali_rencana < today)
            .order_by(Peminjaman.tanggal_kembali_rencana.asc())
            .all()
        )

    # ── Anti Double-Booking Check (BR-03) ─────────────────────
    def validate_availability(
        self,
        barang_id: str,
        tgl_start: date,
        tgl_end: date,
        jumlah: int = 1,
        exclude_peminjaman_id: Optional[str] = None,
    ) -> bool:
        """
        Cek apakah ``barang_id`` tersedia untuk dipinjam pada rentang
        ``[tgl_start, tgl_end]`` dengan jumlah ``jumlah``.

        Anti double-booking: jumlah total barang yang dipinjam dalam
        peminjaman aktif (status ``STATUS_AKTIF_DIPINJAM``) yang overlap
        rentang tanggal + jumlah yang diminta tidak boleh melebihi
        ``barang.jumlah_unit``.

        Query overlap memanfaatkan composite index
        ``idx_peminjaman_tanggal_pinjam_tanggal_kembali_rencana``.

        Args:
            barang_id: ID barang yang dicek.
            tgl_start: Tanggal mulai pinjam yang diminta.
            tgl_end: Tanggal kembali rencana yang diminta.
            jumlah: Jumlah unit yang diminta (default 1).
            exclude_peminjaman_id: ID peminjaman yang dikecualikan dari
                                   cek (mis. saat edit peminjaman sendiri).

        Returns:
            ``True`` jika tersedia, ``False`` jika bentrok/tidak tersedia.
        """
        barang = db.session.get(Barang, barang_id)
        if barang is None or barang.is_deleted:
            return False
        if barang.status in ("dihapus", "perbaikan"):
            return False

        tgl_start = self._coerce_date(tgl_start, "tgl_start")
        tgl_end = self._coerce_date(tgl_end, "tgl_end")

        # Sum jumlah dari peminjaman aktif yang overlap
        overlap_query = (
            db.session.query(
                func.coalesce(func.sum(DetailPeminjaman.jumlah), 0)
            )
            .join(
                Peminjaman,
                Peminjaman.id == DetailPeminjaman.peminjaman_id,
            )
            .filter(DetailPeminjaman.barang_id == barang_id)
            .filter(Peminjaman.status.in_(STATUS_AKTIF_DIPINJAM))
            # Interval overlap: A.start <= B.end AND A.end >= B.start
            .filter(Peminjaman.tanggal_pinjam <= tgl_end)
            .filter(Peminjaman.tanggal_kembali_rencana >= tgl_start)
        )
        if exclude_peminjaman_id:
            overlap_query = overlap_query.filter(
                Peminjaman.id != exclude_peminjaman_id
            )

        dipakai = overlap_query.scalar() or 0
        return (dipakai + jumlah) <= barang.jumlah_unit

    # ── Helper internal ───────────────────────────────────────
    def _get(self, peminjaman_id: str) -> Optional[Peminjaman]:
        """Return peminjaman by ID (singkatan)."""
        return db.session.get(Peminjaman, peminjaman_id)

    @staticmethod
    def _coerce_date(value, field_name: str = "tanggal") -> date:
        """
        Coerce value ke ``date``. Accept ``date`` atau string ISO (``YYYY-MM-DD``).

        Raises:
            ValueError: Jika value bukan date/ISO-string valid.
        """
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                raise ValueError(
                    f"Format {field_name} tidak valid (harus YYYY-MM-DD)"
                )
        raise ValueError(f"{field_name} wajib diisi")
