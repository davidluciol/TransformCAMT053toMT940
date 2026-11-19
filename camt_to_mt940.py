# -*- coding: utf-8 -*-
"""Orquestación del lote: CLI -i/-o, detección por contenido, Procesados, log.

Convierte cada archivo CAMT.053 del directorio de entrada a archivos MT940 en
la carpeta de salida, siguiendo las reglas de ensamblado de la SPEC §6.3:

- Todos los mensajes MT940 de un CAMT van a UN SOLO archivo, separados con `$`
  (`OUTPUT_MODE = "single_file"`, default). Con `OUTPUT_MODE = "split_files"`
  (legado), un chunk que cierra con `:62M:` cierra el archivo actual y abre uno
  NUEVO con sufijo `_2`, `_3`, ...
- Nombre base: `<nombre original>_<ddMMyyyy>.txt`, con la fecha de la última
  transacción (`BOOK`). Si ese nombre excede `FILENAME_MAX_CHARS` (32), se
  compacta a `<BIC8 destino>_<YYMMDD transacción>_<ddMMyy corrida>.txt`. Si el
  destino ya existe, NUNCA se sobrescribe: se agrega `(1)`, `(2)`, ... sobre el
  nombre deseado y, si el contador no cabe, sobre el compacto (SPEC §6.3-C).
- Los originales convertidos se mueven a `<entrada>\\Procesados` solo si toda la
  conversión terminó con éxito; un fallo deja el original en su lugar (ERROR).
- La detección es por contenido (parseo XML + `BkToCstmrStmt`), nunca por
  extensión. Un archivo no-CAMT produce WARN y se omite.

Toda incidencia va por `RunLog` (nunca `print`). El progreso del lote se
muestra en stdout solo cuando `echo=True` (así lo hace el CLI): "Transformando
<archivo>", "Transformacion exitosa", "Ha ocurrido un error ... registrando en
Log", "Omitido, no es un CAMT.053", "No se encontraron archivos ...", y un
resumen final. Código de salida: 0 si la corrida terminó sin ERROR; 1 si hubo al
menos un ERROR.
"""

from __future__ import annotations

import argparse
import codecs
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from Library import config
from Library.camt053 import CamtDocument, CamtParseError, parse_document
from Library.mt940_builder import (
    BalanceMismatchError,
    Mt940BuildError,
    build_statement_lines,
    join_messages,
    mt940_date,
    wrap_message,
)
from Library.config import resolve_header_values, resolve_page_size
from Library.mt940_splitter import split_statement_lines
from Library.runlog import RunLog

_STATUS_OK = "ok"
_STATUS_SKIPPED = "skipped"
_STATUS_ERROR = "error"


def _transaction_date(document: CamtDocument) -> str:
    """Fecha ISO (`YYYY-MM-DD`) de la transacción BOOK más reciente; '' si no hay."""
    dates = [
        (entry.bookg_dt or entry.val_dt).split("T")[0]
        for stmt in document.statements
        for entry in stmt.entries
        if entry.sts == "BOOK" and (entry.bookg_dt or entry.val_dt)
    ]
    return max(dates) if dates else ""


def _fmt_dmy(iso: str) -> str:
    """'2026-08-31' → '31082026'; sin 8 dígitos → ''."""
    digits = "".join(ch for ch in (iso or "").split("T")[0] if ch.isdigit())
    return f"{digits[6:8]}{digits[4:6]}{digits[0:4]}" if len(digits) >= 8 else ""


def _compact_stem(bic: str, tx_date: str, run_at: datetime) -> str:
    """Stem compacto `<BIC8>_<YYMMDD transacción>_<ddMMyy corrida>` (SPEC §6.3-C)."""
    bic8 = "".join(ch for ch in (bic or "").upper()
                   if ch.isalnum())[:config.COMPACT_BIC_WIDTH] or "XXXXXXXX"
    tx = mt940_date(tx_date) if tx_date else run_at.strftime("%y%m%d")
    return f"{bic8}_{tx}_{run_at.strftime('%d%m%y')}"


def _output_stems(stem: str, run_at: datetime, n_files: int, *,
                  bic: str = "", tx_date: str = "") -> list[tuple[str, str]]:
    """Pares (stem deseado, stem compacto) sin extensión, uno por archivo.

    El deseado es `<stem>_<ddMMyyyy de la última transacción>`; si el juego
    completo (con el mayor sufijo `_N`) excede `FILENAME_MAX_CHARS`, el deseado
    pasa a ser el compacto. El compacto se devuelve siempre como alternativa
    para resolver colisiones (SPEC §6.3-C).
    """
    normal = f"{stem}_{_fmt_dmy(tx_date) or run_at.strftime('%d%m%Y')}"
    compact = _compact_stem(bic, tx_date, run_at)
    max_suffix = "" if n_files <= 1 else f"_{n_files}"
    if len(normal + max_suffix + config.OUT_EXTENSION) > config.FILENAME_MAX_CHARS:
        normal = compact
    stems: list[tuple[str, str]] = []
    for i in range(1, n_files + 1):
        suffix = "" if i == 1 else f"_{i}"   # `_2`, `_3`, ... solo en split_files
        stems.append((f"{normal}{suffix}", f"{compact}{suffix}"))
    return stems


