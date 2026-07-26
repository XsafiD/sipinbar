"""
tests/test_auth.py — Test modul Autentikasi SIPINBAR v2.0.0.

Menguji:
  - AuthService.login untuk Admin & Warga (username-based)
  - Password change functionality
  - Password hashing benar (tidak plain-text)
  - Controller endpoint /login, /logout, /change-password
  - Role-based session setelah login

Ref: SIPINBAR v2.0.0 - Username-based authentication, no self-registration
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
    """Warga aktif dengan username & password sudah di-set."""
    w = Warga(
        nik="3171010101010001",
        nama_lengkap="Warga Aktif",
        alamat="Jl. Mawar No. 1",
        telepon="081234567890",
        rt_rw="001/002",
        status="data_only",
    )
    w.activate("warga_aktif", "warga12345")
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def warga_data_only(app):
    """Warga data_only (belum punya username/password)."""
    w = Warga(
        nik="3171010101010002",
        nama_lengkap="Warga Data Only",
        alamat="Jl. Melati No. 2",
        telepon="081234567891",
        rt_rw="003/004",
        status="data_only",
    )
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def warga_diblokir(app):
    """Warga diblokir (pernah aktif, kemudian diblokir)."""
    w = Warga(
        nik="3171010101010003",
        nama_lengkap="Warga Diblokir",
        alamat="Jl. Anggrek No. 3",
        telepon="081234567892",
        rt_rw="005/006",
        status="data_only",
    )
    w.activate("warga_diblokir", "warga12345")
    w.blokir()
    db.session.add(w)
    db.session.commit()
    return w


# ── SERVICE LAYER TESTS ──────────────────────────────────────


class TestAuthServiceLogin:
    """TC-01: Login berhasil & gagal (username-based)."""

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
        """Login warga dengan username + password benar → return (Warga, 'warga')."""
        result = auth_service.login("warga_aktif", "warga12345")
        assert result is not None
        user, role = result
        assert role == "warga"
        assert isinstance(user, Warga)
        assert user.id == warga_aktif.id

    def test_login_warga_data_only_gagal(self, auth_service, warga_data_only):
        """Warga berstatus 'data_only' tidak bisa login walau password benar."""
        # warga_data_only belum punya username, jadi tidak bisa login
        assert auth_service.login("any_username", "apaapa") is None

    def test_login_warga_diblokir_gagal(self, auth_service, warga_diblokir):
        """Warga berstatus 'diblokir' tidak bisa login."""
        assert auth_service.login("warga_diblokir", "warga12345") is None

    def test_login_input_kosong_return_none(self, auth_service):
        """Input kosong (None / '') → None, tidak raise."""
        assert auth_service.login("", "x") is None
        assert auth_service.login("admin", "") is None
        assert auth_service.login(None, None) is None

    def test_login_warga_username_tidak_ada_gagal(self, auth_service):
        """Login warga dengan username tidak terdaftar → None."""
        assert auth_service.login("ghost_warga", "password123") is None


class TestAuthServiceChangePassword:
    """TC-03: Ganti password untuk user yang sedang login."""

    def test_change_password_admin_berhasil(self, auth_service, admin_user):
        """Ganti password admin dengan password saat ini benar → sukses."""
        auth_service.change_password(admin_user, "admin12345", "newpass123")
        # Verifikasi password baru
        assert admin_user.check_password("newpass123") is True
        assert admin_user.check_password("admin12345") is False

    def test_change_password_gagal_password_salah(self, auth_service, admin_user):
        """Ganti password dengan password saat ini salah → ValueError."""
        with pytest.raises(ValueError, match="salah"):
            auth_service.change_password(admin_user, "password_salah", "newpass123")

    def test_change_password_gagal_password_baru_kurang_dari_6(self, auth_service, admin_user):
        """Password baru kurang dari 6 karakter → ValueError."""
        with pytest.raises(ValueError, match="minimal 6 karakter"):
            auth_service.change_password(admin_user, "admin12345", "short")

    def test_change_password_warga_berhasil(self, auth_service, warga_aktif):
        """Ganti password warga dengan password saat ini benar → sukses."""
        auth_service.change_password(warga_aktif, "warga12345", "newwarga123")
        # Verifikasi password baru
        assert warga_aktif.check_password("newwarga123") is True
        assert warga_aktif.check_password("warga12345") is False


class TestPasswordHashing:
    """TC-04: Password hashing benar (bukan plain-text)."""

    def test_admin_password_tidak_plain(self, admin_user):
        """Password admin disimpan sebagai hash, bukan plain-text."""
        assert admin_user.password_hash is not None
        assert admin_user.password_hash != "admin12345"
        assert "|" not in admin_user.password_hash  # Bukan format pipe

    def test_warga_password_tidak_plain(self, warga_aktif):
        """Password warga disimpan sebagai hash, bukan plain-text."""
        assert warga_aktif.password_hash is not None
        assert warga_aktif.password_hash != "warga12345"
        assert "|" not in warga_aktif.password_hash

    def test_password_minimal_6_karakter(self, app):
        """Password minimal 6 karakter → enforced di model."""
        admin = Admin(username="admin_pwd", nama_lengkap="Admin Pwd", role="admin")
        with pytest.raises(ValueError, match="minimal 6 karakter"):
            admin.set_password("short")

        # Valid password sukses
        admin.set_password("valid123")
        assert admin.password_hash is not None


# ── CONTROLLER LAYER TESTS ─────────────────────────────────────


class TestAuthControllerLogin:
    """TC-05: Login endpoint (/login) GET & POST."""

    def test_get_login_menampilkan_form(self, client):
        """GET /login → 200 + form field ter-render."""
        response = client.get("/login")
        assert response.status_code == 200
        # Cek form field ada di HTML
        assert b"type=\"password\"" in response.data
        assert b"name=\"username\"" in response.data
        # Cek tidak ada link register (v2.0.0)
        assert b"/register" not in response.data

    def test_post_login_admin_berhasil_redirect_dashboard(self, client, admin_user):
        """POST /login dengan kredensial admin benar → redirect ke /dashboard."""
        response = client.post(
            "/login", data={"username": "admin_test", "password": "admin12345"}, follow_redirects=False
        )
        assert response.status_code == 302  # redirect
        assert response.headers["Location"] == "/dashboard"

        # Follow redirect
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_post_login_berhasil_set_session_role(self, client, admin_user):
        """POST /login berhasil → session ter-set dengan user_id & role."""
        response = client.post(
            "/login", data={"username": "admin_test", "password": "admin12345"}, follow_redirects=False
        )
        assert response.status_code == 302

        # Cek session cookie
        session_cookie = [c for c in response.headers.getlist("Set-Cookie") if "session" in c]
        assert len(session_cookie) > 0

        # Follow redirect & cek session
        response = client.get("/dashboard")
        assert response.status_code == 200
        # User info seharusnya muncul di dashboard
        assert b"Admin Test" in response.data or b"Logout" in response.data

    def test_post_login_password_salah_render_ulang_dengan_flash(self, client, admin_user):
        """POST /login password salah → tetap di /login + flash error."""
        response = client.post(
            "/login", data={"username": "admin_test", "password": "salah_sangat"}, follow_redirects=False
        )
        assert response.status_code == 200  # tetap di login
        assert b"Username atau password salah" in response.data

    def test_post_login_username_tidak_ada_render_ulang_dengan_flash(self, client):
        """POST /login username tidak ada → tetap di /login + flash error."""
        response = client.post(
            "/login", data={"username": "tidak_ada", "password": "apaaja"}, follow_redirects=False
        )
        assert response.status_code == 200
        assert b"Username atau password salah" in response.data


class TestAuthControllerLogout:
    """TC-06: Logout endpoint (/logout)."""

    def test_logout_menghapus_session(self, client, admin_user):
        """GET /logout → session dihapus + redirect ke /login."""
        # Login dulu
        client.post("/login", data={"username": "admin_test", "password": "admin12345"})

        # Logout
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"

    def test_logout_tanpa_login_redirect_login(self, client):
        """GET /logout tanpa login → tetap redirect ke /login."""
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"


class TestAuthControllerChangePassword:
    """TC-07: Change Password endpoint (/change-password) v2.0.0."""

    def test_get_change_password_memampilkan_form(self, client, admin_user):
        """GET /change-password → 200 + form field ter-render."""
        # Login dulu
        client.post("/login", data={"username": "admin_test", "password": "admin12345"})

        response = client.get("/change-password")
        assert response.status_code == 200
        assert b"type=\"password\"" in response.data
        assert b"current_password" in response.data
        assert b"new_password" in response.data
        assert b"confirm_password" in response.data

    def test_post_change_password_berhasil(self, client, admin_user):
        """POST /change-password dengan data valid → redirect dashboard + flash sukses."""
        # Login dulu
        client.post("/login", data={"username": "admin_test", "password": "admin12345"})

        response = client.post(
            "/change-password",
            data={
                "current_password": "admin12345",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302  # redirect
        assert response.headers["Location"] == "/dashboard"

        # Follow redirect & cek flash message
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"Password berhasil diubah" in response.data

    def test_post_change_password_gagal_konfirmasi_tidak_cocok(self, client, admin_user):
        """POST /change-password dengan konfirmasi salah → render ulang dengan error."""
        # Login dulu
        client.post("/login", data={"username": "admin_test", "password": "admin12345"})

        response = client.post(
            "/change-password",
            data={
                "current_password": "admin12345",
                "new_password": "newpass123",
                "confirm_password": "beda",  # konfirmasi beda
            },
            follow_redirects=False,
        )
        assert response.status_code == 200  # tetap di halaman
        assert b"tidak cocok" in response.data or "cocok" in response.data

    def test_post_change_password_gagal_password_salah(self, client, admin_user):
        """POST /change-password dengan password saat ini salah → render ulang dengan error."""
        # Login dulu
        client.post("/login", data={"username": "admin_test", "password": "admin12345"})

        response = client.post(
            "/change-password",
            data={
                "current_password": "password_salah",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
            follow_redirects=False,
        )
        assert response.status_code == 200  # tetap di halaman
        assert b"salah" in response.data

    def test_change_password_tanpa_login_redirect_login(self, client):
        """GET/POST /change-password tanpa login → redirect ke /login."""
        response = client.get("/change-password", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"] == "/login"
