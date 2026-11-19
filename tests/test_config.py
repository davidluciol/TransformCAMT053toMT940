# -*- coding: utf-8 -*-
"""Task 18 — config.py: templates SPEC §6.2, perfil FIN + legado, build_block2.

Cubre los defaults del perfil FIN validable por el gateway (SPEC §6.2:
BLOCKn_ENABLED/BLOCKn_TEMPLATE con bloques 3/5 OFF, RECEIVER_ADDRESS dinámico),
la resolución de templates y la validación de build_block2 (Input-header
`{2:I…}` + RECEIVER_ADDRESS de 12 chars con 'X' en índice 9), conservando la
byte-identidad del perfil legado con la línea 1 del ejemplo real del banco
(Salida/mt940_202609170910001.txt).
"""

import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import _pathfix  # noqa: F401

from Library import config
from Library.config import (Mt940BuildError, build_block1, build_block2,
                            resolve_header_values, resolve_template)
from Library.runlog import RunLog

FIXTURES = Path(__file__).parent / "fixtures"

REAL_LINE1 = (
    "{1:F21DEMOBKMMAXXX1234567890}"
    "{4:{177:2609170901}{451:0}}"
    "{1:F01DEMOBKMMAXXX1234567890}"
    "{2:0940"
    "0309"            # IN_TIME
    "260916"          # IN_DATE
    "DEMOLGCYQXXX"    # RECEIVER_LT
    "0123456789"      # SESSION_ISN
    "260917"          # OUT_DATE
    "0707"            # OUT_TIME
    "01"              # sufijo fijo del banco
    "N"               # PRIORITY
    "}"
    "{3:{108:DDA00000000001}}"
    "{4:"
)

FIN_BLOCK2_DEFAULT = "{2:I940DEMORCVGXXXXN}"
FIN_BLOCK2_CHASE = "{2:I940DEMOLGCYXXXXN}"


class TestConfig(unittest.TestCase):

    def test_constantes_de_identificacion(self):
        self.assertEqual(config.SENDER_LT, "DEMOBKMMAXXX")
        self.assertEqual(config.RECEIVER_LT, "DEMOLGCYQXXX")
        self.assertEqual(config.LEGACY_SYS_SEQ, "1234567890")
        self.assertEqual(config.SESSION_ISN, "0123456789")
        self.assertEqual(config.PRIORITY, "N")

    def test_limites_y_opciones_de_ensamblado(self):
        self.assertEqual(config.MAX_BLOCK4_CHARS, 9800)
        self.assertEqual(config.SPLIT_RESERVE_CHARS, 120)
        self.assertEqual(config.FIELD_86_FIRST_WIDTH, 61)
        self.assertEqual(config.FIELD_86_NEXT_WIDTH, 65)
        self.assertEqual(config.FIELD_86_MAX_LINES, 6)
        self.assertEqual(config.SUPP_LINE_WIDTH, 34)
        self.assertFalse(config.COLLAPSE_SPACES)
        self.assertTrue(config.PAD_61_REFS)
        self.assertEqual(config.MSG_SEPARATOR, "$")
        self.assertEqual(config.EOL, "\r\n")
        self.assertTrue(config.FILE_FINAL_EOL)
        self.assertEqual(config.PROCESSED_DIRNAME, "Procesados")
        self.assertEqual(config.CHK_PLACEHOLDER, "A1B2C3D4E5F6")
        self.assertEqual(config.BLOCK4_OPEN, "{4:\n")
        self.assertEqual(config.BLOCK4_TAG, ":{tag}:{value}")
        self.assertEqual(config.BLOCK4_CLOSE, "-}")

    def test_constantes_perfil_fin_default(self):
        """Defaults SPEC §6.2 del perfil FIN validable por el gateway."""
        self.assertEqual(config.RECEIVER_ADDRESS, "DEMORCVGXXXX")
        self.assertEqual(config.MSG_TYPE, "940")
        self.assertEqual(config.MONITORING, "")
        self.assertEqual(config.OBSOLESCENCE, "")
        self.assertEqual(config.SYS_SEQ, "0000000000")
        self.assertTrue(config.BLOCK1_ENABLED)
        self.assertEqual(config.BLOCK1_TEMPLATE,
                         "{1:F01{SENDER_LT}{SYS_SEQ}}")
        self.assertTrue(config.BLOCK2_ENABLED)
        self.assertEqual(
            config.BLOCK2_TEMPLATE,
            "{2:I{MSG_TYPE}{RECEIVER_ADDRESS}{PRIORITY}"
            "{MONITORING}{OBSOLESCENCE}}")
        self.assertFalse(config.BLOCK3_ENABLED)
        self.assertEqual(config.BLOCK3_TEMPLATE, "{3:{108:{REFERENCE}}}")
        self.assertFalse(config.BLOCK5_ENABLED)
        self.assertEqual(config.BLOCK5_TEMPLATE,
                         "{5:{CHK:{CHK}}{DLM:}}{S:{COP:P}}")

    def test_perfil_legado_conservado(self):
        """El perfil legado del banco queda como configuración (SPEC §11)."""
        self.assertTrue(config.LEGACY_BLOCK5_ENABLED)
        self.assertEqual(
            config.LEGACY_BLOCK0_TEMPLATE,
            "{1:F21{SENDER_LT}{SYS_SEQ}}"
            "{4:{177:{OUT_DATE}{OUT_TIME}}{451:0}}")
        self.assertEqual(
            config.LEGACY_BLOCK2_TEMPLATE,
            "{2:0940{IN_TIME}{IN_DATE}{RECEIVER_LT}{SESSION_ISN}"
            "{OUT_DATE}{OUT_TIME}01{PRIORITY}}")
        self.assertEqual(config.block1(),
                         "{1:F01DEMOBKMMAXXX1234567890}")

    def test_cabeceras_byte_identicas_al_ejemplo_real(self):
        """Ensambla bloques 1/2/3 (+ wrapper) del perfil legado y los compara
        con la línea real del banco (sin el `{4:` final, que cierra
        BLOCK4_OPEN)."""
        assembled = (
            config.block0_wrap("260917", "0901")
            + config.block1()
            + config.block2(in_time="0309", in_date="260916",
                            out_date="260917", out_time="0707")
            + config.block3("DDA00000000001")
        )
        self.assertEqual(assembled, REAL_LINE1.removesuffix("{4:"))

    def test_block3_formato(self):
        self.assertEqual(config.block3("ABC123"), "{3:{108:ABC123}}")

    def test_block5_template_habilitado(self):
        self.assertEqual(
            config.block5(config.CHK_PLACEHOLDER),
            "{5:{CHK:A1B2C3D4E5F6}{DLM:}}{S:{COP:P}}",
        )

    def test_fixtures_creados(self):
        for name in ("test_camt053.xml", "test_camt053.txt",
                     "non_camt.txt", "multi_stmt.xml"):
            self.assertTrue((FIXTURES / name).is_file(), msg=name)
        self.assertEqual((FIXTURES / "test_camt053.xml").stat().st_size,
                         (FIXTURES / "test_camt053.txt").stat().st_size)


