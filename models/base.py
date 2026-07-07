"""
models/base.py — Abstract Base Classes (ABC) & Mixin untuk SIPINBAR.

Mendefinisikan **kontrak method** yang HARUS diimplementasikan oleh
subclass konkret. Memenuhi 2 pilar OOP:
  - **Abstraction**: interface standar
  - **Polymorphism**: setiap subclass bisa punya perilaku berbeda

Kontrak ini menjadi **interface antar modul** — anggota tim lain
(Dev 3, 4, 6) cukup tahu method signature, tidak perlu tahu
detail implementasi.

Catatan teknis:
  - `BarangBase` diimplementasikan sebagai **mixin class** (bukan
    `abc.ABC`) karena subclass `Barang` juga mewarisi `db.Model`
    (SQLAlchemy) yang memiliki metaclass sendiri — `abc.ABCMeta`
    akan bentrok (metaclass conflict). Kontrak tetap ter-enforce
    via `NotImplementedError` saat method tidak di-override.
  - `NotifikasiBase` & `LaporanBase` adalah `abc.ABC` murni karena
    subclass-nya bukan db.Model (tidak ada konflik metaclass).
"""
from abc import ABC, abstractmethod


class BarangBase:
    """
    Contract untuk semua jenis barang yang dapat dipinjam.

    Diimplementasikan oleh: `models.barang.Barang` (Dev 3).

    Pilar OOP:
      - **Abstraction**: menyembunyikan detail cara hitung denda;
        yang tahu hanya bahwa setiap barang PUNYA cara hitung denda.
      - **Polymorphism**: subclass berbeda (per kategori) dapat
        menerapkan tarif denda berbeda tanpa mengubah caller code.

    Mixin pattern: method default raise `NotImplementedError` agar
    subclass wajib override. Tidak pakai `abc.ABCMeta` untuk hindari
    metaclass conflict dengan `db.Model`.
    """

    def hitung_denda(self, hari_terlambat: int) -> int:
        """
        Hitung total denda keterlambatan dalam Rupiah.

        Args:
            hari_terlambat: Jumlah hari keterlambatan (>= 0).

        Returns:
            Denda dalam Rupiah (INTEGER, bukan float).
            Return 0 jika hari_terlambat <= 0.
        """
        raise NotImplementedError(
            f"{type(self).__name__} harus mengimplementasikan hitung_denda()"
        )

    def get_info(self) -> dict:
        """
        Return ringkasan info barang sebagai dict (untuk display).

        Minimal berisi: nama, kategori, jumlah_unit, kondisi, status.
        """
        raise NotImplementedError(
            f"{type(self).__name__} harus mengimplementasikan get_info()"
        )


class NotifikasiBase(ABC):
    """
    Abstract contract untuk berbagai kanal notifikasi.

    Diimplementasikan oleh: `models.notifikasi.NotifikasiInApp` (Dev 6).

    Saat ini hanya In-App, namun ABC ini memungkinkan ekstensi
    Email / WhatsApp / SMS tanpa mengubah caller.
    """

    @abstractmethod
    def kirim(self) -> "NotifikasiBase":
        """
        Kirim / simpan notifikasi.

        Returns:
            Instance notifikasi yang sudah tersimpan (untuk chaining).
        """
        raise NotImplementedError

    @abstractmethod
    def get_preview(self) -> str:
        """Return preview singkat notifikasi (untuk list UI)."""
        raise NotImplementedError


class LaporanBase(ABC):
    """
    Abstract contract untuk semua jenis laporan.

    Diimplementasikan oleh:
      - `models.laporan.LaporanPeminjaman` (Dev 6)
      - `models.laporan.LaporanInventaris` (Dev 6)
    """

    @abstractmethod
    def generate(self, **filters) -> dict:
        """
        Generate isi laporan berdasarkan filter.

        Returns:
            Dict berisi data terstruktur (rows, summary, metadata).
        """
        raise NotImplementedError

    @abstractmethod
    def export(self, data: dict, format: str = "csv") -> bytes:
        """
        Ekspor data laporan ke format tertentu.

        Args:
            data: Output dari method `generate()`.
            format: Format ekspor ('csv', 'pdf', 'html').

        Returns:
            Bytes content siap di-download.
        """
        raise NotImplementedError
