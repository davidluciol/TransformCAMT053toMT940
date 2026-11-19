# -*- coding: utf-8 -*-
"""Conformidad del bloque 4 con las reglas explícitas SWIFT del MT940.

Valida la salida real contra `MT940_Especificacion_Tecnica.md`:
:20: `16x` sin `/` inicial/final ni `//`; :25: `35x`; :28C: `5n[/5n]`;
:60:/:62:/:64: = `1!a6!n3!a15d`; :61: = `6!n[4!n]2a[1!a]15d1!a3!c16x[//16x][34x]`;
:86: `6*65x`; suplementaria `34x`.
"""

import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import _pathfix  # noqa: F401

import camt_to_mt940
from Library import config

FIXTURES = Path(__file__).parent / "fixtures"
RUN = datetime(2026, 9, 18, 10, 30, 15)

RE_28C = re.compile(r"^:28C:\d{5}/\d{5}$")
RE_BAL = re.compile(r"^:(?:60F|60M|62F|62M|64|65):[DC]\d{6}[A-Z]{3}\d{1,15},\d{2}$")
RE_61 = re.compile(
    r"^:61:\d{6}\d{4}(?:RC|RD|[DC])[A-Z]?\d{1,15},\d{2}"
    r"[SNF][A-Z0-9]{3}(?:[^/]|/(?!/)){1,16}//[^/]{1,16}$")


def _valida_20(line: str) -> bool:
    body = line[len(":20:"):]
    return (1 <= len(body) <= 16 and "//" not in body
            and not body.startswith("/") and not body.endswith("/"))


class TestConformidadSwift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        entrada = Path(tmp.name) / "Entrada"
        salida = Path(tmp.name) / "Salida"
        entrada.mkdir()
        shutil.copy(FIXTURES / "test_camt053.xml", entrada / "test_camt053.xml")
        cls.code = camt_to_mt940.run_batch(entrada, salida, config=config,
                                           run_at=RUN)
        out = next(salida.glob("test_camt053_*.txt"))
        cls.text = out.read_text(encoding="utf-8", newline="")

    def test_corrida_ok(self):
        self.assertEqual(self.code, 0)

    def test_cada_linea_del_bloque4_cumple_la_regla_swift(self):
        vistos = {"20": 0, "25": 0, "28C": 0, "bal": 0, "61": 0, "86": 0}
        for mensaje in self.text.rstrip("\r\n").split("\r\n$"):
            body = mensaje.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]
            lineas = body.split("\r\n")
            i = 0
            while i < len(lineas):
                linea = lineas[i]
                if linea.startswith(":20:"):
                    self.assertTrue(_valida_20(linea), linea)
                    vistos["20"] += 1
                elif linea.startswith(":25:"):
                    self.assertLessEqual(len(linea) - 4, 35, linea)
                    vistos["25"] += 1
                elif linea.startswith(":28C:"):
                    self.assertRegex(linea, RE_28C)
                    vistos["28C"] += 1
                elif linea.startswith((":60F:", ":60M:", ":62F:", ":62M:",
                                       ":64:", ":65:")):
                    self.assertRegex(linea, RE_BAL)
                    vistos["bal"] += 1
                elif linea.startswith(":61:"):
                    self.assertRegex(linea, RE_61)
                    vistos["61"] += 1
                elif linea.startswith(":86:"):
                    grupo = [linea]
                    i += 1
                    while i < len(lineas) and not lineas[i].startswith(":"):
                        grupo.append(lineas[i])
                        i += 1
                    self.assertLessEqual(len(grupo), 6)
                    for l in grupo:
                        self.assertLessEqual(len(l), 65, l)
                    vistos["86"] += 1
                    continue
                else:
                    self.assertLessEqual(len(linea), 34, linea)
                i += 1
        self.assertEqual(vistos["20"], 12)
        self.assertEqual(vistos["25"], 12)
        self.assertEqual(vistos["28C"], 12)
        self.assertEqual(vistos["61"], 34)
        self.assertEqual(vistos["86"], 34)


if __name__ == "__main__":
    unittest.main()