class TestResolveTemplate(unittest.TestCase):

    def test_resuelve_placeholder_y_deja_llaves_literales(self):
        self.assertEqual(
            resolve_template("{3:{108:{REFERENCE}}}", REFERENCE="ABC123"),
            "{3:{108:ABC123}}",
        )

    def test_placeholder_sin_variable_queda_intacto(self):
        self.assertEqual(resolve_template("{2:I{MSG_TYPE}}"),
                         "{2:I{MSG_TYPE}}")

    def test_legacy_block2_reexpresado_sobre_template(self):
        """El helper legado produce exactamente lo que resuelve su template."""
        resolved = resolve_template(
            config.LEGACY_BLOCK2_TEMPLATE,
            IN_TIME="0309", IN_DATE="260916",
            RECEIVER_LT=config.RECEIVER_LT,
            SESSION_ISN=config.SESSION_ISN,
            OUT_DATE="260917", OUT_TIME="0707", PRIORITY=config.PRIORITY)
        self.assertEqual(
            resolved,
            config.block2(in_time="0309", in_date="260916",
                          out_date="260917", out_time="0707"))

    def test_legacy_block5_reexpresado_sobre_template(self):
        self.assertEqual(
            resolve_template(config.BLOCK5_TEMPLATE, CHK=config.CHK_PLACEHOLDER),
            config.block5(),
        )


