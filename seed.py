"""
seed.py — Skrip untuk inisialisasi database + data demo SIPINBAR.

Melakukan 5 hal:
  1. ``db.create_all()`` — buat 7 tabel sesuai skema
  2. Insert admin default (username: ``admin``, password: ``admin123``)
  3. Insert 3 kategori default + 12 barang contoh (beragam kategori & kondisi)
  4. Insert 7 warga demo (beragam status: aktif, menunggu, diblokir, ditolak)
  5. Insert 7 peminjaman demo (beragam status) + 5 notifikasi contoh

Penggunaan:
    python seed.py             # semua data (admin + kategori + barang + demo)
    python seed.py --no-barang # tanpa contoh barang (dan tanpa peminjaman/notif)
    python seed.py --no-demo   # tanpa data demo (warga/peminjaman/notifikasi)
    python seed.py --reset     # hapus semua data lalu re-seed (hati-hati!)

Akun demo (UBAH DI PRODUCTION!):
    Admin  : admin / admin123
    Warga  : NIK 3201010101900001 / warga123  (Budi Santoso — aktif)
             NIK 3201010202900002 / warga123  (Siti Aminah — aktif)
             NIK 3201010303900003 / warga123  (Ahmad Dahlan — aktif)
             NIK 3201010404900004 / warga123  (Dewi Lestari — aktif)

Catatan: File ``.db`` TIDAK di-commit ke git (lihat .gitignore).
Jalankan sekali setelah clone / pull pertama.
"""
import argparse
import sys
from datetime import date, timedelta
from typing import Optional

from app import create_app
from models import db
from models.admin import Admin
from models.warga import Warga
from models.barang import Barang, Kategori
from models.peminjaman import Peminjaman, DetailPeminjaman
from models.notifikasi import Notifikasi, NotifikasiInApp


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

# Format: dict dengan nama, kategori, jumlah_unit, kondisi, status, deskripsi
BARANG_CONTOH = [
    {
        "nama": "Proyektor Epson",
        "kategori": "Elektronik",
        "jumlah_unit": 2,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Proyektor LCD untuk presentasi & acara desa",
    },
    {
        "nama": "Sound System Portable",
        "kategori": "Elektronik",
        "jumlah_unit": 1,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Speaker aktif + mixer 8 channel",
    },
    {
        "nama": "Kursi Lipat",
        "kategori": "Furniture",
        "jumlah_unit": 50,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Kursi lipat plastik untuk acara massal",
    },
    {
        "nama": "Tenda Regu 6x6",
        "kategori": "Peralatan",
        "jumlah_unit": 3,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Tenda kapasitas 8-10 orang",
    },
    {
        "nama": "Kompor Gas Besar",
        "kategori": "Peralatan",
        "jumlah_unit": 2,
        "kondisi": "perlu_perbaikan",
        "status": "perbaikan",
        "deskripsi": "Kompor 4 tungku, regulator perlu ganti",
    },
    {
        "nama": "Meja Rapat",
        "kategori": "Furniture",
        "jumlah_unit": 5,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Meja lipat 180x60 cm",
    },
    {
        "nama": 'LCD Display 55"',
        "kategori": "Elektronik",
        "jumlah_unit": 1,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "TV LED 55 inch untuk display informasi",
    },
    {
        "nama": "Tenda Dome 4x4",
        "kategori": "Peralatan",
        "jumlah_unit": 4,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Tenda dome kapasitas 4-6 orang",
    },
    {
        "nama": "Lemari Arsip",
        "kategori": "Furniture",
        "jumlah_unit": 3,
        "kondisi": "perlu_perbaikan",
        "status": "perbaikan",
        "deskripsi": "Lemari arsip 4 laci, engsel longgar",
    },
    {
        "nama": "Mikrofon Nirkabel",
        "kategori": "Elektronik",
        "jumlah_unit": 2,
        "kondisi": "rusak",
        "status": "perbaikan",
        "deskripsi": "Mic wireless dual channel, receiver rusak",
    },
    {
        "nama": "Kursi Tamu Set",
        "kategori": "Furniture",
        "jumlah_unit": 2,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Set 1 sofa + 2 kursi tunggal",
    },
    {
        "nama": "Dispenser Air",
        "kategori": "Peralatan",
        "jumlah_unit": 2,
        "kondisi": "baik",
        "status": "tersedia",
        "deskripsi": "Dispenser galon 19 liter, hot & cold",
    },
]

