# SPEC — CAMT.053 → MT940 Converter (v2.2 · profile `GOLDEN_940`)

> **v2.2 — 2026-10-04.** Adds **dynamic paging** (§6.3-D): the 3-entries-per-message layout is now a **config.py switch** (`PAGING_ENABLED` + `ENTRIES_PER_MESSAGE`), not a fixed behaviour. Also fixes the `:20:` consistency check for page sizes ≠ 3 (§6.4).
>
> **v2.1 — 2026-10-01.** Supersedes v2. Built from four artifacts:
> - `test_camt053` — real CAMT.053.001.08 (SWIFT Envelope, 1 `Stmt`, 34 `Ntry`) → **source structure**.
> - `test_camt053_01102026.txt` — what the project generated from it (rejected shape).
> - `finalExample.TXT` — MT940 known to be **accepted by the SWIFT upload path** (*golden*; its CAMT is not available, assumed structurally identical to `test_camt053`).
> - `test_camt053_expected_MT940.TXT` — target for `test_camt053` (12 messages: 11×3 + 1 entries). **[VERIFIED v2.2 by script]** CRLF, 34 entries in the same order as the project output, `:60:`/`:62:` chain reconciles in all 12 messages, `:20:` step 2001, `:28C:` `01565/00001…00012`. Not yet gateway-accepted (13-3).
>
> Facts are tagged **[VERIFIED]** (observed in the files, or reproduced by a prototype that reconciles balances)
> or **[INFERRED]** (hypothesis; see §13). Appendix A lists every difference and its root cause.

## 0. Scope

One batch converter. Build order: `config` → `swift_charset` → `camt053` → `mt940_builder` → `runlog` → `mt940_splitter` → `camt_to_mt940`.

## 1. Objective

Convert CAMT.053 (`.001.02/.08/.10/.11`, plain or SWIFT Envelope) into **profile-valid MT940**, preserving information and logging every loss.
Separate generic FIN/MT syntax (always applies) from bank/channel-specific rules (profile `GOLDEN_940`, configurable).

**Paging is a config switch** (§6.3-D): `PAGING_ENABLED` turns count paging on/off and `ENTRIES_PER_MESSAGE` (N) sets the entries per block, so the same CAMT converts both as one block (`PAGING_ENABLED = False`, the shape of the rejected `test_camt053_01102026.txt`) and in blocks of N (`True`, N = 3 in `GOLDEN_940`) without touching code.

**Acceptance reference** (with the profile defaults `PAGING_ENABLED = True`, `ENTRIES_PER_MESSAGE = 3`): for the same logical content, output must be **structurally identical** to the golden file
(same blocks, entries per message, field layout, padding, separators, line endings). Where this SPEC and the golden
disagree, the golden wins until a real upload proves otherwise.

## 2. Tech Stack

Python 3.9+, standard library only: `xml.etree.ElementTree`, `decimal`, `datetime`, `re`, `hashlib`, `unicodedata`, `pathlib`, `argparse`, `unittest`. UTF-8 without BOM (output is plain ASCII after charset filtering).

## 3. Commands

```text
python camt_to_mt940.py -i "<input>" -o "<output>"
python -m unittest discover -s tests -v
```

Paging is controlled in `Library/config.py` (`PAGING_ENABLED`, `ENTRIES_PER_MESSAGE`, §6.3-D); there are no paging CLI options.

## 4. Project Structure

```text
CAMTtoMT/
├── SPEC.md / camt_to_mt940.py
├── Library/{config,camt053,swift_charset,mt940_builder,mt940_splitter,runlog}.py
├── tests/
│   ├── fixtures/
│   │   ├── plain/  envelope/  synthetic_over_limit/
│   │   ├── rejected/test_camt053_01102026.txt    (project output, rejected: 1 message × 34 entries)
│   │   └── golden/
│   │       ├── finalExample.TXT                  (accepted by gateway)
│   │       ├── test_camt053.xml                  (real CAMT, 34 entries)
│   │       └── test_camt053_expected_MT940.TXT   (derived from this SPEC; NOT yet gateway-accepted)
│   └── test_camt053.py, test_swift_charset.py, test_mt940_builder.py, test_splitter.py,
│       test_golden_profile.py, test_paging.py, test_integration.py
├── Entrada/  Ejemplos/
└── Salida/
```

## 5. Code Style

`snake_case`, `UPPER_SNAKE_CASE`, type hints, PEP 8 ≤100 columns, Spanish docstrings, and `runlog` for incidents (never `print`).

## 6. Functional Contract

### 6.1 Input

- Detect by content, not extension (the real input file has **no extension**); parse XML and find `BkToCstmrStmt` by local name. Match elements by local name / `{*}` wildcard (default namespace + Envelope).
- Non-CAMT → `WARN`, skip, do not move.
- Accept UTF-8 (with/without BOM) and UTF-16 LE/BE with BOM; otherwise `ERROR`.

### 6.2 FIN Envelope / Channel Profile

FIN MT has Blocks 1–5; Block 3 is optional and Block 5 is system/trailer data. The upload channel may generate/replace them, so envelope blocks are configurable.
Templates use `<NAME>` placeholders (plain `re.sub`), **not** `str.format`, so literal `{` `}` need no escaping.

