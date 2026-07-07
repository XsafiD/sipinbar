"""
controllers/peminjaman_controller.py — Blueprint ``peminjaman_bp`` (STUB).

Modul peminjaman akan diimplementasi penuh di M3 §4.1 (task T-PJM-01 s/d
T-PJM-04). Saat ini (§3.4 scaffolding) hanya dibuat stub agar:
  - Sidebar menu "Peminjaman" punya link valid (url_for('peminjaman.index'))
  - Halaman tidak 404, melainkan redirect ke dashboard dengan flash info

Routes (stub):
  - ``GET /peminjaman/``  — redirect ke /dashboard + flash "modul belum tersedia"

Refs: TODO §4.1 (M3), T-FE-06 sidebar dependency
"""
from flask import Blueprint, flash, redirect, url_for

peminjaman_bp = Blueprint("peminjaman", __name__, url_prefix="/peminjaman")


@peminjaman_bp.route("/")
def index():
    """Stub — modul peminjaman belum tersedia, redirect ke dashboard."""
    flash(
        "Modul Peminjaman sedang dalam pengembangan (M3 §4.1). "
        "Sementara ini, kembali ke dashboard.",
        "info",
    )
    return redirect(url_for("dashboard.index"))
