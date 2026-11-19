# -*- coding: utf-8 -*-
"""Task 7 — mt940_splitter.py: particionado de un Statement en chunks ≤9800."""

import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import _pathfix  # noqa: F401

from Library import config
from Library.camt053 import Balance, Entry, Statement, parse_document
from Library.mt940_builder import (
    balance_tag,
    build_statement_lines,
    mt940_date,
)
from Library.mt940_splitter import (
    Chunk,
    _block4_size,
    _entry_blocks,
    split_statement_lines,
)
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"
RUN_AT = datetime(2026, 9, 18, 10, 30, 15)
FILENAME = "multi_stmt.xml"


def make_log() -> RunLog:
    return RunLog(now=lambda: RUN_AT)


def _entry(amount, cdt_dbt_ind="CRDT", val_dt="2026-09-15", addtl="",
           ntry_ref="REF-000001"):
    return Entry(
        amount=Decimal(amount),
        amount_ccy="MXN",
        cdt_dbt_ind=cdt_dbt_ind,
        sts="BOOK",
        bookg_dt="2026-09-15",
        val_dt=val_dt,
        rvsl_ind=False,
        ntry_ref=ntry_ref,
        acct_svcr_ref="NONE",
        tx_code="NMSC",
        tx_issr="DEMO",
        tx_details=(),
        addtl_ntry_inf=addtl,
    )


def _stmt(entries, opbd="1000.00", clbd="1000.00", lgl="178", elctrnc="1",
          with_avail=True, ccy="MXN"):
    def bal(code, amount, date):
        return Balance(code, Decimal(amount), ccy, "CRDT", date)

    return Statement(
        stmt_id="STM000007",
        elctrnc_seq_nb=elctrnc,
        lgl_seq_nb=lgl,
        pg_nb="1",
        last_pg_ind="true",
        account="MX18BAN000001100000000001",
        ccy=ccy,
        opening=bal("OPBD", opbd, "2026-09-14"),
        closing=bal("CLBD", clbd, "2026-09-15"),
        avail=bal("CLAV", clbd, "2026-09-15") if with_avail else None,
        entries=tuple(entries),
    )


def _build(entries, **stmt_kw):
    stmt = _stmt(entries, **stmt_kw)
    log = make_log()
    lines = build_statement_lines(stmt, "MSG", config, log, FILENAME)
    return stmt, log, lines


class TestBlock4Size(unittest.TestCase):

    def test_cuantifica_como_envuelve_wrap(self):
        self.assertEqual(_block4_size(["X"]), 10)
        self.assertEqual(_block4_size(["AB", "C"]), 7 + 4 + 3)


class TestMensajePequeno(unittest.TestCase):

    def test_cabe_en_un_solo_chunk_intacto(self):
        entries = [_entry("500.00"), _entry("200.00", cdt_dbt_ind="DBIT")]
        stmt, log, lines = _build(entries, clbd="1300.00")
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=config.MAX_BLOCK4_CHARS)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].ends_with_62m, False)
        self.assertEqual(chunks[0].lines, lines)

    def test_sin_entradas_un_chunk(self):
        stmt, log, lines = _build([], clbd="1000.00")
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=config.MAX_BLOCK4_CHARS)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].lines, lines)