# Password default untuk semua warga demo yang sudah terverifikasi
PASSWORD_WARGA_DEMO = "warga123"  # UBAH DI PRODUCTION!

# Format: dict dengan key, nik, nama_lengkap, alamat, telepon, rt_rw, status
WARGA_DEMO = [
    {
        "key": "budi",
        "nik": "3201010101900001",
        "nama_lengkap": "Budi Santoso",
        "alamat": "Jl. Melati No. 1, Dusun Krajan",
        "telepon": "081234560001",
        "rt_rw": "001/001",
        "status": "aktif",
    },
    {
        "key": "siti",
        "nik": "3201010202900002",
        "nama_lengkap": "Siti Aminah",
        "alamat": "Jl. Mawar No. 2, Dusun Krajan",
        "telepon": "081234560002",
        "rt_rw": "001/002",
        "status": "aktif",
    },
    {
        "key": "ahmad",
        "nik": "3201010303900003",
        "nama_lengkap": "Ahmad Dahlan",
        "alamat": "Jl. Anggrek No. 3, Dusun Sukamaju",
        "telepon": "081234560003",
        "rt_rw": "002/001",
        "status": "aktif",
    },
    {
        "key": "dewi",
        "nik": "3201010404900004",
        "nama_lengkap": "Dewi Lestari",
        "alamat": "Jl. Kenanga No. 4, Dusun Sukamaju",
        "telepon": "081234560004",
        "rt_rw": "002/002",
        "status": "aktif",
    },
    {
        "key": "joko",
        "nik": "3201010505900005",
        "nama_lengkap": "Joko Widodo",
        "alamat": "Jl. Dahlia No. 5, Dusun Mekarsari",
        "telepon": "081234560005",
        "rt_rw": "003/001",
        "status": "menunggu",
    },
    {
        "key": "rina",
        "nik": "3201010606900006",
        "nama_lengkap": "Rina Marlina",
        "alamat": "Jl. Flamboyan No. 6, Dusun Mekarsari",
        "telepon": "081234560006",
        "rt_rw": "003/002",
        "status": "diblokir",
    },
    {
        "key": "bambang",
        "nik": "3201010707900007",
        "nama_lengkap": "Bambang Susilo",
        "alamat": "Jl. Cempaka No. 7, Dusun Tegalrejo",
        "telepon": "081234560007",
        "rt_rw": "004/001",
        "status": "ditolak",
        "alasan_penolakan": "Data NIK tidak cocok dengan KTP yang dilampirkan",
    },
]


# ── Seed Functions ────────────────────────────────────────────
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


def seed_barang(kategori_map: dict) -> dict:
    """
    Insert contoh barang.

    Return mapping nama → Barang instance (hanya yang belum di-soft-delete).
    """
    result = {}
    for data in BARANG_CONTOH:
        # Skip jika barang dengan nama yang sama sudah ada & belum dihapus
        existing = (
            Barang.query.filter_by(nama=data["nama"])
            .filter(Barang.deleted_at.is_(None))
            .first()
        )
        if existing:
            print(f"  [skip] Barang '{existing.nama}' sudah ada")
            result[data["nama"]] = existing
            continue

        barang = Barang(
            nama=data["nama"],
            kategori_id=kategori_map[data["kategori"]].id,
            jumlah_unit=data["jumlah_unit"],
            kondisi=data["kondisi"],
            status=data["status"],
            deskripsi=data.get("deskripsi"),
        )
        db.session.add(barang)
        db.session.commit()
        result[data["nama"]] = barang
        print(
            f"  [ok] Barang '{barang.nama}' "
            f"({data['kategori']}, {data['jumlah_unit']} unit, {data['kondisi']})"
        )
    return result


