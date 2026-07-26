"""
controllers/warga_controller.py — Blueprint ``admin_warga_bp`` untuk
manajemen warga oleh admin.

Prefix URL: ``/admin/warga`` (semua route di-protect ``@admin_required``).

Routes:
  - ``GET /admin/warga``                      — daftar warga + filter status
  - ``GET /admin/warga/create``              — form create warga baru
  - ``POST /admin/warga/create``             — proses create warga
  - ``GET /admin/warga/<warga_id>``          — detail warga + riwayat
  - ``GET/POST /admin/warga/<warga_id>/edit`` — edit data warga
  - ``POST /admin/warga/<warga_id>/activate`` — aktivasi warga (data_only → aktif)
  - ``POST /admin/warga/<warga_id>/reset-password`` — reset password warga
  - ``POST /admin/warga/<warga_id>/block``   — blokir warga aktif
  - ``POST /admin/warga/<warga_id>/unblock`` — aktifkan kembali warga diblokir
  - ``POST /admin/warga/<warga_id>/delete``  — hapus warga
  - ``GET /admin/warga/import``               — halaman import bulk
  - ``POST /admin/warga/import/preview``      — preview import file
  - ``POST /admin/warga/import/process``     — proses import ke database
  - ``GET /admin/warga/template``            — download template CSV

Ref: SIPINBAR v2.0.0 - Admin-controlled account management with bulk import
"""
import os
import tempfile
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from controllers.decorators import admin_required
from services.warga_import_service import WargaImportService
from services.warga_service import WargaService


# ── Form Definitions ─────────────────────────────────────────
class CreateWargaForm(FlaskForm):
    """Form create warga baru — bisa langsung aktif atau data_only."""

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
            Regexp(r"^\d{1,3}/\d{1,3}$", message="Format RT/RW: 1/2, 01/02, atau 001/002"),
        ],
    )
    langsung_aktif = StringField(
        "Langsung Aktif",
        validators=[Optional()],
    )  # Checkbox value: "on" or None
    username = StringField(
        "Username",
        validators=[
            Optional(),
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
            Optional(),
            Length(min=6, max=72, message="Password minimal 6 karakter"),
        ],
    )


class EditWargaForm(FlaskForm):
    """Form edit data warga (tidak termasuk username/password)."""

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
            Regexp(r"^\d{1,3}/\d{1,3}$", message="Format RT/RW: 1/2, 01/02, atau 001/002"),
        ],
    )


class ActivateWargaForm(FlaskForm):
    """Form aktivasi warga — set username & password."""

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


class ResetPasswordForm(FlaskForm):
    """Form reset password warga oleh admin."""

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
admin_warga_bp = Blueprint(
    "admin_warga", __name__, url_prefix="/admin/warga"
)
_warga_service = WargaService()
_import_service = WargaImportService()


# ── Routes ───────────────────────────────────────────────────
@admin_warga_bp.route("/")
@admin_required
def index():
    """Daftar warga dengan filter status (?status=), search (?q=), dan RT (?rt=)."""
    status_filter = request.args.get("status", type=str) or None
    q_filter = request.args.get("q", type=str) or None
    rt_filter = request.args.get("rt", type=str) or None

    filters = {}
    if status_filter:
        filters["status"] = status_filter
    if q_filter:
        filters["q"] = q_filter
    if rt_filter:
        filters["rt"] = rt_filter

    try:
        warga_list = _warga_service.get_all(filters)
    except ValueError as err:
        flash(str(err), "error")
        warga_list = []

    return render_template(
        "admin/warga/list.html",
        warga_list=warga_list,
        status_filter=status_filter or "",
        q_filter=q_filter or "",
        rt_filter=rt_filter or "",
    )


