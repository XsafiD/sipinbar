"""
services/notifikasi_service.py — Business logic modul Notifikasi.

Mengelola:
  - Pengiriman notifikasi in-app (pengingat jatuh tempo, info perubahan
    status peminjaman, peringatan keterlambatan)
  - Query notifikasi per warga (dengan filter unread)
  - Tandai dibaca (single & bulk)
  - Scheduler entry-point ``check_and_send_reminders`` untuk pengingat H-1
    jatuh tempo (BR-07)

Pilar OOP yang terlihat:
  - **Abstraction**: service menjadi pintu masuk tunggal untuk operasi
    notifikasi di layer controller & scheduler, menyembunyikan detail
    query anti-duplicate-reminder & pemilihan tipe notifikasi.
  - **Polymorphism**: memakai ``NotifikasiInApp`` (kontrak
    ``NotifikasiBase``) sebagai factory. Jika kelak ditambah kanal
    Email/WhatsApp, caller tidak berubah — cukup ganti instance kanal.
  - **Encapsulation**: perubahan status baca didelegasikan ke method model
    ``Notifikasi.tandai_dibaca()`` (idempoten), bukan set langsung.

Refs: SRS §4.5, PRD FR-06, arsitektur-db §5.7, TODO T-LAP-01 & T-LAP-04
"""
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_

from models import db, utcnow
from models.notifikasi import Notifikasi, NotifikasiInApp
from models.peminjaman import Peminjaman


# ── Mapping status peminjaman → tipe notifikasi ────────────────
# Memutuskan tipe notifikasi (pengingat/info/peringatan) berdasarkan
# perubahan status peminjaman. `terlambat` & `ditolak` masuk peringatan;
# transisi progresif (disetujui/dipinjam/dikembalikan) masuk info.
STATUS_TO_TIPE = {
    "disetujui": "info",
    "ditolak": "peringatan",
    "dipinjam": "info",
    "terlambat": "peringatan",
    "dikembalikan": "info",
}


