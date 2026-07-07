"""
tests/test_smoke.py — Smoke test dasar untuk memvalidasi foundation M1.

Memastikan:
  - App factory berfungsi
  - Database bisa di-create
  - Model bisa di-instantiate & save
  - ABC/mixin contract berfungsi
  - Constraint di-enforce
"""


def test_app_factory_menghasilkan_flask_app(app):
    """App factory harus return Flask app yang siap pakai."""
    assert app is not None
    assert app.config["TESTING"] is True
    # In-memory DB
    assert ":memory:" in app.config["SQLALCHEMY_DATABASE_URI"]


def test_client_bisa_akses_health(client):
    """Test client harus bisa akses endpoint dasar."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["app"] == "sipinbar"


def test_dibuat_semua_tabel_tersedia(app):
    """db.create_all harus menghasilkan 7 tabel sesuai spec."""
    from sqlalchemy import inspect

    inspector = inspect(db.engine) if (db := __import__("models").db) else None
    # Alternative: query langsung
    from models import db as _db
    inspector = inspect(_db.engine)
    tabels = inspector.get_table_names()
    expected = {
        "admin", "warga", "kategori", "barang",
        "peminjaman", "detail_peminjaman", "notifikasi",
    }
    assert expected.issubset(set(tabels)), (
        f"Tabel hilang: {expected - set(tabels)}"
    )


def test_admin_password_hashing(sample_admin):
    """Admin.set_password harus menghash, check_password harus verify."""
    assert sample_admin.password_hash != "password123"  # tidak plain
    assert sample_admin.check_password("password123") is True
    assert sample_admin.check_password("salah") is False


def test_polymorphism_denda_berbeda_per_kategori(app, sample_barang):
    """Barang.hitung_denda harus menghasilkan nilai berbeda per kategori."""
    hari = 5
    denda_list = [b.hitung_denda(hari) for b in sample_barang]
    # 3 barang → 3 nilai denda berbeda (karena tarif berbeda)
    assert len(set(denda_list)) == 3, (
        f"Denda seharusnya unik per kategori: {denda_list}"
    )
    # Proyektor (Elektronik, 5000) → 5 * 5000 = 25000
    assert denda_list[0] == 25000
    # Kursi (Furniture, 2000) → 5 * 2000 = 10000
    assert denda_list[1] == 10000
    # Tenda (Peralatan, 3000) → 5 * 3000 = 15000
    assert denda_list[2] == 15000


def test_denda_nol_jika_tepat_waktu(app, sample_barang):
    """hitung_denda(0) atau negatif harus return 0."""
    for b in sample_barang:
        assert b.hitung_denda(0) == 0
        assert b.hitung_denda(-5) == 0


def test_barang_base_contract_via_mixin(app):
    """BarangBase (mixin) harus raise NotImplementedError jika tidak di-override."""
    from models.base import BarangBase

    # Class dummy tanpa override
    class BarangDummy(BarangBase):
        pass

    dummy = BarangDummy()
    try:
        dummy.hitung_denda(1)
        assert False, "Harus raise NotImplementedError"
    except NotImplementedError:
        pass

    try:
        dummy.get_info()
        assert False, "Harus raise NotImplementedError"
    except NotImplementedError:
        pass


def test_unique_username_di_enforce(app, sample_admin):
    """Username duplikat harus ditolak DB."""
    from models.admin import Admin
    from sqlalchemy.exc import IntegrityError

    dup = Admin(username="admin_test", password_hash="x", nama_lengkap="Dup")
    import uuid
    dup.id = str(uuid.uuid4())
    from models import db
    db.session.add(dup)
    try:
        db.session.commit()
        assert False, "Harus raise IntegrityError"
    except IntegrityError:
        db.session.rollback()


def test_warga_state_transitions_terkontrol(sample_warga):
    """Warga.verifikasi/tolak/blokir/aktifkan_kembali harus ikut state machine."""
    # Warga awalnya 'aktif' (via fixture)
    assert sample_warga.status == "aktif"

    # aktif → blokir
    sample_warga.blokir()
    assert sample_warga.status == "diblokir"

    # diblokir → aktif
    sample_warga.aktifkan_kembali()
    assert sample_warga.status == "aktif"

    # Transisi ilegal dari 'aktif' → 'aktif' (verifikasi) harus gagal
    import pytest
    with pytest.raises(ValueError):
        sample_warga.verifikasi("newpass")
