"""
services/auth_service.py — Business logic untuk Autentikasi.

Mengelola:
  - Login multi-aktor (Admin & Warga berdasarkan username)
  - Password change untuk user yang sedang login

Pilar OOP yang terlihat:
  - **Encapsulation**: service tidak tahu detail hashing password —
    cukup panggil `Admin.check_password()` / `Warga.check_password()`.
  - **Abstraction**: bergantung pada kontrak method model (set_password,
    check_password, update_password) tanpa peduli implementasi.

Ref: SIPINBAR v2.0.0 - Username-based authentication
"""
from typing import Optional, Tuple, Union

from models import db
from models.admin import Admin
from models.warga import Warga


class AuthService:
    """Service layer untuk modul Autentikasi (login & password change)."""

    # ── Login: Multi-aktor (Admin / Warga) ─────────────────────
    def login(
        self, identifier: str, password: str
    ) -> Optional[Tuple[Union[Admin, Warga], str]]:
        """
        Verifikasi kredensial login.

        Alur:
          1. Cari Admin berdasarkan `username`.
             Valid jika `is_aktif=True` & password cocok.
          2. Jika tidak ketemu, cari Warga berdasarkan `username` (BUKAN NIK!).
             Valid hanya jika `status='aktif'` & password cocok
             (warga 'data_only'/'diblokir' TIDAK bisa login).
          3. Return tuple ``(user, role)`` atau ``None`` jika gagal.

        Args:
            identifier: Username (admin & warga).
            password: Password plain-text (akan di-hash untuk verifikasi).

        Returns:
            ``(user_instance, "admin" | "warga")`` jika berhasil, ``None`` jika gagal.
        """
        if not identifier or not password:
            return None

        identifier = identifier.strip()

        # ── Strategi 1: Cek Admin (by username) ────────────────
        admin = Admin.query.filter_by(username=identifier).first()
        if admin and admin.is_aktif and admin.check_password(password):
            admin.update_last_login()
            db.session.commit()
            return admin, "admin"

        # ── Strategi 2: Cek Warga (by username, BUKAN NIK!) ───────
        warga = Warga.query.filter_by(username=identifier).first()
        if warga and warga.status == "aktif" and warga.check_password(password):
            return warga, "warga"

        return None

    # ── Password Change ───────────────────────────────────────
    def change_password(
        self, user: Union[Admin, Warga], current_password: str, new_password: str
    ) -> None:
        """
        Ganti password untuk user yang sedang login.

        Args:
            user: Instance Admin atau Warga yang sedang login
            current_password: Password saat ini untuk verifikasi
            new_password: Password baru (minimal 6 karakter)

        Raises:
            ValueError: Jika password saat ini salah atau password baru tidak valid
        """
        if not user.check_password(current_password):
            raise ValueError("Password saat ini salah")

        if not new_password or len(new_password) < 6:
            raise ValueError("Password baru minimal 6 karakter")

        user.set_password(new_password)
        db.session.commit()
