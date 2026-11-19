# -*- coding: utf-8 -*-
"""Task 4 — camt053.py: parser XML por contenido → modelo Statement."""

import unittest
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import _pathfix  # noqa: F401

from Library.camt053 import CamtParseError, _parse_balance, parse_document
from Library import config
from Library.mt940_builder import build_statement_lines
from Library.mt940_splitter import split_statement_lines
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseFixtureReal(unittest.TestCase):
    """Fixture real: Envelope SWIFT, 1 Stmt, 34 Ntry, BkTxCd Prtry."""

    @classmethod
    def setUpClass(cls):
        data = (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8")
        cls.doc = parse_document(data)
        cls.stmt = cls.doc.statements[0]

    def test_un_stmt_y_34_entries(self):
        self.assertEqual(len(self.doc.statements), 1)
        self.assertEqual(len(self.stmt.entries), 34)

    def test_apphdr_del_envelope(self):
        self.assertEqual(self.doc.apphdr_fr_bic, "DEMOBKMMXXX")
        self.assertEqual(self.doc.apphdr_to_bic, "DEMORCVGXXX")

    def test_plain_sin_apphdr(self):
        data = (FIXTURES / "multi_stmt.xml").read_text(encoding="utf-8")
        doc = parse_document(data)
        self.assertEqual(doc.apphdr_fr_bic, "")
        self.assertEqual(doc.apphdr_to_bic, "")

    def test_cuenta_via_othr_id(self):
        self.assertEqual(self.stmt.account, "H01-234-567890")
        self.assertEqual(self.stmt.ccy, "MXN")

    def test_secuencias_crudas(self):
        self.assertEqual(self.stmt.elctrnc_seq_nb, "1565")
        self.assertEqual(self.stmt.lgl_seq_nb, "1565")

    def test_opbd_y_clbd(self):
        op = self.stmt.opening
        self.assertEqual(op.code, "OPBD")
        self.assertEqual(op.amount, Decimal("14955145.69"))
        self.assertEqual(op.currency, "MXN")
        self.assertEqual(op.date, "2026-08-31")
        cl = self.stmt.closing
        self.assertEqual(cl.code, "CLBD")
        self.assertEqual(cl.amount, Decimal("261430649.29"))

    def test_todas_las_entries_book(self):
        self.assertTrue(all(e.sts == "BOOK" for e in self.stmt.entries))

    def test_acct_svcr_ref_distingue_none_de_reales(self):
        refs = [e.acct_svcr_ref for e in self.stmt.entries]
        self.assertEqual(sum(r == "NONE" for r in refs), 30)
        real = {r for r in refs if r != "NONE"}
        self.assertEqual(real, {"SES000000001", "SEB000000002",
                                "SEB000000003", "SEB000000004"})

    def test_bk_tx_cd_captura_cd_e_issr(self):
        codes = {(e.tx_code, e.tx_issr) for e in self.stmt.entries}
        self.assertEqual(codes, {("NMSC", "DEMO"), ("NFEX", "DEMO")})

    def test_rvsl_ind_falso_en_todas(self):
        self.assertTrue(all(e.rvsl_ind is False for e in self.stmt.entries))

    def test_fechas_y_importe_de_la_primera_entry(self):
        e = self.stmt.entries[0]
        self.assertEqual(e.val_dt, "2026-08-31")
        self.assertEqual(e.bookg_dt, "2026-08-31")
        self.assertEqual(e.amount, Decimal("38356.13"))
        self.assertEqual(e.amount_ccy, "MXN")
        self.assertEqual(e.ntry_ref, "260831000000012-1")
        self.assertEqual(e.cdt_dbt_ind, "CRDT")

    def test_msg_id_global(self):
        self.assertEqual(self.doc.msg_id, "9999999")

    def test_txt_con_mismo_contenido_parsea_igual(self):
        data_txt = (FIXTURES / "test_camt053.txt").read_text(encoding="utf-8")
        doc_txt = parse_document(data_txt)
        self.assertEqual(len(doc_txt.statements), 1)
        self.assertEqual(len(doc_txt.statements[0].entries), 34)


class TestParseMultiStmt(unittest.TestCase):
    """Fixtures sintético plano (sin Envelope), 2 Stmt."""

    @classmethod
    def setUpClass(cls):
        data = (FIXTURES / "multi_stmt.xml").read_text(encoding="utf-8")
        cls.doc = parse_document(data)

    def test_dos_stmt_con_ids_y_entries_distintos(self):
        self.assertEqual(len(self.doc.statements), 2)
        stmt_a, stmt_b = self.doc.statements
        self.assertEqual(stmt_a.stmt_id, "STM000001")
        self.assertEqual(stmt_b.stmt_id, "STM000002")
        self.assertEqual(len(stmt_a.entries), 2)
        self.assertEqual(len(stmt_b.entries), 1)

    def test_cuenta_iban_y_othr(self):
        self.assertEqual(self.doc.statements[0].account,
                         "MX18BAN000001100000000001")
        self.assertEqual(self.doc.statements[1].account, "H10-999-999999")

    def test_tx_details_instr_y_addtl(self):
        tx = self.doc.statements[0].entries[0].tx_details
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx[0].instr_id, "INSTR-0001")
        self.assertEqual(tx[0].addtl_tx_inf, "TRANSFERENCIA UNO")

    def test_entry_second_stmt_sin_tx_details(self):
        e = self.doc.statements[1].entries[0]
        self.assertEqual(e.tx_details, ())
        self.assertEqual(e.acct_svcr_ref, "NONE")


