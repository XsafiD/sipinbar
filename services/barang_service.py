"""
services/barang_service.py — Business logic manajemen inventaris barang.

Mengelola:
  - CRUD barang (tambah, edit, hapus/soft-delete, list, detail)
  - Search & filter (per nama, per kategori)
  - Upload foto barang dengan validasi tipe & ukuran
  - Anti-hapus barang yang sedang dipinjam (BR-06)

Pilar OOP yang terlihat:
  - **Encapsulation**: transisi kondisi/status & soft-delete didelegasikan
    ke method model (`Barang.set_kondisi`, `Barang.set_status`,
    `Barang.soft_delete`). Service tidak pernah set `barang.status = ...`
    atau `barang.deleted_at = ...` secara langsung.
  - **Polymorphism**: ditegaskan via test — `Barang.hitung_denda()` menghasilkan
    denda berbeda per kategori (Elektronik 5000, Furniture 2000, Peralatan 3000)
    tanpa caller perlu tahu jenisnya.
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    barang di layer controller, menyembunyikan detail query SQLAlchemy &
    aturan bisnis (BR-06).

Refs: SRS §4.2, arsitektur-db §5.3 & §5.4, TODO T-BRG-01
"""
import os
import uuid
from typing import List, Optional

from flask import current_app

from models import db
from models.barang import Barang, Kategori, KONDISI_BARANG, STATUS_BARANG
from models.peminjaman import DetailPeminjaman, Peminjaman

# ── Aturan validasi upload foto (SRS §7 Keamanan & TODO §7.4 T-SEC-05) ──
ALLOWED_FOTO_EXT = frozenset({"png", "jpg", "jpeg", "webp"})
MAX_FOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

# Status peminjaman yang berarti barang "sedang dipakai" — wajib cegah hapus.
# (lihat BR-06). `dikembalikan`/`ditolak` TIDAK termasuk karena barang sudah bebas.
STATUS_BARANG_TERPAKAI = frozenset(
    {"diajukan", "disetujui", "dipinjam", "terlambat"}
)