def seed_warga() -> dict:
    """
    Insert warga demo dengan beragam status (aktif/menunggu/diblokir/ditolak).

    Status dicapai melalui controlled mutators (``verifikasi()``, ``tolak()``,
    ``blokir()``) untuk menghormati encapsulation & state transition rules.

    Return mapping key → Warga instance.
    """
    result = {}
    for data in WARGA_DEMO:
        # Skip jika NIK sudah ada
        existing = Warga.query.filter_by(nik=data["nik"]).first()
        if existing:
            print(f"  [skip] Warga NIK '{existing.nik}' sudah ada")
            result[data["key"]] = existing
            continue

        warga = Warga(
            nik=data["nik"],
            nama_lengkap=data["nama_lengkap"],
            alamat=data["alamat"],
            telepon=data["telepon"],
            rt_rw=data["rt_rw"],
        )
        db.session.add(warga)
        db.session.flush()  # dapat ID tanpa commit penuh

        # Transition ke status target via controlled mutators
        status = data["status"]
        if status == "aktif":
            warga.verifikasi(PASSWORD_WARGA_DEMO)
        elif status == "diblokir":
            # aktif dulu, lalu diblokir
            warga.verifikasi(PASSWORD_WARGA_DEMO)
            warga.blokir()
        elif status == "ditolak":
            warga.tolak(data.get("alasan_penolakan", "Ditolak oleh admin"))
        # status == "menunggu": tidak ada transisi (status default)

        result[data["key"]] = warga
        print(f"  [ok] Warga '{warga.nama_lengkap}' ({status})")

    db.session.commit()
    return result


def _create_peminjaman(
    kode: str,
    warga: Warga,
    items: list,
    tgl_pinjam: date,
    tgl_kembali_rencana: date,
    status: str,
    admin_id: str,
    alasan_penolakan: str = "",
    tanggal_kembali_aktual: Optional[date] = None,
) -> Peminjaman:
    """
    Buat peminjaman dengan status akhir yang diinginkan via state machine.

    Transisi dijalankan melalui method model (``setujui()``, ``tolak()``,
    ``mulai_pinjam()``, ``tandai_terlambat()``, ``kembalikan()``) sehingga
    invariant state machine & perhitungan denda (polymorphism) terjaga.

    Args:
        kode: Kode peminjaman (format PJM-YYYY-NNNN).
        warga: Instance Warga peminjam.
        items: List tuple (Barang, jumlah).
        tgl_pinjam: Tanggal mulai pinjam.
        tgl_kembali_rencana: Tanggal rencana pengembalian.
        status: Status akhir yang diinginkan.
        admin_id: ID admin untuk approval/rejection.
        alasan_penolakan: Alasan (wajib jika status == 'ditolak').
        tanggal_kembali_aktual: Tanggal pengembalian aktual
                                (wajib jika status == 'dikembalikan').

    Returns:
        Instance Peminjaman (sudah di-flush ke session, belum commit).
    """
    peminjaman = Peminjaman(
        kode_peminjaman=kode,
        warga_id=warga.id,
        tanggal_pinjam=tgl_pinjam,
        tanggal_kembali_rencana=tgl_kembali_rencana,
        status="diajukan",
    )
    db.session.add(peminjaman)
    db.session.flush()

    for barang, jumlah in items:
        detail = DetailPeminjaman(
            peminjaman_id=peminjaman.id,
            barang_id=barang.id,
            jumlah=jumlah,
        )
        db.session.add(detail)
    db.session.flush()

    # Transition via state machine methods (respects encapsulation)
    if status == "diajukan":
        pass  # sudah diajukan
    elif status == "disetujui":
        peminjaman.setujui(admin_id)
    elif status == "dipinjam":
        peminjaman.setujui(admin_id)
        peminjaman.mulai_pinjam()
    elif status == "terlambat":
        peminjaman.setujui(admin_id)
        peminjaman.mulai_pinjam()
        peminjaman.tandai_terlambat()
    elif status == "dikembalikan":
        peminjaman.setujui(admin_id)
        peminjaman.mulai_pinjam()
        peminjaman.kembalikan(tanggal_aktual=tanggal_kembali_aktual)
    elif status == "ditolak":
        peminjaman.tolak(admin_id, alasan_penolakan)
    else:
        raise ValueError(f"Status peminjaman tidak dikenal: {status}")

    return peminjaman


