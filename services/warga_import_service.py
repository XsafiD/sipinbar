"""
services/warga_import_service.py — Bulk import warga dari CSV/Excel.

Service ini menangani import bulk data warga dari file CSV atau Excel.
Semua warga yang diimport akan memiliki status 'data_only' (master data).

Pilar OOP:
  - **Encapsulation**: logic validasi & import disembunyikan di service
  - **Abstraction**: controller hanya perlu call `process_import()` tanpa
    tahu detail parsing file CSV/Excel

Ref: SIPINBAR v2.0.0 - Bulk import warga data
"""
import os
import re
from typing import Dict, List, Tuple

import pandas as pd

from models import db
from models.warga import Warga


# ── Validator format ────────────────────────────────────────────
NIK_PATTERN = re.compile(r"^\d{16}$")
TELEPON_PATTERN = re.compile(r"^\d{10,15}$")
RT_RW_PATTERN = re.compile(r"^\d{1,3}/\d{1,3}$")  # Lebih fleksibel: 1/2, 01/02, 001/002


class WargaImportService:
    """Service layer untuk bulk import warga dari CSV/Excel."""

    REQUIRED_COLUMNS = ["nik", "nama_lengkap", "alamat", "telepon", "rt_rw"]
    MAX_PREVIEW_ROWS = 10

    # ── File Validation ─────────────────────────────────────────
    def validate_file(self, file_path: str) -> Dict:
        """
        Validasi format file CSV/Excel.

        Args:
            file_path: Path ke file yang akan divalidasi

        Returns:
            Dict dengan keys:
            - valid: bool
            - message: str (pesan error atau sukses)
            - file_type: str ('csv' atau 'excel')
            - total_rows: int (jumlah baris data)
        """
        if not os.path.exists(file_path):
            return {
                "valid": False,
                "message": f"File tidak ditemukan: {file_path}",
                "file_type": None,
                "total_rows": 0,
            }

        # Cek ekstensi file
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in [".csv", ".xlsx", ".xls"]:
            return {
                "valid": False,
                "message": "Format file tidak didukung. Gunakan .csv, .xlsx, atau .xls",
                "file_type": None,
                "total_rows": 0,
            }

        # Baca file berdasarkan ekstensi
        try:
            if ext == ".csv":
                df = pd.read_csv(file_path)
                file_type = "csv"
            else:  # .xlsx atau .xls
                df = pd.read_excel(file_path)
                file_type = "excel"
        except Exception as e:
            return {
                "valid": False,
                "message": f"Gagal membaca file: {str(e)}",
                "file_type": None,
                "total_rows": 0,
            }

        # Cek kolom wajib
        missing_cols = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing_cols:
            return {
                "valid": False,
                "message": f"Kolom wajib tidak lengkap: {', '.join(missing_cols)}",
                "file_type": file_type,
                "total_rows": len(df),
            }

        # Validasi baris kosong
        if len(df) == 0:
            return {
                "valid": False,
                "message": "File tidak memiliki data (kosong)",
                "file_type": file_type,
                "total_rows": 0,
            }

        return {
            "valid": True,
            "message": "File valid",
            "file_type": file_type,
            "total_rows": len(df),
        }

    # ── Preview Import ─────────────────────────────────────────
    def preview_import(self, file_path: str) -> Dict:
        """
        Preview hasil import sebelum diproses.

        Args:
            file_path: Path ke file yang akan di-preview

        Returns:
            Dict dengan keys:
            - valid: bool
            - message: str
            - total_rows: int
            - valid_rows: List[dict] (baris valid, max 10)
            - invalid_rows: List[dict] (baris invalid dengan alasan)
            - summary: Dict (ringkasan valid/invalid/duplicate)
        """
        # Validasi file dulu
        validation = self.validate_file(file_path)
        if not validation["valid"]:
            return validation

        # Baca file
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        # Process setiap baris
        valid_rows = []
        invalid_rows = []
        duplicate_nik = []

        for idx, row in df.iterrows():
            result = self._validate_row(row.to_dict(), idx + 1)
            if result["valid"]:
                # Cek duplikasi NIK dengan existing data di DB
                existing = Warga.query.filter_by(nik=result["data"]["nik"]).first()
                if existing:
                    duplicate_nik.append(
                        {
                            "row": idx + 1,
                            "nik": result["data"]["nik"],
                            "nama": result["data"]["nama_lengkap"],
                            "reason": "NIK sudah terdaftar",
                        }
                    )
                else:
                    valid_rows.append(result["data"])
                    if len(valid_rows) >= self.MAX_PREVIEW_ROWS:
                        break
            else:
                invalid_rows.append(result)

        # Summary
        total_valid = len(valid_rows) + len(
            [r for r in range(len(df)) if r not in [i["row"] - 1 for i in invalid_rows]]
        )
        # Recalculate properly
        total_valid = 0
        for idx, row in df.iterrows():
            result = self._validate_row(row.to_dict(), idx + 1)
            if result["valid"]:
                existing = Warga.query.filter_by(nik=result["data"]["nik"]).first()
                if not existing:
                    total_valid += 1

        return {
            "valid": True,
            "message": "Preview berhasil",
            "total_rows": len(df),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows[: self.MAX_PREVIEW_ROWS],
            "duplicate_nik": duplicate_nik[: self.MAX_PREVIEW_ROWS],
            "summary": {
                "total": len(df),
                "valid": total_valid,
                "invalid": len(invalid_rows),
                "duplicate": len(duplicate_nik),
            },
        }

    # ── Validate Single Row ─────────────────────────────────────
    def _validate_row(self, row: Dict, row_num: int = 1) -> Dict:
        """
        Validasi satu baris data warga.

        Args:
            row: Dict data warga
            row_num: Nomor baris (untuk error message)

        Returns:
            Dict dengan keys:
            - valid: bool
            - data: dict (data yang sudah divalidasi)
            - reason: str (alasan jika invalid)
            - row: int (nomor baris)
        """
        # Trim semua values
        data = {k: str(v).strip() if pd.notna(v) else "" for k, v in row.items()}

        # Validasi NIK
        nik = data.get("nik", "")
        if not NIK_PATTERN.match(nik):
            return {
                "valid": False,
                "data": None,
                "reason": "NIK harus 16 digit angka",
                "row": row_num,
            }

        # Validasi nama
        nama_lengkap = data.get("nama_lengkap", "")
        if not nama_lengkap or len(nama_lengkap) < 3:
            return {
                "valid": False,
                "data": None,
                "reason": "Nama lengkap minimal 3 karakter",
                "row": row_num,
            }

        # Validasi alamat
        alamat = data.get("alamat", "")
        if not alamat or len(alamat) < 5:
            return {
                "valid": False,
                "data": None,
                "reason": "Alamat minimal 5 karakter",
                "row": row_num,
            }

        # Validasi telepon
        telepon = data.get("telepon", "")
        if not TELEPON_PATTERN.match(telepon):
            return {
                "valid": False,
                "data": None,
                "reason": "Telepon harus 10-15 digit angka",
                "row": row_num,
            }

        # Validasi RT/RW
        rt_rw = data.get("rt_rw", "")
        if not RT_RW_PATTERN.match(rt_rw):
            return {
                "valid": False,
                "data": None,
                "reason": "Format RT/RW tidak valid (contoh: 1/2, 01/02, 001/002)",
                "row": row_num,
            }

        # Return valid data
        return {
            "valid": True,
            "data": {
                "nik": nik,
                "nama_lengkap": nama_lengkap,
                "alamat": alamat,
                "telepon": telepon,
                "rt_rw": rt_rw,
            },
            "reason": None,
            "row": row_num,
        }

    # ── Process Import ─────────────────────────────────────────
    def process_import(self, file_path: str) -> Dict:
        """
        Proses import data warga dari file ke database.

        Args:
            file_path: Path ke file yang akan diimport

        Returns:
            Dict dengan keys:
            - success: bool
            - message: str
            - summary: Dict (ringkasan import)
            - created: List[Warga] (list warga yang berhasil dibuat)
        """
        # Validasi file dulu
        validation = self.validate_file(file_path)
        if not validation["valid"]:
            return {
                "success": False,
                "message": validation["message"],
                "summary": None,
                "created": [],
            }

        # Baca file
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)

        # Process setiap baris
        created = []
        skipped = []
        errors = []

        for idx, row in df.iterrows():
            validation = self._validate_row(row.to_dict(), idx + 1)

            if not validation["valid"]:
                errors.append(
                    {"row": idx + 1, "reason": validation["reason"]}
                )
                continue

            data = validation["data"]

            # Cek duplikasi NIK
            existing = Warga.query.filter_by(nik=data["nik"]).first()
            if existing:
                skipped.append(
                    {
                        "row": idx + 1,
                        "nik": data["nik"],
                        "reason": "NIK sudah terdaftar",
                    }
                )
                continue

            # Create warga dengan status data_only
            try:
                warga = Warga(
                    nik=data["nik"],
                    nama_lengkap=data["nama_lengkap"],
                    alamat=data["alamat"],
                    telepon=data["telepon"],
                    rt_rw=data["rt_rw"],
                    status="data_only",
                )
                db.session.add(warga)
                created.append(warga)
            except Exception as e:
                errors.append(
                    {"row": idx + 1, "reason": f"Database error: {str(e)}"}
                )

        # Commit semua transaction
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {
                "success": False,
                "message": f"Gagal menyimpan ke database: {str(e)}",
                "summary": None,
                "created": [],
            }

        return {
            "success": True,
            "message": "Import berhasil",
            "summary": {
                "total": len(df),
                "created": len(created),
                "skipped": len(skipped),
                "errors": len(errors),
            },
            "created": created,
        }

    # ── Generate Template ─────────────────────────────────────
    def generate_template_csv(self, output_path: str) -> None:
        """
        Generate template CSV untuk import.

        Args:
            output_path: Path untuk menyimpan template CSV
        """
        template_data = pd.DataFrame(
            columns=[
                "nik",
                "nama_lengkap",
                "alamat",
                "telepon",
                "rt_rw",
            ]
        )
        # Tambahkan contoh data
        template_data.loc[0] = [
            "3201010101900001",
            "Contoh Warga",
            "Jl. Contoh No. 123",
            "081234567890",
            "001/002",
        ]
        template_data.to_csv(output_path, index=False)

    # ── Get Required Columns ───────────────────────────────────
    def get_required_columns(self) -> List[str]:
        """Return list kolom wajib untuk import."""
        return self.REQUIRED_COLUMNS.copy()
