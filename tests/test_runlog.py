# -*- coding: utf-8 -*-
"""Task 2 — runlog.py: log por corrida (WARN/ERROR + texto perdido)."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import _pathfix  # noqa: F401

from Library.runlog import RunLog

RUN_AT = datetime(2026, 9, 18, 10, 30, 15)


def make_log() -> RunLog:
    return RunLog(now=lambda: RUN_AT)


class TestRunLog(unittest.TestCase):

    def test_warn_acumula_evento_con_formato_spec(self):
        log = make_log()
        log.warn("archivo.xml", "charset", "texto perdido")
        self.assertEqual(len(log.events), 1)
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml | WARN: [charset] + texto perdido",
        )

    def test_error_acumula_evento_con_formato_spec(self):
        log = make_log()
        log.error("archivo.xml", "saldo OPBD no encontrado")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml | ERROR: [saldo OPBD no encontrado]",
        )

    def test_info_acumula_evento_con_formato_spec(self):
        log = make_log()
        log.info("archivo.xml", "20: consistencia", "sufijo 012 != 12 mensajes")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml "
            "| INFO: [20: consistencia] + sufijo 012 != 12 mensajes",
        )

    def test_info_sin_detalle_omite_sufijo(self):
        log = make_log()
        log.info("archivo.xml", "regla")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml | INFO: [regla]",
        )

    def test_warn_sin_texto_perdido_omite_sufijo(self):
        log = make_log()
        log.warn("archivo.xml", "truncado")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml | WARN: [truncado]",
        )

    def test_eventos_van_en_orden(self):
        log = make_log()
        log.warn("a.xml", "w1")
        log.error("b.xml", "e1")
        log.warn("a.xml", "w2")
        self.assertEqual([str(e) for e in log.events],
                         [
                             "18/09/2026 10:30 | a.xml | WARN: [w1]",
                             "18/09/2026 10:30 | b.xml | ERROR: [e1]",
                             "18/09/2026 10:30 | a.xml | WARN: [w2]",
                         ])

    def test_write_genera_log_de_corrida(self):
        log = make_log()
        log.warn("archivo.xml", "regla", "perdido")
        with tempfile.TemporaryDirectory() as tmp:
            path = log.write(Path(tmp))
            self.assertEqual(path.name, "log_18092026_103015.txt")
            self.assertTrue(path.is_file())

    def test_write_utf8_sin_bom_y_una_linea_por_evento(self):
        log = make_log()
        log.warn("a.xml", "w1")
        log.error("b.xml", "e1")
        with tempfile.TemporaryDirectory() as tmp:
            path = log.write(Path(tmp))
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"),
                             "el log no debe tener BOM")
            lines = raw.decode("utf-8").splitlines()
            self.assertEqual(len(lines), 2)

    def test_newlines_y_tabs_saneados_a_una_linea(self):
        log = make_log()
        log.warn("a.xml", "regla", "linea1\r\nlinea2\ttab")
        with tempfile.TemporaryDirectory() as tmp:
            path = log.write(Path(tmp))
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("\r", content)
            self.assertNotIn("\t", content)
            self.assertEqual(len(content.splitlines()), 1)

    def test_write_crea_el_directorio(self):
        log = make_log()
        log.warn("a.xml", "w")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "carpeta"
            path = log.write(out)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()