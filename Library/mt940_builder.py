# -*- coding: utf-8 -*-
"""Armado de contenido MT940 a partir de un Statement CAMT.053.

Genera las líneas del bloque 4 (tags :20:, :25:, :28C:, :60F:, :61:/:86:,
:62F:, :64:) con montos de coma decimal, fechas YYMMDD/MMDD y balances D/C.
Al envolver el mensaje (wrap_message) el perfil FIN default (SPEC §6.2/§11)
monta la envoltura SOLO desde los templates de config con los tags a columna
0 separados por CRLF y bloques 3/5 opcionales (OFF por defecto); el perfil
legado del banco (config.PROFILE="legacy") conserva el wrapper F21, el
bloque 2 '0940' y la indentación de 1 espacio del ejemplo real.

Incidencia: valida integridad `OPBD +/- Σ:61: == CLBD` (tol. 0.005); un desfase
levanta BalanceMismatchError. Cada pérdida (truncados, charset, tipo de
transacción) se reporta vía RunLog, nunca en silencio.

Validación obligatoria (SPEC §6.4/§12.4): `build_field_61`/`validate_field_61`
y `build_field_86`/`wrap_field_86`/`validate_field_86` corren ANTES de
serializar; una violación de gramática (`:61:` con narrativa pegada, `:86:`
>6×65, continuaciones con tag) levanta Mt940BuildError y nunca produce salida
inválida. `wrap_message` revalida el bloque 4 como compuerta final.

Alcance: un Statement → un único mensaje. La división multi-mensaje y los
saldos :60M:/:62M: son responsabilidad de mt940_splitter.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation

from Library import config
from Library.config import Mt940BuildError
from Library.camt053 import Balance, Entry, Statement
from Library import swift_charset


class BalanceMismatchError(Mt940BuildError):
    """OPBD +/- Σ:61: no cuadra con CLBD (tol. 0.005)."""



def format_amount(value: Decimal) -> str:
    """Decimal → importe MT940 con coma decimal y 2 decimales."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise Mt940BuildError(f"Importe inválido '{value}'") from exc
    return f"{amount:.2f}".replace(".", ",")


def dc(cdt_dbt_ind: str) -> str:
    """CRDT→C, DBIT→D; desconocido → ''."""
    return {"CRDT": "C", "DBIT": "D"}.get(cdt_dbt_ind or "", "")


def _marker(cdt_dbt_ind: str) -> str:
    """Marca D/C del SWIFT; un `CdtDbtInd` fuera de CRDT/DBIT es ERROR.

    Antes un valor desconocido (o vacío) se convertía en `C` en silencio,
    invirtiendo el signo del saldo sin avisar (SPEC §6.4).
    """
    marker = dc(cdt_dbt_ind)
    if not marker:
        raise Mt940BuildError(
            f"CdtDbtInd inválido {cdt_dbt_ind!r}: debe ser CRDT o DBIT")
    return marker


