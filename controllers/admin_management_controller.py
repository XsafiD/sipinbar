"""
controllers/admin_management_controller.py — Blueprint ``admin_management_bp``
untuk manajemen admin oleh super admin.

Prefix URL: ``/admin/admin`` (semua route di-protect ``@admin_required``).

Routes:
  - ``GET /admin/admin``                       — daftar admin
  - ``GET/POST /admin/admin/create``           — create admin baru
  - ``GET/POST /admin/admin/<admin_id>/edit``  — edit admin (nama, is_aktif)
  - ``POST /admin/admin/<admin_id>/reset-password`` — reset password admin
  - ``POST /admin/admin/<admin_id>/activate``  — aktifkan admin
  - ``POST /admin/admin/<admin_id>/deactivate`` — non-aktifkan admin
  - ``POST /admin/admin/<admin_id>/delete``    — hapus admin

Ref: SIPINBAR v2.0.0 - Multi-admin support with admin management
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from controllers.decorators import admin_required
from services.admin_service import AdminService


# ── Form Definitions ─────────────────────────────────────────
class CreateAdminForm(FlaskForm):
    """Form create admin baru."""

    username = StringField(
        "Username",
        validators=[
            DataRequired(message="Username wajib diisi"),
            Length(min=3, max=50, message="Username 3-50 karakter"),
            Regexp(
                r"^[a-zA-Z0-9_]+$",
                message="Username hanya boleh alphanumeric dan underscore",
            ),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password wajib diisi"),
            Length(min=6, max=72, message="Password minimal 6 karakter"),
        ],
    )
    nama_lengkap = StringField(
        "Nama Lengkap",
        validators=[
            DataRequired(message="Nama lengkap wajib diisi"),
            Length(max=100),
        ],
    )


class EditAdminForm(FlaskForm):
    """Form edit admin (nama & is_aktif)."""

    nama_lengkap = StringField(
        "Nama Lengkap",
        validators=[
            DataRequired(message="Nama lengkap wajib diisi"),
            Length(max=100),
        ],
    )
    is_aktif = BooleanField("Aktif")


class ResetPasswordAdminForm(FlaskForm):
    """Form reset password admin."""

    new_password = PasswordField(
        "Password Baru",
        validators=[
            DataRequired(message="Password baru wajib diisi"),
            Length(min=6, max=72, message="Password minimal 6 karakter"),
        ],
    )


class ConfirmForm(FlaskForm):
    """Form kosong — hanya untuk CSRF protection pada aksi singkat."""

    pass


# ── Blueprint Init ───────────────────────────────────────────
admin_management_bp = Blueprint(
    "admin_management", __name__, url_prefix="/admin/admin"
)
_admin_service = AdminService()


# ── Routes ───────────────────────────────────────────────────
@admin_management_bp.route("/")
@admin_required
def index():
    """Daftar semua admin."""
    try:
        admin_list = _admin_service.get_all(include_inactive=True)
    except Exception as err:
        flash(str(err), "error")
        admin_list = []

    return render_template("admin/admin/list.html", admin_list=admin_list)


@admin_management_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create():
    """Form create admin baru."""
    form = CreateAdminForm()

    if form.validate_on_submit():
        try:
            admin = _admin_service.create_admin(
                username=form.username.data,
                password=form.password.data,
                nama_lengkap=form.nama_lengkap.data,
            )
            flash(f"Admin '{admin.username}' berhasil dibuat.", "success")
            return redirect(url_for("admin_management.index"))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("admin/admin/create.html", form=form)


@admin_management_bp.route("/<admin_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(admin_id: str):
    """Edit data admin (nama & is_aktif)."""
    admin = _admin_service.get_by_id(admin_id)
    if admin is None:
        abort(404)

    form = EditAdminForm(
        nama_lengkap=admin.nama_lengkap,
        is_aktif=admin.is_aktif,
    )

    if form.validate_on_submit():
        try:
            _admin_service.update_admin(
                admin_id,
                nama_lengkap=form.nama_lengkap.data,
            )
            # Update is_aktif separately
            if admin.is_aktif != form.is_aktif.data:
                if form.is_aktif.data:
                    _admin_service.activate_admin(admin_id)
                else:
                    _admin_service.deactivate_admin(admin_id)

            flash("Data admin berhasil diupdate.", "success")
            return redirect(url_for("admin_management.index"))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("admin/admin/edit.html", form=form, admin=admin, reset_form=ResetPasswordAdminForm())


@admin_management_bp.route("/<admin_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(admin_id: str):
    """Reset password admin."""
    form = ResetPasswordAdminForm()
    if not form.validate_on_submit():
        flash("Password baru tidak valid (minimal 6 karakter).", "error")
        return redirect(url_for("admin_management.edit", admin_id=admin_id))

    try:
        _admin_service.reset_admin_password(admin_id, form.new_password.data)
        flash("Password admin berhasil di-reset.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_management.edit", admin_id=admin_id))


@admin_management_bp.route("/<admin_id>/activate", methods=["POST"])
@admin_required
def activate(admin_id: str):
    """Aktifkan admin yang non-aktif."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_management.index"))

    try:
        _admin_service.activate_admin(admin_id)
        flash("Admin telah diaktifkan.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_management.index"))


@admin_management_bp.route("/<admin_id>/deactivate", methods=["POST"])
@admin_required
def deactivate(admin_id: str):
    """Non-aktifkan admin."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_management.index"))

    try:
        _admin_service.deactivate_admin(admin_id)
        flash("Admin telah dinon-aktifkan.", "info")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_management.index"))


@admin_management_bp.route("/<admin_id>/delete", methods=["POST"])
@admin_required
def delete(admin_id: str):
    """Hapus admin."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_management.index"))

    try:
        _admin_service.delete_admin(admin_id)
        flash("Admin telah dihapus.", "info")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_management.index"))
