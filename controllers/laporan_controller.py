"""
controllers/laporan_controller.py — Blueprint ``laporan_bp`` untuk modul
Laporan & Notifikasi.

Menghandle 2 prefix URL (karena itulah blueprint ini TANPA ``url_prefix``):
  - ``/laporan/*``     — admin-only (pusat laporan, laporan peminjaman,
                         laporan inventaris, export CSV)
  - ``/notifikasi/*``  — authenticated (warga/admin lihat notifikasi sendiri,
                         tandai dibaca)

Routes:
  - ``GET  /laporan/``               — pusat laporan (admin) → SCR-14
  - ``GET  /laporan/peminjaman``     — laporan peminjaman (admin) → SCR-15
  - ``GET  /laporan/inventaris``     — laporan inventaris (admin) → SCR-16
  - ``GET  /laporan/export``         — export CSV (admin) → trigger download
  - ``GET  /notifikasi/``            — daftar notifikasi (auth) → SCR-17
  - ``POST /notifikasi/<id>/baca``   — tandai dibaca (auth, owner-only)
  - ``POST /notifikasi/baca-semua``  — tandai semua dibaca (auth, owner-only)

Akses:
  - Laporan: ``@admin_required`` (warga → 403).
  - Notifikasi: ``@login_required``; warga hanya bisa aksi ke notifikasi
    miliknya (403 jika akses milik warga lain).

Refs: SRS §4.5.3 & §6.1, UI Spec SCR-14..SCR-17, TODO T-LAP-03
"""
import io
from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_wtf import FlaskForm

from controllers.decorators import admin_required, login_required
from services.laporan_service import LaporanService
from services.notifikasi_service import NotifikasiService


# ── Form Definitions (CSRF-only) ──────────────────────────────
class ConfirmForm(FlaskForm):
    """Form kosong — hanya CSRF protection untuk aksi tandai dibaca."""

    pass


# ── Blueprint Init ────────────────────────────────────────────
# Catatan: TANPA url_prefix karena menghandle /laporan/* dan /notifikasi/*
laporan_bp = Blueprint("laporan", __name__)
_laporan_service = LaporanService()
_notifikasi_service = NotifikasiService()


