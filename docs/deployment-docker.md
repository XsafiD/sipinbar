# Deployment Docker SIPINBAR — Transfer ke Server Ubuntu

> **Tujuan:** Memindahkan aplikasi SIPINBAR yang sudah dibungkus Docker dari mesin
> dev ke server Ubuntu untuk demo/grading.

---

## 1. Eksekusi Cepat (TL;DR)

```bash
# Di mesin dev (folder tugas-besar/):
zip -r sipinbar-docker.zip . \
  -x "venv/*" ".git/*" "__pycache__/*" ".pytest_cache/*" ".mypy_cache/*" \
     "tests/*" "docs/*" "docs-sipinbar/*" "ui-referensi-sipinbar/*" \
     "instance/*" "*.pyc" ".env" ".env.example" ".flaskenv" \
     ".flake8" "mypy.ini" "*.md" "*.pdf" ".gitignore" ".gitmessage"

# Transfer ke server:
scp sipinbar-docker.zip user@SERVER_IP:~/

# Di server Ubuntu:
ssh user@SERVER_IP
sudo apt update && sudo apt install -y docker.io docker-compose-v2 unzip
sudo usermod -aG docker $USER && newgrp docker
unzip sipinbar-docker.zip -d sipinbar && cd sipinbar
docker compose up -d --build
# Akses: http://SERVER_IP:5000
```

---

## 2. Apa Saja yang Perlu Ditransfer

### 2.1 Wajib (kode aplikasi + Docker)

| File/Folder | Ukuran | Fungsi |
|-------------|--------|--------|
| `app.py` | ~8 KB | Entry point Flask + factory `create_app()` + endpoint `/health` |
| `config.py` | ~3 KB | Konfigurasi (baca env vars: SECRET_KEY, DATABASE_PATH, dll.) |
| `seed.py` | ~27 KB | Database seeder (idempoten — aman dijalankan berulang) |
| `requirements.txt` | ~1 KB | Daftar dependency Python untuk `pip install` |
| `controllers/` | ~148 KB | Blueprint Flask (auth, barang, peminjaman, dashboard, dll.) |
| `models/` | ~136 KB | Model SQLAlchemy (Admin, Warga, Barang, Peminjaman, dll.) |
| `services/` | ~172 KB | Business logic layer |
| `templates/` | ~240 KB | Jinja2 HTML templates |
| `static/` | ~160 KB | CSS, JS, dan folder `img/` untuk upload gambar |
| `Dockerfile` | ~1.2 KB | Build image `python:3.12-slim` |
| `docker-compose.yml` | ~1.6 KB | Orkestrasi: port, volume, env, healthcheck |
| `.dockerignore` | ~1 KB | Filter file saat build image |

### 2.2 Data Demo (pre-seeded) — Opsional tapi disarankan

| File | Ukuran | Alasan menyertakan |
|------|--------|--------------------|
| `database/sipinbar.db` | 131 KB | Data demo sudah siap. Tanpa ini, `seed.py` akan recreate di first-run (tetap works, tapi seed butuh ~3 detik tambahan) |
| `static/img/0ec55988500f4677b17ffec83145b285.jpg` | 125 KB | Gambar contoh hasil upload testing (diperlukan jika ingin tampil di detail barang tertentu) |

> **Catatan:** Jika ingin demo "fresh" (biarkan seed.py yang bangun data dari nol),
> hapus kedua file di atas dari zip. Aplikasi tetap berjalan normal — `seed.py`
> otomatis menjalan saat container start.

### 2.3 Yang TIDAK Perlu Ditransfer (Aman Dilewati)

