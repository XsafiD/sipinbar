"""
controllers/dashboard_controller.py — Blueprint ``dashboard_bp``.

Routes:
  - ``GET /``           — redirect ke /dashboard (atau /login jika belum login)
  - ``GET /dashboard``  — halaman dashboard utama (SCR-03)

Dashboard menampilkan:
  - Stat card (total barang, peminjaman aktif, terlambat, warga terdaftar)
  - Tabel 5 peminjaman terbaru
  - Panel notifikasi terbaru

Catatan scope (§3.4 / T-FE-14):
  Data saat ini masih DUMMY (konteks statis). Integrasi real dengan
  ``LaporanService.get_statistik_dashboard()`` akan dilakukan di M3 §4.2
  (task T-UI-03 / T-UI-17). Lihat handoff-frontend Q-11.

Refs: TODO T-FE-14, UI Spec SCR-03, handoff Q-11
"""
from flask import (
    Blueprint,
    redirect,
    render_template,
    session,
    url_for,
)

from controllers.decorators import login_required


dashboard_bp = Blueprint("dashboard", __name__)


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

    Render dengan DUMMY context. Data real akan dikirim oleh
    LaporanService.get_statistik_dashboard() setelah M3 §4.2 selesai.
    """
    role = session.get("role", "warga")

    # ── DUMMY DATA (TODO: ganti dengan LaporanService.get_statistik_dashboard()) ──
    # Lihat handoff-frontend Q-11 & TODO T-UI-03.
    stats = {
        "total_barang": 24,
        "tersedia": 18,
        "peminjaman_aktif": 4,
        "terlambat": 2,
    }
    if role == "admin":
        stats["warga_terdaftar"] = 12

    recent_peminjaman = [
        {"kode": "PJM-2026-0001", "peminjam": "Budi Santoso",
         "tgl_pinjam": "2026-07-05", "status": "dipinjam"},
        {"kode": "PJM-2026-0002", "peminjam": "Siti Aminah",
         "tgl_pinjam": "2026-07-06", "status": "diajukan"},
        {"kode": "PJM-2026-0003", "peminjam": "Ahmad Yani",
         "tgl_pinjam": "2026-07-04", "status": "terlambat"},
        {"kode": "PJM-2026-0004", "peminjam": "Dewi Lestari",
         "tgl_pinjam": "2026-07-03", "status": "dikembalikan"},
        {"kode": "PJM-2026-0005", "peminjam": "Rudi Hartono",
         "tgl_pinjam": "2026-07-02", "status": "disetujui"},
    ]

    notifications = [
        {"tipe": "pengingat", "judul": "Jatuh tempo besok",
         "pesan": "Peminjaman PJM-2026-0001 jatuh tempo 2026-07-08.",
         "timestamp": "2 jam lalu", "unread": True},
        {"tipe": "info", "judul": "Peminjaman baru",
         "pesan": "Siti Aminah mengajukan peminjaman PJM-2026-0002.",
         "timestamp": "5 jam lalu", "unread": True},
        {"tipe": "peringatan", "judul": "Terlambat",
         "pesan": "PJM-2026-0003 sudah 2 hari terlambat.",
         "timestamp": "1 hari lalu", "unread": False},
    ]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_peminjaman=recent_peminjaman,
        notifications=notifications,
    )
