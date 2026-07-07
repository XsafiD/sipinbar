"""
controllers/peminjaman_controller.py — Blueprint ``peminjaman_bp`` untuk
modul Peminjaman.

Prefix URL: ``/peminjaman``.

Routes:
  - ``GET  /peminjaman/``                       — daftar peminjaman (filter status)
  - ``GET  /peminjaman/<peminjaman_id>``        — detail peminjaman
  - ``GET/POST /peminjaman/ajukan``             — form ajukan peminjaman (warga)
  - ``POST /peminjaman/<id>/setujui``           — admin setujui (CSRF-only)
  - ``POST /peminjaman/<id>/tolak``             — admin tolak (dengan alasan)
  - ``POST /peminjaman/<id>/pinjam``            — admin tandai dipinjam
  - ``GET/POST /peminjaman/<id>/kembalikan``    — form proses pengembalian (admin)

Akses:
  - Daftar & detail: ``@login_required`` (admin & warga). Warga hanya lihat
    peminjaman miliknya; admin lihat semua.
  - Ajukan: ``@login_required`` + harus warga (admin → 403).
  - Setujui/tolak/pinjam/kembalikan: ``@admin_required`` (warga → 403).

Refs: SRS §4.3.3 & §6.1, UI Spec SCR-08..SCR-11, TODO T-PJM-03
"""
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from controllers.decorators import admin_required, login_required
from models.barang import Barang
from models.peminjaman import KONDISI_KEMBALI, STATUS_PEMINJAMAN
from services.peminjaman_service import PeminjamanService


# ── Form Definitions (Flask-WTF: auto CSRF + validation) ──────
class AjukanPeminjamanForm(FlaskForm):
    """Form pengajuan peminjaman oleh warga.

    Item (barang + jumlah) di-parse manual dari ``request.form`` agar
    mendukung jumlah baris dinamis (JS tambah baris di sisi UI).
    """

    tanggal_pinjam = DateField(
        "Tanggal Pinjam",
        format="%Y-%m-%d",
        validators=[DataRequired(message="Tanggal pinjam wajib diisi")],
    )
    tanggal_kembali = DateField(
        "Tanggal Kembali",
        format="%Y-%m-%d",
        validators=[DataRequired(message="Tanggal kembali wajib diisi")],
    )
    catatan = TextAreaField(
        "Catatan",
        validators=[Optional(), Length(max=1000)],
    )


class RejectForm(FlaskForm):
    """Form penolakan peminjaman oleh admin (alasan wajib)."""

    alasan = TextAreaField(
        "Alasan Penolakan",
        validators=[
            DataRequired(message="Alasan penolakan wajib diisi"),
            Length(max=500),
        ],
    )


class ConfirmForm(FlaskForm):
    """Form kosong — hanya CSRF protection untuk aksi singkat."""

    pass


# ── Blueprint Init ────────────────────────────────────────────
peminjaman_bp = Blueprint("peminjaman", __name__, url_prefix="/peminjaman")
_peminjaman_service = PeminjamanService()


def _warga_id_from_session() -> str:
    """Return user_id dari session (warga yang sedang login)."""
    return session.get("user_id")


def _parse_items_from_form() -> list:
    """
    Parse daftar item dari form POST.

    Form mengirim multiple input dengan ``name="barang_id"`` dan
    ``name="jumlah"``. Input kosong di-skip.
    """
    barang_ids = request.form.getlist("barang_id")
    jumlahs = request.form.getlist("jumlah")
    items = []
    for bid, jum in zip(barang_ids, jumlahs):
        bid = (bid or "").strip()
        if not bid:
            continue
        try:
            jum_int = int(jum) if jum else 0
        except ValueError:
            jum_int = 0
        if jum_int <= 0:
            continue
        items.append({"barang_id": bid, "jumlah": jum_int})
    return items


# ── Routes ────────────────────────────────────────────────────
@peminjaman_bp.route("/")
@login_required
def index():
    """Daftar peminjaman. Warga lihat miliknya, admin lihat semua."""
    filters = {
        "status": request.args.get("status", type=str) or None,
        "q": request.args.get("q", type=str) or None,
    }

    # Warga hanya lihat peminjaman sendiri (filter paksa)
    if session.get("role") == "warga":
        filters["warga_id"] = _warga_id_from_session()
    else:
        # Admin boleh filter per warga
        warga_id = request.args.get("warga_id", type=str) or None
        if warga_id:
            filters["warga_id"] = warga_id

    try:
        peminjaman_list = _peminjaman_service.get_all(filters)
    except ValueError as err:
        flash(str(err), "error")
        peminjaman_list = []

    return render_template(
        "peminjaman/index.html",
        peminjaman_list=peminjaman_list,
        status_filter=filters.get("status") or "",
        q_filter=filters.get("q") or "",
        status_options=STATUS_PEMINJAMAN,
    )