class TestBkTxCdAnidado(unittest.TestCase):
    """BkTxCd fuera del Ntry directo (bajo NtryDtls/TxDtls/Refs) se captura."""

    def test_bk_tx_cd_bajo_txdtls_refs(self):
        xml = (
            "<BkToCstmrStmt xmlns='urn:x'>"
            "<GrpHdr><MsgId>NESTED-1</MsgId></GrpHdr>"
            "<Stmt><Id>NST</Id><ElctrncSeqNb>1</ElctrncSeqNb>"
            "<LglSeqNb>1</LglSeqNb>"
            "<Acct><Id><Othr><Id>H10-752-000001</Id></Othr></Id>"
            "<Ccy>MXN</Ccy></Acct>"
            "<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>"
            "<Amt Ccy='MXN'>100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
            "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
            "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
            "<Amt Ccy='MXN'>200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
            "<Dt><Dt>2026-09-15</Dt></Dt></Bal>"
            "<Ntry>"
            "<Amt Ccy='MXN'>100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
            "<Sts><Cd>BOOK</Cd></Sts>"
            "<BookgDt><Dt>2026-09-15</Dt></BookgDt>"
            "<ValDt><Dt>2026-09-15</Dt></ValDt>"
            "<NtryRef>REF-N</NtryRef><AcctSvcrRef>NONE</AcctSvcrRef>"
            "<NtryDtls><TxDtls><Refs>"
            "<BkTxCd><Prtry><Cd>NEST</Cd><Issr>BANK</Issr></Prtry></BkTxCd>"
            "</Refs></TxDtls></NtryDtls>"
            "</Ntry></Stmt></BkToCstmrStmt>"
        )
        doc = parse_document(xml)
        entry = doc.statements[0].entries[0]
        self.assertEqual(entry.tx_code, "NEST")
        self.assertEqual(entry.tx_issr, "BANK")


