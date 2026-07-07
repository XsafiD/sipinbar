"""
tests/test_warga.py — Test modul manajemen Warga (T-AUTH-07).

Menguji:
  - WargaService.get_all dengan filter status
  - WargaService.blokir & aktifkan (state machine)
  - WargaService.get_riwayat_peminjaman
  - Warga diblokir tidak bisa login
  - Warga controller endpoint ter-proteksi @admin_required (403 untuk warga)
  - Verify & reject via HTTP (controller integration)

Refs: TODO T-AUTH-07, SRS §11.2 TC-01 (lifecycle warga)
"""
import pytest

from models import db
from models.admin import Admin
from models.warga import Warga
from services.auth_service import AuthService
from services.warga_service import WargaService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def warga_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return WargaService()


@pytest.fixture
def auth_service(app):
    """AuthService — depend on `app` agar app context aktif."""
    return AuthService()


@pytest.fixture
def admin_user(app):
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
def beberapa_warga(app):
    """5 warga dengan beragam status untuk test filter."""
    data = [
        Warga(
            nik="3171010101010001",
            nama_lengkap="Warga Aktif A",
            alamat="A",
            telepon="081200000001",
            rt_rw="001/001",
            status="aktif",
        ),
        Warga(
            nik="3171010101010002",
            nama_lengkap="Warga Aktif B",
            alamat="B",
            telepon="081200000002",
            rt_rw="001/002",
            status="aktif",
        ),
        Warga(
            nik="3171010101010003",
            nama_lengkap="Warga Menunggu C",
            alamat="C",
            telepon="081200000003",
            rt_rw="001/003",
            status="menunggu",
        ),
        Warga(
            nik="3171010101010004",
            nama_lengkap="Warga Ditolak D",
            alamat="D",
            telepon="081200000004",
            rt_rw="001/004",
            status="ditolak",
            alasan_penolakan="Data tidak lengkap",
        ),
        Warga(
            nik="3171010101010005",
            nama_lengkap="Warga Diblokir E",
            alamat="E",
            telepon="081200000005",
            rt_rw="001/005",
            status="diblokir",
        ),
    ]
    # Set password hanya untuk warga aktif & diblokir (sudah diverifikasi sebelumnya)
    data[0].set_password("passaktif1")
    data[1].set_password("passaktif2")
    data[4].set_password("passblokir1")
    db.session.add_all(data)
    db.session.commit()
    return data


@pytest.fixture
def login_admin(client, admin_user):
    """Login sebagai admin via test client."""
    client.post(
        "/login",
        data={"username": "admin_test", "password": "admin12345"},
    )


# ── SERVICE LAYER TESTS ──────────────────────────────────────


class TestWargaServiceGetAll:
    """Filter & search warga."""

    def test_get_all_mengembalikan_semua(self, warga_service, beberapa_warga):
        """Tanpa filter → return semua warga."""
        result = warga_service.get_all()
        assert len(result) == 5

    def test_get_all_filter_status_aktif(self, warga_service, beberapa_warga):
        """Filter status=aktif → hanya 2 warga aktif."""
        result = warga_service.get_all({"status": "aktif"})
        assert len(result) == 2
        assert all(w.status == "aktif" for w in result)

    def test_get_all_filter_status_menunggu(self, warga_service, beberapa_warga):
        """Filter status=menunggu → hanya 1."""
        result = warga_service.get_all({"status": "menunggu"})
        assert len(result) == 1
        assert result[0].status == "menunggu"

    def test_get_all_filter_status_invalid_raise(self, warga_service):
        """Filter status tidak valid → ValueError."""
        with pytest.raises(ValueError, match="tidak valid"):
            warga_service.get_all({"status": "hacker"})

    def test_get_all_search_by_nama(self, warga_service, beberapa_warga):
        """Search ?q= → match nama (case-insensitive)."""
        result = warga_service.get_all({"q": "aktif a"})
        assert len(result) == 1
        assert "Aktif A" in result[0].nama_lengkap

    def test_get_by_id_dan_by_nik(self, warga_service, beberapa_warga):
        """Lookup by ID & by NIK konsisten."""
        target = beberapa_warga[0]
        by_id = warga_service.get_by_id(target.id)
        by_nik = warga_service.get_by_nik(target.nik)
        assert by_id is not None
        assert by_nik is not None
        assert by_id.id == by_nik.id == target.id


class TestWargaServiceStateTransition:
    """blokir & aktifkan (state machine)."""

    def test_blokir_warga_aktif_sukses(self, warga_service, beberapa_warga):
        """Blokir warga aktif → status jadi 'diblokir'."""
        target = beberapa_warga[0]
        assert target.status == "aktif"
        result = warga_service.blokir(target.id)
        assert result.status == "diblokir"

    def test_blokir_warga_menunggu_gagal(self, warga_service, beberapa_warga):
        """Blokir warga 'menunggu' → ValueError (state machine ilegal)."""
        target = beberapa_warga[2]  # menunggu
        with pytest.raises(ValueError):
            warga_service.blokir(target.id)

    def test_aktifkan_warga_diblokir_sukses(self, warga_service, beberapa_warga):
        """Aktifkan kembali warga diblokir → status 'aktif'."""
        target = beberapa_warga[4]  # diblokir
        result = warga_service.aktifkan(target.id)
        assert result.status == "aktif"

    def test_aktifkan_warga_sudah_aktif_gagal(self, warga_service, beberapa_warga):
        """Aktifkan warga yang sudah aktif → ValueError."""
        target = beberapa_warga[0]
        with pytest.raises(ValueError):
            warga_service.aktifkan(target.id)


