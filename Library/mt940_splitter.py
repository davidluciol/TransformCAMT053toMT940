# -*- coding: utf-8 -*-
"""Particionado de un Statement en chunks ≤ MAX_BLOCK4_CHARS por bloque 4.

Toma las líneas del bloque 4 producidas por mt940_builder y decide cuántos
mensajes MT940 se necesitan. Si el bloque 4 completo no cabe:

- la división por tamaño (mecanismo B de la SPEC §6.3) se decide EXCLUSIVAMENTE
  por el conteo de caracteres acumulado del bloque 4 + `SPLIT_RESERVE_CHARS`,
  nunca por la presencia de un balance intermedio (`ITBD`) o un `:62M:` en el
  CAMT de origen — el `:62M:` es una consecuencia del corte, no su causa;
- los chunks intermedios cierran en `:62M:` (saldo corriente tras la última
  entrada del chunk) y el siguiente abre con `:60M:` con exactamente ese
  saldo — continuidad de balance—;
- la secuencia de `:28C:` avanza por chunk (`nnnnn/00001`, `nnnnn/00002`, ...)
  conservando el LglSeqNb original del statement;
- `:62F:`/`:64:` solo al final del último chunk;
- nunca se parte una línea de tag a la mitad: si un `:61:`+`:86:` individual
  supera el límite, se incluye completo con WARN.

Un chunk intermedio marca `ends_with_62m=True` para que el CLI cierre archivo
y abra `_n` (SPEC §6.2 separador `$`, archivos `_2`/`_3`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from Library import config
from Library.mt940_builder import (
    Mt940BuildError,
    _pad5,
    balance_tag,
    entry_delta,
    mt940_date,
)


@dataclass
class Chunk:
    """Un mensaje MT940 (líneas del bloque 4) listo para envolver."""
    lines: list[str] = field(default_factory=list)
    ends_with_62m: bool = False


def _block4_size(lines: list[str]) -> int:
    """Bytes que ocupará el bloque 4 al envolver {4: + líneas CRLF + -}."""
    return 7 + sum(len(line) + 2 for line in lines)


def _balance_str(code: str, balance, date: str, ccy: str) -> str:
    """`60M`/`62M` D/C YYMMDD Ccy Amt,coma desde un saldo corriente."""
    marker = "C" if balance >= 0 else "D"
    return balance_tag(code, marker, date, ccy, abs(balance))


def _entry_blocks(lines: list[str]) -> tuple[list[str], list[list[str]],
                                             list[str]]:
    """Divide las líneas en head (tags :20:/:25:/:28C:/:60F:), bloques de
    entrada (:61: + sus :86:/continuaciones) y tail (:62F:/:64:)."""
    head: list[str] = []
    blocks: list[list[str]] = []
    tail: list[str] = []
    current = None
    started = False
    for line in lines:
        if line.startswith(":61:"):
            current = [line]
            blocks.append(current)
            started = True
        elif not started:
            head.append(line)
        elif line.startswith((":62F:", ":62M:", ":64:")):
            tail.append(line)
            current = None
        elif current is not None:
            current.append(line)
        else:
            tail.append(line)
    return head, blocks, tail


def _chunk_head(head: list[str], ordinal: int) -> list[str]:
    """Head de un chunk: :20:/:25:/:28C: con secuencia = ordinal, sin :60F:."""
    rebuilt: list[str] = []
    for line in head:
        if line.startswith(":28C:"):
            rebuilt.append(line.split("/")[0] + "/" + _pad5(str(ordinal)))
        elif line.startswith(":60F:"):
            continue
        else:
            rebuilt.append(line)
    return rebuilt


def _seq_base(pg_nb: str) -> int:
    """Valor inicial del 2º componente de :28C: (StmtPgntn/PgNb; fallback 1)."""
    digits = "".join(ch for ch in (pg_nb or "") if ch.isdigit())
    return int(digits) if digits else 1


_UNSET = object()


def _page_ref20(base: str, index: int, total: int, step: int) -> str:
    """`:20:` único por mensaje (anchor_last, SPEC §6.4).

    El último mensaje conserva `base` (Stmt/Id); el k-ésimo resta
    (total-k)*step conservando el ancho. Si `base` no es numérico o el
    resultado no es positivo, cae al modo sufijo: base[:13] + NNN.
    """
    if base.isdigit():
        value = int(base) - (total - index) * step
        if value > 0:
            return str(value).zfill(len(base))
    return base[:13] + f"{index:03d}"


def _info_consistencia_20(base: str, total: int, page_size, log,
                          filename: str) -> None:
    """INFO si `int(Stmt/Id[-3:]) != N` (solo s = 3, SPEC §6.4).

    El sufijo del `Stmt/Id` es el conteo de páginas del layout bancario de 3
    entradas; con otro tamaño (o paginado apagado) la comparación no aplica.
    Solo se evalúa cuando hay más de un mensaje.
    """
    if page_size != 3 or not base.isdigit() or len(base) < 3:
        return
    sufijo = int(base[-3:])
    if sufijo != total:
        log.info(filename, "20: consistencia",
                 f"sufijo {base[-3:]} != {total} mensajes")


def _apply_page_refs(chunks: list[list[str]], log, filename: str,
                     step: int, page_size=None) -> None:
    """Reescribe `:20:` para que sea único en cada mensaje del Statement."""
    total = len(chunks)
    if total < 2:
        return
    base = chunks[0][0][len(":20:"):]
    for index, chunk in enumerate(chunks, start=1):
        chunk[0] = ":20:" + _page_ref20(base, index, total, step)
    refs = [chunk[0] for chunk in chunks]
    if len(set(refs)) != total:
        raise Mt940BuildError(f":20: duplicado entre los {total} mensajes")
    _info_consistencia_20(base, total, page_size, log, filename)


def split_statement_lines(lines: list[str], statement, log, filename: str,
                          max_chars: int | None = None,
                          reserve_chars: int | None = None,
                          page_size=_UNSET) -> list[Chunk]:
    """Particiona las líneas del bloque 4 de un Statement en chunks ≤ max_chars.

    Un bloque de entrada nunca se corta: si supera el límite se incluye
    completo con WARN. Si max_chars es None se usa el tope vigente de la
    config (leído en tiempo de llamada); igual para reserve_chars con
    `SPLIT_RESERVE_CHARS`. `page_size` (N movimientos por mensaje) se toma de
    `config.resolve_page_size()` si no se indica; `None` = sin paginado por
    conteo. El corte por conteo ocurre antes del movimiento N+1 y gana sobre
    el de tamaño; el de tamaño sigue como red de seguridad (con paginado
    encendido registra WARN). Fórmula de corte por tamaño (SPEC §6.3 paso 3):
    `projected = _block4_size(chunk + :62M: de cierre + entrada)`; se corta
    antes de la entrada si `projected + reserve_chars > max_chars`. Devuelve
    los chunks en orden con la bandera `ends_with_62m` en cada chunk
    intermedio.
    """
    if max_chars is None:
        max_chars = config.MAX_BLOCK4_CHARS
    if reserve_chars is None:
        reserve_chars = config.SPLIT_RESERVE_CHARS
    if page_size is _UNSET:
        page_size = config.resolve_page_size()
    head, blocks, tail = _entry_blocks(lines)
    if not blocks:
        return [Chunk(lines=list(lines), ends_with_62m=False)]

    book = [e for e in statement.entries if e.sts == "BOOK"]
    if len(blocks) != len(book):
        raise Mt940BuildError(
            f"desajuste bloques/entradas: {len(blocks)} bloques "
            f"vs {len(book)} entradas BOOK")
    if statement.opening is None:
        raise Mt940BuildError("Faltan saldos OPBD para particionar")

    ccy = (statement.ccy or statement.opening.currency or "XXX").strip()
    seq_base = _seq_base(statement.pg_nb)

    running: list[tuple[Decimal, str]] = []
    balance = statement.opening.amount
    for entry in book:
        balance += entry_delta(entry)
        running.append((balance, mt940_date(entry.val_dt)))

    chunks: list[list[str]] = []
    current = list(head)
    has_entry = False
    in_current = 0
    for index, block in enumerate(blocks):
        block_size = _block4_size(block)
        oversized = block_size > max_chars
        if oversized:
            log.warn(filename, "bloque4: 61 no cabe",
                     lost_text=f"bloque de {block_size} chars > {max_chars}")
        if has_entry:
            close = _balance_str("62M", *running[index - 1], ccy)
            by_count = page_size is not None and in_current >= page_size
            by_size = False
            if not by_count and not oversized:
                projected = _block4_size(current + [close] + block)
                by_size = projected + reserve_chars > max_chars
                if by_size and page_size is not None:
                    log.warn(filename, "paginado: corte por tamaño",
                             lost_text=f"mensaje de {in_current} movimientos "
                                       f"cortado antes de lo previsto ({page_size})")
            if by_count or by_size:
                current.append(close)
                chunks.append(current)
                current = _chunk_head(head, seq_base + len(chunks))
                current.append(_balance_str("60M", *running[index - 1], ccy))
                in_current = 0
        current.extend(block)
        has_entry = True
        in_current += 1

    if has_entry:
        current.extend(tail)
    chunks.append(current)
    _apply_page_refs(chunks, log, filename, config.PAGE_REF20_STEP,
                     page_size=page_size)

    return [Chunk(lines=chunk, ends_with_62m=index < len(chunks) - 1)
            for index, chunk in enumerate(chunks)]