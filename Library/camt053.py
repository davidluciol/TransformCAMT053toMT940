# -*- coding: utf-8 -*-
"""Parser de estados CAMT.053 (ISO 20022) → modelo tipado.

Detección por contenido (no por extensión): parsea el XML, busca
`BkToCstmrStmt` por local-name (agnóstico de namespaces) y soporta tanto el
documento plano como el Envelope SWIFT (`Envelope/Document`). Cualquier
entrada que no sea XML válido o no contenga CAMT levanta CamtParseError.

Los textos se guardan crudos (sin sanear); el armado MT940 se encarga de
limpieza/truncado (mt940_builder + swift_charset).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET


class CamtParseError(Exception):
    """Error al detectar o parsear un CAMT.053."""


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Balance:
    code: str            # OPBD, CLBD, CLAV, ITBD...
    amount: Decimal
    currency: str
    cdt_dbt_ind: str     # CRDT / DBIT
    date: str            # texto crudo (p. ej. "2026-08-31")


@dataclass(frozen=True)
class TxDetails:
    instr_id: str = ""
    end_to_end_id: str = ""
    uetr: str = ""
    ustrd: str = ""          # RmtInf/Ustrd (remesa no estructurada)
    addtl_tx_inf: str = ""
    acct_svcr_ref: str = ""  # Refs/AcctSvcrRef (fuente 1 del :61: bank ref)


@dataclass(frozen=True)
class Entry:
    amount: Decimal
    amount_ccy: str
    cdt_dbt_ind: str         # CRDT / DBIT
    sts: str                 # BOOK, PDNG, INFO...
    bookg_dt: str
    val_dt: str
    rvsl_ind: bool
    ntry_ref: str
    acct_svcr_ref: str
    tx_code: str             # BkTxCd Prtry/Cd (o Domn/Cd)
    tx_issr: str
    tx_details: tuple[TxDetails, ...]
    addtl_ntry_inf: str


@dataclass(frozen=True)
class Statement:
    stmt_id: str
    elctrnc_seq_nb: str
    lgl_seq_nb: str
    pg_nb: str
    last_pg_ind: str
    account: str             # IBAN o Othr/Id
    ccy: str
    opening: Balance | None  # OPBD
    closing: Balance | None  # CLBD
    avail: Balance | None    # CLAV (opcional)
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class CamtDocument:
    msg_id: str
    statements: tuple[Statement, ...]
    apphdr_fr_bic: str = ""   # AppHdr/Fr/FIId/FinInstnId/BICFI (SPEC §6.2)
    apphdr_to_bic: str = ""   # AppHdr/To/FIId/FinInstnId/BICFI


# ---------------------------------------------------------------------------
# Helpers XML por local-name
# ---------------------------------------------------------------------------

def _local_name(tag: str) -> str:
    return tag.split('}')[-1] if '}' in tag else tag


def _children(parent, name: str) -> list:
    if parent is None:
        return []
    return [c for c in parent if _local_name(c.tag) == name]


def _child(parent, name: str):
    if parent is None:
        return None
    for c in parent:
        if _local_name(c.tag) == name:
            return c
    return None


def _descendants(parent, name: str) -> list:
    return [n for n in parent.iter() if _local_name(n.tag) == name]


def _text(node) -> str:
    if node is None or node.text is None:
        return ''
    return node.text.strip()


def _node_text(parent, name: str) -> str:
    return _text(_child(parent, name))


def _pick_text(parent, *names: str) -> str:
    """Primer texto no vacío entre los hijos de parent llamados names."""
    if parent is None:
        return ''
    for name in names:
        value = _node_text(parent, name)
        if value:
            return value
    return ''


def _parse_amount(text: str) -> Decimal:
    text = (text or '').strip()
    if not text:
        raise CamtParseError("Importe vacío")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise CamtParseError(f"Importe inválido '{text}'") from exc


# ---------------------------------------------------------------------------
# Parseo de nodos
# ---------------------------------------------------------------------------

def _parse_balance(bal_node) -> Balance:
    tp = _child(bal_node, 'Tp')
    cdp = _child(tp, 'CdOrPrtry') if tp is not None else None
    code = _pick_text(cdp, 'Cd', 'Prtry')
    amt_node = _child(bal_node, 'Amt')
    amount = _parse_amount(_text(amt_node))
    currency = (amt_node.attrib.get('Ccy') or '').upper() if amt_node is not None else ''
    cdt = _node_text(bal_node, 'CdtDbtInd')
    dt_node = _child(bal_node, 'Dt')
    date = _pick_text(dt_node, 'Dt', 'DtTm')
    return Balance(code=code, amount=amount, currency=currency,
                   cdt_dbt_ind=cdt, date=date)


def _parse_tx_details(node) -> TxDetails:
    refs = _child(node, 'Refs')
    rmt = _child(node, 'RmtInf')
    addtl = ' '.join(_text(a) for a in _children(node, 'AddtlTxInf'))
    return TxDetails(
        instr_id=_node_text(refs, 'InstrId') if refs is not None else '',
        end_to_end_id=_node_text(refs, 'EndToEndId') if refs is not None else '',
        uetr=_node_text(refs, 'UETR') if refs is not None else '',
        ustrd=_node_text(rmt, 'Ustrd') if rmt is not None else '',
        addtl_tx_inf=addtl,
        acct_svcr_ref=_node_text(refs, 'AcctSvcrRef') if refs is not None else '',
    )


def _bk_tx_cd(bk_node) -> tuple[str, str]:
    """BkTxCd → (código, emisor): Prtry (Cd + Issr) o Domn (Cd)."""
    if bk_node is None:
        return '', ''
    pr = _child(bk_node, 'Prtry')
    if pr is not None:
        return _node_text(pr, 'Cd'), _node_text(pr, 'Issr')
    dm = _child(bk_node, 'Domn')
    if dm is not None:
        return _node_text(dm, 'Cd'), ''
    return '', ''


def _parse_entry(node) -> Entry:
    amt_node = _child(node, 'Amt')
    amount = _parse_amount(_text(amt_node))
    ccy = (amt_node.attrib.get('Ccy') or '').upper() if amt_node is not None else ''
    sts_node = _child(node, 'Sts')
    sts = _pick_text(sts_node, 'Cd', 'Prtry')

    bookg = _child(node, 'BookgDt')
    bookg_dt = _pick_text(bookg, 'Dt', 'DtTm')
    val = _child(node, 'ValDt')
    val_dt = _pick_text(val, 'Dt', 'DtTm')

    rvsl = _node_text(node, 'RvslInd').lower() == 'true'

    tx_code, tx_issr = _bk_tx_cd(_child(node, 'BkTxCd'))
    if not tx_code:
        for nd in _children(node, 'NtryDtls'):
            for td in _children(nd, 'TxDtls'):
                refs = _child(td, 'Refs')
                code, issr = _bk_tx_cd(_child(td, 'BkTxCd')
                                       or _child(refs, 'BkTxCd'))
                if code:
                    tx_code, tx_issr = code, issr
                    break
            if tx_code:
                break

    tx_details = tuple(
        _parse_tx_details(td)
        for nd in _children(node, 'NtryDtls')
        for td in _children(nd, 'TxDtls')
    )
    addtl_ntry = ' '.join(_text(a) for a in _children(node, 'AddtlNtryInf'))

    return Entry(
        amount=amount,
        amount_ccy=ccy,
        cdt_dbt_ind=_node_text(node, 'CdtDbtInd'),
        sts=sts,
        bookg_dt=bookg_dt,
        val_dt=val_dt,
        rvsl_ind=rvsl,
        ntry_ref=_node_text(node, 'NtryRef'),
        acct_svcr_ref=_node_text(node, 'AcctSvcrRef'),
        tx_code=tx_code,
        tx_issr=tx_issr,
        tx_details=tx_details,
        addtl_ntry_inf=addtl_ntry,
    )


def _account_identification(acct_node) -> str:
    if acct_node is None:
        return ''
    acc_id = _child(acct_node, 'Id')
    if acc_id is None:
        return ''
    iban = _node_text(acc_id, 'IBAN')
    if iban:
        return iban
    othr = _child(acc_id, 'Othr')
    return _node_text(othr, 'Id') if othr is not None else ''


def _parse_statement(node) -> Statement:
    pg = _child(node, 'StmtPgntn')
    acct_node = _child(node, 'Acct')

    balances = {b.code.lower(): b for b in (_parse_balance(n) for n in _children(node, 'Bal'))}

    return Statement(
        stmt_id=_node_text(node, 'Id'),
        elctrnc_seq_nb=_node_text(node, 'ElctrncSeqNb'),
        lgl_seq_nb=_node_text(node, 'LglSeqNb'),
        pg_nb=_node_text(pg, 'PgNb') if pg is not None else '',
        last_pg_ind=_node_text(pg, 'LastPgInd') if pg is not None else '',
        account=_account_identification(acct_node),
        ccy=_node_text(acct_node, 'Ccy') or 'XXX',
        opening=balances.get('opbd'),
        # Una página intermedia (LastPgInd=false) no trae CLBD: se usa ITBD
        # como saldo de cierre para no perder la página (SPEC §13.9).
        closing=balances.get('clbd') or balances.get('itbd'),
        avail=balances.get('clav'),
        entries=tuple(_parse_entry(n) for n in _children(node, 'Ntry')),
    )


# ---------------------------------------------------------------------------
# Entrada pública
# ---------------------------------------------------------------------------

def _apphdr_bics(root) -> tuple[str, str]:
    """BICFI de AppHdr/Fr y AppHdr/To del Envelope (o ('', '') si no hay)."""
    apphdr = _child(root, 'AppHdr')
    if apphdr is None:
        return '', ''

    def _bic(side: str) -> str:
        fiid = _child(_child(apphdr, side), 'FIId')
        fin = _child(fiid, 'FinInstnId')
        return _node_text(fin, 'BICFI') if fin is not None else ''

    return _bic('Fr'), _bic('To')


def parse_document(data: str) -> CamtDocument:
    """Parsea XML CAMT.053 (con o sin Envelope) a un CamtDocument tipado."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CamtParseError(f"XML inválido: {exc}") from exc

    bk_nodes = _descendants(root, 'BkToCstmrStmt')
    if not bk_nodes:
        raise CamtParseError("No es un CAMT.053 (no se encontró BkToCstmrStmt)")

    msg_ids = [_text(n) for n in _descendants(root, 'MsgId')]
    msg_id = msg_ids[0] if msg_ids else ''
    apphdr_fr, apphdr_to = _apphdr_bics(root)

    statements = tuple(
        _parse_statement(stmt)
        for bk in bk_nodes
        for stmt in _children(bk, 'Stmt')
    )
    if not statements:
        raise CamtParseError("BkToCstmrStmt sin Stmt")

    return CamtDocument(msg_id=msg_id, statements=statements,
                        apphdr_fr_bic=apphdr_fr, apphdr_to_bic=apphdr_to)