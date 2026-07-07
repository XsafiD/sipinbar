"""
tests/test_e2e.py — End-to-End Testing (M4 §5.2)

Menguji alur lengkap aplikasi end-to-end via HTTP test client (Flask test
client). Setiap test menembus seluruh stack: routing → decorator → controller
→ service → model → DB, persis seperti request nyata dari browser.

Task yang dicakup (mengacu TODO §5.2):
  - T-INT-03 · Happy path E2E
      register warga → admin verifikasi → login warga → cari barang →
      ajukan peminjaman → admin setujui → tandai dipinjam → kembalikan
  - T-INT-04 · Alternate path E2E
      penolakan + alasan, pengembalian terlambat + denda polymorphism,
      double-booking ditolak, warga diblokir tidak bisa ajukan
  - T-INT-05 · Role-based access test
      warga → 403 untuk route admin; admin → 403 untuk ajukan;
      belum login → redirect /login
  - T-INT-06 · Functional requirements checklist
      verifikasi FR-01 s/d FR-06 (MUST) terimplementasi via HTTP

Refs: SRS §11.2, PRD §8.1 & §5 (FR-01 s/d FR-06), TODO §5.2
"""
from datetime import date, timedelta

import pytest

from models import db
from models.admin import Admin
from models.barang import Barang, Kategori
from models.peminjaman import Peminjaman
from models.warga import Warga


# ── Konstanta test ───────────────────────────────────────────
WARGA_NIK = "3171010101010001"
WARGA_PASSWORD = "warga12345"
ADMIN_PASSWORD = "admin12345"
TODAY = date.today()
TGL_PINJAM = TODAY + timedelta(days=1)
TGL_KEMBALI = TODAY + timedelta(days=7)


# ── Fixtures ─────────────────────────────────────────────────
@pytest.fixture
def admin_user(app):
    """Admin aktif untuk test E2E."""
    admin = Admin(
        username="admin_e2e",
        nama_lengkap="Admin E2E",
        role="admin",
        is_aktif=True,
    )
    admin.set_password(ADMIN_PASSWORD)
    db.session.add(admin)
    db.session.commit()
    return admin