```python
PROFILE_NAME         = "GOLDEN_940"
EOL                  = "\r\n"          # [VERIFIED] both MT940 files are CRLF

# --- Envelope values (golden) ---
HEADER_SOURCE        = "config"        # "config" | "apphdr" (derive LTs from Envelope AppHdr, see below)
SENDER_LT_CODE       = "A"             # inserted after BIC8 of AppHdr/Fr when HEADER_SOURCE="apphdr"
RECEIVER_LT_CODE     = "X"             # inserted after BIC8 of AppHdr/To
SENDER_LT            = "DEMOBKMMAXXX"  # 12 chars
RECEIVER_ADDRESS     = "DEMORCVGXXXX"  # 12 chars; position 9 (LT code) MUST be "X"
MSG_TYPE             = "940"
PRIORITY             = "N"
DELIVERY_MONITORING  = ""              # golden omits it (project output had "1")
OBSOLESCENCE         = ""              # golden omits it (project output had "003")
SESSION_NO           = "0000"          # Block 1 = F01 + LT(12) + session(4) + sequence(6)
SEQUENCE_NO          = "000000"

BLOCK1_ENABLED       = True
BLOCK1_TEMPLATE      = "{1:F01<SENDER_LT><SESSION_NO><SEQUENCE_NO>}"
BLOCK2_ENABLED       = True
BLOCK2_TEMPLATE      = "{2:I<MSG_TYPE><RECEIVER_ADDRESS><PRIORITY><DELIVERY_MONITORING><OBSOLESCENCE>}"
BLOCK3_ENABLED       = False
BLOCK3_TEMPLATE      = "{3:{108:<REFERENCE>}}"
BLOCK4_OPEN          = "{4:"           # followed by EOL
BLOCK4_TAG           = ":<tag>:<value>"
BLOCK4_CLOSE         = "-}"
BLOCK5_ENABLED       = False
BLOCK5_TEMPLATE      = "{5:{CHK:<CHK>}{DLM:}}{S:{COP:P}}"
CHK_PLACEHOLDER      = "A1B2C3D4E5F6"  # used ONLY if BLOCK5_ENABLED

# --- Paging / file ---
PAGING_ENABLED         = True         # True = count paging; False = one message per Stmt (see 6.3-D)
ENTRIES_PER_MESSAGE    = 3            # N entries per message when PAGING_ENABLED; int >= 1
MAX_BLOCK4_CHARS        = 9800         # safety net; active in BOTH paging modes
SPLIT_RESERVE_CHARS     = 120
MSG_SEPARATOR           = "$"
OUTPUT_MODE             = "single_file"  # all messages in ONE file; "split_files" = legacy _2/_3
OUTPUT_EXTENSION        = ".txt"         # golden is ".TXT" -> see 13-5
FILE_FINAL_EOL          = True           # file ends with "-}" + EOL
PAGE_REF20_MODE         = "anchor_last"  # or "suffix" (see 6.4)
PAGE_REF20_STEP         = 2001

# --- :61: / :86: profile ---
PAD_61_REFS             = True           # owner/bank ref padded to 16, supp line to 34
OWNER_REF_SOURCES       = ["EndToEndId", "InstrId"]   # NtryRef is NOT used (see 6.5)
BANK_REF_SOURCES        = ["TxDtls/Refs/AcctSvcrRef", "Ntry/AcctSvcrRef"]
REF_FALLBACK            = "NONE"
SUPP_LINE_WIDTH         = 34
FIELD_86_FIRST_WIDTH    = 61             # 65 incl. the ":86:" tag
FIELD_86_NEXT_WIDTH     = 65
FIELD_86_MAX_LINES      = 6
NARRATIVE_SPLIT_PATTERNS = [r",\s+", r"(?<=\S)(?=EXCH\.RATE)"]   # profile-only, see 6.6
COLLAPSE_SPACES         = False          # profile-only; project output collapsed them (see 6.6)
```

Rules:
- Build Blocks 1/2/3/5 from templates; no header/trailer structure may be hard-coded in builder logic.
- `build_block1()` / `build_block2()` MUST validate the rendered header before serialization (reference regexes):
  - Block 1: `^\{1:F01[A-Z0-9]{12}[0-9]{10}\}$`
  - Block 2 (Input): `^\{2:I[0-9]{3}[A-Z0-9]{8}X[A-Z0-9]{3}[SUN]?([123]([0-9]{3})?)?\}$`
- **`HEADER_SOURCE="apphdr"` [VERIFIED equivalence]:** the Envelope carries `AppHdr/Fr/…/BICFI = DEMOBKMMXXX` and `AppHdr/To/…/BICFI = DEMORCVGXXX`. Inserting an LT code after the 8th char gives exactly the golden values: `DEMOBKMM`+`A`+`XXX` = `DEMOBKMMAXXX` (Block 1) and `DEMORCVG`+`X`+`XXX` = `DEMORCVGXXXX` (Block 2). Default stays `"config"` (explicit); when `"apphdr"` is used and AppHdr is absent (plain CAMT) fall back to config values; any mismatch between AppHdr-derived and config values → `INFO`.
- Do not use an Output-header layout for an Input message.
- Block 4 tags start at column 0; fields are separated by `EOL`; no indentation.
- A text line inside Block 4 (supplementary line or `:86:` continuation) must never start with `:` or `-` (FIN would read it as a tag / block end). If it does, prefix one space and log `INFO`.

**Root cause of the Block 2 defect [VERIFIED]:** the project output `DEMORCVGAXXX` reused the *sender* LT code `A` for the *receiver*. Golden uses `X`. v1's default `DEMOLGCYQXXX` (`Q` at position 9) also contradicted its own "X at position 9" rule.

### 6.3 Messages, Paging and File Layout

**A — Multi-statement:** each source `Stmt` is processed independently; messages of Stmt 1 come first, then Stmt 2, etc., all in the same output file. Each Stmt keeps its own `:25:` and `:28C:` first component.

