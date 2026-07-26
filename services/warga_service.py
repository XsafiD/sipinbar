"""
services/warga_service.py — Business logic manajemen warga oleh admin.

Berbeda dengan AuthService (login), WargaService fokus pada
operasi CRUD & state transition warga:
  - Create (data_only & aktif)
  - List dengan filter (status, search)
  - Activate warga from data_only
  - Update data (excluding auth fields)
  - Reset password (by admin)
  - Blokir / unblock (delegate ke method model)

Pilar OOP yang terlihat:
  - **Encapsulation**: transisi status (`activate`, `blokir`, `unblock`)
    didelegasikan ke method model — service tidak pernah set
    `warga.status = '...'` secara langsung.
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    warga di layer controller, menyembunyikan detail query SQLAlchemy.

Ref: SIPINBAR v2.0.0 - Admin-controlled account management
"""
import re
from typing import List, Optional

from sqlalchemy import or_

from models import db
from models.warga import Warga


# ── Validator format (dipakai di create & form layer) ────────
NIK_PATTERN = re.compile(r"^\d{16}$")
TELEPON_PATTERN = re.compile(r"^\d{10,15}$")
RT_RW_PATTERN = re.compile(r"^\d{3}/\d{3}$")
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,50}$")


class WargaService:
    """Service layer untuk manajemen warga (akses admin)."""

    # Status warga yang valid (mengacu model.warga.Warga.__state machine__)
    VALID_STATUSES = ("data_only", "aktif", "diblokir")

    # ── Create Warga ─────────────────────────────────────────
    def create_data_only(
        self, nik: str, nama_lengkap: str, alamat: str, telepon: str, rt_rw: str
    ) -> Warga:
        """
        Buat warga baru dengan status 'data_only' (master data, belum bisa login).

        Args:
            nik: NIK 16 digit (unique)
            nama_lengkap: Nama lengkap warga
            alamat: Alamat lengkap
            telepon: Nomor telepon 10-15 digit
            rt_rw: Format RT/RW (contoh: 001/002)

        Returns:
            Instance Warga dengan status 'data_only'

        Raises:
            ValueError: Jika validasi gagal
        """
        # Validasi format
        if not NIK_PATTERN.match(nik):
            raise ValueError("NIK harus terdiri dari 16 digit angka")

        if Warga.query.filter_by(nik=nik).first() is not None:
            raise ValueError(f"NIK '{nik}' sudah terdaftar")

        if not TELEPON_PATTERN.match(telepon):
            raise ValueError("Format telepon tidak valid (10-15 digit angka)")

        if not RT_RW_PATTERN.match(rt_rw):
            raise ValueError("Format RT/RW tidak valid (contoh: 001/002)")

        warga = Warga(
            nik=nik,
            nama_lengkap=nama_lengkap.strip(),
            alamat=alamat.strip(),
            telepon=telepon,
            rt_rw=rt_rw,
            status="data_only",
        )
        db.session.add(warga)
        db.session.commit()
        return warga

    def create_active(
        self,
        nik: str,
        nama_lengkap: str,
        alamat: str,
        telepon: str,
        rt_rw: str,
        username: str,
        password: str,
    ) -> Warga:
        """
        Buat warga baru dengan status 'aktif' (langsung bisa login).

        Args:
            nik: NIK 16 digit (unique)
            nama_lengkap: Nama lengkap warga
            alamat: Alamat lengkap
            telepon: Nomor telepon 10-15 digit
            rt_rw: Format RT/RW (contoh: 001/002)
            username: Username untuk login (3-50 karakter, alphanumeric + underscore)
            password: Password minimal 6 karakter

        Returns:
            Instance Warga dengan status 'aktif'

        Raises:
            ValueError: Jika validasi gagal
        """
        # Validasi format identitas
        if not NIK_PATTERN.match(nik):
            raise ValueError("NIK harus terdiri dari 16 digit angka")

        if Warga.query.filter_by(nik=nik).first() is not None:
            raise ValueError(f"NIK '{nik}' sudah terdaftar")

        if not TELEPON_PATTERN.match(telepon):
            raise ValueError("Format telepon tidak valid (10-15 digit angka)")

        if not RT_RW_PATTERN.match(rt_rw):
            raise ValueError("Format RT/RW tidak valid (contoh: 001/002)")

        # Validasi username & password
        if not USERNAME_PATTERN.match(username):
            raise ValueError(
                "Username hanya boleh alphanumeric dan underscore, 3-50 karakter"
            )

        if Warga.query.filter_by(username=username).first() is not None:
            raise ValueError(f"Username '{username}' sudah digunakan")

        if not password or len(password) < 6:
            raise ValueError("Password minimal 6 karakter")

        # Create warga dengan status data_only dulu
        warga = Warga(
            nik=nik,
            nama_lengkap=nama_lengkap.strip(),
            alamat=alamat.strip(),
            telepon=telepon,
            rt_rw=rt_rw,
            status="data_only",
        )
        db.session.add(warga)
        db.session.flush()  # Get ID tapi belum commit

        # Activate dengan username & password
        warga.activate(username, password)
        db.session.commit()
        return warga

    # ── Query / Read ──────────────────────────────────────────
    def get_all(self, filters: Optional[dict] = None) -> List[Warga]:
        """
        Return list warga, urut terbaru dibuat.

        Filter yang didukung:
          - ``status``: salah satu dari VALID_STATUSES
          - ``q``: search berdasarkan nama atau NIK (case-insensitive LIKE)
          - ``rt``: filter berdasarkan RT (prefix match pada rt_rw)

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

        rt_filter = (filters.get("rt") or "").strip()
        if rt_filter:
            # Filter RT: mencari prefix match pada rt_rw (misal "001" match dengan "001/002")
            query = query.filter(Warga.rt_rw.like(f"{rt_filter}%"))

        return query.order_by(Warga.created_at.desc()).all()

    def get_by_id(self, warga_id: str) -> Optional[Warga]:
        """Return warga berdasarkan ID, atau None jika tidak ada."""
        return db.session.get(Warga, warga_id)

    def get_by_nik(self, nik: str) -> Optional[Warga]:
        """Return warga berdasarkan NIK, atau None jika tidak ada."""
        return Warga.query.filter_by(nik=nik).first()

    def get_by_username(self, username: str) -> Optional[Warga]:
        """Return warga berdasarkan username, atau None jika tidak ada."""
        return Warga.query.filter_by(username=username).first()

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

    # ── Activate Warga ───────────────────────────────────────
    def activate_warga(self, warga_id: str, username: str, password: str) -> Warga:
        """
        Aktivasi warga dari data_only menjadi aktif.

        Args:
            warga_id: ID warga
            username: Username untuk login (unique, 3-50 karakter)
            password: Password untuk login (minimal 6 karakter)

        Returns:
            Instance Warga dengan status 'aktif'

        Raises:
            ValueError: Jika validasi gagal
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        # Delegate ke method model
        warga.activate(username, password)
        db.session.commit()
        return warga

    # ── Update Data ────────────────────────────────────────────
    def update_warga_data(
        self,
        warga_id: str,
        nama_lengkap: str = None,
        alamat: str = None,
        telepon: str = None,
        rt_rw: str = None,
    ) -> Warga:
        """
        Update data warga (field identitas, BUKAN auth fields).

        Args:
            warga_id: ID warga
            nama_lengkap: Nama lengkap baru (opsional)
            alamat: Alamat baru (opsional)
            telepon: Telepon baru (opsional)
            rt_rw: RT/RW baru (opsional)

        Returns:
            Instance Warga yang sudah di-update

        Raises:
            ValueError: Jika warga tidak ditemukan atau validasi gagal
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        # Validasi jika ada perubahan
        if telepon is not None and not TELEPON_PATTERN.match(telepon):
            raise ValueError("Format telepon tidak valid (10-15 digit angka)")

        if rt_rw is not None and not RT_RW_PATTERN.match(rt_rw):
            raise ValueError("Format RT/RW tidak valid (contoh: 001/002)")

        # Delegate ke method model
        warga.update_data(
            nama_lengkap=nama_lengkap,
            alamat=alamat,
            telepon=telepon,
            rt_rw=rt_rw,
        )
        db.session.commit()
        return warga

    # ── Password Management ─────────────────────────────────────
    def reset_password(self, warga_id: str, new_password: str) -> Warga:
        """
        Reset password warga (by admin).

        Args:
            warga_id: ID warga
            new_password: Password baru (minimal 6 karakter)

        Returns:
            Instance Warga yang password-nya sudah di-reset

        Raises:
            ValueError: Jika warga tidak ditemukan atau password tidak valid
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        if not new_password or len(new_password) < 6:
            raise ValueError("Password minimal 6 karakter")

        warga.set_password(new_password)
        db.session.commit()
        return warga

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

    def unblock(self, warga_id: str) -> Warga:
        """
        Aktifkan kembali warga yang diblokir.

        Raises:
            ValueError: Jika warga tidak ditemukan atau statusnya bukan 'diblokir'.
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")
        warga.unblock()  # state machine validate
        db.session.commit()
        return warga

    # ── Delete ─────────────────────────────────────────────────
    def delete(self, warga_id: str) -> None:
        """
        Hapus warga dari database.

        Args:
            warga_id: ID warga

        Raises:
            ValueError: Jika warga tidak ditemukan atau masih memiliki peminjaman aktif
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        # Cek apakah ada peminjaman aktif
        from models.peminjaman import Peminjaman

        active_loans = Peminjaman.query.filter_by(
            warga_id=warga_id, status__in=["diajukan", "dipinjam", "dikembalikan"]
        ).first()
        if active_loans:
            raise ValueError("Warga masih memiliki peminjaman aktif")

        db.session.delete(warga)
        db.session.commit()
