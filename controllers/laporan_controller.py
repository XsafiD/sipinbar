"""
controllers/laporan_controller.py — Blueprint ``laporan_bp`` (STUB).

Modul laporan & notifikasi akan diimplementasi penuh di M3 §4.2 (task
T-LAP-01 s/d T-LAP-06). Saat ini (§3.4 scaffolding) hanya dibuat stub agar:
  - Sidebar menu "Laporan" punya link valid (url_for('laporan.index'))
  - Navbar bell notifikasi punya link valid (url_for('laporan.notifikasi'))
  - Halaman tidak 404, melainkan redirect ke dashboard dengan flash info

Routes (stub):
  - ``GET /laporan/``            — redirect ke dashboard
  - ``GET /laporan/peminjaman``  — redirect ke dashboard
  - ``GET /laporan/inventaris``  — redirect ke dashboard
  - ``GET /notifikasi/``         — redirect ke dashboard

Catatan: laporan_bp TANPA url_prefix karena menghandle route di 2 path
berbeda (/laporan/* dan /notifikasi/*) sesuai TODO §4.2.2.

Refs: TODO §4.2 (M3), T-FE-06 sidebar & T-FE-05 navbar dependency
"""
from flask import Blueprint, flash, redirect, url_for

laporan_bp = Blueprint("laporan", __name__)


@laporan_bp.route("/laporan/")
def index():
    """Stub — pusat laporan belum tersedia."""
    flash(
        "Modul Laporan sedang dalam pengembangan (M3 §4.2).",
        "info",
    )
    return redirect(url_for("dashboard.index"))


@laporan_bp.route("/laporan/peminjaman")
def peminjaman():
    """Stub — laporan peminjaman belum tersedia."""
    flash("Laporan Peminjaman belum tersedia (M3 §4.2).", "info")
    return redirect(url_for("dashboard.index"))


@laporan_bp.route("/laporan/inventaris")
def inventaris():
    """Stub — laporan inventaris belum tersedia."""
    flash("Laporan Inventaris belum tersedia (M3 §4.2).", "info")
    return redirect(url_for("dashboard.index"))


@laporan_bp.route("/notifikasi/")
def notifikasi():
    """Stub — halaman notifikasi belum tersedia."""
    flash("Halaman Notifikasi belum tersedia (M3 §4.2).", "info")
    return redirect(url_for("dashboard.index"))