**B — Count paging (`PAGING_ENABLED = True`; replaces v1 size paging as primary trigger):**
The rules below use `ENTRIES_PER_MESSAGE` = *s* = `ENTRIES_PER_MESSAGE` (3 in `GOLDEN_940`). With `PAGING_ENABLED = False` this subsection does not apply (see D).
Golden = 21 entries in 7 messages of exactly 3 entries. **[INFERRED, strong evidence]** this is the bank's *native* MT940 pagination: the CAMT collapses it into one `Stmt` (here 34 entries, `PgNb=00001`, `LastPgInd=true`) but the `Stmt/Id` still carries it — `260831000000012` ends in `012` = ⌈34/3⌉ pages, and its middle digits fit the +2-per-page pattern of the golden `:20:` values (6.4). So the upload path almost certainly expects the bank's 3-entry layout. Therefore:

1. Entries keep source order and are chunked sequentially into groups of *s*. A message holds 1..*s* entries; only the last may hold fewer (*s*=3: 34 → 11×3 + 1 = 12 messages).
2. A Stmt with ≤ *s* entries (or 0) produces exactly one message (`:60F:` … `:62F:`).
3. Never create an empty trailing message (*s*=3: 21 entries → 7 messages, not 8).
4. A `(:61:, supplementary line, :86:)` unit is never split across messages.
5. Safety net (both modes): if a message's Block 4 still exceeds `MAX_BLOCK4_CHARS` (in `count` only possible if *s* is raised; in `none` whenever the Stmt is large), split it further using `current_len + entry_len + SPLIT_RESERVE_CHARS > MAX_BLOCK4_CHARS`.
6. Paging is **never** triggered by source `ITBD`/`:62M:` presence (invariant from 2026-09-18, retained).

**Per-message field layout** [VERIFIED against golden; prototype reconciles on the 34-entry CAMT]:

| Message | Opening | Closing |
|---|---|---|
| First (more follow) | `:60F:` (source `OPBD`) | `:62M:` = opening ± Σ entries of this message |
| Middle | `:60M:` = previous `:62M:` | `:62M:` |
| Last | `:60M:` = previous `:62M:` (`:60F:` if also first) | `:62F:` (source `CLBD`) + `:64:` if `CLAV` exists |

- `:64:` appears **only** on the last message.
- `:62M:` sign: `C` if running balance ≥ 0, else `D` with absolute value (the 34-entry fixture goes negative mid-day, e.g. `:62M:D260831MXN393482162,97` — valid). Date = booking date of the last entry of the message.
- `:28C:` = `<LglSeqNb 5d>/<seq 5d>`; first component constant for the Stmt; second starts at `StmtPgntn/PgNb` (fallback `00001`) and **+1 per message** (golden `01649/00001…00007`; project `01565/00001`).
- `:20:` is **unique per message** (6.4). `:25:` identical in every message of the Stmt.

**C — File layout** [VERIFIED]:

```text
{1:…}{2:…}{4:<EOL>
:20:…<EOL>
…
-}<EOL>
${1:…}{2:…}{4:<EOL>          <- "$" at column 0 of the next line, immediately before "{1:"
…
-}<EOL>                       <- file ends with "-}" + EOL
```

- Join rule: `message₁ + EOL + "$" + message₂ + EOL + "$" + … + messageₙ + EOL`.
- One output file per input file. Naming: `<original>_<ddMMyyyy><OUTPUT_EXTENSION>` (input may have no extension → name is `test_camt053_<ddMMyyyy>.txt`).
  - **Date (2026-10-12):** `ddMMyyyy` is the **last** `BOOK` transaction date (`BookgDt`/`ValDt`), not the run date; if there is none, the run date is used.
  - **32-char cap (2026-10-05):** if the whole name (incl. extension and the largest `_N` suffix) exceeds `FILENAME_MAX_CHARS` (32), it is compacted to `<BIC8 destination>_<YYMMDD last BOOK entry>_<ddMMyy run>.txt` (e.g. `DEMORCVG_260831_051026.txt`). The BIC comes from `AppHdr/To` when present, else `RECEIVER_ADDRESS`.
  - **Collision (2026-10-12):** if the target already exists it is **never overwritten**: `(1)`, `(2)`, ... are appended before the extension while they fit in 32; if they do not fit, the compact name is used and the counter applied there.
  - `_2`, `_3` files exist only if `OUTPUT_MODE = "split_files"` (legacy, off by default).
  - Move originals only after the whole file is written and validated; a collision logs `WARN`.

**D — Dynamic paging (config switch)** *(new in v2.2 · implemented)*

Paging is a **configuration decision**, not a constant of the code. Two values in `Library/config.py`:

| Setting | Values | Effect |
|---|---|---|
| `PAGING_ENABLED` | `True` / `False` (strict `bool`) | `True`: every `ENTRIES_PER_MESSAGE` entries start a new message. `False`: one message per Stmt; only the safety net (`MAX_BLOCK4_CHARS`) can still split. |
| `ENTRIES_PER_MESSAGE` | integer ≥ 1 | *s*, entries per message. Ignored when `PAGING_ENABLED = False`. |
| `OUTPUT_MODE` | `"single_file"` / `"split_files"` | `single_file` (default): all messages of the CAMT in ONE file joined by `$`. `split_files`: legacy `_2`, `_3` files, one per cut. |
| `PAGE_REF20_STEP` | integer | Step between the `:20:` of consecutive messages (6.4). |

With `PAGING_ENABLED = False` the output has the single-block shape of `test_camt053_01102026.txt` (but with every other fix of this SPEC applied); with `True, 3` it has the shape of `test_camt053_expected_MT940.TXT`. This makes the A/B matrix of 13-3 executable by editing two lines.

**Validation:** `config.resolve_page_size()` runs once per file, before anything is written: `PAGING_ENABLED` must be a `bool`; when enabled, `ENTRIES_PER_MESSAGE` must be an `int` ≥ 1 (not `bool`). Violation → `Mt940BuildError`, file logged as `ERROR`, original not moved. "No paging" is expressed only by `PAGING_ENABLED = False` (no magic `0`).

