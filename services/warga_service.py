"""
services/warga_service.py — Business logic manajemen warga oleh admin.

Berbeda dengan AuthService (login/registrasi), WargaService fokus pada
operasi CRUD & state transition warga setelah mereka terdaftar:
  - List dengan filter (status, search)
  - Detail & riwayat peminjaman
  - Blokir / aktifkan kembali (delegate ke method model)

Pilar OOP yang terlihat:
  - **Encapsulation**: transisi status (`blokir`, `aktifkan_kembali`)
    didelegasikan ke method model — service tidak pernah set
    `warga.status = '...'` secara langsung.
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    warga di layer controller, menyembunyikan detail query SQLAlchemy.

Refs: SRS §4.1, TODO T-AUTH-02
"""
from typing import List, Optional

from sqlalchemy import or_

from models import db
from models.warga import Warga


class WargaService:
    """Service layer untuk manajemen warga (akses admin)."""

    # Status warga yang valid (mengacu model.warga.Warga.__state machine__)
    VALID_STATUSES = ("menunggu", "aktif", "ditolak", "diblokir")

    # ── Query / Read ──────────────────────────────────────────
    def get_all(self, filters: Optional[dict] = None) -> List[Warga]:
        """
        Return list warga, urut terbaru dibuat.

        Filter yang didukung:
          - ``status``: salah satu dari VALID_STATUSES
          - ``q``: search berdasarkan nama atau NIK (case-insensitive LIKE)

        Args:
            filters: Dict filter opsional.

        Raises:
            ValueError: Jika filter status tidak valid.

        Returns:
            List instance ``Warga`` (bisa kosong).
        """
        query = Warga.query
        filters = filters or {}

        status = filters.get("status")
        if status:
            if status not in self.VALID_STATUSES:
                raise ValueError(
                    f"Status filter tidak valid. Pilihan: {', '.join(self.VALID_STATUSES)}"
                )
            query = query.filter(Warga.status == status)

        search = (filters.get("q") or "").strip()
        if search:
            like = f"%{search}%"
            query = query.filter(
                or_(
                    Warga.nama_lengkap.ilike(like),
                    Warga.nik.ilike(like),
                )
            )

        return query.order_by(Warga.created_at.desc()).all()

    def get_by_id(self, warga_id: str) -> Optional[Warga]:
        """Return warga berdasarkan ID, atau None jika tidak ada."""
        return db.session.get(Warga, warga_id)

    def get_by_nik(self, nik: str) -> Optional[Warga]:
        """Return warga berdasarkan NIK, atau None jika tidak ada."""
        return Warga.query.filter_by(nik=nik).first()

    def get_riwayat_peminjaman(self, warga_id: str) -> list:
        """
        Return riwayat peminjaman milik warga, urut terbaru.

        Raises:
            ValueError: Jika warga tidak ditemukan.
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")
        # Delegate ke method model (lazy-load relationship + sort)
        return warga.get_riwayat_peminjaman()

    # ── State Transitions (delegate ke model) ─────────────────
    def blokir(self, warga_id: str) -> Warga:
        """
        Blokir warga aktif (tidak bisa login/pinjam).

        Raises:
            ValueError: Jika warga tidak ditemukan atau statusnya bukan 'aktif'.
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")
        warga.blokir()  # state machine validate
        db.session.commit()
        return warga

    def aktifkan(self, warga_id: str) -> Warga:
        """
        Aktifkan kembali warga yang diblokir.

        Raises:
            ValueError: Jika warga tidak ditemukan atau statusnya bukan 'diblokir'.
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")
        warga.aktifkan_kembali()  # state machine validate
        db.session.commit()
        return warga
