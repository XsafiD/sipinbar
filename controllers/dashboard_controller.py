"""
controllers/dashboard_controller.py — Blueprint ``dashboard_bp``.

Routes:
  - ``GET /``           — redirect ke /dashboard (atau /login jika belum login)
  - ``GET /dashboard``  — halaman dashboard utama (SCR-03)

Dashboard menampilkan:
  - Stat card (total barang, peminjaman aktif, terlambat, warga terdaftar)
  - Tabel 5 peminjaman terbaru
  - Panel notifikasi terbaru

Integrasi data real (T-UI-03 / T-UI-17):
  - Admin: ``LaporanService.get_statistik_dashboard()`` + 5 peminjaman
    terbaru global + notifikasi seluruh sistem (di-scope per role).
  - Warga: ``LaporanService.get_statistik_warga()`` + 5 peminjaman
    terbaru milik user + notifikasi milik user.

Refs: TODO T-FE-14 & T-UI-03/T-UI-17, UI Spec SCR-03, handoff Q-11
"""
from flask import (
    Blueprint,
    redirect,
    render_template,
    session,
    url_for,
)

from controllers.decorators import login_required
from models.peminjaman import Peminjaman
from services.laporan_service import LaporanService
from services.notifikasi_service import NotifikasiService


dashboard_bp = Blueprint("dashboard", __name__)
_laporan_service = LaporanService()
_notifikasi_service = NotifikasiService()


def _format_peminjaman_row(p: Peminjaman) -> dict:
    """Format satu Peminjaman menjadi row untuk tabel dashboard."""
    return {
        "id": p.id,
        "kode": p.kode_peminjaman,
        "peminjam": p.warga.nama_lengkap if p.warga else "-",
        "tgl_pinjam": p.tanggal_pinjam.isoformat() if p.tanggal_pinjam else "-",
        "status": p.status,
    }


@dashboard_bp.route("/")
def root():
    """Root route — redirect ke /dashboard.

    /dashboard sendiri diproteksi @login_required, jadi user belum login
    akan otomatis di-redirect ke /login.
    """
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/dashboard")
@login_required
def index():
    """Halaman dashboard utama (SCR-03).

    Data real dari ``LaporanService`` + ``NotifikasiService``.
    Admin lihat global; warga lihat pribadi.
    """
    role = session.get("role", "warga")
    user_id = session.get("user_id")

    # ── Statistik ─────────────────────────────────────────────
    if role == "admin":
        stats = _laporan_service.get_statistik_dashboard()
        # Tambahkan kategori "tersedia" (barang berstatus 'tersedia')
        from models.barang import Barang

        stats["tersedia"] = (
            Barang.query.filter(Barang.deleted_at.is_(None))
            .filter(Barang.status == "tersedia")
            .count()
        )
    else:
        stat_warga = _laporan_service.get_statistik_warga(user_id)
        # Samakan shape dengan admin agar template tetap konsisten
        stats = {
            "peminjaman_aktif": stat_warga["peminjaman_aktif"],
            "terlambat": stat_warga["peminjaman_terlambat"],
            "peminjaman_riwayat": stat_warga["peminjaman_riwayat"],
        }

    # ── 5 Peminjaman terbaru ──────────────────────────────────
    query = Peminjaman.query
    if role != "admin":
        query = query.filter(Peminjaman.warga_id == user_id)
    recent = (
        query.order_by(Peminjaman.created_at.desc()).limit(5).all()
    )
    recent_peminjaman = [_format_peminjaman_row(p) for p in recent]

    # ── Notifikasi terbaru (3-5 item, milik user) ────────────
    notif_list = _notifikasi_service.get_by_warga(user_id)[:5]
    notifications = [
        {
            "id": n.id,
            "tipe": n.tipe,
            "judul": n.judul,
            "pesan": n.pesan,
            "timestamp": n.created_at.strftime("%d %b %Y, %H:%M"),
            "unread": not n.is_dibaca,
        }
        for n in notif_list
    ]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_peminjaman=recent_peminjaman,
        notifications=notifications,
        unread_count=_notifikasi_service.get_unread_count(user_id),
    )
