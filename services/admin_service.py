"""
services/admin_service.py — Business logic manajemen admin oleh super admin.

Service ini menangani operasi CRUD untuk admin:
  - Create admin baru
  - List semua admin
  - Update admin (nama, is_aktif)
  - Reset password admin
  - Activate/deactivate admin

Pilar OOP:
  - **Encapsulation**: transisi status (activate/deactivate) dan password
    management didelegasikan ke method model
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    admin di layer controller

Ref: SIPINBAR v2.0.0 - Multi-admin support
"""
import re
from typing import List, Optional

from models import db
from models.admin import Admin


# ── Validator format ────────────────────────────────────────────
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,50}$")


class AdminService:
    """Service layer untuk manajemen admin (akses super admin)."""

    # ── Create Admin ─────────────────────────────────────────────
    def create_admin(
        self, username: str, password: str, nama_lengkap: str, role: str = "admin"
    ) -> Admin:
        """
        Buat admin baru.

        Args:
            username: Username untuk login (3-50 karakter, alphanumeric + underscore)
            password: Password minimal 6 karakter
            nama_lengkap: Nama lengkap admin
            role: Role admin (default: 'admin')

        Returns:
            Instance Admin yang baru dibuat

        Raises:
            ValueError: Jika validasi gagal
        """
        # Validasi username
        if not USERNAME_PATTERN.match(username):
            raise ValueError(
                "Username hanya boleh alphanumeric dan underscore, 3-50 karakter"
            )

        if Admin.query.filter_by(username=username).first() is not None:
            raise ValueError(f"Username '{username}' sudah digunakan")

        # Validasi password
        if not password or len(password) < 6:
            raise ValueError("Password minimal 6 karakter")

        # Validasi nama
        if not nama_lengkap or len(nama_lengkap.strip()) < 3:
            raise ValueError("Nama lengkap minimal 3 karakter")

        # Create admin
        admin = Admin(
            username=username,
            nama_lengkap=nama_lengkap.strip(),
            role=role,
            is_aktif=True,
        )
        admin.set_password(password)

        db.session.add(admin)
        db.session.commit()
        return admin

    # ── Query / Read ──────────────────────────────────────────────
    def get_all(self, include_inactive: bool = False) -> List[Admin]:
        """
        Return list semua admin.

        Args:
            include_inactive: Jika True, termasuk admin yang non-aktif

        Returns:
            List instance Admin
        """
        query = Admin.query
        if not include_inactive:
            query = query.filter_by(is_aktif=True)

        return query.order_by(Admin.created_at.desc()).all()

    def get_by_id(self, admin_id: str) -> Optional[Admin]:
        """Return admin berdasarkan ID, atau None jika tidak ada."""
        return db.session.get(Admin, admin_id)

    def get_by_username(self, username: str) -> Optional[Admin]:
        """Return admin berdasarkan username, atau None jika tidak ada."""
        return Admin.query.filter_by(username=username).first()

    # ── Update Admin ─────────────────────────────────────────────
    def update_admin(
        self, admin_id: str, nama_lengkap: str = None, role: str = None
    ) -> Admin:
        """
        Update data admin (nama dan role).

        Args:
            admin_id: ID admin
            nama_lengkap: Nama lengkap baru (opsional)
            role: Role baru (opsional)

        Returns:
            Instance Admin yang sudah di-update

        Raises:
            ValueError: Jika admin tidak ditemukan atau validasi gagal
        """
        admin = db.session.get(Admin, admin_id)
        if admin is None:
            raise ValueError("Admin tidak ditemukan")

        if nama_lengkap is not None:
            if len(nama_lengkap.strip()) < 3:
                raise ValueError("Nama lengkap minimal 3 karakter")
            admin.nama_lengkap = nama_lengkap.strip()

        if role is not None:
            admin.role = role

        db.session.commit()
        return admin

    # ── Password Management ───────────────────────────────────────
    def reset_admin_password(self, admin_id: str, new_password: str) -> Admin:
        """
        Reset password admin (by super admin).

        Args:
            admin_id: ID admin
            new_password: Password baru (minimal 6 karakter)

        Returns:
            Instance Admin yang password-nya sudah di-reset

        Raises:
            ValueError: Jika admin tidak ditemukan atau password tidak valid
        """
        admin = db.session.get(Admin, admin_id)
        if admin is None:
            raise ValueError("Admin tidak ditemukan")

        if not new_password or len(new_password) < 6:
            raise ValueError("Password minimal 6 karakter")

        admin.set_password(new_password)
        db.session.commit()
        return admin

    # ── Activate/Deactivate Admin ────────────────────────────────
    def activate_admin(self, admin_id: str) -> Admin:
        """
        Aktifkan admin yang sebelumnya non-aktif.

        Args:
            admin_id: ID admin

        Returns:
            Instance Admin yang sudah di-aktifkan

        Raises:
            ValueError: Jika admin tidak ditemukan
        """
        admin = db.session.get(Admin, admin_id)
        if admin is None:
            raise ValueError("Admin tidak ditemukan")

        admin.activate()
        db.session.commit()
        return admin

    def deactivate_admin(self, admin_id: str) -> Admin:
        """
        Non-aktifkan admin.

        Args:
            admin_id: ID admin

        Returns:
            Instance Admin yang sudah di-non-aktifkan

        Raises:
            ValueError: Jika admin tidak ditemukan
        """
        admin = db.session.get(Admin, admin_id)
        if admin is None:
            raise ValueError("Admin tidak ditemukan")

        admin.deactivate()
        db.session.commit()
        return admin

    # ── Delete Admin ─────────────────────────────────────────────
    def delete_admin(self, admin_id: str) -> None:
        """
        Hapus admin dari database.

        Args:
            admin_id: ID admin

        Raises:
            ValueError: Jika admin tidak ditemukan
        """
        admin = db.session.get(Admin, admin_id)
        if admin is None:
            raise ValueError("Admin tidak ditemukan")

        db.session.delete(admin)
        db.session.commit()