@pytest.fixture
def kategori_set(app):
    """3 kategori default (tarif berbeda untuk uji polymorphism denda)."""
    data = [
        Kategori(nama="Elektronik", tarif_denda_per_hari=5000),
        Kategori(nama="Furniture", tarif_denda_per_hari=2000),
        Kategori(nama="Peralatan", tarif_denda_per_hari=3000),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {k.nama: k for k in data}


@pytest.fixture
def barang_set(app, kategori_set):
    """Barang contoh dengan beragam kategori."""
    data = [
        Barang(
            nama="Proyektor",
            kategori_id=kategori_set["Elektronik"].id,
            jumlah_unit=2,
        ),
        Barang(
            nama="Kursi Lipat",
            kategori_id=kategori_set["Furniture"].id,
            jumlah_unit=10,
        ),
        Barang(
            nama="Tenda",
            kategori_id=kategori_set["Peralatan"].id,
            jumlah_unit=3,
        ),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {b.nama: b for b in data}


@pytest.fixture
def admin_client(app, admin_user):
    """Test client yang sudah login sebagai admin (session aktif)."""
    c = app.test_client()
    c.post(
        "/login",
        data={"username": "admin_e2e", "password": ADMIN_PASSWORD},
    )
    return c


@pytest.fixture
def anon_client(app):
    """Test client anonim (untuk register & login sebagai warga)."""
    return app.test_client()


# ── Helper ───────────────────────────────────────────────────
def _register_warga(client, nik=WARGA_NIK, nama="Warga E2E"):
    """Registrasi warga baru via HTTP POST /register."""
    return client.post(
        "/register",
        data={
            "nik": nik,
            "nama_lengkap": nama,
            "alamat": "Jl. E2E No. 1",
            "telepon": "081234567890",
            "rt_rw": "001/002",
        },
        follow_redirects=True,
    )


def _get_warga_id(nik=WARGA_NIK):
    """Query warga ID berdasarkan NIK dari DB."""
    w = Warga.query.filter_by(nik=nik).first()
    assert w is not None, f"Warga dengan NIK {nik} tidak ditemukan"
    return w.id


def _setup_warga_aktif(anon_client, admin_client, nik=WARGA_NIK):
    """Shortcut: register + verify + login sebagai warga. Return warga_id."""
    _register_warga(anon_client, nik=nik)
    wid = _get_warga_id(nik)
    admin_client.post(
        f"/admin/warga/{wid}/verify", data={"password": WARGA_PASSWORD}
    )
    anon_client.post(
        "/login",
        data={"username": nik, "password": WARGA_PASSWORD},
    )
    return wid


def _ajukan_peminjaman(client, items, tgl_pinjam=None, tgl_kembali=None):
    """POST /peminjaman/ajukan dengan list items [(barang_id, jumlah), ...]."""
    barang_ids = [bid for bid, _ in items]
    jumlahs = [str(j) for _, j in items]
    return client.post(
        "/peminjaman/ajukan",
        data={
            "tanggal_pinjam": (tgl_pinjam or TGL_PINJAM).isoformat(),
            "tanggal_kembali": (tgl_kembali or TGL_KEMBALI).isoformat(),
            "catatan": "E2E test",
            "barang_id": barang_ids,
            "jumlah": jumlahs,
        },
    )


def _set_terlambat(pid, hari_terlambat=3):
    """Mutate tanggal_pinjam & tanggal_kembali_rencana ke masa lalu untuk
    mensimulasikan peminjaman yang sudah lewat jatuh tempo.

    Menjaga invariant DB ``tanggal_kembali_rencana > tanggal_pinjam``
    (constraint ``ck_peminjaman_tanggal_valid``) dengan men-set pinjam
    7 hari lebih awal dari rencana.
    """
    p = db.session.get(Peminjaman, pid)
    p.tanggal_pinjam = TODAY - timedelta(days=hari_terlambat + 7)
    p.tanggal_kembali_rencana = TODAY - timedelta(days=hari_terlambat)
    db.session.commit()


# ════════════════════════════════════════════════════════════
#  T-INT-03 · HAPPY PATH E2E
# ════════════════════════════════════════════════════════════
class TestHappyPathE2E:
    """Skenario: register → verifikasi → login → cari → ajukan →
    setujui → pinjam → kembalikan. AC: alur lengkap tanpa error."""

    def test_register_warga_berakhir_status_menunggu(self, anon_client):
        """Register self-service → status 'menunggu', belum bisa login."""
        resp = _register_warga(anon_client)
        assert resp.status_code == 200  # follow_redirects → /login (200)
        warga = Warga.query.filter_by(nik=WARGA_NIK).first()
        assert warga is not None
        assert warga.status == "menunggu"
        assert warga.password_hash is None  # password di-set saat verifikasi

    def test_warga_menunggu_tidak_bisa_login(self, anon_client):
        """Warga 'menunggu' belum bisa login (FR-01.7 verifikasi wajib)."""
        _register_warga(anon_client)
        resp = anon_client.post(
            "/login",
            data={"username": WARGA_NIK, "password": WARGA_PASSWORD},
        )
        # Login gagal → 401 (render login + flash error)
        assert resp.status_code == 401

    def test_alur_lengkap_register_sampai_kembalikan(
        self, anon_client, admin_client, barang_set
    ):
        """ALUR LENGKAP happy path: 8 step, denda = 0, status = dikembalikan."""
        # 1. Register warga (self-service)
        _register_warga(anon_client)
        wid = _get_warga_id()
        assert db.session.get(Warga, wid).status == "menunggu"

        # 2. Admin verifikasi → status 'aktif' + password ter-set
        admin_client.post(
            f"/admin/warga/{wid}/verify", data={"password": WARGA_PASSWORD}
        )
        warga = db.session.get(Warga, wid)
        assert warga.status == "aktif"
        assert warga.check_password(WARGA_PASSWORD)

        # 3. Warga login
        resp = anon_client.post(
            "/login",
            data={"username": WARGA_NIK, "password": WARGA_PASSWORD},
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

        # 4. Cari barang (FR-04.1 search by nama)
        resp = anon_client.get("/barang/", query_string={"q": "Proyektor"})
        assert resp.status_code == 200
        assert b"Proyektor" in resp.data

        # 5. Ajukan peminjaman (1 barang, 1 unit)
        proyektor = barang_set["Proyektor"]
        resp = _ajukan_peminjaman(
            anon_client, [(proyektor.id, 1)]
        )
        assert resp.status_code == 302  # redirect ke detail

        peminjaman = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
        )
        assert peminjaman is not None
        assert peminjaman.status == "diajukan"
        assert len(peminjaman.detail_list) == 1
        pid = peminjaman.id

        # 6. Admin setujui
        resp = admin_client.post(f"/peminjaman/{pid}/setujui")
        assert resp.status_code == 302
        assert db.session.get(Peminjaman, pid).status == "disetujui"

        # 7. Admin tandai dipinjam (barang diserahkan)
        resp = admin_client.post(f"/peminjaman/{pid}/pinjam")
        assert resp.status_code == 302
        assert db.session.get(Peminjaman, pid).status == "dipinjam"

        # 8. Admin proses pengembalian (kondisi baik → denda 0)
        resp = admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={f"kondisi_{proyektor.id}": "baik"},
        )
        assert resp.status_code == 302
        final = db.session.get(Peminjaman, pid)
        assert final.status == "dikembalikan"
        assert final.total_denda_rupiah == 0
        assert final.tanggal_kembali_aktual == TODAY

    def test_happy_path_multi_item_dua_barang(
        self, anon_client, admin_client, barang_set
    ):
        """FR-03.9 (COULD): warga pinjam >1 barang dalam satu pengajuan."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]
        kursi = barang_set["Kursi Lipat"]

        resp = _ajukan_peminjaman(
            anon_client, [(proyektor.id, 1), (kursi.id, 2)]
        )
        assert resp.status_code == 302
        peminjaman = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
        )
        assert len(peminjaman.detail_list) == 2
        # Selesaikan sampai dikembalikan (tepat waktu)
        pid = peminjaman.id
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")
        admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={
                f"kondisi_{proyektor.id}": "baik",
                f"kondisi_{kursi.id}": "baik",
            },
        )
        assert db.session.get(Peminjaman, pid).status == "dikembalikan"


# ════════════════════════════════════════════════════════════
#  T-INT-04 · ALTERNATE PATH E2E
# ════════════════════════════════════════════════════════════
class TestAlternatePathE2E:
    """Alternate path: penolakan, terlambat+denda, double-booking,
    warga diblokir. AC: semua alternate path behave sesuai spec."""

    def test_penolakan_peminjaman_dengan_alasan(
        self, anon_client, admin_client, barang_set
    ):
        """Admin tolak peminjaman + alasan → status 'ditolak', alasan tersimpan."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]
        _ajukan_peminjaman(anon_client, [(proyektor.id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )

        alasan = "Barang sedang dipakai acara desa tanggal tersebut"
        resp = admin_client.post(
            f"/peminjaman/{pid}/tolak", data={"alasan": alasan}
        )
        assert resp.status_code == 302
        p = db.session.get(Peminjaman, pid)
        assert p.status == "ditolak"
        assert p.alasan_penolakan == alasan
        assert p.is_final is True

    def test_pengembalian_terlambat_denda_otomatis(
        self, anon_client, admin_client, barang_set
    ):
        """Pengembalian setelah jatuh tempo → denda > 0 (FR-03.7)."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]  # Elektronik, 5000/hari
        _ajukan_peminjaman(anon_client, [(proyektor.id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")

        # Simulasi waktu: jatuh tempo sudah lewat 3 hari
        _set_terlambat(pid, hari_terlambat=3)

        resp = admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={f"kondisi_{proyektor.id}": "baik"},
        )
        assert resp.status_code == 302
        p = db.session.get(Peminjaman, pid)
        assert p.status == "dikembalikan"
        # 3 hari terlambat × tarif Elektronik 5000 × 1 unit = 15000
        assert p.total_denda_rupiah == 15000

    def test_denda_polymorphism_multi_kategori_terlambat(
        self, anon_client, admin_client, barang_set
    ):
        """FR-02.6: denda dihitung per kategori (polymorphism) —
        Proyektor (5000) + Kursi (2000), 3 hari terlambat = 21000."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]
        kursi = barang_set["Kursi Lipat"]
        _ajukan_peminjaman(
            anon_client, [(proyektor.id, 1), (kursi.id, 1)]
        )
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")

        _set_terlambat(pid, hari_terlambat=3)

        admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={
                f"kondisi_{proyektor.id}": "baik",
                f"kondisi_{kursi.id}": "baik",
            },
        )
        p = db.session.get(Peminjaman, pid)
        # (5000×1 + 2000×1) × 3 hari = 21000
        assert p.total_denda_rupiah == 21000

    def test_double_booking_ditolak(
        self, anon_client, admin_client, barang_set
    ):
        """FR-03.3: pengajuan kedua yang bentrok jadwal → ditolak."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]  # 2 unit total

        # Peminjaman A: semua unit (2), D+1 s/d D+7
        resp = _ajukan_peminjaman(anon_client, [(proyektor.id, 2)])
        assert resp.status_code == 302
        assert Peminjaman.query.count() == 1

        # Peminjaman B: 1 unit, overlap (D+3 s/d D+5) → ditolak
        resp = _ajukan_peminjaman(
            anon_client,
            [(proyektor.id, 1)],
            tgl_pinjam=TODAY + timedelta(days=3),
            tgl_kembali=TODAY + timedelta(days=5),
        )
        # Controller re-render form (200) + flash error, peminjaman tidak dibuat
        assert resp.status_code == 200
        assert Peminjaman.query.count() == 1  # tidak bertambah

    def test_non_overlap_tetap_boleh(
        self, anon_client, admin_client, barang_set
    ):
        """Pengajuan dengan rentang non-overlap tetap diizinkan."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]

        # Peminjaman A: D+1 s/d D+3
        _ajukan_peminjaman(
            anon_client,
            [(proyektor.id, 1)],
            tgl_pinjam=TODAY + timedelta(days=1),
            tgl_kembali=TODAY + timedelta(days=3),
        )
        # Peminjaman B: D+5 s/d D+7 (non-overlap) → boleh
        resp = _ajukan_peminjaman(
            anon_client,
            [(proyektor.id, 1)],
            tgl_pinjam=TODAY + timedelta(days=5),
            tgl_kembali=TODAY + timedelta(days=7),
        )
        assert resp.status_code == 302
        assert Peminjaman.query.count() == 2

    def test_warga_diblokir_tidak_bisa_ajukan(
        self, anon_client, admin_client, barang_set
    ):
        """Warga yang diblokir (session masih ada) tidak bisa ajukan."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]

        # Admin blokir warga (warga sedang login)
        admin_client.post(f"/admin/warga/{wid}/blokir")
        assert db.session.get(Warga, wid).status == "diblokir"

        # Warga coba ajukan → service tolak (ValueError → flash error)
        resp = _ajukan_peminjaman(anon_client, [(proyektor.id, 1)])
        assert resp.status_code == 200  # re-render form dengan error
        assert Peminjaman.query.count() == 0  # tidak ada peminjaman dibuat

    def test_warga_diblokir_tidak_bisa_login(self, anon_client, admin_client):
        """Warga diblokir tidak bisa login (FR-05.4 efek)."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        admin_client.post(f"/admin/warga/{wid}/blokir")
        # Logout dulu, lalu coba login
        anon_client.get("/logout")
        resp = anon_client.post(
            "/login",
            data={"username": WARGA_NIK, "password": WARGA_PASSWORD},
        )
        assert resp.status_code == 401  # login ditolak


# ════════════════════════════════════════════════════════════
#  T-INT-05 · ROLE-BASED ACCESS TEST
# ════════════════════════════════════════════════════════════
class TestRoleBasedAccessE2E:
    """Verifikasi tidak ada kebocoran akses antar role.
    AC: tidak ada kebocoran akses."""

    def test_warga_tidak_bisa_akses_admin_warga(self, anon_client, admin_client):
        """Warga → /admin/warga/* → 403."""
        _setup_warga_aktif(anon_client, admin_client)
        # Daftar warga
        assert anon_client.get("/admin/warga/").status_code == 403
        # Detail warga (milik sendiri pun tidak boleh, route admin-only)
        wid = _get_warga_id()
        assert anon_client.get(f"/admin/warga/{wid}").status_code == 403

    def test_warga_tidak_bisa_akses_laporan(self, anon_client, admin_client):
        """Warga → /laporan/* → 403 (admin-only)."""
        _setup_warga_aktif(anon_client, admin_client)
        for url in [
            "/laporan/",
            "/laporan/peminjaman",
            "/laporan/inventaris",
            "/laporan/export",
        ]:
            resp = anon_client.get(url)
            assert resp.status_code == 403, f"{url} harus 403, dapat {resp.status_code}"

    def test_warga_tidak_bisa_setujui_peminjaman(
        self, anon_client, admin_client, barang_set
    ):
        """Warga → POST /peminjaman/<id>/setujui → 403."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        _ajukan_peminjaman(anon_client, [(barang_set["Proyektor"].id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        resp = anon_client.post(f"/peminjaman/{pid}/setujui")
        assert resp.status_code == 403
        # Pastikan state tidak berubah
        assert db.session.get(Peminjaman, pid).status == "diajukan"

    def test_admin_tidak_bisa_ajukan_peminjaman(self, admin_client):
        """Admin → /peminjaman/ajukan → 403 (warga-only)."""
        assert admin_client.get("/peminjaman/ajukan").status_code == 403
        resp = admin_client.post(
            "/peminjaman/ajukan",
            data={
                "tanggal_pinjam": TGL_PINJAM.isoformat(),
                "tanggal_kembali": TGL_KEMBALI.isoformat(),
                "barang_id": ["fake-id"],
                "jumlah": ["1"],
            },
        )
        assert resp.status_code == 403

    def test_belum_login_redirect_ke_login(self, anon_client):
        """Anon → protected routes → 302 redirect /login (FR-01.5)."""
        protected = [
            "/dashboard",
            "/barang/",
            "/peminjaman/",
            "/laporan/",
            "/admin/warga/",
            "/notifikasi/",
        ]
        for url in protected:
            resp = anon_client.get(url)
            assert resp.status_code == 302, f"{url} harus 302, dapat {resp.status_code}"
            assert "/login" in resp.headers["Location"], (
                f"{url} harus redirect ke /login"
            )

    def test_warga_lihat_peminjaman_orang_lain_403(
        self, anon_client, admin_client, barang_set
    ):
        """Warga A tidak bisa lihat peminjaman milik warga B."""
        # Warga A
        wid_a = _setup_warga_aktif(anon_client, admin_client, nik="3171010101010011")
        # Warga B buat peminjaman (via client terpisah)
        client_b = anon_client.application.test_client() if hasattr(anon_client, "application") else None
        # Gunakan app fixture dari anon_client
        _register_warga(client_b, nik="3171010101010022", nama="Warga B")
        wid_b = _get_warga_id("3171010101010022")
        admin_client.post(f"/admin/warga/{wid_b}/verify", data={"password": WARGA_PASSWORD})
        client_b.post("/login", data={"username": "3171010101010022", "password": WARGA_PASSWORD})
        _ajukan_peminjaman(client_b, [(barang_set["Proyektor"].id, 1)])
        pid_b = (
            Peminjaman.query.filter_by(warga_id=wid_b).first().id
        )

        # Warga A coba lihat peminjaman milik B → 403
        resp = anon_client.get(f"/peminjaman/{pid_b}")
        assert resp.status_code == 403

    def test_logout_menghancurkan_session(self, anon_client, admin_client):
        """FR-01.3: logout → session hilang, route protected redirect."""
        _setup_warga_aktif(anon_client, admin_client)
        assert anon_client.get("/dashboard").status_code == 200
        resp = anon_client.get("/logout")
        assert resp.status_code == 302
        # Setelah logout, akses protected → redirect login
        assert anon_client.get("/dashboard").status_code == 302


# ════════════════════════════════════════════════════════════
#  T-INT-06 · FUNCTIONAL REQUIREMENTS CHECKLIST
# ════════════════════════════════════════════════════════════
class TestFunctionalRequirementsChecklist:
    """Verifikasi FR-01 s/d FR-06 (MUST) terimplementasi via HTTP.
    AC: 100% FR MUST terimplementasi.

    Setiap test memetakan ke satu atau lebih FR ID dari PRD §5.
    """

    # ── FR-01: Autentikasi (MUST) ───────────────────────────
    def test_FR_01_autentikasi_lengkap(self, anon_client, admin_client):
        """FR-01.1 s/d FR-01.7: login, session, logout, hash,
        redirect, register, verify/reject."""
        # FR-01.6: register warga
        _register_warga(anon_client)
        wid = _get_warga_id()
        assert db.session.get(Warga, wid).status == "menunggu"

        # FR-01.7: admin verifikasi
        admin_client.post(
            f"/admin/warga/{wid}/verify", data={"password": WARGA_PASSWORD}
        )
        warga = db.session.get(Warga, wid)
        assert warga.status == "aktif"

        # FR-01.4: password disimpan sebagai hash (bukan plain-text)
        assert warga.password_hash is not None
        assert warga.password_hash != WARGA_PASSWORD
        assert warga.check_password(WARGA_PASSWORD) is True

        # FR-01.1 & FR-01.2: login berhasil + session dibuat
        resp = anon_client.post(
            "/login",
            data={"username": WARGA_NIK, "password": WARGA_PASSWORD},
        )
        assert resp.status_code == 302
        # Verifikasi session via akses /dashboard (butuh login)
        assert anon_client.get("/dashboard").status_code == 200

        # FR-01.3: logout → session dihancurkan
        anon_client.get("/logout")
        assert anon_client.get("/dashboard").status_code == 302

        # FR-01.5: halaman protected redirect ke login jika belum login
        resp = anon_client.get("/peminjaman/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_FR_01_admin_reject_warga(self, anon_client, admin_client):
        """FR-01.7: admin bisa menolak registrasi warga + alasan."""
        _register_warga(anon_client)
        wid = _get_warga_id()
        resp = admin_client.post(
            f"/admin/warga/{wid}/reject",
            data={"alasan": "Data NIK tidak valid"},
        )
        assert resp.status_code == 302
        warga = db.session.get(Warga, wid)
        assert warga.status == "ditolak"
        assert warga.alasan_penolakan == "Data NIK tidak valid"

    # ── FR-02: Inventaris Barang (MUST) ─────────────────────
    def test_FR_02_inventaris_crud_lengkap(
        self, admin_client, kategori_set
    ):
        """FR-02.1 s/d FR-02.5: tambah, edit, hapus (soft),
        ubah kondisi, kategori."""
        kid = kategori_set["Elektronik"].id

        # FR-02.5: sistem mengkategorikan barang (kategori ada)
        assert Kategori.query.count() >= 3

        # FR-02.1: admin tambah barang baru
        resp = admin_client.post(
            "/barang/tambah",
            data={
                "nama": "Speaker Aktif",
                "kategori_id": kid,
                "jumlah": 5,
                "kondisi": "baik",
                "status": "tersedia",
                "deskripsi": "Untuk acara desa",
            },
        )
        assert resp.status_code == 302
        barang = Barang.query.filter_by(nama="Speaker Aktif").first()
        assert barang is not None
        assert barang.jumlah_unit == 5
        assert barang.kondisi == "baik"
        assert barang.status == "tersedia"
        bid = barang.id

        # FR-02.2 & FR-02.4: edit barang (ubah jumlah + kondisi)
        resp = admin_client.post(
            f"/barang/{bid}/edit",
            data={
                "nama": "Speaker Aktif",
                "kategori_id": kid,
                "jumlah": 3,
                "kondisi": "perlu_perbaikan",
                "status": "tersedia",
                "deskripsi": "Updated",
            },
        )
        assert resp.status_code == 302
        updated = db.session.get(Barang, bid)
        assert updated.jumlah_unit == 3
        assert updated.kondisi == "perlu_perbaikan"

        # FR-02.3: hapus barang (soft delete — bukan hard delete)
        resp = admin_client.post(f"/barang/{bid}/hapus")
        assert resp.status_code == 302
        deleted = db.session.get(Barang, bid)
        # Soft delete: data masih ada di DB tapi ditandai deleted_at
        assert deleted is not None  # tidak benar-benar terhapus
        assert deleted.deleted_at is not None
        assert deleted.is_deleted is True

    def test_FR_02_6_denda_polymorphism_per_kategori(
        self, anon_client, admin_client, barang_set, kategori_set
    ):
        """FR-02.6 (SHOULD): denda berbeda per kategori (polymorphism).
        Diverifikasi via E2E pengembalian terlambat."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]  # Elektronik 5000
        tenda = barang_set["Tenda"]  # Peralatan 3000
        _ajukan_peminjaman(
            anon_client, [(proyektor.id, 1), (tenda.id, 1)]
        )
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")

        # Jatuh tempo 2 hari lalu
        _set_terlambat(pid, hari_terlambat=2)

        admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={
                f"kondisi_{proyektor.id}": "baik",
                f"kondisi_{tenda.id}": "baik",
            },
        )
        p = db.session.get(Peminjaman, pid)
        # (5000×1 + 3000×1) × 2 hari = 16000 (bukan rata-rata)
        assert p.total_denda_rupiah == 16000

    # ── FR-03: Sistem Peminjaman (MUST) ─────────────────────
    def test_FR_03_state_machine_transisi_lengkap(
        self, anon_client, admin_client, barang_set
    ):
        """FR-03.8: status berubah sesuai state machine
        diajukan → disetujui → dipinjam → dikembalikan."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        _ajukan_peminjaman(anon_client, [(barang_set["Kursi Lipat"].id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )

        p = db.session.get(Peminjaman, pid)
        assert p.status == "diajukan"

        admin_client.post(f"/peminjaman/{pid}/setujui")
        assert db.session.get(Peminjaman, pid).status == "disetujui"

        admin_client.post(f"/peminjaman/{pid}/pinjam")
        assert db.session.get(Peminjaman, pid).status == "dipinjam"

        admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={f"kondisi_{barang_set['Kursi Lipat'].id}": "baik"},
        )
        assert db.session.get(Peminjaman, pid).status == "dikembalikan"

    def test_FR_03_6_catat_kondisi_kembali(
        self, anon_client, admin_client, barang_set
    ):
        """FR-03.6: admin catat pengembalian beserta kondisi barang."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]
        _ajukan_peminjaman(anon_client, [(proyektor.id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")

        # Catat kondisi kembali: rusak_ringan
        admin_client.post(
            f"/peminjaman/{pid}/kembalikan",
            data={f"kondisi_{proyektor.id}": "rusak_ringan"},
        )
        p = db.session.get(Peminjaman, pid)
        assert p.status == "dikembalikan"
        detail = p.detail_list[0]
        assert detail.kondisi_kembali == "rusak_ringan"

    # ── FR-04: Pencarian & Pelacakan (MUST) ─────────────────
    def test_FR_04_pencarian_dan_filter_barang(
        self, anon_client, admin_client, barang_set, kategori_set
    ):
        """FR-04.1 s/d FR-04.3 & FR-04.5: search, filter kategori,
        status ketersediaan, daftar peminjaman aktif."""
        _setup_warga_aktif(anon_client, admin_client)

        # FR-04.1: cari barang by nama
        resp = anon_client.get("/barang/", query_string={"q": "Proyektor"})
        assert resp.status_code == 200
        assert b"Proyektor" in resp.data
        # Barang lain tidak ikut
        resp2 = anon_client.get("/barang/", query_string={"q": "Tenda"})
        assert b"Tenda" in resp2.data

        # FR-04.2: filter by kategori
        kid_elektronik = kategori_set["Elektronik"].id
        resp = anon_client.get(
            "/barang/", query_string={"kategori": kid_elektronik}
        )
        assert resp.status_code == 200
        assert b"Proyektor" in resp.data  # Elektronik
        assert b"Kursi Lipat" not in resp.data  # Furniture

        # FR-04.3: status ketersediaan ditampilkan di katalog
        resp = anon_client.get("/barang/")
        assert resp.status_code == 200
        # Status 'tersedia' muncul di halaman katalog
        assert b"ersedia" in resp.data  # "Tersedia" (case-insensitive)

        # FR-04.5: admin lihat daftar semua peminjaman
        resp = admin_client.get("/peminjaman/")
        assert resp.status_code == 200

    # ── FR-05: Manajemen Warga (MUST) ───────────────────────
    def test_FR_05_manajemen_warga_lengkap(
        self, anon_client, admin_client, barang_set
    ):
        """FR-05.1 s/d FR-05.3: daftar warga, detail, riwayat peminjaman."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        # Buat 1 peminjaman agar riwayat tidak kosong
        _ajukan_peminjaman(anon_client, [(barang_set["Proyektor"].id, 1)])

        # FR-05.1: admin lihat daftar semua warga
        resp = admin_client.get("/admin/warga/")
        assert resp.status_code == 200
        assert b"Warga E2E" in resp.data

        # FR-05.2: admin lihat detail profil warga
        resp = admin_client.get(f"/admin/warga/{wid}")
        assert resp.status_code == 200
        assert WARGA_NIK.encode() in resp.data

        # FR-05.3: admin lihat riwayat peminjaman per warga
        # (riwayat ditampilkan di halaman detail warga)
        peminjaman_kode = (
            Peminjaman.query.filter_by(warga_id=wid).first().kode_peminjaman
        )
        assert peminjaman_kode.encode() in resp.data

    # ── FR-06: Laporan & Notifikasi ─────────────────────────
    def test_FR_06_laporan_dan_export(
        self, anon_client, admin_client, barang_set
    ):
        """FR-06.1 (SHOULD) & FR-06.5 (COULD): laporan peminjaman +
        export CSV dengan data."""
        # Setup: buat 1 peminjaman agar laporan non-empty
        wid = _setup_warga_aktif(anon_client, admin_client)
        _ajukan_peminjaman(anon_client, [(barang_set["Proyektor"].id, 1)])
        kode = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .kode_peminjaman
        )

        # FR-06.1: admin lihat laporan peminjaman per periode
        resp = admin_client.get("/laporan/peminjaman")
        assert resp.status_code == 200
        assert kode.encode() in resp.data

        # FR-06.5: admin ekspor laporan ke CSV
        resp = admin_client.get("/laporan/export?type=peminjaman")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        # CSV diawali BOM UTF-8
        assert resp.data.startswith(b"\xef\xbb\xbf")
        # Ada header row + data (kode peminjaman muncul di CSV)
        assert len(resp.data) > len(b"\xef\xbb\xbf")
        assert kode.encode() in resp.data

    def test_FR_06_laporan_inventaris(self, admin_client):
        """FR-06.2 (SHOULD): laporan inventaris barang tersedia."""
        resp = admin_client.get("/laporan/inventaris")
        assert resp.status_code == 200

    def test_FR_06_notifikasi_in_app(
        self, anon_client, admin_client, barang_set
    ):
        """FR-06.4 (COULD): notifikasi in-app untuk pengingat & perubahan status."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        _ajukan_peminjaman(anon_client, [(barang_set["Proyektor"].id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        # Admin setujui → memicu notifikasi status 'disetujui' (info)
        admin_client.post(f"/peminjaman/{pid}/setujui")

        # Warga lihat notifikasinya
        resp = anon_client.get("/notifikasi/")
        assert resp.status_code == 200
        # Kode peminjaman muncul di panel notifikasi
        kode = db.session.get(Peminjaman, pid).kode_peminjaman
        assert kode.encode() in resp.data

    def test_FR_06_3_daftar_peminjaman_terlambat(
        self, anon_client, admin_client, barang_set
    ):
        """FR-06.3 (SHOULD): sistem menampilkan peminjaman terlambat."""
        wid = _setup_warga_aktif(anon_client, admin_client)
        proyektor = barang_set["Proyektor"]
        _ajukan_peminjaman(anon_client, [(proyektor.id, 1)])
        pid = (
            Peminjaman.query.filter_by(warga_id=wid)
            .order_by(Peminjaman.created_at.desc())
            .first()
            .id
        )
        admin_client.post(f"/peminjaman/{pid}/setujui")
        admin_client.post(f"/peminjaman/{pid}/pinjam")
        # Set jatuh tempo ke masa lalu
        _set_terlambat(pid, hari_terlambat=5)
        peminjaman = db.session.get(Peminjaman, pid)

        # Laporan peminjaman menampilkan data (termasuk yang terlambat)
        resp = admin_client.get("/laporan/peminjaman")
        assert resp.status_code == 200
        # Kode peminjaman muncul di laporan
        assert peminjaman.kode_peminjaman.encode() in resp.data