| Folder/File | Ukuran Dilewati | Alasan |
|-------------|-----------------|--------|
| `venv/` | **106 MB** | Virtual env local. Container akan install ulang dependency via `pip install -r requirements.txt` |
| `.git/` | bervariasi | Version history tidak dibutuhkan untuk deployment |
| `tests/` | 3.3 MB | Unit/integration test — tidak dipakai di runtime |
| `docs/` | 92 KB | Dokumen PRD/SRS — tidak dipakai container |
| `docs-sipinbar/` | 684 KB | Dokumentasi tambahan |
| `ui-referensi-sipinbar/` | 492 KB | Referensi UI untuk development |
| `__pycache__/`, `.pytest_cache/`, `.mypy_cache/` | ~20 MB | Cache Python, pytest, mypy — di-regenerate |
| `instance/` | 4 KB | Tidak dipakai (config pakai absolute path) |
| `.env`, `.env.example`, `.flaskenv` | kecil | Secret & Flask config diatur via `docker-compose.yml` environment |
| `.flake8`, `mypy.ini` | kecil | Dev tooling config |
| `*.md`, `*.pdf` | ~6.5 MB | Dokumentasi (README, PRD, SRS, Instruksi) |
| `.gitignore`, `.gitmessage` | kecil | Git config |

**Estimasi ukuran zip akhir:** ~1.5–2 MB (sangat kecil, transfer cepat).

---

## 3. Langkah-Langkah Detail

### Step 1 — Buat Zip di Mesin Dev

```bash
cd /path/ke/04_TUGAS/tugas-besar

zip -r sipinbar-docker.zip . \
  -x "venv/*" \
     ".git/*" \
     "__pycache__/*" \
     ".pytest_cache/*" \
     ".mypy_cache/*" \
     "tests/*" \
     "docs/*" \
     "docs-sipinbar/*" \
     "ui-referensi-sipinbar/*" \
     "instance/*" \
     "*.pyc" \
     "*.pyo" \
     ".env" \
     ".env.example" \
     ".flaskenv" \
     ".flake8" \
     "mypy.ini" \
     "*.md" \
     "*.pdf" \
     ".gitignore" \
     ".gitmessage"
```

**Verifikasi isi zip** (harusnya ~15 file/folder, bukan ratusan):

```bash
unzip -l sipinbar-docker.zip | head -40
unzip -l sipinbar-docker.zip | tail -5    # lihat total size & jumlah entries
```

**Isi zip yang diharapkan:**
```
app.py
config.py
seed.py
requirements.txt
Dockerfile
docker-compose.yml
.dockerignore
controllers/        (recursively)
models/             (recursively)
services/           (recursively)
templates/          (recursively)
static/css/style.css
static/js/app.js
static/img/.gitkeep
static/img/0ec55988500f4677b17ffec83145b285.jpg   (opsional)
database/sipinbar.db                                (opsional)
```

### Step 2 — Alternatif: `tar.gz` (lebih efisien untuk transfer Unix→Unix)

```bash
cd /path/ke/04_TUGAS/tugas-besar

tar --exclude='./venv' \
    --exclude='./.git' \
    --exclude='*/__pycache__' \
    --exclude='./.pytest_cache' \
    --exclude='./.mypy_cache' \
    --exclude='./tests' \
    --exclude='./docs' \
    --exclude='./docs-sipinbar' \
    --exclude='./ui-referensi-sipinbar' \
    --exclude='./instance' \
    --exclude='*.pyc' \
    --exclude='./.env' \
    --exclude='./.env.example' \
    --exclude='./.flaskenv' \
    --exclude='./.flake8' \
    --exclude='./mypy.ini' \
    --exclude='*.md' \
    --exclude='*.pdf' \
    --exclude='./.gitignore' \
    --exclude='./.gitmessage' \
    -czf sipinbar-docker.tar.gz .

ls -lh sipinbar-docker.tar.gz    # ~1.5 MB
```

### Step 3 — Transfer ke Server

**Opsi A: `scp` (paling simple)**
```bash
scp sipinbar-docker.zip user@SERVER_IP:~/
```

**Opsi B: `rsync` (lebih cepat, support resume)**
```bash
rsync -avz --progress sipinbar-docker.zip user@SERVER_IP:~/
```