@admin_warga_bp.route("/create", methods=["GET", "POST"])
@admin_required
def create():
    """Form create warga baru (bisa data_only atau langsung aktif)."""
    form = CreateWargaForm()

    if form.validate_on_submit():
        try:
            langsung_aktif = form.langsung_aktif.data == "on"

            if langsung_aktif:
                # Validasi username & password wajib untuk langsung aktif
                if not form.username.data or not form.password.data:
                    flash(
                        "Username dan password wajib diisi untuk membuat warga langsung aktif.",
                        "error",
                    )
                    return render_template("admin/warga/create.html", form=form)

                warga = _warga_service.create_active(
                    nik=form.nik.data,
                    nama_lengkap=form.nama_lengkap.data,
                    alamat=form.alamat.data,
                    telepon=form.telepon.data,
                    rt_rw=form.rt_rw.data,
                    username=form.username.data,
                    password=form.password.data,
                )
                flash(
                    f"Warga '{warga.nama_lengkap}' berhasil dibuat dengan status aktif.",
                    "success",
                )
            else:
                # Create data_only
                warga = _warga_service.create_data_only(
                    nik=form.nik.data,
                    nama_lengkap=form.nama_lengkap.data,
                    alamat=form.alamat.data,
                    telepon=form.telepon.data,
                    rt_rw=form.rt_rw.data,
                )
                flash(
                    f"Warga '{warga.nama_lengkap}' berhasil dibuat dengan status data_only. "
                    "Silakan aktivasi untuk memberikan akses login.",
                    "success",
                )

            return redirect(url_for("admin_warga.index"))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("admin/warga/create.html", form=form)


@admin_warga_bp.route("/<warga_id>")
@admin_required
def detail(warga_id: str):
    """Detail warga + riwayat peminjaman."""
    warga = _warga_service.get_by_id(warga_id)
    if warga is None:
        abort(404)

    try:
        riwayat = _warga_service.get_riwayat_peminjaman(warga_id)
    except ValueError:
        riwayat = []

    return render_template(
        "admin/warga/detail.html",
        warga=warga,
        riwayat=riwayat,
        activate_form=ActivateWargaForm(),
        reset_password_form=ResetPasswordForm(),
        confirm_form=ConfirmForm(),
    )


