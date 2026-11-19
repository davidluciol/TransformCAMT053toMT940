# -*- coding: utf-8 -*-
"""Configuración central del convertidor CAMT.053 → MT940.

Dos perfiles de envoltura (SPEC §6.2/§11):

- Perfil FIN validable (default): el que consume el gateway de carga —
  `{1:F01…}{2:I940…}{4:` + tags a columna 0 + CRLF, bloques 3/5 OFF.
  Toda la estructura vive en templates (`BLOCKn_TEMPLATE`); nada de
  cabecera/cierre queda hard-coded en el builder.
- Perfil legado del banco: wrapper F21 + `{177:}`/`{451:0}` + bloque 2 con
  prefijo `0940` + bloques 3/5 ON. Se conserva como referencia histórica;
  el archivo de salida del banco no se incluye en el repositorio.

Solo varían en tiempo de ejecución fecha/hora/ref/seq/counter; el resto es
fijo y ajustable aquí.
"""

from __future__ import annotations

import re


class Mt940BuildError(Exception):
    """Error de armado del contenido MT940 (régimen ERROR del RunLog)."""


# ---------------------------------------------------------------------------
# Selección de perfil de envoltura (SPEC §11)
# ---------------------------------------------------------------------------
# "fin" = perfil FIN validable por el gateway (default): {1:F01…}{2:I940…}{4:}
#        con tags a columna 0 + CRLF y bloques 3/5 OFF.
# "legacy" = perfil legado del banco (referencia histórica del banco):
#        wrapper F21 + {177:}/{451:0} + bloque 2 '0940' + {3:{108:}} + tags con
#        1 espacio + bloque 5 según LEGACY_BLOCK5_ENABLED.
PROFILE = "fin"

# ---------------------------------------------------------------------------
# Identificación (verbatim del banco)
# ---------------------------------------------------------------------------
SENDER_LT = "DEMOBKMMAXXX"    # LT del BIC emisor (bloques 1 y wrapper F21)
RECEIVER_LT = "DEMOLGCYQXXX"  # LT del BIC destinatario (bloque 2 legado)
SESSION_ISN = "0123456789"    # sesión + número de secuencia del banco (bloque 2 legado)
PRIORITY = "N"                # prioridad del mensaje

# ---------------------------------------------------------------------------
# Perfil FIN validable por el gateway (default, SPEC §6.2/§11)
# ---------------------------------------------------------------------------
# BIC dinámico del gateway: cambiarlo aquí no requiere reescribir código.
# Validación del Input-header (build_block2, SPEC §6.2): 12 chars con el LT
# code 'X' en la posición 9 (1-indexada) = índice 8 (0-indexada). La cumplen
# DEMORCVGXXXX y DEMOLGCYXXXX; NUNCA DEMORCVGAXXX/DEMOLGCYQXXX (App. A #1).
HEADER_SOURCE = "config"      # "config" | "apphdr" (deriva los LT del Envelope)
SENDER_LT_CODE = "A"          # insertado tras el BIC8 de AppHdr/Fr
RECEIVER_LT_CODE = "X"        # insertado tras el BIC8 de AppHdr/To
RECEIVER_ADDRESS = "DEMORCVGXXXX"
MSG_TYPE = "940"
MONITORING = ""               # SPEC §6.2 DELIVERY_MONITORING: el golden lo omite
OBSOLESCENCE = ""             # SPEC §6.2: el golden lo omite (el proyecto emitía "003")
SYS_SEQ = "0000000000"        # default del perfil nuevo (muestra corregida del gateway)

BLOCK1_ENABLED = True
BLOCK1_TEMPLATE = "{1:F01{SENDER_LT}{SYS_SEQ}}"
BLOCK2_ENABLED = True
BLOCK2_TEMPLATE = "{2:I{MSG_TYPE}{RECEIVER_ADDRESS}{PRIORITY}{MONITORING}{OBSOLESCENCE}}"
BLOCK3_ENABLED = False        # OFF por defecto en el perfil del gateway (SPEC §11)
BLOCK3_TEMPLATE = "{3:{108:{REFERENCE}}}"
BLOCK5_ENABLED = False        # OFF por defecto en el perfil del gateway (SPEC §11)
BLOCK5_TEMPLATE = "{5:{CHK:{CHK}}{DLM:}}{S:{COP:P}}"
CHK_PLACEHOLDER = "A1B2C3D4E5F6"      # valor fijo si el bloque 5 está activo

