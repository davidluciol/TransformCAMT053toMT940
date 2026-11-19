# -*- coding: utf-8 -*-
"""Tasks 5/19/20 — mt940_builder.py: tags :20:..:64:, :61:, :86:, envoltura
template-driven (perfil FIN + legado) y validadores obligatorios (§6.4/§12.4)."""

import hashlib
import unittest
from dataclasses import replace as dreplace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import _pathfix  # noqa: F401

from Library import config
from Library.camt053 import Balance, Entry, Statement, TxDetails, parse_document
from Library.mt940_builder import (
    BalanceMismatchError,
    Mt940BuildError,
    balance_line,
    build_field_61,
    build_field_86,
    build_statement_lines,
    build_supplementary_line,
    dc,
    entry_delta,
    format_amount,
    join_messages,
    mmdd,
    mt940_date,
    ref20,
    split_narrative,
    tx_type,
    validate_field_61,
    validate_field_86,
    wrap_field_86,
    wrap_message,
)
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"
RUN_AT = datetime(2026, 9, 18, 10, 30, 15)
FILENAME = "test_camt053.xml"


def make_log() -> RunLog:
    return RunLog(now=lambda: RUN_AT)


class TestHelpers(unittest.TestCase):

    def test_format_amount_comma_decimal(self):
        self.assertEqual(format_amount(Decimal("38356.13")), "38356,13")

    def test_format_amount_enteros_dos_decimales(self):
        self.assertEqual(format_amount(Decimal("150000000")), "150000000,00")

    def test_format_amount_cero(self):
        self.assertEqual(format_amount(Decimal("0.00")), "0,00")

    def test_dc_crdt_dbty_desconocido(self):
        self.assertEqual(dc("CRDT"), "C")
        self.assertEqual(dc("DBIT"), "D")
        self.assertEqual(dc("NOPE"), "")

    def test_mt940_date_de_iso(self):
        self.assertEqual(mt940_date("2026-08-31"), "260831")

    def test_mt940_date_vacio(self):
        self.assertEqual(mt940_date(""), "")

    def test_mmdd_de_iso(self):
        self.assertEqual(mmdd("2026-08-31"), "0831")


class TestRef20(unittest.TestCase):

    def test_id_corto_se_usa_directo(self):
        log = make_log()
        self.assertEqual(ref20("260831000000012", "MSG", log, FILENAME),
                         "260831000000012")
        self.assertEqual(log.events, [])

    def test_msg_id_como_fallback_si_stmt_sin_id(self):
        log = make_log()
        self.assertEqual(ref20("", "9999999", log, FILENAME), "9999999")

    def test_largo_usa_fallback_c_sha256(self):
        log = make_log()
        ref = ref20("12345678901234567890", "MSG", log, FILENAME)
        self.assertTrue(ref.startswith("C"))
        self.assertEqual(len(ref), 16)
        self.assertEqual(ref, "C" + hashlib.sha256(
            b"12345678901234567890").hexdigest()[:15])
        self.assertEqual(len(log.events), 1)

    def test_slashes_invalidos_usan_fallback_c_sha256(self):
        """SWIFT :20: no admite '/' inicial/final ni '//' (doc SWIFT)."""
        for malo in ("/ABC/", "A//B", "/LEAD", "TRAIL/"):
            with self.subTest(valor=malo):
                log = make_log()
                ref = ref20(malo, "MSG", log, FILENAME)
                self.assertTrue(ref.startswith("C"))
                self.assertEqual(len(ref), 16)
                self.assertEqual(len(log.events), 1)


class TestBalanceLine(unittest.TestCase):

    def test_crédito(self):
        b = Balance("OPBD", Decimal("14955145.69"), "MXN", "CRDT", "2026-08-31")
        self.assertEqual(balance_line("60F", b, config, make_log(), FILENAME),
                         ":60F:C260831MXN14955145,69")

    def test_DBIT(self):
        b = Balance("CLBD", Decimal("100.50"), "MXN", "DBIT", "2026-09-01")
        self.assertEqual(balance_line("62F", b, config, make_log(), FILENAME),
                         ":62F:D260901MXN100,50")

    def test_acepta_formato_swift_1a6n3a15d(self):
        b = Balance("CLBD", Decimal("1234567.89"), "USD", "CRDT", "2026-09-16")
        self.assertEqual(balance_line("62F", b, config, make_log(), FILENAME),
                         ":62F:C260916USD1234567,89")

    def test_rechaza_moneda_no_3a(self):
        b = Balance("OPBD", Decimal("1"), "MX", "CRDT", "2026-09-16")
        with self.assertRaises(Mt940BuildError):
            balance_line("60F", b, config, make_log(), FILENAME)

    def test_rechaza_fecha_no_6n(self):
        b = Balance("OPBD", Decimal("1"), "MXN", "CRDT", "2026-9")
        with self.assertRaises(Mt940BuildError):
            balance_line("60F", b, config, make_log(), FILENAME)

    def test_rechaza_cdt_dbt_ind_desconocido(self):
        """Un CdtDbtInd fuera de CRDT/DBIT es ERROR, no un 'C' silencioso."""
        b = Balance("OPBD", Decimal("1"), "MXN", "XX", "2026-09-16")
        with self.assertRaises(Mt940BuildError):
            balance_line("60F", b, config, make_log(), FILENAME)


