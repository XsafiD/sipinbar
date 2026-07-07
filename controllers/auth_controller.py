"""
controllers/auth_controller.py — Blueprint ``auth_bp`` untuk modul Autentikasi.

Routes:
  - ``GET/POST /login``     — form & proses login (Admin/Warga)
  - ``GET /logout``         — hapus session, redirect ke login
  - ``GET/POST /register``  — form registrasi warga baru (self-service)

Session contract (di-set di sini, dibaca oleh ``decorators``):
  - ``user_id``: ID user
  - ``role``: ``'admin'`` atau ``'warga'``
  - ``nama``: nama_lengkap untuk greeting navbar

Catatan scope:
  Setelah login sukses, user di-redirect ke ``/dashboard``. Endpoint
  ``/dashboard`` SEHARUSNYA dikelola oleh ``dashboard_bp`` (task T-FE-04
  di section 3.4). Untuk M2 §3.1, dibuat placeholder minimal di sini
  agar alur login→dashboard bisa diuji end-to-end. Frontend dev akan
  memindahkan ke ``controllers/dashboard_controller.py`` saat T-FE-04
  dikerjakan.

Refs: SRS §4.1.3 & §6.1, UI Spec SCR-01 & SCR-02, TODO T-AUTH-03
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
from wtforms import PasswordField, StringField, TextAreaField
from wtforms.validators import (
    DataRequired,
    Length,
    Regexp,
)

from controllers.decorators import login_required
from services.auth_service import AuthService


# ── Form Definitions (Flask-WTF: auto CSRF + validation) ──────
class LoginForm(FlaskForm):
    """Form login — identifier bisa username (admin) atau NIK (warga)."""

    username = StringField(
        "Username / NIK",
        validators=[DataRequired(message="Username atau NIK wajib diisi")],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password wajib diisi")],
    )


class RegisterForm(FlaskForm):
    """Form registrasi warga — status awal selalu 'menunggu'."""

    nik = StringField(
        "NIK (16 digit)",
        validators=[
            DataRequired(message="NIK wajib diisi"),
            Length(min=16, max=16, message="NIK harus tepat 16 digit"),
            Regexp(r"^\d{16}$", message="NIK harus 16 digit angka"),
        ],
    )
    nama_lengkap = StringField(
        "Nama Lengkap",
        validators=[
            DataRequired(message="Nama lengkap wajib diisi"),
            Length(max=100),
        ],
    )
    alamat = TextAreaField(
        "Alamat",
        validators=[
            DataRequired(message="Alamat wajib diisi"),
            Length(max=500),
        ],
    )
    telepon = StringField(
        "No. Telepon",
        validators=[
            DataRequired(message="Telepon wajib diisi"),
            Regexp(r"^\d{10,15}$", message="Format telepon: 10-15 digit angka"),
        ],
    )
    rt_rw = StringField(
        "RT/RW",
        validators=[
            DataRequired(message="RT/RW wajib diisi"),
            Regexp(r"^\d{3}/\d{3}$", message="Format RT/RW: 001/002"),
        ],
    )


# ── Blueprint Init ────────────────────────────────────────────
auth_bp = Blueprint("auth", __name__)
_auth_service = AuthService()


# ── Routes ────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Form & proses login untuk admin maupun warga."""
    form = LoginForm()

    if form.validate_on_submit():
        identifier = form.username.data
        password = form.password.data

        result = _auth_service.login(identifier, password)
        if result is None:
            flash("Username/NIK atau password salah.", "error")
            return render_template("auth/login.html", form=form), 401

        user, role = result
        # Reset session lalu set key kontrak (jangan pakai session.update agar bersih)
        session.clear()
        session["user_id"] = user.id
        session["role"] = role
        session["nama"] = user.nama_lengkap

        flash(f"Selamat datang, {user.nama_lengkap}!", "success")
        # Sementara redirect ke placeholder dashboard (lihat catatan scope di atas).
        # Saat dashboard_bp terdaftar dengan endpoint 'dashboard.index', ini tetap
        # berfungsi karena URL path sama. Frontend dev tinggal memindahkan handler.
        return redirect("/dashboard")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    """Hapus session & redirect ke login."""
    session.clear()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Form registrasi warga baru (self-service)."""
    form = RegisterForm()

    if form.validate_on_submit():
        try:
            warga = _auth_service.register_warga(
                {
                    "nik": form.nik.data,
                    "nama_lengkap": form.nama_lengkap.data,
                    "alamat": form.alamat.data,
                    "telepon": form.telepon.data,
                    "rt_rw": form.rt_rw.data,
                }
            )
            flash(
                f"Registrasi berhasil. NIK Anda ({warga.nik}) menunggu "
                f"verifikasi admin.",
                "success",
            )
            return redirect(url_for("auth.login"))
        except ValueError as err:
            # Pesan dari service (NIK duplikat, format salah, dll.)
            flash(str(err), "error")

    return render_template("auth/register.html", form=form)


# ── Placeholder Dashboard (sementara, akan dipindah ke dashboard_bp) ─
# Catatan: T-FE-04 (section 3.4) akan membuat dashboard_controller.py
# dengan route `/dashboard`. Endpoint di bawah ini memastikan alur auth
# bisa dites end-to-end di M2 §3.1 tanpa menunggu frontend.
@auth_bp.route("/dashboard")
@login_required
def _placeholder_dashboard():
    """Dashboard sementara — tampilkan greeting sesuai role."""
    return (
        f"<!doctype html><title>Dashboard SIPINBAR</title>"
        f"<h1>Halo, {session.get('nama', '?')}!</h1>"
        f"<p>Role: {session.get('role')}</p>"
        f"<p><em>Placeholder dashboard — akan digantikan oleh T-FE-04.</em></p>"
        f'<p><a href="{url_for("auth.logout")}">Logout</a></p>'
    )