@peminjaman_bp.route("/<peminjaman_id>")
@login_required
def detail(peminjaman_id: str):
    """Detail peminjaman."""
    peminjaman = _peminjaman_service.get_by_id(peminjaman_id)
    if peminjaman is None:
        abort(404)

    # Warga tidak boleh lihat peminjaman milik warga lain
    if (
        session.get("role") == "warga"
        and peminjaman.warga_id != _warga_id_from_session()
    ):
        abort(403)

    return render_template(
        "peminjaman/detail.html",
        peminjaman=peminjaman,
        reject_form=RejectForm(),
        confirm_form=ConfirmForm(),
        kondisi_options=KONDISI_KEMBALI,
    )


@peminjaman_bp.route("/ajukan", methods=["GET", "POST"])
@login_required
def ajukan():
    """Form ajukan peminjaman baru (warga only)."""
    # Hanya warga yang boleh mengajukan
    if session.get("role") != "warga":
        abort(403)

    form = AjukanPeminjamanForm()

    if form.validate_on_submit():
        items = _parse_items_from_form()
        try:
            peminjaman = _peminjaman_service.ajukan(
                warga_id=_warga_id_from_session(),
                items=items,
                tgl_pinjam=form.tanggal_pinjam.data,
                tgl_kembali=form.tanggal_kembali.data,
                catatan=form.catatan.data,
            )
            flash(
                f"Peminjaman {peminjaman.kode_peminjaman} berhasil diajukan. "
                f"Menunggu persetujuan admin.",
                "success",
            )
            return redirect(
                url_for("peminjaman.detail", peminjaman_id=peminjaman.id)
            )
        except ValueError as err:
            flash(str(err), "error")

    # Daftar barang tersedia untuk dropdown pilihan
    barang_list = (
        Barang.query.filter(Barang.deleted_at.is_(None))
        .filter(Barang.status.in_(("tersedia", "dipinjam")))
        .order_by(Barang.nama.asc())
        .all()
    )
    return render_template(
        "peminjaman/form_ajukan.html", form=form, barang_list=barang_list
    )


@peminjaman_bp.route("/<peminjaman_id>/setujui", methods=["POST"])
@admin_required
def setujui(peminjaman_id: str):
    """Admin setujui peminjaman."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))

    try:
        peminjaman = _peminjaman_service.setujui(
            peminjaman_id, admin_id=session["user_id"]
        )
        flash(
            f"Peminjaman {peminjaman.kode_peminjaman} disetujui.",
            "success",
        )
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))


@peminjaman_bp.route("/<peminjaman_id>/tolak", methods=["POST"])
@admin_required
def tolak(peminjaman_id: str):
    """Admin tolak peminjaman (dengan alasan)."""
    form = RejectForm()
    if not form.validate_on_submit():
        flash("Alasan penolakan wajib diisi.", "error")
        return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))

    try:
        peminjaman = _peminjaman_service.tolak(
            peminjaman_id,
            admin_id=session["user_id"],
            alasan=form.alasan.data,
        )
        flash(
            f"Peminjaman {peminjaman.kode_peminjaman} ditolak.",
            "info",
        )
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))


@peminjaman_bp.route("/<peminjaman_id>/pinjam", methods=["POST"])
@admin_required
def pinjam(peminjaman_id: str):
    """Admin tandai barang sudah diserahkan (disetujui → dipinjam)."""
    form = ConfirmForm()
    if not form.validate_on_submit():
        flash("Token CSRF tidak valid.", "error")
        return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))

    try:
        peminjaman = _peminjaman_service.mulai_pinjam(peminjaman_id)
        flash(
            f"Peminjaman {peminjaman.kode_peminjaman} berstatus 'Dipinjam'.",
            "success",
        )
    except ValueError as err:
        flash(str(err), "error")
    return redirect(url_for("peminjaman.detail", peminjaman_id=peminjaman_id))


@peminjaman_bp.route("/<peminjaman_id>/kembalikan", methods=["GET", "POST"])
@admin_required
def kembalikan(peminjaman_id: str):
    """Admin proses pengembalian barang."""
    peminjaman = _peminjaman_service.get_by_id(peminjaman_id)
    if peminjaman is None:
        abort(404)

    form = ConfirmForm()

    if form.validate_on_submit():
        # Parse kondisi_kembali per barang dari form
        # Field name: kondisi_<barang_id>
        kondisi_map = {}
        for detail in peminjaman.detail_list:
            key = f"kondisi_{detail.barang_id}"
            val = request.form.get(key, "baik")
            kondisi_map[detail.barang_id] = val

        try:
            result = _peminjaman_service.proses_pengembalian(
                peminjaman_id, kondisi_map=kondisi_map
            )
            if result["terlambat"]:
                flash(
                    f"Pengembalian terlambat {result['hari_terlambat']} hari. "
                    f"Denda: Rp {result['denda']:,}.",
                    "warning",
                )
            else:
                flash(
                    f"Pengembalian tepat waktu. Denda: Rp {result['denda']:,}.",
                    "success",
                )
            return redirect(
                url_for("peminjaman.detail", peminjaman_id=peminjaman_id)
            )
        except ValueError as err:
            flash(str(err), "error")

    return render_template(
        "peminjaman/form_kembalikan.html",
        peminjaman=peminjaman,
        form=form,
        kondisi_options=KONDISI_KEMBALI,
    )
