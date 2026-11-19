# -*- coding: utf-8 -*-
"""SPEC §8: checker independiente del golden aceptado por el gateway.

No convierte CAMT: valida directamente la forma de
`fixtures/golden/finalExample.TXT` (7 mensajes × 3 `:61:`, `:28C:` secuencial,
cadena `:60M:`/`:62M:`, unión con `EOL + $`, cierre `-}` + CRLF, padding de
`:61:`/suplementaria y patrón `anchor_last` del `:20:`).
"""

import re
import unittest
from pathlib import Path

import _pathfix  # noqa: F401

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "finalExample.TXT"

RE_61 = re.compile(
    r"^:61:\d{6}\d{4}(?:RC|RD|[DC])[A-Z]?\d{1,15},\d{2}"
    r"[SNF][A-Z0-9]{3}(?:[^/]|/(?!/)){1,16}//[^/]{1,16}$")
RE_BAL = re.compile(r"^:(?:60F|60M|62F|62M|64|65):[DC]\d{6}[A-Z]{3}\d{1,15},\d{2}$")
RE_28C = re.compile(r"^:28C:\d{5}/\d{5}$")


class TestGoldenProfile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = GOLDEN.read_bytes()
        cls.text = cls.raw.decode("utf-8")
        cls.messages = cls.text.rstrip("\r\n").split("\r\n$")

    @staticmethod
    def _lines(message: str) -> list[str]:
        return message.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0].split("\r\n")

    @staticmethod
    def _first(lines: list[str], prefixes) -> str:
        return next(l for l in lines if l.startswith(prefixes))

    def test_siete_mensajes_de_tres_61(self):
        self.assertEqual(len(self.messages), 7)
        for message in self.messages:
            n61 = sum(1 for l in self._lines(message) if l.startswith(":61:"))
            self.assertEqual(n61, 3)

    def test_28c_secuencial(self):
        valores = [self._first(self._lines(m), ":28C:") for m in self.messages]
        self.assertEqual(valores,
                         [f":28C:01649/{i:05d}" for i in range(1, 8)])

    def test_20_anchor_last_paso_2001(self):
        refs = [self._first(self._lines(m), ":20:")[len(":20:"):]
                for m in self.messages]
        self.assertEqual(refs[-1], "260900742182007")
        self.assertEqual(refs[0], "260900742170001")
        for index, ref in enumerate(refs, start=1):
            esperado = str(int(refs[-1]) - (7 - index) * 2001)
            self.assertEqual(ref, esperado)
        self.assertEqual([r[-3:] for r in refs],
                         [f"{i:03d}" for i in range(1, 8)])

    def test_60m_es_el_62m_anterior(self):
        aperturas = [self._first(self._lines(m), (":60F:", ":60M:"))
                     for m in self.messages]
        cierres = [self._first(self._lines(m), (":62M:", ":62F:"))
                   for m in self.messages]
        self.assertTrue(aperturas[0].startswith(":60F:"))
        for i in range(1, 7):
            self.assertTrue(aperturas[i].startswith(":60M:"))
            self.assertEqual(aperturas[i].replace(":60M:", ""),
                             cierres[i - 1].replace(":62M:", ""))

    def test_62f_y_64_solo_en_el_ultimo(self):
        for message in self.messages[:-1]:
            self.assertNotIn(":62F:", message)
            self.assertNotIn(":64:", message)
        self.assertIn(":62F:", self.messages[-1])
        self.assertIn(":64:", self.messages[-1])

    def test_dolar_a_columna_0_antes_de_abrir_llave(self):
        self.assertEqual(self.text.count("\r\n$"), 6)
        self.assertEqual(self.text.count("\r\n${1:"), 6)
        self.assertNotIn("-}$", self.text)

    def test_archivo_termina_en_cierre_mas_crlf(self):
        self.assertTrue(self.raw.endswith(b"-}\r\n"))

    def test_primera_61_tiene_59_de_contenido(self):
        primera = next(l for l in self.text.split("\r\n")
                       if l.startswith(":61:"))
        self.assertEqual(len(primera) - len(":61:"), 59)

    def test_suplementarias_de_34(self):
        for message in self.messages:
            lines = self._lines(message)
            for i, line in enumerate(lines):
                if line.startswith(":61:"):
                    self.assertFalse(lines[i + 1].startswith(":"),
                                     "falta suplementaria tras :61:")
                    self.assertEqual(len(lines[i + 1]), 34)

    def test_gramatica_swift_del_golden(self):
        for message in self.messages:
            lines = self._lines(message)
            for line in lines:
                if line.startswith(":61:"):
                    self.assertRegex(line, RE_61)
                elif line.startswith((":60F:", ":60M:", ":62F:", ":62M:",
                                      ":64:", ":65:")):
                    self.assertRegex(line, RE_BAL)
                elif line.startswith(":28C:"):
                    self.assertRegex(line, RE_28C)
            for i, line in enumerate(lines):
                if line.startswith(":86:"):
                    grupo = [line]
                    j = i + 1
                    while j < len(lines) and not lines[j].startswith(":"):
                        grupo.append(lines[j])
                        j += 1
                    self.assertLessEqual(len(grupo), 6)
                    for l in grupo:
                        self.assertLessEqual(len(l), 65)


if __name__ == "__main__":
    unittest.main()
