# -*- coding: utf-8 -*-
"""Checkpoint C — integración: mensaje MT940 y split >9800 (perfil FIN).

Verifica end-to-end (parse→build→wrap y build→split→wrap→join):
1. El mensaje del fixture real tiene la envoltura del perfil FIN de SPEC
   §6.2/§11 ({1:F01…}{2:I940…}{4:, tags a columna 0 separados por CRLF,
   bloques 3/5 OFF por defecto, cierre `-}`).
2. Un statement > MAX_BLOCK4_CHARS se parte en varios mensajes con
   continuidad de saldo (:60M: == :62M: anterior), :28C: secuencial,
   :62F:/:64: solo al final y separador `$` correcto.
"""

import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import _pathfix  # noqa: F401

from Library import config
from Library.camt053 import Balance, Entry, Statement, parse_document
from Library.mt940_builder import build_statement_lines, join_messages, wrap_message
from Library.mt940_splitter import split_statement_lines
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"
RUN_AT = datetime(2026, 9, 18, 10, 30, 15)
FILENAME = "test_camt053.xml"

HEADER = (
    "{1:F01DEMOBKMMAXXX0000000000}"
    "{2:I940DEMORCVGXXXXN}"
)
CLOSE = "-}"


def make_log() -> RunLog:
    return RunLog(now=lambda: RUN_AT)


def body_of(message: str) -> str:
    return message.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]


def tag_line(body: str, prefix: str) -> str:
    return next(l for l in body.split("\r\n")
                if l.lstrip().startswith(prefix))


class TestMensajeReal5Bloques(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.log = make_log()
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        lines = build_statement_lines(
            doc.statements[0], doc.msg_id, config, cls.log, FILENAME)
        cls.msg = wrap_message(
            lines, config,
            reference=doc.statements[0].stmt_id,
            in_time="0309", in_date="260916",
            out_date="260917", out_time="0707")

    def test_cabeceras_fin_y_bloque4(self):
        self.assertTrue(self.msg.startswith(
            HEADER + "{4:\r\n:20:260831000000012\r\n"))

    def test_cierre_del_bloque4_sin_bloque3_ni_5(self):
        self.assertTrue(self.msg.endswith("\r\n" + CLOSE))
        self.assertNotIn("{3:", self.msg)
        self.assertNotIn("{5:", self.msg)

    def test_34_61_dentro_del_bloque4(self):
        body = body_of(self.msg)
        n = len([l for l in body.split("\r\n") if l.startswith(":61:")])
        self.assertEqual(n, 34)

    def test_tags_a_columna_0(self):
        body = body_of(self.msg)
        for line in body.split("\r\n"):
            self.assertFalse(line.startswith(" "), repr(line))

    def test_saldos_cierre_en_el_body(self):
        body = body_of(self.msg)
        self.assertIn(":62F:C260831MXN261430649,29", body)
        self.assertIn(":64:C260831MXN261430649,29", body)

    def test_sin_dolar_ni_salto_final(self):
        self.assertNotIn("$", self.msg)


def _entry(amount, addtl=""):
    return Entry(
        amount=Decimal(amount), amount_ccy="MXN", cdt_dbt_ind="CRDT",
        sts="BOOK", bookg_dt="2026-09-15", val_dt="2026-09-15",
        rvsl_ind=False, ntry_ref="REF-000001", acct_svcr_ref="NONE",
        tx_code="NMSC", tx_issr="DEMO", tx_details=(),
        addtl_ntry_inf=addtl)


def _large_stmt():
    def bal(code, amount, date):
        return Balance(code, Decimal(amount), "MXN", "CRDT", date)

    entries = [_entry("100.00", addtl="EFAECF" * 30) for _ in range(120)]
    closing = "13000.00"
    return Statement(
        stmt_id="STM000007", elctrnc_seq_nb="1", lgl_seq_nb="178",
        pg_nb="1", last_pg_ind="true",
        account="MX18BAN000001100000000001", ccy="MXN",
        opening=bal("OPBD", "1000.00", "2026-09-14"),
        closing=bal("CLBD", closing, "2026-09-15"),
        avail=bal("CLAV", closing, "2026-09-15"),
        entries=tuple(entries))


class TestSplitEnsamblado(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.log = make_log()
        stmt = _large_stmt()
        lines = build_statement_lines(stmt, "MSG", config, cls.log, FILENAME)
        chunks = split_statement_lines(
            lines, stmt, cls.log, FILENAME,
            max_chars=config.MAX_BLOCK4_CHARS)
        cls.chunks = chunks
        cls.messages = [
            wrap_message(c.lines, config, reference=stmt.stmt_id,
                         in_time="0309", in_date="260916",
                         out_date="260917", out_time="0707")
            for c in chunks
        ]
        cls.joined = join_messages(cls.messages)

    def test_particiona_en_varios_mensajes(self):
        self.assertGreaterEqual(len(self.messages), 2)

    def test_cada_mensaje_tiene_cabecera_fin_y_cierre(self):
        for msg in self.messages:
            self.assertTrue(msg.startswith(HEADER + "{4:"))
            self.assertTrue(msg.endswith(CLOSE))

    def test_dolares_entre_mensajes_solo(self):
        self.assertEqual(self.joined.count("$"), len(self.messages) - 1)
        self.assertTrue(all("$" not in m for m in self.messages))
        self.assertFalse(self.joined.endswith("$"))

    def test_28c_secuencial_por_mensaje(self):
        for i, msg in enumerate(self.messages, start=1):
            line = tag_line(body_of(msg), ":28C:")
            self.assertEqual(line.strip(), f":28C:00178/{i:05d}")

    def test_continuidad_de_saldo_entre_mensajes(self):
        for prev, nxt in zip(self.messages, self.messages[1:]):
            prev_62m = tag_line(body_of(prev), ":62M:").strip()
            nxt_60m = tag_line(body_of(nxt), ":60M:").strip()
            self.assertEqual(prev_62m.replace(":62M:", ""),
                             nxt_60m.replace(":60M:", ""))

    def test_62f_solo_en_el_ultimo_mensaje(self):
        for msg in self.messages[:-1]:
            body = body_of(msg)
            self.assertTrue(any(l.startswith(":62M:")
                                for l in body.split("\r\n")))
            self.assertFalse(any(l.startswith(":62F:")
                                 for l in body.split("\r\n")))
        last_body = body_of(self.messages[-1])
        self.assertTrue(any(l.startswith(":62F:")
                            for l in last_body.split("\r\n")))
        self.assertTrue(any(l.startswith(":64:")
                            for l in last_body.split("\r\n")))

    def test_cada_parte_del_split_sigue_siendo_mensaje_valido(self):
        for msg in self.messages:
            body = body_of(msg)
            self.assertTrue(body.split("\r\n")[0].startswith(":20:"))


if __name__ == "__main__":
    unittest.main()