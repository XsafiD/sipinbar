"""
services/laporan_service.py — Business logic modul Laporan.

Mengelola:
  - Generate laporan peminjaman (filter periode + status)
  - Generate laporan inventaris (snapshot barang)
  - Export laporan ke CSV (dengan BOM UTF-8 untuk Excel)
  - Statistik dashboard (total barang, peminjaman aktif, terlambat, warga)

Pilar OOP yang terlihat:
  - **Abstraction**: service menjadi facade tunggal untuk semua operasi
    laporan di layer controller. Detail query & agregasi disembunyikan.
  - **Polymorphism**: memegang instance ``LaporanBase`` (bisa
    ``LaporanPeminjaman`` atau ``LaporanInventaris``) dan memanggil
    ``.generate()`` / ``.export()`` tanpa peduli subclassnya — sesuai
    kontrak ABC di ``models/base.py``.
  - **Encapsulation**: statistik dashboard dihitung via method terpisah
    per metrik, tidak mengakses langsung atribut model dari luar.

Refs: SRS §4.5, PRD FR-06, arsitektur-db §5.7, TODO T-LAP-02
"""
from datetime import date, datetime
from typing import Optional

from models import db
from models.barang import Barang
from models.laporan import LaporanInventaris, LaporanPeminjaman
from models.peminjaman import Peminjaman, STATUS_PEMINJAMAN
from models.warga import Warga


# Status peminjaman yang berarti "aktif berjalan" — untuk stat dashboard.
STATUS_AKTIF_BERJALAN = frozenset({"diajukan", "disetujui", "dipinjam", "terlambat"})


class LaporanService:
    """Service layer untuk modul Laporan & statistik dashboard."""

    def __init__(self) -> None:
        # Polymorphism: service memegang 2 subclass berbeda via kontrak
        # LaporanBase. Bisa ditukar tanpa ubah kode caller.
        self._laporan_peminjaman = LaporanPeminjaman()
        self._laporan_inventaris = LaporanInventaris()

    # ── Generate Laporan ──────────────────────────────────────
    def generate_laporan_peminjaman(
        self,
        mulai: Optional[date] = None,
        selesai: Optional[date] = None,
        status: Optional[str] = None,
    ) -> dict:
        """
        Generate laporan transaksi peminjaman dalam rentang tanggal.

        Delegasi ke ``LaporanPeminjaman.generate()`` (kontrak ABC).

        Args:
            mulai: Filter ``tanggal_pinjam >= mulai`` (opsional).
            selesai: Filter ``tanggal_pinjam <= selesai`` (opsional).
            status: Filter status peminjaman (opsional, validasi enum).

        Returns:
            Dict berisi ``rows``, ``summary``, ``metadata``.

        Raises:
            ValueError: Jika ``status`` tidak termasuk ``STATUS_PEMINJAMAN``.
        """
        if status is not None and status not in STATUS_PEMINJAMAN:
            raise ValueError(
                f"Status filter tidak valid. Pilihan: "
                f"{', '.join(STATUS_PEMINJAMAN)}"
            )
        return self._laporan_peminjaman.generate(
            tanggal_mulai=mulai,
            tanggal_selesai=selesai,
            status=status,
        )

    def generate_laporan_inventaris(
        self, include_deleted: bool = False
    ) -> dict:
        """
        Generate laporan snapshot inventaris barang.

        Delegasi ke ``LaporanInventaris.generate()`` (kontrak ABC).

        Args:
            include_deleted: ``True`` untuk sertakan barang yang di-soft-delete.
        """
        return self._laporan_inventaris.generate(include_deleted=include_deleted)

    # ── Export ────────────────────────────────────────────────
    def export_laporan(self, data: dict, format: str = "csv") -> bytes:
        """
        Export hasil ``generate_*`` ke bytes siap download.

        Strategy: jika ``data`` berasal dari laporan peminjaman, pakai
        exporter ``LaporanPeminjaman``; jika dari inventaris, pakai
        ``LaporanInventaris``. Deteksi via metadata.filter yang di-set
        oleh masing-masing generator.

        Args:
            data: Output dari method ``generate_*``.
            format: Format ekspor (saat ini hanya ``'csv'``).

        Raises:
            ValueError: Jika format tidak didukung.

        Returns:
            Bytes content dengan BOM UTF-8 (untuk Excel).
        """
        # Heuristik sederhana: laporan inventaris punyakey 'total_jenis_barang'
        # di summary; laporan peminjaman punya 'total_peminjaman'.
        summary = data.get("summary", {}) or {}
        if "total_jenis_barang" in summary:
            return self._laporan_inventaris.export(data, format=format)
        return self._laporan_peminjaman.export(data, format=format)

    # ── Statistik Dashboard ───────────────────────────────────
    def get_statistik_dashboard(self) -> dict:
        """
        Agregasi statistik ringkas untuk dashboard.

        Metrik (mengacu TODO T-LAP-02 AC):
          - ``total_barang``: jumlah jenis barang aktif (tidak di-soft-delete)
          - ``total_unit_barang``: total unit semua barang aktif
          - ``peminjaman_aktif``: jumlah peminjaman berstatus aktif berjalan
          - ``peminjaman_terlambat``: jumlah peminjaman terlambat
          - ``warga_terdaftar``: jumlah warga terdaftar (semua status)
          - ``warga_aktif``: jumlah warga berstatus 'aktif'

        Returns:
            Dict berisi semua metrik di atas.
        """
        barang_aktif = (
            Barang.query.filter(Barang.deleted_at.is_(None)).all()
        )
        total_barang = len(barang_aktif)
        total_unit = sum(b.jumlah_unit for b in barang_aktif)

        peminjaman_aktif = (
            Peminjaman.query
            .filter(Peminjaman.status.in_(STATUS_AKTIF_BERJALAN))
            .count()
        )
        peminjaman_terlambat = (
            Peminjaman.query.filter(Peminjaman.status == "terlambat").count()
        )

        warga_terdaftar = Warga.query.count()
        warga_aktif = Warga.query.filter(Warga.status == "aktif").count()

        return {
            "total_barang": total_barang,
            "total_unit_barang": total_unit,
            "peminjaman_aktif": peminjaman_aktif,
            "peminjaman_terlambat": peminjaman_terlambat,
            "warga_terdaftar": warga_terdaftar,
            "warga_aktif": warga_aktif,
            "generated_at": datetime.utcnow().isoformat(),
        }

    # ── Statistik per Warga (untuk dashboard warga) ───────────
    def get_statistik_warga(self, warga_id: str) -> dict:
        """
        Statistik dashboard untuk warga (hanya miliknya).

        Args:
            warga_id: ID warga.

        Returns:
            Dict berisi: peminjaman_aktif, peminjaman_riwayat,
            peminjaman_terlambat.
        """
        base_query = Peminjaman.query.filter(Peminjaman.warga_id == warga_id)
        aktif = base_query.filter(
            Peminjaman.status.in_(STATUS_AKTIF_BERJALAN)
        ).count()
        riwayat = base_query.count()
        terlambat = base_query.filter(Peminjaman.status == "terlambat").count()

        return {
            "peminjaman_aktif": aktif,
            "peminjaman_riwayat": riwayat,
            "peminjaman_terlambat": terlambat,
            "generated_at": datetime.utcnow().isoformat(),
        }
