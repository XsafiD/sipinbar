"""
controllers/decorators.py — Decorator proteksi endpoint berbasis session.

Dua decorator utama:
  - ``login_required``: endpoint hanya bisa diakses user yang sudah login.
    Jika belum → redirect ke ``/login`` + flash error.
  - ``admin_required``: endpoint hanya bisa diakses admin.
    Jika belum login → redirect ke ``/login``.
    Jika login sebagai warga → HTTP 403 Forbidden.

Session contract (di-set oleh ``auth_controller.login``):
  - ``session['user_id']``: ID user (UUID)
  - ``session['role']``: ``'admin'`` atau ``'warga'``
  - ``session['nama']``: Nama untuk ditampilkan di navbar

Refs: TODO T-AUTH-05, SRS §6.1 (Role-based access)
"""
from functools import wraps

from flask import abort, flash, redirect, session, url_for


def login_required(f):
    """Redirect ke /login jika user belum terautentikasi."""

    @wraps(f)
    def _wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Anda harus login terlebih dahulu.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return _wrapper


def admin_required(f):
    """
    Proteksi endpoint khusus admin.

    - Belum login → redirect ke /login + flash.
    - Login sebagai warga → HTTP 403.
    - Login sebagai admin → lanjut.
    """

    @wraps(f)
    def _wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Anda harus login terlebih dahulu.", "error")
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            abort(403)  # warga mencoba akses endpoint admin
        return f(*args, **kwargs)

    return _wrapper
