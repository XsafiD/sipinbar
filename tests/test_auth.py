"""
tests/test_auth.py — Test modul Autentikasi (T-AUTH-06).

Menguji:
  - AuthService.login untuk Admin & Warga (happy + error path)
  - AuthService.register_warga (valid, NIK duplikat, format invalid)
  - AuthService.verify_warga & reject_warga
  - Password hashing benar (tidak plain-text)
  - Controller endpoint /login, /logout, /register (HTTP level)
  - Role-based session setelah login

Refs: SRS §11.2 TC-01 & TC-02, TODO T-AUTH-06
"""
import pytest

from models import db
from models.admin import Admin
from models.warga import Warga
from services.auth_service import AuthService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def auth_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return AuthService()


@pytest.fixture
def admin_user(app):
    """Admin aktif untuk test login."""
    admin = Admin(
        username="admin_test",
        nama_lengkap="Admin Test",
        role="admin",
        is_aktif=True,
    )
    admin.set_password("admin12345")
    db.session.add(admin)
    db.session.commit()
    return admin


@pytest.fixture
def warga_aktif(app):
    """Warga aktif dengan password sudah di-set."""
    w = Warga(
        nik="3171010101010001",
        nama_lengkap="Warga Aktif",
        alamat="Jl. Mawar No. 1",
        telepon="081234567890",
        rt_rw="001/002",
        status="aktif",
    )
    w.set_password("warga12345")
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def warga_menunggu(app):
    """Warga menunggu verifikasi (belum punya password)."""
    w = Warga(
        nik="3171010101010002",
        nama_lengkap="Warga Menunggu",
        alamat="Jl. Melati No. 2",
        telepon="081234567891",
        rt_rw="003/004",
        status="menunggu",
    )
    db.session.add(w)
    db.session.commit()
    return w


# ── SERVICE LAYER TESTS ──────────────────────────────────────


class TestAuthServiceLogin:
    """TC-01: Login berhasil; TC-02: Login gagal."""

    def test_login_admin_berhasil(self, auth_service, admin_user):
        """Login admin dengan username + password benar → return (Admin, 'admin')."""
        result = auth_service.login("admin_test", "admin12345")
        assert result is not None
        user, role = result
        assert role == "admin"
        assert isinstance(user, Admin)
        assert user.id == admin_user.id
        # last_login_at ter-update
        assert user.last_login_at is not None

    def test_login_admin_gagal_password_salah(self, auth_service, admin_user):
        """Login admin dengan password salah → None."""
        assert auth_service.login("admin_test", "salah") is None

    def test_login_admin_gagal_username_tidak_ada(self, auth_service):
        """Login admin dengan username tidak terdaftar → None."""
        assert auth_service.login("ghost_user", "apaaja") is None

    def test_login_warga_berhasil(self, auth_service, warga_aktif):
        """Login warga dengan NIK + password benar → return (Warga, 'warga')."""
        result = auth_service.login("3171010101010001", "warga12345")
        assert result is not None
        user, role = result
        assert role == "warga"
        assert isinstance(user, Warga)
        assert user.id == warga_aktif.id

    def test_login_warga_menunggu_gagal(self, auth_service, warga_menunggu):
        """Warga berstatus 'menunggu' tidak bisa login walau password benar."""
        # warga_menunggu belum punya password_hash, jadi memang tidak bisa login
        assert auth_service.login("3171010101010002", "apaapa") is None

    def test_login_warga_diblokir_gagal(self, auth_service, warga_aktif):
        """Warga berstatus 'diblokir' tidak bisa login."""
        warga_aktif.blokir()
        db.session.commit()
        assert auth_service.login("3171010101010001", "warga12345") is None

    def test_login_input_kosong_return_none(self, auth_service):
        """Input kosong (None / '') → None, tidak raise."""
        assert auth_service.login("", "x") is None
        assert auth_service.login("admin", "") is None
        assert auth_service.login(None, None) is None