**Opsi C: Jika server di port SSH non-default**
```bash
scp -P 2222 sipinbar-docker.zip user@SERVER_IP:~/
# atau
rsync -avz -e "ssh -p 2222" sipinbar-docker.zip user@SERVER_IP:~/
```

---

## 4. Setup di Server Ubuntu

### Step 4 — Install Docker (jika belum)

```bash
ssh user@SERVER_IP

# Cek apakah Docker sudah terinstall
docker --version
docker compose version

# Jika belum, install:
sudo apt update
sudo apt install -y docker.io docker-compose-v2 unzip

# Tambahkan user ke group docker (agar tidak perlu sudo setiap kali)
sudo usermod -aG docker $USER
newgrp docker    # reload group tanpa logout

# Verifikasi (tanpa sudo)
docker run hello-world
```

> **Catatan versi:** Docker Engine 20.10+ dan Docker Compose v2 (plugin `docker compose`,
> BUKAN `docker-compose` legacy) diperlukan karena `docker-compose.yml` pakai format
> schema terbaru.

### Step 5 — Ekstrak & Jalankan

```bash
# Ekstrak
cd ~
unzip sipinbar-docker.zip -d sipinbar
cd sipinbar

# Verifikasi struktur
ls -la
# Harus terlihat: Dockerfile, docker-compose.yml, app.py, requirements.txt, dll.

# Build image + jalankan container di background
docker compose up -d --build

# Tunggu ~20-30 detik (first run: seed.py + Flask boot)
# Lalu cek status
docker compose ps
docker compose logs -f sipinbar    # Ctrl+C untuk keluar dari log
```

### Step 6 — Buka Port Firewall (jika ufw aktif)

```bash
sudo ufw status
# Jika "Status: active", izinkan port 5000:
sudo ufw allow 5000/tcp
sudo ufw reload
```

---

## 5. Verifikasi Deployment

### Step 5.1 — Health Check (dari server)

```bash
curl http://localhost:5000/health
# Expected: {"app":"sipinbar","status":"ok","version":"1.0.0-rc"}
```

### Step 5.2 — Akses dari Browser Eksternal

Buka di browser: `http://SERVER_IP:5000`

- Login admin: `admin` / `admin123`
- Login warga demo: NIK `3201010101900001` / `warga123` (Budi Santoso)

### Step 5.3 — Cek Status Container

```bash
docker ps
# STATUS harus: "Up X minutes (healthy)"

docker inspect --format='{{.State.Health.Status}}' sipinbar
# Expected: healthy
```

### Step 5.4 — Cek Data Demo

```bash
docker compose logs sipinbar | grep -A 10 "RINGKASAN DATA"
# Harus terlihat:
#   Admin       : 1
#   Warga       : 7
#   Kategori    : 3
#   Barang      : 12
#   Peminjaman  : 8
#   Notifikasi  : 5
```

---

## 6. Operasional & Maintenance

### Command Sehari-hari

| Aksi | Command |
|------|---------|
| Lihat log real-time | `docker compose logs -f sipinbar` |
| Stop container | `docker compose down` |
| Start lagi (data tetap) | `docker compose up -d` |
| Rebuild setelah ubah kode | `docker compose up -d --build` |
| Restart container | `docker compose restart` |
| Masuk ke container (debug) | `docker compose exec sipinbar bash` |
| Jalankan pengingat H-1 manual | `docker compose exec sipinbar flask send-reminders` |
| Hapus container + image (reset total) | `docker compose down --rmi all` ⚠️ |

### Lokasi Data di Server

```
~/sipinbar/
├── database/
│   └── sipinbar.db          ← data SQLite (persistent via bind mount)
├── static/
│   └── img/                 ← upload gambar barang (persistent via bind mount)
├── app.py, Dockerfile, ...
```

> **Backup:** cukup copy folder `database/` dan `static/img/` untuk membackup
> semua data aplikasi.

---

## 7. Troubleshooting

### Masalah: Port 5000 sudah dipakai

