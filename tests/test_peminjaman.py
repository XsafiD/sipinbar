"""
tests/test_peminjaman.py — Test modul Peminjaman (T-PJM-04).

Menguji:
  - PeminjamanService.ajukan (valid, warga non-aktif, tanggal invalid,
    barang tidak ada, jumlah > stok, double-booking, duplikat barang)
  - State transitions: setujui, tolak, mulai_pinjam, proses_pengembalian
  - Pengembalian tepat waktu (denda 0) & terlambat (denda > 0, polymorphism)
  - Transisi state ilegal ditolak
  - Generate kode_peminjaman format PJM-YYYY-NNNN (unik & monoton)
  - validate_availability (anti double-booking)
  - get_by_warga, get_terlambat
  - Controller HTTP: access control (login_required, admin_required),
    happy path ajukan/setujui/kembalikan via test client

Refs: TODO T-PJM-04, SRS §11.2 TC-05 s/d TC-10, TC-13
"""
from datetime import date, timedelta

import pytest

from models import db
from models.admin import Admin
from models.barang import Barang, Kategori
from models.peminjaman import Peminjaman
from models.warga import Warga
from services.peminjaman_service import PeminjamanService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def peminjaman_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return PeminjamanService()


@pytest.fixture
def kategori_set(app):
    """3 kategori default (sama dengan seed & test_barang)."""
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
        Barang(nama="Proyektor", kategori_id=kategori_set["Elektronik"].id, jumlah_unit=2),
        Barang(nama="Kursi Lipat", kategori_id=kategori_set["Furniture"].id, jumlah_unit=10),
        Barang(nama="Tenda", kategori_id=kategori_set["Peralatan"].id, jumlah_unit=3),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {b.nama: b for b in data}


@pytest.fixture
def admin_user(app):
    """Admin aktif untuk test endpoint admin."""
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
    """Warga berstatus aktif (bisa ajukan peminjaman)."""
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
def warga_diblokir(app):
    """Warga berstatus diblokir (tidak bisa ajukan)."""
    w = Warga(
        nik="3171010101010002",
        nama_lengkap="Warga Diblokir",
        alamat="Jl. Test",
        telepon="081234567891",
        rt_rw="001/002",
        status="diblokir",
    )
    w.set_password("warga12345")
    db.session.add(w)
    db.session.commit()
    return w


@pytest.fixture
def login_admin(client, admin_user):
    """Login sebagai admin via test client."""
    client.post(
        "/login",
        data={"username": "admin_test", "password": "admin12345"},
    )


@pytest.fixture
def login_warga(client, warga_aktif):
    """Login sebagai warga via test client."""
    client.post(
        "/login",
        data={"username": warga_aktif.nik, "password": "warga12345"},
    )


# ── Helper untuk tanggal ─────────────────────────────────────
TODAY = date.today()
TMROW = TODAY + timedelta(days=1)
DAY_AFTER = TODAY + timedelta(days=2)
WEEK_LATER = TODAY + timedelta(days=7)


# ════════════════════════════════════════════════════════════
#  SERVICE LAYER TESTS
# ════════════════════════════════════════════════════════════