def seed_peminjaman(
    warga_map: dict, barang_map: dict, admin: Admin
) -> tuple:
    """
    Insert peminjaman demo di beragam status.

    Menggunakan tanggal relatif (timedelta dari hari ini) sehingga data
    selalu relevan kapan pun seed dijalankan.

    Return tuple (jumlah_inserted, list_peminjaman_created).
    """
    today = date.today()
    year = today.year
    prefix = f"PJM-{year}-"

    # Spec peminjaman: tanggal relatif terhadap hari ini
    specs = [
        {
            "kode": f"{prefix}0001",
            "warga_key": "budi",
            "items": [("Proyektor Epson", 1)],
            "tgl_pinjam": today + timedelta(days=3),
            "tgl_kembali": today + timedelta(days=6),
            "status": "diajukan",
            "catatan": "Untuk presentasi rapat BKD",
        },
        {
            "kode": f"{prefix}0002",
            "warga_key": "siti",
            "items": [("Kursi Lipat", 10)],
            "tgl_pinjam": today - timedelta(days=3),
            "tgl_kembali": today + timedelta(days=2),
            "status": "dipinjam",
            "catatan": "Acara pengajian RT 001",
        },
        {
            "kode": f"{prefix}0003",
            "warga_key": "ahmad",
            "items": [("Tenda Regu 6x6", 2)],
            "tgl_pinjam": today - timedelta(days=10),
            "tgl_kembali": today - timedelta(days=2),
            "status": "terlambat",
            "catatan": "Camping pramuka desa",
        },
        {
            "kode": f"{prefix}0004",
            "warga_key": "budi",
            "items": [("Sound System Portable", 1)],
            "tgl_pinjam": today - timedelta(days=20),
            "tgl_kembali": today - timedelta(days=15),
            "tgl_kembali_aktual": today - timedelta(days=15),
            "status": "dikembalikan",
            "catatan": "Pelatihan kader posyandu",
        },
        {
            "kode": f"{prefix}0005",
            "warga_key": "dewi",
            "items": [('LCD Display 55"', 1)],
            "tgl_pinjam": today - timedelta(days=25),
            "tgl_kembali": today - timedelta(days=18),
            "tgl_kembali_aktual": today - timedelta(days=15),
            "status": "dikembalikan",
            "catatan": "Pameran UMKM desa",
        },
        {
            "kode": f"{prefix}0006",
            "warga_key": "siti",
            "items": [("Tenda Dome 4x4", 1)],
            "tgl_pinjam": today - timedelta(days=5),
            "tgl_kembali": today - timedelta(days=1),
            "status": "ditolak",
            "alasan": "Barang sedang dalam perbaikan",
            "catatan": "Acara arisan warga",
        },
        {
            "kode": f"{prefix}0007",
            "warga_key": "ahmad",
            "items": [("Meja Rapat", 2)],
            "tgl_pinjam": today + timedelta(days=1),
            "tgl_kembali": today + timedelta(days=4),
            "status": "disetujui",
            "catatan": "Workshop UMKM",
        },
    ]

    inserted = 0
    created = []
    for spec in specs:
        # Skip jika kode sudah ada (idempotent)
        if Peminjaman.query.filter_by(kode_peminjaman=spec["kode"]).first():
            print(f"  [skip] Peminjaman '{spec['kode']}' sudah ada")
            continue

        warga = warga_map.get(spec["warga_key"])
        if not warga:
            print(f"  [skip] Warga '{spec['warga_key']}' tidak ditemukan")
            continue

        # Build items list
        items = []
        for barang_nama, jumlah in spec["items"]:
            barang = barang_map.get(barang_nama)
            if not barang:
                print(f"  [skip] Barang '{barang_nama}' tidak ditemukan")
                continue
            items.append((barang, jumlah))

        if not items:
            continue

        peminjaman = _create_peminjaman(
            kode=spec["kode"],
            warga=warga,
            items=items,
            tgl_pinjam=spec["tgl_pinjam"],
            tgl_kembali_rencana=spec["tgl_kembali"],
            status=spec["status"],
            admin_id=admin.id,
            alasan_penolakan=spec.get("alasan", ""),
            tanggal_kembali_aktual=spec.get("tgl_kembali_aktual"),
        )
        if spec.get("catatan"):
            peminjaman.catatan = spec["catatan"]

        created.append(peminjaman)
        inserted += 1
        denda = peminjaman.total_denda_rupiah
        suffix = f" (denda Rp{denda:,})" if denda > 0 else ""
        print(f"  [ok] {peminjaman.kode_peminjaman} — {spec['status']}{suffix}")

    db.session.commit()
    return inserted, created