```bash
# Cek apa yang pakai port 5000
sudo ss -tulpn | grep :5000
# atau
sudo lsof -i :5000
```

**Solusi:** ubah mapping port di `docker-compose.yml`:
```yaml
ports:
  - "5001:5000"    # akses via http://SERVER_IP:5001
```

### Masalah: `Permission denied` saat container menulis DB/upload

Penyebab: bind mount folder `database/` atau `static/img/` tidak writable oleh
container yang berjalan sebagai root.

**Solusi:**
```bash
# Di server, ubah ownership folder bind mount
sudo chown -R $USER:$USER database/ static/
# Atau alternatif: chmod ke 777 (kurang aman, tapi works untuk demo)
sudo chmod -R 777 database/ static/
docker compose restart
```

### Masalah: File `.db` jadi root-owned setelah dibuat container

```bash
# Hapus dengan sudo (memang behaviour Docker bind mount sebagai root)
sudo rm database/sipinbar.db
docker compose down && docker compose up -d
# Container akan buat file baru via seed.py
```

### Masalah: Container status `(unhealthy)`

```bash
# Cek log healthcheck
docker inspect --format='{{json .State.Health}}' sipinbar | jq

# Kemungkinan penyebab:
# 1. Flask belum siap saat healthcheck jalan → tunggu start_period (30s)
# 2. Endpoint /health error → cek docker compose logs sipinbar
# 3. Python urllib gagal resolve localhost → coba gunakan 127.0.0.1 di healthcheck
```

### Masalah: Tailwind CSS tidak load (halaman polos tanpa style)

Penyebab: server tidak ada internet untuk load `cdn.tailwindcss.com`.

**Solusi sementara:** app tetap berfungsi, hanya tanpa styling. Untuk production,
bundle Tailwind secara lokal (di luar scope demo ini).

### Masalah: `docker compose: command not found`

```bash
# Install plugin compose v2
sudo apt install -y docker-compose-v2

# Atau verifikasi plugin terpasang
docker compose version    # bukan "docker-compose version"
```

---

## 8. Checklist Final Sebelum Demo

- [ ] Zip berisi ~15 entries (bukan ratusan file dari `venv/`)
- [ ] Ukuran zip < 5 MB
- [ ] Docker & Docker Compose v2 terinstall di server
- [ ] Port 5000 tidak konflik (`ss -tulpn | grep :5000` kosong)
- [ ] Firewall mengizinkan port 5000 (jika ufw aktif)
- [ ] `docker compose up -d --build` sukses tanpa error
- [ ] `curl http://localhost:5000/health` returns `{"status":"ok"}`
- [ ] Browser eksternal bisa akses `http://SERVER_IP:5000`
- [ ] Login admin (`admin`/`admin123`) redirect ke dashboard
- [ ] Dashboard menampilkan 12 barang, 7 warga, 8 peminjaman
- [ ] Container status `(healthy)` setelah 60 detik

---

## 9. Catatan Keamanan untuk Demo di Server Publik

Jika server dapat diakses dari internet (bukan LAN lokal):

1. **Ganti `SECRET_KEY`** di `docker-compose.yml`:
   ```yaml
   environment:
     SECRET_KEY: <string-acak-64-char>
   ```
   Generate dengan: `python3 -c "import secrets; print(secrets.token_hex(32))"`

2. **Pertimbangkan reverse proxy** (nginx/caddy) dengan HTTPS untuk produksi.

3. **Flask dev server tidak untuk produksi.** Untuk deploy sungguhan, ganti CMD
   di Dockerfile ke gunicorn:
   ```
   pip install gunicorn    # tambah ke requirements.txt
   CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:create_app()"]
   ```

4. **Demo credentials** (`admin`/`admin123`, `warga123`) HARUS diganti sebelum
   paparan ke publik.

---

*Dokumen ini berdasarkan setup Docker SIPINBAR — 3 file: Dockerfile,
docker-compose.yml, .dockerignore. Lihat README.md untuk dokumentasi aplikasi
lengkap.*
