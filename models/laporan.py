"""
models/laporan.py — Class LaporanPeminjaman & LaporanInventaris.

Bukan db.Model — kelas ini adalah *service/generator* yang meng-
implementasi `LaporanBase` (ABC) untuk memproduksi data laporan
dari query ke model-model lain.

Pilar OOP:
  - **Abstraction**: kontrak `generate()` & `export()` di ABC.
  - **Inheritance**: dua subclass konkret dengan perilaku berbeda.
  - **Polymorphism**: caller cukup tahu ia memegang `LaporanBase`,
    tidak peduli subclassnya — bisa diganti tanpa ubah kode caller.

Catatan: Implementasi di file ini adalah skeleton fungsional.
Dev 6 akan melengkapi format ekspor tambahan (PDF/HTML) dan
statistik yang lebih kaya di M4.
"""
import csv
import io
from datetime import date
from typing import Optional

from models import utcnow
from models.base import LaporanBase


class LaporanPeminjaman(LaporanBase):
    """
    Laporan transaksi peminjaman dalam rentang tanggal.

    Meng-agregasi data dari tabel `peminjaman` + `detail_peminjaman`.
    """

    def generate(
        self,
        tanggal_mulai: Optional[date] = None,
        tanggal_selesai: Optional[date] = None,
        status: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """
        Generate data laporan peminjaman.

        Args:
            tanggal_mulai: Filter tanggal_pinjam >= tanggal_mulai.
            tanggal_selesai: Filter tanggal_pinjam <= tanggal_selesai.
            status: Filter status peminjaman (opsional).

        Returns:
            Dict berisi:
              - rows: list of dict per peminjaman
              - summary: statistik agregat
              - metadata: parameter & timestamp generate
        """
        from models.peminjaman import Peminjaman

        query = Peminjaman.query
        if tanggal_mulai:
            query = query.filter(Peminjaman.tanggal_pinjam >= tanggal_mulai)
        if tanggal_selesai:
            query = query.filter(Peminjaman.tanggal_pinjam <= tanggal_selesai)
        if status:
            query = query.filter(Peminjaman.status == status)

        rows_data = [p.to_dict() for p in query.all()]

        # Statistik ringkas
        total = len(rows_data)
        total_denda = sum(r.get("total_denda_rupiah", 0) for r in rows_data)
        count_by_status: dict[str, int] = {}
        for r in rows_data:
            s = r.get("status", "unknown")
            count_by_status[s] = count_by_status.get(s, 0) + 1

        return {
            "rows": rows_data,
            "summary": {
                "total_peminjaman": total,
                "total_denda_rupiah": total_denda,
                "distribusi_status": count_by_status,
            },
            "metadata": {
                "generated_at": utcnow().isoformat(),
                "filter": {
                    "tanggal_mulai": tanggal_mulai.isoformat() if tanggal_mulai else None,
                    "tanggal_selesai": (
                        tanggal_selesai.isoformat() if tanggal_selesai else None
                    ),
                    "status": status,
                },
            },
        }

    def export(self, data: dict, format: str = "csv") -> bytes:
        """
        Ekspor hasil `generate()` ke format tertentu.

        Supported format: 'csv'.
        """
        if format != "csv":
            raise ValueError(f"Format '{format}' belum didukung. Gunakan 'csv'.")

        output = io.StringIO()
        output.write("\ufeff")  # BOM untuk Excel
        rows = data.get("rows", [])
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return output.getvalue().encode("utf-8")


class LaporanInventaris(LaporanBase):
    """
    Laporan kondisi inventaris barang (snapshot terkini).

    Meng-agregasi data dari tabel `barang` + `kategori`.
    """

    def generate(self, include_deleted: bool = False, **kwargs) -> dict:
        """
        Generate data laporan inventaris.

        Args:
            include_deleted: True untuk sertakan barang yang di-soft-delete.

        Returns:
            Dict berisi rows, summary (total unit, distribusi status/kondisi),
            dan metadata.
        """
        from models.barang import Barang

        query = Barang.query
        if not include_deleted:
            query = query.filter(Barang.deleted_at.is_(None))

        rows_data = [b.to_dict() for b in query.all()]

        total_unit = sum(r.get("jumlah_unit", 0) for r in rows_data)
        dist_status: dict[str, int] = {}
        dist_kondisi: dict[str, int] = {}
        for r in rows_data:
            s = r.get("status", "unknown")
            k = r.get("kondisi", "unknown")
            dist_status[s] = dist_status.get(s, 0) + 1
            dist_kondisi[k] = dist_kondisi.get(k, 0) + 1

        return {
            "rows": rows_data,
            "summary": {
                "total_jenis_barang": len(rows_data),
                "total_unit": total_unit,
                "distribusi_status": dist_status,
                "distribusi_kondisi": dist_kondisi,
            },
            "metadata": {
                "generated_at": utcnow().isoformat(),
                "filter": {"include_deleted": include_deleted},
            },
        }

    def export(self, data: dict, format: str = "csv") -> bytes:
        """Ekspor snapshot inventaris. Supported: 'csv'."""
        if format != "csv":
            raise ValueError(f"Format '{format}' belum didukung. Gunakan 'csv'.")

        output = io.StringIO()
        output.write("\ufeff")
        rows = data.get("rows", [])
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return output.getvalue().encode("utf-8")