# ---------------------------------------------------------------------------
# Perfil legado del banco (referencia histórica del banco)
# ---------------------------------------------------------------------------
LEGACY_SYS_SEQ = "1234567890"         # secuencia de sistema del ejemplo real
LEGACY_BLOCK5_ENABLED = True          # el perfil legado sí emite {5:...}/{S:...}
LEGACY_BLOCK0_TEMPLATE = (
    "{1:F21{SENDER_LT}{SYS_SEQ}}"
    "{4:{177:{OUT_DATE}{OUT_TIME}}{451:0}}"
)
LEGACY_BLOCK2_TEMPLATE = (
    "{2:0940{IN_TIME}{IN_DATE}{RECEIVER_LT}{SESSION_ISN}"
    "{OUT_DATE}{OUT_TIME}01{PRIORITY}}"
)

# ---------------------------------------------------------------------------
# Límites y opciones de ensamblado
# ---------------------------------------------------------------------------
# --- Paginado por conteo (SPEC §6.3-B/D) ---
# PAGING_ENABLED = True  → cada mensaje MT940 lleva como máximo ENTRIES_PER_MESSAGE
#                          movimientos (:61:); el último lleva el resto.
# PAGING_ENABLED = False → un solo mensaje por Statement (solo corta el tope de
#                          MAX_BLOCK4_CHARS como red de seguridad).
PAGING_ENABLED = True
ENTRIES_PER_MESSAGE = 3       # N de movimientos por bloque; entero >= 1
# "single_file": todos los mensajes del CAMT en UN archivo unidos con `$` (golden).
# "split_files": legado — un chunk que cierra en :62M: abre archivo `_2`, `_3`, ...
OUTPUT_MODE = "single_file"
# Paso de :20: entre mensajes de un mismo Statement (anchor_last, SPEC §6.4):
# el último mensaje conserva Stmt/Id; el k-ésimo resta (N-k)*PAGE_REF20_STEP.
PAGE_REF20_STEP = 2001

MAX_BLOCK4_CHARS = 9800       # tope del bloque 4 antes de dividir el mensaje
SPLIT_RESERVE_CHARS = 120     # margen para :62M:/:64: + "-}" al cortar (SPEC §6.2)
# --- :86: (SPEC §6.6) ---
FIELD_86_FIRST_WIDTH = 61     # contenido de la 1ª línea (65 con ":86:")
FIELD_86_NEXT_WIDTH = 65      # ancho de las continuaciones
FIELD_86_MAX_LINES = 6
NARRATIVE_SPLIT_PATTERNS = (r",\s+", r"(?<=\S)(?=EXCH\.RATE)")
COLLAPSE_SPACES = False       # SPEC §6.6/App. A #17: "0011  CCN…" se conserva
MSG_SEPARATOR = "$"            # separador entre mensajes MT940 en un archivo
EOL = "\r\n"                   # SPEC §6.2/§6.9: los MT940 del banco son CRLF
FILE_FINAL_EOL = True          # SPEC §6.3-C/§6.9: el archivo cierra con "-}" + EOL
PROCESSED_DIRNAME = "Procesados"  # carpeta de originales convertidos
OUT_EXTENSION = ".txt"
# --- Nombre de salida (SPEC §6.3-C) ---
# Tope del nombre de archivo (con extensión). SWIFT rechaza > 32 chars; si
# `<original>_<ddMMyyyy>.txt` lo excede, se compacta a
# `<BIC8>_<YYMMDD transacción>_<ddMMyy corrida>.txt`.
FILENAME_MAX_CHARS = 32
COMPACT_BIC_WIDTH = 8         # ancho del BIC destino en el nombre compacto

# --- Tipo de transacción en :61: (1!a3!c) ---
# Clave: BkTxCd/Domn/Cd → código MT940. Si el código viene de Prtry y ya es
# alfanumérico de 4 chars se usa directo; si no hay mapeo posible → NMSC + WARN.
TX_TYPE_MAP = {}
FALLBACK_TX_CODE = "NMSC"

# --- :61: Statement Line + suplementaria (SPEC §6.5) ---
PAD_61_REFS = True            # owner/bank a 16, suplementaria a 34
OWNER_REF_SOURCES = ("EndToEndId", "InstrId")     # NtryRef NUNCA (§6.5)
BANK_REF_SOURCES = ("TxDtls/Refs/AcctSvcrRef", "Ntry/AcctSvcrRef")
REF_FALLBACK = "NONE"
SUPP_LINE_WIDTH = 34

# ---------------------------------------------------------------------------
# Bloque 4 (común a ambos perfiles)
# ---------------------------------------------------------------------------
BLOCK4_OPEN = "{4:\n"
BLOCK4_TAG = ":{tag}:{value}"
BLOCK4_CLOSE = "-}"

