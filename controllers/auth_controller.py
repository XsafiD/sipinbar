"""
controllers/auth_controller.py — Blueprint ``auth_bp`` untuk modul Autentikasi.

Routes:
  - ``GET/POST /login``             — form & proses login (Admin/Warga dengan username)
  - ``GET /logout``                 — hapus session, redirect ke login
  - ``GET/POST /change-password``   — ganti password untuk user yang sedang login

Session contract (di-set di sini, dibaca oleh ``decorators``):
  - ``user_id``: ID user
  - ``role``: ``'admin'`` atau ``'warga'``
  - ``nama``: nama_lengkap untuk greeting navbar

Catatan scope:
  Setelah login sukses, user di-redirect ke ``/dashboard``. Endpoint
  ``/dashboard`` dikelola oleh ``dashboard_bp`` di
  ``controllers/dashboard_controller.py``.

Ref: SIPINBAR v2.0.0 - Username-based authentication, no self-registration
"""
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import (
    DataRequired,
    Length,
    Regexp,
)

from controllers.decorators import login_required
from models import db
from models.admin import Admin
from models.warga import Warga
from services.auth_service import AuthService


# ── Form Definitions (Flask-WTF: auto CSRF + validation) ──────
class LoginForm(FlaskForm):
    """Form login — username untuk admin & warga."""

    username = StringField(
        "Username",
        validators=[DataRequired(message="Username wajib diisi")],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password wajib diisi")],
    )


class ChangePasswordForm(FlaskForm):
    """Form ganti password — user yang sedang login."""

    current_password = PasswordField(
        "Password Saat Ini",
        validators=[DataRequired(message="Password saat ini wajib diisi")],
    )
    new_password = PasswordField(
        "Password Baru",
        validators=[
            DataRequired(message="Password baru wajib diisi"),
            Length(min=6, max=72, message="Password minimal 6 karakter"),
        ],
    )
    confirm_password = PasswordField(
        "Konfirmasi Password Baru",
        validators=[
            DataRequired(message="Konfirmasi password wajib diisi"),
        ],
    )


# ── Blueprint Init ────────────────────────────────────────────
auth_bp = Blueprint("auth", __name__)
_auth_service = AuthService()


# ── Routes ────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Form & proses login untuk admin maupun warga (username-based)."""
    form = LoginForm()

    if form.validate_on_submit():
        identifier = form.username.data
        password = form.password.data

        result = _auth_service.login(identifier, password)
        if result is None:
            flash("Username atau password salah.", "error")
            return render_template("auth/login.html", form=form), 401

        user, role = result
        # Reset session lalu set key kontrak (jangan pakai session.update agar bersih)
        session.clear()
        session["user_id"] = user.id
        session["role"] = role
        session["nama"] = user.nama_lengkap

        flash(f"Selamat datang, {user.nama_lengkap}!", "success")
        # Redirect ke dashboard (dikelola oleh dashboard_bp)
        return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """Hapus session & redirect ke login."""
    session.clear()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """
    Form ganti password untuk user yang sedang login.

    Tersedia untuk admin dan warga. Memerlukan password saat ini
    untuk verifikasi sebelum mengubah ke password baru.
    """
    form = ChangePasswordForm()

    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data
        confirm_password = form.confirm_password.data

        # Validasi konfirmasi password
        if new_password != confirm_password:
            flash("Password baru dan konfirmasi password tidak cocok.", "error")
            return render_template("auth/change_password.html", form=form)

        # Get current user
        user_id = session.get("user_id")
        role = session.get("role")

        if role == "admin":
            user = db.session.get(Admin, user_id)
        else:  # warga
            user = db.session.get(Warga, user_id)

        if user is None:
            session.clear()
            flash("Sesi tidak valid. Silakan login kembali.", "error")
            return redirect(url_for("auth.login"))

        # Try change password via service
        try:
            _auth_service.change_password(user, current_password, new_password)
            flash("Password berhasil diubah.", "success")
            return redirect(url_for("dashboard.index"))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("auth/change_password.html", form=form)
