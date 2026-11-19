# -*- coding: utf-8 -*-
"""Aceptación y cierre (Task 9 / Tasks 18-22): criterios SPEC §9/§10.

Con el perfil FIN validable (default): fixture real en UN archivo sin `_2`,
gramática `:61:` sin narrativa pegada, `:86:` ≤6×65, paging `_2`/`_3` con
continuidad de saldo y `:28C:` secuencial, pérdidas logueadas con texto,
idempotencia y goldens dual (perfil nuevo + referencia legada).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import _pathfix  # noqa: F401
from _paging_helpers import legacy_single_message

from Library import config
from Library.camt053 import parse_document
from Library.mt940_builder import (build_statement_lines, join_messages,
                                   validate_field_61, validate_field_86,
                                   wrap_message)
from Library.mt940_splitter import split_statement_lines
from Library.runlog import RunLog
import camt_to_mt940

from test_integration import _large_camt_xml

FIXTURES = Path(__file__).parent / "fixtures"
RUN = datetime(2026, 9, 18, 10, 30, 15)
OUT_DATE = "31082026"        # test_camt053.xml: última transacción 2026-08-31
OUT_DATE_SINT = "15092026"   # fixtures sintéticos (_camt_xml/_large/multi_stmt)


def _camt_xml(narrative: str) -> str:
    """CAMT.053 mínimo de 1 Ntry CRDT 500.00 MXN con la narrativa dada."""
    ns = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<BkToCstmrStmt xmlns='{ns}'>"
        "<GrpHdr><MsgId>ACC-0000001</MsgId>"
        "<CreDtTm>2026-09-15T10:00:00</CreDtTm></GrpHdr>"
        "<Stmt>"
        "<Id>STM-ACENTOS</Id><ElctrncSeqNb>00100</ElctrncSeqNb>"
        "<LglSeqNb>00001</LglSeqNb>"
        "<Acct><Id><Othr><Id>MX18BAN000001100000000001</Id></Othr></Id>"
        "<Ccy>MXN</Ccy></Acct>"
        "<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
        "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-15</Dt></Dt></Bal>"
        "<Ntry>"
        "<Amt Ccy='MXN'>500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Sts><Cd>BOOK</Cd></Sts>"
        "<BookgDt><Dt>2026-09-15</Dt></BookgDt>"
        "<ValDt><Dt>2026-09-15</Dt></ValDt>"
        f"<NtryRef>REF-1</NtryRef><AcctSvcrRef>NONE</AcctSvcrRef>"
        "<BkTxCd><Domn><Cd>NMSC</Cd></Domn></BkTxCd>"
        f"<AddtlNtryInf>{narrative}</AddtlNtryInf>"
        "</Ntry>"
        "</Stmt></BkToCstmrStmt>"
    )


class TestAceptacionAcentos(unittest.TestCase):
    def setUp(self) -> None:
        legacy_single_message(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entrada = Path(tmp.name) / "Entrada"
        self.salida = Path(tmp.name) / "Salida"
        self.entrada.mkdir()

    def convert(self, filename: str, data: str) -> str:
        (self.entrada / filename).write_text(data, encoding="utf-8")
        camt_to_mt940.run_batch(self.entrada, self.salida,
                                config=config, run_at=RUN)
        out = self.salida / f"{Path(filename).stem}_{OUT_DATE_SINT}.txt"
        self.assertTrue(out.exists())
        log_text = self.salida.glob("log_*.txt").__next__().read_text(
            encoding="utf-8", newline="")
        return out.read_text(encoding="utf-8", newline=""), log_text

    def test_fold_de_acentos_silencioso(self) -> None:
        text, log_text = self.convert(
            "acentos.xml",
            _camt_xml("Pago a Société Générale por transferencia"))
        self.assertIn("Societe Generale", text)
        self.assertNotIn("é", text.replace("É", ""))
        self.assertNotIn("WARN", log_text)

    def test_caracter_fuera_del_charset_genera_warn(self) -> None:
        text, log_text = self.convert(
            "charla.xml", _camt_xml("Pago de 500 euros con símbolo €"))
        self.assertNotIn("€", text)
        self.assertIn("WARN", log_text)
        self.assertIn("€", log_text)

    def test_multi_stmt_un_solo_archivo_con_dolar(self) -> None:
        shutil.copy(FIXTURES / "multi_stmt.xml", self.entrada / "multi_stmt.xml")
        code = camt_to_mt940.run_batch(self.entrada, self.salida,
                                       config=config, run_at=RUN)
        self.assertEqual(code, 0)

        out = self.salida / f"multi_stmt_{OUT_DATE_SINT}.txt"
        text = out.read_text(encoding="utf-8", newline="")
        self.assertEqual(text.count("$"), 1)
        self.assertFalse(text.endswith("$"))
        self.assertEqual(text.count("{1:F01"), 2)
        self.assertEqual(text.count("\r\n$"), 1)
        self.assertTrue(text.endswith("-}\r\n"))
        self.assertFalse((self.salida / f"multi_stmt_{OUT_DATE_SINT}_2.txt").exists())
        self.assertTrue((self.entrada / "Procesados" / "multi_stmt.xml").exists())


def _split_messages(text: str) -> list[str]:
    """Mecanismo A (SPEC §6.3-C): separa mensajes unidos por `$`.

    Soporta el layout nuevo (`-}` EOL `$` `{1:`) y el legado (`-}${1:`).
    """
    text = text.rstrip("\r\n")
    return [part.rstrip("\r\n") for part in text.split(config.MSG_SEPARATOR)]


def _tag_value(body: str, prefix: str) -> str:
    """Valor del tag (sin el prefijo ni los espacios iniciales del bloque 4)."""
    for line in body.split("\r\n"):
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):]
    raise AssertionError(f"tag {prefix} no encontrado")


class TestGoldenPerfilFin(unittest.TestCase):
    def setUp(self) -> None:
        legacy_single_message(self)

    """Task 21 — golden del perfil FIN validable (SPEC §10/§11).

    `golden_mt940_profile.txt` es el mensaje del fixture REAL en el perfil
    nuevo ({1:F01…}{2:I940…}{4:, columna 0, CRLF, bloques 3/5 OFF), generado
    por el codigo y revisado por el humano (Checkpoint G). El bloque 2 del
    perfil FIN no lleva fecha/hora, por lo que la regeneracion es
    byte-a-byte reproducible.
    """

    GOLDEN = FIXTURES / "golden_mt940_profile.txt"

    def _regenerado(self) -> str:
        doc = parse_document(
            (FIXTURES / "test_camt053.xml").read_text(encoding="utf-8"))
        log = RunLog(now=lambda: RUN)
        stmt = doc.statements[0]
        lines = build_statement_lines(stmt, doc.msg_id, config, log,
                                      "test_camt053.xml")
        chunks = split_statement_lines(lines, stmt, log, "test_camt053.xml")
        messages = [
            wrap_message(chunk.lines, config,
                         reference=lines[0][len(":20:"):],
                         in_time="0309", in_date="260916",
                         out_date="260917", out_time="0707")
            for chunk in chunks
        ]
        return join_messages(messages)

    def test_golden_existe_y_es_reproducible(self) -> None:
        self.assertTrue(self.GOLDEN.is_file(),
                        "falta golden_mt940_profile.txt (Task 21)")
        text = self.GOLDEN.read_text(encoding="utf-8", newline="")
        self.assertEqual(text, self._regenerado(),
                         "el codigo ya no reproduce el golden aprobado")

    def test_perfil_fin_del_golden(self) -> None:
        """Cumplimiento §10: envoltura F01/I940, col 0, ≤65, sin 3/5 ni $."""
        text = self.GOLDEN.read_text(encoding="utf-8", newline="")
        self.assertTrue(text.startswith(
            "{1:F01DEMOBKMMAXXX0000000000}"
            "{2:I940DEMORCVGXXXXN}{4:\r\n"))
        body = text.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]
        lineas = body.split("\r\n")
        self.assertEqual(len([l for l in lineas if l.startswith(":61:")]), 34)
        for line in lineas:
            self.assertFalse(line.startswith(" "), repr(line))
            self.assertLessEqual(len(line), 65, repr(line))
        self.assertTrue(text.endswith("-}\r\n"))
        for ausente in ("{5:", "{S:", "{3:", "{177:", "F21", "$"):
            self.assertNotIn(ausente, text)


class TestMecanismoARefReal(unittest.TestCase):
    """Mecanismo A contra la REFERENCIA LEGADA del banco (Task 21).

    `golden_mt940_reference.txt` es copia CRLF-normalizada de
    Salida/mt940_202609170910001.txt (3 Stmt reales unidos con `$`) y vale
    SOLO como patron legado del mecanismo A (SPEC §6.3/§7): segmentos
    `{4:...-}{5:...}` unidos por N−1 `$` sin `$` final, y `:28C:` de cada
    Stmt intacto (el separador NO renumera: 00178/00001, 02409/00001,
    00179/00001). No es el perfil validable del gateway — ese es
    golden_mt940_profile.txt.
    """

    GOLDEN = FIXTURES / "golden_mt940_reference.txt"

    def setUp(self) -> None:
        legacy_single_message(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entrada = Path(tmp.name) / "Entrada"
        self.salida = Path(tmp.name) / "Salida"
        self.entrada.mkdir()

    def convert(self, fixture: str) -> str:
        shutil.copy(FIXTURES / fixture, self.entrada / fixture)
        code = camt_to_mt940.run_batch(self.entrada, self.salida,
                                       config=config, run_at=RUN)
        self.assertEqual(code, 0)
        out = self.salida / f"{Path(fixture).stem}_{OUT_DATE_SINT}.txt"
        self.assertTrue(out.exists())
        return out.read_text(encoding="utf-8", newline="")

    def _assert_esqueleto(self, msg: str) -> None:
        """Headers SENDER_LT/RECEIVER_LT y cierre de bloque 5 en cada segmento."""
        header21 = "{1:F21" + config.SENDER_LT
        header01 = "{1:F01" + config.SENDER_LT
        self.assertTrue(msg.startswith(header21), msg[:40])
        self.assertIn(header01, msg)
        self.assertIn(config.RECEIVER_LT, msg)
        self.assertIn("{4:{177:", msg)
        self.assertIn("{3:{108:", msg)
        self.assertIn("-}{5:{CHK:", msg)
        self.assertTrue(msg.endswith("{S:{COP:P}}"), msg[-20:])

    def _leer_referencia(self) -> str:
        """Lee la referencia legada sin el encabezado de comentario `#`."""
        raw = self.GOLDEN.read_text(encoding="utf-8", newline="")
        lineas = raw.splitlines(keepends=True)
        while lineas and lineas[0].startswith("#"):
            lineas.pop(0)
        return "".join(lineas)

    def test_referencia_declarada_legado(self) -> None:
        """Task 21: la referencia del banco queda documentada como LEGADO."""
        self.assertTrue(self.GOLDEN.exists())
        raw = self.GOLDEN.read_text(encoding="utf-8", newline="")
        self.assertTrue(raw.startswith("#"),
                        "falta el encabezado de comentario de legado")
        self.assertIn("legado", raw.split("\n", 1)[0].lower())

    def test_referencia_golden_3_segmentos_sin_dolar_final(self) -> None:
        self.assertTrue(self.GOLDEN.exists(),
                        "falta la copia de la referencia real (mecanismo A)")
        text = self._leer_referencia()
        messages = _split_messages(text)
        self.assertEqual(len(messages), 3)
        self.assertEqual(text.count("$"), 2)
        self.assertFalse(text.endswith("$"))
        for msg in messages:
            self._assert_esqueleto(msg)
        secs = [_tag_value(msg, ":28C:") for msg in messages]
        self.assertEqual(secs, ["00178/00001", "02409/00001", "00179/00001"])

    def test_multi_stmt_replica_esqueleto_de_la_referencia(self) -> None:
        """Compara contra la referencia legada: corre en PROFILE="legacy"."""
        prev = getattr(config, "PROFILE", "fin")
        config.PROFILE = "legacy"
        try:
            text = self.convert("multi_stmt.xml")
        finally:
            config.PROFILE = prev
        self.assertEqual(text.count("$"), 1)
        self.assertFalse(text.endswith("$"))
        messages = _split_messages(text)
        self.assertEqual(len(messages), 2)
        for msg in messages:
            self._assert_esqueleto(msg)
            self.assertTrue(msg.startswith(
                "{1:F21" + config.SENDER_LT + config.LEGACY_SYS_SEQ),
                "mismo remitente entre `$`")
            self.assertIn("{4:{177:" + RUN.strftime('%y%m%d%H%M') + "}", msg)
            self.assertRegex(msg, r"\r\n :28C:00\d\d\d/00\d\d\d")

    def test_28c_preservado_por_dolar_sin_renumeracion(self) -> None:
        text = self.convert("multi_stmt.xml")
        messages = _split_messages(text)
        self.assertEqual([_tag_value(m, ":28C:") for m in messages],
                         ["00001/00001", "00001/00001"],
                         "cada Stmt conserva su :28C: base entre `$`")
        self.assertNotIn("/00002", text,
                         "el separador $ no renumera el segundo componente")


def _validar_bloque4(texto: str) -> tuple[int, int]:
    """Valida gramaticalmente todas las `:61:` y cada grupo `:86:` del
    bloque 4 de un mensaje. Devuelve (n_61, n_86)."""
    body = texto.split("{4:\r\n", 1)[1].split("\r\n-}", 1)[0]
    lineas = body.split("\r\n")
    for linea in lineas:
        if linea.startswith(":"):
            assert not linea.startswith(" "), f"tag indentado: {linea!r}"
        assert len(linea) <= 65, f"línea >65: {linea!r}"
    n61 = n86 = 0
    i = 0
    while i < len(lineas):
        if lineas[i].startswith(":61:"):
            validate_field_61(lineas[i])
            n61 += 1
        elif lineas[i].startswith(":86:"):
            grupo = [lineas[i]]
            i += 1
            while i < len(lineas) and not lineas[i].startswith(":"):
                grupo.append(lineas[i])
                i += 1
            validate_field_86(grupo)
            n86 += 1
            continue
        i += 1
    return n61, n86


class TestCierreSpec910(unittest.TestCase):
    """Task 22 — checklist §9/§10 re-verificado end-to-end con el perfil nuevo."""

    def setUp(self) -> None:
        legacy_single_message(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entrada = Path(tmp.name) / "Entrada"
        self.salida = Path(tmp.name) / "Salida"
        self.entrada.mkdir()

    def run_batch(self) -> int:
        return camt_to_mt940.run_batch(self.entrada, self.salida,
                                       config=config, run_at=RUN)

    def leer(self, name: str) -> str:
        return (self.salida / name).read_text(encoding="utf-8", newline="")

    def test_criterios_1_a_3_y_7_fixture_real(self) -> None:
        """§10.1-3 + §10.7: un archivo sin `_2`, perfil validable, saldos
        cuadrados y original movido tras el éxito."""
        shutil.copy(FIXTURES / "test_camt053.xml",
                    self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)
        self.assertFalse(
            (self.salida / f"test_camt053_{OUT_DATE}_2.txt").exists())
        text = self.leer(f"test_camt053_{OUT_DATE}.txt")
        self.assertTrue(text.startswith(
            "{1:F01DEMOBKMMAXXX0000000000}"
            "{2:I940DEMORCVGXXXXN}{4:\r\n"))
        self.assertTrue(text.endswith("-}\r\n"))
        for ausente in ("{5:", "{3:", "{S:", "F21", "$"):
            self.assertNotIn(ausente, text)
        n61, n86 = _validar_bloque4(text)
        self.assertEqual((n61, n86), (34, 34))
        self.assertIn(":60F:C260831MXN14955145,69", text)
        self.assertIn(":62F:C260831MXN261430649,29", text)
        self.assertFalse((self.entrada / "test_camt053.xml").exists())
        self.assertTrue(
            (self.entrada / "Procesados" / "test_camt053.xml").exists())

    def test_criterio_6_paging_por_tamano_perfil_nuevo(self) -> None:
        """§10.6: >9800 → varios archivos con `:60M:`/`:62M:` continuos,
        `:62F:` solo al final, `:28C:` secuencial y gramática válida en
        TODAS las salidas (regresión §11 de narrativa pegada)."""
        (self.entrada / "grande.xml").write_text(_large_camt_xml(),
                                                 encoding="utf-8")
        self.assertEqual(self.run_batch(), 0)
        files = sorted(self.salida.glob(f"grande_{OUT_DATE_SINT}*.txt"))
        self.assertGreaterEqual(len(files), 2)
        textos = [self.leer(f.name) for f in files]
        for ordinal, text in enumerate(textos, start=1):
            self.assertTrue(text.startswith(
                "{1:F01DEMOBKMMAXXX0000000000}{2:I940"))
            self.assertTrue(text.endswith("-}\r\n"))
            self.assertIn(f":28C:00178/{ordinal:05d}", text)
            self.assertNotEqual(_validar_bloque4(text), (0, 0))
        for text in textos[:-1]:
            self.assertIn(":62M:", text)
            self.assertNotIn(":62F:", text)
        self.assertNotIn(":60M:", textos[0])
        self.assertIn(":60M:", textos[1])
        self.assertIn(":62F:C260915MXN13000,00", textos[-1])
        # `:60M:`(k) == `:62M:`(k-1) en cada frontera.
        for anterior, siguiente in zip(textos, textos[1:]):
            fin = next(l for l in anterior.split("\r\n", 1)[1].split("\r\n")
                       if l.startswith(":62M:"))
            ini = next(l for l in siguiente.split("\r\n", 1)[1].split("\r\n")
                       if l.startswith(":60M:"))
            self.assertEqual(fin.replace(":62M:", ""), ini.replace(":60M:", ""))

    def test_criterio_perdidas_logueadas_con_texto(self) -> None:
        """§6.5: toda pérdida se registra con el texto perdido."""
        (self.entrada / "charla.xml").write_text(
            _camt_xml("Pago de 500 euros con símbolo €"), encoding="utf-8")
        self.assertEqual(self.run_batch(), 0)
        log_text = next(self.salida.glob("log_*.txt")).read_text(
            encoding="utf-8", newline="")
        self.assertIn("charla.xml", log_text)
        self.assertIn("WARN", log_text)
        self.assertIn("€", log_text)

    def test_reejecucion_idempotente_con_perfil_nuevo(self) -> None:
        """§10: los originales ya movidos no se reprocesan."""
        shutil.copy(FIXTURES / "test_camt053.xml",
                    self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)
        n_salida = len(list(self.salida.glob("*.txt")))
        contenido = self.leer(f"test_camt053_{OUT_DATE}.txt")
        self.assertEqual(self.run_batch(), 0)
        self.assertEqual(len(list(self.salida.glob("*.txt"))), n_salida)
        self.assertEqual(self.leer(f"test_camt053_{OUT_DATE}.txt"), contenido)

    def test_golden_perfil_coincide_con_corrida_real(self) -> None:
        """El golden aprobado (Task 21) es exactamente lo que produce el
        pipeline completo del lote para el fixture real."""
        shutil.copy(FIXTURES / "test_camt053.xml",
                    self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)
        golden = (FIXTURES / "golden_mt940_profile.txt").read_text(
            encoding="utf-8", newline="")
        # El lote mete fechas/hora del RUN en el nombre; el mensaje FIN no
        # lleva fecha/hora, así que el contenido es idéntico al golden.
        self.assertEqual(self.leer(f"test_camt053_{OUT_DATE}.txt"), golden)


if __name__ == "__main__":
    unittest.main()