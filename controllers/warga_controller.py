"""
controllers/warga_controller.py — Blueprint ``admin_warga_bp`` untuk
manajemen warga oleh admin.

Prefix URL: ``/admin/warga`` (semua route di-protect ``@admin_required``).

Routes:
  - ``GET /admin/warga``                       — daftar warga + filter status
  - ``GET /admin/warga/<warga_id>``            — detail warga + riwayat
  - ``POST /admin/warga/<warga_id>/verify``    — verifikasi warga (set password)
  - ``POST /admin/warga/<warga_id>/reject``    — tolak warga (+ alasan)
  - ``POST /admin/warga/<warga_id>/blokir``    — blokir warga aktif
  - ``POST /admin/warga/<warga_id>/aktifkan``  — aktifkan kembali warga diblokir

Catatan: route ``aktifkan`` tidak tercantum di TODO §3.1.2 namun
diperlukan karena T-AUTH-02 AC mensyaratkan method ``aktifkan(id)``
di WargaService, dan lifecycle warga lengkap (aktif↔diblokir) wajib
ter-expose via UI agar admin bisa mengelola warga secara penuh.

Refs: SRS §6.1, UI Spec SCR-12 & SCR-13, TODO T-AUTH-04
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import PasswordField, TextAreaField
from wtforms.validators import DataRequired, Length

from controllers.decorators import admin_required
from services.auth_service import AuthService
from services.warga_service import WargaService


# ── Form Definitions ─────────────────────────────────────────
class VerifyForm(FlaskForm):
    """Form verifikasi warga — password awal yang di-set admin."""

    password = PasswordField(
        "Password Awal Warga",
        validators=[
            DataRequired(message="Password awal wajib diisi"),
            Length(min=6, max=72, message="Password minimal 6 karakter"),
        ],
    )


class RejectForm(FlaskForm):
    """Form penolakan warga — alasan wajib."""

    alasan = TextAreaField(
        "Alasan Penolakan",
        validators=[
            DataRequired(message="Alasan penolakan wajib diisi"),
            Length(min=5, max=500, message="Alasan 5-500 karakter"),
        ],
    )


class ConfirmForm(FlaskForm):
    """Form kosong — hanya untuk CSRF protection pada aksi singkat."""

    pass


# ── Blueprint Init ───────────────────────────────────────────
admin_warga_bp = Blueprint(
    "admin_warga", __name__, url_prefix="/admin/warga"
)
_warga_service = WargaService()
_auth_service = AuthService()


# ── Routes ───────────────────────────────────────────────────
@admin_warga_bp.route("/")
@admin_required
def index():
    """Daftar warga dengan filter status (?status=) & search (?q=)."""
    status_filter = request.args.get("status", type=str) or None
    filters = {}
    if status_filter:
        filters["status"] = status_filter

    try:
        warga_list = _warga_service.get_all(filters)
    except ValueError as err:
        flash(str(err), "error")
        warga_list = []

    return render_template(
        "warga/index.html",
        warga_list=warga_list,
        status_filter=status_filter or "",
    )


@admin_warga_bp.route("/<warga_id>")
@admin_required
def detail(warga_id: str):
    """Detail warga + riwayat peminjaman + form aksi kontekstual."""
    warga = _warga_service.get_by_id(warga_id)
    if warga is None:
        abort(404)

    try:
        riwayat = _warga_service.get_riwayat_peminjaman(warga_id)
    except ValueError:
        riwayat = []

    return render_template(
        "warga/detail.html",
        warga=warga,
        riwayat=riwayat,
        verify_form=VerifyForm(),
        reject_form=RejectForm(),
        confirm_form=ConfirmForm(),
    )


@admin_warga_bp.route("/<warga_id>/verify", methods=["POST"])
@admin_required
def verify(warga_id: str):
    """Verifikasi warga — set status ke 'aktif' + password awal."""
    form = VerifyForm()
    if not form.validate_on_submit():
        flash("Password tidak valid (minimal 6 karakter).", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _auth_service.verify_warga(warga_id, form.password.data)
        flash("Warga berhasil diverifikasi & password awal telah di-set.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/reject", methods=["POST"])
@admin_required
def reject(warga_id: str):
    """Tolak pendaftaran warga — status ke 'ditolak' dengan alasan."""
    form = RejectForm()
    if not form.validate_on_submit():
        flash("Alasan penolakan wajib diisi (minimal 5 karakter).", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _auth_service.reject_warga(warga_id, form.alasan.data)
        flash("Warga telah ditolak.", "info")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/blokir", methods=["POST"])
@admin_required
def blokir(warga_id: str):
    """Blokir warga aktif — status ke 'diblokir' (tidak bisa login/pinjam)."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _warga_service.blokir(warga_id)
        flash("Warga telah diblokir.", "info")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/aktifkan", methods=["POST"])
@admin_required
def aktifkan(warga_id: str):
    """Aktifkan kembali warga yang diblokir."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _warga_service.aktifkan(warga_id)
        flash("Warga telah diaktifkan kembali.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))
