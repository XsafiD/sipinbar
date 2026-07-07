"""
controllers/barang_controller.py — Blueprint ``barang_bp`` untuk modul
Inventaris Barang.

Prefix URL: ``/barang`` (semua route butuh minimal ``@login_required``).
Route tambah/edit/hapus ditambah ``@admin_required``.

Routes:
  - ``GET /barang/``                    — katalog barang + filter/search
  - ``GET /barang/<barang_id>``         — detail barang
  - ``GET/POST /barang/tambah``         — form tambah barang (admin)
  - ``GET/POST /barang/<barang_id>/edit`` — form edit barang (admin)
  - ``POST /barang/<barang_id>/hapus``  — soft delete barang (admin)

Query string yang didukung di katalog:
  - ``?q=<keyword>``        — search by nama
  - ``?kategori=<id>``      — filter by kategori
  - ``?status=<status>``    — filter by status barang

Akses:
  - Katalog & detail: login_required (admin & warga lihat)
  - Tambah/edit/hapus: admin_required (warga → 403)

Refs: SRS §4.2.3 & §6.1, UI Spec SCR-04..SCR-07, TODO T-BRG-02
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
from wtforms import (
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from controllers.decorators import admin_required, login_required
from models.barang import Kategori, KONDISI_BARANG, STATUS_BARANG
from services.barang_service import BarangService


# ── Form Definitions (Flask-WTF: auto CSRF + validation) ──────
class BarangForm(FlaskForm):
    """Form tambah & edit barang (reusable — mode ditentukan controller)."""

    nama = StringField(
        "Nama Barang",
        validators=[
            DataRequired(message="Nama barang wajib diisi"),
            Length(max=100, message="Nama maksimal 100 karakter"),
        ],
    )
    kategori_id = SelectField(
        "Kategori",
        coerce=str,
        validators=[DataRequired(message="Kategori wajib dipilih")],
    )
    jumlah = IntegerField(
        "Jumlah Unit",
        validators=[
            DataRequired(message="Jumlah unit wajib diisi"),
            NumberRange(min=1, message="Jumlah unit minimal 1"),
        ],
    )
    kondisi = SelectField(
        "Kondisi",
        choices=[(k, k.replace("_", " ").title()) for k in KONDISI_BARANG],
        validators=[DataRequired(message="Kondisi wajib dipilih")],
    )
    status = SelectField(
        "Status",
        choices=[(s, s.title()) for s in STATUS_BARANG if s != "dihapus"],
        validators=[DataRequired(message="Status wajib dipilih")],
    )
    deskripsi = TextAreaField(
        "Deskripsi",
        validators=[Optional(), Length(max=2000)],
    )


class ConfirmForm(FlaskForm):
    """Form kosong — hanya untuk CSRF protection pada aksi singkat (hapus)."""

    pass


# ── Blueprint Init ────────────────────────────────────────────
barang_bp = Blueprint("barang", __name__, url_prefix="/barang")
_barang_service = BarangService()


def _populate_kategori_choices(form: BarangForm) -> None:
    """Isi dropdown kategori dari DB (dipanggil sebelum render form)."""
    kategori_list = Kategori.query.order_by(Kategori.nama.asc()).all()
    form.kategori_id.choices = [("", "-- Pilih Kategori --")] + [
        (k.id, k.nama) for k in kategori_list
    ]


# ── Routes ────────────────────────────────────────────────────
@barang_bp.route("/")
@login_required
def index():
    """Katalog barang — search, filter kategori, filter status."""
    filters = {
        "q": request.args.get("q", type=str) or None,
        "kategori": request.args.get("kategori", type=str) or None,
        "status": request.args.get("status", type=str) or None,
    }

    try:
        barang_list = _barang_service.get_all(filters)
    except ValueError as err:
        flash(str(err), "error")
        barang_list = []

    kategori_list = Kategori.query.order_by(Kategori.nama.asc()).all()
    return render_template(
        "barang/index.html",
        barang_list=barang_list,
        kategori_list=kategori_list,
        q_filter=filters["q"] or "",
        kategori_filter=filters["kategori"] or "",
        status_filter=filters["status"] or "",
    )


@barang_bp.route("/<barang_id>")
@login_required
def detail(barang_id: str):
    """Detail barang."""
    barang = _barang_service.get_by_id(barang_id)
    if barang is None:
        abort(404)
    return render_template(
        "barang/detail.html",
        barang=barang,
        confirm_form=ConfirmForm(),
    )


@barang_bp.route("/tambah", methods=["GET", "POST"])
@admin_required
def tambah():
    """Form tambah barang (admin only)."""
    form = BarangForm()
    _populate_kategori_choices(form)

    if form.validate_on_submit():
        try:
            barang = _barang_service.tambah(
                {
                    "nama": form.nama.data,
                    "kategori_id": form.kategori_id.data,
                    "jumlah": form.jumlah.data,
                    "kondisi": form.kondisi.data,
                    "status": form.status.data,
                    "deskripsi": form.deskripsi.data,
                }
            )
            # Upload foto opsional
            foto = request.files.get("foto")
            if foto and foto.filename:
                try:
                    _barang_service.upload_foto(barang.id, foto)
                except ValueError as err:
                    flash(f"Barang tersimpan tapi foto gagal: {err}", "warning")
            flash(f"Barang '{barang.nama}' berhasil ditambahkan.", "success")
            return redirect(url_for("barang.detail", barang_id=barang.id))
        except ValueError as err:
            flash(str(err), "error")

    return render_template("barang/form.html", form=form, mode="create")


@barang_bp.route("/<barang_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(barang_id: str):
    """Form edit barang (admin only)."""
    barang = _barang_service.get_by_id(barang_id)
    if barang is None:
        abort(404)

    form = BarangForm()
    _populate_kategori_choices(form)

    if form.validate_on_submit():
        try:
            data = {
                "nama": form.nama.data,
                "kategori_id": form.kategori_id.data,
                "jumlah": form.jumlah.data,
                "kondisi": form.kondisi.data,
                "status": form.status.data,
                "deskripsi": form.deskripsi.data,
            }
            foto = request.files.get("foto")
            if foto and foto.filename:
                try:
                    _barang_service.upload_foto(barang_id, foto)
                except ValueError as err:
                    flash(f"Data tersimpan tapi foto gagal: {err}", "warning")
            updated = _barang_service.edit(barang_id, data)
            flash(f"Barang '{updated.nama}' berhasil diupdate.", "success")
            return redirect(url_for("barang.detail", barang_id=updated.id))
        except ValueError as err:
            flash(str(err), "error")
    else:
        # Pre-fill form dari data barang (GET atau POST yang gagal validasi)
        if request.method == "GET":
            form.nama.data = barang.nama
            form.kategori_id.data = barang.kategori_id
            form.jumlah.data = barang.jumlah_unit
            form.kondisi.data = barang.kondisi
            form.status.data = barang.status if barang.status != "dihapus" else "tersedia"
            form.deskripsi.data = barang.deskripsi or ""

    return render_template(
        "barang/form.html", form=form, mode="edit", barang=barang
    )


@barang_bp.route("/<barang_id>/hapus", methods=["POST"])
@admin_required
def hapus(barang_id: str):
    """Soft-delete barang (admin only)."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("barang.detail", barang_id=barang_id))

    try:
        _barang_service.hapus(barang_id)
        flash("Barang telah dihapus (soft delete).", "info")
        return redirect(url_for("barang.index"))
    except ValueError as err:
        flash(str(err), "error")
        return redirect(url_for("barang.detail", barang_id=barang_id))
