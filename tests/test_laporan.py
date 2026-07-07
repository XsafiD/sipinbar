"""
tests/test_laporan.py — Test modul Laporan (T-LAP-06).

Menguji:
  - LaporanService.generate_laporan_peminjaman (empty, dengan data,
    filter periode, filter status, distribusi status)
  - LaporanService.generate_laporan_inventaris (empty, dengan data,
    exclude/include soft-deleted)
  - LaporanService.export_laporan (CSV dengan BOM, format tidak didukung)
  - LaporanService.get_statistik_dashboard (empty, dengan data,
    exclude deleted barang)
  - LaporanService.get_statistik_warga

Refs: TODO T-LAP-06
"""
from datetime import date, timedelta

import pytest

from models import db
from models.admin import Admin
from models.barang import Barang, Kategori
from models.warga import Warga
from services.laporan_service import LaporanService
from services.peminjaman_service import PeminjamanService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def laporan_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return LaporanService()


@pytest.fixture
def peminjaman_service(app):
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
def warga_diblokir(app):
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


# ── Helper tanggal ───────────────────────────────────────────
TODAY = date.today()
TMROW = TODAY + timedelta(days=1)
DAY_AFTER = TODAY + timedelta(days=2)
LAST_WEEK = TODAY - timedelta(days=7)


# ════════════════════════════════════════════════════════════
#  LAPORAN PEMINJAMAN
# ════════════════════════════════════════════════════════════