@admin_warga_bp.route("/<warga_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(warga_id: str):
    """Edit data warga (identitas saja, bukan username/password)."""
    warga = _warga_service.get_by_id(warga_id)
    if warga is None:
        abort(404)

    form = EditWargaForm(
        nama_lengkap=warga.nama_lengkap,
        alamat=warga.alamat,
        telepon=warga.telepon,
        rt_rw=warga.rt_rw,
    )

    if form.validate_on_submit():
        try:
            _warga_service.update_warga_data(
                warga_id,
                nama_lengkap=form.nama_lengkap.data,
                alamat=form.alamat.data,
                telepon=form.telepon.data,
                rt_rw=form.rt_rw.data,
            )
            flash("Data warga berhasil diupdate.", "success")
            return redirect(url_for("admin_warga.detail", warga_id=warga_id))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("admin/warga/edit.html", form=form, warga=warga)


@admin_warga_bp.route("/<warga_id>/activate", methods=["POST"])
@admin_required
def activate(warga_id: str):
    """Aktivasi warga dari data_only menjadi aktif (set username & password)."""
    form = ActivateWargaForm()
    if not form.validate_on_submit():
        flash("Data aktivasi tidak valid.", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _warga_service.activate_warga(
            warga_id, form.username.data, form.password.data
        )
        flash("Warga berhasil diaktivasi. Sekarang bisa login dengan username & password.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(warga_id: str):
    """Reset password warga (oleh admin)."""
    form = ResetPasswordForm()
    if not form.validate_on_submit():
        flash("Password baru tidak valid (minimal 6 karakter).", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _warga_service.reset_password(warga_id, form.new_password.data)
        flash("Password warga berhasil di-reset.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/block", methods=["POST"])
@admin_required
def block(warga_id: str):
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


@admin_warga_bp.route("/<warga_id>/unblock", methods=["POST"])
@admin_required
def unblock(warga_id: str):
    """Aktifkan kembali warga yang diblokir."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_warga.detail", warga_id=warga_id))

    try:
        _warga_service.unblock(warga_id)
        flash("Warga telah diaktifkan kembali.", "success")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.detail", warga_id=warga_id))


@admin_warga_bp.route("/<warga_id>/delete", methods=["POST"])
@admin_required
def delete(warga_id: str):
    """Hapus warga dari database."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("admin_warga.index"))

    try:
        _warga_service.delete(warga_id)
        flash("Warga telah dihapus.", "info")
    except ValueError as err:
        flash(str(err), "error")

    return redirect(url_for("admin_warga.index"))


# ── Import Routes ─────────────────────────────────────────────
@admin_warga_bp.route("/import", methods=["GET", "POST"])
@admin_required
def import_page():
    """Halaman import bulk warga dari CSV/Excel."""
    if request.method == "POST":
        # Cek apakah ada file yang diupload
        if "file" not in request.files:
            flash("Tidak ada file yang diupload.", "error")
            return render_template("admin/warga/import.html")

        file = request.files["file"]
        if file.filename == "":
            flash("Tidak ada file yang dipilih.", "error")
            return render_template("admin/warga/import.html")

        # Validasi ekstensi file
        allowed_extensions = {".csv", ".xlsx", ".xls"}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            flash(
                "Format file tidak didukung. Gunakan .csv, .xlsx, atau .xls",
                "error",
            )
            return render_template("admin/warga/import.html")

        # Simpan file temporary
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=file_ext
            ) as tmp_file:
                file.save(tmp_file.name)
                tmp_file_path = tmp_file.name

            # Redirect ke preview page
            return redirect(
                url_for("admin_warga.import_preview", file_path=tmp_file_path)
            )
        except Exception as e:
            flash(f"Gagal mengupload file: {str(e)}", "error")

    return render_template("admin/warga/import.html")


@admin_warga_bp.route("/import/preview")
@admin_required
def import_preview():
    """Preview hasil import sebelum diproses."""
    file_path = request.args.get("file_path")
    if not file_path or not os.path.exists(file_path):
        flash("File tidak ditemukan.", "error")
        return redirect(url_for("admin_warga.import_page"))

    try:
        preview = _import_service.preview_import(file_path)
        return render_template(
            "admin/warga/import_preview.html",
            preview=preview,
            file_path=file_path,
        )
    except Exception as e:
        flash(f"Gagal mempreview file: {str(e)}", "error")
        return redirect(url_for("admin_warga.import_page"))


@admin_warga_bp.route("/import/process", methods=["POST"])
@admin_required
def import_process():
    """Proses import file ke database."""
    file_path = request.form.get("file_path")
    if not file_path or not os.path.exists(file_path):
        flash("File tidak ditemukan.", "error")
        return redirect(url_for("admin_warga.import_page"))

    try:
        result = _import_service.process_import(file_path)

        # Hapus file temporary
        try:
            os.unlink(file_path)
        except:
            pass

        if result["success"]:
            flash(
                f"Import berhasil! {result['summary']['created']} warga dibuat, "
                f"{result['summary']['skipped']} dilewati (duplikat), "
                f"{result['summary']['errors']} error.",
                "success" if result["summary"]["errors"] == 0 else "warning",
            )
        else:
            flash(result["message"], "error")

        return redirect(url_for("admin_warga.index"))
    except Exception as e:
        flash(f"Gagal memproses import: {str(e)}", "error")
        return redirect(url_for("admin_warga.import_page"))


@admin_warga_bp.route("/template")
@admin_required
def download_template():
    """Download template CSV untuk import."""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".csv"
        ) as tmp_file:
            tmp_path = tmp_file.name

        # Generate template
        _import_service.generate_template_csv(tmp_path)

        # Send file
        return send_file(
            tmp_path,
            as_attachment=True,
            download_name="template_import_warga.csv",
            mimetype="text/csv",
        )
    except Exception as e:
        flash(f"Gagal generate template: {str(e)}", "error")
        return redirect(url_for("admin_warga.import_page"))