class TestAuthServiceRegister:
    """TC-02 register: valid, duplikat, format invalid."""

    def test_register_warga_berhasil_status_menunggu(self, auth_service, app):
        """Register valid → warga tersimpan dengan status='menunggu'."""
        data = {
            "nik": "3171010101010010",
            "nama_lengkap": "Budi Santoso",
            "alamat": "Jl. Kenanga No. 5",
            "telepon": "081299988877",
            "rt_rw": "005/006",
        }
        w = auth_service.register_warga(data)
        assert w.id is not None
        assert w.nik == "3171010101010010"
        assert w.status == "menunggu"
        # Password belum di-set sampai verifikasi
        assert w.password_hash is None

    def test_register_nik_duplikat_gagal(self, auth_service, warga_aktif):
        """Register NIK yang sudah ada → ValueError."""
        with pytest.raises(ValueError, match="sudah terdaftar"):
            auth_service.register_warga(
                {
                    "nik": "3171010101010001",  # sama dengan warga_aktif
                    "nama_lengkap": "Peniru",
                    "alamat": "Jl. X",
                    "telepon": "081200000000",
                    "rt_rw": "001/001",
                }
            )

    def test_register_nik_format_invalid(self, auth_service):
        """NIK bukan 16 digit → ValueError."""
        with pytest.raises(ValueError, match="NIK"):
            auth_service.register_warga(
                {
                    "nik": "123",  # terlalu pendek
                    "nama_lengkap": "X",
                    "alamat": "Y",
                    "telepon": "081234567890",
                    "rt_rw": "001/002",
                }
            )

    def test_register_telepon_format_invalid(self, auth_service):
        """Telepon dengan huruf → ValueError."""
        with pytest.raises(ValueError, match="telepon"):
            auth_service.register_warga(
                {
                    "nik": "3171010101010020",
                    "nama_lengkap": "X",
                    "alamat": "Y",
                    "telepon": "08abc",  # huruf
                    "rt_rw": "001/002",
                }
            )

    def test_register_rt_rw_format_invalid(self, auth_service):
        """RT/RW format salah → ValueError."""
        with pytest.raises(ValueError, match="RT/RW"):
            auth_service.register_warga(
                {
                    "nik": "3171010101010030",
                    "nama_lengkap": "X",
                    "alamat": "Y",
                    "telepon": "081234567890",
                    "rt_rw": "1/2",  # format salah
                }
            )

    def test_register_field_kosong_gagal(self, auth_service):
        """Field wajib kosong → ValueError."""
        with pytest.raises(ValueError, match="wajib diisi"):
            auth_service.register_warga(
                {
                    "nik": "3171010101010040",
                    "nama_lengkap": "",
                    "alamat": "Y",
                    "telepon": "081234567890",
                    "rt_rw": "001/002",
                }
            )


class TestAuthServiceVerifyReject:
    """Verifikasi & penolakan warga oleh admin."""

    def test_verify_warga_menunggu_jadi_aktif(self, auth_service, warga_menunggu):
        """Verifikasi: menunggu → aktif, password ter-set."""
        verified = auth_service.verify_warga(warga_menunggu.id, "newpass123")
        assert verified.status == "aktif"
        assert verified.password_hash is not None
        # Password ter-hash (bukan plain)
        assert "newpass123" not in (verified.password_hash or "")
        assert verified.check_password("newpass123") is True
        assert verified.verified_at is not None

    def test_verify_warga_tidak_ditemukan(self, auth_service):
        """Verify ID tidak ada → ValueError."""
        with pytest.raises(ValueError, match="tidak ditemukan"):
            auth_service.verify_warga("nonexistent-id", "pass123")

    def test_verify_warga_sudah_aktif_gagal(self, auth_service, warga_aktif):
        """Verifikasi warga yang sudah aktif → ValueError (state machine)."""
        with pytest.raises(ValueError):
            auth_service.verify_warga(warga_aktif.id, "pass123")

    def test_reject_warga_menunggu_jadi_ditolak(self, auth_service, warga_menunggu):
        """Reject: menunggu → ditolak dengan alasan."""
        rejected = auth_service.reject_warga(
            warga_menunggu.id, "Data NIK tidak lengkap"
        )
        assert rejected.status == "ditolak"
        assert rejected.alasan_penolakan == "Data NIK tidak lengkap"

    def test_reject_tanpa_alasan_gagal(self, auth_service, warga_menunggu):
        """Reject tanpa alasan → ValueError."""
        with pytest.raises(ValueError):
            auth_service.reject_warga(warga_menunggu.id, "   ")


