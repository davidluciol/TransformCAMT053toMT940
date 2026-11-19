# -*- coding: utf-8 -*-
"""Confirmación final del CLI como proceso real (Checkpoint Final / SPEC §9).

Ejecuta `camt_to_mt940.py` con `subprocess` en la forma exacta del criterio
de éxito 1 de SPEC §9 (`python camt_to_mt940.py -i <dir> -o <dir>`), desde un
cwd ajeno al repo para probar que el script resuelve `Library/` por su propia
ruta, no por el directorio de trabajo.

Cubre lo que los tests de integración no pueden: `main()`, argparse, código de
salida a nivel de SO y ausencia de BOM en las salidas generadas (SPEC §8).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _pathfix  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
REAL_CAMT = FIXTURES / "test_camt053.xml"
CLI = ROOT / "camt_to_mt940.py"

BOM = b"\xef\xbb\xbf"


def run_cli(in_path: str, out_path: str, cwd: Path,
            timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "-i", in_path, "-o", out_path],
        cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout)


class TestCliProcesoReal(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.cwd = self.base / "cwd"
        self.entrada = self.base / "Entrada"
        self.salida = self.base / "Salida"
        self.cwd.mkdir()
        self.entrada.mkdir()

    def logos(self) -> list[Path]:
        return sorted(self.salida.glob("log_*.txt"))

    def test_flujo_completo_del_criterio_spec9(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        out = next(self.salida.glob("test_camt053_*.txt"))
        text = out.read_text(encoding="utf-8", newline="")
        self.assertTrue(text.startswith(
            "{1:F01DEMOBKMMAXXX0000000000}{2:I940DEMORCVGXXXXN}"))
        self.assertEqual(text.count(":61:"), 34)
        # Default de config (PAGING_ENABLED=True, ENTRIES_PER_MESSAGE=3):
        # 34 movimientos → 11 mensajes de 3 + 1 de 1, en un solo archivo.
        self.assertEqual(text.count("{1:F01"), 12)
        self.assertEqual(text.count("\r\n$"), 11)
        self.assertTrue(text.endswith("-}\r\n"))
        self.assertNotIn("{5:", text)
        self.assertFalse(list(self.salida.glob("test_camt053_*_2.txt")))

        self.assertFalse((self.entrada / "test_camt053.xml").exists())
        self.assertTrue(
            (self.entrada / "Procesados" / "test_camt053.xml").exists())
        self.assertEqual(len(self.logos()), 1)

    def test_salidas_y_log_utf8_sin_bom(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        for path in [*self.salida.glob("test_camt053_*.txt"),
                     *self.logos()]:
            header = path.read_bytes()[:3]
            self.assertNotEqual(header, BOM, msg=f"{path.name} lleva BOM")

    def test_modo_archivo_individual_y_multi_stmt(self) -> None:
        src = self.entrada / "multi_stmt.xml"
        shutil.copy(FIXTURES / "multi_stmt.xml", src)
        proc = run_cli(str(src), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        out = next(self.salida.glob("multi_stmt_*.txt"))
        text = out.read_text(encoding="utf-8", newline="")
        self.assertEqual(text.count("$"), 1)
        self.assertEqual(text.count("{1:F01"), 2)
        self.assertEqual(text.count("\r\n$"), 1)
        self.assertTrue(text.endswith("-}\r\n"))
        self.assertFalse(src.exists())
        self.assertTrue((self.entrada / "Procesados" / "multi_stmt.xml").exists())

    def test_entrada_inexistente_devuelve_1_con_error_en_log(self) -> None:
        proc = run_cli(str(self.entrada / "no_existe.xml"),
                       str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(self.logos()), 1)
        log_text = self.logos()[0].read_text(encoding="utf-8", newline="")
        self.assertIn("no_existe.xml", log_text)
        self.assertIn("ERROR", log_text)
        self.assertIn("no_existe.xml", proc.stdout)
        self.assertIn("registrando en Log", proc.stdout)

    def test_argparse_exige_iy_o(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CLI)], cwd=str(self.cwd),
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr.lower())

    def test_progreso_visible_en_stdout(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Transformando test_camt053.xml", proc.stdout)
        self.assertIn("Transformacion exitosa, continuando con el siguiente",
                      proc.stdout)
        self.assertIn("1 transformados", proc.stdout)

    def test_omitido_no_camt_avisado_en_stdout(self) -> None:
        (self.entrada / "README.txt").write_text("hola", encoding="utf-8")
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Transformando README.txt", proc.stdout)
        self.assertIn("Omitido, no es un CAMT.053: README.txt", proc.stdout)
        self.assertIn("1 omitidos", proc.stdout)

    def test_carpeta_vacia_avisa_que_no_hay_archivos(self) -> None:
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("No se encontraron archivos", proc.stdout)
        self.assertIn("0 transformados", proc.stdout)

    def test_ignora_archivos_ocultos_de_la_entrada(self) -> None:
        # `.gitkeep` mantiene la carpeta en el repo, pero no es un CAMT.
        (self.entrada / ".gitkeep").write_text("", encoding="utf-8")
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        proc = run_cli(str(self.entrada), str(self.salida), self.cwd)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("1 transformados, 0 omitidos, 0 con error", proc.stdout)


if __name__ == "__main__":
    unittest.main()