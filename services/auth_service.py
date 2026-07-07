"""
services/auth_service.py — Business logic untuk Autentikasi & Registrasi.

Mengelola:
  - Login multi-aktor (Admin berdasarkan username, Warga berdasarkan NIK)
  - Registrasi warga baru (status awal: 'menunggu')
  - Verifikasi & penolakan warga oleh admin (delegate state transition
    ke method model `Warga.verifikasi()` & `Warga.tolak()`)

Pilar OOP yang terlihat:
  - **Encapsulation**: service tidak tahu detail hashing password —
    cukup panggil `Admin.check_password()` / `Warga.check_password()`.
    Validasi NIK/telepon/RT-RW disembunyikan di dalam method `register_warga`.
  - **Abstraction**: bergantung pada kontrak method model (set_password,
    check_password, verifikasi, tolak) tanpa peduli implementasi.

Refs: SRS §4.1.2, TODO T-AUTH-01
"""
import re
from typing import Optional, Tuple, Union

from models import db
from models.admin import Admin
from models.warga import Warga


# ── Validator format (dipakai di register & form layer) ────────
NIK_PATTERN = re.compile(r"^\d{16}$")
TELEPON_PATTERN = re.compile(r"^\d{10,15}$")
RT_RW_PATTERN = re.compile(r"^\d{3}/\d{3}$")


class AuthService:
    """Service layer untuk modul Autentikasi (login & registrasi warga)."""

    # ── Login: Multi-aktor (Admin / Warga) ─────────────────────
    def login(
        self, identifier: str, password: str
    ) -> Optional[Tuple[Union[Admin, Warga], str]]:
        """
        Verifikasi kredensial login.

        Alur:
          1. Cari Admin berdasarkan `username`.
             Valid jika `is_aktif=True` & password cocok.
          2. Jika tidak ketemu, cari Warga berdasarkan `nik`.
             Valid hanya jika `status='aktif'` & password cocok
             (warga 'menunggu'/'ditolak'/'diblokir' TIDAK bisa login).
          3. Return tuple ``(user, role)`` atau ``None`` jika gagal.

        Args:
            identifier: Username (admin) atau NIK (warga).
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

        # ── Strategi 2: Cek Warga (by NIK) ─────────────────────
        warga = Warga.query.filter_by(nik=identifier).first()
        if warga and warga.status == "aktif" and warga.check_password(password):
            return warga, "warga"

        return None

    # ── Registrasi Warga Baru ──────────────────────────────────
    def register_warga(self, data: dict) -> Warga:
        """
        Registrasi warga baru oleh warga (self-service).

        Status awal: ``'menunggu'`` — belum bisa login sampai diverifikasi admin.
        Password baru di-set saat admin memverifikasi (lihat `verify_warga`).

        Validasi:
          - Semua field wajib (nik, nama_lengkap, alamat, telepon, rt_rw)
          - NIK harus 16 digit angka & unik
          - Telepon 10-15 digit angka
          - RT/RW format ``\\d{3}/\\d{3}`` (contoh: ``001/002``)

        Args:
            data: Dict berisi field form registrasi.

        Raises:
            ValueError: Jika ada validasi gagal (field kosong, format salah,
                        NIK duplikat).

        Returns:
            Instance ``Warga`` yang sudah tersimpan ke DB (status='menunggu').
        """
        required = ("nik", "nama_lengkap", "alamat", "telepon", "rt_rw")
        for field in required:
            value = (data.get(field) or "").strip()
            if not value:
                raise ValueError(f"Field '{field}' wajib diisi")

        nik = data["nik"].strip()
        if not NIK_PATTERN.match(nik):
            raise ValueError("NIK harus terdiri dari 16 digit angka")

        # Cek NIK unik (constraint DB juga enforce, tapi kita kasih pesan ramah)
        if Warga.query.filter_by(nik=nik).first() is not None:
            raise ValueError(f"NIK '{nik}' sudah terdaftar")

        telepon = data["telepon"].strip()
        if not TELEPON_PATTERN.match(telepon):
            raise ValueError("Format telepon tidak valid (10-15 digit angka)")

        rt_rw = data["rt_rw"].strip()
        if not RT_RW_PATTERN.match(rt_rw):
            raise ValueError("Format RT/RW tidak valid (contoh: 001/002)")

        warga = Warga(
            nik=nik,
            nama_lengkap=data["nama_lengkap"].strip(),
            alamat=data["alamat"].strip(),
            telepon=telepon,
            rt_rw=rt_rw,
            status="menunggu",
        )
        db.session.add(warga)
        db.session.commit()
        return warga

    # ── Verifikasi & Penolakan Warga oleh Admin ────────────────
    def verify_warga(self, warga_id: str, password_plain: str) -> Warga:
        """
        Verifikasi warga oleh admin.

        Transisi status: ``menunggu``/``ditolak`` → ``aktif``.
        Password awal warga di-set pada saat ini (sebelumnya belum ada).

        Args:
            warga_id: ID warga (UUID string).
            password_plain: Password awal untuk warga (minimal 6 karakter).

        Raises:
            ValueError: Jika warga tidak ditemukan atau status tidak valid
                        untuk diverifikasi (sudah aktif/diblokir).
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        # Delegate ke method model (encapsulation: state transition)
        # Akan raise ValueError jika status tidak valid atau password < 6 karakter
        warga.verifikasi(password_plain)
        db.session.commit()
        return warga

    def reject_warga(self, warga_id: str, alasan: str) -> Warga:
        """
        Tolak pendaftaran warga.

        Transisi status: ``menunggu`` → ``ditolak``. Alasan wajib diisi.

        Args:
            warga_id: ID warga.
            alasan: Alasan penolakan (tidak boleh kosong).

        Raises:
            ValueError: Jika warga tidak ditemukan, status tidak valid,
                        atau alasan kosong.
        """
        warga = db.session.get(Warga, warga_id)
        if warga is None:
            raise ValueError("Warga tidak ditemukan")

        # Delegate ke method model
        warga.tolak(alasan)
        db.session.commit()
        return warga