**Effect by setting:**

| Element | `PAGING_ENABLED = True` (size *s*) | `PAGING_ENABLED = False` |
|---|---|---|
| Messages *N* | `max(1, ⌈n/s⌉)` | 1 |
| `:60F:` | first message | the only message |
| `:60M:` / `:62M:` | chained between messages | absent (N = 1) |
| `:62F:` + `:64:` | last message only | the only message |
| `:20:` | `anchor_last` (6.4) | `Stmt/Id` unchanged |
| `:28C:` 2nd component | `PgNb + k − 1` | `PgNb` (`01565/00001`) |
| Separator `$` | between messages | none |

**Safety net:** the `MAX_BLOCK4_CHARS` cut stays active in both modes. With paging enabled, a size cut that fires before *s* entries is logged `WARN [paginado: corte por tamaño]` (the "only the last message may hold fewer than *s*" property no longer holds for that Stmt). A count cut wins over a size cut.

**Invariants** (every setting; covered by `tests/test_paging.py`):
- Flattening the entries of all messages gives exactly the source `BOOK` entries, same order, none lost or duplicated.
- First `:60F:` = `OPBD`; last `:62F:` = `CLBD`; `:60M:`(k) = `:62M:`(k−1); each message reconciles (6.8).
- The `:61:`/`:86:` text of an entry is identical with paging on or off; paging changes only envelope, `:20:`, `:28C:`, `:60:`, `:62:`, `:64:`, separators.

**Code boundary:** `config.resolve_page_size()` (validation), `mt940_splitter.split_statement_lines(..., page_size=)` (count cut + safety net + `:20:` per message), `camt_to_mt940._messages_for()` (reads the settings, honours `OUTPUT_MODE`). `mt940_builder` never reads the page size.

### 6.4 MT940 Mapping (CAMT → MT940)

| MT940 | CAMT source (real file) | Rule |
|---|---|---|
| `{1:}` / `{2:}` | `AppHdr/Fr`, `AppHdr/To` | 6.2 |
| `:20:` | `Stmt/Id` (`260831000000012`) | see below |
| `:25:` | `Stmt/Acct/Id/Othr/Id` (`H01-234-567890`), else IBAN | max 35 |
| `:28C:` | `LglSeqNb` (→ `ElctrncSeqNb`) `/` `StmtPgntn/PgNb` | `01565/00001`; paging +1 on 2nd |
| `:60F:`/`:60M:` | `Bal[OPBD]` | `CRDT`→`C`, `DBIT`→`D`; `YYMMDD`+ccy+comma amount |
| `:62F:`/`:62M:` | `Bal[CLBD]` / computed running balance | 6.3 |
| `:64:` | `Bal[CLAV]` | last message only |
| `:61:` | `Ntry` (`BOOK` only) | 6.5 |
| supp line | `TxDtls/AddtlTxInf` | 6.5 |
| `:86:` | `Ntry/AddtlNtryInf` | 6.6 |