class TestResolveHeaderValues(unittest.TestCase):
    """SPEC §6.2: HEADER_SOURCE='apphdr' deriva los LT del Envelope."""

    @staticmethod
    def _log() -> RunLog:
        return RunLog(now=lambda: datetime(2026, 9, 18, 10, 30, 15))

    def test_config_es_el_default(self):
        self.assertEqual(config.HEADER_SOURCE, "config")
        self.assertEqual(resolve_header_values("DEMOBKMMXXX", "DEMORCVGXXX"),
                         (config.SENDER_LT, config.RECEIVER_ADDRESS))

    def test_apphdr_deriva_los_lt_del_envelope(self):
        with mock.patch.object(config, "HEADER_SOURCE", "apphdr"):
            log = self._log()
            sender, receiver = resolve_header_values(
                "DEMOBKMMXXX", "DEMORCVGXXX", log, "x.xml")
        self.assertEqual(sender, "DEMOBKMMAXXX")
        self.assertEqual(receiver, "DEMORCVGXXXX")
        self.assertEqual([e for e in log.events if e.level == "INFO"], [])

    def test_apphdr_avisa_si_no_coincide_con_config(self):
        with mock.patch.object(config, "HEADER_SOURCE", "apphdr"):
            log = self._log()
            sender, receiver = resolve_header_values(
                "DEUTDEFFXXX", "COBADEFFXXX", log, "x.xml")
        self.assertEqual(sender, "DEUTDEFFAXXX")
        self.assertEqual(receiver, "COBADEFFXXXX")
        self.assertEqual(len([e for e in log.events if e.level == "INFO"]), 2)

    def test_apphdr_sin_envelope_cae_a_config(self):
        with mock.patch.object(config, "HEADER_SOURCE", "apphdr"):
            log = self._log()
            self.assertEqual(resolve_header_values("", "", log, "x.xml"),
                             (config.SENDER_LT, config.RECEIVER_ADDRESS))
        self.assertEqual([e for e in log.events if e.level == "INFO"], [])


class TestBuildBlock1(unittest.TestCase):
    """SPEC §6.2: el bloque 1 se construye y se valida antes de serializar."""

    def test_bloque1_default_del_perfil_fin(self):
        self.assertEqual(build_block1(), "{1:F01DEMOBKMMAXXX0000000000}")

    def test_cumple_el_regex_de_referencia(self):
        import re
        self.assertRegex(build_block1(),
                         r"^\{1:F01[A-Z0-9]{12}[0-9]{10}\}$")

    def test_rechaza_layout_y_anchos_invalidos(self):
        for malo in (
            "{2:I940DEMORCVGXXXXN}",              # no es un bloque 1
            "{1:F01DEMOBKMMAXXX000000000}",       # 9 dígitos
            "{1:F01DEMOBKMMAXXX00000000000}",     # 11 dígitos
            "{1:F01DEMOBKMMAXXX000000000A}",      # letra en la parte numérica
        ):
            with self.subTest(bloque=malo):
                with self.assertRaises(Mt940BuildError):
                    build_block1(template=malo)

    def test_rechaza_placeholder_sin_resolver(self):
        with self.assertRaises(Mt940BuildError):
            build_block1(template="{1:F01{SENDER_LT}{FALTA}}")

    def test_rechaza_sender_lt_invalido(self):
        with self.assertRaises(Mt940BuildError):
            build_block1(sender_lt="CORTO")


class TestBuildBlock2(unittest.TestCase):

    def test_bloque2_default_del_perfil_fin(self):
        self.assertEqual(build_block2(), FIN_BLOCK2_DEFAULT)

    def test_receiver_alternativo_valido(self):
        """Cambiar el BIC por config no requiere reescribir código."""
        self.assertEqual(build_block2(receiver_address="DEMOLGCYXXXX"),
                         FIN_BLOCK2_CHASE)

    def test_rechaza_receiver_de_longitud_invalida(self):
        with self.assertRaises(Mt940BuildError):
            build_block2(receiver_address="DEMOLGCY")

    def test_rechaza_lt_code_distinto_de_x(self):
        """SPEC §8: rechaza `DEMORCVGAXXX`/`DEMOLGCYQXXX`; acepta `XXXX`."""
        build_block2(receiver_address="DEMORCVGXXXX")
        for defectuoso in ("DEMORCVGAXXX", "DEMOLGCYQXXX", "DEMOLGCYQQQQ"):
            with self.subTest(receiver=defectuoso):
                with self.assertRaises(Mt940BuildError):
                    build_block2(receiver_address=defectuoso)

    def test_rechaza_layout_de_salida(self):
        """Un template de Output-header (`{2:O…}`) nunca se serializa."""
        output_template = ("{2:O{MSG_TYPE}{RECEIVER_ADDRESS}{PRIORITY}"
                           "{MONITORING}{OBSOLESCENCE}}")
        with self.assertRaises(Mt940BuildError):
            build_block2(template=output_template)

    def test_rechaza_placeholder_sin_resolver(self):
        incomplete = ("{2:I{MSG_TYPE}{DESCONOCIDO}{PRIORITY}"
                      "{MONITORING}{OBSOLESCENCE}}")
        with self.assertRaises(Mt940BuildError):
            build_block2(template=incomplete)


if __name__ == "__main__":
    unittest.main()
