# -*- coding: utf-8 -*-
"""Asegura que la raíz del proyecto esté en sys.path para que los tests de
unittest (discover -s tests) puedan importar los módulos top-level."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))