- Only `BOOK`; `PDNG`/`INFO` → `WARN` and exclude.
- Amounts: `<Amt>6611646.2</Amt>` → `19834938,60` (always 2 decimals, comma, no thousands separator).
- **`:20:` (≤16 chars)** — `Stmt/Id` invalid/overflow → deterministic hash + `WARN`. For a Stmt split into N messages, mode `anchor_last` **[INFERRED, matches both data points]**:
  - message N (last) `:20:` = `Stmt/Id`; message k = `str(int(Id) − (N−k)·PAGE_REF20_STEP).zfill(len(Id))`, `PAGE_REF20_STEP = 2001`.
  - Check A (34 entries, N=12): msg 1 = `260830999978001`, msg 12 = `260831000000012` (= Id).
  - Check B (golden, N=7, assuming Id = last `:20:`): msg 7 = `260900742182007`, msg 1 = `260900742170001` ✓ (values in the golden).
  - Consistency log: `INFO` if `int(Id[-3:]) != N`, **only when `s` = 3** (the suffix = page count is a property of the bank's 3-entry layout). For other sizes or `PAGING_ENABLED = False` the check is skipped.
  - `PAGE_REF20_STEP` does not depend on *s*. With *s* ≠ 3 the scheme only guarantees uniqueness; it is not bank-native (13-14).
  - N = 1 → `:20:` = `Stmt/Id` unchanged. Non-numeric / >16 chars / non-positive result → mode `suffix`: `base[:13] + f"{k:03d}"`.
  - Duplicate `:20:` in one file → `ERROR`.

### 6.5 `:61:` Statement Line + Supplementary Line

Golden layout (two physical lines per entry) [VERIFIED]:

```text
:61:<YYMMDD><MMDD><D|C|RC|RD><amount>N<3!c><owner ref → 16 padded>//<bank ref → 16 padded>
<supplementary details → 34 padded>
```

```text
:61:2609110911C15000000,00NMSCNONE············//NONE············
2026091140014ADFO0000798909100····
:61:2609110911C375000000,00NFEXNONE············//SEB000000005····
OP FOREX··························
```
(`·` = trailing space)

Rules:
- Dates: value date `ValDt/Dt` → `YYMMDD`; entry date `BookgDt/Dt` → `MMDD`. Mark: `CdtDbtInd` `CRDT`→`C`, `DBIT`→`D`; `RvslInd=true` → `RC`/`RD` (and the running-balance sign flips).
- **Type code:** `BkTxCd/Prtry/Cd` **verbatim** (`NMSC`, `NFEX` = `N` + 3!c). If not 4 chars `[NFS]+3!c`, use the existing `BkTxCd` mapping.
- **Owner reference (16x):** `EndToEndId` → `Refs/InstrId` → `NONE`. In the real CAMT `InstrId` is the literal `NONE` → output `NONE`; this is *source data*, not an invented fallback [VERIFIED]. **`NtryRef` is not used**: the bank builds it as `<Stmt/Id>-<n>` (`260831000000012-1`, `-2`, …), carries no per-transaction information, and the project output leaked it (`-N` stripped → `260831000000012`) into every `:61:`.
- **Bank reference (16x):** `TxDtls/Refs/AcctSvcrRef` → `Ntry/AcctSvcrRef` → `NONE`; value `NONE` is emitted literally. `//` is **always** emitted in this profile (`//NONE`, `//SEB000000005`).
- **Padding (`PAD_61_REFS`)** [VERIFIED]: owner ref right-padded to 16, bank ref to 16, supplementary line to 34. **Never `rstrip()` these lines.**
- **Supplementary line (34x):** `TxDtls/AddtlTxInf` verbatim (`FT00000S0001`, `OP FOREX`, `BOOK TRANSFER`, `0011  CCN000000001`, `WITHHOLD TAX H00000000000`; all ≤34 in the real file). If longer than 34: cut at the last token boundary ≤34 and *prepend* the remainder to the `:86:` content (no information loss). If the entry has neither `AddtlTxInf` nor `AddtlNtryInf`: omit both the line and `:86:` (`INFO`).
- No free-form narrative is ever appended to line 1.

Required functions: `build_field_61()`, `validate_field_61()`. Validation MUST run before serialization and checks component-wise: date formats, mark, amount ≤15 chars with a comma, type `[NFS]+3!c`, owner ref ≤16, bank ref ≤16, supp ≤34, padded widths when `PAD_61_REFS`, no `CR`/`LF` inside components.

### 6.6 `:86:` Information to Account Owner

Format: **≤ 6 lines**; first physical line starts with `:86:`, continuations contain text only.

**Source = `Ntry/AddtlNtryInf` only** [VERIFIED by reconstruction]. The CAMT splits the bank's native narrative in two: `AddtlTxInf` (→ `:61:` supplementary line) and `AddtlNtryInf` (→ `:86:`). The project output glued them together as
`AddtlTxInf + " " + AddtlNtryInf + " " + <NtryRef stem> + " " + <AcctSvcrRef if ≠ NONE>` — exactly what produced the over-long, reference-polluted `:86:`.

1. `:86:` = `AddtlNtryInf`, **never** prefixed with `AddtlTxInf` and **never** suffixed with `NtryRef`/`AcctSvcrRef`/`EndToEndId`/Stmt `Id`/`:20:`. Parties, UETR and other elements are not added in this profile; dropped source elements → one aggregated `WARN [86_SOURCE_OMITTED]` per Stmt (count + element name).
2. **Split into physical lines (profile-only) [INFERRED from golden FX entry]:** apply `NARRATIVE_SPLIT_PATTERNS` in order — `", "` (comma + whitespace; separator consumed) and the zero-width point before a glued `EXCH.RATE`. Commas inside amounts (`USD22,096,778.01`) have no following space → untouched.

```text
CAMT  : FOREIGN EXCHANGE, CONTRACT DATE 2026-08-28, OUR SALE USD26,398,226.04EXCH.RATE 17.0466
:86:FOREIGN EXCHANGE
CONTRACT DATE 2026-08-28
OUR SALE USD26,398,226.04
EXCH.RATE 17.0466
```
   (Golden FX entry has the identical 4-line shape; `OP FOREX` sits in the `:61:` supplementary line.) Narratives without these patterns (`PRINCIPAL MXN115,068.39`) stay on one line.
3. Wrap only lines longer than the width, **at token boundaries**: first physical line ≤ 65 **including** `:86:` (→ 61 content, `FIELD_86_FIRST_WIDTH`); continuation lines ≤ 65. **Never split a token containing a digit/`,`/`.`** (amounts, IDs) unless it alone exceeds the width; then hard-split + `WARN [86_HARD_SPLIT]`.
4. Max 6 lines. Overflow → deterministic truncation + `WARN [86_OVERFLOW] + <lost text>`.
5. Never inject another field tag or `:61:` narrative into `:86:`.
6. **Whitespace:** `COLLAPSE_SPACES = False`. The real data has double spaces (`0011  CCN000000001`); the project output silently collapsed them. Collapsing/punctuation rewriting (`.`→`,`, removing `:`) is profile-only, off by default, tested separately.

Required functions: `build_field_86()`, `split_narrative()`, `wrap_field_86(width_first=61, width_next=65, max_lines=6)`, `validate_field_86()`. Validation MUST run before serialization.

**Why this matters:** the project output hard-cut lines at 61 chars **mid-token** (`MXN145,668` / `.26 …`), which can corrupt amounts. With the source-faithful mapping, the longest real narrative (the FX entry) fits in 4 lines of ≤28 chars; wrapping becomes a rare safety net.

### 6.7 Character Handling

Apply SWIFT character filtering after mapping and before length checks. Fold accents silently (`Société` → `Societe`). Unsupported characters → replacement + `WARN` when information is lost; never silently discard data. Padding spaces from 6.5 are added **after** filtering and are never trimmed.

### 6.8 Integrity

- Per message: `:60 ± Σ(:61: of that message) = :62` within `0.005`.
- Per Stmt: `OPBD ± Σ(all :61:) = CLBD` (real file: `44865437.07 → 784291947.87` ✓), and compare with `TxsSummry` when present (absent in the real file → `INFO`).
- Chain: `:60M:` of message *k* == `:62M:` of message *k−1*.
- Mismatch → `WARN`/`ERROR` by severity.

### 6.9 Output Encoding

ASCII (UTF-8 without BOM), `EOL = CRLF` on every line including the last; no tabs. Trailing spaces preserved where 6.5 requires them.

## 7. Logging

`log_<ddMMyyyy>_<HHmmss>.txt`:

```text
DD/MM/YYYY HH:MM | file.xml | WARN: [<rule>] + <lost text>
DD/MM/YYYY HH:MM | file.xml | ERROR: [<message>]
DD/MM/YYYY HH:MM | file.xml | INFO: [<rule>] + <detail>
```

## 8. Tests

`unittest` only. Cover XML versions/Envelope/plain input; all fields; charset/truncation.

**Golden-profile tests (`test_golden_profile.py`):**
- Independent checker over `golden/finalExample.TXT`: 7 messages × 3 `:61:`; `:28C:` `01649/00001..00007`; `:60M:`==previous `:62M:`; `:62F:`+`:64:` only in message 7; `$` at column 0 before `{1:`; file ends `-}`+CRLF; `:61:` line 1 content = 59 chars; supp lines = 34; `:20:` values match the `anchor_last` pattern (step 2001, last digits 001..007).
- **Real-CAMT test** (`golden/test_camt053.xml`, 34 entries): 12 messages (11×3 + 1); `:20:` first `260830999978001`, last `260831000000012`; `:28C:` `01565/00001..00012`; message 1 opens `:60F:C260831MXN44865437,07`; message 12 has one entry and closes `:62F:`/`:64:` = `C260831MXN784291947,87`; per-message balance reconciliation; message 2 FX entry renders the 4-line `:86:` and `//SES000000001`; owner ref `NONE` on all entries; entry `0011  CCN000000001` keeps the double space.
- **Byte-equality** against `test_camt053_expected_MT940.TXT` (derived from this SPEC). Promote it to a true golden only after the gateway accepts it (13-3).
- Paging boundaries (*s* = 3): 0, 1, 3, 4, 6, 7, 21, 22, 34 entries → messages 1, 1, 1, 2, 2, 3, 7, 8, 12; last message = remainder; no empty trailing message.

**Dynamic-paging tests (`test_paging.py`, implemented):**
- `resolve_page_size`: off → `None`; on → N; rejects `0`, `-1`, `2.5`, `"3"`, `True`; rejects non-bool flag; reads config at call time.
- Matrix on the real CAMT (34 entries): N = 1, 2, 3, 5, 10, 34, 50 → 34, 17, 12, 7, 4, 1, 1 messages; paging off → 1.
- Invariants of 6.3-D for every N: entry order/count, `OPBD`→`CLBD`, per-message reconciliation and chain, `:62F:`/`:64:` only last, unique `:20:` ending in `Stmt/Id`, `:28C:` +1, `ends_with_62m`.
- Structural lines (`:20:`, `:25:`, `:28C:`, `:60:`, `:62:`, `:64:`) and the `:61:` prefix of each entry equal `golden/test_camt053_expected_MT940.TXT` for N = 3.
- `:20:` anchor_last, suffix fallback (non-numeric / non-positive), N = 1 message unchanged.
- Safety net: WARN only when paging is on.
- End-to-end `run_batch`: defaults → 1 file, 12 messages, 11 `-}$`; paging off → 1 message, no `$`; N = 5 → 7 messages; `OUTPUT_MODE = "split_files"` → 12 files; invalid N → exit 1, original not moved, no output.
- Full byte-equality with the expected file stays **pending** until the items in §14 are implemented.
- Multi-`Stmt`: independent paging, own `:25:`/`:28C:`; one file.
- `:60M:`/`:62M:` propagation incl. sign flip to `D`; `:64:` only last; `:28C:` +1 per message; `:20:` unique (anchor_last, suffix fallback, N=1).
- Block 2: rejects `DEMORCVGAXXX` and `DEMOLGCYQXXX`; accepts `DEMORCVGXXXX`; `HEADER_SOURCE="apphdr"` derives `DEMOBKMMAXXX`/`DEMORCVGXXXX` from the Envelope; suffix `1003` only if configured; template change needs no builder change. Blocks 3/5 independent; Block 1 regex.
- `:61:`: exact grammar, padding widths, `NtryRef` ignored, `InstrId` → owner ref, `AcctSvcrRef` → bank ref, `//NONE` when literal `NONE`, `Prtry/Cd` verbatim, supp overflow >34 moves remainder to `:86:`, reversal `RC`/`RD`.
- `:86:`: only `AddtlNtryInf`, no reference duplication, comma/`EXCH.RATE` splitting, 61/65 boundary, no mid-token cut of amounts, 6-line overflow + log, lines starting `:`/`-` protected, `COLLAPSE_SPACES` off by default.
- Regression tests for each defect in Appendix A.
- Idempotent re-run; naming (input without extension); originals moved only after full success; synthetic >9800-char fixture (safety net).

Target ≥90% coverage in parse/build/split/charset modules.

## 9. Boundaries

**Always:** content detection; `BOOK` only; balance checks; ≤ `ENTRIES_PER_MESSAGE` entries per message when `PAGING_ENABLED = True` (3 in the profile); complete transaction units; unique `:20:` per message; `$` join rule; `:61:` with supplementary line; `:86:` from `AddtlNtryInf` only; padding preserved; column-0 tags; CRLF; log all losses.

**Configurable:** Block 1/2/3/5 presence/templates, header values and `HEADER_SOURCE`, `PAGING_ENABLED`, `ENTRIES_PER_MESSAGE`, `OUTPUT_MODE`, padding, reference sources/fallback, `:20:` mode/step, `:86:` widths and split patterns, punctuation/whitespace rules, filenames/extension, `OUTPUT_MODE`, BIC/LT values.

**Ask first:** new external dependencies; changes to CLI, paging semantics, or source/bank mappings beyond this SPEC.

**Never:** hard-code the page size outside `config.py`; interpret `ENTRIES_PER_MESSAGE = 0` as "no paging"; let paging change the text of any `:61:`/`:86:`; convert `PDNG`/`INFO`; delete originals before full success; silently discard data; fabricate MAC/CHK when Block 5 is disabled; confuse profile-specific restrictions with generic SWIFT rules; prefix `:86:` with `AddtlTxInf`; use `NtryRef` as owner reference; strip padding; hard-cut inside amounts/IDs; collapse whitespace by default; emit an empty trailing message.

## 10. Success Criteria

1. Real CAMT → `test_camt053_expected_MT940.TXT` byte for byte; and the golden's shape is matched (messages, layout, padding, separators, EOL).
2. Every message has ≤ *s* `:61:` (*s* = 3 by default); last holds the remainder; `:62F:`/`:64:` only on the last; `:60M:`/`:62M:` chain reconciles.
3. One output file; messages joined by `EOL + "$"`; file ends with `-}` + CRLF.
4. Every `:61:` passes validation (padding included) with its supplementary line and no embedded narrative.
5. Every `:86:` ≤6 lines, from `AddtlNtryInf` only, no mid-token cuts; overflow logged.
6. Block 2 template-driven and validated (X at position 9); Blocks 3/5 off by default and independently enable-able.
7. Balances reconcile per message and per Stmt; originals move only after complete success.
8. Paging is switchable from `config.py` with no code change: `PAGING_ENABLED = False` → 1 message; `True` with *s* → `⌈n/s⌉` messages; the invariants of 6.3-D hold for every size.

## 11. Bug / Contradiction History

**2026-10-12 — Repeated files overwritten despite different transaction dates**
- A 15-file batch logged the same output being overwritten; all files shared the run-date suffix, so different transaction dates collapsed to one name. → §6.3-C: the name is dated by the **last** `BOOK` transaction (not the run date); on a still-existing target, `(1)`, `(2)`, ... are appended (compact name first if the counter does not fit in 32). Overwrite is no longer a behavior — `process_file` resolves a free name (`_resolve_output_name`).

**2026-10-05 — Output filename over SWIFT's 32-char limit**
- A gateway rejected `DDEMOBKMMAXXX20260930000105300001_05102026.txt` (46 chars): the name carried the full original stem, which SWIFT's upload rejects past 32 chars. → §6.3-C: keep `<original>_<ddMMyyyy>.txt` when it fits; otherwise compact to `<BIC8>_<YYMMDD>_<ddMMyy>.txt` (`FILENAME_MAX_CHARS`, `_compact_stem`, `_transaction_date`). Destination BIC = `AppHdr/To` (fallback `RECEIVER_ADDRESS`); transaction date = oldest `BOOK` `BookgDt`/`ValDt`; run date unchanged.

**2026-10-04 — Dynamic paging (v2.2)**
- Page size was a bare constant with no way to switch it off, so the single-block shape (rejected file) could not be reproduced and the A/B matrix of 13-3 needed code edits. → `PAGING_ENABLED`, `ENTRIES_PER_MESSAGE`, `OUTPUT_MODE`, `resolve_page_size()` (6.3-D).
- `:20:` consistency `INFO` assumed *s* = 3 and would fire falsely for any other size. → restricted to *s* = 3 (6.4).
- Expected file `test_camt053_expected_MT940.TXT` checked by script: 12 messages, 34 entries in the same order as the project output, chain and per-message balances reconcile, `:20:` step 2001, CRLF with final EOL.

**2026-10-01 (b) — Real CAMT analysis (v2.1)**
- Owner ref defect explained: project used `NtryRef` (`<Id>-<n>`, suffix stripped) → same value on all 34 entries. Golden = `InstrId` (`NONE`). → 6.5.
- `:86:` defect explained: project concatenated `AddtlTxInf + AddtlNtryInf + NtryRef stem + AcctSvcrRef`. Correct split: `AddtlTxInf` → `:61:` supp line, `AddtlNtryInf` → `:86:`. → 6.5/6.6.
- Block 2 receiver defect explained: sender LT code `A` reused for the receiver (should be `X`). → 6.2.
- `:20:` resolved: `Stmt/Id` is the **last** message's reference (suffix `012` = 12 pages); earlier pages step back by 2001. → 6.4.
- `:28C:` second component comes from `StmtPgntn/PgNb`, not from `ElctrncSeqNb` (v1 text was wrong: it would give `01565/01565`). → 6.4.
- 3-entry paging now explained as bank-native pagination collapsed by the CAMT (inferred). → 6.3.
- Project silently collapsed double spaces in narratives (`0011  CCN…`) → off by default.
- Real input file has no extension → content detection confirmed necessary.

**2026-10-01 (a) — Golden-file comparison (v2)**
- Size paging was the wrong primary trigger → count paging (3/message), one file joined by `$`; `_2`/`_3` files legacy.
- Block 2 suffix `1003`, `SYS_SEQ` default mismatch, `str.format` templates → fixed.
- `:61:` missing bank-ref default / supplementary line / padding → fixed.
- `:86:` hard cut at 61 mid-token → fixed. Output lacked final CRLF → fixed.

**2026-09-23 — MT940 rejection investigation** (kept)
- Leading tag spaces → fixed (column 0). `:61:` narrative leakage → forbidden. `:86:` length violation → wrapping/validation. Block 3/5 over-specified → configurable. Block 2 hard-coded → template-driven. Punctuation hypothesis (`.`→`,`, removing `:`) is **not** a generic rule → profile-only; golden leaves `.` and `,` untouched.

**2026-09-18** — Paging bug: `:62M:` is an output of paging, never its trigger → invariant retained.

## 12. Appendix A — Project output vs golden (with root cause)

| # | Aspect | Project output | Golden | Root cause / Rule |
|---|---|---|---|---|
| 1 | Block 2 receiver | `DEMORCVGAXXX` | `DEMORCVGXXXX` | wrong LT code (6.2) |
| 2 | Block 2 suffix | `N1003` | `N` | optional fields filled (6.2) |
| 3 | Block 1 | `…0000000000` | identical | — |
| 4 | Messages | 1 × 34 `:61:` | 7 × 3 | count paging (6.3); project shape = `PAGING_ENABLED = False` (6.3-D) |
| 5 | Separator | n/a | `-}` EOL `$`+`{1:` | 6.3-C |
| 6 | Final bytes | `-}` no EOL | `-}` CRLF | 6.9 |
| 7 | `:20:` | one value | unique, step 2001, last = Stmt/Id | 6.4 |
| 8 | `:28C:` | `01565/00001` | `01649/00001…7` | `PgNb` + paging (6.3) |
| 9 | `:60M:`/`:62M:`/`:64:` | none | chained; `:64:` last only | 6.3 |
| 10 | Tags col 0, CRLF, `{4:`+CRLF, no Block 3/5 | same | same | — |
| 11 | `:61:` owner ref | `260831000000012` (NtryRef stem) | `NONE` (InstrId) padded 16 | 6.5 |
| 12 | `:61:` bank ref | only if ≠ `NONE` | always `//…` padded 16 | 6.5 |
| 13 | `:61:` supp line | none | `AddtlTxInf`, padded 34 | 6.5 |
| 14 | `:86:` content | `AddtlTxInf+AddtlNtryInf+NtryRef+AcctSvcrRef` | `AddtlNtryInf` only | 6.6 |
| 15 | `:86:` wrapping | cut at 61 mid-token | by narrative parts | 6.6 |
| 16 | `:86:` FX | one joined string | 4 lines | 6.6 |
| 17 | Double spaces | collapsed | (not in sample) | 6.6 |
| 18 | Extension | `.txt` | `.TXT` | 13-5 |

## 13. Pending Items

1. **Golden's CAMT** is unavailable; every rule assumes it has the same structure as `test_camt053`. Confirm that its `Stmt/Id` is `260900742182007` (would validate `anchor_last` exactly) and that it has one `Stmt`.
2. **Remainder message:** golden has 21 entries (divisible by 3). Confirm a last message with 1–2 entries is accepted (real file → last message has 1).
3. **Gateway test of `test_camt053_expected_MT940.TXT`** and an A/B matrix to isolate the real cause (10+ differences at once). With v2.2 the paging cells need no code change (`PAGING_ENABLED` / `ENTRIES_PER_MESSAGE` in `config.py`): (a) golden envelope only (`PAGING_ENABLED = False`); (b) + 3-entry paging; (c) + `:61:` padding/supp line; (d) + `:86:` from `AddtlNtryInf`; (e) 6-entry messages (tests the count limit); (f) unpadded `:61:`.
4. **`, ` / `EXCH.RATE` split** is inferred from one golden FX entry (different day than the CAMT). Confirm with another FX sample.
5. **Extension case** `.TXT` vs `.txt`.
6. **`:86:` width** counting (with/without tag); v2.1 uses the conservative reading.
7. **Gateway Blocks 1/2/5:** session/sequence zeros suggest the gateway rewrites them; confirm.
8. **Padding** required or only tolerated (A/B (f)); double-space handling.
9. **Multi-page CAMT** (`LastPgInd=false`, closing `ITBD`, `PgNb>1`): how its pages map to `:62M:`/`:60M:` and `:28C:`. Not covered by any sample.
10. **`:62M:` date** for multi-day Stmts (all samples are single-day).
11. Bank/channel `:86:` punctuation/whitespace restrictions (carried over).
12. Implement and integrate `:61:`/`:86:` validators **before** changing business mappings (carried over).
13. **`auto` paging mode (not specified):** derive *s* from the `Stmt/Id` suffix (`⌈n / int(Id[-3:])⌉` = 3 for the real file). Only worth it if the suffix proves to be the bank's page count in more samples; for now *s* is explicit.
14. **`:20:` step vs. page size:** `PAGE_REF20_STEP = 2001` was fitted at *s* = 3. Unknown whether the gateway cares about the pattern or only about uniqueness; relevant if sizes other than 3 are ever sent.
15. **Ceiling on *s*:** the gateway's real maximum entries per message is unknown (13-3 e tests 6); until then values above 3 only log `INFO`.

## 14. Implementation status (v2.2, 2026-10-05)

**Implemented and tested (242 tests OK, coverage ≥ 95% on parse/build/split/charset):**
- `PAGING_ENABLED` / `ENTRIES_PER_MESSAGE` (6.3-D), `resolve_page_size()` validation.
- Count cut in `split_statement_lines(page_size=)` with `:60M:`/`:62M:` chain, `:28C:` +1 and unique `:20:` per message (anchor_last, step 2001).
- `OUTPUT_MODE = "single_file"` (default) in `camt_to_mt940._messages_for`.
- On the real CAMT with defaults: 12 messages in one file; the 61 structural lines (`:20:`/`:25:`/`:28C:`/`:60`/`:62`/`:64:`) are identical to `test_camt053_expected_MT940.TXT`, and so is the `:61:` prefix (dates, mark, amount) of all 34 entries.

**Still pending for byte-equality with the expected file (not part of paging):**
1. Join `-}` + EOL + `$` and final EOL after the last `-}` (6.3-C, 6.9). Code still joins with `-}$` and no final EOL.
2. Block 2 receiver `DEMORCVGXXXX` with no `1003` suffix (6.2): code still uses `DEMORCVGAXXX` + `N1003`.
3. `:61:` owner/bank refs padded to 16, `//NONE`, supplementary line padded to 34 (6.5).
4. `:86:` from `AddtlNtryInf` only, comma/`EXCH.RATE` split (6.6).