class TestPeminjamanServiceAjukan:
    """TC-05: Pengajuan peminjaman valid & invalid."""

    def test_ajukan_valid(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Ajukan peminjaman valid → status diajukan, kode & detail terbuat."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
            catatan="Untuk acara warga",
        )
        assert pjm.id is not None
        assert pjm.status == "diajukan"
        assert pjm.warga_id == warga_aktif.id
        assert pjm.kode_peminjaman.startswith(f"PJM-{TODAY.year}-")
        assert len(pjm.detail_list) == 1
        assert pjm.detail_list[0].barang_id == barang_set["Proyektor"].id
        assert pjm.detail_list[0].jumlah == 1
        assert pjm.catatan == "Untuk acara warga"

    def test_ajukan_multi_item(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Ajukan beberapa barang sekaligus."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[
                {"barang_id": barang_set["Proyektor"].id, "jumlah": 1},
                {"barang_id": barang_set["Tenda"].id, "jumlah": 2},
            ],
            tgl_pinjam=TMROW,
            tgl_kembali=WEEK_LATER,
        )
        assert len(pjm.detail_list) == 2

    def test_ajukan_warga_non_aktif_ditolak(
        self, peminjaman_service, warga_diblokir, barang_set
    ):
        """Warga diblokir tidak bisa ajukan (BR-01)."""
        with pytest.raises(ValueError, match="tidak dapat mengajukan"):
            peminjaman_service.ajukan(
                warga_id=warga_diblokir.id,
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_warga_tidak_ada(
        self, peminjaman_service, barang_set
    ):
        """Warga_id tidak terdaftar → ValueError."""
        with pytest.raises(ValueError, match="Warga tidak ditemukan"):
            peminjaman_service.ajukan(
                warga_id="nonexistent-id",
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_tanggal_invalid(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """tgl_kembali <= tgl_pinjam → ValueError."""
        with pytest.raises(ValueError, match="Tanggal kembali harus setelah"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=TMROW,  # sama dengan tgl_pinjam
            )

    def test_ajukan_items_kosong(
        self, peminjaman_service, warga_aktif
    ):
        """Items kosong → ValueError."""
        with pytest.raises(ValueError, match="Minimal satu barang"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_barang_tidak_ada(
        self, peminjaman_service, warga_aktif
    ):
        """barang_id invalid → ValueError."""
        with pytest.raises(ValueError, match="Barang tidak ditemukan"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[{"barang_id": "nonexistent-bid", "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_jumlah_melebihi_stok(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """jumlah > barang.jumlah_unit → ValueError."""
        with pytest.raises(ValueError, match="melebihi stok"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 99}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_duplikat_barang(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Barang yang sama didaftarkan 2x dalam satu pengajuan → ValueError."""
        with pytest.raises(ValueError, match="lebih dari sekali"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[
                    {"barang_id": barang_set["Proyektor"].id, "jumlah": 1},
                    {"barang_id": barang_set["Proyektor"].id, "jumlah": 1},
                ],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )

    def test_ajukan_double_booking_ditolak(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Overlap dengan peminjaman aktif & stok habis → ValueError (BR-03)."""
        # Peminjaman pertama: Proyektor (stok 2) dipinjam 2 unit
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 2}],
            tgl_pinjam=TMROW,
            tgl_kembali=WEEK_LATER,
        )
        # Peminjaman kedua overlap → ditolak (stok habis)
        with pytest.raises(ValueError, match="bentrok"):
            peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
                tgl_pinjam=DAY_AFTER,
                tgl_kembali=WEEK_LATER,
            )

    def test_ajukan_tidak_overlap_boleh(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Peminjaman non-overlap diizinkan walaupun barang sama."""
        # Peminjaman pertama: TMROW → DAY_AFTER
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 2}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        # Peminjaman kedua: setelah peminjaman pertama selesai → boleh
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 2}],
            tgl_pinjam=DAY_AFTER + timedelta(days=1),
            tgl_kembali=DAY_AFTER + timedelta(days=3),
        )
        assert pjm2.status == "diajukan"


class TestPeminjamanServiceKodePeminjaman:
    """T-PJM-02: Generate kode_peminjaman format PJM-YYYY-NNNN."""

    def test_kode_format_benar(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Kode mengikuti format PJM-YYYY-NNNN."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        import re
        assert re.match(rf"^PJM-{TODAY.year}-\d{{4}}$", pjm.kode_peminjaman)

    def test_kode_monoton_naik(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Kode urut naik untuk peminjaman berturut-turut."""
        pjm1 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Tenda"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        seq1 = int(pjm1.kode_peminjaman.rsplit("-", 1)[-1])
        seq2 = int(pjm2.kode_peminjaman.rsplit("-", 1)[-1])
        assert seq2 == seq1 + 1

    def test_kode_unik(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Setiap peminjaman punya kode unik."""
        kodes = set()
        for i in range(3):
            pjm = peminjaman_service.ajukan(
                warga_id=warga_aktif.id,
                items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )
            assert pjm.kode_peminjaman not in kodes
            kodes.add(pjm.kode_peminjaman)


class TestPeminjamanServiceStateTransitions:
    """TC-06, TC-07: State machine peminjaman."""

    @pytest.fixture
    def peminjaman_diajukan(self, peminjaman_service, warga_aktif, barang_set):
        """Peminjaman berstatus 'diajukan'."""
        return peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )

    def test_setujui(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """diajukan → disetujui, approved_by terisi."""
        pjm = peminjaman_service.setujui(peminjaman_diajukan.id, admin_user.id)
        assert pjm.status == "disetujui"
        assert pjm.approved_by_admin_id == admin_user.id
        assert pjm.approved_at is not None

    def test_tolak_dengan_alasan(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """diajukan → ditolak, alasan terisi."""
        pjm = peminjaman_service.tolak(
            peminjaman_diajukan.id, admin_user.id, "Barang sedang rusak"
        )
        assert pjm.status == "ditolak"
        assert pjm.alasan_penolakan == "Barang sedang rusak"
        assert pjm.is_final is True

    def test_tolak_tanpa_alasan(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """Tolak tanpa alasan → ValueError."""
        with pytest.raises(ValueError, match="Alasan penolakan wajib"):
            peminjaman_service.tolak(
                peminjaman_diajukan.id, admin_user.id, ""
            )

    def test_mulai_pinjam(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """disetujui → dipinjam."""
        peminjaman_service.setujui(peminjaman_diajukan.id, admin_user.id)
        pjm = peminjaman_service.mulai_pinjam(peminjaman_diajukan.id)
        assert pjm.status == "dipinjam"

    def test_transisi_ilegal_disetujui_dua_kali(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """Setujui peminjaman yang sudah disetujui → ValueError."""
        peminjaman_service.setujui(peminjaman_diajukan.id, admin_user.id)
        with pytest.raises(ValueError, match="tidak dapat disetujui"):
            peminjaman_service.setujui(peminjaman_diajukan.id, admin_user.id)

    def test_transisi_ilegal_mulai_pinjam_dari_diajukan(
        self, peminjaman_service, peminjaman_diajukan
    ):
        """Mulai pinjam dari status 'diajukan' (belum disetujui) → ValueError."""
        with pytest.raises(ValueError, match="tidak dapat diproses"):
            peminjaman_service.mulai_pinjam(peminjaman_diajukan.id)

    def test_tolak_peminjaman_sudah_dipinjam(
        self, peminjaman_service, peminjaman_diajukan, admin_user
    ):
        """Tolak peminjaman yang sudah dipinjam → ValueError."""
        peminjaman_service.setujui(peminjaman_diajukan.id, admin_user.id)
        peminjaman_service.mulai_pinjam(peminjaman_diajukan.id)
        with pytest.raises(ValueError, match="tidak dapat ditolak"):
            peminjaman_service.tolak(
                peminjaman_diajukan.id, admin_user.id, "Telat"
            )

    def test_setujui_peminjaman_tidak_ada(
        self, peminjaman_service, admin_user
    ):
        """Setujui peminjaman yang tidak ada → ValueError."""
        with pytest.raises(ValueError, match="Peminjaman tidak ditemukan"):
            peminjaman_service.setujui("nonexistent-id", admin_user.id)


class TestPeminjamanServicePengembalian:
    """TC-09, TC-10, TC-13: Pengembalian & perhitungan denda (polymorphism)."""

    @pytest.fixture
    def peminjaman_dipinjam(
        self, peminjaman_service, warga_aktif, barang_set, admin_user
    ):
        """Peminjaman berstatus 'dipinjam' (sudah disetujui & diserahkan)."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[
                {"barang_id": barang_set["Proyektor"].id, "jumlah": 1},
                {"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1},
            ],
            tgl_pinjam=TODAY,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        peminjaman_service.mulai_pinjam(pjm.id)
        return pjm

    def test_pengembalian_tepat_waktu_denda_nol(
        self, peminjaman_service, peminjaman_dipinjam
    ):
        """Kembalikan tepat waktu → denda 0, status dikembalikan."""
        result = peminjaman_service.proses_pengembalian(
            peminjaman_dipinjam.id,
            kondisi_map={},
            tanggal_aktual=DAY_AFTER,  # tepat di tanggal rencana
        )
        assert result["denda"] == 0
        assert result["terlambat"] is False
        assert result["hari_terlambat"] == 0
        assert result["peminjaman"].status == "dikembalikan"
        assert result["peminjaman"].tanggal_kembali_aktual == DAY_AFTER

    def test_pengembalian_terlambat_denda_polymorphism(
        self, peminjaman_service, peminjaman_dipinjam, barang_set
    ):
        """
        Kembalikan terlambat → denda > 0 dengan tarif per kategori.

        Proyektor (Elektronik, 5000/hari) + Kursi Lipat (Furniture, 2000/hari).
        Terlambat 3 hari → denda = (5000 + 2000) * 3 = 21000.
        """
        kembali_aktual = DAY_AFTER + timedelta(days=3)  # 3 hari terlambat
        result = peminjaman_service.proses_pengembalian(
            peminjaman_dipinjam.id,
            kondisi_map={},
            tanggal_aktual=kembali_aktual,
        )
        assert result["terlambat"] is True
        assert result["hari_terlambat"] == 3
        # Polymorphism: 5000*3 + 2000*3 = 21000
        assert result["denda"] == 21000
        assert result["peminjaman"].total_denda_rupiah == 21000

    def test_pengembalian_catat_kondisi_kembali(
        self, peminjaman_service, peminjaman_dipinjam, barang_set
    ):
        """Kondisi_kembali tercatat per barang."""
        proyektor_id = barang_set["Proyektor"].id
        kursi_id = barang_set["Kursi Lipat"].id
        result = peminjaman_service.proses_pengembalian(
            peminjaman_dipinjam.id,
            kondisi_map={
                proyektor_id: "baik",
                kursi_id: "rusak_ringan",
            },
            tanggal_aktual=DAY_AFTER,
        )
        details = {d.barang_id: d for d in result["peminjaman"].detail_list}
        assert details[proyektor_id].kondisi_kembali == "baik"
        assert details[kursi_id].kondisi_kembali == "rusak_ringan"

    def test_pengembalian_kondisi_invalid(
        self, peminjaman_service, peminjaman_dipinjam, barang_set
    ):
        """Kondisi_kembali tidak valid → ValueError."""
        with pytest.raises(ValueError, match="Kondisi kembali tidak valid"):
            peminjaman_service.proses_pengembalian(
                peminjaman_dipinjam.id,
                kondisi_map={barang_set["Proyektor"].id: "rusak_total"},
                tanggal_aktual=DAY_AFTER,
            )

    def test_pengembalian_status_salah(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Kembalikan peminjaman yang masih 'diajukan' → ValueError."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        with pytest.raises(ValueError, match="tidak dapat dikembalikan"):
            peminjaman_service.proses_pengembalian(pjm.id)


class TestPeminjamanServiceQuery:
    """Test getter & filter."""

    def test_get_by_warga(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """get_by_warga return hanya peminjaman milik warga itu."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Tenda"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        result = peminjaman_service.get_by_warga(warga_aktif.id)
        assert len(result) == 2
        # Urut terbaru
        assert result[0].created_at >= result[1].created_at

    def test_get_all_filter_status(
        self, peminjaman_service, warga_aktif, barang_set, admin_user
    ):
        """get_all dengan filter status."""
        pjm1 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Tenda"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.setujui(pjm2.id, admin_user.id)

        diajukan = peminjaman_service.get_all({"status": "diajukan"})
        disetujui = peminjaman_service.get_all({"status": "disetujui"})
        assert all(p.status == "diajukan" for p in diajukan)
        assert all(p.status == "disetujui" for p in disetujui)
        assert any(p.id == pjm1.id for p in diajukan)
        assert any(p.id == pjm2.id for p in disetujui)

    def test_get_all_filter_status_invalid(
        self, peminjaman_service
    ):
        """Filter status invalid → ValueError."""
        with pytest.raises(ValueError, match="Status filter tidak valid"):
            peminjaman_service.get_all({"status": "tidak_ada_status_seperti_ini"})

    def test_get_terlambat(
        self, peminjaman_service, warga_aktif, barang_set, admin_user
    ):
        """get_terlambat return peminjaman dipinjam yang lewat jatuh tempo."""
        # Peminjaman dengan rencana kembali kemarin (sudah lewat)
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY - timedelta(days=5),
            tgl_kembali=TODAY - timedelta(days=1),
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        peminjaman_service.mulai_pinjam(pjm.id)

        terlambat = peminjaman_service.get_terlambat()
        assert any(p.id == pjm.id for p in terlambat)
        assert all(p.status == "dipinjam" for p in terlambat)

    def test_get_by_id_tidak_ada(self, peminjaman_service):
        """get_by_id return None jika tidak ada."""
        assert peminjaman_service.get_by_id("nonexistent") is None


class TestPeminjamanServiceValidateAvailability:
    """TC-08: Anti double-booking."""

    def test_tersedia_tanpa_peminjaman(
        self, peminjaman_service, barang_set
    ):
        """Barang tanpa peminjaman aktif → tersedia."""
        result = peminjaman_service.validate_availability(
            barang_set["Proyektor"].id, TMROW, DAY_AFTER, jumlah=1
        )
        assert result is True

    def test_bentrok_overlap(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Overlap dengan peminjaman aktif & stok habis → False."""
        # Proyektor stok 2, dipinjam 2 unit
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 2}],
            tgl_pinjam=TMROW,
            tgl_kembali=WEEK_LATER,
        )
        # Cek availability 1 unit pada rentang overlap → False
        result = peminjaman_service.validate_availability(
            barang_set["Proyektor"].id, DAY_AFTER, WEEK_LATER, jumlah=1
        )
        assert result is False

    def test_tersedia_non_overlap(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Peminjaman non-overlap → tersedia."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 2}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        # Cek availability setelah peminjaman pertama selesai
        result = peminjaman_service.validate_availability(
            barang_set["Proyektor"].id,
            DAY_AFTER + timedelta(days=1),
            DAY_AFTER + timedelta(days=3),
            jumlah=2,
        )
        assert result is True

    def test_stok_sebagian_dipinjam_masih_tersedia(
        self, peminjaman_service, warga_aktif, barang_set
    ):
        """Stok 10, dipinjam 3, minta 5 overlap → tersedia (3+5=8 ≤ 10)."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 3}],
            tgl_pinjam=TMROW,
            tgl_kembali=WEEK_LATER,
        )
        result = peminjaman_service.validate_availability(
            barang_set["Kursi Lipat"].id, DAY_AFTER, WEEK_LATER, jumlah=5
        )
        assert result is True

    def test_barang_terhapus_tidak_tersedia(
        self, peminjaman_service, barang_set
    ):
        """Barang yang di-soft-delete → tidak tersedia."""
        barang_set["Proyektor"].soft_delete()
        db.session.commit()
        result = peminjaman_service.validate_availability(
            barang_set["Proyektor"].id, TMROW, DAY_AFTER, jumlah=1
        )
        assert result is False


# ════════════════════════════════════════════════════════════
#  CONTROLLER HTTP TESTS
# ════════════════════════════════════════════════════════════

class TestPeminjamanControllerAccessControl:
    """Test akses endpoint peminjaman (login_required, admin_required, warga-only)."""

    def test_index_tanpa_login_redirect(self, client):
        """GET /peminjaman/ tanpa login → redirect ke /login."""
        resp = client.get("/peminjaman/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_detail_tanpa_login_redirect(self, client):
        """GET /peminjaman/<id> tanpa login → redirect."""
        resp = client.get("/peminjaman/some-id", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_ajukan_admin_403(self, client, login_admin):
        """Admin mencoba akses /peminjaman/ajukan → 403 (warga-only)."""
        resp = client.get("/peminjaman/ajukan")
        assert resp.status_code == 403

    def test_setujui_warga_403(self, client, login_warga):
        """Warga mencoba setujui peminjaman → 403."""
        resp = client.post("/peminjaman/some-id/setujui")
        assert resp.status_code == 403

    def test_tolak_warga_403(self, client, login_warga):
        """Warga mencoba tolak peminjaman → 403."""
        resp = client.post("/peminjaman/some-id/tolak")
        assert resp.status_code == 403

    def test_pinjam_warga_403(self, client, login_warga):
        """Warga mencoba tandai dipinjam → 403."""
        resp = client.post("/peminjaman/some-id/pinjam")
        assert resp.status_code == 403

    def test_kembalikan_warga_403(self, client, login_warga):
        """Warga mencoba proses pengembalian → 403."""
        resp = client.get("/peminjaman/some-id/kembalikan")
        assert resp.status_code == 403

    def test_detail_warga_lihat_milik_orang_403(
        self, client, login_warga, peminjaman_service, barang_set, app
    ):
        """Warga tidak boleh lihat peminjaman milik warga lain."""
        # Buat warga lain & peminjaman miliknya
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
            pjm = peminjaman_service.ajukan(
                warga_id=warga_lain.id,
                items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )
            pjm_id = pjm.id
        # login_warga (warga_aktif) mencoba akses peminjaman milik warga_lain
        resp = client.get(f"/peminjaman/{pjm_id}")
        assert resp.status_code == 403


class TestPeminjamanControllerHappyPath:
    """Test happy path via HTTP."""

    def test_index_admin_lihat_semua(
        self, client, login_admin, peminjaman_service, warga_aktif, barang_set
    ):
        """Admin lihat daftar peminjaman → 200, ada peminjaman."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        resp = client.get("/peminjaman/")
        assert resp.status_code == 200
        assert "PJM-".encode() in resp.data

    def test_index_warga_hanya_miliknya(
        self, client, login_warga, peminjaman_service, warga_aktif,
        barang_set, app
    ):
        """Warga lihat daftar → hanya peminjaman miliknya, bukan warga lain."""
        # Peminjaman milik warga_aktif (yang sedang login)
        pjm_sendiri = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        # Peminjaman milik warga lain
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
            pjm_orang = peminjaman_service.ajukan(
                warga_id=warga_lain.id,
                items=[{"barang_id": barang_set["Tenda"].id, "jumlah": 1}],
                tgl_pinjam=TMROW,
                tgl_kembali=DAY_AFTER,
            )
            kode_orang = pjm_orang.kode_peminjaman
            kode_sendiri = pjm_sendiri.kode_peminjaman

        resp = client.get("/peminjaman/")
        assert resp.status_code == 200
        # Peminjaman sendiri terlihat
        assert kode_sendiri.encode() in resp.data
        # Peminjaman orang lain TIDAK terlihat
        assert kode_orang.encode() not in resp.data

    def test_ajukan_warga_happy_path(
        self, client, login_warga, barang_set
    ):
        """Warga ajukan peminjaman via POST → redirect ke detail."""
        resp = client.post(
            "/peminjaman/ajukan",
            data={
                "tanggal_pinjam": TMROW.isoformat(),
                "tanggal_kembali": DAY_AFTER.isoformat(),
                "catatan": "Acara RT",
                "barang_id": barang_set["Proyektor"].id,
                "jumlah": 1,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/peminjaman/" in resp.headers["Location"]
        assert resp.headers["Location"].endswith("/peminjaman/") is False
        # redirect ke /peminjaman/<id>

    def test_ajukan_warga_form_render(
        self, client, login_warga, barang_set
    ):
        """GET /peminjaman/ajukan → 200, form ada."""
        resp = client.get("/peminjaman/ajukan")
        assert resp.status_code == 200
        assert b"Tanggal Pinjam" in resp.data
        assert b"Proyektor" in resp.data

    def test_setujui_admin_happy_path(
        self, client, login_admin, peminjaman_service, warga_aktif, barang_set
    ):
        """Admin setujui peminjaman via POST → redirect, status berubah."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        resp = client.post(
            f"/peminjaman/{pjm.id}/setujui",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Verify status changed
        db.session.expire_all()
        updated = db.session.get(Peminjaman, pjm.id)
        assert updated.status == "disetujui"

    def test_tolak_admin_happy_path(
        self, client, login_admin, peminjaman_service, warga_aktif, barang_set
    ):
        """Admin tolak peminjaman dengan alasan via POST."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        resp = client.post(
            f"/peminjaman/{pjm.id}/tolak",
            data={"alasan": "Barang tidak tersedia"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire_all()
        updated = db.session.get(Peminjaman, pjm.id)
        assert updated.status == "ditolak"
        assert updated.alasan_penolakan == "Barang tidak tersedia"

    def test_alur_lengkap_lifecycle_via_controller(
        self, client, login_admin, peminjaman_service, warga_aktif,
        barang_set, admin_user
    ):
        """
        TC-05: Alur lengkap diajukan → disetujui → dipinjam → dikembalikan
        via kombinasi service + controller HTTP.
        """
        # 1. Warga ajukan (via service)
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY,
            tgl_kembali=DAY_AFTER,
        )
        assert pjm.status == "diajukan"

        # 2. Admin setujui via HTTP POST (login_admin fixture sudah login)
        resp = client.post(
            f"/peminjaman/{pjm.id}/setujui", follow_redirects=False
        )
        assert resp.status_code == 302
        db.session.expire_all()
        pjm = db.session.get(Peminjaman, pjm.id)
        assert pjm.status == "disetujui"

        # 3. Admin tandai dipinjam via HTTP POST
        resp = client.post(
            f"/peminjaman/{pjm.id}/pinjam", follow_redirects=False
        )
        assert resp.status_code == 302
        db.session.expire_all()
        pjm = db.session.get(Peminjaman, pjm.id)
        assert pjm.status == "dipinjam"

        # 4. Admin proses pengembalian via HTTP POST
        resp = client.post(
            f"/peminjaman/{pjm.id}/kembalikan",
            data={f"kondisi_{barang_set['Proyektor'].id}": "baik"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.expire_all()
        pjm = db.session.get(Peminjaman, pjm.id)
        assert pjm.status == "dikembalikan"
        assert pjm.is_final is True

    def test_alur_lengkap_via_service(
        self, peminjaman_service, warga_aktif, barang_set, admin_user
    ):
        """Alur lengkap state machine via service layer."""
        # 1. Ajukan
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TODAY,
            tgl_kembali=DAY_AFTER,
        )
        assert pjm.status == "diajukan"

        # 2. Setujui
        pjm = peminjaman_service.setujui(pjm.id, admin_user.id)
        assert pjm.status == "disetujui"

        # 3. Mulai pinjam
        pjm = peminjaman_service.mulai_pinjam(pjm.id)
        assert pjm.status == "dipinjam"

        # 4. Kembalikan tepat waktu
        result = peminjaman_service.proses_pengembalian(
            pjm.id, kondisi_map={}, tanggal_aktual=DAY_AFTER
        )
        assert result["peminjaman"].status == "dikembalikan"
        assert result["denda"] == 0
        assert pjm.is_final is True