def mt940_date(iso: str) -> str:
    """'2026-08-31' → '260831' (YYMMDD); sin dígitos devuelve ''. """
    digits = "".join(ch for ch in (iso or "") if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def mmdd(iso: str) -> str:
    """'2026-08-31' → '0831' (MMDD)."""
    digits = "".join(ch for ch in (iso or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits


def _pad5(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if digits:
        return f"{int(digits):05d}"
    return "00001"


def _real(value: str | None) -> str | None:
    """None para vacío/whitespace/'NONE' (placeholder del banco)."""
    if value is None:
        return None
    value = value.strip()
    if not value or value == "NONE":
        return None
    return value


def ref20(stmt_id: str, msg_id: str, log, filename: str) -> str:
    """`:20:` ← Stmt/Id (fallback MsgId).

    SWIFT `:20:` es `16x` sin `/` inicial/final ni `//`. Si el valor excede 16
    o viola esa regla se reemplaza por `C`+SHA-256(15) con WARN (SPEC §6.4).
    """
    value = swift_charset.clean(stmt_id or msg_id or "",
                                log=log, filename=filename)
    motivo = None
    if len(value) > 16:
        motivo = "larga"
    elif "//" in value or value.startswith("/") or value.endswith("/"):
        motivo = "invalida"
    if motivo is None:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:15]
    log.warn(filename, f"20: referencia {motivo}",
             lost_text=f"'{value}'")
    return "C" + digest


def tx_type(entry: Entry, config, log, filename: str) -> str:
    """Tipo de transacción (1!a3!c): TX_TYPE_MAP → Prtry 4 → NMSC + WARN."""
    code = (entry.tx_code or "").strip()
    mapped = (config.TX_TYPE_MAP or {}).get(code)
    if mapped:
        return mapped
    if len(code) == 4 and code.isalnum():
        return code
    log.warn(filename, "tx-type", lost_text=f"código '{code}'")
    return config.FALLBACK_TX_CODE


def balance_tag(code: str, marker: str, date: str, ccy: str,
                amount: Decimal) -> str:
    """Línea de balance `:code:MARKER YYMMDD Ccy Amt,00` (prefijada)."""
    return f":{code}:{marker}{date}{ccy}{format_amount(amount)}"


_BALANCE_RE = re.compile(
    r"^:(?:60F|60M|62F|62M|64|65):[DC]\d{6}[A-Z]{3}\d{1,15},\d{2}$")


def validate_balance_tag(value: str) -> str:
    """Valida un balance contra SWIFT `1!a6!n3!a15d` (doc SWIFT / SPEC §6.2).

    Exige marca `D`/`C`, fecha `YYMMDD`, moneda `3!a` y monto con coma. Levanta
    Mt940BuildError si el render no cumple (evita emitir `:60:`/`:62:`/`:64:`
    malformados por una fecha corta o una moneda de 2 letras).
    """
    if not _BALANCE_RE.fullmatch(value or ""):
        raise Mt940BuildError(
            f"balance no cumple 1!a6!n3!a15d: {value!r}")
    return value


def balance_line(code: str, balance: Balance, config, log, filename: str) -> str:
    """Línea de balance :60F:/:62F:/:62M:/:64: en formato D/C YYMMDD Ccy Amt."""
    marker = _marker(balance.cdt_dbt_ind)
    currency = (balance.currency or "XXX").strip()
    return validate_balance_tag(
        balance_tag(code, marker, mt940_date(balance.date),
                    currency, balance.amount))


# Gramática del :61: (SPEC §6.5):
# :61:<YYMMDD>[<MMDD>]<D|C|RC|RD>[<1!a funds>]<amount><1!a3!c><owner 16x>//<bank 16x>
# Ninguna narrativa libre puede quedar pegada a la línea primaria (§9).
_FIELD61_RE = re.compile(
    r":61:"
    r"(?P<val>\d{6})"               # YYMMDD fecha valor
    r"(?P<book>\d{4})?"             # [MMDD] fecha de registro
    r"(?P<mark>RC|RD|[DC])"         # D/C + inversión (RC/RD)
    r"(?P<funds>[A-Z])?"            # [funds code]
    r"(?P<amount>\d{1,12},\d{2})"   # importe ≤15 chars con coma decimal
    r"(?P<type>[SNF][A-Z0-9]{3})"   # 1!a3!c: prefijo S/N/F (doc SWIFT)
    r"(?P<owner>(?:[^/]|/(?!/)){1,16})"  # 16x: admite '/' suelto, no '//'
    r"(?://(?P<bank>[^/]{0,16}))?"  # //bank reference (16x si PAD_61_REFS)
    r"$"
)

_TAG_PREFIX_RE = re.compile(r":\d{2}[A-Z]?:")


def validate_field_61(value: str, padded: bool | None = None) -> str:
    """Aplica la gramática §6.5 al :61: antes de serializar.

    Levanta Mt940BuildError si la línea no cumple (narrativa pegada, importe
    fuera de 15d, refs >16x, estructura inválida, CR/LF embebido). Con
    `padded` (default `config.PAD_61_REFS`) exige owner y bank de 16 chars
    con `//` presente; sin padding admite refs 1..16 y `//` opcional.
    Devuelve el valor intacto si pasa.
    """
    if padded is None:
        padded = config.PAD_61_REFS
    match = _FIELD61_RE.fullmatch(value or "")
    if match is None:
        raise Mt940BuildError(f":61: no cumple la gramática: {value!r}")
    if padded:
        owner = match.group("owner")
        bank = match.group("bank")
        if len(owner) != 16 or bank is None or len(bank) != 16:
            raise Mt940BuildError(f":61: refs sin padding 16/16: {value!r}")
    return value


def _first_real(values) -> str:
    """Primer valor 'real' (no vacío / no 'NONE') de una secuencia."""
    for value in values:
        real = _real(value)
        if real:
            return real
    return ""


def owner_ref(entry: Entry) -> str:
    """Owner ref (SPEC §6.5): EndToEndId → InstrId → REF_FALLBACK.

    `NtryRef` NUNCA se usa: el banco lo construye como `<Stmt/Id>-<n>` y no
    aporta información por transacción (defecto App. A #11).
    """
    return (_first_real(td.end_to_end_id for td in entry.tx_details)
            or _first_real(td.instr_id for td in entry.tx_details)
            or config.REF_FALLBACK)


def bank_ref(entry: Entry) -> str:
    """Bank ref (SPEC §6.5): TxDtls/Refs/AcctSvcrRef → Ntry/AcctSvcrRef → fallback."""
    return (_first_real(td.acct_svcr_ref for td in entry.tx_details)
            or _real(entry.acct_svcr_ref)
            or config.REF_FALLBACK)


def build_field_61(entry: Entry, config, log, filename: str) -> str:
    """`:61:` completa: YYMMDD+MMDD+marca+importe+tipo+owner16+//bank16 (§6.5).

    Owner/bank salen de las fuentes declaradas, se truncan con WARN si exceden
    16 y se padean a 16 cuando `PAD_61_REFS` (nunca `rstrip`). `//` se emite
    siempre. Se valida con `validate_field_61` antes de devolver.
    """
    value_date = mt940_date(entry.val_dt)
    book_date = mmdd(entry.bookg_dt)
    if entry.rvsl_ind:
        marker = "R" + _marker(entry.cdt_dbt_ind)
    else:
        marker = _marker(entry.cdt_dbt_ind)
    owner = swift_charset.limit(owner_ref(entry), 16, "61: ref", log, filename)
    bank = swift_charset.limit(bank_ref(entry), 16, "61: ref banco",
                               log, filename)
    if config.PAD_61_REFS:
        owner = owner.ljust(16)
        bank = bank.ljust(16)
    line = (":61:" + value_date + book_date + marker
            + format_amount(entry.amount)
            + tx_type(entry, config, log, filename)
            + owner + "//" + bank)
    return validate_field_61(line)


def build_supplementary_line(entry: Entry, config, log, filename: str
                             ) -> tuple[str | None, str]:
    """Línea suplementaria del :61: (SPEC §6.5): `TxDtls/AddtlTxInf`.

    Devuelve `(linea, resto)`. `linea` es `AddtlTxInf` padeada a
    `SUPP_LINE_WIDTH` (o None si no hay `AddtlTxInf`). Si excede el ancho se
    corta en el último espacio ≤ancho y `resto` (lo que no cupo) se prepende
    al `:86:`: nunca se pierde texto.
    """
    raw = _first_real(td.addtl_tx_inf for td in entry.tx_details)
    if not raw:
        return None, ""
    width = config.SUPP_LINE_WIDTH
    resto = ""
    if config.PAD_61_REFS and len(raw) > width:
        cut = raw.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        resto = raw[cut:].strip()
        raw = raw[:cut].rstrip()
    linea = raw.ljust(width) if config.PAD_61_REFS else raw
    return linea, resto


def split_narrative(text: str) -> list[str]:
    """Divide la narrativa en líneas lógicas (SPEC §6.6 punto 2).

    Aplica `NARRATIVE_SPLIT_PATTERNS` en orden: `", "` (separador consumido;
    las comas de importes como `USD8,799,408.68` no llevan espacio detrás y no
    parten) y el punto cero-ancho antes de un `EXCH.RATE` pegado.
    """
    parts = [text]
    for pattern in config.NARRATIVE_SPLIT_PATTERNS:
        parts = [piece for part in parts for piece in re.split(pattern, part)]
    return [part for part in parts if part != ""]


def _wrap_tokens(text: str, width: int) -> list[str]:
    """Envuelve por tokens; un token solo >`width` se parte en duro.

    Si `text` ya cabe se devuelve intacto (conserva dobles espacios).
    """
    if len(text) <= width:
        return [text]
    lines: list[str] = []
    current = ""
    for token in text.split():
        if len(token) > width:
            if current:
                lines.append(current)
                current = ""
            lines.extend(token[i:i + width] for i in range(0, len(token), width))
            continue
        candidate = token if not current else f"{current} {token}"
        if len(candidate) > width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _wrap_parts(parts: list[str], width_first: int, width_next: int,
                max_lines: int | None) -> list[str]:
    lines: list[str] = []
    for part in parts:
        width = width_first if not lines else width_next
        for piece in _wrap_tokens(part, width):
            if max_lines is not None and len(lines) >= max_lines:
                return lines
            lines.append(":86:" + piece if not lines else piece)
    return lines


def wrap_field_86(text: str, width_first: int = 61,
                  width_next: int = 65, max_lines: int = 6) -> list[str]:
    """`:86:` físico (SPEC §6.6 punto 3): split_narrative + wrap por tokens.

    La primera línea lleva el prefijo `:86:` y ≤`width_first` de contenido;
    las continuaciones ≤`width_next`. Determinista y sin log: el overflow y el
    hard-split los registra `build_field_86`.
    """
    if not text:
        return []
    return _wrap_parts(split_narrative(text), width_first, width_next, max_lines)


def validate_field_86(lines: list[str], first_width: int | None = None,
                      next_width: int = 65,
                      max_lines: int | None = None) -> list[str]:
    """Valida el :86: físico antes de serializar (SPEC §6.6/§12.4).

    Exige: 1..`max_lines` líneas, primera con un único prefijo `:86:` y
    contenido ≤`first_width`, continuaciones ≤`next_width` y sin prefijo de tag
    ni otro `:86:` (nunca se inyecta otro campo dentro de la narrativa).
    Levanta Mt940BuildError en cualquier violación.
    """
    if first_width is None:
        first_width = config.FIELD_86_FIRST_WIDTH
    if max_lines is None:
        max_lines = config.FIELD_86_MAX_LINES
    if not lines:
        raise Mt940BuildError(":86: sin contenido")
    if len(lines) > max_lines:
        raise Mt940BuildError(
            f":86: excede {max_lines} líneas ({len(lines)})")
    if not lines[0].startswith(":86:"):
        raise Mt940BuildError(
            f":86: sin prefijo en la primera línea: {lines[0]!r}")
    if ":86:" in lines[0][4:]:
        raise Mt940BuildError(f":86: con prefijo duplicado: {lines[0]!r}")
    if len(lines[0]) - len(":86:") > first_width:
        raise Mt940BuildError(
            f"1ª línea de :86: de {len(lines[0]) - 4} > {first_width}: "
            f"{lines[0]!r}")
    for line in lines[1:]:
        if _TAG_PREFIX_RE.match(line):
            raise Mt940BuildError(
                f"continuación de :86: con prefijo de tag: {line!r}")
        if ":86:" in line:
            raise Mt940BuildError(
                f"continuación de :86: con otro :86:: {line!r}")
        if len(line) > next_width:
            raise Mt940BuildError(
                f"línea de :86: de {len(line)} > {next_width}: {line!r}")
    return lines


def build_field_86(entry: Entry, config, log, filename: str,
                   prefix: str = "") -> list[str]:
    """Líneas del :86: (≤6), validadas antes de devolver (SPEC §6.6).

    Fuente **única**: `Ntry/AddtlNtryInf` (nunca `AddtlTxInf` — va a la
    suplementaria del :61: — ni `NtryRef`/`AcctSvcrRef`/`EndToEndId`, defecto
    App. A #14). `prefix` es el resto de la suplementaria que no cupo en 34 y
    se antepone sin pérdida (§6.5). Se divide con `split_narrative` y se
    envuelve por tokens; overflow → WARN `[86_OVERFLOW]` con el texto perdido;
    token irrompible → WARN `[86_HARD_SPLIT]`.
    """
    body = (entry.addtl_ntry_inf or "").strip()
    if prefix:
        body = f"{prefix} {body}".strip() if body else prefix
    if not body:
        return []
    body = swift_charset.clean(body, log=log, filename=filename,
                               rule="charset", collapse=config.COLLAPSE_SPACES)
    if not body:
        return []
    first = config.FIELD_86_FIRST_WIDTH
    nxt = config.FIELD_86_NEXT_WIDTH
    max_lines = config.FIELD_86_MAX_LINES
    parts = split_narrative(body)
    for index, part in enumerate(parts):
        width = first if index == 0 else nxt
        if any(len(token) > width for token in part.split()):
            log.warn(filename, "86_HARD_SPLIT",
                     lost_text=f"token > {width}: {part[:40]}")
    todas = _wrap_parts(parts, first, nxt, None)
    if len(todas) > max_lines:
        perdidas = " ".join(todas[max_lines:])
        log.warn(filename, "86_OVERFLOW", lost_text=perdidas[:60])
        todas = todas[:max_lines]
    return validate_field_86(todas, first_width=first, next_width=nxt,
                             max_lines=max_lines)


def entry_delta(entry: Entry) -> Decimal:
    """Variación de saldo de una entrada (CRDT suma, DBIT resta)."""
    return entry.amount if _marker(entry.cdt_dbt_ind) == "C" else -entry.amount


def running_balance(opening: Decimal, entries: list[Entry]) -> Decimal:
    """Saldo acumulado tras aplicar las entradas."""
    return opening + sum((entry_delta(e) for e in entries), Decimal("0"))


def validate_balance(stmt: Statement, book_entries: list[Entry],
                     config, log, filename: str) -> None:
    """OPBD ± Σ:61: == CLBD (tol. 0.005); desfase → BalanceMismatchError."""
    if stmt.opening is None or stmt.closing is None:
        raise BalanceMismatchError("Faltan saldos OPBD/CLBD")
    expect = running_balance(stmt.opening.amount, book_entries)
    actual = stmt.closing.amount
    if abs(expect - actual) > Decimal("0.005"):
        raise BalanceMismatchError(
            f"saldo no cuadra: OPBD ± Σ:61: = {expect} != CLBD {actual}")
    if stmt.opening.currency != stmt.closing.currency:
        log.warn(filename, "saldo: moneda OPBD/CLBD distinta",
                 lost_text=f"{stmt.opening.currency} vs {stmt.closing.currency}")


def _warn_elementos_descartados(entries, log, filename: str) -> None:
    """Un WARN agregado por Stmt por elementos fuente que el `:86:` omite.

    El `:86:` se construye solo desde `AddtlNtryInf` (SPEC §6.6); `RmtInf/Ustrd`
    y `UETR` no se vuelcan en este perfil, así que se reportan juntos (conteo +
    elemento) para que la pérdida no sea silenciosa.
    """
    descartados: dict[str, int] = {}
    for entry in entries:
        for td in entry.tx_details:
            if _real(td.ustrd):
                descartados["RmtInf/Ustrd"] = descartados.get("RmtInf/Ustrd", 0) + 1
            if _real(td.uetr):
                descartados["UETR"] = descartados.get("UETR", 0) + 1
    if descartados:
        detalle = ", ".join(f"{name}×{count}"
                            for name, count in sorted(descartados.items()))
        log.warn(filename, "86_SOURCE_OMITTED", lost_text=detalle)


def build_statement_lines(stmt: Statement, msg_id: str, config,
                          log, filename: str) -> list[str]:
    """Bloque 4 (lista de líneas) de un Statement como mensaje único (:62F:)."""
    book_entries = [e for e in stmt.entries if e.sts == "BOOK"]
    for e in stmt.entries:
        if e.sts != "BOOK":
            log.warn(filename, "NO-BOOK",
                     lost_text=f"entrada {e.ntry_ref or e.acct_svcr_ref} ({e.sts})")

    validate_balance(stmt, book_entries, config, log, filename)

    _warn_elementos_descartados(book_entries, log, filename)

    lines = [":20:" + ref20(stmt.stmt_id, msg_id, log, filename)]
    lines.append(":25:" + swift_charset.limit(stmt.account, 35,
                                              "25: cuenta", log, filename))
    # :28C: = LglSeqNb/segundo; el segundo arranca en StmtPgntn/PgNb (SPEC §6.3)
    # y solo avanza (+1 por mensaje) cuando el splitter parte el Statement.
    lines.append(f":28C:{_pad5(stmt.lgl_seq_nb)}/{_pad5(stmt.pg_nb)}")
    if stmt.opening is not None:
        lines.append(balance_line("60F", stmt.opening, config, log, filename))

    for entry in book_entries:
        lines.append(build_field_61(entry, config, log, filename))
        suplementaria, resto = build_supplementary_line(entry, config, log,
                                                        filename)
        if suplementaria is not None:
            lines.append(suplementaria)
        elif not _real(entry.addtl_ntry_inf):
            log.info(filename, "61: sin narrativa",
                     f"entrada {entry.ntry_ref or entry.acct_svcr_ref}")
        lines.extend(build_field_86(entry, config, log, filename, prefix=resto))

    if stmt.closing is not None:
        lines.append(balance_line("62F", stmt.closing, config, log, filename))
    if stmt.avail is not None:
        lines.append(balance_line("64", stmt.avail, config, log, filename))
    return lines


def _validate_block4(lines: list[str]) -> None:
    """Compuerta final: revalida :61: y grupos :86: antes de serializar.

    Los `build_field_*` ya validan al construir; esto cubre líneas que
    lleguen de otro lado (p. ej. chunks del splitter) para que nunca se
    emita salida inválida (SPEC §12.4).
    """
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(":61:"):
            validate_field_61(line)
        elif line.startswith(":86:"):
            group = [line]
            index += 1
            while index < len(lines) and not _TAG_PREFIX_RE.match(lines[index]):
                group.append(lines[index])
                index += 1
            validate_field_86(group)
            continue
        index += 1


def wrap_message(lines: list[str], config, reference: str,
                 in_time: str, in_date: str, out_date: str, out_time: str,
                 eol: str = "\r\n", sender_lt: str | None = None,
                 receiver_address: str | None = None) -> str:
    """Envuelve las líneas del bloque 4 en un mensaje MT940 (SPEC §6.2/§11).

    Perfil FIN (default): montado solo desde los templates de config —
    BLOCK1 (si BLOCK1_ENABLED) + BLOCK2 validado en `config.build_block2`
    (template/parámetros leídos de config en tiempo de llamada: cambiarlos
    no requiere reescribir este código) + BLOCK3 (si BLOCK3_ENABLED) +
    BLOCK4_OPEN + líneas a columna 0 separadas por CRLF + BLOCK4_CLOSE +
    BLOCK5 (si BLOCK5_ENABLED). in_time/in_date/out_date/out_time solo los
    usa el perfil legado. Devuelve el mensaje sin salto final ni `$`.
    """
    _validate_block4(lines)
    if getattr(config, "PROFILE", "fin") == "legacy":
        return _wrap_legacy(lines, config, reference, in_time, in_date,
                            out_date, out_time, eol)
    block4 = (config.BLOCK4_OPEN.replace("\n", eol)
              + eol.join(lines) + eol + config.BLOCK4_CLOSE)
    message = ""
    if config.BLOCK1_ENABLED:
        message += config.build_block1(
            sender_lt=sender_lt or config.SENDER_LT)
    if config.BLOCK2_ENABLED:
        message += config.build_block2(
            msg_type=config.MSG_TYPE,
            receiver_address=receiver_address or config.RECEIVER_ADDRESS,
            priority=config.PRIORITY,
            monitoring=config.MONITORING,
            obsolescence=config.OBSOLESCENCE,
            template=config.BLOCK2_TEMPLATE)
    if config.BLOCK3_ENABLED:
        message += config.block3(reference)
    message += block4
    if config.BLOCK5_ENABLED:
        message += config.block5(config.CHK_PLACEHOLDER)
    return message


def _wrap_legacy(lines: list[str], config, reference: str,
                 in_time: str, in_date: str, out_date: str, out_time: str,
                 eol: str) -> str:
    """Envoltura del perfil legado del banco (referencia real de Salida).

    Wrapper F21 + bloques 1/2('0940')/3 pegados, tags con 1 espacio y
    continuaciones :86: sin prefijo, cierre `-}` + bloque 5 según
    LEGACY_BLOCK5_ENABLED.
    """
    spaced = [" " + line if line.startswith(":") else line for line in lines]
    block4 = (config.BLOCK4_OPEN.replace("\n", eol)
              + eol.join(spaced) + eol + config.BLOCK4_CLOSE)
    message = (config.block0_wrap(out_date, out_time)
               + config.block1()
               + config.block2(in_time, in_date, out_date, out_time)
               + config.block3(reference)
               + block4)
    if config.LEGACY_BLOCK5_ENABLED:
        message += config.block5()
    return message


def join_messages(messages: list[str], separator: str | None = None,
                  eol: str | None = None,
                  final_eol: bool | None = None) -> str:
    """Une varios mensajes según SPEC §6.3-C.

    Regla: `m₁ + EOL + "$" + m₂ + EOL + "$" + … + mₙ + EOL`. El `$` queda a
    columna 0 de la línea siguiente a `-}` y el archivo cierra con `-}` + EOL
    (salvo `final_eol=False`). Sin mensajes devuelve "".
    """
    if not messages:
        return ""
    separator = config.MSG_SEPARATOR if separator is None else separator
    eol = config.EOL if eol is None else eol
    if final_eol is None:
        final_eol = config.FILE_FINAL_EOL
    joined = (eol + separator).join(messages)
    return joined + eol if final_eol else joined