def _resolve_output_name(out_dir: Path, stem: str, compact_stem: str) -> str:
    """Nombre libre para `stem`: si ya existe, `<stem>(n).ext`; si no cabe, compacto.

    Nunca sobrescribe: agrega `(1)`, `(2)`, ... antes de la extensión mientras
    quepan en `FILENAME_MAX_CHARS`; si no cabe, reintenta sobre el stem compacto
    (SPEC §6.3-C).
    """
    limit = config.FILENAME_MAX_CHARS
    ext = config.OUT_EXTENSION

    def _free(base: str) -> str | None:
        if not (out_dir / f"{base}{ext}").exists():
            return f"{base}{ext}"
        n = 1
        while len(base) + len(f"({n})") + len(ext) <= limit:
            candidate = f"{base}({n}){ext}"
            if not (out_dir / candidate).exists():
                return candidate
            n += 1
        return None

    return _free(stem) or _free(compact_stem)


def _resolve_output_names(out_dir: Path, stems: list[tuple[str, str]],
                          log: RunLog, filename: str) -> list[str] | None:
    """Nombre libre por cada (stem, compacto); `None` si ninguno queda disponible.

    Un destino ocupado se resuelve con `(1)`, `(2)`, ... y se avisa con WARN
    (SPEC §6.3-C). Si no hay nombre libre para algún archivo, se registra ERROR
    y se devuelve `None` (el original no debe moverse).
    """
    names: list[str] = []
    for stem, compact in stems:
        out_name = _resolve_output_name(out_dir, stem, compact)
        if out_name is None:
            log.error(filename, f"sin nombre de salida libre para '{stem}'")
            return None
        if out_name != f"{stem}{config.OUT_EXTENSION}":
            log.warn(filename, f"destino ya existe, se guarda como: {out_name}")
        names.append(out_name)
    return names


def _write_groups(out_dir: Path, names: list[str], groups: list[list[str]],
                  log: RunLog, filename: str) -> bool:
    """Escribe un archivo por grupo. True si todos se escribieron.

    Ante un fallo de escritura borra los archivos parciales de esta corrida y
    registra ERROR, para que el original no se mueva.
    """
    written: list[Path] = []
    for out_name, group in zip(names, groups):
        target = out_dir / out_name
        try:
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(join_messages(group))
        except OSError as exc:
            for partial in written:
                try:
                    partial.unlink()
                except OSError:
                    pass
            log.error(filename, f"escritura de {out_name}: {exc}")
            return False
        written.append(target)
    return True


def _archive_source(src: Path, log: RunLog, filename: str) -> bool:
    """Mueve el original a `<entrada>/Procesados`. True si el movimiento tuvo éxito."""
    processed_dir = src.parent / config.PROCESSED_DIRNAME
    processed_dir.mkdir(exist_ok=True)
    archived = processed_dir / filename
    if archived.exists():
        log.warn(filename, f"destino en Procesados ya existe, se sobrescribe: {filename}")
    try:
        src.replace(archived)
    except OSError as exc:
        log.error(filename, f"movimiento a Procesados: {exc}")
        return False
    return True


def _messages_for(from_camt: CamtDocument, config, log: RunLog,
                  filename: str, run_at: datetime) -> list[list[str]]:
    """Agrupa los mensajes MT940 del documento en archivos.

    Devuelve una lista de archivos; cada archivo es la lista de mensajes que se
    juntarán con `$`. Un chunk que cierra con `:62M:` cierra el archivo actual
    (una pieza más del lote continua en el archivo siguiente), por lo que esa
    lista siempre queda unitaria. Solo con `OUTPUT_MODE="split_files"` (legado);
    con `"single_file"` (default) todos los mensajes van en un único archivo.
    """
    out_date = run_at.strftime("%y%m%d")
    out_time = run_at.strftime("%H%M")
    groups: list[list[str]] = []
    current: list[str] = []
    page_size = resolve_page_size(config.PAGING_ENABLED,
                                  config.ENTRIES_PER_MESSAGE)
    split_files = config.OUTPUT_MODE == "split_files"
    sender_lt, receiver_address = resolve_header_values(
        from_camt.apphdr_fr_bic, from_camt.apphdr_to_bic, log, filename)

    def flush() -> None:
        if current:
            groups.append(current.copy())
            current.clear()

    for stmt in from_camt.statements:
        lines = build_statement_lines(stmt, from_camt.msg_id, config, log, filename)
        reference = lines[0][len(":20:"):] if lines else from_camt.msg_id
        for chunk in split_statement_lines(lines, stmt, log, filename,
                                           page_size=page_size):
            current.append(wrap_message(
                chunk.lines, config, reference=reference,
                in_time=out_time, in_date=out_date,
                out_date=out_date, out_time=out_time,
                sender_lt=sender_lt, receiver_address=receiver_address,
            ))
            if chunk.ends_with_62m and split_files:
                flush()

    flush()
    return groups


