"""
tests/test_notifikasi.py — Test modul Notifikasi (T-LAP-05).

Menguji:
  - NotifikasiService.kirim_pengingat (H-1, bukan H-1, status bukan dipinjam,
    anti-spam, peminjaman tidak ada)
  - NotifikasiService.kirim_notifikasi_status (info/peringatan, status tidak
    perlu notif, status invalid)
  - NotifikasiService.get_by_warga, get_unread_count, get_by_id
  - NotifikasiService.tandai_dibaca (happy, idempoten, tidak ada),
    tandai_semua_dibaca
  - NotifikasiService.check_and_send_reminders (TC-15: H-1 terkirim,
    tidak ada kandidat, anti-spam, skip status bukan dipinjam)
  - Controller HTTP: access control (login_required, owner-only),
    happy path tandai dibaca, daftar notifikasi
  - Flask CLI ``flask send-reminders`` via test_cli_runner

Refs: TODO T-LAP-05, SRS §11.2 TC-15
"""
from datetime import date, timedelta

import pytest

from models import db
from models.admin import Admin
from models.barang import Barang, Kategori
from models.warga import Warga
from services.notifikasi_service import NotifikasiService
from services.peminjaman_service import PeminjamanService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def notifikasi_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return NotifikasiService()


@pytest.fixture
def peminjaman_service(app):
    """PeminjamanService untuk setup peminjaman berstatus dipinjam."""
    return PeminjamanService()