class TestBalanceIntermedio(unittest.TestCase):
    """SPEC 18/09/2026 §6.3 (nota final): un balance intermedio `ITBD` de
    origen se captura como `Balance` sin afectar `opening` (OPBD) ni
    `closing` (CLBD) y sin disparar el corte por tamaño (regresión)."""

    XML = (
        "<BkToCstmrStmt xmlns='urn:x'>"
        "<GrpHdr><MsgId>ITBD-1</MsgId></GrpHdr>"
        "<Stmt><Id>ITB</Id><ElctrncSeqNb>1</ElctrncSeqNb><LglSeqNb>178</LglSeqNb>"
        "<Acct><Id><Othr><Id>H10-752-000001</Id></Othr></Id>"
        "<Ccy>MXN</Ccy></Acct>"
        "<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
        "<Bal><Tp><CdOrPrtry><Cd>ITBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
        "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-15</Dt></Dt></Bal>"
        "<Ntry>"
        "<Amt Ccy='MXN'>100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Sts><Cd>BOOK</Cd></Sts>"
        "<BookgDt><Dt>2026-09-15</Dt></BookgDt>"
        "<ValDt><Dt>2026-09-15</Dt></ValDt>"
        "<NtryRef>REF-1</NtryRef><AcctSvcrRef>NONE</AcctSvcrRef>"
        "</Ntry>"
        "<Ntry>"
        "<Amt Ccy='MXN'>100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Sts><Cd>BOOK</Cd></Sts>"
        "<BookgDt><Dt>2026-09-15</Dt></BookgDt>"
        "<ValDt><Dt>2026-09-15</Dt></ValDt>"
        "<NtryRef>REF-2</NtryRef><AcctSvcrRef>NONE</AcctSvcrRef>"
        "</Ntry>"
        "</Stmt></BkToCstmrStmt>"
    )

    def test_itbd_se_parsea_como_balance(self):
        bal = ET.fromstring(
            "<Bal><Tp><CdOrPrtry><Cd>ITBD</Cd></CdOrPrtry></Tp>"
            "<Amt Ccy='MXN'>1100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
            "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
        )
        parsed = _parse_balance(bal)
        self.assertEqual(parsed.code, "ITBD")
        self.assertEqual(parsed.amount, Decimal("1100.00"))
        self.assertEqual(parsed.currency, "MXN")
        self.assertEqual(parsed.cdt_dbt_ind, "CRDT")
        self.assertEqual(parsed.date, "2026-09-14")

    def test_opening_y_closing_quedan_en_opbd_y_clbd_pese_al_itbd(self):
        doc = parse_document(self.XML)
        stmt = doc.statements[0]
        self.assertEqual((stmt.opening.code, stmt.opening.amount),
                         ("OPBD", Decimal("1000.00")))
        self.assertEqual((stmt.closing.code, stmt.closing.amount),
                         ("CLBD", Decimal("1200.00")))
        self.assertEqual(len(stmt.entries), 2)


class TestMultiPagina(unittest.TestCase):
    """SPEC §13.9: página intermedia (`PgNb>1`, `LastPgInd=false`, cierre ITBD).

    Una página que no cierra el estado no trae `CLBD`; se usa `ITBD` como saldo
    de cierre para que la página no falle y `:28C:` arranque en `PgNb`. La
    continuidad entre páginas (`:62M:`/`:60M:`) queda fuera de este fixture.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = parse_document(
            (FIXTURES / "multipage" / "camt053_pagina2.xml")
            .read_text(encoding="utf-8"))
        cls.stmt = cls.doc.statements[0]

    def test_pg_nb_y_last_pg_ind(self):
        self.assertEqual(self.stmt.pg_nb, "00002")
        self.assertEqual(self.stmt.last_pg_ind, "false")

    def test_closing_cae_a_itbd_si_no_hay_clbd(self):
        self.assertIsNotNone(self.stmt.closing)
        self.assertEqual(self.stmt.closing.code, "ITBD")
        self.assertEqual(self.stmt.closing.amount, Decimal("1100.00"))

    def test_28c_arranca_en_pg_nb(self):
        lines = build_statement_lines(self.stmt, self.doc.msg_id, config,
                                      RunLog(), "pagina2.xml")
        self.assertIn(":28C:01649/00002", lines)

    def test_itbd_no_dispara_corte(self):
        log = RunLog()
        lines = build_statement_lines(self.stmt, self.doc.msg_id, config, log,
                                      "pagina2.xml")
        chunks = split_statement_lines(lines, self.stmt, log, "pagina2.xml")
        self.assertEqual(len(chunks), 1)
        self.assertTrue(any(l.startswith(":62F:") for l in chunks[0].lines))
        self.assertEqual(len(self.stmt.entries), 1)


class TestErrores(unittest.TestCase):

    def test_xml_invalido_levanta_camt_parse_error(self):
        with self.assertRaises(CamtParseError):
            parse_document("esto no es xml")

    def test_raiz_no_camt_levanta_camt_parse_error(self):
        with self.assertRaises(CamtParseError):
            parse_document("<foo><bar>1</bar></foo>")

    def test_bk_sin_stmt_levanta_camt_parse_error(self):
        with self.assertRaises(CamtParseError):
            parse_document("<BkToCstmrStmt x='y'/>")

    def test_error_indica_no_es_camt(self):
        try:
            parse_document("<html/>")
        except CamtParseError as exc:
            self.assertIn("CAMT", str(exc))
        else:
            self.fail("debió levantar CamtParseError")


if __name__ == "__main__":
    unittest.main()