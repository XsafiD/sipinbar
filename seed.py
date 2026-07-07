"""
seed.py — Skrip untuk inisialisasi database + data awal SIPINBAR.

Melakukan 3 hal:
  1. `db.create_all()` — buat 7 tabel sesuai skema
  2. Insert admin default (username: `admin`, password: `admin123`)
  3. Insert 3 kategori default + contoh barang awal (untuk demo)

Penggunaan:
    python seed.py             # semua data
    python seed.py --no-barang # tanpa contoh barang
    python seed.py --reset     # hapus semua data lalu re-seed (hati-hati!)

Catatan: File `.db` TIDAK di-commit ke git (lihat .gitignore).
Jalankan sekali setelah clone / pull pertama.
"""
import argparse
import sys

from app import create_app
from models import db
from models.admin import Admin
from models.warga import Warga
from models.barang import Barang, Kategori


# ── Data Seed Konstan ─────────────────────────────────────────
ADMIN_DEFAULT = {
    "username": "admin",
    "password_plain": "admin123",  # UBAH DI PRODUCTION!
    "nama_lengkap": "Administrator Desa",
    "role": "admin",
}

KATEGORI_DEFAULT = [
    {
        "nama": "Elektronik",
        "tarif_denda_per_hari": 5000,
        "deskripsi": "Barang elektronik (proyektor, sound system, dll)",
    },
    {
        "nama": "Furniture",
        "tarif_denda_per_hari": 2000,
        "deskripsi": "Perabot (kursi, meja, lemari)",
    },
    {
        "nama": "Peralatan",
        "tarif_denda_per_hari": 3000,
        "deskripsi": "Peralatan masak, tenda, dll",
    },
]

# Format: (nama, kategori_nama, jumlah_unit, kondisi)
BARANG_CONTOH = [
    ("Proyektor Epson", "Elektronik", 2, "baik"),
    ("Sound System Portable", "Elektronik", 1, "baik"),
    ("Kursi Lipat", "Furniture", 50, "baik"),
    ("Tenda Regu 6x6", "Peralatan", 3, "baik"),
    ("Kompor Gas Besar", "Peralatan", 2, "perlu_perbaikan"),
]


def seed_admin() -> Admin:
    """Insert admin default jika belum ada."""
    existing = Admin.query.filter_by(username=ADMIN_DEFAULT["username"]).first()
    if existing:
        print(f"  [skip] Admin '{existing.username}' sudah ada")
        return existing

    admin = Admin(
        username=ADMIN_DEFAULT["username"],
        nama_lengkap=ADMIN_DEFAULT["nama_lengkap"],
        role=ADMIN_DEFAULT["role"],
        is_aktif=True,
    )
    admin.set_password(ADMIN_DEFAULT["password_plain"])
    db.session.add(admin)
    db.session.commit()
    print(
        f"  [ok] Admin '{admin.username}' dibuat "
        f"(password: '{ADMIN_DEFAULT['password_plain']}' — UBAH DI PRODUCTION!)"
    )
    return admin


def seed_kategori() -> dict:
    """Insert kategori default. Return mapping nama → kategori instance."""
    result = {}
    for data in KATEGORI_DEFAULT:
        existing = Kategori.query.filter_by(nama=data["nama"]).first()
        if existing:
            print(f"  [skip] Kategori '{existing.nama}' sudah ada")
            result[data["nama"]] = existing
            continue
        kat = Kategori(**data)
        db.session.add(kat)
        db.session.commit()
        print(f"  [ok] Kategori '{kat.nama}' (denda {kat.tarif_denda_per_hari}/hari)")
        result[data["nama"]] = kat
    return result


def seed_barang(kategori_map: dict) -> int:
    """Insert contoh barang. Return jumlah barang yang di-insert."""
    inserted = 0
    for nama, kat_nama, jumlah, kondisi in BARANG_CONTOH:
        # Skip jika barang dengan nama yang sama sudah ada & belum dihapus
        existing = (
            Barang.query.filter_by(nama=nama)
            .filter(Barang.deleted_at.is_(None))
            .first()
        )
        if existing:
            print(f"  [skip] Barang '{existing.nama}' sudah ada")
            continue

        barang = Barang(
            nama=nama,
            kategori_id=kategori_map[kat_nama].id,
            jumlah_unit=jumlah,
            kondisi=kondisi,
            status="tersedia",
        )
        db.session.add(barang)
        inserted += 1
        print(f"  [ok] Barang '{barang.nama}' ({kat_nama}, {jumlah} unit)")
    db.session.commit()
    return inserted


def reset_database(app) -> None:
    """Hapus SEMUA data dari semua tabel. Hati-hati!"""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        print("  [ok] Semua tabel di-drop & di-recreate")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed SIPINBAR database")
    parser.add_argument(
        "--no-barang",
        action="store_true",
        help="Lewati insert contoh barang",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DROP semua tabel sebelum seed (DESTRUKTIF!)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print("═══════════════════════════════════════════════════════")
        print("  SIPINBAR Database Seeder")
        print("═══════════════════════════════════════════════════════")

        # 1. Buat tabel
        print("\n[1/4] Membuat tabel (db.create_all)...")
        db.create_all()
        print("  [ok] Skema database siap")

        # 2. Reset (opsional)
        if args.reset:
            print("\n[!] RESET MODE: menghapus semua data...")
            reset_database(app)

        # 3. Seed admin
        print("\n[2/4] Seed admin default...")
        seed_admin()

        # 4. Seed kategori
        print("\n[3/4] Seed kategori default...")
        kategori_map = seed_kategori()

        # 5. Seed barang contoh
        if not args.no_barang:
            print("\n[4/4] Seed contoh barang...")
            total = seed_barang(kategori_map)
            print(f"  Total {total} barang baru ditambahkan")
        else:
            print("\n[4/4] Skip barang (--no-barang)")

        # Ringkasan
        print("\n═══════════════════════════════════════════════════════")
        print("  RINGKASAN DATA")
        print("═══════════════════════════════════════════════════════")
        print(f"  Admin       : {Admin.query.count()}")
        print(f"  Warga       : {Warga.query.count()}")
        print(f"  Kategori    : {Kategori.query.count()}")
        print(f"  Barang      : {Barang.query.filter(Barang.deleted_at.is_(None)).count()}")
        print("\n  Selesai. Jalankan: flask run")
        print("═══════════════════════════════════════════════════════\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