def resolve_page_size(enabled=None, entries=None):
    """Tamaño de página efectivo: N si el paginado está encendido, None si no.

    Lee la config en tiempo de llamada (igual que el resto de los límites).
    `enabled` debe ser bool y `entries` un entero >= 1 (no bool); si no,
    levanta Mt940BuildError antes de procesar nada.
    """
    enabled = PAGING_ENABLED if enabled is None else enabled
    entries = ENTRIES_PER_MESSAGE if entries is None else entries
    if not isinstance(enabled, bool):
        raise Mt940BuildError(
            f"PAGING_ENABLED inválido {enabled!r}: debe ser True o False")
    if not enabled:
        return None
    if isinstance(entries, bool) or not isinstance(entries, int) or entries < 1:
        raise Mt940BuildError(
            f"ENTRIES_PER_MESSAGE inválido {entries!r}: debe ser un entero >= 1")
    return entries


_PLACEHOLDER_RE = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")

# Regex de referencia de los headers FIN (SPEC §6.2). El bloque 1 es
# F01 + LT(12) + sesión+secuencia(10); el bloque 2 es un Input-header con el
# LT 'X' en la posición 9 (índice 8).
BLOCK1_RE = re.compile(r"^\{1:F01[A-Z0-9]{12}[0-9]{10}\}$")
BLOCK2_RE = re.compile(
    r"^\{2:I[0-9]{3}[A-Z0-9]{8}X[A-Z0-9]{3}[SUN]?([123]([0-9]{3})?)?\}$")


def resolve_template(template: str, **variables: str) -> str:
    """Resuelve los placeholders `{NOMBRE}` de un template de bloque.

    Solo sustituye los nombres presentes en `variables`; las llaves literales
    (`{1:`, `{108:`, `}}`, …) quedan intactas.
    """
    def _replace(match: re.Match) -> str:
        return variables.get(match.group(1), match.group(0))
    return _PLACEHOLDER_RE.sub(_replace, template)


def validate_receiver_address(receiver_address: str) -> None:
    """Valida el BIC destinatario del Input-header antes de serializar.

    Regla del gateway (SPEC §6.2, regex `[A-Z0-9]{8}X[A-Z0-9]{3}`): 12
    caracteres con el LT code 'X' en la posición 9 (1-indexada) = índice 8
    (0-indexada). Así `DEMORCVGXXXX` es válido y `DEMORCVGAXXX` /
    `DEMOLGCYQXXX` se rechazan (App. A #1). Una violación levanta
    Mt940BuildError.
    """
    if len(receiver_address) != 12:
        raise Mt940BuildError(
            f"RECEIVER_ADDRESS inválido '{receiver_address}': "
            "debe tener 12 caracteres")
    if receiver_address[8] != "X":
        raise Mt940BuildError(
            f"RECEIVER_ADDRESS inválido '{receiver_address}': "
            "el LT code (posición 9, índice 8) debe ser 'X'")


def build_block2(msg_type: str = MSG_TYPE,
                 receiver_address: str = RECEIVER_ADDRESS,
                 priority: str = PRIORITY,
                 monitoring: str = MONITORING,
                 obsolescence: str = OBSOLESCENCE,
                 template: str = BLOCK2_TEMPLATE) -> str:
    """Construye y valida el bloque 2 (Input-header) del perfil FIN.

    Valida ANTES de serializar (SPEC §6.2/§12.4): el RECEIVER_ADDRESS
    configurado (12 chars + 'X' en índice 8), que el template resuelto sea
    un Input-header `{2:I…}` (nunca un layout de salida `{2:O…}`) y que no
    queden placeholders sin resolver. Cambiar el template o el destinatario
    por config no requiere reescribir el builder. Una violación levanta
    Mt940BuildError.
    """
    validate_receiver_address(receiver_address)
    block = resolve_template(template,
                             MSG_TYPE=msg_type,
                             RECEIVER_ADDRESS=receiver_address,
                             PRIORITY=priority,
                             MONITORING=monitoring,
                             OBSOLESCENCE=obsolescence)
    if not block.startswith("{2:I"):
        raise Mt940BuildError(
            f"Bloque 2 inválido '{block}': el Input-header debe empezar "
            "por '{2:I' (no es un layout de salida)")
    leftover = _PLACEHOLDER_RE.search(block)
    if leftover:
        raise Mt940BuildError(
            f"Bloque 2 con placeholder sin resolver '{leftover.group(0)}'")
    if not BLOCK2_RE.fullmatch(block):
        raise Mt940BuildError(
            f"Bloque 2 inválido '{block}': no cumple {BLOCK2_RE.pattern}")
    return block


