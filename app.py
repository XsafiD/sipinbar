"""
app.py — Entry point aplikasi SIPINBAR.

Menggunakan **Application Factory pattern** (`create_app()`) — standar
Flask untuk mendukung multiple environment (dev/test/prod) dan
memudahkan testing (bikin app instance per test).

Tanggung jawab:
  1. Muat konfigurasi
  2. Init ekstensi (SQLAlchemy)
  3. Register event listener `PRAGMA foreign_keys = ON`
  4. Register semua blueprint controller
  5. Buat tabel di first-run (opsional, seed.py juga melakukan ini)
"""
import os
from typing import Optional

from flask import Flask, jsonify, render_template, request

from config import Config
from models import db


def create_app(config_class: type = Config) -> Flask:
    """
    Application Factory — membangun instance Flask siap pakai.

    Args:
        config_class: Class konfigurasi (default: Config untuk dev).
                      Test conftest akan pass TestConfig.

    Returns:
        Instance Flask yang sudah dikonfigurasi + DB ter-init.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Catatan: pembuatan folder database & resolve path dilakukan di config.py
    # sehingga konsisten di semua entry-point (app.py, seed.py, tests).

    # ── Init Ekstensi ─────────────────────────────────────────
    db.init_app(app)

    # ── SQLite: Aktifkan Foreign Key enforcement ──────────────
    # Secara default SQLite NON-aktifkan FK constraint. Kita paksa ON
    # via event listener setiap koneksi baru.
    _enable_sqlite_fk_pragma(app)

    # ── Register Blueprints ───────────────────────────────────
    # Dichecked-import di dalam fungsi agar tidak crash saat modul
    # controller belum ada (M1 masih foundation — belum semua controller
    # diimplementasi oleh Dev 2-6).
    _register_blueprints(app)

    # ── Register CLI Commands ─────────────────────────────────
    _register_cli_commands(app)

    # ── Health Check Route ────────────────────────────────────
    @app.route("/health")
    def health_check():
        """Endpoint health check untuk verifikasi server berjalan."""
        return jsonify(
            status="ok",
            app="sipinbar",
            version="0.1.0",
        )

    # ── Error Handlers ────────────────────────────────────────
    # Render halaman error HTML yang ramah pengguna (T-FE-14, handoff Q-14).
    # JSON response tetap dipertahankan untuk request API/JSON (mis. /health
    # tidak memicu error handler selama sukses 200).
    @app.errorhandler(404)
    def not_found(err):
        if _wants_json():
            return jsonify(status="error", error="not_found",
                           message=str(err) or "Halaman tidak ditemukan"), 404
        return render_template(
            "error.html",
            error_code=404,
            error_title="Halaman Tidak Ditemukan",
            error_message="Maaf, halaman yang Anda cari tidak tersedia atau telah dipindahkan.",
        ), 404

    @app.errorhandler(403)
    def forbidden(err):
        if _wants_json():
            return jsonify(status="error", error="forbidden",
                           message="Akses ditolak"), 403
        return render_template(
            "error.html",
            error_code=403,
            error_title="Akses Ditolak",
            error_message="Anda tidak memiliki izin untuk mengakses halaman ini.",
        ), 403

    @app.errorhandler(500)
    def server_error(err):
        app.logger.exception("Internal server error: %s", err)
        if _wants_json():
            return jsonify(status="error", error="internal_error",
                           message="Server error"), 500
        return render_template(
            "error.html",
            error_code=500,
            error_title="Kesalahan Server",
            error_message="Terjadi kesalahan internal di server. Tim kami telah diberi notifikasi.",
        ), 500

    return app


def _wants_json() -> bool:
    """Heuristik apakah request ini mengharapkan respons JSON.

    Dipakai error handler untuk memilih antara HTML template (browser) atau
    JSON payload (API client / test client yang set Accept: application/json).
    """
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and request.accept_mimetypes[best] > \
        request.accept_mimetypes["text/html"]


def _enable_sqlite_fk_pragma(app: Flask) -> None:
    """Pasang event listener untuk `PRAGMA foreign_keys = ON` di tiap koneksi."""

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """
        Untuk SQLite, jalankan `PRAGMA foreign_keys = ON` di setiap
        koneksi baru. Non-SQLite engine diabaikan.
        """
        # Cek apakah koneksi adalah SQLite (sqlite3 module)
        if dbapi_connection.__class__.__module__.startswith("sqlite3"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()


def _register_blueprints(app: Flask) -> None:
    """
    Register semua Flask Blueprint dari folder controllers/.

    Import dilakukan di dalam try/except agar foundation (M1) tidak
    crash kalau modul controller belum dibuat oleh dev lain.
    """
    # Mapping blueprint → modul (diisi bertahap seiring progress milestone)
    blueprint_modules = [
        ("controllers.dashboard_controller", "dashboard_bp"),
        ("controllers.auth_controller", "auth_bp"),
        ("controllers.barang_controller", "barang_bp"),
        ("controllers.peminjaman_controller", "peminjaman_bp"),
        ("controllers.warga_controller", "admin_warga_bp"),
        ("controllers.laporan_controller", "laporan_bp"),
    ]

    for module_name, attr_name in blueprint_modules:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            bp = getattr(module, attr_name, None)
            if bp is not None:
                app.register_blueprint(bp)
                app.logger.info("Blueprint '%s' registered", module_name)
        except ImportError:
            # Modul belum ada — skip (M1 wajar belum ada semua controller)
            app.logger.debug("Blueprint '%s' belum tersedia, skip", module_name)


def _register_cli_commands(app: Flask) -> None:
    """
    Register Flask CLI commands (dipanggil via ``flask <command>``).

    Command yang tersedia:
      - ``flask send-reminders`` — jalankan scheduler pengingat H-1
        jatuh tempo peminjaman (BR-07). Didesain dijalankan via cron
        job, mis. setiap jam 8 pagi.
    """
    import click

    @app.cli.command("send-reminders")
    def send_reminders_command():
        """
        Kirim pengingat H-1 untuk peminjaman yang jatuh tempo besok.

        Idempoten: aman dipanggil berkali-kali dalam sehari (anti-spam
        di level service). Output: jumlah pengingat yang terkirim.

        Cron job rekomendasi (MVP):
            0 8 * * *  cd /path/to/sipinbar && flask send-reminders
        """
        from services.notifikasi_service import NotifikasiService

        try:
            jumlah = NotifikasiService().check_and_send_reminders()
            click.echo(
                f"✓ Pengingat terkirim: {jumlah} peminjaman jatuh tempo besok."
            )
        except Exception as err:  # pragma: no cover — defensive
            app.logger.exception("send-reminders failed: %s", err)
            click.echo(f"✗ Error: {err}", err=True)
            raise


# ── CLI entry point (python app.py) ───────────────────────────
if __name__ == "__main__":
    app = create_app()
    # Host 0.0.0.0 agar bisa diakses dari device lain di jaringan lokal
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", 5000)),
        debug=app.config.get("FLASK_DEBUG", True),
    )