class TestParticionado(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.entries = [_entry("100.00") for _ in range(5)]
        cls.stmt, cls.log, cls.lines = _build(
            cls.entries, clbd="1500.00", lgl="178", elctrnc="1")
        cls.chunks = split_statement_lines(cls.lines, cls.stmt, cls.log,
                                           FILENAME, max_chars=240)

    def test_particiona_en_varios_chunks(self):
        self.assertGreaterEqual(len(self.chunks), 2)

    def test_solo_el_ultimo_cierra_con_62f(self):
        for chunk in self.chunks[:-1]:
            self.assertTrue(chunk.ends_with_62m, msg=chunk.lines)
            self.assertTrue(any(l.startswith(":62M:") for l in chunk.lines))
            self.assertFalse(any(l.startswith((":62F:", ":64:"))
                                 for l in chunk.lines))
        last = self.chunks[-1]
        self.assertFalse(last.ends_with_62m)
        self.assertTrue(any(l.startswith(":62F:") for l in last.lines))
        self.assertTrue(any(l.startswith(":64:") for l in last.lines))

    def test_60m_del_siguiente_es_el_62m_anterior(self):
        for prev, nxt in zip(self.chunks, self.chunks[1:]):
            prev_62m = next(l for l in prev.lines if l.startswith(":62M:"))
            nxt_60m = next(l for l in nxt.lines if l.startswith(":60M:"))
            self.assertEqual(prev_62m.replace(":62M:", ""),
                             nxt_60m.replace(":60M:", ""))

    def test_28c_incrementa_por_chunk(self):
        for i, chunk in enumerate(self.chunks, start=1):
            self.assertIn(f":28C:00178/{i:05d}", chunk.lines)

    def test_entradas_ordenadas_y_completas(self):
        solo_entradas = [
            l for l in self.lines
            if not l.startswith((":20:", ":25:", ":28C:", ":60F:",
                                 ":62F:", ":64:"))]
        de_chunks = [
            l for chunk in self.chunks
            for l in chunk.lines
            if not l.startswith((":20:", ":25:", ":28C:", ":60F:",
                                 ":60M:", ":62M:", ":62F:", ":64:"))]
        self.assertEqual(de_chunks, solo_entradas)

    def test_cada_chunk_respeta_el_limite(self):
        for chunk in self.chunks:
            self.assertLessEqual(_block4_size(chunk.lines), 240)


class TestEntradaTails(unittest.TestCase):
    """Clasificación de líneas: solo tags de cierre REALES van a tail."""

    def test_continuacion_que_empieza_con_62_pertenece_al_bloque(self):
        lines = [
            ":20:REF",
            ":25:H10",
            ":28C:00178/00001",
            ":60F:C260915MXN1000,00",
            ":61:2609150915C100,00NMSCREF-1",
            ":86:nota de cortesia",
            ":62 de cortesia que no es un tag",
            ":62F:C260915MXN1100,00",
            ":64:C260915MXN1100,00",
        ]
        head, blocks, tail = _entry_blocks(lines)
        self.assertEqual(blocks, [[
            ":61:2609150915C100,00NMSCREF-1",
            ":86:nota de cortesia",
            ":62 de cortesia que no es un tag",
        ]])
        self.assertEqual(tail, [":62F:C260915MXN1100,00",
                                ":64:C260915MXN1100,00"])


class TestBalancesCorrientes(unittest.TestCase):

    def test_cierre_con_saldo_corriente_y_continuidad(self):
        entries = [_entry("500.00"), _entry("200.00", cdt_dbt_ind="DBIT")]
        stmt, log, lines = _build(entries, clbd="1300.00", lgl="178")
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=240)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertIn(":62M:C260915MXN1500,00", chunks[0].lines)
        self.assertIn(":60M:C260915MXN1500,00", chunks[1].lines)
        self.assertIn(":62F:C260915MXN1300,00", chunks[-1].lines)


class TestSecuenciaDesdePgNb(unittest.TestCase):
    """SPEC §6.3: el 2º componente de :28C: arranca en StmtPgntn/PgNb."""

    def test_arranca_en_pg_nb_y_suma_por_chunk(self):
        entries = [_entry("100.00") for _ in range(5)]
        _, log, _ = _build(entries, clbd="1500.00")
        stmt = replace(_stmt(entries, clbd="1500.00"), pg_nb="00005")
        lines = build_statement_lines(stmt, "MSG", config, log, FILENAME)
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=240)
        self.assertGreaterEqual(len(chunks), 2)
        for offset, chunk in enumerate(chunks):
            self.assertIn(f":28C:00178/{5 + offset:05d}", chunk.lines)

    def test_fallback_00001_sin_pg_nb(self):
        entries = [_entry("100.00")]
        stmt = replace(_stmt(entries, clbd="1100.00"), pg_nb="")
        lines = build_statement_lines(stmt, "MSG", config, make_log(), FILENAME)
        self.assertIn(":28C:00178/00001", lines)


