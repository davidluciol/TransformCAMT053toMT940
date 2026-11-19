# -*- coding: utf-8 -*-
"""Helpers de test para el paginado (config.PAGING_ENABLED / OUTPUT_MODE)."""

from unittest import mock

from Library import config


def legacy_single_message(testcase) -> None:
    """Restaura el comportamiento previo al paginado por conteo en este test.

    Un mensaje por Statement (salvo el tope de MAX_BLOCK4_CHARS) y archivos
    `_2`/`_3` al cortar por tamaño. Se revierte solo al terminar el test.
    """
    patcher = mock.patch.multiple(config, PAGING_ENABLED=False,
                                  OUTPUT_MODE="split_files")
    patcher.start()
    testcase.addCleanup(patcher.stop)
