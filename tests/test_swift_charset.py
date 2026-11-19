# -*- coding: utf-8 -*-
"""Task 3 — swift_charset.py: fold de acentos, limpieza SWIFT, truncado, wrap."""

import unittest
from datetime import datetime

import _pathfix  # noqa: F401

from Library.runlog import RunLog
from Library.swift_charset import clean, fold_accents, limit, wrap

RUN_AT = datetime(2026, 9, 18, 10, 30, 15)


def make_log() -> RunLog:
    return RunLog(now=lambda: RUN_AT)


class TestFoldAccents(unittest.TestCase):

    def test_ases_fold(self):
        self.assertEqual(fold_accents("Société Générale"), "Societe Generale")

    def test_ene_y_n_tilde(self):
        self.assertEqual(fold_accents("Año 2026"), "Ano 2026")

    def test_texto_sin_acentos_intacto(self):
        self.assertEqual(fold_accents("ABC 123/-"), "ABC 123/-")


class TestClean(unittest.TestCase):

    def test_colapsa_whitespace_y_trim(self):
        self.assertEqual(clean("  uno \t dos \r\n tres  "), "uno dos tres")

    def test_acentos_se_pliegan_antes_del_charset(self):
        self.assertEqual(clean("Courçonne Ñuñéz"), "Courconne Nunez")

    def test_caracteres_fuera_del_set_se_eliminan(self):
        self.assertEqual(clean("Hola € 100% #ok"), "Hola 100 ok")

    def test_sin_perdida_no_genera_warn(self):
        log = make_log()
        self.assertEqual(clean("Pago / Banco (MX) 1.000,00", log=log), "Pago / Banco (MX) 1.000,00")
        self.assertEqual(log.events, [])

    def test_perdida_genera_warn_con_texto_perdido(self):
        log = make_log()
        self.assertEqual(clean("Courçonne €", log=log, filename="archivo.xml"), "Courconne")
        self.assertEqual(len(log.events), 1)
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | archivo.xml | WARN: [charset] + €",
        )

    def test_texto_perdido_es_el_real_en_orden_y_con_repeticiones(self):
        log = make_log()
        self.assertEqual(clean("Sueldo 500€€ y §§ extra €",
                               log=log, filename="x.xml"),
                         "Sueldo 500 y extra")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | x.xml | WARN: [charset] + €€§§€",
        )

    def test_texto_perdido_truncado_con_nota_de_omitidos(self):
        log = make_log()
        clean("datos " + "§" * 200, log=log, filename="x.xml")
        text = str(log.events[0])
        self.assertIn("[charset] + " + "§" * 60 + "…", text)
        self.assertIn("+140 más", text)
        self.assertLess(len(text), 250)


class TestLimit(unittest.TestCase):

    def test_corto_pasa_sin_cambios(self):
        self.assertEqual(limit("12345", 10, "campo"), "12345")

    def test_largo_trunca_sin_log(self):
        self.assertEqual(limit("123456789", 5, "campo"), "12345")

    def test_truncado_registra_warn_con_total_descartado(self):
        log = make_log()
        result = limit("123456789", 5, "NtryRef", log=log, filename="a.xml")
        self.assertEqual(result, "12345")
        self.assertEqual(
            str(log.events[0]),
            "18/09/2026 10:30 | a.xml | WARN: [NtryRef: truncado] + se descartaron 4 caracteres",
        )

    def test_limpia_antes_de_limitar(self):
        self.assertEqual(limit("  abcd  ", 10, "campo"), "abcd")


class TestWrap(unittest.TestCase):

    def test_envuelve_sin_cortar_palabras(self):
        self.assertEqual(wrap("uno dos tres cuatro", width=10),
                         ["uno dos", "tres", "cuatro"])

    def test_ninguna_linea_supera_el_ancho(self):
        for line in wrap("palabra repetida palabra repetida", width=7):
            self.assertLessEqual(len(line), 7)

    def test_palabra_mas_larga_que_el_ancho_se_parte(self):
        lines = wrap("supercalifragilisticoespialidoso", width=10)
        self.assertTrue(all(len(line) <= 10 for line in lines))
        self.assertEqual("".join(lines), "supercalifragilisticoespialidoso")

    def test_vacio_devuelve_lista_vacia(self):
        self.assertEqual(wrap("   ", width=65), [])

    def test_ancho_default_es_65(self):
        lines = wrap("x" * 130)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(len(line) <= 65 for line in lines))


if __name__ == "__main__":
    unittest.main()