# ── Helper ────────────────────────────────────────────────────
def _parse_date(value: str, field_name: str):
    """Parse string ISO (YYYY-MM-DD) ke date, atau None jika kosong."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        flash(
            f"Format {field_name} tidak valid (harus YYYY-MM-DD).",
            "error",
        )
        return None


def _current_user_id() -> str:
    """Return user_id dari session."""
    return session.get("user_id")


# ════════════════════════════════════════════════════════════
#  ROUTES — LAPORAN (admin-only)
# ════════════════════════════════════════════════════════════
@laporan_bp.route("/laporan/")
@admin_required
def index():
    """Pusat laporan — ringkasan statistik + link ke laporan detail."""
    statistik = _laporan_service.get_statistik_dashboard()
    return render_template(
        "laporan/index.html",
        statistik=statistik,
    )


@laporan_bp.route("/laporan/peminjaman")
@admin_required
def peminjaman():
    """Laporan transaksi peminjaman dengan filter periode."""
    mulai = _parse_date(request.args.get("mulai", type=str) or "", "mulai")
    selesai = _parse_date(
        request.args.get("selesai", type=str) or "", "selesai"
    )
    status = request.args.get("status", type=str) or None

    try:
        data = _laporan_service.generate_laporan_peminjaman(
            mulai=mulai, selesai=selesai, status=status
        )
    except ValueError as err:
        flash(str(err), "error")
        data = {"rows": [], "summary": {}, "metadata": {}}

    return render_template(
        "laporan/peminjaman.html",
        data=data,
        mulai_filter=mulai.isoformat() if mulai else "",
        selesai_filter=selesai.isoformat() if selesai else "",
        status_filter=status or "",
    )


@laporan_bp.route("/laporan/inventaris")
@admin_required
def inventaris():
    """Laporan snapshot inventaris barang."""
    include_deleted = request.args.get(
        "include_deleted", type=str, default="false"
    ).lower() in ("true", "1", "yes")

    data = _laporan_service.generate_laporan_inventaris(
        include_deleted=include_deleted
    )
    return render_template(
        "laporan/inventaris.html",
        data=data,
        include_deleted=include_deleted,
    )


@laporan_bp.route("/laporan/export")
@admin_required
def export():
    """
    Export laporan ke CSV (trigger download).

    Query string:
      - ``type``: ``'peminjaman'`` (default) atau ``'inventaris'``
      - ``mulai``, ``selesai``, ``status``: filter untuk laporan peminjaman
      - ``include_deleted``: untuk laporan inventaris
      - ``format``: saat ini hanya ``'csv'``
    """
    format = request.args.get("format", type=str) or "csv"
    if format != "csv":
        flash(f"Format '{format}' belum didukung. Gunakan 'csv'.", "error")
        return redirect(url_for("laporan.index"))

    laporan_type = request.args.get("type", type=str) or "peminjaman"

    if laporan_type == "inventaris":
        include_deleted = request.args.get(
            "include_deleted", type=str, default="false"
        ).lower() in ("true", "1", "yes")
        data = _laporan_service.generate_laporan_inventaris(
            include_deleted=include_deleted
        )
        filename = "laporan_inventaris_sipinbar.csv"
    else:
        mulai = _parse_date(
            request.args.get("mulai", type=str) or "", "mulai"
        )
        selesai = _parse_date(
            request.args.get("selesai", type=str) or "", "selesai"
        )
        status = request.args.get("status", type=str) or None
        try:
            data = _laporan_service.generate_laporan_peminjaman(
                mulai=mulai, selesai=selesai, status=status
            )
        except ValueError as err:
            flash(str(err), "error")
            return redirect(url_for("laporan.peminjaman"))
        filename = "laporan_peminjaman_sipinbar.csv"

    csv_bytes = _laporan_service.export_laporan(data, format="csv")
    return send_file(
        io.BytesIO(csv_bytes),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# ════════════════════════════════════════════════════════════
#  ROUTES — NOTIFIKASI (authenticated, owner-only)
# ════════════════════════════════════════════════════════════
@laporan_bp.route("/notifikasi/")
@login_required
def notifikasi():
    """Daftar notifikasi milik user yang sedang login."""
    warga_id = _current_user_id()
    only_unread = request.args.get(
        "unread", type=str, default="false"
    ).lower() in ("true", "1", "yes")

    notif_list = _notifikasi_service.get_by_warga(
        warga_id, only_unread=only_unread
    )
    unread_count = _notifikasi_service.get_unread_count(warga_id)

    return render_template(
        "laporan/notifikasi.html",
        notif_list=notif_list,
        unread_count=unread_count,
        only_unread=only_unread,
        confirm_form=ConfirmForm(),
    )


@laporan_bp.route("/notifikasi/<notifikasi_id>/baca", methods=["POST"])
@login_required
def tandai_baca(notifikasi_id: str):
    """Tandai satu notifikasi sebagai dibaca (owner-only)."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("laporan.notifikasi"))

    try:
        notif = _notifikasi_service.tandai_dibaca(notifikasi_id)
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("laporan.notifikasi"))

    # Anti-akses lintas warga: notifikasi milik warga lain → 403
    if notif.warga_id != _current_user_id():
        abort(403)

    flash("Notifikasi ditandai dibaca.", "success")
    return redirect(url_for("laporan.notifikasi"))


@laporan_bp.route("/notifikasi/baca-semua", methods=["POST"])
@login_required
def tandai_semua_baca():
    """Tandai semua notifikasi user yang sedang login sebagai dibaca."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("laporan.notifikasi"))

    jumlah = _notifikasi_service.tandai_semua_dibaca(_current_user_id())
    flash(f"{jumlah} notifikasi ditandai dibaca.", "success")
    return redirect(url_for("laporan.notifikasi"))
