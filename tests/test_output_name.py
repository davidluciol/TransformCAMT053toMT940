# -*- coding: utf-8 -*-
"""SPEC §6.3-C: nombre de salida acotado a 32 chars, fechado por transacción.

- Fecha del nombre = última transacción `BOOK` (no la de corrida).
- Si `<original>_<ddMMyyyy>.txt` excede 32, compacta a
  `<BIC8>_<YYMMDD transacción>_<ddMMyy corrida>.txt`.
- Si el destino ya existe, agrega `(1)`, `(2)`, ... (nunca sobrescribe).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import _pathfix  # noqa: F401

import camt_to_mt940
from Library import config
from Library.camt053 import parse_document
from Library.runlog import RunLog

RUN = datetime(2026, 10, 5, 14, 30)
FIXTURES = Path(__file__).parent / "fixtures"
LARGO = "DDEMOBKMMAXXX20260930000105300001"  # stem del ejemplo rechazado (34)
TX = "2026-08-31"

DOS_FECHAS = (
    "<BkToCstmrStmt xmlns='urn:x'>"
    "<GrpHdr><MsgId>M</MsgId></GrpHdr>"
    "<Stmt><Id>S</Id><Acct><Id><Othr><Id>X</Id></Othr></Id><Ccy>MXN</Ccy></Acct>"
    "<Ntry><Amt Ccy='MXN'>1.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
    "<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-09-01</Dt></BookgDt>"
    "<ValDt><Dt>2026-09-01</Dt></ValDt></Ntry>"
    "<Ntry><Amt Ccy='MXN'>2.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
    "<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>2026-09-30</Dt></BookgDt>"
    "<ValDt><Dt>2026-09-30</Dt></ValDt></Ntry>"
    "</Stmt></BkToCstmrStmt>"
)


class TestCompactStem(unittest.TestCase):
    def test_bic8_y_fechas_cortas(self):
        self.assertEqual(
            camt_to_mt940._compact_stem("DEMORCVGXXX", TX, RUN),
            "DEMORCVG_260831_051026")

    def test_bic_vacio_cae_a_marcador(self):
        self.assertEqual(camt_to_mt940._compact_stem("", "", RUN),
                         "XXXXXXXX_261005_051026")

    def test_bic_se_sanea_y_corta(self):
        self.assertEqual(
            camt_to_mt940._compact_stem("demorcv-g-extra", TX, RUN),
            "DEMORCVG_260831_051026")


class TestOutputStems(unittest.TestCase):
    def test_stem_corto_fecha_ultima_transaccion(self):
        stems = camt_to_mt940._output_stems("test_camt053", RUN, 1, tx_date=TX)
        self.assertEqual(stems[0][0], "test_camt053_31082026")

    def test_sin_fecha_cae_a_la_de_corrida(self):
        stems = camt_to_mt940._output_stems("test_camt053", RUN, 1, tx_date="")
        self.assertEqual(stems[0][0], "test_camt053_05102026")

    def test_justo_en_32_conserva(self):
        stem = "a" * 19  # 19 + "_31082026" + ".txt" = 32
        stems = camt_to_mt940._output_stems(stem, RUN, 1, tx_date=TX)
        self.assertEqual(stems[0][0], f"{stem}_31082026")

    def test_excede_32_usa_compacto(self):
        stem = "a" * 20  # 33
        stems = camt_to_mt940._output_stems(stem, RUN, 1,
                                            bic="DEMORCVGXXX", tx_date=TX)
        self.assertEqual(stems[0][0], "DEMORCVG_260831_051026")

    def test_ejemplo_rechazado(self):
        stems = camt_to_mt940._output_stems(LARGO, RUN, 1,
                                            bic="DEMORCVGXXX",
                                            tx_date="2026-09-30")
        self.assertEqual(stems[0][0], "DEMORCVG_260930_051026")

    def test_sufijo_split_files(self):
        stems = camt_to_mt940._output_stems(LARGO, RUN, 3,
                                            bic="DEMORCVGXXX", tx_date=TX)
        self.assertEqual(stems[0][0], "DEMORCVG_260831_051026")
        self.assertEqual(stems[1][0], "DEMORCVG_260831_051026_2")
        self.assertEqual(stems[2][0], "DEMORCVG_260831_051026_3")


class TestResolveOutputName(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_libre_usa_el_deseado(self):
        self.assertEqual(
            camt_to_mt940._resolve_output_name(self.out, "a_31082026", "C_1"),
            "a_31082026.txt")

    def test_existente_agrega_contador(self):
        (self.out / "a_31082026.txt").write_text("x", encoding="utf-8")
        self.assertEqual(
            camt_to_mt940._resolve_output_name(self.out, "a_31082026", "C_1"),
            "a_31082026(1).txt")

    def test_contador_ocupado_salta_al_siguiente(self):
        (self.out / "a_31082026.txt").write_text("x", encoding="utf-8")
        (self.out / "a_31082026(1).txt").write_text("x", encoding="utf-8")
        self.assertEqual(
            camt_to_mt940._resolve_output_name(self.out, "a_31082026", "C_1"),
            "a_31082026(2).txt")

    def test_sin_espacio_para_contador_compacta(self):
        stem = "a" * 28  # 28 + ".txt" = 32: no cabe "(1)"
        (self.out / f"{stem}.txt").write_text("x", encoding="utf-8")
        name = camt_to_mt940._resolve_output_name(self.out, stem, "C_1")
        self.assertEqual(name, "C_1.txt")

    def test_compacto_con_contador_si_ocupado(self):
        stem = "a" * 28
        (self.out / f"{stem}.txt").write_text("x", encoding="utf-8")
        (self.out / "C_1.txt").write_text("x", encoding="utf-8")
        self.assertEqual(
            camt_to_mt940._resolve_output_name(self.out, stem, "C_1"),
            "C_1(1).txt")

    def test_sin_nombre_libre_devuelve_none(self):
        stem = "a" * 26        # 26 + "(1)" + ".txt" = 33: no cabe ningún contador
        compact = "c" * 26
        (self.out / f"{stem}.txt").write_text("x", encoding="utf-8")
        (self.out / f"{compact}.txt").write_text("x", encoding="utf-8")
        self.assertIsNone(
            camt_to_mt940._resolve_output_name(self.out, stem, compact))


class TestResolveOutputNames(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        self.log = RunLog(now=lambda: RUN)

    def test_resuelve_uno_por_stem(self):
        names = camt_to_mt940._resolve_output_names(
            self.out, [("a_31082026", "C_1"), ("b_31082026", "C_2")],
            self.log, "x.xml")
        self.assertEqual(names, ["a_31082026.txt", "b_31082026.txt"])
        self.assertEqual(self.log.events, [])

    def test_sin_nombre_libre_loguea_error_y_devuelve_none(self):
        stem, compact = "a" * 26, "c" * 26
        (self.out / f"{stem}.txt").write_text("x", encoding="utf-8")
        (self.out / f"{compact}.txt").write_text("x", encoding="utf-8")
        self.assertIsNone(camt_to_mt940._resolve_output_names(
            self.out, [(stem, compact)], self.log, "x.xml"))
        self.assertEqual([e.level for e in self.log.events], ["ERROR"])


class TestTransactionDate(unittest.TestCase):
    def test_es_la_mas_reciente(self):
        doc = parse_document(DOS_FECHAS)
        self.assertEqual(camt_to_mt940._transaction_date(doc), "2026-09-30")

    def test_fixture_real(self):
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        self.assertEqual(camt_to_mt940._transaction_date(doc), "2026-08-31")


class TestEndToEndNombreLargo(unittest.TestCase):
    def test_nombre_largo_sale_compacto(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entrada = base / "Entrada"
            entrada.mkdir()
            salida = base / "Salida"
            shutil.copy(FIXTURES / "test_camt053.xml",
                        entrada / f"{LARGO}.xml")

            code = camt_to_mt940.run_batch(entrada, salida, config=config,
                                           run_at=RUN)

            self.assertEqual(code, 0)
            salidas = [p.name for p in salida.glob("*.txt")
                       if not p.name.startswith("log_")]
            self.assertEqual(salidas, ["DEMORCVG_260831_051026.txt"])
            self.assertLessEqual(len(salidas[0]), 32)


class TestEndToEndColision(unittest.TestCase):
    def test_segundo_archivo_no_sobrescribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entrada = base / "Entrada"
            entrada.mkdir()
            salida = base / "Salida"
            for _ in range(2):
                shutil.copy(FIXTURES / "test_camt053.xml",
                            entrada / "corto.xml")
                self.assertEqual(
                    camt_to_mt940.run_batch(entrada, salida, config=config,
                                            run_at=RUN), 0)

            nombres = sorted(p.name for p in salida.glob("corto_*.txt"))
            self.assertEqual(nombres, ["corto_31082026(1).txt",
                                       "corto_31082026.txt"])
            for nombre in nombres:
                self.assertLessEqual(len(nombre), 32)


class TestEndToEndSinNombreLibre(unittest.TestCase):
    def test_error_no_mueve_el_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entrada = base / "Entrada"
            entrada.mkdir()
            salida = base / "Salida"
            shutil.copy(FIXTURES / "test_camt053.xml",
                        entrada / "test_camt053.xml")

            with mock.patch.object(camt_to_mt940, "_resolve_output_name",
                                   return_value=None):
                code = camt_to_mt940.run_batch(entrada, salida, config=config,
                                               run_at=RUN)

            self.assertEqual(code, 1)
            self.assertTrue((entrada / "test_camt053.xml").exists())
            self.assertFalse((entrada / "Procesados").exists())
            log_text = (salida / "log_05102026_143000.txt").read_text(
                encoding="utf-8")
            self.assertIn("ERROR", log_text)


if __name__ == "__main__":
    unittest.main()