def build_block1(sender_lt: str = SENDER_LT, sys_seq: str = SYS_SEQ,
                 template: str = BLOCK1_TEMPLATE) -> str:
    """Construye y valida el bloque 1 (Basic header) del perfil FIN.

    Valida ANTES de serializar (SPEC §6.2/§12.4): el render debe cumplir
    `BLOCK1_RE` (F01 + LT(12) + 10 dígitos) y no dejar placeholders sin
    resolver. Cambiar el template o los valores por config no requiere
    reescribir el builder. Una violación levanta Mt940BuildError.
    """
    block = resolve_template(template, SENDER_LT=sender_lt, SYS_SEQ=sys_seq)
    leftover = _PLACEHOLDER_RE.search(block)
    if leftover:
        raise Mt940BuildError(
            f"Bloque 1 con placeholder sin resolver '{leftover.group(0)}'")
    if not BLOCK1_RE.fullmatch(block):
        raise Mt940BuildError(
            f"Bloque 1 inválido '{block}': no cumple {BLOCK1_RE.pattern}")
    return block


def _derive_lt(bicfi: str, lt_code: str) -> str:
    """Inserta el LT code tras el BIC8 (SPEC §6.2): `BICFI[:8]+LT+BICFI[8:]`."""
    if not bicfi:
        return ""
    return bicfi[:8] + lt_code + bicfi[8:]


def resolve_header_values(apphdr_fr: str = "", apphdr_to: str = "",
                          log=None, filename: str = "") -> tuple[str, str]:
    """`(sender_lt, receiver_address)` efectivos según `HEADER_SOURCE` (§6.2).

    Con `"config"` (default) devuelve los valores de config. Con `"apphdr"`
    deriva los LT del `AppHdr/Fr`/`AppHdr/To` del Envelope; si falta el
    AppHdr (CAMT plano) cae a config, y si el valor derivado difiere del de
    config registra un `INFO`.
    """
    sender, receiver = SENDER_LT, RECEIVER_ADDRESS
    if HEADER_SOURCE != "apphdr":
        return sender, receiver
    fr = _derive_lt(apphdr_fr, SENDER_LT_CODE)
    to = _derive_lt(apphdr_to, RECEIVER_LT_CODE)
    if log is not None:
        if fr and fr != sender:
            log.info(filename, "apphdr", f"Fr {fr} != config {sender}")
        if to and to != receiver:
            log.info(filename, "apphdr", f"To {to} != config {receiver}")
    return fr or sender, to or receiver


# ---------------------------------------------------------------------------
# Helpers del perfil legado (re-expresados sobre templates)
# ---------------------------------------------------------------------------
def block0_wrap(out_date: str, out_time: str,
                sender_lt: str = SENDER_LT,
                sys_seq: str = LEGACY_SYS_SEQ) -> str:
    """Wrapper F21 + reseña de sistema ({177:...}{451:0}) del perfil legado."""
    return resolve_template(LEGACY_BLOCK0_TEMPLATE,
                            SENDER_LT=sender_lt, SYS_SEQ=sys_seq,
                            OUT_DATE=out_date, OUT_TIME=out_time)


def block1(sender_lt: str = SENDER_LT,
           sys_seq: str = LEGACY_SYS_SEQ) -> str:
    """Bloque 1 SWIFT."""
    return resolve_template(BLOCK1_TEMPLATE,
                            SENDER_LT=sender_lt, SYS_SEQ=sys_seq)


def block2(in_time: str, in_date: str, out_date: str, out_time: str,
           receiver_lt: str = RECEIVER_LT, session_isn: str = SESSION_ISN,
           priority: str = PRIORITY) -> str:
    """Bloque 2 de salida del perfil legado (prefijo fijo '0940')."""
    return resolve_template(LEGACY_BLOCK2_TEMPLATE,
                            IN_TIME=in_time, IN_DATE=in_date,
                            RECEIVER_LT=receiver_lt,
                            SESSION_ISN=session_isn,
                            OUT_DATE=out_date, OUT_TIME=out_time,
                            PRIORITY=priority)


def block3(reference: str) -> str:
    """Bloque 3 ({108:}) con la referencia del mensaje."""
    return resolve_template(BLOCK3_TEMPLATE, REFERENCE=reference)


def block5(chk: str = CHK_PLACEHOLDER) -> str:
    """Bloque 5: {CHK:}{DLM:} + cierre {S:{COP:P}}. Valor de CHK configurable."""
    return resolve_template(BLOCK5_TEMPLATE, CHK=chk)
