# SIPINBAR — Sistem Informasi Peminjaman Barang Desa

> Aplikasi web untuk digitalisasi siklus peminjaman barang inventaris desa
> (proyektor, kursi, tenda, sound system, peralatan masak, dll) — dari pencatatan
> manual menggunakan buku tulis menjadi sistem terpusat yang dapat diakses dari browser.

**Mata Kuliah** — Pemrograman Berorientasi Object (OOP) · Semester 4 Informatika
**Tech Stack** — Python 3.12 · Flask 3.0 · Flask-SQLAlchemy · SQLite · Tailwind CSS · Jinja2
**Versi** — 0.1.0 (M1 — Foundation)

---

## Daftar Isi

1. [Latar Belakang](#1-latar-belakang)
2. [Fitur Utama](#2-fitur-utama)
3. [Teknologi & Arsitektur](#3-teknologi--arsitektur)
4. [Struktur Project](#4-struktur-project)
5. [Quick Start](#5-quick-start)
6. [Database](#6-database)
7. [Implementasi 4 Pilar OOP](#7-implementasi-4-pilar-oop)
8. [Testing](#8-testing)
9. [Roadmap & Status](#9-roadmap--status)
10. [Tim Pengembang](#10-tim-pengembang)
11. [Dokumentasi Terkait](#11-dokumentasi-terkait)

---

## 1. Latar Belakang

Pencatatan peminjaman barang inventaris di balai desa masih dilakukan secara
manual menggunakan buku tulis. Praktik ini menyebabkan beberapa masalah:

- **Data hilang** — buku fisik mudah rusak / hilang
- **Konflik jadwal** — double-booking karena tidak ada pengecekan real-time
- **Keterlambatan pengembalian** sulit dilacak
- **Tidak ada rekam jejak historis** untuk perencanaan anggaran

**SIPINBAR** menggantikan proses manual ini dengan platform digital yang
mengelola seluruh siklus peminjaman: pencatatan inventaris, pengajuan,
persetujuan admin, pengembalian, denda keterlambatan, hingga pelaporan.

---

## 2. Fitur Utama

| Modul | Fitur | Status |
|:---|:---|:---:|
| **Autentikasi** | Login/logout, registrasi warga, verifikasi admin, hashing password | M2 |
| **Inventaris** | CRUD barang, kategori, status ketersediaan, upload foto | M2 |
| **Peminjaman** | Ajukan pinjaman, setujui/tolak, kembalikan, validasi anti double-booking | M3 |
| **Pencarian** | Cari barang, filter kategori, cek ketersediaan | M2 |
| **Warga** | Registrasi, verifikasi, riwayat peminjaman | M2 |
| **Dashboard** | Statistik ringkas, peminjaman aktif, jumlah barang | M4 |
| **Notifikasi** | In-app notification pengingat pengembalian H-1 | M4 |
| **Laporan** | Laporan peminjaman per periode, ekspor sederhana | M4 |

**Pengguna target:**

- **Admin desa** — operator yang mengelola sistem & approve peminjaman
- **Warga desa** — peminjam yang mengajukan & melacak peminjaman
- **Kepala desa** — pengambil keputusan yang butuh ringkasan statistik

---

## 3. Teknologi & Arsitektur

### Tech Stack

| Lapisan | Teknologi | Alasan |
|:---|:---|:---|
| Bahasa | Python 3.12 | Sesuai mata kuliah OOP |
| Web framework | Flask 3.0 | Lightweight, fleksibel, cocok untuk skala kecil-menengah |
| ORM | Flask-SQLAlchemy 3.1 | Proteksi SQL injection, mapping OOP ke DB |
| Database | SQLite 3 | Embedded, tanpa server terpisah, portable |
| Form | Flask-WTF + WTForms | CSRF protection & validasi server-side |
| Template | Jinja2 | Bawaan Flask, komposisi layout via extends/include |
| Styling | Tailwind CSS | Utility-first, responsif mobile-first |
| Testing | pytest | Standar komunitas Python |

### Arsitektur: Model-Service-Controller (MSC)

Varian MVC yang memisahkan **business logic** (Service) dari **penanganan HTTP**
(Controller). Aturan disiplin:

- **Controller** tidak boleh akses Model langsung — harus via Service
- **Service** tidak boleh akses template — hanya return data
- **Model** tidak boleh mengandung business logic — hanya data + enkapsulasi

```
HTTP Request
    │
    ▼
Controller (Flask Blueprint)   ← routing, request parsing, response
    │
    ▼
Service (Business Logic)       ← validasi, aturan bisnis, orchestration
    │
    ▼
Model (SQLAlchemy ORM)         ← entitas DB, encapsulation, polymorphism
    │
    ▼
SQLite database
```

---

## 4. Struktur Project

```
sipinbar/
│
├── app.py                       # Entry point — Application Factory (create_app)
├── config.py                    # Konfigurasi (Config, TestConfig)
├── seed.py                      # Seeder: admin default + kategori + barang contoh
├── requirements.txt             # Daftar dependencies
│
├── .env.example                 # Template env vars (copy ke .env)
├── .flaskenv                    # FLASK_APP, FLASK_ENV
├── .gitignore                   # File yang diabaikan git
├── .gitmessage                  # Template format commit message
│
├── models/                      # ══ MODEL LAYER ══
│   ├── __init__.py              # Instance SQLAlchemy + import semua model
│   ├── base.py                  # ABC/Mixin: BarangBase, NotifikasiBase, LaporanBase
│   ├── admin.py                 # Class Admin
│   ├── warga.py                 # Class Warga
│   ├── barang.py                # Class Kategori + Barang
│   ├── peminjaman.py            # Class Peminjaman + DetailPeminjaman
│   ├── notifikasi.py            # Class Notifikasi + NotifikasiInApp
│   └── laporan.py               # Class LaporanPeminjaman + LaporanInventaris
│
├── services/                    # ══ SERVICE LAYER ══ (M2-M4)
├── controllers/                 # ══ CONTROLLER LAYER ══ (M2-M4)
│
├── templates/                   # ══ VIEW LAYER ══ (M2-M4)
│   ├── auth/ barang/ peminjaman/ warga/ laporan/ components/
│
├── static/                      # ══ ASSETS ══
│   ├── css/  js/  img/
│
├── database/                    # ══ DATABASE ══
│   └── sipinbar.db              # (auto-created, TIDAK di-commit)
│
├── tests/                       # ══ TESTING ══
│   ├── conftest.py              # Pytest fixtures
│   └── test_smoke.py            # Smoke test foundation
│
└── docs/                        # ══ DOKUMENTASI ══ (PRD, SRS, dll)
```

---

## 5. Quick Start

### Prasyarat

- Python **3.10+** (tested on 3.12)
- `pip`, `venv`

### Instalasi

```bash
# 1. Clone repository
git clone <repo-url>
cd sipinbar

# 2. Buat & aktifkan virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Siapkan environment variables
cp .env.example .env
# Edit SECRET_KEY di .env untuk production

# 5. Inisialisasi database + data awal
python seed.py

# 6. Jalankan aplikasi
flask run
# atau: python app.py

# 7. Buka browser
# http://127.0.0.1:5000/health
```

### Akun Default (setelah seed)

| Peran | Username | Password |
|:---|:---|:---|
| Admin | `admin` | `admin123` |

> **PENTING:** Ganti password admin default di production via interface admin
> atau dengan re-seed menggunakan `python seed.py --reset`.

### Perintah berguna

```bash
# Reset database (DESTRUKTIF — hapus semua data)
python seed.py --reset

# Seed tanpa contoh barang
python seed.py --no-barang

# Jalankan test suite
pytest tests/ -v

# Aktifkan debug mode
export FLASK_DEBUG=1
flask run
```

---

## 6. Database

### Skema Entitas (7 tabel)

```
admin                warga                kategori
─────                ─────                ────────
id (PK)              id (PK)              id (PK)
username (UNIQUE)    nik (UNIQUE)         nama (UNIQUE)
password_hash        password_hash        tarif_denda_per_hari
nama_lengkap         nama_lengkap         deskripsi
role                 alamat
is_aktif             telepon              ┌────────────────┐
last_login_at        rt_rw                │     barang     │
                     status               │ ────────────── │
                     verified_at          │ id (PK)        │
                                          │ nama           │
                     ┌──────────────┐     │ kategori_id FK─┼─► kategori.id
                     │  peminjaman  │     │ jumlah_unit    │
                     │ ──────────── │     │ kondisi        │
                     │ id (PK)      │     │ status         │
                     │ kode (UNIQ)  │     │ foto_path      │
                     │ warga_id  FK─┼─► warga.id         │ deleted_at (soft)
                     │ admin_id  FK─┼─► admin.id          └─────┬─────┘
                     │ tanggal_*    │           ▲                  │
                     │ status       │           │1:N               │
                     │ denda_total  │           │                  │
                     │ approved_at  │     ┌─────┴──────────────┐   │
                     └──────┬───────┘     │ detail_peminjaman  │   │
                            │1:N          │ ────────────────── │   │
                            ▼             │ id (PK)            │   │
                     ┌──────────────┐     │ peminjaman_id  FK──┼───┘
                     │ notifikasi   │     │ barang_id  FK──────┼───► barang.id
                     │ ──────────── │     │ jumlah             │
                     │ id (PK)      │     │ kondisi_kembali    │
                     │ peminjaman FK│     └────────────────────┘
                     │ warga_id  FK─┼─► warga.id
                     │ tipe         │
                     │ judul, pesan │
                     │ is_dibaca    │
                     └──────────────┘
```

### Naming Convention

- **Tabel**: singular noun, `snake_case` (contoh: `peminjaman`, `detail_peminjaman`)
- **Primary Key**: kolom `id` bertipe `VARCHAR(36)` (UUID v4 string)
- **Foreign Key**: `<tabel>_id` (contoh: `warga_id`, `kategori_id`)
- **Tanggal** (tanpa jam): prefix `tanggal_` (contoh: `tanggal_pinjam`)
- **Timestamp** (dengan jam): suffix `_at` (contoh: `created_at`, `approved_at`)
- **Boolean**: prefix `is_` (contoh: `is_aktif`, `is_dibaca`)
- **Uang**: `INTEGER` (Rupiah penuh), suffix `_rupiah` atau eksplisit satuan

### Integritas Data

- **Foreign Key** di-enforce via `PRAGMA foreign_keys = ON` (event listener SQLAlchemy)
- **UNIQUE constraint**: username, nik, nama kategori, kode_peminjaman, composite (peminjaman_id, barang_id)
- **CHECK constraint**: tarif >= 0, jumlah > 0, tanggal_kembali_rencana > tanggal_pinjam
- **Soft delete** di tabel `barang` (kolom `deleted_at`) untuk menjaga integritas transaksi historis

Detail lengkap di [`arsitektur-database-v1.0.0-sipinbar.md`](arsitektur-database-v1.0.0-sipinbar.md).

---

## 7. Implementasi 4 Pilar OOP

| Pilar | Lokasi Implementasi | Penjelasan |
|:---|:---|:---|
| **Encapsulation** | `Admin.set_password()` / `check_password()` <br> `Warga.verifikasi()` / `blokir()` / `aktifkan_kembali()` <br> `Barang.set_kondisi()` / `set_status()` <br> `Peminjaman.setujui()` / `tolak()` / `kembalikan()` | Atribut privat (`password_hash`), akses via method. Perubahan status hanya melalui method yang memvalidasi transisi state machine. |
| **Inheritance** | `Barang(db.Model, BarangBase)` <br> `NotifikasiInApp(NotifikasiBase)` <br> `LaporanPeminjaman(LaporanBase)` <br> `LaporanInventaris(LaporanBase)` | Subclass mewarisi kontrak dari ABC/Mixin. Barang mewarisi `db.Model` (SQLAlchemy) + `BarangBase` (interface). |
| **Polymorphism** | `Barang.hitung_denda(hari)` mendelegasikan ke `kategori.tarif_denda_per_hari` <br> `Peminjaman.hitung_denda()` menjumlahkan denda tiap item | Satu interface, perilaku beda per kategori. Contoh: denda 3 hari untuk Elektronik (Rp 15.000), Furniture (Rp 6.000), Peralatan (Rp 9.000). |
| **Abstraction** | `models/base.py` — `BarangBase`, `NotifikasiBase`, `LaporanBase` | Kontrak method antar modul. Developer cukup tahu signature method, tidak perlu tahu detail implementasi subclass. |

### Catatan teknis: Mixin vs ABC

`BarangBase` sengaja menggunakan **mixin pattern** (method raise
`NotImplementedError`) dan bukan `abc.ABCMeta`, karena `Barang` juga mewarisi
`db.Model` (SQLAlchemy) yang memiliki metaclass sendiri — menggunakan `ABC`
akan menyebabkan **metaclass conflict**. Kontrak tetap ter-enforce, hanya saja
di runtime (saat method dipanggil), bukan saat instantiation.

`NotifikasiBase` & `LaporanBase` tetap menggunakan `abc.ABC` murni karena
subclass-nya (NotifikasiInApp, LaporanPeminjaman, LaporanInventaris) bukan
db.Model — tidak ada konflik metaclass.

---

## 8. Testing

Test suite menggunakan **pytest** dengan in-memory SQLite untuk isolasi penuh.

### Fixtures tersedia (`tests/conftest.py`)

| Fixture | Peran |
|:---|:---|
| `app` | Flask app instance dengan TestConfig (in-memory DB) |
| `client` | Flask test client untuk HTTP request tanpa server jaringan |
| `runner` | Flask CLI test runner |
| `db_session` | Akses langsung SQLAlchemy session |
| `sample_admin` | Admin default (`username=admin_test`) |
| `sample_kategori` | 3 kategori (Elektronik, Furniture, Peralatan) |
| `sample_barang` | 3 barang contoh (1 per kategori) untuk test polymorphism |
| `sample_warga` | Warga dengan status `aktif` |

### Menjalankan test

```bash
pytest tests/ -v                # verbose
pytest tests/ -k "polymorphism" # filter by keyword
pytest tests/ --tb=short        # traceback ringkas
```

### Cakupan test saat ini (M1 — Foundation)

- Application factory & test client
- Pembuatan semua tabel via `db.create_all()`
- Password hashing (Werkzeug)
- Polymorphism denda per kategori
- Contract enforcement (NotImplementedError dari mixin)
- UNIQUE & FK constraint enforcement
- State machine warga (verifikasi → blokir → aktifkan)

---

## 9. Roadmap & Status

Mengikuti milestone yang didefinisikan di PRD:

| Milestone | Konten | Status |
|:---|:---|:---:|
| **M1 — Foundation** | Setup project, base class, config, database, app skeleton | ✅ **Selesai** |
| **M2 — Core Modules** | Autentikasi + Inventaris Barang | ⏳ Berikutnya |
| **M3 — Peminjaman** | Modul peminjaman & pengembalian | ⏳ |
| **M4 — UI & Reports** | Dashboard, laporan, notifikasi | ⏳ |
| **M5 — Integration** | Merge semua modul, testing, bug fixing | ⏳ |

Target rilis: **v1.0** — integrasi penuh + testing + bug fixing.

---

## 10. Tim Pengembang

| Nama | Peran | Modul |
|:---|:---|:---|
| **Lanjib** | Project Manager | M1 — Foundation |
| **Ficky** | UI/UX Designer | Desain UI/UX |
| **Dimas** | UI/UX Designer | Komponen & style guide |
| **Shohih** | Frontend Developer | Dashboard & komponen reusable |
| **Anwar** | Backend Developer | M2 — Autentikasi & Warga |
| **Luthfi** | Backend Developer | M2-M4 — Inventaris, Peminjaman, Laporan |

---

## 11. Dokumentasi Terkait

Dokumen lengkap (di luar repo, dikelola terpisah):

| Dokumen | Isi |
|:---|:---|
| `prd-v1.0.0-sipinbar.md` | Product Requirements Document — tujuan, user persona, FR/NFR, user stories |
| `srs-v1.0.0-sipinbar.md` | Software Requirements Specification — detail teknis |
| `arsitektur-database-v1.0.0-sipinbar.md` | Skema DB lengkap + naming convention |
| `struktur-folder-v1.0.0-sipinbar.md` | Struktur folder & pembagian file per developer |
| `ui-spec-v1.0.0-sipinbar.md` | Spec UI/UX & design system |
| `milestone-v1.0.0-sipinbar.md` | Timeline & milestone M1-M5 |
| `laporan-progress-v1.0.0-sipinbar.md` | Laporan progress untuk laporan kuliah |

---

## Kontribusi

Format commit mengikuti `.gitmessage`:

```
YYYY-MM-DD - Judul Commit Singkat

- Detail poin 1
- Detail poin 2
```

Aktifkan template ini otomatis:

```bash
git config commit.template .gitmessage
```

---

## Lisensi

Project tugas besar mata kuliah Pemrograman Berorientasi Object — tidak
untuk distribusi komersial.

---

*Dibuat untuk Tugas Besar Pemrograman Berorientasi Object — Semester 4 Informatika · 2026*