class TestTxType(unittest.TestCase):

    def test_codigo_prtry_4_chars_se_usa(self):
        e = _fake_entry()
        self.assertEqual(tx_type(e, config, make_log(), FILENAME), "NMSC")

    def test_domn_desconocido_cae_a_nmsc_con_warn(self):
        log = make_log()
        e = dreplace(_fake_entry(), tx_code="ABC", tx_issr="X")
        self.assertEqual(tx_type(e, config, log, FILENAME), "NMSC")
        self.assertEqual(len(log.events), 1)
        self.assertIn("[tx-type]", str(log.events[0]))


class TestBuildField61(unittest.TestCase):

    def _sufijo(self, owner: str, bank: str) -> str:
        return owner.ljust(16) + "//" + bank.ljust(16)

    def test_nmsc_credito_owner_instr_id_bank_none(self):
        e = _fake_entry()
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831C38356,13NMSC"
                         + self._sufijo("INSTR-0001", "NONE"))

    def test_bank_ref_ses_conservada(self):
        e = dreplace(_fake_entry(), acct_svcr_ref="SES000000001")
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831C38356,13NMSC"
                         + self._sufijo("INSTR-0001", "SES000000001"))

    def test_dbit_nfex(self):
        e = dreplace(_fake_entry(), amount=Decimal("150000000.00"),
                     cdt_dbt_ind="DBIT", tx_code="NFEX")
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831D150000000,00NFEX"
                         + self._sufijo("INSTR-0001", "NONE"))

    def test_rvsl_usa_rc(self):
        e = dreplace(_fake_entry(), rvsl_ind=True, cdt_dbt_ind="CRDT")
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831RC38356,13NMSC"
                         + self._sufijo("INSTR-0001", "NONE"))

    def test_rvsl_dbit_usa_rd(self):
        e = dreplace(_fake_entry(), rvsl_ind=True, cdt_dbt_ind="DBIT")
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831RD38356,13NMSC"
                         + self._sufijo("INSTR-0001", "NONE"))

    def test_owner_ref_16x_truncado_con_warn(self):
        log = make_log()
        e = dreplace(_fake_entry(), tx_details=(
            TxDetails(instr_id="ABCDEFGHIJKLMNOPQ"),))
        self.assertEqual(build_field_61(e, config, log, FILENAME).split("//")[0],
                         ":61:2608310831C38356,13NMSCABCDEFGHIJKLMNOP")
        self.assertEqual(len([ev for ev in log.events if "truncado" in str(ev)]), 1)

    def test_owner_ref_corta_se_padea_a_16(self):
        e = dreplace(_fake_entry(), tx_details=(TxDetails(instr_id="REF-1"),))
        self.assertEqual(build_field_61(e, config, make_log(), FILENAME),
                         ":61:2608310831C38356,13NMSC"
                         + self._sufijo("REF-1", "NONE"))

    def test_rechaza_cdt_dbt_ind_desconocido(self):
        e = dreplace(_fake_entry(), cdt_dbt_ind="XX")
        with self.assertRaises(Mt940BuildError):
            build_field_61(e, config, make_log(), FILENAME)

    def test_rechaza_cdt_dbt_ind_desconocido_en_reverso(self):
        e = dreplace(_fake_entry(), cdt_dbt_ind="XX", rvsl_ind=True)
        with self.assertRaises(Mt940BuildError):
            build_field_61(e, config, make_log(), FILENAME)


class TestEntryDelta(unittest.TestCase):
    """SPEC §6.4: CRDT suma, DBIT resta; cualquier otro valor es ERROR."""

    def test_crdt_y_dbit(self):
        self.assertEqual(entry_delta(_fake_entry()), Decimal("38356.13"))
        e = dreplace(_fake_entry(), cdt_dbt_ind="DBIT")
        self.assertEqual(entry_delta(e), Decimal("-38356.13"))

    def test_rechaza_cdt_dbt_ind_desconocido(self):
        e = dreplace(_fake_entry(), cdt_dbt_ind="XX")
        with self.assertRaises(Mt940BuildError):
            entry_delta(e)