def seed_notifikasi(
    warga_map: dict, peminjaman_list: list
) -> int:
    """
    Insert notifikasi contoh untuk warga demo.

    Notifikasi dibuat via ``NotifikasiInApp`` (factory yang memenuhi kontrak
    ``NotifikasiBase`` ABC) sehingga validasi tipe & konten terjamin.

    Return jumlah notifikasi yang di-insert.
    """
    if not peminjaman_list:
        # Coba load peminjaman yang sudah ada di DB (idempotent run)
        peminjaman_list = Peminjaman.query.all()
        if not peminjaman_list:
            print("  [skip] Tidak ada peminjaman untuk dibuat notifikasi")
            return 0

    pjm_by_kode = {p.kode_peminjaman: p for p in peminjaman_list}
    today = date.today()
    year = today.year

    def _pjm(suffix: str) -> Peminjaman:
        return pjm_by_kode.get(f"PJM-{year}-{suffix}")

    # Build spec notifikasi (reference peminjaman by kode suffix)
    p1 = _pjm("0001")
    p2 = _pjm("0002")
    p3 = _pjm("0003")
    p6 = _pjm("0006")

    specs = []
    if p1:
        specs.append({
            "warga_key": "budi",
            "tipe": "info",
            "judul": "Pengajuan Diterima",
            "pesan": (
                f"Pengajuan {p1.kode_peminjaman} sedang menunggu "
                f"persetujuan admin."
            ),
            "peminjaman": p1,
            "dibaca": False,
        })
    if p2:
        specs.append({
            "warga_key": "siti",
            "tipe": "info",
            "judul": "Barang Diserahkan",
            "pesan": (
                f"Peminjaman {p2.kode_peminjaman} disetujui, "
                f"barang telah diserahkan."
            ),
            "peminjaman": p2,
            "dibaca": False,
        })
        specs.append({
            "warga_key": "siti",
            "tipe": "pengingat",
            "judul": "Pengingat Pengembalian",
            "pesan": (
                f"Peminjaman {p2.kode_peminjaman} jatuh tempo dalam 2 hari. "
                f"Jangan lupa kembalikan tepat waktu."
            ),
            "peminjaman": p2,
            "dibaca": False,
        })
    if p3:
        specs.append({
            "warga_key": "ahmad",
            "tipe": "peringatan",
            "judul": "Keterlambatan Pengembalian",
            "pesan": (
                f"Peminjaman {p3.kode_peminjaman} telah melewati jatuh tempo. "
                f"Segera kembalikan barang."
            ),
            "peminjaman": p3,
            "dibaca": False,
        })
    if p6:
        specs.append({
            "warga_key": "siti",
            "tipe": "peringatan",
            "judul": "Peminjaman Ditolak",
            "pesan": (
                f"Maaf, peminjaman {p6.kode_peminjaman} ditolak. "
                f"Alasan: {p6.alasan_penolakan}"
            ),
            "peminjaman": p6,
            "dibaca": True,
        })

    inserted = 0
    for spec in specs:
        warga = warga_map.get(spec["warga_key"])
        if not warga:
            continue

        # Skip jika notifikasi dengan judul sama sudah ada untuk warga ini
        existing = Notifikasi.query.filter_by(
            warga_id=warga.id, judul=spec["judul"]
        ).first()
        if existing:
            print(f"  [skip] Notifikasi '{spec['judul']}' sudah ada")
            continue

        builder = NotifikasiInApp(
            warga_id=warga.id,
            tipe=spec["tipe"],
            judul=spec["judul"],
            pesan=spec["pesan"],
            peminjaman_id=spec["peminjaman"].id if spec.get("peminjaman") else None,
        )
        notif = builder.kirim()

        # Tandai sudah dibaca untuk notifikasi tertentu
        if spec.get("dibaca"):
            notif.tandai_dibaca()

        inserted += 1
        print(
            f"  [ok] Notifikasi [{spec['tipe']}] '{spec['judul']}' "
            f"→ {warga.nama_lengkap}"
        )

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
        help="Lewati insert contoh barang (juga lewati peminjaman & notifikasi)",
    )
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="Lewati insert data demo (warga, peminjaman, notifikasi)",
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
        print("\n[1/7] Membuat tabel (db.create_all)...")
        db.create_all()
        print("  [ok] Skema database siap")

        # 2. Reset (opsional)
        if args.reset:
            print("\n[!] RESET MODE: menghapus semua data...")
            reset_database(app)

        # 3. Seed admin
        print("\n[2/7] Seed admin default...")
        admin = seed_admin()

        # 4. Seed kategori
        print("\n[3/7] Seed kategori default...")
        kategori_map = seed_kategori()

        # 5. Seed barang contoh
        barang_map = {}
        if not args.no_barang:
            print("\n[4/7] Seed contoh barang...")
            barang_map = seed_barang(kategori_map)
        else:
            print("\n[4/7] Skip barang (--no-barang)")

        # 6. Seed warga demo
        warga_map = {}
        if not args.no_demo:
            print("\n[5/7] Seed warga demo...")
            warga_map = seed_warga()
        else:
            print("\n[5/7] Skip warga demo (--no-demo)")

        # 7. Seed peminjaman demo
        peminjaman_created = []
        if not args.no_demo and not args.no_barang:
            print("\n[6/7] Seed peminjaman demo...")
            _, peminjaman_created = seed_peminjaman(
                warga_map, barang_map, admin
            )
        else:
            reason = "--no-demo" if args.no_demo else "--no-barang"
            print(f"\n[6/7] Skip peminjaman ({reason})")

        # 8. Seed notifikasi contoh
        if not args.no_demo and not args.no_barang:
            print("\n[7/7] Seed notifikasi contoh...")
            seed_notifikasi(warga_map, peminjaman_created)
        else:
            print("\n[7/7] Skip notifikasi (butuh peminjaman)")

        # Ringkasan
        print("\n═══════════════════════════════════════════════════════")
        print("  RINGKASAN DATA")
        print("═══════════════════════════════════════════════════════")
        print(f"  Admin       : {Admin.query.count()}")
        print(f"  Warga       : {Warga.query.count()}")
        print(f"  Kategori    : {Kategori.query.count()}")
        print(
            f"  Barang      : "
            f"{Barang.query.filter(Barang.deleted_at.is_(None)).count()}"
        )
        print(f"  Peminjaman  : {Peminjaman.query.count()}")
        print(f"  Notifikasi  : {Notifikasi.query.count()}")

        # Breakdown peminjaman per status (jika ada)
        if Peminjaman.query.count() > 0:
            print("\n  Peminjaman per status:")
            for status in (
                "diajukan", "disetujui", "dipinjam",
                "terlambat", "dikembalikan", "ditolak",
            ):
                count = Peminjaman.query.filter_by(status=status).count()
                if count > 0:
                    print(f"    {status:12s}: {count}")

        # Breakdown warga per status (jika ada)
        if Warga.query.count() > 0:
            print("\n  Warga per status:")
            for status in ("aktif", "menunggu", "ditolak", "diblokir"):
                count = Warga.query.filter_by(status=status).count()
                if count > 0:
                    print(f"    {status:12s}: {count}")

        print("\n  Selesai. Jalankan: flask run")
        print("═══════════════════════════════════════════════════════\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
