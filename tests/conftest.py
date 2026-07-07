"""
tests/conftest.py — Pytest fixtures bersama untuk testing SIPINBAR.

Menyediakan:
  - `app`: Flask app instance dengan TestConfig (in-memory SQLite)
  - `client`: Flask test client untuk simulate HTTP request
  - `db_session`: SQLAlchemy session dengan in-memory DB, auto-cleanup
  - `sample_data`: Data contoh (admin, kategori, barang, warga) untuk test

Pattern: Setiap test mendapat fresh database (isolation penuh).
"""
import pytest

from app import create_app
from config import TestConfig
from models import db
from models.admin import Admin
from models.warga import Warga
from models.barang import Barang, Kategori


@pytest.fixture
def app():
    """
    Flask app instance dengan TestConfig (in-memory SQLite).

    Setiap test dapat fresh DB karena menggunakan `:memory:` SQLite.
    """
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Flask test client untuk simulate HTTP requests tanpa server jaringan."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Flask CLI test runner (untuk test custom CLI command)."""
    return app.test_cli_runner()


@pytest.fixture
def db_session(app):
    """Akses langsung SQLAlchemy session untuk test yang butuh DB manipulation."""
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def sample_admin(app):
    """Admin default untuk test."""
    admin = Admin(
        username="admin_test",
        nama_lengkap="Admin Test",
        role="admin",
        is_aktif=True,
    )
    admin.set_password("password123")
    db.session.add(admin)
    db.session.commit()
    return admin


@pytest.fixture
def sample_kategori(app):
    """3 kategori contoh (sesuai seed)."""
    data = [
        Kategori(nama="Elektronik", tarif_denda_per_hari=5000),
        Kategori(nama="Furniture", tarif_denda_per_hari=2000),
        Kategori(nama="Peralatan", tarif_denda_per_hari=3000),
    ]
    db.session.add_all(data)
    db.session.commit()
    return {k.nama: k for k in data}


@pytest.fixture
def sample_barang(app, sample_kategori):
    """Barang contoh untuk test polymorphism denda."""
    data = [
        Barang(nama="Proyektor", kategori_id=sample_kategori["Elektronik"].id, jumlah_unit=2),
        Barang(nama="Kursi Lipat", kategori_id=sample_kategori["Furniture"].id, jumlah_unit=10),
        Barang(nama="Tenda", kategori_id=sample_kategori["Peralatan"].id, jumlah_unit=3),
    ]
    db.session.add_all(data)
    db.session.commit()
    return data


@pytest.fixture
def sample_warga(app):
    """Warga aktif untuk test peminjaman."""
    warga = Warga(
        nik="1234567890123456",
        nama_lengkap="Warga Test",
        alamat="Jl. Test No. 1",
        telepon="081234567890",
        rt_rw="001/002",
        status="aktif",
    )
    warga.set_password("password123")
    db.session.add(warga)
    db.session.commit()
    return warga