class TestBuildField86(unittest.TestCase):

    def test_solo_addtl_ntry_inf(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="PRINCIPAL MXN38,356.13",
                     ntry_ref="260831000000012-1", acct_svcr_ref="SES1")
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:PRINCIPAL MXN38,356.13"])

    def test_no_incluye_addtl_tx_inf_ni_refs(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="PRINCIPAL",
                     ntry_ref="260831000000012-1", acct_svcr_ref="SES1")
        linea = build_field_86(e, config, make_log(), FILENAME)[0]
        self.assertNotIn("TRANSFERENCIA UNO", linea)
        self.assertNotIn("260831000000012", linea)
        self.assertNotIn("SES1", linea)

    def test_acentos_se_pliegan(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="Générale")
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:Generale"])

    def test_caracteres_invalidos_producen_warn(self):
        log = make_log()
        e = dreplace(_fake_entry(), addtl_ntry_inf="Pago €100%")
        build_field_86(e, config, log, FILENAME)
        self.assertTrue(any("[charset]" in str(ev) for ev in log.events))

    def test_dobles_espacios_no_se_colapsan(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="0011  CCN000000001")
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:0011  CCN000000001"])

    def test_sin_addtl_ntry_inf_no_genera_86(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="", tx_details=())
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME), [])

    def test_overflow_trunca_con_warn_86_overflow(self):
        log = make_log()
        e = dreplace(_fake_entry(), addtl_ntry_inf="X" * 500)
        lines = build_field_86(e, config, log, FILENAME)
        self.assertLessEqual(len(lines), config.FIELD_86_MAX_LINES)
        self.assertTrue(lines[0].startswith(":86:"))
        self.assertTrue(any("[86_OVERFLOW]" in str(ev) for ev in log.events))


class TestCampo86Spec66(unittest.TestCase):
    """SPEC §6.6: :86: solo desde AddtlNtryInf, split de narrativa y wrap."""

    def test_fx_se_parte_en_cuatro_lineas(self):
        fx = ("FOREIGN EXCHANGE, CONTRACT DATE 2026-08-28, OUR SALE "
              "USD8,799,408.68EXCH.RATE 17.0466")
        e = dreplace(_fake_entry(), addtl_ntry_inf=fx)
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:FOREIGN EXCHANGE",
                          "CONTRACT DATE 2026-08-28",
                          "OUR SALE USD8,799,408.68",
                          "EXCH.RATE 17.0466"])

    def test_coma_de_importe_no_parte(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="OUR SALE USD8,799,408.68")
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:OUR SALE USD8,799,408.68"])

    def test_narrativa_sin_patrones_queda_en_una_linea(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="PRINCIPAL MXN38,356.13")
        self.assertEqual(build_field_86(e, config, make_log(), FILENAME),
                         [":86:PRINCIPAL MXN38,356.13"])

    def test_token_irrompible_hard_split_con_warn(self):
        log = make_log()
        e = dreplace(_fake_entry(), addtl_ntry_inf="A1" * 80)
        lines = build_field_86(e, config, log, FILENAME)
        self.assertTrue(any("[86_HARD_SPLIT]" in str(ev) for ev in log.events))
        self.assertTrue(all(len(line) <= 65 for line in lines))

    def test_prefijo_de_suplementaria_se_antepone(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="COLA")
        self.assertEqual(
            build_field_86(e, config, make_log(), FILENAME, prefix="RESTO"),
            [":86:RESTO COLA"])

    def test_split_narrative_orden_de_patrones(self):
        self.assertEqual(split_narrative("A, B, CDEXCH.RATE 9.3"),
                         ["A", "B", "CD", "EXCH.RATE 9.3"])

    def test_info_cuando_la_entrada_no_tiene_narrativa(self):
        log = make_log()
        e = dreplace(_fake_entry(), tx_details=(), addtl_ntry_inf="")
        stmt = Statement(
            stmt_id="S1", elctrnc_seq_nb="1", lgl_seq_nb="1", pg_nb="1",
            last_pg_ind="true", account="ACC", ccy="MXN",
            opening=Balance("OPBD", Decimal("0"), "MXN", "CRDT", "2026-08-31"),
            closing=Balance("CLBD", Decimal("38356.13"), "MXN", "CRDT",
                            "2026-08-31"),
            avail=None, entries=(e,))
        build_statement_lines(stmt, "MSG", config, log, FILENAME)
        info = [ev for ev in log.events if ev.level == "INFO"]
        self.assertEqual(len(info), 1)
        self.assertIn("sin narrativa", str(info[0]))

    def test_elementos_descartados_warn_agregado_por_stmt(self):
        log = make_log()
        e = dreplace(_fake_entry(), addtl_ntry_inf="X",
                     tx_details=(TxDetails(instr_id="I1", ustrd="PAGO",
                                           uetr="U1"),))
        stmt = Statement(
            stmt_id="S1", elctrnc_seq_nb="1", lgl_seq_nb="1", pg_nb="1",
            last_pg_ind="true", account="ACC", ccy="MXN",
            opening=Balance("OPBD", Decimal("0"), "MXN", "CRDT", "2026-08-31"),
            closing=Balance("CLBD", Decimal("38356.13"), "MXN", "CRDT",
                            "2026-08-31"),
            avail=None, entries=(e,))
        build_statement_lines(stmt, "MSG", config, log, FILENAME)
        eventos = [ev for ev in log.events if "86_SOURCE_OMITTED" in str(ev)]
        self.assertEqual(len(eventos), 1)
        self.assertIn("Ustrd", str(eventos[0]))
        self.assertIn("UETR", str(eventos[0]))