class TestReservaSplit(unittest.TestCase):
    """SPEC §6.3 (b): el corte por tamaño adelanta la división al aplicar la
    reserva `SPLIT_RESERVE_CHARS` sobre el tamaño proyectado."""

    def test_la_reserva_por_defecto_adelanta_el_corte(self):
        entries = [_entry("100.00") for _ in range(3)]
        stmt, log, lines = _build(entries, clbd="1300.00")
        # Mensaje completo: 301 chars; proyección con la 2ª entrada + :62M:: 181.
        # Presupuesto 351: sin reserva cabe entero (301 <= 351), pero con la
        # reserva de config (120) el corte se adelanta y nace una 2ª parte.
        max_chars = _block4_size(lines) + 50
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=max_chars)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].ends_with_62m)


class TestLimiteExacto(unittest.TestCase):
    """SPEC §7 — frontera exacta del mecanismo B. Una entrada cabe (no corta)
    cuando `proyectado + SPLIT_RESERVE_CHARS <= max_chars`; una entrada
    apenas más grande fuerza el corte a `:62M:` con `:60M:` de continuación."""

    RESERVE = config.SPLIT_RESERVE_CHARS

    @classmethod
    def setUpClass(cls):
        # 3 entradas idénticas 100.00; opening 1000.00. Al evaluar la última,
        # el chunk actual lleva las 2 primeras y el cierre :62M: usa el saldo
        # corriente tras la 2ª: 1000.00 + 100.00 + 100.00 = 1200.00.
        cls.entries = [_entry("100.00") for _ in range(3)]
        cls.stmt, cls.log, cls.lines = _build(cls.entries, clbd="1300.00",
                                              lgl="178", elctrnc="1")
        cls.close = balance_tag("62M", "C", mt940_date("2026-09-15"),
                                "MXN", Decimal("1200.00"))

    def _budget_under(self, lines, extra_chars):
        """max_chars que deja el corte N chars por debajo del proyectado."""
        head, blocks, _ = _entry_blocks(lines)
        projected = _block4_size(head + blocks[0] + blocks[1]
                                 + [self.close] + blocks[2])
        return projected + self.RESERVE - extra_chars

    def test_entrada_que_encaja_justo_en_la_frontera_no_corta(self):
        # proyectado + reserva == max_chars → la 3ª entrada sigue cabiendo.
        max_chars = self._budget_under(self.lines, 0)
        chunks = split_statement_lines(self.lines, self.stmt, self.log, FILENAME,
                                       max_chars=max_chars)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].lines, self.lines)
        self.assertFalse(chunks[0].ends_with_62m)

    def test_una_entrada_mas_grande_fuerza_el_corte(self):
        # La 3ª entrada con un token más de narrativa (X, +2 chars: token +
        # separador) cruza la frontera con el mismo presupuesto nominal.
        entries = [_entry("100.00"), _entry("100.00"),
                   _entry("100.00", addtl="X")]
        stmt, log, lines = _build(entries, clbd="1300.00", lgl="178")
        max_chars = self._budget_under(lines, 2)
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=max_chars)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].ends_with_62m)
        self.assertIn(self.close, chunks[0].lines)
        self.assertIn(":60M:" + self.close[5:], chunks[1].lines)
        self.assertTrue(any(l.startswith(":62F:") for l in chunks[1].lines))
        self.assertIn(":28C:00178/00001", chunks[0].lines)
        self.assertIn(":28C:00178/00002", chunks[1].lines)
        for chunk in chunks:
            self.assertLessEqual(_block4_size(chunk.lines), max_chars)


