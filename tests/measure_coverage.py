# -*- coding: utf-8 -*-
"""Mide cobertura (best-effort) de los módulos núcleo con `trace` (stdlib).

Uso desde la raíz del repo:
    python tests/measure_coverage.py

Devuelve 0 si los 4 módulos núcleo alcanzan MIN_COVERAGE, 1 si alguno se
queda corto. Sirve de verificación para Task 9 / SPEC §9.

Métrica: sentencias ejecutables (línea inicial de cada sentencia según `ast`,
sin docstrings) que el `trace` de stdlib cuenta como alcanzadas durante la
suite. El denominador por `ast` evita inflar con líneas de continuación que
`trace` no reporta por separado.
"""

from __future__ import annotations

import ast
import os
import sys
import trace
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORE_MODULES = (
    "camt053.py",
    "mt940_builder.py",
    "mt940_splitter.py",
    "swift_charset.py",
)
MIN_COVERAGE = 0.90


def _code_lines(path: Path) -> set[int]:
    """Líneas iniciales de sentencias ejecutables (sin docstrings)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    starts: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue
        starts.add(node.lineno)
    return starts


def _run_suite() -> bool:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    runner = unittest.TextTestRunner(
        verbosity=1, stream=open(os.devnull, "w", encoding="utf-8"))
    return runner.run(suite).wasSuccessful()


def main() -> int:
    tracer = trace.Trace(count=True, trace=False, ignoredirs=[])
    success = tracer.runfunc(_run_suite)
    counts = tracer.results().counts

    print(f"\n{'módulo':<22} {'cubiertas':>9} {'ejecutables':>12} {' %':>6}")
    low = 0
    for name in CORE_MODULES:
        code = _code_lines(ROOT / "Library" / name)
        covered = {n for (fn, n) in counts if Path(fn).name == name}
        hit = len(covered & code)
        pct = hit / len(code)
        flag = "  OK" if pct >= MIN_COVERAGE else "  <90%"
        print(f"{name:<22} {hit:>9} {len(code):>12} {pct:>5.1%}{flag}")
        if pct < MIN_COVERAGE:
            low += 1

    print(f"\nSuite de tests: " + ("OK" if success else "FAILED"))
    return 1 if (low or not success) else 0


if __name__ == "__main__":
    sys.exit(main())