class NotifikasiService:
    """Service layer untuk modul Notifikasi in-app."""

    # ── Kirim Notifikasi (factory via NotifikasiInApp) ─────────
    def kirim_pengingat(self, peminjaman_id: str) -> Optional[Notifikasi]:
        """
        Kirim notifikasi pengingat H-1 untuk peminjaman yang akan jatuh tempo.

        Notifikasi hanya dikirim jika peminjaman berstatus ``'dipinjam'`` dan
        ``tanggal_kembali_rencana`` adalah besok (H-1 dari jatuh tempo).
        Anti-spam: jika pengingat untuk peminjaman ini sudah pernah dikirim
        hari ini, tidak dikirim ulang.

        Args:
            peminjaman_id: ID peminjaman.

        Raises:
            ValueError: Jika peminjaman tidak ditemukan.

        Returns:
            Instance ``Notifikasi`` yang tersimpan, atau ``None`` jika
            tidak memenuhi syarat (bukan dipinjam / bukan H-1 / sudah dikirim).
        """
        peminjaman = self._get_peminjaman(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")

        # Hanya peminjaman yang sedang dipinjam yang perlu pengingat
        if peminjaman.status != "dipinjam":
            return None

        # Hanya kirim jika jatuh tempo besok (H-1)
        besok = date.today() + timedelta(days=1)
        if peminjaman.tanggal_kembali_rencana != besok:
            return None

        # Anti-spam: skip jika sudah ada pengingat untuk peminjaman ini hari ini
        if self._pengingat_hari_ini_ada(peminjaman_id):
            return None

        builder = NotifikasiInApp(
            warga_id=peminjaman.warga_id,
            tipe="pengingat",
            judul="Pengingat Pengembalian",
            pesan=(
                f"Peminjaman {peminjaman.kode_peminjaman} jatuh tempo besok "
                f"({peminjaman.tanggal_kembali_rencana.isoformat()}). "
                f"Mohon kembalikan barang tepat waktu."
            ),
            peminjaman_id=peminjaman.id,
        )
        notif = builder.kirim()
        db.session.commit()
        return notif

    def kirim_notifikasi_status(
        self, peminjaman_id: str, status_baru: str
    ) -> Optional[Notifikasi]:
        """
        Kirim notifikasi saat status peminjaman berubah.

        Tipe notifikasi dipilih otomatis berdasarkan ``status_baru``:
          - ``disetujui`` / ``dipinjam`` / ``dikembalikan`` → ``info``
          - ``ditolak`` / ``terlambat`` → ``peringatan``

        Args:
            peminjaman_id: ID peminjaman.
            status_baru: Status baru peminjaman (harus salah satu dari
                         ``STATUS_PEMINJAMAN``).

        Raises:
            ValueError: Jika peminjaman tidak ditemukan atau status tidak
                        dikenali.

        Returns:
            Instance ``Notifikasi``, atau ``None`` jika status tidak
            memerlukan notifikasi (mis. ``diajukan``).
        """
        peminjaman = self._get_peminjaman(peminjaman_id)
        if peminjaman is None:
            raise ValueError("Peminjaman tidak ditemukan")

        tipe = STATUS_TO_TIPE.get(status_baru)
        if tipe is None:
            # Status 'diajukan' tidak mengirim notifikasi (warga sendiri yang ajukan)
            return None

        # Pesan disesuaikan dengan status
        pesan_map = {
            "disetujui": (
                f"Peminjaman {peminjaman.kode_peminjaman} disetujui admin. "
                f"Barang dapat diambil."
            ),
            "ditolak": (
                f"Peminjaman {peminjaman.kode_peminjaman} ditolak. "
                f"Alasan: {peminjaman.alasan_penolakan or '-'}"
            ),
            "dipinjam": (
                f"Barang peminjaman {peminjaman.kode_peminjaman} telah diserahkan. "
                f"Jatuh tempo: {peminjaman.tanggal_kembali_rencana.isoformat()}."
            ),
            "terlambat": (
                f"Peminjaman {peminjaman.kode_peminjaman} terlambat. "
                f"Segera kembalikan barang untuk menghindari denda tambahan."
            ),
            "dikembalikan": (
                f"Peminjaman {peminjaman.kode_peminjaman} telah dikembalikan. "
                f"Denda: Rp {peminjaman.total_denda_rupiah:,}."
            ),
        }

        builder = NotifikasiInApp(
            warga_id=peminjaman.warga_id,
            tipe=tipe,
            judul=f"Status Peminjaman: {status_baru.title()}",
            pesan=pesan_map.get(status_baru, f"Status peminjaman kini: {status_baru}"),
            peminjaman_id=peminjaman.id,
        )
        notif = builder.kirim()
        db.session.commit()
        return notif

    # ── Scheduler: Cek & Kirim Pengingat Massal (BR-07) ────────
    def check_and_send_reminders(self) -> int:
        """
        Cek semua peminjaman aktif & kirim pengingat H-1 jatuh tempo.

        Dipanggil oleh scheduler (Flask CLI ``flask send-reminders`` atau
        cron job). Idempoten: aman dipanggil berkali-kali dalam sehari
        berkat anti-spam per peminjaman.

        Returns:
            Jumlah pengingat yang berhasil terkirim.
        """
        besok = date.today() + timedelta(days=1)
        candidates = (
            Peminjaman.query
            .filter(Peminjaman.status == "dipinjam")
            .filter(Peminjaman.tanggal_kembali_rencana == besok)
            .all()
        )

        terkirim = 0
        for peminjaman in candidates:
            # Anti-spam: skip yang sudah dikirimi hari ini
            if self._pengingat_hari_ini_ada(peminjaman.id):
                continue
            builder = NotifikasiInApp(
                warga_id=peminjaman.warga_id,
                tipe="pengingat",
                judul="Pengingat Pengembalian",
                pesan=(
                    f"Peminjaman {peminjaman.kode_peminjaman} jatuh tempo besok "
                    f"({peminjaman.tanggal_kembali_rencana.isoformat()}). "
                    f"Mohon kembalikan barang tepat waktu."
                ),
                peminjaman_id=peminjaman.id,
            )
            builder.kirim()
            terkirim += 1

        if terkirim:
            db.session.commit()
        return terkirim

    # ── Query / Read ──────────────────────────────────────────
    def get_by_warga(
        self, warga_id: str, only_unread: bool = False
    ) -> List[Notifikasi]:
        """
        Return daftar notifikasi milik warga, urut terbaru.

        Args:
            warga_id: ID warga.
            only_unread: Jika ``True``, hanya return yang belum dibaca.
        """
        query = Notifikasi.query.filter(Notifikasi.warga_id == warga_id)
        if only_unread:
            query = query.filter(Notifikasi.is_dibaca.is_(False))
        return query.order_by(Notifikasi.created_at.desc()).all()

    def get_unread_count(self, warga_id: str) -> int:
        """Return jumlah notifikasi belum dibaca milik warga."""
        return (
            Notifikasi.query
            .filter(Notifikasi.warga_id == warga_id)
            .filter(Notifikasi.is_dibaca.is_(False))
            .count()
        )

    def get_by_id(self, notifikasi_id: str) -> Optional[Notifikasi]:
        """Return notifikasi by ID, atau None."""
        return db.session.get(Notifikasi, notifikasi_id)

    # ── Mutasi Status Baca ────────────────────────────────────
    def tandai_dibaca(self, notifikasi_id: str) -> Notifikasi:
        """
        Tandai satu notifikasi sebagai sudah dibaca.

        Delegate ke method model ``Notifikasi.tandai_dibaca()`` (idempoten).

        Raises:
            ValueError: Jika notifikasi tidak ditemukan.
        """
        notif = self.get_by_id(notifikasi_id)
        if notif is None:
            raise ValueError("Notifikasi tidak ditemukan")
        notif.tandai_dibaca()  # encapsulation: model yang ubah state
        db.session.commit()
        return notif

    def tandai_semua_dibaca(self, warga_id: str) -> int:
        """
        Tandai semua notifikasi belum dibaca milik warga sebagai dibaca.

        Returns:
            Jumlah notifikasi yang ditandai dibaca.
        """
        unread = (
            Notifikasi.query
            .filter(Notifikasi.warga_id == warga_id)
            .filter(Notifikasi.is_dibaca.is_(False))
            .all()
        )
        for notif in unread:
            notif.tandai_dibaca()
        db.session.commit()
        return len(unread)

    # ── Helper internal ───────────────────────────────────────
    def _get_peminjaman(self, peminjaman_id: str) -> Optional[Peminjaman]:
        """Return peminjaman by ID (singkatan)."""
        return db.session.get(Peminjaman, peminjaman_id)

    def _pengingat_hari_ini_ada(self, peminjaman_id: str) -> bool:
        """
        Cek apakah pengingat untuk ``peminjaman_id`` sudah dikirim hari ini.

        Anti-spam agar scheduler yang berjalan berkali-kali sehari tidak
        mengirim pengingat ganda.

        **Penting**: window calendar-day dihitung dalam **UTC** (bukan local
        time) agar konsisten dengan ``Notifikasi.created_at`` yang disimpan
        sebagai UTC via ``utcnow()``. Bug T-INT-07: sebelumnya memakai
        ``date.today()`` (local) yang mismatch dengan ``created_at`` (UTC)
        saat berjalan di rentang 00:00–07:00 UTC+N, menyebabkan anti-spam
        gagal dan pengingat dikirim ganda.
        """
        today_utc = utcnow().date()
        start_of_day = datetime.combine(today_utc, datetime.min.time())
        end_of_day = datetime.combine(today_utc, datetime.max.time())
        existing = (
            Notifikasi.query
            .filter(Notifikasi.peminjaman_id == peminjaman_id)
            .filter(Notifikasi.tipe == "pengingat")
            .filter(
                and_(
                    Notifikasi.created_at >= start_of_day,
                    Notifikasi.created_at <= end_of_day,
                )
            )
            .first()
        )
        return existing is not None
