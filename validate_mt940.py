#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Validador externo de archivos MT940 usando la librería mt-940 (PyPI).

Instalar dependencia:  pip install mt-940

Uso:
    python validate_mt940.py [archivo.txt ...]

Sin argumentos, valida los archivos de Salida/ del proyecto.
"""
from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

try:
    from mt940 import parse
except ImportError:
    sys.exit("ERROR: instalar primero 'pip install mt-940'")


_RE_SALDOS = re.compile(
    r"final_opening:\s*([\d,\.]+)\s*(\w+)"
    r".*?"
    r"final_closing:\s*([\d,\.]+)\s*(\w+)"
)


def parse_amount(amount_obj) -> Decimal:
    """Extrae Decimal desde el objeto Amount de mt940."""
    s = str(amount_obj)
    m = re.match(r"([+-]?[\d,]+\.\d+)", s)
    if not m:
        raise ValueError(f"No se pudo parsear el monto: {amount_obj!r}")
    return Decimal(m.group(1).replace(",", ""))


def validate_file(fpath: str) -> tuple[bool, str]:
    """Valida un archivo MT940. Devuelve (ok, mensaje)."""
    with open(fpath, "r", encoding="utf-8") as fh:
        content = fh.read()

    try:
        result = parse(content)
    except Exception as exc:
        return False, f"Parse ERROR: {exc}"

    txs = list(result.transactions)
    if not txs:
        return True, "Parse OK pero 0 transacciones extraídas (posible perfil legacy)"

    # extraer saldos del repr
    m = re.search(r"final_opening:\s*([\d,\.]+)\s*(\w+)", str(result))
    if not m:
        return False, "No se encontró opening balance en el repr"
    opbd = Decimal(m.group(1).replace(",", ""))
    ccy = m.group(2)

    m = re.search(r"final_closing:\s*([\d,\.]+)\s*(\w+)", str(result))
    if not m:
        return False, "No se encontró closing balance en el repr"
    clbd = Decimal(m.group(1).replace(",", ""))

    # sumar montos
    credits = Decimal("0")
    debits = Decimal("0")
    for tx in txs:
        amt = parse_amount(tx.data["amount"])
        if amt >= 0:
            credits += amt
        else:
            debits += abs(amt)

    expected = opbd + credits - debits
    diff = abs(expected - clbd)

    ok = diff < Decimal("0.01")
    status = "VALIDO" if ok else "INVALIDO"
    msg = (
        f"{status}: {len(txs)} transacciones, saldos cuadrados "
        f"(diff={diff:.4f} {ccy})"
        if ok
        else f"{status}: {len(txs)} transacciones, saldos NO cuadran (diff={diff:.4f} {ccy})"
    )
    return ok, msg


def _default_files() -> list[str]:
    """Archivos .txt de Salida/ (excluye logs y archivos ocultos)."""
    out_dir = Path("Salida")
    if not out_dir.is_dir():
        return []
    return [str(p) for p in sorted(out_dir.glob("*.txt"))
            if not p.name.startswith(("log_", "."))]


def main(argv: list[str] | None = None) -> int:
    files = argv[1:] if argv else _default_files()
    if not files:
        print("No se encontraron archivos .txt en Salida/.")
        print("Uso: python validate_mt940.py [archivo.txt ...]")
        return 1

    all_ok = True
    print("=" * 70)
    print("VALIDACION MT940 CON LIBRERIA EXTERNA mt-940 (pip install mt-940)")
    print("=" * 70)
    print()

    for fpath in files:
        try:
            ok, msg = validate_file(fpath)
        except FileNotFoundError:
            print(f"  NO ENCONTRADO: {fpath}")
            all_ok = False
            continue
        except Exception as exc:
            print(f"  ERROR inesperado: {fpath} -> {exc}")
            all_ok = False
            continue

        print(f"  {fpath}:")
        print(f"    {msg}")
        print()
        if not ok:
            all_ok = False

    print("=" * 70)
    print(f"RESULTADO GLOBAL: {'TODOS VALIDOS' if all_ok else 'HAY ARCHIVOS INVALIDOS'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
