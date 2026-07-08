# ============================================================
# Dockerfile — SIPINBAR (Demo/Grading Mode)
# ============================================================
# Python 3.12 Flask + SQLite, single-stage, Flask dev server.
# Build: docker compose build
# Run:   docker compose up
# ============================================================
FROM python:3.12-slim

# Python runtime: jangan tulis .pyc, flush stdout/stderr (log real-time)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=app.py
    # CATATAN: FLASK_DEBUG TIDAK di-set di sini.
    # Diturunkan dari compose environment (default 0 / production-safe).

WORKDIR /app

# Install dependency dulu (layer cache — code change tidak re-install pip)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy kode aplikasi (.dockerignore memfilter sisanya)
COPY . .

# Pastikan folder untuk bind mount ada (no-op jika sudah ada via mount)
RUN mkdir -p database static/img

# Port Flask
EXPOSE 5000

# Seed database (idempoten → aman setiap startup) lalu jalankan Flask.
# --host=0.0.0.0 WAJIB agar container reachable dari host.
CMD ["sh", "-c", "python seed.py && flask run --host=0.0.0.0 --port=5000"]
