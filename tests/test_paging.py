# -*- coding: utf-8 -*-
"""Paginado por conteo configurable (SPEC §6.3-D): PAGING_ENABLED + ENTRIES_PER_MESSAGE."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

import _pathfix  # noqa: F401

import camt_to_mt940
from Library import config
from Library.camt053 import parse_document
from Library.config import resolve_page_size
from Library.mt940_builder import Mt940BuildError, build_statement_lines
from Library.mt940_splitter import (_apply_page_refs, _page_ref20,
                                    split_statement_lines)
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"
REAL_CAMT = FIXTURES / "test_camt053.xml"
EXPECTED = FIXTURES / "golden" / "test_camt053_expected_MT940.TXT"
RUN_AT = datetime(2026, 10, 1, 14, 21, 38)
NAME = "test_camt053.xml"


def _chunks(page_size, **kwargs):
    document = parse_document(REAL_CAMT.read_text(encoding="utf-8"))
    stmt = document.statements[0]
    log = RunLog(now=lambda: RUN_AT)
    lines = build_statement_lines(stmt, document.msg_id, config, log, NAME)
    return split_statement_lines(lines, stmt, log, NAME,
                                 page_size=page_size, **kwargs), stmt, log


def _signed(marker: str, amount: str) -> Decimal:
    value = Decimal(amount.replace(",", "."))
    return value if marker == "C" else -value


class TestResolvePageSize(unittest.TestCase):
    def test_apagado_devuelve_none(self):
        self.assertIsNone(resolve_page_size(False, 3))

    def test_encendido_devuelve_n(self):
        self.assertEqual(resolve_page_size(True, 3), 3)
        self.assertEqual(resolve_page_size(True, 1), 1)

    def test_lee_la_config_en_tiempo_de_llamada(self):
        with mock.patch.multiple(config, PAGING_ENABLED=True,
                                 ENTRIES_PER_MESSAGE=5):
            self.assertEqual(resolve_page_size(), 5)
        with mock.patch.object(config, "PAGING_ENABLED", False):
            self.assertIsNone(resolve_page_size())

    def test_n_invalido_levanta_error(self):
        for bad in (0, -1, 2.5, "3", None, True):
            with self.subTest(n=bad):
                with self.assertRaises(Mt940BuildError):
                    resolve_page_size(True, bad if bad is not None else "x")

    def test_bandera_no_booleana_levanta_error(self):
        for bad in (1, "True", 0):
            with self.subTest(flag=bad):
                with self.assertRaises(Mt940BuildError):
                    resolve_page_size(bad, 3)

    def test_n_se_ignora_si_esta_apagado(self):
        self.assertIsNone(resolve_page_size(False, 0))


class TestMatrizDePaginado(unittest.TestCase):
    """CAMT real de 34 movimientos con distintos N."""

    EXPECTED_MESSAGES = {1: 34, 2: 17, 3: 12, 5: 7, 10: 4, 34: 1, 50: 1}

    def test_numero_de_mensajes_por_n(self):
        for n, count in self.EXPECTED_MESSAGES.items():
            with self.subTest(n=n):
                chunks, _, _ = _chunks(n)
                self.assertEqual(len(chunks), count)

    def test_apagado_un_solo_mensaje(self):
        chunks, _, _ = _chunks(None)
        self.assertEqual(len(chunks), 1)

    def test_el_ultimo_mensaje_lleva_el_resto(self):
        chunks, _, _ = _chunks(3)
        sizes = [sum(l.startswith(":61:") for l in c.lines) for c in chunks]
        self.assertEqual(sizes, [3] * 11 + [1])

    def test_invariantes_para_todo_n(self):
        original, _, _ = _chunks(None)
        source = [l for l in original[0].lines if l.startswith(":61:")]
        for n in (*self.EXPECTED_MESSAGES, None):
            with self.subTest(n=n):
                chunks, stmt, _ = _chunks(n)
                flat = [l for c in chunks for l in c.lines
                        if l.startswith(":61:")]
                self.assertEqual(flat, source)           # orden y conteo
                self.assertTrue(chunks[0].lines[3].startswith(":60F:"))
                self.assertTrue(chunks[-1].lines[-2].startswith(":62F:"))
                self.assertTrue(chunks[-1].lines[-1].startswith(":64:"))
                self.assertFalse(
                    any(l.startswith((":62F:", ":64:"))
                        for c in chunks[:-1] for l in c.lines))
                refs = [c.lines[0] for c in chunks]
                self.assertEqual(len(set(refs)), len(refs))   # :20: único
                self.assertEqual(refs[-1], ":20:260831000000012")
                seqs = [c.lines[2] for c in chunks]
                self.assertEqual(seqs, [f":28C:01565/{i:05d}"
                                        for i in range(1, len(chunks) + 1)])
                self.assertEqual([c.ends_with_62m for c in chunks],
                                 [True] * (len(chunks) - 1) + [False])

    def test_saldos_cuadran_por_mensaje_y_encadenan(self):
        for n in (1, 3, 5):
            with self.subTest(n=n):
                chunks, _, _ = _chunks(n)
                prev_close = None
                for chunk in chunks:
                    opening = next(l for l in chunk.lines
                                   if l.startswith((":60F:", ":60M:")))
                    closing = next(l for l in chunk.lines
                                   if l.startswith((":62F:", ":62M:")))
                    op = re.match(r":60[FM]:([CD])\d{6}MXN([\d,]+)", opening)
                    cl = re.match(r":62[FM]:([CD])\d{6}MXN([\d,]+)", closing)
                    start = _signed(op.group(1), op.group(2))
                    end = _signed(cl.group(1), cl.group(2))
                    movs = sum(_signed(m.group(1), m.group(2)) for m in (
                        re.match(r":61:\d{10}([CD])([\d,]+)N", l)
                        for l in chunk.lines if l.startswith(":61:")))
                    self.assertEqual(start + movs, end)
                    if prev_close is not None:
                        self.assertEqual(start, prev_close)
                    prev_close = end

    def test_texto_de_cada_movimiento_no_depende_del_paginado(self):
        def blocks(chunks):
            out, cur = [], None
            for c in chunks:
                for l in c.lines:
                    if l.startswith(":61:"):
                        cur = [l]
                        out.append(cur)
                    elif cur is not None and not l.startswith(
                            (":62", ":60", ":64", ":20", ":25", ":28")):
                        cur.append(l)
                    else:
                        cur = None if l.startswith(":6") else cur
            return out
        self.assertEqual(blocks(_chunks(3)[0]), blocks(_chunks(None)[0]))


class TestContraArchivoEsperado(unittest.TestCase):
    """Estructura de paginado == test_camt053_expected_MT940.TXT (N=3)."""

    STRUCTURAL = (":20:", ":25:", ":28C:", ":60F:", ":60M:", ":62F:", ":62M:",
                  ":64:")

    def test_lineas_estructurales_identicas(self):
        expected = EXPECTED.read_text(encoding="utf-8", newline="")
        expected_struct = [l for l in expected.split("\r\n")
                           if l.startswith(self.STRUCTURAL)]
        chunks, _, _ = _chunks(3)
        got = [l for c in chunks for l in c.lines
               if l.startswith(self.STRUCTURAL)]
        self.assertEqual(got, expected_struct)

    def test_prefijo_de_cada_61_identico(self):
        expected = EXPECTED.read_text(encoding="utf-8", newline="")
        want = [re.match(r":61:(\d{10}[CD][\d,]+N)", l).group(1)
                for l in expected.split("\r\n") if l.startswith(":61:")]
        chunks, _, _ = _chunks(3)
        got = [re.match(r":61:(\d{10}[CD][\d,]+N)", l).group(1)
               for c in chunks for l in c.lines if l.startswith(":61:")]
        self.assertEqual(got, want)


class TestReferencia20(unittest.TestCase):
    def test_anchor_last(self):
        self.assertEqual(_page_ref20("260831000000012", 12, 12, 2001),
                         "260831000000012")
        self.assertEqual(_page_ref20("260831000000012", 1, 12, 2001),
                         "260830999978001")

    def test_no_numerico_cae_a_sufijo(self):
        self.assertEqual(_page_ref20("STM000007", 2, 3, 2001), "STM000007"[:13] + "002")

    def test_resultado_no_positivo_cae_a_sufijo(self):
        self.assertEqual(_page_ref20("100", 1, 3, 2001), "100" + "001")

    def test_un_solo_mensaje_no_cambia_el_20(self):
        chunks, _, _ = _chunks(None)
        self.assertEqual(chunks[0].lines[0], ":20:260831000000012")


class TestInfoConsistencia20(unittest.TestCase):
    """SPEC §6.4: INFO si int(Stmt/Id[-3:]) != N, solo con s = 3."""

    @staticmethod
    def _chunks(base: str, total: int) -> list[list[str]]:
        return [[f":20:{base}"] for _ in range(total)]

    def test_avisa_si_el_sufijo_no_coincide_con_n(self):
        log = RunLog(now=lambda: RUN_AT)
        chunks = self._chunks("260831000000012", 4)   # sufijo 012 = 12 != 4
        _apply_page_refs(chunks, log, "x.xml", 2001, page_size=3)
        info = [e for e in log.events if e.level == "INFO"]
        self.assertEqual(len(info), 1)
        self.assertIn("012", str(info[0]))
        self.assertIn("4", str(info[0]))

    def test_no_avisa_si_el_sufijo_coincide(self):
        log = RunLog(now=lambda: RUN_AT)
        chunks = self._chunks("260831000000012", 12)
        _apply_page_refs(chunks, log, "x.xml", 2001, page_size=3)
        self.assertEqual([e for e in log.events if e.level == "INFO"], [])

    def test_no_avisa_si_s_es_distinto_de_3(self):
        log = RunLog(now=lambda: RUN_AT)
        chunks = self._chunks("260831000000012", 4)
        _apply_page_refs(chunks, log, "x.xml", 2001, page_size=5)
        self.assertEqual([e for e in log.events if e.level == "INFO"], [])

    def test_no_avisa_si_el_id_no_es_numerico(self):
        log = RunLog(now=lambda: RUN_AT)
        chunks = self._chunks("ABC123", 4)
        _apply_page_refs(chunks, log, "x.xml", 2001, page_size=3)
        self.assertEqual([e for e in log.events if e.level == "INFO"], [])


class TestRedDeSeguridad(unittest.TestCase):
    def test_corte_por_tamano_con_paginado_encendido_avisa(self):
        chunks, _, log = _chunks(34, max_chars=1500, reserve_chars=0)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(any("paginado: corte por tamaño" in str(w)
                            for w in log.events))

    def test_sin_paginado_el_corte_por_tamano_no_avisa(self):
        chunks, _, log = _chunks(None, max_chars=1500, reserve_chars=0)
        self.assertGreater(len(chunks), 1)
        self.assertFalse(any("paginado: corte por tamaño" in str(w)
                             for w in log.events))


class TestLoteExtremoAExtremo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entrada = Path(tmp.name) / "Entrada"
        self.salida = Path(tmp.name) / "Salida"
        self.entrada.mkdir()
        shutil.copy(REAL_CAMT, self.entrada / NAME)

    def run_batch(self):
        return camt_to_mt940.run_batch(self.entrada, self.salida,
                                       run_at=RUN_AT)

    def test_defaults_un_archivo_12_mensajes(self):
        self.assertEqual(self.run_batch(), 0)
        files = sorted(self.salida.glob("test_camt053_*.txt"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8", newline="")
        self.assertEqual(text.count("{1:F01"), 12)
        self.assertEqual(text.count("\r\n$"), 11)
        self.assertTrue(text.endswith("-}\r\n"))

    def test_byte_equality_con_el_esperado(self):
        """SPEC §10.1/§8: el CAMT real == test_camt053_expected_MT940.TXT."""
        self.assertEqual(self.run_batch(), 0)
        out = next(self.salida.glob("test_camt053_*.txt"))
        self.assertEqual(out.read_bytes(), EXPECTED.read_bytes())

    def test_corrida_real_no_emite_info_de_consistencia(self):
        """N=12 coincide con el sufijo `012` de Stmt/Id → sin INFO."""
        self.assertEqual(self.run_batch(), 0)
        textos = [p.read_text(encoding="utf-8")
                  for p in self.salida.glob("log_*.txt")]
        self.assertNotIn("20: consistencia", "".join(textos))

    def test_header_source_apphdr_reproduce_el_esperado(self):
        """SPEC §6.2: los LT derivados del Envelope dan el mismo header."""
        with mock.patch.object(config, "HEADER_SOURCE", "apphdr"):
            self.assertEqual(self.run_batch(), 0)
        out = next(self.salida.glob("test_camt053_*.txt"))
        self.assertEqual(out.read_bytes(), EXPECTED.read_bytes())

    def test_bandera_apagada_un_mensaje(self):
        with mock.patch.object(config, "PAGING_ENABLED", False):
            self.assertEqual(self.run_batch(), 0)
        text = next(self.salida.glob("test_camt053_*.txt")).read_text(
            encoding="utf-8", newline="")
        self.assertEqual(text.count("{1:F01"), 1)
        self.assertNotIn("$", text)
        self.assertEqual(text.count(":61:"), 34)

    def test_n_configurable(self):
        with mock.patch.object(config, "ENTRIES_PER_MESSAGE", 5):
            self.assertEqual(self.run_batch(), 0)
        text = next(self.salida.glob("test_camt053_*.txt")).read_text(
            encoding="utf-8", newline="")
        self.assertEqual(text.count("{1:F01"), 7)

    def test_split_files_legado_abre_archivos_2_3(self):
        with mock.patch.object(config, "OUTPUT_MODE", "split_files"):
            self.assertEqual(self.run_batch(), 0)
        self.assertEqual(len(list(self.salida.glob("test_camt053_*.txt"))), 12)

    def test_n_invalido_es_error_y_no_mueve_el_original(self):
        with mock.patch.object(config, "ENTRIES_PER_MESSAGE", 0):
            self.assertEqual(self.run_batch(), 1)
        self.assertTrue((self.entrada / NAME).exists())
        self.assertFalse(list(self.salida.glob("test_camt053_*.txt")))


if __name__ == "__main__":
    unittest.main()