def _decode_text(data: bytes) -> str:
    """Decodifica la entrada: UTF-8, o UTF-16 con BOM (LE/BE); falla → UnicodeError."""
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    return data.decode("utf-8")


def process_file(src: Path, out_dir: Path, *, config=config, log: RunLog,
                 run_at: datetime) -> str:
    """Procesa un archivo de entrada. Devuelve ok | skipped | error."""
    name = src.name
    try:
        data = _decode_text(src.read_bytes())
    except (OSError, UnicodeError) as exc:
        log.error(name, f"lectura: {exc}")
        return _STATUS_ERROR

    try:
        document = parse_document(data)
    except CamtParseError as exc:
        if "BkToCstmrStmt" in data:
            log.error(name, f"CAMT.053 inválido: {exc}")
            return _STATUS_ERROR
        log.warn(name, f"no es un CAMT.053, se omite: {exc}")
        return _STATUS_SKIPPED

    try:
        groups = _messages_for(document, config, log, name, run_at)
    except (Mt940BuildError, BalanceMismatchError) as exc:
        log.error(name, f"fallo de conversión: {exc}")
        return _STATUS_ERROR

    stems = _output_stems(Path(name).stem, run_at, len(groups),
                          bic=document.apphdr_to_bic or config.RECEIVER_ADDRESS,
                          tx_date=_transaction_date(document))
    out_dir.mkdir(parents=True, exist_ok=True)
    names = _resolve_output_names(out_dir, stems, log, name)
    if names is None:
        return _STATUS_ERROR
    if not _write_groups(out_dir, names, groups, log, name):
        return _STATUS_ERROR
    if not _archive_source(src, log, name):
        return _STATUS_ERROR
    return _STATUS_OK


def run_batch(in_path: Path, out_path: Path, *, config=config,
              log: RunLog | None = None, run_at: datetime | None = None,
              echo: bool = False) -> int:
    """Convierte todos los archivos de la entrada y devuelve el código de salida.

    Con `echo=True` muestra en stdout el progreso del lote (Transformando /
    exitosa / error / omitido / resumen). Las incidencias siempre van al log.
    """
    run_at = run_at or datetime.now()
    log = log or RunLog(now=lambda: run_at)

    src = Path(in_path)
    if not src.exists():
        if echo:
            print(f"Ruta de entrada inexistente: {src}, registrando en Log")
        log.error(str(src), "ruta de entrada inexistente")
        log.write(Path(out_path))
        return 1

    if src.is_dir():
        # Los archivos ocultos (p. ej. `.gitkeep`, `.DS_Store`) no son estados
        # de cuenta y no deben aparecer como "omitidos" en cada corrida.
        candidates = sorted(p for p in src.iterdir()
                            if p.is_file() and not p.name.startswith("."))
    else:
        candidates = [src]

    if not candidates and echo:
        # Sin archivos no hay nada que convertir, pero el usuario debe saberlo
        # (p. ej. todo lo movido ya en `Procesados`).
        print(f"No se encontraron archivos para convertir en {src}")

    errors = 0
    transformed = 0
    skipped = 0
    for candidate in candidates:
        if echo:
            print(f"Transformando {candidate.name}")
        status = process_file(candidate, Path(out_path), config=config,
                              log=log, run_at=run_at)
        if status == _STATUS_OK:
            transformed += 1
            if echo:
                print(f"Transformacion exitosa, continuando con el siguiente: "
                      f"{candidate.name}")
        elif status == _STATUS_SKIPPED:
            skipped += 1
            if echo:
                print(f"Omitido, no es un CAMT.053: {candidate.name}")
        else:
            errors += 1
            if echo:
                print(f"Ha ocurrido un error en {candidate.name}, "
                      f"registrando en Log")
    log.write(Path(out_path))
    if echo:
        print(f"Resumen: {transformed} transformados, {skipped} omitidos, "
              f"{errors} con error")
    return 1 if errors else 0


def main(argv: list[str] | None = None,
         now: Callable[[], datetime] | None = None) -> int:
    """Punto de entrada del CLI. Devuelve el código de salida del proceso."""
    parser = argparse.ArgumentParser(
        prog="camt_to_mt940",
        description="Convierte estados CAMT.053 a MT940 SWIFT de 5 bloques.",
    )
    parser.add_argument("-i", dest="in_path", required=True,
                        help="archivo o carpeta de entrada")
    parser.add_argument("-o", dest="out_path", required=True,
                        help="carpeta de salida")
    args = parser.parse_args(argv)
    return run_batch(Path(args.in_path), Path(args.out_path),
                     log=RunLog(now=now), run_at=now() if now else None,
                     echo=True)


if __name__ == "__main__":
    sys.exit(main())