class TestCorteAMediaEntrada(unittest.TestCase):
    """SPEC §7 — un corte que cae a mitad de un `:86:` nunca parte el bloque
    `:61:`+`:86:`: el par completo (continuaciones incluidas) se desplaza a la
    parte siguiente, entradas completas y en orden."""

    def test_el_bloque_completo_se_desplaza_a_la_parte_siguiente(self):
        # 2 entradas pequeñas + 1 grande cuyo `:86:` envuelve en 2 líneas.
        entries = [_entry("100.00"), _entry("100.00"),
                   _entry("100.00", addtl="A" * 70)]
        stmt, log, lines = _build(entries, clbd="1300.00", lgl="178")
        head, blocks, _ = _entry_blocks(lines)
        close = balance_tag("62M", "C", mt940_date("2026-09-15"),
                            "MXN", Decimal("1200.00"))
        # Presupuesto por debajo de la frontera de la entrada grande: el corte
        # cae justo antes de ella, en medio de lo que sería su `:86:` envuelto.
        projected = _block4_size(head + blocks[0] + blocks[1]
                                 + [close] + blocks[2])
        max_chars = projected + config.SPLIT_RESERVE_CHARS - 1
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=max_chars)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].ends_with_62m)
        self.assertIn(close, chunks[0].lines)
        self.assertIn(":60M:" + close[5:], chunks[1].lines)
        # El bloque grande (con su línea de continuación sin tag) quedó como
        # unidad en la parte 2, sin líneas partidas.
        show = [l for l in chunks[1].lines
                if not l.startswith((":20:", ":25:", ":28C:", ":60M:",
                                     ":62F:", ":64:"))]
        self.assertEqual(show, blocks[-1])
        # Entradas completas y en orden, repartidas entre las partes.
        solo_entradas = [l for l in lines
                         if not l.startswith((":20:", ":25:", ":28C:", ":60F:",
                                              ":62F:", ":64:"))]
        de_chunks = [l for chunk in chunks for l in chunk.lines
                     if not l.startswith((":20:", ":25:", ":28C:", ":60F:",
                                          ":60M:", ":62M:", ":62F:", ":64:"))]
        self.assertEqual(de_chunks, solo_entradas)
        for chunk in chunks:
            self.assertLessEqual(_block4_size(chunk.lines), max_chars)


class TestRegresionITBD(unittest.TestCase):
    """Regresión 18/09/2026 (SPEC §6.3 nota final): un balance intermedio
    `ITBD` en el CAMT de origen NO dispara el corte `_N`. El corte se decide
    exclusivamente por el conteo de caracteres del block4 + reserva; como el
    block4 de este fixture es pequeño → un solo chunk, sin `:62M:`, sin
    sufijo `_2` (chunk único = archivo único)."""

    XML = (
        "<BkToCstmrStmt xmlns='urn:x'>"
        "<GrpHdr><MsgId>ITBD-1</MsgId></GrpHdr>"
        "<Stmt><Id>ITB</Id><ElctrncSeqNb>1</ElctrncSeqNb><LglSeqNb>178</LglSeqNb>"
        "<Acct><Id><Othr><Id>MX18BAN000001100000000001</Id></Othr></Id>"
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

    def test_itbd_de_origen_no_genera_corte_ni_62m(self):
        doc = parse_document(self.XML)
        stmt = doc.statements[0]
        log = make_log()
        lines = build_statement_lines(stmt, doc.msg_id, config, log, FILENAME)
        self.assertLessEqual(_block4_size(lines),
                             config.MAX_BLOCK4_CHARS - config.SPLIT_RESERVE_CHARS)
        chunks = split_statement_lines(lines, stmt, log, FILENAME)
        self.assertEqual(len(chunks), 1)
        self.assertFalse(chunks[0].ends_with_62m)
        self.assertFalse(any(l.startswith(":62M:") for l in chunks[0].lines))
        self.assertTrue(any(l.startswith(":62F:") for l in chunks[0].lines))


class TestBloqueGigante(unittest.TestCase):

    def test_61_que_no_cabe_se_incluye_completo_con_warn(self):
        entrada = _entry("500.00", addtl="X" * 500)
        stmt, log, lines = _build([entrada], clbd="1500.00")
        chunks = split_statement_lines(lines, stmt, log, FILENAME, max_chars=80)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].lines, lines)
        warns = [ev for ev in log.events if "[bloque4" in str(ev)]
        self.assertEqual(len(warns), 1)


class TestLimiteReal(unittest.TestCase):

    def test_fixture_mayor_a_9800_se_particiona(self):
        entries = [_entry("100.00", addtl="EFAECF" * 30) for _ in range(120)]
        stmt, log, lines = _build(entries, clbd="13000.00")
        max_chars = config.MAX_BLOCK4_CHARS
        chunks = split_statement_lines(lines, stmt, log, FILENAME,
                                       max_chars=max_chars)
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            if chunk.ends_with_62m:
                self.assertLessEqual(_block4_size(chunk.lines), max_chars)


if __name__ == "__main__":
    unittest.main()