class TestWargaDiblokirTidakBisaLogin:
    """Warga berstatus 'diblokir' tidak bisa login."""

    def test_warga_diblokir_tidak_bisa_login(
        self, auth_service, warga_service, beberapa_warga
    ):
        """Warga diblokir walau password benar → login None."""
        target = beberapa_warga[4]  # diblokir, password 'passblokir1'
        result = auth_service.login(target.nik, "passblokir1")
        assert result is None

    def test_warga_diblokir_lalu_diaktifkan_bisa_login_lagi(
        self, auth_service, warga_service, beberapa_warga
    ):
        """Aktifkan kembali → login berhasil."""
        target = beberapa_warga[4]
        warga_service.aktifkan(target.id)
        result = auth_service.login(target.nik, "passblokir1")
        assert result is not None
        assert result[1] == "warga"


class TestWargaServiceRiwayat:
    """get_riwayat_peminjaman untuk warga baru maupun dengan transaksi."""

    def test_riwayat_warga_baru_kosong(self, warga_service, beberapa_warga):
        """Warga baru → riwayat kosong."""
        target = beberapa_warga[0]
        riwayat = warga_service.get_riwayat_peminjaman(target.id)
        assert riwayat == []

    def test_riwayat_warga_tidak_ditemukan_raise(self, warga_service):
        """ID warga tidak ada → ValueError."""
        with pytest.raises(ValueError, match="tidak ditemukan"):
            warga_service.get_riwayat_peminjaman("ghost-id")


# ── CONTROLLER (HTTP) TESTS ──────────────────────────────────


class TestWargaControllerAccessControl:
    """Role-based access untuk endpoint /admin/warga."""

    def test_daftar_warga_tanpa_login_redirect(self, client):
        """GET /admin/warga/ tanpa login → 302 ke /login."""
        resp = client.get("/admin/warga/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_daftar_warga_sebagai_warga_403(
        self, client, beberapa_warga, auth_service
    ):
        """Login sebagai warga → GET /admin/warga/ → 403 Forbidden."""
        # Login sebagai warga aktif
        target = beberapa_warga[0]
        client.post(
            "/login",
            data={"username": target.nik, "password": "passaktif1"},
        )
        resp = client.get("/admin/warga/")
        assert resp.status_code == 403

    def test_daftar_warga_sebagai_admin_ok(
        self, client, login_admin, beberapa_warga
    ):
        """Login sebagai admin → GET /admin/warga/ → 200."""
        resp = client.get("/admin/warga/")
        assert resp.status_code == 200

    def test_filter_status_di_query_string(
        self, client, login_admin, beberapa_warga
    ):
        """?status=menunggu → hanya tampil warga menunggu."""
        resp = client.get("/admin/warga/?status=menunggu")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Warga Menunggu C" in body
        assert "Warga Aktif A" not in body  # difilter

    def test_detail_warga_sebagai_admin_ok(
        self, client, login_admin, beberapa_warga
    ):
        """GET /admin/warga/<id> → 200 + info warga."""
        target = beberapa_warga[0]
        resp = client.get(f"/admin/warga/{target.id}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert target.nama_lengkap in body
        assert target.nik in body

    def test_detail_warga_tidak_ada_404(self, client, login_admin):
        """GET /admin/warga/ghost-id → 404."""
        resp = client.get("/admin/warga/ghost-id-tidak-ada")
        assert resp.status_code == 404


class TestWargaControllerVerifyReject:
    """Verifikasi & penolakan warga via HTTP (admin)."""

    def test_verify_warga_via_http(
        self, client, login_admin, beberapa_warga
    ):
        """POST /admin/warga/<id>/verify → warga jadi aktif."""
        target = beberapa_warga[2]  # menunggu
        resp = client.post(
            f"/admin/warga/{target.id}/verify",
            data={"password": "passwordbaru123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Reload dari DB
        db.session.refresh(target)
        assert target.status == "aktif"
        assert target.check_password("passwordbaru123")

    def test_reject_warga_via_http(
        self, client, login_admin, beberapa_warga
    ):
        """POST /admin/warga/<id>/reject → warga jadi ditolak."""
        target = beberapa_warga[2]  # menunggu
        resp = client.post(
            f"/admin/warga/{target.id}/reject",
            data={"alasan": "Data NIK mencurigakan"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.refresh(target)
        assert target.status == "ditolak"
        assert target.alasan_penolakan == "Data NIK mencurigakan"

    def test_blokir_warga_via_http(
        self, client, login_admin, beberapa_warga
    ):
        """POST /admin/warga/<id>/blokir → warga jadi diblokir."""
        target = beberapa_warga[0]  # aktif
        resp = client.post(
            f"/admin/warga/{target.id}/blokir",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.refresh(target)
        assert target.status == "diblokir"
