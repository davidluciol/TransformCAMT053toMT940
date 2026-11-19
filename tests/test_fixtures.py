# -*- coding: utf-8 -*-
"""SPEC §4: layout de fixtures (plain / envelope / synthetic_over_limit /
rejected / golden) y su rol en las pruebas."""

import unittest
from pathlib import Path

import _pathfix  # noqa: F401

from Library import config
from Library.camt053 import parse_document
from Library.mt940_builder import build_statement_lines
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"


class TestLayoutDeFixtures(unittest.TestCase):

    def test_plain_es_camt_sin_apphdr(self):
        doc = parse_document((FIXTURES / "plain" / "camt053_plain.xml")
                             .read_text(encoding="utf-8"))
        self.assertEqual(len(doc.statements), 1)
        self.assertEqual(len(doc.statements[0].entries), 34)
        self.assertEqual(doc.apphdr_fr_bic, "")

    def test_envelope_es_camt_con_apphdr(self):
        doc = parse_document((FIXTURES / "envelope" / "camt053_envelope.xml")
                             .read_text(encoding="utf-8"))
        self.assertEqual(len(doc.statements[0].entries), 34)
        self.assertEqual(doc.apphdr_fr_bic, "DEMOBKMMXXX")
        self.assertEqual(doc.apphdr_to_bic, "DEMORCVGXXX")

    def test_golden_tiene_el_camt_real(self):
        doc = parse_document((FIXTURES / "golden" / "test_camt053.xml")
                             .read_text(encoding="utf-8"))
        self.assertEqual(len(doc.statements[0].entries), 34)

    def test_rejected_es_una_sola_parte_de_34(self):
        text = (FIXTURES / "rejected" / "test_camt053_01102026.txt").read_text(
            encoding="utf-8", newline="")
        self.assertEqual(text.count("{1:F01"), 1)
        self.assertEqual(text.count(":61:"), 34)
        self.assertNotIn("$", text)

    def test_synthetic_over_limit_supera_9800(self):
        doc = parse_document((FIXTURES / "synthetic_over_limit"
                              / "camt053_over_limit.xml")
                             .read_text(encoding="utf-8"))
        log = RunLog()
        lines = build_statement_lines(doc.statements[0], doc.msg_id, config,
                                      log, "over.xml")
        size = 7 + sum(len(line) + 2 for line in lines)
        self.assertGreater(size, config.MAX_BLOCK4_CHARS)


if __name__ == "__main__":
    unittest.main()