class TestValidateField61(unittest.TestCase):
    """Task 20 — gramática obligatoria del :61: (SPEC §6.4/§12.4)."""

    def test_acepta_lineas_padeadas_reales(self):
        for value in (
            ":61:2608310831C38356,13NMSCNONE            //NONE            ",
            ":61:2608310831D150000000,00NFEXNONE            //SES000000001    ",
            ":61:2608310831RC38356,13NMSCNONE            //NONE            ",
            ":61:2608310831RD38356,13NMSCNONE            //NONE            ",
            ":61:260831C38356,13NMSCNONE            //NONE            ",
            ":61:2608310831DN38356,13NMSCNONE            //NONE            ",
        ):
            self.assertEqual(validate_field_61(value), value)

    def test_acepta_sin_padding_si_padded_false(self):
        for value in (
            ":61:2608310831C38356,13NMSC260831000000012",
            ":61:2608310831D150000000,00NFEX260831000000012//SES000000001",
            ":61:2608310831RC38356,13NMSCREF-000001",
            ":61:2608310831C38356,13NMSCANONREF",
        ):
            self.assertEqual(validate_field_61(value, padded=False), value)

    def test_rechaza_narrativa_pegada(self):
        """Regresión §11: 'Payee…' pegado a la línea primaria."""
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C138285,28NMSC260831000000012"
                              " Payee : DEMORCVG PRINCIPAL MX")

    def test_rechaza_monto_con_punto_decimal(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C38356.13NMSCREF-000001")

    def test_rechaza_monto_mayusculo(self):
        """15d: >13 dígitos enteros no cabe en la gramática."""
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C12345678901234,00NMSCREF-000001")

    def test_rechaza_bank_ref_largo(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C38356,13NMSCREF-000001"
                              "//ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def test_rechaza_estructura_invalida(self):
        for value in (":61:", ":61:2608310831C38356,13", ":61:XX"):
            with self.assertRaises(Mt940BuildError, msg=value):
                validate_field_61(value)

    def test_build_field_61_valida_antes_de_devolver(self):
        """Una entrada cuyo monto excede 15d nunca sale serializada."""
        e = dreplace(_fake_entry(), amount=Decimal("12345678901234.00"))
        with self.assertRaises(Mt940BuildError):
            build_field_61(e, config, make_log(), FILENAME)


class TestWrapField86(unittest.TestCase):
    """Task 20 — wrap determinista 65 × 6 del :86:."""

    def test_prefijo_en_linea_unica(self):
        self.assertEqual(wrap_field_86("HOLA MUNDO"), [":86:HOLA MUNDO"])

    def test_linea_hasta_el_ancho_exacto(self):
        text = "X" * 61
        lines = wrap_field_86(text)
        self.assertEqual(lines, [":86:" + text])
        self.assertEqual(len(lines[0]), 65)

    def test_envuelve_sin_pasar_65(self):
        lines = wrap_field_86("PALABRA " * 40)
        self.assertTrue(all(len(l) <= 65 for l in lines))
        self.assertTrue(lines[0].startswith(":86:"))

    def test_max_lines(self):
        lines = wrap_field_86("PALABRA " * 200, max_lines=6)
        self.assertLessEqual(len(lines), 6)


class TestValidateField86(unittest.TestCase):
    """Task 20 — :86: estricto ≤6×65, prefijo único, sin tags en continuaciones."""

    def test_acepta_narrativa_real_del_fixture(self):
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        stmt = doc.statements[0]
        for entry in stmt.entries:
            lines = build_field_86(entry, config, make_log(), FILENAME)
            if lines:
                validate_field_86(lines)

    def test_rechaza_linea_mayor_a_65(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:" + "X" * 70])

    def test_rechaza_continuacion_mayor_a_65(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:a", "b" * 66])

    def test_rechaza_mas_de_seis_lineas(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:a"] + ["b"] * 6)

    def test_rechaza_prefijo_doble(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:texto con :86: duplicado"])

    def test_rechaza_sin_prefijo_al_inicio(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86(["narrativa sin tag"])

    def test_rechaza_continuacion_con_tag(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:texto", ":25:continua"])

    def test_rechaza_continuacion_con_otro_86(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_86([":86:texto", ":86:otro bloque"])

    def test_build_field_86_valida_lo_que_devuelve(self):
        e = dreplace(_fake_entry(), addtl_ntry_inf="X" * 500)
        lines = build_field_86(e, config, make_log(), FILENAME)
        self.assertTrue(lines)
        validate_field_86(lines)


class TestGateWrapMessage(unittest.TestCase):
    """Task 20 — wrap_message valida el bloque 4 antes de serializar."""

    def _wrap(self, lines):
        return wrap_message(lines, config, reference="X",
                            in_time="0309", in_date="260916",
                            out_date="260917", out_time="0707")

    def test_rechaza_61_con_narrativa_pegada(self):
        with self.assertRaises(Mt940BuildError):
            self._wrap([":61:2608310831C138285,28NMSC260831000000012"
                        " Payee : DEMORCVG PRINCIPAL MX"])

    def test_rechaza_86_demasiado_largo(self):
        with self.assertRaises(Mt940BuildError):
            self._wrap([":86:" + "X" * 70])

    def test_deja_pasar_lineas_validas(self):
        valida = ":61:2608310831C38356,13NMSCNONE            //NONE            "
        msg = self._wrap([
            valida,
            "FT00000S0001".ljust(34),
            ":86:PRINCIPAL MXN38,356.13",
        ])
        self.assertIn(valida, msg)


class TestBuildFixtureReal(unittest.TestCase):
    """Fixture real: 34 :61:, saldos cuadrados, :64: desde CLAV."""

    @classmethod
    def setUpClass(cls):
        cls.log = make_log()
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        cls.lines = build_statement_lines(
            doc.statements[0], doc.msg_id, config, cls.log, FILENAME)

    def test_tags_de_cabecera(self):
        self.assertEqual(self.lines[0], ":20:260831000000012")
        self.assertEqual(self.lines[1], ":25:H01-234-567890")
        self.assertEqual(self.lines[2], ":28C:01565/00001")

    def test_34_lineas_61(self):
        n = len([l for l in self.lines if l.startswith(":61:")])
        self.assertEqual(n, 34)

    def test_las_34_61_reales_pasan_la_gramatica(self):
        """Criterio §9.2: ninguna :61: real lleva narrativa pegada."""
        n = 0
        for line in self.lines:
            if line.startswith(":61:"):
                validate_field_61(line)
                n += 1
        self.assertEqual(n, 34)

    def test_saldos_con_formato(self):
        self.assertEqual(self.lines[3], ":60F:C260831MXN14955145,69")
        self.assertIn(":62F:C260831MXN261430649,29", self.lines)
        self.assertIn(":64:C260831MXN261430649,29", self.lines)

    def test_primera_entrada_owner_none_sin_ntry_ref(self):
        self.assertIn(
            ":61:2608310831C38356,13NMSCNONE            //NONE            ",
            self.lines)
        for line in self.lines:
            if line.startswith(":61:"):
                self.assertNotIn("260831000000012", line,
                                 "el :61: no debe filtrar el NtryRef del banco")

    def test_linea_suplementaria_padeada_a_34(self):
        idx = self.lines.index(
            ":61:2608310831C38356,13NMSCNONE            //NONE            ")
        self.assertEqual(self.lines[idx + 1], "FT00000S0001".ljust(34))

    def test_entrada_forex_debito_con_ref_banco(self):
        self.assertIn(
            ":61:2608310831D150000000,00NFEXNONE            //SES000000001    ",
            self.lines)

    def test_narrativa_primera_entrada(self):
        linea = next(l for l in self.lines if l.startswith(":86:"))
        self.assertEqual(linea, ":86:PRINCIPAL MXN38,356.13")

    def test_refs_del_fixture_sin_truncados(self):
        n = len([ev for ev in self.log.events if "61: ref: truncado" in str(ev)])
        self.assertEqual(n, 0)

    def test_sin_errores_de_saldo(self):
        self.assertEqual(
            len([ev for ev in self.log.events if ev.level == "ERROR"]), 0)


class TestBuildMultiStmt(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        log = RunLog(now=lambda: RUN_AT)
        doc = parse_document(
            (FIXTURES / "multi_stmt.xml").read_text(encoding="utf-8"))
        cls.a = build_statement_lines(doc.statements[0], doc.msg_id,
                                      config, log, "multi_stmt.xml")
        cls.b = build_statement_lines(doc.statements[1], doc.msg_id,
                                      config, log, "multi_stmt.xml")

    def test_stmt_a_iban_y_secuencia(self):
        self.assertEqual(self.a[0], ":20:STM000001")
        self.assertEqual(self.a[1], ":25:MX18BAN000001100000000001")
        self.assertEqual(self.a[2], ":28C:00001/00001")

    def test_stmt_a_todas_las_lineas(self):
        self.assertEqual(self.a, [
            ":20:STM000001",
            ":25:MX18BAN000001100000000001",
            ":28C:00001/00001",
            ":60F:C260914MXN1000,00",
            ":61:2609150915C500,00NMSCINSTR-0001      //SVCR-0001       ",
            "TRANSFERENCIA UNO                 ",
            ":61:2609150915D200,00NFEXINSTR-0002      //NONE            ",
            "COMPRA DIVISA                     ",
            ":62F:C260915MXN1300,00",
        ])

    def test_stmt_b_sin_clav_no_emite_64(self):
        self.assertNotIn(":64:", self.b)
        self.assertEqual(self.b[-1], ":62F:C260915MXN100,00")
        self.assertEqual(
            self.b[-2], ":61:2609150915C100,00NMSCNONE            //NONE            ")
        self.assertFalse(any(l.startswith(":86:") for l in self.b),
                         "sin AddtlNtryInf el :86: se omite")

    def test_lineas_debloques_tienen_al_menos_un_tag(self):
        for line in self.b:
            self.assertTrue(line.startswith(":"))


class TestValidaciones(unittest.TestCase):

    def test_desfase_de_saldo_levanta_error(self):
        doc = parse_document(
            (FIXTURES / "multi_stmt.xml").read_text(encoding="utf-8"))
        stmt = doc.statements[0]
        malo = dreplace(stmt, closing=dreplace(stmt.closing,
                                               amount=Decimal("9999.00")))
        with self.assertRaises(BalanceMismatchError):
            build_statement_lines(malo, doc.msg_id, config, make_log(), FILENAME)

    def test_error_es_tipo_mt940_build_error(self):
        self.assertTrue(issubclass(BalanceMismatchError, Mt940BuildError))

    def test_no_book_excluidas_con_warn(self):
        log = make_log()
        doc = parse_document(
            (FIXTURES / "multi_stmt.xml").read_text(encoding="utf-8"))
        stmt = doc.statements[0]
        con_pdng = dreplace(stmt, entries=(
            dreplace(stmt.entries[0], sts="PDNG"), stmt.entries[1]))
        esperado = dreplace(con_pdng,
                            closing=Balance("CLBD", Decimal("800.00"), "MXN",
                                            "CRDT", "2026-09-15"))
        lines = build_statement_lines(esperado, doc.msg_id, config, log,
                                      FILENAME)
        n = len([l for l in lines if l.startswith(":61:")])
        self.assertEqual(n, 1)
        self.assertEqual(
            len([ev for ev in log.events if "[NO-BOOK]" in str(ev)]), 1)


class TestWrapMessage(unittest.TestCase):
    """Task 19 — envoltura template-driven del perfil FIN (SPEC §6.2/§11)."""

    @classmethod
    def setUpClass(cls):
        cls.log = make_log()
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        cls.lines = build_statement_lines(
            doc.statements[0], doc.msg_id, config, cls.log, FILENAME)
        cls.msg = wrap_message(
            cls.lines, config, reference="260831000000012",
            in_time="0309", in_date="260916", out_date="260917", out_time="0707")

    def test_cabeceras_f01_i940_y_bloque4(self):
        self.assertTrue(self.msg.startswith(
            "{1:F01DEMOBKMMAXXX0000000000}"
            "{2:I940DEMORCVGXXXXN}"
            "{4:\r\n:20:260831000000012\r\n"))

    def test_sin_bloque3_5_ni_wrapper_f21_por_defecto(self):
        self.assertNotIn("{3:", self.msg)
        self.assertNotIn("{5:", self.msg)
        self.assertNotIn("{S:", self.msg)
        self.assertNotIn("F21", self.msg)
        self.assertNotIn("{177:", self.msg)

    def test_cierre_bloque4(self):
        self.assertTrue(self.msg.endswith("\r\n-}"))

    def test_tags_a_columna_0(self):
        body = self.msg.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]
        for line in body.split("\r\n"):
            self.assertFalse(line.startswith(" "), repr(line))
        self.assertIn("\r\n:62F:C260831MXN261430649,29\r\n", self.msg)
        self.assertIn("\r\n:64:C260831MXN261430649,29\r\n", self.msg)

    def test_34_entradas_dentro_del_bloque4(self):
        body = self.msg.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]
        n = len([l for l in body.split("\r\n") if l.startswith(":61:")])
        self.assertEqual(n, 34)

    def test_sin_dolar_al_final_del_mensaje(self):
        self.assertNotIn("$", self.msg)


class TestWrapBloquesOpcionales(unittest.TestCase):
    """Task 19 — BLOCK3/BLOCK5 opcionales (default OFF) en el perfil FIN."""

    def setUp(self):
        self.prev3 = config.BLOCK3_ENABLED
        self.prev5 = config.BLOCK5_ENABLED

    def tearDown(self):
        config.BLOCK3_ENABLED = self.prev3
        config.BLOCK5_ENABLED = self.prev5

    def _wrap(self):
        return wrap_message([":20:X"], config, reference="REFX",
                            in_time="0309", in_date="260916",
                            out_date="260917", out_time="0707")

    def test_bloque3_aparece_si_se_habilita(self):
        config.BLOCK3_ENABLED = True
        msg = self._wrap()
        self.assertIn("}{3:{108:REFX}}{4:", msg)

    def test_bloque5_aparece_si_se_habilita(self):
        config.BLOCK5_ENABLED = True
        msg = self._wrap()
        self.assertTrue(msg.endswith(
            "\r\n-}{5:{CHK:A1B2C3D4E5F6}{DLM:}}{S:{COP:P}}"))

    def test_default_sin_bloque3_ni_bloque5(self):
        msg = self._wrap()
        self.assertNotIn("{3:", msg)
        self.assertNotIn("{5:", msg)
        self.assertNotIn("{S:", msg)
        self.assertTrue(msg.endswith("\r\n-}"))


class TestWrapBlock2Dinamico(unittest.TestCase):
    """Task 19 — el bloque 2 cambia por config sin reescribir wrap_message."""

    def _wrap(self):
        return wrap_message([":20:X"], config, reference="X",
                            in_time="0309", in_date="260916",
                            out_date="260917", out_time="0707")

    def test_receiver_address_dinamico_por_config(self):
        prev = config.RECEIVER_ADDRESS
        config.RECEIVER_ADDRESS = "DEMOLGCYXXXX"
        try:
            msg = self._wrap()
        finally:
            config.RECEIVER_ADDRESS = prev
        self.assertIn("{2:I940DEMOLGCYXXXXN}", msg)

    def test_template_de_bloque2_dinamico_por_config(self):
        prev = config.BLOCK2_TEMPLATE
        config.BLOCK2_TEMPLATE = "{2:I{MSG_TYPE}{RECEIVER_ADDRESS}{PRIORITY}}"
        try:
            msg = self._wrap()
        finally:
            config.BLOCK2_TEMPLATE = prev
        self.assertIn("{2:I940DEMORCVGXXXXN}", msg)


class TestWrapLegacyProfile(unittest.TestCase):
    """Task 19 — perfil legado del banco accesible vía config.PROFILE."""

    def setUp(self):
        self.prev = getattr(config, "PROFILE", "fin")
        config.PROFILE = "legacy"

    def tearDown(self):
        config.PROFILE = self.prev

    def _wrap(self, lines=(":20:X",)):
        return wrap_message(list(lines), config, reference="X",
                            in_time="0309", in_date="260916",
                            out_date="260917", out_time="0707")

    def test_envoltura_legada_compuesta_desde_config(self):
        msg = self._wrap()
        header = (config.block0_wrap("260917", "0707")
                  + config.block1()
                  + config.block2("0309", "260916", "260917", "0707")
                  + config.block3("X"))
        self.assertTrue(msg.startswith(header + "{4:\r\n :20:X\r\n-}"))
        self.assertIn("{4:{177:2609170707}{451:0}}", msg)
        self.assertIn("{2:0940", msg)

    def test_sys_seq_legado_conservado(self):
        msg = self._wrap()
        self.assertIn("1234567890", msg)

    def test_tags_legados_con_1_espacio(self):
        msg = self._wrap([":20:X", "continuacion"])
        self.assertIn("\r\n :20:X\r\n", msg)
        self.assertIn("\r\ncontinuacion\r\n", msg)

    def test_bloque5_legado_condicional(self):
        prev = config.LEGACY_BLOCK5_ENABLED
        config.LEGACY_BLOCK5_ENABLED = False
        try:
            msg = self._wrap()
        finally:
            config.LEGACY_BLOCK5_ENABLED = prev
        self.assertTrue(msg.endswith("\r\n-}"))
        self.assertNotIn("{5:", msg)
        self.assertNotIn("{S:", msg)

    def test_bloque5_legado_presente_por_defecto(self):
        msg = self._wrap()
        self.assertTrue(msg.endswith(
            "{5:{CHK:A1B2C3D4E5F6}{DLM:}}{S:{COP:P}}"))


class TestJoinMessages(unittest.TestCase):

    def test_un_solo_dolar_entre_mensajes(self):
        def wrap(tag):
            return wrap_message([tag], config, reference=tag[1:],
                                in_time="0309", in_date="260916",
                                out_date="260917", out_time="0707")

        m1 = wrap(":20:A")
        m2 = wrap(":20:B")
        joined = join_messages([m1, m2])
        self.assertEqual(joined, m1 + "\r\n$" + m2 + "\r\n")
        self.assertNotIn("$" * 2, joined)

    def test_mensaje_individual_sin_dolar(self):
        self.assertEqual(join_messages([":20:A"]), ":20:A\r\n")

    def test_tres_mensajes_dos_dolares(self):
        joined = join_messages([":20:A", ":20:B", ":20:C"])
        self.assertEqual(joined.count("$"), 2)


class TestCampo61Spec65(unittest.TestCase):
    """SPEC §6.5: owner/bank refs 16x, `//` siempre, suplementaria 34x."""

    def test_owner_ref_desde_instr_id_padeado_a_16(self):
        e = dreplace(_fake_entry(), tx_details=(
            TxDetails(instr_id="INSTR-0001", addtl_tx_inf="TRANSFERENCIA UNO"),))
        self.assertEqual(
            build_field_61(e, config, make_log(), FILENAME),
            ":61:2608310831C38356,13NMSCINSTR-0001      //NONE            ")

    def test_owner_ref_prefiere_end_to_end_id(self):
        e = dreplace(_fake_entry(), tx_details=(
            TxDetails(instr_id="INSTR-0001", end_to_end_id="E2E-42"),))
        line = build_field_61(e, config, make_log(), FILENAME)
        self.assertEqual(line.split("//")[0].split("NMSC")[1],
                         "E2E-42" + " " * 10)

    def test_nunca_usa_ntry_ref_como_owner_ref(self):
        e = dreplace(_fake_entry(), tx_details=(), ntry_ref="260831000000012-1")
        line = build_field_61(e, config, make_log(), FILENAME)
        self.assertNotIn("260831000000012", line)
        self.assertEqual(line.split("//")[0].split("NMSC")[1],
                         "NONE" + " " * 12)

    def test_bank_ref_tras_doble_slash_padeada_a_16(self):
        e = dreplace(_fake_entry(), acct_svcr_ref="SES000000001")
        self.assertTrue(build_field_61(e, config, make_log(), FILENAME)
                        .endswith("//SES000000001    "))

    def test_sin_bank_ref_emite_none_literal(self):
        e = dreplace(_fake_entry(), acct_svcr_ref="NONE")
        self.assertTrue(build_field_61(e, config, make_log(), FILENAME)
                        .endswith("//NONE" + " " * 12))

    def test_anchos_exactos_16_y_16(self):
        line = build_field_61(_fake_entry(), config, make_log(), FILENAME)
        owner_bank = line.split("NMSC", 1)[1]
        self.assertEqual(len(owner_bank.split("//")[0]), 16)
        self.assertEqual(len(owner_bank.split("//")[1]), 16)

    def test_suplementaria_desde_addtl_tx_inf_padeada_a_34(self):
        e = _fake_entry()
        linea, resto = build_supplementary_line(e, config, make_log(), FILENAME)
        self.assertEqual(linea, "TRANSFERENCIA UNO" + " " * 17)
        self.assertEqual(resto, "")

    def test_sin_addtl_tx_inf_no_hay_suplementaria(self):
        e = dreplace(_fake_entry(), tx_details=())
        linea, resto = build_supplementary_line(e, config, make_log(), FILENAME)
        self.assertIsNone(linea)
        self.assertEqual(resto, "")

    def test_suplementaria_larga_se_corta_en_token_y_resto_se_conserva(self):
        largo = "UNO DOS TRES CUATRO CINCO SEIS SIETE OCHO NUEVE DIEZ"
        e = dreplace(_fake_entry(), tx_details=(
            TxDetails(instr_id="INSTR-0001", addtl_tx_inf=largo),))
        linea, resto = build_supplementary_line(e, config, make_log(), FILENAME)
        self.assertEqual(len(linea), config.SUPP_LINE_WIDTH)
        self.assertTrue(resto)
        self.assertEqual(linea.rstrip() + " " + resto, largo)

    def test_validate_field_61_exige_padding_cuando_corresponde(self):
        for sin_pad in (
            ":61:2608310831C38356,13NMSCNONE//NONE",
            ":61:2608310831C38356,13NMSCNONE            ",
        ):
            with self.subTest(valor=sin_pad):
                with self.assertRaises(Mt940BuildError):
                    validate_field_61(sin_pad)

    def test_validate_field_61_admite_modo_sin_padding(self):
        valor = ":61:2608310831C38356,13NMSCREF-000001"
        self.assertEqual(validate_field_61(valor, padded=False), valor)

    def test_validate_field_61_rechaza_salto_de_linea(self):
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C38356,13NMSCNONE            "
                              "//NONE            \r\n")

    def test_rechaza_tipo_sin_prefijo_snf(self):
        """SWIFT :61: subcampo 6 = 1!a3!c con prefijo S/N/F (doc SWIFT)."""
        with self.assertRaises(Mt940BuildError):
            validate_field_61(":61:2608310831C38356,13CMSC"
                              + "NONE".ljust(16) + "//" + "NONE".ljust(16))

    def test_acepta_owner_ref_con_slash_simple(self):
        """SWIFT :61: owner ref es 16x: admite '/' suelto (no '//')."""
        valor = (":61:2608310831C38356,13NMSC"
                 + "TOP/SWEEPSVERIGE" + "//" + "NONE".ljust(16))
        self.assertEqual(validate_field_61(valor), valor)


def _fake_entry() -> Entry:
    """Entrada sintética típica: CRDT NMSC, con remesa estructurada."""
    return Entry(
        amount=Decimal("38356.13"),
        amount_ccy="MXN",
        cdt_dbt_ind="CRDT",
        sts="BOOK",
        bookg_dt="2026-08-31",
        val_dt="2026-08-31",
        rvsl_ind=False,
        ntry_ref="REF-000001",
        acct_svcr_ref="NONE",
        tx_code="NMSC",
        tx_issr="DEMO",
        tx_details=(TxDetails(instr_id="INSTR-0001",
                              addtl_tx_inf="TRANSFERENCIA UNO"),),
        addtl_ntry_inf="",
    )


if __name__ == "__main__":
    unittest.main()