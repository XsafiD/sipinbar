"""
tests/test_barang.py — Test modul Inventaris Barang (T-BRG-03).

Menguji:
  - BarangService.tambah (valid, nama duplikat, validasi field)
  - BarangService.edit (update field, nama duplikat)
  - BarangService.hapus (soft delete: status 'dihapus' + deleted_at terisi)
  - BarangService.search & get_all dengan filter (q, kategori)
  - Polymorphism denda: Elektronik 5000, Furniture 2000, Peralatan 3000
  - BR-06: hapus barang yang sedang dipinjam ditolak
  - Controller HTTP: access control (login_required, admin_required),
    happy path create/edit/hapus via test client

Refs: TODO T-BRG-03, SRS §11.2 TC-03, TC-04, TC-11, TC-12, TC-14
"""
from datetime import date

import pytest

from models import db
from models.admin import Admin
from models.barang import Barang, Kategori
from models.peminjaman import DetailPeminjaman, Peminjaman
from models.warga import Warga
from services.barang_service import BarangService


# ── Helper fixtures ──────────────────────────────────────────
@pytest.fixture
def barang_service(app):
    """Service instance — depend on `app` agar app context aktif."""
    return BarangService()


@pytest.fixture
def kategori_set(app):
    """3 kategori default (sesuai seed & SRS §5.4)."""
    data = [
        Kategori(nama="Elektronik", tarif_denda_per_hari=5000),
        Kategori(nama="Furniture", tarif_denda_per_hari=2000),
        Kategori(nama="Peralatan", tarif_denda_per_hari=3000),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {k.nama: k for k in data}


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
    """Warga aktif untuk test akses (harus dapat 403 di endpoint admin)."""
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


# ── SERVICE LAYER TESTS ──────────────────────────────────────


class TestBarangServiceTambah:
    """TC-03: Tambah barang valid & invalid."""

    def test_tambah_barang_valid(
        self, barang_service, kategori_set
    ):
        """Tambah barang valid → tersimpan, status default 'tersedia'."""
        barang = barang_service.tambah(
            {
                "nama": "Proyektor Epson",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 2,
                "kondisi": "baik",
                "deskripsi": "Proyektor untuk acara",
            }
        )
        assert barang.id is not None
        assert barang.nama == "Proyektor Epson"
        assert barang.jumlah_unit == 2
        assert barang.status == "tersedia"
        assert barang.kondisi == "baik"
        assert barang.deleted_at is None

    def test_tambah_nama_duplikat_ditolak(
        self, barang_service, kategori_set
    ):
        """TC-04: Tambah nama duplikat (case-insensitive) → ValueError."""
        barang_service.tambah(
            {
                "nama": "Proyektor",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        # Nama sama persis
        with pytest.raises(ValueError, match="sudah dipakai"):
            barang_service.tambah(
                {
                    "nama": "Proyektor",
                    "kategori_id": kategori_set["Elektronik"].id,
                    "jumlah": 1,
                }
            )
        # Nama beda case juga harus ditolak
        with pytest.raises(ValueError, match="sudah dipakai"):
            barang_service.tambah(
                {
                    "nama": "PROYEKTOR",
                    "kategori_id": kategori_set["Peralatan"].id,
                    "jumlah": 1,
                }
            )

    def test_tambah_jumlah_invalid_ditolak(self, barang_service, kategori_set):
        """Jumlah <= 0 → ValueError."""
        with pytest.raises(ValueError, match="Jumlah"):
            barang_service.tambah(
                {
                    "nama": "Barang Aneh",
                    "kategori_id": kategori_set["Elektronik"].id,
                    "jumlah": 0,
                }
            )

    def test_tambah_kategori_tidak_ada_ditolak(self, barang_service):
        """Kategori ID ghost → ValueError."""
        with pytest.raises(ValueError, match="Kategori tidak ditemukan"):
            barang_service.tambah(
                {
                    "nama": "Barang X",
                    "kategori_id": "ghost-kategori-id",
                    "jumlah": 1,
                }
            )

    def test_tambah_kondisi_invalid_ditolak(
        self, barang_service, kategori_set
    ):
        """Kondisi invalid → ValueError (delegasi ke model.set_kondisi)."""
        with pytest.raises(ValueError, match="Kondisi tidak valid"):
            barang_service.tambah(
                {
                    "nama": "Barang Y",
                    "kategori_id": kategori_set["Elektronik"].id,
                    "jumlah": 1,
                    "kondisi": "rusak_berat",  # tidak ada di enum
                }
            )


class TestBarangServiceEdit:
    """TC-14: Edit barang."""

    def test_edit_update_nama_dan_jumlah(
        self, barang_service, kategori_set
    ):
        """Edit nama & jumlah → tersimpan."""
        barang = barang_service.tambah(
            {
                "nama": "Tenda Lama",
                "kategori_id": kategori_set["Peralatan"].id,
                "jumlah": 1,
            }
        )
        updated = barang_service.edit(
            barang.id,
            {"nama": "Tenda Baru", "jumlah": 5},
        )
        assert updated.nama == "Tenda Baru"
        assert updated.jumlah_unit == 5

    def test_edit_nama_duplikat_ke_barang_lain_ditolak(
        self, barang_service, kategori_set
    ):
        """Edit nama jadi nama barang lain → ValueError."""
        barang_service.tambah(
            {
                "nama": "Kursi A",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        b2 = barang_service.tambah(
            {
                "nama": "Kursi B",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        with pytest.raises(ValueError, match="sudah dipakai"):
            barang_service.edit(b2.id, {"nama": "Kursi A"})

    def test_edit_barang_tidak_ditemukan(self, barang_service):
        """Edit ID ghost → ValueError."""
        with pytest.raises(ValueError, match="tidak ditemukan"):
            barang_service.edit("ghost-id", {"nama": "Apapun"})


class TestBarangServiceSoftDelete:
    """BR-08: hapus = soft delete."""

    def test_hapus_set_status_dihapus_dan_deleted_at(
        self, barang_service, kategori_set
    ):
        """Soft delete → status='dihapus' & deleted_at terisi."""
        barang = barang_service.tambah(
            {
                "nama": "Meja Lipat",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        assert barang.deleted_at is None
        deleted = barang_service.hapus(barang.id)
        assert deleted.status == "dihapus"
        assert deleted.deleted_at is not None

    def test_hapus_tidak_muncul_di_get_all(
        self, barang_service, kategori_set
    ):
        """Setelah soft delete, barang tidak muncul di get_all default."""
        barang = barang_service.tambah(
            {
                "nama": "Sound System",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        assert len(barang_service.get_all()) == 1
        barang_service.hapus(barang.id)
        assert len(barang_service.get_all()) == 0
        # Tapi tetap ada di DB jika include_deleted=True
        assert len(barang_service.get_all({"include_deleted": True})) == 1

    def test_get_by_id_default_exclude_deleted(
        self, barang_service, kategori_set
    ):
        """get_by_id default return None untuk barang terhapus."""
        barang = barang_service.tambah(
            {
                "nama": "Barang Sementara",
                "kategori_id": kategori_set["Peralatan"].id,
                "jumlah": 1,
            }
        )
        barang_service.hapus(barang.id)
        assert barang_service.get_by_id(barang.id) is None
        assert (
            barang_service.get_by_id(barang.id, include_deleted=True)
            is not None
        )


class TestBarangServiceSearchFilter:
    """TC-11, TC-12: search by nama, filter by kategori."""

    def test_search_by_nama(self, barang_service, kategori_set):
        """Search keyword → match nama (case-insensitive)."""
        for nama in ("Proyektor", "Proyektor Mini", "Tenda"):
            barang_service.tambah(
                {
                    "nama": nama,
                    "kategori_id": kategori_set["Elektronik"].id,
                    "jumlah": 1,
                }
            )
        # Pakai service.search
        hasil = barang_service.search("proyek")
        assert len(hasil) == 2  # Proyektor & Proyektor Mini
        # Pakai get_all dengan filter q
        hasil_q = barang_service.get_all({"q": "proyek"})
        assert len(hasil_q) == 2

    def test_filter_by_kategori(self, barang_service, kategori_set):
        """Filter kategori → hanya barang kategori itu."""
        barang_service.tambah(
            {
                "nama": "Proyektor",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        barang_service.tambah(
            {
                "nama": "Kursi",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        barang_service.tambah(
            {
                "nama": "Tenda",
                "kategori_id": kategori_set["Peralatan"].id,
                "jumlah": 1,
            }
        )

        elektronik = barang_service.get_by_kategori(
            kategori_set["Elektronik"].id
        )
        assert len(elektronik) == 1
        assert elektronik[0].nama == "Proyektor"

        # via get_all filter
        hasil = barang_service.get_all(
            {"kategori": kategori_set["Furniture"].id}
        )
        assert len(hasil) == 1
        assert hasil[0].nama == "Kursi"

    def test_get_all_filter_status_invalid_raise(
        self, barang_service, kategori_set
    ):
        """Filter status invalid → ValueError."""
        with pytest.raises(ValueError, match="tidak valid"):
            barang_service.get_all({"status": "hapus-semua"})


class TestPolymorphismDenda:
    """TC-11 & TC-12: tarif denda berbeda per kategori."""

    def test_denda_elektronik_5000(self, barang_service, kategori_set):
        """Barang Elektronik, 3 hari → denda 3 * 5000 = 15000."""
        barang = barang_service.tambah(
            {
                "nama": "Proyektor",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        assert barang.hitung_denda(3) == 15000

    def test_denda_furniture_2000(self, barang_service, kategori_set):
        """Barang Furniture, 3 hari → denda 3 * 2000 = 6000."""
        barang = barang_service.tambah(
            {
                "nama": "Kursi Lipat",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        assert barang.hitung_denda(3) == 6000

    def test_denda_peralatan_3000(self, barang_service, kategori_set):
        """Barang Peralatan, 3 hari → denda 3 * 3000 = 9000."""
        barang = barang_service.tambah(
            {
                "nama": "Tenda",
                "kategori_id": kategori_set["Peralatan"].id,
                "jumlah": 1,
            }
        )
        assert barang.hitung_denda(3) == 9000

    def test_denda_nol_jika_tidak_terlambat(self, barang_service, kategori_set):
        """hari_terlambat <= 0 → denda 0."""
        barang = barang_service.tambah(
            {
                "nama": "Speaker",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        assert barang.hitung_denda(0) == 0
        assert barang.hitung_denda(-2) == 0

    def test_polymorphism_tanpa_peduli_jenis_kategori(
        self, app, kategori_set
    ):
        """
        Caller code tidak perlu tahu jenis kategori — cukup panggil
        hitung_denda(). Inilah inti polymorphism di SIPINBAR.
        """
        # Persist dulu agar relasi lazy='joined' ke kategori ter-load.
        barang_list = [
            Barang(nama="A", kategori_id=kategori_set["Elektronik"].id),
            Barang(nama="B", kategori_id=kategori_set["Furniture"].id),
            Barang(nama="C", kategori_id=kategori_set["Peralatan"].id),
        ]
        db.session.add_all(barang_list)
        db.session.commit()
        # Total denda untuk 2 hari terlambat = 2*(5000+2000+3000) = 20000
        total = sum(b.hitung_denda(2) for b in barang_list)
        assert total == 20000


class TestBr06BarangSedangDipinjam:
    """BR-06: barang yang sedang dipinjam tidak bisa dihapus."""

    def test_hapus_barang_sedang_dipinjam_ditolak(
        self, barang_service, kategori_set, app
    ):
        """Barang dengan peminjaman aktif (dipinjam) → hapus ditolak."""
        # Setup: 1 warga, 1 barang, 1 peminjaman aktif berisi barang itu
        warga = Warga(
            nik="3171010101010099",
            nama_lengkap="Peminjam",
            alamat="Jl. X",
            telepon="081234567899",
            rt_rw="001/001",
            status="aktif",
        )
        warga.set_password("pass12345")
        db.session.add(warga)

        barang = barang_service.tambah(
            {
                "nama": "Proyektor Dipinjam",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )

        peminjaman = Peminjaman(
            kode_peminjaman="PJM-2026-0001",
            warga_id=warga.id,
            tanggal_pinjam=date(2026, 7, 1),
            tanggal_kembali_rencana=date(2026, 7, 3),
            status="dipinjam",  # status aktif → barang sedang dipakai
        )
        db.session.add(peminjaman)
        db.session.flush()
        db.session.add(
            DetailPeminjaman(
                peminjaman_id=peminjaman.id,
                barang_id=barang.id,
                jumlah=1,
            )
        )
        db.session.commit()

        # BR-06: hapus harus ditolak
        with pytest.raises(ValueError, match="BR-06"):
            barang_service.hapus(barang.id)

        # Barang masih ada (tidak terhapus)
        assert barang_service.get_by_id(barang.id) is not None
        assert barang.status != "dihapus"

    def test_hapus_barang_dengan_peminjaman_lampau_tetap_bisa(
        self, barang_service, kategori_set, app
    ):
        """
        Barang yang peminjamannya SUDAH dikembalikan/ditolak (final)
        tetap boleh dihapus — karena sudah tidak sedang dipakai.
        """
        warga = Warga(
            nik="3171010101010088",
            nama_lengkap="Peminjam Lampau",
            alamat="Jl. Y",
            telepon="081234567888",
            rt_rw="001/002",
            status="aktif",
        )
        warga.set_password("pass12345")
        db.session.add(warga)

        barang = barang_service.tambah(
            {
                "nama": "Kursi Lalu",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )

        peminjaman = Peminjaman(
            kode_peminjaman="PJM-2026-0002",
            warga_id=warga.id,
            tanggal_pinjam=date(2026, 6, 1),
            tanggal_kembali_rencana=date(2026, 6, 3),
            tanggal_kembali_aktual=date(2026, 6, 3),
            status="dikembalikan",  # final → barang bebas
        )
        db.session.add(peminjaman)
        db.session.flush()
        db.session.add(
            DetailPeminjaman(
                peminjaman_id=peminjaman.id,
                barang_id=barang.id,
                jumlah=1,
            )
        )
        db.session.commit()

        # Harus bisa dihapus
        deleted = barang_service.hapus(barang.id)
        assert deleted.status == "dihapus"


# ── CONTROLLER (HTTP) TESTS ──────────────────────────────────


class TestBarangControllerAccessControl:
    """Role-based access untuk endpoint /barang."""

    def test_katalog_tanpa_login_redirect(self, client):
        """GET /barang/ tanpa login → 302 ke /login."""
        resp = client.get("/barang/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_katalog_sebagai_warga_ok(
        self, client, login_warga, kategori_set, barang_service
    ):
        """Login sebagai warga → GET /barang/ → 200."""
        barang_service.tambah(
            {
                "nama": "Proyektor",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        resp = client.get("/barang/")
        assert resp.status_code == 200
        assert "Proyektor" in resp.get_data(as_text=True)

    def test_katalog_sebagai_admin_ok(
        self, client, login_admin, kategori_set, barang_service
    ):
        """Login sebagai admin → GET /barang/ → 200."""
        barang_service.tambah(
            {
                "nama": "Tenda",
                "kategori_id": kategori_set["Peralatan"].id,
                "jumlah": 1,
            }
        )
        resp = client.get("/barang/")
        assert resp.status_code == 200

    def test_detail_barang_ok(self, client, login_warga, kategori_set, barang_service):
        """GET /barang/<id> → 200 + info barang."""
        barang = barang_service.tambah(
            {
                "nama": "Speaker JBL",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 2,
            }
        )
        resp = client.get(f"/barang/{barang.id}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Speaker JBL" in body

    def test_detail_barang_tidak_ada_404(self, client, login_admin):
        """GET /barang/ghost-id → 404."""
        resp = client.get("/barang/ghost-id-tidak-ada")
        assert resp.status_code == 404

    def test_tambah_sebagai_warga_403(
        self, client, login_warga, kategori_set
    ):
        """POST /barang/tambah sebagai warga → 403 Forbidden."""
        resp = client.post(
            "/barang/tambah",
            data={
                "nama": "Hack",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
                "kondisi": "baik",
                "status": "tersedia",
            },
        )
        assert resp.status_code == 403

    def test_edit_sebagai_warga_403(
        self, client, login_warga, kategori_set, barang_service
    ):
        """GET & POST /barang/<id>/edit sebagai warga → 403."""
        barang = barang_service.tambah(
            {
                "nama": "Barang Warga",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        assert client.get(f"/barang/{barang.id}/edit").status_code == 403
        assert (
            client.post(
                f"/barang/{barang.id}/edit",
                data={"nama": "Diubah Warga"},
            ).status_code
            == 403
        )

    def test_hapus_sebagai_warga_403(
        self, client, login_warga, kategori_set, barang_service
    ):
        """POST /barang/<id>/hapus sebagai warga → 403."""
        barang = barang_service.tambah(
            {
                "nama": "Barang Hapus",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        resp = client.post(f"/barang/{barang.id}/hapus")
        assert resp.status_code == 403


class TestBarangControllerCrudHappyPath:
    """Happy path CRUD via HTTP (sebagai admin)."""

    def test_tambah_barang_via_http(
        self, client, login_admin, kategori_set
    ):
        """POST /barang/tambah valid → redirect ke detail + barang tersimpan."""
        resp = client.post(
            "/barang/tambah",
            data={
                "nama": "Proyektor HTTP",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 3,
                "kondisi": "baik",
                "status": "tersedia",
                "deskripsi": "Via HTTP test",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/barang/" in resp.headers["Location"]
        # Cek tersimpan
        hasil = Barang.query.filter_by(nama="Proyektor HTTP").first()
        assert hasil is not None
        assert hasil.jumlah_unit == 3

    def test_tambah_nama_duplikat_via_http_flash_error(
        self, client, login_admin, kategori_set, barang_service
    ):
        """POST /barang/tambah nama duplikat → render ulang + flash error."""
        barang_service.tambah(
            {
                "nama": "Duplikat HTTP",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        resp = client.post(
            "/barang/tambah",
            data={
                "nama": "Duplikat HTTP",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
                "kondisi": "baik",
                "status": "tersedia",
            },
            follow_redirects=True,
        )
        # Form di-render ulang (200), ada flash error
        assert resp.status_code == 200
        assert "sudah dipakai" in resp.get_data(as_text=True)

    def test_edit_barang_via_http(
        self, client, login_admin, kategori_set, barang_service
    ):
        """POST /barang/<id>/edit → redirect detail, data berubah."""
        barang = barang_service.tambah(
            {
                "nama": "Edit HTTP",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        resp = client.post(
            f"/barang/{barang.id}/edit",
            data={
                "nama": "Edit HTTP Updated",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 7,
                "kondisi": "perlu_perbaikan",
                "status": "perbaikan",
                "deskripsi": "Sudah diupdate",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.refresh(barang)
        assert barang.nama == "Edit HTTP Updated"
        assert barang.jumlah_unit == 7
        assert barang.kategori_id == kategori_set["Furniture"].id
        assert barang.kondisi == "perlu_perbaikan"

    def test_hapus_barang_via_http_soft_delete(
        self, client, login_admin, kategori_set, barang_service
    ):
        """POST /barang/<id>/hapus → redirect index + status jadi 'dihapus'."""
        barang = barang_service.tambah(
            {
                "nama": "Hapus HTTP",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        resp = client.post(
            f"/barang/{barang.id}/hapus",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.session.refresh(barang)
        assert barang.status == "dihapus"
        assert barang.deleted_at is not None

    def test_filter_kategori_via_http(
        self, client, login_admin, kategori_set, barang_service
    ):
        """?kategori=<id> → hanya tampil barang kategori itu."""
        barang_service.tambah(
            {
                "nama": "Hanya Elektronik",
                "kategori_id": kategori_set["Elektronik"].id,
                "jumlah": 1,
            }
        )
        barang_service.tambah(
            {
                "nama": "Hanya Furniture",
                "kategori_id": kategori_set["Furniture"].id,
                "jumlah": 1,
            }
        )
        resp = client.get(
            f"/barang/?kategori={kategori_set['Elektronik'].id}"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Hanya Elektronik" in body
        assert "Hanya Furniture" not in body