class TestPasswordHashing:
    """Validasi password hashing di model (encapsulation)."""

    def test_admin_password_tidak_plain(self, admin_user):
        """password_hash ≠ plain text."""
        assert admin_user.password_hash != "admin12345"
        assert len(admin_user.password_hash) > 30  # PBKDF2 hash panjang

    def test_warga_password_tidak_plain(self, warga_aktif):
        """password_hash ≠ plain text."""
        assert warga_aktif.password_hash != "warga12345"
        assert warga_aktif.check_password("warga12345") is True
        assert warga_aktif.check_password("salah") is False

    def test_password_minimal_6_karakter(self, app):
        """Password < 6 karakter → ValueError."""
        w = Warga(
            nik="3171010101010099",
            nama_lengkap="X",
            alamat="Y",
            telepon="081234567890",
            rt_rw="001/002",
        )
        with pytest.raises(ValueError, match="minimal 6"):
            w.set_password("123")


# ── CONTROLLER (HTTP) TESTS ──────────────────────────────────


class TestAuthControllerLogin:
    """TC-01 & TC-02 via HTTP test client."""

    def test_get_login_menampilkan_form(self, client):
        """GET /login → 200, mengandung field username & password."""
        resp = client.get("/login")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "username" in body.lower()
        assert "password" in body.lower()

    def test_post_login_admin_berhasil_redirect_dashboard(
        self, client, admin_user
    ):
        """POST /login admin valid → 302 redirect ke /dashboard."""
        resp = client.post(
            "/login",
            data={"username": "admin_test", "password": "admin12345"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    def test_post_login_berhasil_set_session_role(
        self, client, admin_user
    ):
        """Login berhasil → session berisi user_id, role, nama."""
        with client.session_transaction() as sess:
            assert "user_id" not in sess  # belum login
        client.post(
            "/login",
            data={"username": "admin_test", "password": "admin12345"},
        )
        with client.session_transaction() as sess:
            assert sess["user_id"] == admin_user.id
            assert sess["role"] == "admin"
            assert sess["nama"] == "Admin Test"

    def test_post_login_password_salah_render_ulang_dengan_flash(
        self, client, admin_user
    ):
        """Login gagal → 401 (render ulang form) + flash error."""
        resp = client.post(
            "/login",
            data={"username": "admin_test", "password": "salahbanget"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        body = resp.get_data(as_text=True)
        assert "password salah" in body.lower()

    def test_logout_menghapus_session(self, client, admin_user):
        """Logout → session kosong + redirect ke /login."""
        # Login dulu
        client.post(
            "/login",
            data={"username": "admin_test", "password": "admin12345"},
        )
        # Logout
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_logout_tanpa_login_redirect_login(self, client):
        """Akses /logout tanpa login → redirect ke /login (login_required)."""
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestAuthControllerRegister:
    """Endpoint /register via HTTP."""

    def test_get_register_menampilkan_form(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "nik" in body.lower()
        assert "nama_lengkap" in body.lower()

    def test_post_register_berhasil_redirect_login(self, client, app):
        """Register valid → 302 ke /login + warga tersimpan."""
        resp = client.post(
            "/register",
            data={
                "nik": "3171010101010100",
                "nama_lengkap": "Budi",
                "alamat": "Jl. ABC",
                "telepon": "081234567890",
                "rt_rw": "001/002",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        # Pastikan tersimpan
        with app.app_context():
            w = Warga.query.filter_by(nik="3171010101010100").first()
            assert w is not None
            assert w.status == "menunggu"

    def test_post_register_nik_duplikat_render_error(self, client, warga_aktif):
        """Register NIK duplikat → render ulang + flash error."""
        resp = client.post(
            "/register",
            data={
                "nik": "3171010101010001",  # duplikat
                "nama_lengkap": "Peniru",
                "alamat": "Jl. X",
                "telepon": "081200000000",
                "rt_rw": "001/002",
            },
            follow_redirects=False,
        )
        # Tidak redirect (form render ulang)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "sudah terdaftar" in body.lower()