class TestLaporanPeminjaman:
    """Test generate_laporan_peminjaman."""

    def test_laporan_peminjaman_kosong(self, laporan_service):
        """Tidak ada peminjaman → rows kosong, summary total 0."""
        data = laporan_service.generate_laporan_peminjaman()
        assert data["rows"] == []
        assert data["summary"]["total_peminjaman"] == 0
        assert data["summary"]["total_denda_rupiah"] == 0
        assert data["metadata"]["filter"]["tanggal_mulai"] is None

    def test_laporan_peminjaman_dengan_data(
        self, laporan_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Ada peminjaman → rows terisi, summary benar."""
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        data = laporan_service.generate_laporan_peminjaman()
        assert data["summary"]["total_peminjaman"] == 1
        assert any(r["kode_peminjaman"] == pjm.kode_peminjaman for r in data["rows"])
        assert "diajukan" in data["summary"]["distribusi_status"]

    def test_laporan_peminjaman_filter_periode(
        self, laporan_service, peminjaman_service,
        warga_aktif, barang_set
    ):
        """Filter periode membatasi hasil sesuai rentang tanggal."""
        # Peminjaman minggu lalu
        pjm_lama = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=LAST_WEEK,
            tgl_kembali=LAST_WEEK + timedelta(days=1),
        )
        # Peminjaman besok
        pjm_baru = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )

        # Filter hanya hari ini ke depan
        data = laporan_service.generate_laporan_peminjaman(
            mulai=TODAY, selesai=DAY_AFTER
        )
        kode_hasil = {r["kode_peminjaman"] for r in data["rows"]}
        assert pjm_baru.kode_peminjaman in kode_hasil
        assert pjm_lama.kode_peminjaman not in kode_hasil

    def test_laporan_peminjaman_filter_status(
        self, laporan_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Filter status membatasi hasil."""
        pjm1 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.setujui(pjm2.id, admin_user.id)

        data_diajukan = laporan_service.generate_laporan_peminjaman(status="diajukan")
        data_disetujui = laporan_service.generate_laporan_peminjaman(status="disetujui")

        assert all(r["status"] == "diajukan" for r in data_diajukan["rows"])
        assert all(r["status"] == "disetujui" for r in data_disetujui["rows"])
        assert any(r["kode_peminjaman"] == pjm1.kode_peminjaman for r in data_diajukan["rows"])
        assert any(r["kode_peminjaman"] == pjm2.kode_peminjaman for r in data_disetujui["rows"])

    def test_laporan_peminjaman_status_invalid(
        self, laporan_service
    ):
        """Filter status invalid → ValueError."""
        with pytest.raises(ValueError):
            laporan_service.generate_laporan_peminjaman(status="status_ngawur")

    def test_laporan_peminjaman_distribusi_status(
        self, laporan_service, peminjaman_service,
        warga_aktif, barang_set, admin_user
    ):
        """Distribusi status menghitung benar per kategori."""
        pjm1 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.setujui(pjm2.id, admin_user.id)

        data = laporan_service.generate_laporan_peminjaman()
        dist = data["summary"]["distribusi_status"]
        assert dist.get("diajukan") == 1
        assert dist.get("disetujui") == 1


# ════════════════════════════════════════════════════════════
#  LAPORAN INVENTARIS
# ════════════════════════════════════════════════════════════

class TestLaporanInventaris:
    """Test generate_laporan_inventaris."""

    def test_laporan_inventaris_kosong(self, laporan_service):
        """Tidak ada barang → rows kosong, total 0."""
        data = laporan_service.generate_laporan_inventaris()
        assert data["rows"] == []
        assert data["summary"]["total_jenis_barang"] == 0
        assert data["summary"]["total_unit"] == 0

    def test_laporan_inventaris_dengan_data(
        self, laporan_service, barang_set
    ):
        """Ada barang → rows terisi, total unit benar."""
        data = laporan_service.generate_laporan_inventaris()
        assert data["summary"]["total_jenis_barang"] == 2
        # 2 Proyektor + 10 Kursi Lipat = 12
        assert data["summary"]["total_unit"] == 12
        nama_barang = {r["nama"] for r in data["rows"]}
        assert "Proyektor" in nama_barang
        assert "Kursi Lipat" in nama_barang

    def test_laporan_inventaris_exclude_deleted(
        self, laporan_service, barang_set
    ):
        """Soft-deleted barang tidak muncul by default."""
        barang_set["Proyektor"].soft_delete()
        db.session.commit()

        data = laporan_service.generate_laporan_inventaris()
        assert data["summary"]["total_jenis_barang"] == 1
        nama_barang = {r["nama"] for r in data["rows"]}
        assert "Proyektor" not in nama_barang
        assert "Kursi Lipat" in nama_barang

    def test_laporan_inventaris_include_deleted(
        self, laporan_service, barang_set
    ):
        """include_deleted=True → soft-deleted barang ikut muncul."""
        barang_set["Proyektor"].soft_delete()
        db.session.commit()

        data = laporan_service.generate_laporan_inventaris(include_deleted=True)
        assert data["summary"]["total_jenis_barang"] == 2

    def test_laporan_inventaris_distribusi_kondisi(
        self, laporan_service, barang_set
    ):
        """Distribusi kondisi terisi benar."""
        data = laporan_service.generate_laporan_inventaris()
        dist = data["summary"]["distribusi_kondisi"]
        # Default kondisi = 'baik' untuk semua barang seed
        assert dist.get("baik") == 2


# ════════════════════════════════════════════════════════════
#  EXPORT CSV
# ════════════════════════════════════════════════════════════

class TestLaporanExport:
    """Test export_laporan ke CSV."""

    def test_export_csv_peminjaman(
        self, laporan_service, peminjaman_service,
        warga_aktif, barang_set
    ):
        """Export CSV peminjaman → bytes dengan BOM UTF-8 & header."""
        peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        data = laporan_service.generate_laporan_peminjaman()
        csv_bytes = laporan_service.export_laporan(data, format="csv")

        assert isinstance(csv_bytes, bytes)
        # BOM UTF-8 untuk Excel
        assert csv_bytes.startswith("\ufeff".encode("utf-8"))
        # Header kolom ada
        assert b"kode_peminjaman" in csv_bytes
        # Kode peminjaman tercantum
        assert b"PJM-" in csv_bytes

    def test_export_csv_inventaris(
        self, laporan_service, barang_set
    ):
        """Export CSV inventaris → bytes dengan data barang."""
        data = laporan_service.generate_laporan_inventaris()
        csv_bytes = laporan_service.export_laporan(data, format="csv")

        assert isinstance(csv_bytes, bytes)
        assert csv_bytes.startswith("\ufeff".encode("utf-8"))
        assert b"Proyektor" in csv_bytes
        assert b"Kursi Lipat" in csv_bytes

    def test_export_csv_empty_data(self, laporan_service):
        """Export CSV dengan data kosong → bytes (BOM only, no rows)."""
        data = laporan_service.generate_laporan_peminjaman()
        csv_bytes = laporan_service.export_laporan(data, format="csv")
        # BOM tetap ada, rows kosong
        assert csv_bytes.startswith("\ufeff".encode("utf-8"))

    def test_export_format_tidak_didukung(self, laporan_service):
        """Format tidak didukung → ValueError."""
        data = {"rows": [], "summary": {}, "metadata": {}}
        with pytest.raises(ValueError, match="belum didukung"):
            laporan_service.export_laporan(data, format="pdf")


# ════════════════════════════════════════════════════════════
#  STATISTIK DASHBOARD
# ════════════════════════════════════════════════════════════

class TestLaporanStatistikDashboard:
    """Test get_statistik_dashboard & get_statistik_warga."""

    def test_statistik_dashboard_kosong(self, laporan_service):
        """DB kosong → semua metrik 0."""
        stats = laporan_service.get_statistik_dashboard()
        assert stats["total_barang"] == 0
        assert stats["total_unit_barang"] == 0
        assert stats["peminjaman_aktif"] == 0
        assert stats["peminjaman_terlambat"] == 0
        assert stats["warga_terdaftar"] == 0
        assert stats["warga_aktif"] == 0
        assert "generated_at" in stats

    def test_statistik_dashboard_dengan_data(
        self, laporan_service, peminjaman_service,
        barang_set, warga_aktif, warga_diblokir, admin_user
    ):
        """Ada data → metrik terisi benar."""
        # 2 barang (Proyektor + Kursi Lipat)
        # 1 warga aktif + 1 warga diblokir
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        peminjaman_service.mulai_pinjam(pjm.id)

        stats = laporan_service.get_statistik_dashboard()
        assert stats["total_barang"] == 2
        assert stats["total_unit_barang"] == 12  # 2 + 10
        assert stats["peminjaman_aktif"] == 1  # status dipinjam
        assert stats["peminjaman_terlambat"] == 0
        assert stats["warga_terdaftar"] == 2
        assert stats["warga_aktif"] == 1

    def test_statistik_dashboard_exclude_deleted_barang(
        self, laporan_service, barang_set
    ):
        """Barang soft-deleted tidak dihitung di total_barang."""
        assert laporan_service.get_statistik_dashboard()["total_barang"] == 2
        barang_set["Proyektor"].soft_delete()
        db.session.commit()
        stats = laporan_service.get_statistik_dashboard()
        assert stats["total_barang"] == 1
        assert stats["total_unit_barang"] == 10  # hanya Kursi Lipat

    def test_statistik_dashboard_peminjaman_terlambat(
        self, laporan_service, peminjaman_service,
        barang_set, warga_aktif, admin_user
    ):
        """Peminjaman lewat jatuh tempo & berstatus terlambat terhitung."""
        # Peminjaman dengan tanggal kemarin (sudah lewat)
        pjm = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=LAST_WEEK,
            tgl_kembali=LAST_WEEK + timedelta(days=1),
        )
        peminjaman_service.setujui(pjm.id, admin_user.id)
        peminjaman_service.mulai_pinjam(pjm.id)
        # Tandai terlambat manual
        pjm.tandai_terlambat()
        db.session.commit()

        stats = laporan_service.get_statistik_dashboard()
        # Aktif berjalan termasuk 'terlambat'
        assert stats["peminjaman_aktif"] == 1
        assert stats["peminjaman_terlambat"] == 1

    def test_statistik_warga(
        self, laporan_service, peminjaman_service,
        barang_set, warga_aktif, admin_user
    ):
        """Statistik per warga: aktif, riwayat, terlambat."""
        pjm1 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Proyektor"].id, "jumlah": 1}],
            tgl_pinjam=TMROW,
            tgl_kembali=DAY_AFTER,
        )
        pjm2 = peminjaman_service.ajukan(
            warga_id=warga_aktif.id,
            items=[{"barang_id": barang_set["Kursi Lipat"].id, "jumlah": 1}],
            tgl_pinjam=LAST_WEEK,
            tgl_kembali=LAST_WEEK + timedelta(days=1),
        )
        peminjaman_service.setujui(pjm1.id, admin_user.id)
        peminjaman_service.mulai_pinjam(pjm1.id)
        # pjm1: dipinjam (aktif), pjm2: diajukan (juga aktif berjalan)

        stats = laporan_service.get_statistik_warga(warga_aktif.id)
        assert stats["peminjaman_aktif"] == 2  # pjm1 dipinjam + pjm2 diajukan
        assert stats["peminjaman_riwayat"] == 2  # total 2
        assert stats["peminjaman_terlambat"] == 0
        assert "generated_at" in stats

    def test_statistik_warga_kosong(self, laporan_service, warga_aktif):
        """Warga tanpa peminjaman → semua 0."""
        stats = laporan_service.get_statistik_warga(warga_aktif.id)
        assert stats["peminjaman_aktif"] == 0
        assert stats["peminjaman_riwayat"] == 0
        assert stats["peminjaman_terlambat"] == 0