@pytest.fixture
def kategori_set(app):
    data = [
        Kategori(nama="Elektronik", tarif_denda_per_hari=5000),
        Kategori(nama="Furniture", tarif_denda_per_hari=2000),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {k.nama: k for k in data}


@pytest.fixture
def barang_set(app, kategori_set):
    data = [
        Barang(nama="Proyektor", kategori_id=kategori_set["Elektronik"].id, jumlah_unit=2),
        Barang(nama="Kursi Lipat", kategori_id=kategori_set["Furniture"].id, jumlah_unit=10),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {b.nama: b for b in data}


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
def warga_aktif(app):
    w = Warga(
        nik="3171010101010001",
        nama_lengkap="Warga Aktif",
        alamat="Jl. Test",
        telepon="081234567890",
        rt_rw="001/002",
        status="aktif",
    )
    w.set_password("warga12345")
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def login_admin(client, admin_user):
    client.post("/login", data={"username": "admin_test", "password": "admin12345"})


@pytest.fixture
def login_warga(client, warga_aktif):
    client.post(
        "/login",
        data={"username": warga_aktif.nik, "password": "warga12345"},
    )


# ── Helper tanggal ───────────────────────────────────────────
TODAY = date.today()
TMROW = TODAY + timedelta(days=1)
DAY_AFTER = TODAY + timedelta(days=2)


def _buat_peminjaman_dipinjam(service, warga, barang, admin, tgl_kembali):
    """Setup peminjaman berstatus 'dipinjam' dengan tanggal_kembali_rencana custom."""
    pjm = service.ajukan(
        warga_id=warga.id,
        items=[{"barang_id": barang.id, "jumlah": 1}],
        tgl_pinjam=TODAY,
        tgl_kembali=tgl_kembali,
    )
    service.setujui(pjm.id, admin.id)
    service.mulai_pinjam(pjm.id)
    return pjm


# ════════════════════════════════════════════════════════════
#  SERVICE LAYER TESTS
# ════════════════════════════════════════════════════════════

class TestNotifikasiServiceKirimPengingat:
    """Test kirim_pengingat (H-1 jatuh tempo)."""

    def test_kirim_pengingat_h_minus_1(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Peminjaman dipinjam & jatuh tempo besok → notif terkirim."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)

        assert notif is not None
        assert notif.tipe == "pengingat"
        assert notif.warga_id == warga_aktif.id
        assert notif.peminjaman_id == pjm.id
        assert notif.is_dibaca is False
        assert "jatuh tempo besok" in notif.pesan

    def test_kirim_pengingat_bukan_h_minus_1(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Jatuh tempo lusa (H-2) → None, tidak ada notif."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, DAY_AFTER
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif is None

    def test_kirim_pengingat_status_bukan_dipinjam(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Status 'disetujui' (belum dipinjam) → None."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY,
            tgl_kembali=TMROW,
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        # Status sekarang 'disetujui', belum dipinjam
        notif = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif is None

    def test_kirim_pengingat_peminjaman_tidak_ada(self, notifikasi_service):
        """Peminjaman tidak ditemukan → ValueError."""
        with pytest.raises(ValueError, match="Peminjaman tidak ditemukan"):
            notifikasi_service.kirim_pengingat("nonexistent-id")

    def test_kirim_pengingat_anti_spam(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Pemanggilan kedua hari yang sama → None (anti-spam)."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif1 = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif1 is not None

        notif2 = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif2 is None  # sudah dikirim hari ini


class TestNotifikasiServiceKirimStatus:
    """Test kirim_notifikasi_status."""

    def test_kirim_notifikasi_status_disetujui(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Status disetujui → notif tipe 'info'."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        notif = notifikasi_service.kirim_notifikasi_status(pjm.id, "disetujui")

        assert notif is not None
        assert notif.tipe == "info"
        assert "disetujui" in notif.pesan.lower()

    def test_kirim_notifikasi_status_ditolak(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Status ditolak → notif tipe 'peringatan'."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.tolak(pjm.id, admin_user.id, "Tidak tersedia")
        notif = notifikasi_service.kirim_notifikasi_status(pjm.id, "ditolak")

        assert notif is not None
        assert notif.tipe == "peringatan"

    def test_kirim_notifikasi_status_diajukan_tidak_ada_notif(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set
    ):
        """Status 'diajukan' tidak mengirim notif (warga sendiri yang ajukan)."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        notif = notifikasi_service.kirim_notifikasi_status(pjm.id, "diajukan")
        assert notif is None

    def test_kirim_notifikasi_status_peminjaman_tidak_ada(
        self, notifikasi_service
    ):
        """Peminjaman tidak ditemukan → ValueError."""
        with pytest.raises(ValueError, match="Peminjaman tidak ditemukan"):
            notifikasi_service.kirim_notifikasi_status("no-id", "disetujui")


class TestNotifikasiServiceQuery:
    """Test get_by_warga, get_unread_count, get_by_id."""

    def test_get_by_warga(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """get_by_warga return list notif milik warga."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notifikasi_service.kirim_pengingat(pjm.id)
        notifikasi_service.kirim_notifikasi_status(pjm.id, "dipinjam")

        result = notifikasi_service.get_by_warga(warga_aktif.id)
        assert len(result) == 2
        # Urut terbaru
        assert result[0].created_at >= result[1].created_at

    def test_get_by_warga_only_unread(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """get_by_warga(only_unread=True) hanya yang belum dibaca."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)
        notifikasi_service.tandai_dibaca(notif.id)

        result = notifikasi_service.get_by_warga(warga_aktif.id, only_unread=True)
        assert len(result) == 0

    def test_get_by_warga_isolasi_antar_warga(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user, app
    ):
        """Notifikasi warga A tidak muncul di list warga B."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notifikasi_service.kirim_pengingat(pjm.id)

        # Buat warga lain
        with app.app_context():
            warga_lain = Warga(
                nik="3171010101010099",
                nama_lengkap="Warga Lain",
                alamat="Jl. Lain",
                telepon="081234567899",
                rt_rw="001/002",
                status="aktif",
            )
            warga_lain.set_password("pass12345")
            db.session.add(warga_lain)
            db.session.commit()
            warga_lain_id = warga_lain.id

        # Warga lain tidak punya notif
        result = notifikasi_service.get_by_warga(warga_lain_id)
        assert len(result) == 0

    def test_get_unread_count(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """get_unread_count return jumlah belum dibaca."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif1 = notifikasi_service.kirim_pengingat(pjm.id)
        notifikasi_service.kirim_notifikasi_status(pjm.id, "dipinjam")

        assert notifikasi_service.get_unread_count(warga_aktif.id) == 2

        notifikasi_service.tandai_dibaca(notif1.id)
        assert notifikasi_service.get_unread_count(warga_aktif.id) == 1

    def test_get_by_id_tidak_ada(self, notifikasi_service):
        """get_by_id return None jika tidak ada."""
        assert notifikasi_service.get_by_id("nope") is None


class TestNotifikasiServiceTandaiDibaca:
    """Test tandai_dibaca & tandai_semua_dibaca."""

    def test_tandai_dibaca_berhasil(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Tandai dibaca → is_dibaca True, dibaca_at terisi."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif.is_dibaca is False

        updated = notifikasi_service.tandai_dibaca(notif.id)
        assert updated.is_dibaca is True
        assert updated.dibaca_at is not None

    def test_tandai_dibaca_idempoten(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Tandai dibaca 2x tidak error (idempoten)."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)

        notifikasi_service.tandai_dibaca(notif.id)
        # Kedua kalinya tetap berhasil
        notifikasi_service.tandai_dibaca(notif.id)
        assert notif.is_dibaca is True

    def test_tandai_dibaca_tidak_ada(self, notifikasi_service):
        """Notifikasi tidak ditemukan → ValueError."""
        with pytest.raises(ValueError, match="Notifikasi tidak ditemukan"):
            notifikasi_service.tandai_dibaca("nonexistent-id")

    def test_tandai_semua_dibaca(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Tandai semua dibaca → semua notif warga jadi dibaca."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notifikasi_service.kirim_pengingat(pjm.id)
        notifikasi_service.kirim_notifikasi_status(pjm.id, "dipinjam")

        assert notifikasi_service.get_unread_count(warga_aktif.id) == 2

        jumlah = notifikasi_service.tandai_semua_dibaca(warga_aktif.id)
        assert jumlah == 2
        assert notifikasi_service.get_unread_count(warga_aktif.id) == 0

    def test_tandai_semua_dibaca_tidak_ada_unread(
        self, notifikasi_service, warga_aktif
    ):
        """Tandai semua dibaca tanpa unread → return 0."""
        jumlah = notifikasi_service.tandai_semua_dibaca(warga_aktif.id)
        assert jumlah == 0


class TestNotifikasiServiceCheckAndSendReminders:
    """TC-15: Scheduler pengingat H-1."""

    def test_check_and_send_reminders_h_minus_1(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Peminjaman dipinjam & jatuh tempo besok → pengingat terkirim."""
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        terkirim = notifikasi_service.check_and_send_reminders()
        assert terkirim == 1

    def test_check_and_send_reminders_multi_kandidat(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user, app
    ):
        """Beberapa peminjaman jatuh tempo besok → semua dikirimi."""
        # Peminjaman 1: Proyektor
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        # Peminjaman 2: Kursi Lipat (warga yang sama boleh pinjam barang berbeda)
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Kursi Lipat"], admin_user, TMROW
        )

        terkirim = notifikasi_service.check_and_send_reminders()
        assert terkirim == 2

    def test_check_and_send_reminders_tidak_ada_kandidat(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Tidak ada peminjaman jatuh tempo besok → 0."""
        # Jatuh tempo lusa, bukan besok
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, DAY_AFTER
        )
        terkirim = notifikasi_service.check_and_send_reminders()
        assert terkirim == 0

    def test_check_and_send_reminders_skip_status_bukan_dipinjam(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Status 'disetujui' (belum dipinjam) → skip."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY,
            tgl_kembali=TMROW,
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        # Status sekarang 'disetujui', belum dipinjam

        terkirim = notifikasi_service.check_and_send_reminders()
        assert terkirim == 0

    def test_check_and_send_reminders_anti_spam(
        self, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Pemanggilan kedua hari yang sama → 0 (sudah dikirim)."""
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        terkirim1 = notifikasi_service.check_and_send_reminders()
        assert terkirim1 == 1

        terkirim2 = notifikasi_service.check_and_send_reminders()
        assert terkirim2 == 0


# ════════════════════════════════════════════════════════════
#  CONTROLLER HTTP TESTS
# ════════════════════════════════════════════════════════════

class TestNotifikasiControllerAccessControl:
    """Test akses endpoint notifikasi (login_required, owner-only)."""

    def test_notifikasi_tanpa_login_redirect(self, client):
        """GET /notifikasi/ tanpa login → redirect ke /login."""
        resp = client.get("/notifikasi/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_tandai_baca_tanpa_login_redirect(self, client):
        """POST /notifikasi/<id>/baca tanpa login → redirect."""
        resp = client.post("/notifikasi/some-id/baca", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_laporan_tanpa_login_redirect(self, client):
        """GET /laporan/ tanpa login → redirect (admin_required)."""
        resp = client.get("/laporan/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_laporan_warga_403(
        self, client, login_warga
    ):
        """Warga akses /laporan/ → 403."""
        resp = client.get("/laporan/")
        assert resp.status_code == 403

    def test_laporan_peminjaman_warga_403(self, client, login_warga):
        """Warga akses /laporan/peminjaman → 403."""
        resp = client.get("/laporan/peminjaman")
        assert resp.status_code == 403

    def test_laporan_inventaris_warga_403(self, client, login_warga):
        """Warga akses /laporan/inventaris → 403."""
        resp = client.get("/laporan/inventaris")
        assert resp.status_code == 403

    def test_laporan_export_warga_403(self, client, login_warga):
        """Warga akses /laporan/export → 403."""
        resp = client.get("/laporan/export")
        assert resp.status_code == 403


class TestNotifikasiControllerHappyPath:
    """Test happy path via HTTP."""

    def test_notifikasi_warga_lihat_milik_sendiri(
        self, client, login_warga, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Warga lihat daftar notifikasi miliknya → 200, ada notif."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notifikasi_service.kirim_pengingat(pjm.id)

        resp = client.get("/notifikasi/")
        assert resp.status_code == 200
        assert "Pengingat".encode() in resp.data
        assert pjm.kode_peminjaman.encode() in resp.data

    def test_notifikasi_warga_kosong(self, client, login_warga):
        """Warga tanpa notif → 200, pesan kosong."""
        resp = client.get("/notifikasi/")
        assert resp.status_code == 200
        assert "Tidak ada notifikasi".encode() in resp.data

    def test_tandai_baca_via_post(
        self, client, login_warga, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """POST /notifikasi/<id>/baca → redirect, notif jadi dibaca."""
        pjm = _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        notif = notifikasi_service.kirim_pengingat(pjm.id)
        assert notif.is_dibaca is False

        resp = client.post(
            f"/notifikasi/{notif.id}/baca",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/notifikasi" in resp.headers["Location"]

        # Verify DB
        assert notif.is_dibaca is True

    def test_tandai_baca_milik_orang_lain_403(
        self, client, login_warga, notifikasi_service, peminjaman_service,
        warga_aktif, barang_set, admin_user, app
    ):
        """Warga A mencoba tandai baca notif milik warga B → 403."""
        # Buat warga lain & peminjamannya
        with app.app_context():
            warga_lain = Warga(
                nik="3171010101010099",
                nama_lengkap="Warga Lain",
                alamat="Jl. Lain",
                telepon="081234567899",
                rt_rw="001/002",
                status="aktif",
            )
            warga_lain.set_password("pass12345")
            db.session.add(warga_lain)
            db.session.commit()
            pjm = _buat_peminjaman_dipinjam(
                peminjaman_service, warga_lain,
                barang_set["Proyektor"], admin_user, TMROW
            )
            notif = notifikasi_service.kirim_pengingat(pjm.id)
            notif_id = notif.id

        # login_warga (warga_aktif) mencoba tandai baca notif milik warga_lain
        resp = client.post(f"/notifikasi/{notif_id}/baca")
        assert resp.status_code == 403

    def test_laporan_admin_200(self, client, login_admin):
        """Admin akses /laporan/ → 200, ada statistik."""
        resp = client.get("/laporan/")
        assert resp.status_code == 200
        assert "Pusat Laporan".encode() in resp.data
        assert "Total Barang".encode() in resp.data

    def test_laporan_peminjaman_admin_200(
        self, client, login_admin, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Admin akses /laporan/peminjaman → 200, ada data."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        resp = client.get("/laporan/peminjaman")
        assert resp.status_code == 200
        assert "Laporan Peminjaman".encode() in resp.data
        assert "PJM-".encode() in resp.data

    def test_laporan_inventaris_admin_200(
        self, client, login_admin, barang_set
    ):
        """Admin akses /laporan/inventaris → 200, ada data barang."""
        resp = client.get("/laporan/inventaris")
        assert resp.status_code == 200
        assert "Laporan Inventaris".encode() in resp.data
        assert "Proyektor".encode() in resp.data

    def test_export_csv_peminjaman(
        self, client, login_admin, peminjaman_service,
        warga_aktif, barang_set
    ):
        """GET /laporan/export?type=peminjaman → download CSV."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        resp = client.get("/laporan/export?type=peminjaman&format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["Content-Type"]
        assert "attachment" in resp.headers["Content-Disposition"]
        # BOM UTF-8 + header
        assert resp.data.startswith("\ufeff".encode()) or b"kode_peminjaman" in resp.data

    def test_export_csv_inventaris(self, client, login_admin, barang_set):
        """GET /laporan/export?type=inventaris → download CSV."""
        resp = client.get("/laporan/export?type=inventaris&format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["Content-Type"]
        assert "attachment" in resp.headers["Content-Disposition"]
        assert b"Proyektor" in resp.data

    def test_export_format_tidak_didukung(self, client, login_admin):
        """Format tidak didukung → redirect ke index."""
        resp = client.get(
            "/laporan/export?format=pdf", follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/laporan/" in resp.headers["Location"]


# ════════════════════════════════════════════════════════════
#  CLI COMMAND TESTS
# ════════════════════════════════════════════════════════════

class TestSendRemindersCLI:
    """Test Flask CLI ``flask send-reminders`` (T-LAP-04)."""

    def test_send_reminders_no_candidates(
        self, runner, barang_set, warga_aktif, admin_user,
        peminjaman_service
    ):
        """Tidak ada peminjaman jatuh tempo besok → output 0."""
        # Peminjaman jatuh tempo lusa
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY,
            tgl_kembali=DAY_AFTER,
        )
        result = runner.invoke(args=["send-reminders"])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_send_reminders_with_candidates(
        self, runner, barang_set, warga_aktif, admin_user,
        peminjaman_service
    ):
        """Ada peminjaman dipinjam jatuh tempo besok → output 1."""
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        result = runner.invoke(args=["send-reminders"])
        assert result.exit_code == 0
        assert "1" in result.output

    def test_send_reminders_idempoten(
        self, runner, barang_set, warga_aktif, admin_user,
        peminjaman_service
    ):
        """Dipanggil 2x → kedua kalinya return 0 (anti-spam)."""
        _buat_peminjaman_dipinjam(
            peminjaman_service, warga_aktif,
            barang_set["Proyektor"], admin_user, TMROW
        )
        result1 = runner.invoke(args=["send-reminders"])
        assert result1.exit_code == 0
        assert "1" in result1.output

        result2 = runner.invoke(args=["send-reminders"])
        assert result2.exit_code == 0
        assert "0" in result2.output