class BarangService:
    """Service layer untuk modul Inventaris Barang."""

    # ── Create ────────────────────────────────────────────────
    def tambah(self, data: dict) -> Barang:
        """
        Tambah barang baru.

        Validasi:
          - ``nama`` wajib & unik (case-insensitive) di antara barang aktif
          - ``kategori_id`` wajib & harus merujuk kategori yang ada
          - ``jumlah`` wajib & > 0
          - ``kondisi`` (opsional) harus salah satu dari ``KONDISI_BARANG``

        Args:
            data: Dict berisi field barang. Field yang dikenali:
              ``nama``, ``kategori_id``, ``jumlah`` (atau ``jumlah_unit``),
              ``kondisi``, ``deskripsi``.

        Raises:
            ValueError: Jika validasi gagal.

        Returns:
            Instance ``Barang`` yang sudah tersimpan ke DB.
        """
        nama = (data.get("nama") or "").strip()
        if not nama:
            raise ValueError("Nama barang wajib diisi")

        kategori_id = (data.get("kategori_id") or "").strip()
        if not kategori_id:
            raise ValueError("Kategori wajib dipilih")
        if db.session.get(Kategori, kategori_id) is None:
            raise ValueError("Kategori tidak ditemukan")

        # Field jumlah boleh pakai key 'jumlah' atau 'jumlah_unit'
        jumlah_raw = data.get("jumlah", data.get("jumlah_unit"))
        try:
            jumlah = int(jumlah_raw) if jumlah_raw is not None else None
        except (TypeError, ValueError):
            raise ValueError("Jumlah unit harus berupa angka")
        if jumlah is None or jumlah <= 0:
            raise ValueError("Jumlah unit harus > 0")

        # Nama unik (case-insensitive) di antara barang yang belum di-soft-delete.
        # Cek via lower() agar 'Proyektor' == 'proyektor'.
        existing = (
            Barang.query.filter(db.func.lower(Barang.nama) == nama.lower())
            .filter(Barang.deleted_at.is_(None))
            .first()
        )
        if existing is not None:
            raise ValueError(f"Nama barang '{nama}' sudah dipakai")

        barang = Barang(
            nama=nama,
            kategori_id=kategori_id,
            jumlah_unit=jumlah,
            kondisi="baik",
            status="tersedia",
            deskripsi=(data.get("deskripsi") or "").strip() or None,
        )

        # Set kondisi via method model (encapsulation: ada validasi enum)
        kondisi = (data.get("kondisi") or "").strip()
        if kondisi:
            barang.set_kondisi(kondisi)  # raise ValueError jika invalid

        db.session.add(barang)
        db.session.commit()
        return barang

    # ── Update ────────────────────────────────────────────────
    def edit(self, barang_id: str, data: dict) -> Barang:
        """
        Edit data barang. Hanya field yang diisi (non-empty) yang di-update.

        Validasi sama dengan ``tambah`` untuk field yang diubah.

        Raises:
            ValueError: Jika barang tidak ditemukan, sudah di-soft-delete,
                        atau validasi field gagal.
        """
        barang = self._get_active(barang_id)
        if barang is None:
            raise ValueError("Barang tidak ditemukan")

        nama = (data.get("nama") or "").strip()
        if nama and nama.lower() != barang.nama.lower():
            existing = (
                Barang.query.filter(db.func.lower(Barang.nama) == nama.lower())
                .filter(Barang.deleted_at.is_(None))
                .filter(Barang.id != barang_id)
                .first()
            )
            if existing is not None:
                raise ValueError(f"Nama barang '{nama}' sudah dipakai")
            barang.nama = nama

        kategori_id = (data.get("kategori_id") or "").strip()
        if kategori_id and kategori_id != barang.kategori_id:
            if db.session.get(Kategori, kategori_id) is None:
                raise ValueError("Kategori tidak ditemukan")
            barang.kategori_id = kategori_id

        jumlah_raw = data.get("jumlah", data.get("jumlah_unit"))
        if jumlah_raw not in (None, ""):
            try:
                jumlah = int(jumlah_raw)
            except (TypeError, ValueError):
                raise ValueError("Jumlah unit harus berupa angka")
            if jumlah <= 0:
                raise ValueError("Jumlah unit harus > 0")
            barang.jumlah_unit = jumlah

        kondisi = (data.get("kondisi") or "").strip()
        if kondisi:
            barang.set_kondisi(kondisi)  # encapsulation: enum validate + sinkron status

        status = (data.get("status") or "").strip()
        if status:
            barang.set_status(status)  # encapsulation: enum validate

        deskripsi = data.get("deskripsi")
        if deskripsi is not None:
            barang.deskripsi = deskripsi.strip() or None

        db.session.commit()
        return barang

    # ── Soft Delete (BR-06 & BR-08) ───────────────────────────
    def hapus(self, barang_id: str) -> Barang:
        """
        Soft-delete barang: set ``deleted_at`` + status ``'dihapus'``.

        **BR-06**: barang yang sedang dipinjam (ada di peminjaman aktif:
        ``diajukan``/``disetujui``/``dipinjam``/``terlambat``) TIDAK boleh
        dihapus.

        Raises:
            ValueError: Jika barang tidak ditemukan, sudah dihapus, atau
                        sedang dipinjam (BR-06).
        """
        barang = self._get_active(barang_id)
        if barang is None:
            raise ValueError("Barang tidak ditemukan")

        if self._sedang_dipinjam(barang_id):
            raise ValueError(
                "Barang sedang dipinjam dan tidak dapat dihapus (BR-06)"
            )

        barang.soft_delete()  # encapsulation: set deleted_at + status 'dihapus'
        db.session.commit()
        return barang

    # ── Read ──────────────────────────────────────────────────
    def get_by_id(self, barang_id: str, include_deleted: bool = False) -> Optional[Barang]:
        """
        Return barang berdasarkan ID.

        Args:
            include_deleted: Jika False (default), barang yang sudah di-soft-delete
                             return None.
        """
        barang = db.session.get(Barang, barang_id)
        if barang is None:
            return None
        if barang.is_deleted and not include_deleted:
            return None
        return barang

    def get_all(self, filters: Optional[dict] = None) -> List[Barang]:
        """
        Return list barang aktif (yang belum di-soft-delete), urut nama A-Z.

        Filter yang didukung:
          - ``q``: search berdasarkan nama (case-insensitive LIKE)
          - ``kategori`` / ``kategori_id``: filter by kategori ID
          - ``status``: filter by status barang (validasi enum)
          - ``include_deleted``: jika True, sertakan barang terhapus
        """
        filters = filters or {}
        query = Barang.query

        if not filters.get("include_deleted"):
            query = query.filter(Barang.deleted_at.is_(None))

        search = (filters.get("q") or "").strip()
        if search:
            query = query.filter(Barang.nama.ilike(f"%{search}%"))

        kategori_id = filters.get("kategori") or filters.get("kategori_id")
        if kategori_id:
            query = query.filter(Barang.kategori_id == kategori_id)

        status = filters.get("status")
        if status:
            if status not in STATUS_BARANG:
                raise ValueError(
                    f"Status filter tidak valid. Pilihan: {', '.join(STATUS_BARANG)}"
                )
            query = query.filter(Barang.status == status)

        return query.order_by(Barang.nama.asc()).all()

    def search(self, keyword: str) -> List[Barang]:
        """Shortcut search barang by nama (case-insensitive LIKE)."""
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        return (
            Barang.query.filter(Barang.deleted_at.is_(None))
            .filter(Barang.nama.ilike(f"%{keyword}%"))
            .order_by(Barang.nama.asc())
            .all()
        )

    def get_by_kategori(self, kategori_id: str) -> List[Barang]:
        """Return barang aktif dalam kategori tertentu, urut nama A-Z."""
        return (
            Barang.query.filter(Barang.deleted_at.is_(None))
            .filter(Barang.kategori_id == kategori_id)
            .order_by(Barang.nama.asc())
            .all()
        )

    # ── Upload Foto (T-SEC-05) ────────────────────────────────
    def upload_foto(self, barang_id: str, file_storage) -> str:
        """
        Upload & simpan foto barang.

        Validasi:
          - File ada & punya nama
          - Ekstensi: ``png``/``jpg``/``jpeg``/``webp``
          - Ukuran <= 5 MB (lihat ``MAX_FOTO_SIZE_BYTES``)

        File disimpan dengan nama UUID agar unik & aman (tidak pakai nama
        asli user). Path relatif disimpan di ``barang.foto_path``.

        Args:
            barang_id: ID barang yang akan diupdate fotonya.
            file_storage: ``werkzeug.datastructures.FileStorage`` (dari
                          ``request.files['foto']``).

        Raises:
            ValueError: Jika barang tidak ada / file invalid / ekstensi
                        tidak diizinkan / ukuran melebihi batas.

        Returns:
            Path relatif foto (e.g. ``img/<uuid>.png``) yang juga tersimpan
            di ``barang.foto_path``.
        """
        barang = self._get_active(barang_id)
        if barang is None:
            raise ValueError("Barang tidak ditemukan")

        if file_storage is None or not getattr(file_storage, "filename", ""):
            raise ValueError("File foto wajib diisi")

        filename = file_storage.filename.lower()
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ALLOWED_FOTO_EXT:
            raise ValueError(
                "Ekstensi foto tidak diizinkan. Harus: "
                + ", ".join(sorted(ALLOWED_FOTO_EXT))
            )

        # Cek ukuran via stream — read() lalu seek balik agar tetap bisa disimpan
        file_storage.stream.seek(0, os.SEEK_END)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size > MAX_FOTO_SIZE_BYTES:
            raise ValueError(
                f"Ukuran foto melebihi batas (maks {MAX_FOTO_SIZE_BYTES // (1024*1024)} MB)"
            )

        # Simpan ke folder static/img/<uuid>.<ext>
        img_folder = os.path.join(current_app.static_folder, "img")
        os.makedirs(img_folder, exist_ok=True)
        new_name = f"{uuid.uuid4().hex}.{ext}"
        full_path = os.path.join(img_folder, new_name)
        file_storage.save(full_path)

        # Path relatif (dari static/) untuk dipakai di url_for('static', filename=...)
        relative_path = f"img/{new_name}"
        barang.foto_path = relative_path
        db.session.commit()
        return relative_path

    # ── Helper internal ───────────────────────────────────────
    def _get_active(self, barang_id: str) -> Optional[Barang]:
        """Return barang aktif (belum di-soft-delete) by ID."""
        return self.get_by_id(barang_id, include_deleted=False)

    def _sedang_dipinjam(self, barang_id: str) -> bool:
        """
        Cek BR-06: apakah barang sedang dipakai di peminjaman aktif?

        Peminjaman aktif = status di ``STATUS_BARANG_TERPAKAI``.
        """
        return (
            db.session.query(DetailPeminjaman)
            .join(Peminjaman, Peminjaman.id == DetailPeminjaman.peminjaman_id)
            .filter(DetailPeminjaman.barang_id == barang_id)
            .filter(Peminjaman.status.in_(STATUS_BARANG_TERPAKAI))
            .first()
            is not None
        )
