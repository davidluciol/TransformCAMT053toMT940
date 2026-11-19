# -*- coding: utf-8 -*-
"""Saneamiento de texto para MT940/SWIFT.

- fold_accents: convierte acentos/diacríticos a su base ASCII (NFD).
- clean: colapsa espacios, pliega acentos, elimina los caracteres fuera del
  charset SWIFT y avisa de la pérdida al RunLog.
- limit: trunca a una longitud máx. y registra el truncado.
- wrap: envuelve texto por palabras a un ancho dado, sin exceder líneas.
"""

from __future__ import annotations

import re
import unicodedata

from Library.runlog import RunLog

# ---------------------------------------------------------------------------
# Charset SWIFT: A-Z a-z 0-9 espacio / - ? : ( ) . , ' +
# ---------------------------------------------------------------------------
_SWIFT_SET = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " /-?:().,'+"
)
_WS_RUNS = re.compile(r"\s+")
_MAX_REPORTED_LOST = 60     # chars mostrados en el WARN de pérdida


def collapse_whitespace(value: str) -> str:
    """Colapsa cualquier secuencia de whitespace a un solo espacio y recorta."""
    return _WS_RUNS.sub(" ", value).strip()


def fold_accents(value: str) -> str:
    """Normaliza NFD y descarta marcas combinantes (é→e, ñ→n)."""
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def clean(value: str, log: RunLog | None = None, filename: str = "",
          rule: str = "charset", collapse: bool = True) -> str:
    """Limpia texto para MT940.

    Pliega acentos primero, luego descarta cada carácter fuera del charset
    SWIFT. Si se descartaron caracteres y hay RunLog, registra
    un WARN con el texto perdido REAL (en orden y con repeticiones); si supera
    `_MAX_REPORTED_LOST`, se trunca con nota de los omitidos. Con
    `collapse=False` se preservan los espacios internos (SPEC §6.6).
    """
    value = collapse_whitespace(value) if collapse else value.strip()
    value = fold_accents(value)
    keep: list[str] = []
    removed: list[str] = []
    for ch in value:
        if ch in _SWIFT_SET:
            keep.append(ch)
        elif not ch.isspace():
            removed.append(ch)
    if removed and log is not None:
        lost = "".join(removed)
        if len(lost) > _MAX_REPORTED_LOST:
            log.warn(filename, rule,
                     lost[:_MAX_REPORTED_LOST]
                     + f"… (+{len(lost) - _MAX_REPORTED_LOST} más)")
        else:
            log.warn(filename, rule, lost)
    result = "".join(keep)
    return collapse_whitespace(result) if collapse else result


def limit(value: str, max_len: int, field: str,
          log: RunLog | None = None, filename: str = "") -> str:
    """Limpia y trunca a max_len, avisando de los caracteres descartados."""
    value = clean(value, log=log, filename=filename)
    if len(value) <= max_len:
        return value
    if log is not None:
        over = len(value) - max_len
        log.warn(filename, f"{field}: truncado",
                 f"se descartaron {over} caracteres")
    return value[:max_len]


def wrap(text: str, width: int = 65) -> list[str]:
    """Envuelve por palabras sin exceder width; rompe palabras largas."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(word[i:i + width] for i in range(0, len(word), width))
            continue
        candidate = word if not current else f"{current} {word}"
        if len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines