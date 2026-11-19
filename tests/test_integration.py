# -*- coding: utf-8 -*-
"""Integración del lote: CLI -i/-o, detección por contenido, Procesados, log.

Usa directorios temporales; nunca toca Entrada/Salida reales del repo.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import _pathfix  # noqa: F401
from _paging_helpers import legacy_single_message

from Library import config
import camt_to_mt940

FIXTURES = Path(__file__).parent / "fixtures"
REAL_CAMT = FIXTURES / "test_camt053.xml"
RUN = datetime(2026, 9, 18, 10, 30, 15)
RUN_DATE = "18092026"          # fecha de corrida (nombre del log)
OUT_DATE = "31082026"          # test_camt053.xml: última transacción 2026-08-31
OUT_DATE_GRANDE = "15092026"   # _large_camt_xml: 2026-09-15


def _large_camt_xml(entries: int = 120) -> str:
    """CAMT.053 válido con N entradas largas (>9800 chars de bloque 4)."""
    ntry = "".join(
        "<Ntry>"
        "<Amt Ccy='MXN'>100.00</Amt>"
        "<CdtDbtInd>CRDT</CdtDbtInd>"
        "<Sts><Cd>BOOK</Cd></Sts>"
        "<BookgDt><Dt>2026-09-15</Dt></BookgDt>"
        "<ValDt><Dt>2026-09-15</Dt></ValDt>"
        "<NtryRef>REF-{:06d}</NtryRef>"
        "<AcctSvcrRef>NONE</AcctSvcrRef>"
        "<Tx><BkTxCd><Domn><Cd>NMSC</Cd></Domn></BkTxCd></Tx>"
        "<AddtlNtryInf>{}</AddtlNtryInf>"
        "</Ntry>".format(i, "EFAECF" * 30)
        for i in range(entries)
    )
    ns = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<BkToCstmrStmt xmlns='{ns}'>"
        "<GrpHdr><MsgId>LOTE-0000001</MsgId>"
        "<CreDtTm>2026-09-15T10:00:00</CreDtTm></GrpHdr>"
        "<Stmt>"
        "<Id>STM000007</Id><ElctrncSeqNb>1</ElctrncSeqNb><LglSeqNb>178</LglSeqNb>"
        "<Acct><Id><Othr><Id>MX18BAN000001100000000001</Id></Othr></Id>"
        "<Ccy>MXN</Ccy></Acct>"
        "<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>1000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-14</Dt></Dt></Bal>"
        "<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>"
        "<Amt Ccy='MXN'>13000.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>"
        "<Dt><Dt>2026-09-15</Dt></Dt></Bal>"
        f"{ntry}"
        "</Stmt></BkToCstmrStmt>"
    )


def _tag_value(body: str, prefix: str) -> str:
    """Devuelve el valor del tag (sin prefijo ni espacios iniciales)."""
    for line in body.split("\r\n"):
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):]
    raise AssertionError(f"tag {prefix} no encontrado")


class TestLote(unittest.TestCase):
    def setUp(self) -> None:
        legacy_single_message(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.entrada = Path(tmp.name) / "Entrada"
        self.salida = Path(tmp.name) / "Salida"
        self.entrada.mkdir()

    def run_batch(self, *, in_dir: Path | None = None) -> int:
        return camt_to_mt940.run_batch(
            in_dir or self.entrada, self.salida, config=config, run_at=RUN
        )

    def seed(self, filename: str, data: str | bytes) -> Path:
        target = self.entrada / filename
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8")
        return target

    @staticmethod
    def exact_read(path: Path) -> str:
        """Lee un archivo de salida sin traducción de finales de línea."""
        return path.read_text(encoding="utf-8", newline="")

    def test_real_camt_genera_mt940_5_bloques_y_mueve_original(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)

        out = self.salida / f"test_camt053_{OUT_DATE}.txt"
        self.assertTrue(out.exists())
        text = self.exact_read(out)
        self.assertTrue(text.startswith(
            "{1:F01DEMOBKMMAXXX0000000000}{2:I940DEMORCVGXXXXN}"))
        self.assertNotIn("{3:", text)
        self.assertEqual(text.count(":61:"), 34)
        self.assertTrue(text.endswith("-}\r\n"))
        self.assertNotIn("{5:", text)
        self.assertNotIn("$", text)
        self.assertFalse(text.endswith("-}\r\n\r\n"))
        self.assertFalse(
            (self.salida / f"test_camt053_{OUT_DATE}_2.txt").exists(),
            "el CAMT real (block4 ≈ 4.406 < 9.800) no debe particionarse",
        )

        original = self.entrada / "test_camt053.xml"
        self.assertFalse(original.exists())
        self.assertTrue((self.entrada / "Procesados" / "test_camt053.xml").exists())

    def test_camt_grande_particiona_en_varios_archivos_con_continuidad(self) -> None:
        self.seed("grande.xml", _large_camt_xml())
        self.assertEqual(self.run_batch(), 0)

        files = sorted(self.salida.glob(f"grande_{OUT_DATE_GRANDE}*.txt"))
        self.assertGreaterEqual(len(files), 2)
        textos = [self.exact_read(f) for f in files]

        self.assertIn(":62M:", textos[0])
        self.assertIn(":28C:00178/00001", textos[0])
        self.assertNotIn("$", textos[0])
        self.assertNotIn(":62F:", textos[0])
        for ordinal, text in enumerate(textos, start=1):
            self.assertIn(f":28C:00178/{ordinal:05d}", text)
        for i, (anterior, siguiente) in enumerate(zip(textos, textos[1:]), 2):
            self.assertIn(":60M:", siguiente)
            self.assertIn(f":28C:00178/{i:05d}", siguiente)
            fin = _tag_value(anterior.split("{4:\r\n", 1)[1]
                             .split("\r\n-}", 1)[0], ":62M:")
            ini = _tag_value(siguiente.split("{4:\r\n", 1)[1]
                             .split("\r\n-}", 1)[0], ":60M:")
            self.assertEqual(fin, ini)
        self.assertIn(":62F:C260915MXN13000,00", textos[-1])

    def test_no_camt_warn_omitido_y_no_se_mueve(self) -> None:
        self.seed("non_camt.txt", "esto no es xml ni camt")
        self.assertEqual(self.run_batch(), 0)

        self.assertTrue((self.entrada / "non_camt.txt").exists())
        self.assertFalse((self.entrada / "Procesados" / "non_camt.txt").exists())
        self.assertFalse(list(self.salida.glob("non_camt_*.txt")))
        log_text = self.salida.glob("log_*.txt").__next__().read_text(encoding="utf-8")
        self.assertIn("non_camt.txt", log_text)
        self.assertIn("WARN", log_text)
        self.assertNotIn("ERROR", log_text)

    def test_xml_no_camt_warn_no_se_mueve(self) -> None:
        self.seed("otro.xml", "<Documento><Otro/></Documento>")
        self.assertEqual(self.run_batch(), 0)
        self.assertTrue((self.entrada / "otro.xml").exists())
        self.assertFalse((self.entrada / "Procesados" / "otro.xml").exists())

    def test_camt_invalido_error_no_mueve_y_batch_continua(self) -> None:
        self.seed("roto.xml", "<BkToCstmrStmt><Stmt>")
        shutil.copy(REAL_CAMT, self.entrada / "bueno.xml")
        self.assertEqual(self.run_batch(), 1)

        self.assertTrue((self.entrada / "roto.xml").exists())
        self.assertFalse((self.entrada / "Procesados" / "roto.xml").exists())
        self.assertFalse(list(self.salida.glob("roto_*.txt")))
        self.assertTrue((self.salida / f"bueno_{OUT_DATE}.txt").exists())
        self.assertTrue((self.entrada / "Procesados" / "bueno.xml").exists())

        log_text = self.salida.glob("log_*.txt").__next__().read_text(encoding="utf-8")
        self.assertIn("roto.xml", log_text)
        self.assertIn("ERROR", log_text)

    def test_camt_sin_saldos_error_no_mueve(self) -> None:
        self.seed("sin_saldos.xml",
                  "<BkToCstmrStmt><Stmt><Id>X</Id></Stmt></BkToCstmrStmt>")
        self.assertEqual(self.run_batch(), 1)
        self.assertTrue((self.entrada / "sin_saldos.xml").exists())
        self.assertFalse((self.entrada / "Procesados" / "sin_saldos.xml").exists())
        log_text = self.salida.glob("log_*.txt").__next__().read_text(encoding="utf-8")
        self.assertIn("sin_saldos.xml", log_text)
        self.assertIn("ERROR", log_text)

    def test_o_inexistente_se_crea_y_log_se_escribe(self) -> None:
        self.assertFalse(self.salida.exists())
        self.seed("non_camt.txt", "hola")
        camt_to_mt940.run_batch(self.entrada, self.salida, config=config, run_at=RUN)
        self.assertTrue(self.salida.is_dir())
        logs = list(self.salida.glob(f"log_{RUN_DATE}_*.txt"))
        self.assertEqual(len(logs), 1)

    def test_colision_no_sobrescribe_y_agrega_contador(self) -> None:
        self.salida.mkdir()
        out = self.salida / f"test_camt053_{OUT_DATE}.txt"
        out.write_text("contenido anterior", encoding="utf-8")
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)

        # El previo se conserva; el nuevo va a `(1)`.
        self.assertEqual(out.read_text(encoding="utf-8"), "contenido anterior")
        nuevo = self.salida / f"test_camt053_{OUT_DATE}(1).txt"
        self.assertTrue(nuevo.exists())
        self.assertTrue(self.exact_read(nuevo).startswith(
            "{1:F01DEMOBKMMAXXX0000000000}{2:I940"))
        log_text = self.salida.glob("log_*.txt").__next__().read_text(encoding="utf-8")
        self.assertIn("se guarda como", log_text)
        self.assertIn("WARN", log_text)

    def test_reejecucion_idempotente_no_reprocesa_movidos(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)
        n_salida = len(list(self.salida.glob("*.txt")))

        self.assertEqual(self.run_batch(), 0)
        self.assertEqual(len(list(self.salida.glob("*.txt"))), n_salida)
        self.assertTrue((self.entrada / "Procesados" / "test_camt053.xml").exists())

    def test_camt_utf16_le_con_bom_se_procesa(self) -> None:
        xml = REAL_CAMT.read_text(encoding="utf-8")
        self.seed("test_camt053.xml", xml.encode("utf-16"))
        self.assertEqual(self.run_batch(), 0)

        out = self.salida / f"test_camt053_{OUT_DATE}.txt"
        self.assertTrue(out.exists())
        self.assertEqual(self.exact_read(out).count(":61:"), 34)
        self.assertTrue((self.entrada / "Procesados" / "test_camt053.xml").exists())

    def test_fallo_escritura_limpia_parciales_y_no_mueve(self) -> None:
        self.seed("grande.xml", _large_camt_xml())
        self.salida.mkdir(parents=True)
        real_open = open
        calls = {"n": 0}

        def flaky_open(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:  # el segundo archivo de salida falla
                raise OSError("fallo simulado")
            return real_open(*args, **kwargs)

        with mock.patch("builtins.open", side_effect=flaky_open):
            self.assertEqual(self.run_batch(), 1)

        base = self.salida / f"grande_{OUT_DATE_GRANDE}.txt"
        self.assertFalse(base.exists(), "parciales de la corrida deben limpiarse")
        self.assertTrue((self.entrada / "grande.xml").exists(),
                        "el original no se mueve si la escritura falló")
        log = self.salida.glob("log_*.txt").__next__().read_text(encoding="utf-8")
        self.assertIn("ERROR", log)

    def test_original_repetido_en_procesados_avisa_warn(self) -> None:
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)
        shutil.copy(REAL_CAMT, self.entrada / "test_camt053.xml")
        self.assertEqual(self.run_batch(), 0)

        logs = "".join(p.read_text(encoding="utf-8")
                       for p in sorted(self.salida.glob("log_*.txt")))
        self.assertIn("Procesados", logs)
        self.assertIn("WARN", logs)

    def test_lote_limpio_devuelve_cero(self) -> None:
        self.assertEqual(self.run_batch(), 0)


if __name__ == "__main__":
    unittest.main()