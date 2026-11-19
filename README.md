<div align="center">

# CAMT.053 → MT940

**Conversor por lotes de estados de cuenta CAMT.053 (ISO 20022) a mensajes MT940 (SWIFT FIN).**

Sin dependencias externas · Perfil FIN validable · Cada pérdida de información queda registrada

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Dependencias](https://img.shields.io/badge/dependencias-0-brightgreen?style=flat-square)](#requisitos)
[![Tests](https://img.shields.io/badge/tests-343-brightgreen?style=flat-square)](#pruebas)
[![Licencia](https://img.shields.io/badge/licencia-MIT-blue?style=flat-square)](LICENSE)
[![SPEC](https://img.shields.io/badge/SPEC-v2.2-2ea44f?style=flat-square)](SPEC.md)

</div>

---

## Índice

- [Qué es](#qué-es)
- [Inicio rápido](#inicio-rápido)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Qué acepta como entrada](#qué-acepta-como-entrada)
- [Qué genera](#qué-genera)
- [Reglas del MT940 generado](#reglas-del-mt940-generado)
- [Nombres de archivo y colisiones](#nombres-de-archivo-y-colisiones)
- [Configuración](#configuración)
- [Cómo adaptarlo a tu banco](#cómo-adaptarlo-a-tu-banco)
- [Arquitectura](#arquitectura)
- [Pruebas](#pruebas)
- [Validador externo opcional](#validador-externo-opcional)
- [Solución de problemas](#solución-de-problemas)
- [Alcance y limitaciones](#alcance-y-limitaciones)
- [Privacidad](#privacidad)
- [Contribuir](#contribuir)
- [Licencia](#licencia)

---

## Qué es

Este proyecto convierte **uno o varios archivos CAMT.053** en **archivos MT940** listos para cargar en un canal SWIFT o en un core bancario.

Está pensado para equipos que reciben estados de cuenta en ISO 20022 y todavía necesitan entregarlos en el formato MT940. El conversor:

- Detecta el CAMT **por contenido**, no por extensión.
- Acepta CAMT plano o envuelto en un `Envelope` SWIFT.
- Genera mensajes con la envoltura FIN (`{1:...}{2:...}{4:...-}`).
- Pagina los movimientos en mensajes de N entradas (3 por defecto).
- Encadena los saldos entre mensajes (`:62M:` de uno = `:60M:` del siguiente).
- Valida que los saldos cuadren antes de escribir.
- Valida la gramática de `:61:` y `:86:` antes de serializar.
- Nunca sobrescribe una salida: resuelve colisiones con `(1)`, `(2)`, ...
- Mueve el CAMT original a `Entrada/Procesados/` solo cuando terminó bien.
- Registra cada incidencia (incluido el texto perdido) en un log por corrida.

> **No es un gateway SWIFT.** Genera archivos; no los transmite ni se conecta a la red SWIFT.

---

## Inicio rápido

```bash
# 1. Clona el repositorio
git clone https://github.com/davidluciol/TransformCAMT053toMT940.git
cd TransformCAMT053toMT940

# 2. Copia un CAMT de ejemplo en Entrada/
#    Windows PowerShell:
Copy-Item tests\fixtures\golden\test_camt053.xml Entrada\
#    Linux / macOS:
# cp tests/fixtures/golden/test_camt053.xml Entrada/

# 3. Convierte
python camt_to_mt940.py -i Entrada -o Salida
```

Resultado esperado:

```text
Transformando test_camt053.xml
Transformacion exitosa, continuando con el siguiente: test_camt053.xml
Resumen: 1 transformados, 0 omitidos, 0 con error
```

- El MT940 aparece en `Salida/test_camt053_31082026.txt`.
- El original se mueve a `Entrada/Procesados/test_camt053.xml`.
- La corrida deja `Salida/log_<ddMMyyyy>_<HHmmss>.txt`.
- Si no hubo incidencias, el log puede quedar vacío.

> En Windows, si `python` no está en el `PATH`, usa `py` en lugar de `python`.

---

## Requisitos

| Requisito | Detalle |
|---|---|
| **Python** | 3.9 o superior. Verificado con 3.13. |
| **Dependencias** | **Ninguna.** Solo la biblioteca estándar. |
| **Sistema** | Windows, Linux o macOS. |
| **Permisos** | Lectura/escritura en las carpetas de entrada y salida. |

No hace falta `pip install`, `setup.py` ni crear un entorno virtual. Basta con tener Python instalado.

El único componente opcional es el validador externo, que sí requiere `pip install mt-940` (ver [Validador externo opcional](#validador-externo-opcional)).

---

## Instalación

```bash
git clone https://github.com/davidluciol/TransformCAMT053toMT940.git
cd TransformCAMT053toMT940
```

Verifica la instalación:

```bash
python --version
python -m unittest discover -s tests
```

Si prefieres un entorno virtual:

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

No hay nada que instalar dentro del entorno: el proyecto funciona con la biblioteca estándar.

---

## Uso

### Comando principal

```bash
python camt_to_mt940.py -i "<entrada>" -o "<salida>"
```

| Parámetro | Obligatorio | Descripción |
|---|---|---|
| `-i` | Sí | Archivo **o** carpeta de entrada. |
| `-o` | Sí | Carpeta de salida. Se crea si no existe. |

### Ejemplos

```powershell
# Convertir todos los archivos de una carpeta (Windows PowerShell)
python camt_to_mt940.py -i "Entrada" -o "Salida"

# Convertir un solo archivo con ruta absoluta
python camt_to_mt940.py -i "C:\Banco\camt\estado.xml" -o "C:\Banco\salida"

# Rutas con espacios: usa comillas
python camt_to_mt940.py -i "C:\Mis Estados\Entrada" -o "C:\Mis Estados\Salida"
```

```bash
# Linux / macOS
python3 camt_to_mt940.py -i ./Entrada -o ./Salida
python3 camt_to_mt940.py -i ./Entrada/estado.xml -o ./Salida
```

### Flujo de trabajo

```text
   ┌────────────┐    conversión    ┌────────────────────────────┐
   │  Entrada/  │ ───────────────▶ │  Salida/                   │
   │  *.xml     │                  │  MT940 + log de la corrida │
   └─────┬──────┘                  └────────────────────────────┘
         │ solo si todo terminó bien
         ▼
   ┌──────────────────┐
   │ Entrada/         │
   │   Procesados/    │  originales ya convertidos
   └──────────────────┘
```

- La carpeta de entrada **no se recorre en subcarpetas**: solo se procesan los archivos que están directamente en `-i`. Las subcarpetas (por ejemplo `Procesados/`) se ignoran.
- Los archivos ocultos (`.gitkeep`, `.DS_Store`, etc.) también se ignoran.
- Un archivo convertido **se mueve** a `Procesados/`. Si vuelves a ejecutar sobre la misma carpeta, ya no lo verás.
- Si la carpeta está vacía, el CLI lo avisa: `No se encontraron archivos para convertir en <ruta>`.

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | La corrida terminó sin ningún `ERROR` (puede haber `WARN`). |
| `1` | Hubo al menos un `ERROR` (o la ruta de entrada no existe). |
| `2` | Faltan argumentos obligatorios (`argparse`). |

> Un `WARN` **no** cambia el código de salida. El archivo se genera igualmente.

### Re-ejecución e idempotencia

El conversor está diseñado para poder repetir una corrida sin perder información:

- Si un archivo falla, el original **no se mueve** y puedes corregirlo y reintentar.
- Si el mismo nombre de salida ya existe, se agrega `(1)`, `(2)`, ... y se registra un `WARN`. **Nunca se sobrescribe una salida.**
- Si el movimiento a `Procesados/` falla (por ejemplo, un archivo bloqueado), se registra `ERROR`; la salida ya escrita se conserva y el original queda en su sitio.

---

## Qué acepta como entrada

| Aspecto | Comportamiento |
|---|---|
| **Formato** | CAMT.053 (`camt.053.001.02`, `.08`, `.10`, `.11` y variantes compatibles). |
| **Envoltura** | Documento plano o `Envelope/Document` con `AppHdr`. |
| **Detección** | Por contenido: parsea el XML y busca `BkToCstmrStmt` por *local name*. |
| **Extensión** | No importa: `.xml`, `.txt` u otra, siempre que el contenido sea CAMT.053. |
| **Codificación** | UTF-8 (con o sin BOM) y UTF-16 LE/BE **con BOM**. |
| **Múltiples `Stmt`** | Se procesan todos los `Stmt` del documento. |
| **Páginas** | Soporta `StmtPgntn`, `LglSeqNb`, `PgNb` y páginas intermedias con cierre `ITBD`. |

### Qué pasa con archivos que no son CAMT.053

- Si el XML es válido pero **no contiene** `BkToCstmrStmt`, se registra `WARN` y el archivo se **omite** (no se mueve).
- Si contiene `BkToCstmrStmt` pero el XML está roto o no tiene `Stmt`, se registra `ERROR` y el archivo **no se mueve**.
- Un error en un archivo **no detiene el lote**: los demás se siguen procesando.

---

## Qué genera

### Estructura general

Por defecto (`OUTPUT_MODE = "single_file"`), **cada CAMT genera un único archivo** con todos los mensajes MT940 dentro, separados por `$`.

```text
Salida/
├── test_camt053_31082026.txt   ← MT940 (12 mensajes en el ejemplo real)
└── log_18112026_202934.txt     ← incidencias de la corrida
```

El archivo de salida:

- Es UTF-8 **sin BOM** (tras el filtrado SWIFT queda ASCII).
- Usa **CRLF** (`\r\n`) como fin de línea.
- Termina en `-}` + CRLF.
- Une los mensajes con `-}` + CRLF + `$` + `{1:...` (el `$` queda a columna 0 y el siguiente mensaje empieza inmediatamente después).

### Ejemplo real (recortado)

```text
{1:F01DEMOBKMMAXXX0000000000}{2:I940DEMORCVGXXXXN}{4:
:20:260830999978001
:25:H01-234-567890
:28C:01565/00001
:60F:C260831MXN14955145,69
:61:2608310831C38356,13NMSCNONE            //NONE
FT00000S0001
:86:PRINCIPAL MXN38,356.13
...
:62M:C260831MXN15359597,10
-}
${1:F01DEMOBKMMAXXX0000000000}{2:I940DEMORCVGXXXXN}{4:
...
:62F:C260831MXN261430649,29
:64:C260831MXN261430649,29
-}
```

> En el archivo real, las referencias de `:61:` van padeadas a 16 caracteres y la línea suplementaria a 34; los espacios finales no se ven en el bloque de arriba.

### Mensajes y paginado

Con la configuración por defecto (`PAGING_ENABLED = True`, `ENTRIES_PER_MESSAGE = 3`), el fixture de ejemplo (34 movimientos `BOOK`) produce:

```text
34 movimientos  →  12 mensajes  →  11 mensajes de 3 + 1 mensaje de 1
```

- El primer mensaje de cada `Stmt` abre con `:60F:` (saldo inicial).
- Los mensajes intermedios cierran con `:62M:` y el siguiente abre con `:60M:` con **exactamente** ese saldo.
- El último mensaje de cada `Stmt` cierra con `:62F:` y, si el CAMT trae `CLAV`, también `:64:`.
- El `:28C:` avanza por mensaje (`01565/00001`, `01565/00002`, ...).
- El `:20:` es único por mensaje: el último conserva el `Stmt/Id` y los anteriores retroceden de 2001 en 2001 (`PAGE_REF20_STEP`).
- Un `:61:` y su `:86:` **nunca** se parten entre mensajes.

Si el bloque 4 se acerca al límite de tamaño (`MAX_BLOCK4_CHARS`, 9800 por defecto), el splitter corta antes para no excederlo y lo registra con `WARN`. Es una red de seguridad; el corte normal es por conteo.

---

## Reglas del MT940 generado

### Tags principales

| Tag | Contenido | Origen en el CAMT |
|---|---|---|
| `:20:` | Referencia única del mensaje | `Stmt/Id` (fallback `MsgId`) |
| `:25:` | Identificación de cuenta | `Acct/Id/IBAN` o `Acct/Id/Othr/Id` |
| `:28C:` | Secuencia de página | `LglSeqNb` / `StmtPgntn/PgNb` |
| `:60F:` / `:60M:` | Saldo de apertura | `Bal` `OPBD`, encadenado |
| `:61:` | Movimiento | `Ntry` con estado `BOOK` |
| `:62F:` / `:62M:` | Saldo de cierre | `Bal` `CLBD` (o `ITBD` en páginas intermedias) |
| `:64:` | Saldo final valorado | `Bal` `CLAV`, solo si existe |
| `:86:` | Información adicional | `Ntry/AddtlNtryInf` |

### `:61:` (movimiento)

- **Fecha valor**: `ValDt` en `YYMMDD`.
- **Fecha de registro**: `BookgDt` en `MMDD`.
- **Marca**: `C` (crédito), `D` (débito), `RC`/`RD` si `RvslInd = true`.
- **Importe**: coma decimal y dos decimales.
- **Tipo**: `TX_TYPE_MAP` → código `Prtry` de 4 caracteres válido → `NMSC` + `WARN` si no hay uno válido.
- **Owner reference**: `EndToEndId` → `InstrId` → `NONE`. `NtryRef` **nunca** se usa.
- **Bank reference**: `TxDtls/Refs/AcctSvcrRef` → `Ntry/AcctSvcrRef` → `NONE`.
- **Padding**: por defecto owner y bank a 16 caracteres, `//` siempre presente.
- **Línea suplementaria**: `TxDtls/AddtlTxInf`, padeada a 34 caracteres. Si no cabe, el resto pasa al `:86:` sin perder texto.

### `:86:` (narrativa)

- Se construye **solo** desde `Ntry/AddtlNtryInf`.
- `RmtInf/Ustrd` y `UETR` no se vuelcan en este perfil; se reportan juntos en un `WARN` (`86_SOURCE_OMITTED`) para que la omisión no sea silenciosa.
- Máximo **6 líneas**.
- Primera línea: hasta 61 caracteres de contenido (65 con el prefijo `:86:`).
- Continuaciones: hasta 65 caracteres, sin prefijo de tag.
- El texto que no cabe se registra con `WARN` (`86_OVERFLOW`) y el texto perdido.
- Los espacios internos se conservan (`COLLAPSE_SPACES = False`), por ejemplo `0011  CCN000000001`.

### Saldos y validaciones

Antes de escribir, el conversor comprueba:

```text
OPBD + créditos − débitos = CLBD     (tolerancia 0.005)
```

- Solo se incluyen entradas con estado `BOOK`. Las demás se registran con `WARN` y se omiten.
- Si falta `OPBD` o `CLBD` (o `ITBD` en una página intermedia), se registra `ERROR` y el archivo no se convierte.
- Si el saldo no cuadra, se registra `ERROR` y no se escribe salida.
- Un `CdtDbtInd` distinto de `CRDT`/`DBIT` es `ERROR`; no se asume un signo en silencio.
- Si `OPBD` y `CLBD` tienen monedas distintas, se registra `WARN`.

### Charset SWIFT

El texto se sanea antes de serializar:

- Los acentos se pliegan: `Société` → `Societe`, `Muñoz` → `Munoz`.
- Solo se conservan los caracteres del set SWIFT:
  `A-Z a-z 0-9 espacio / - ? : ( ) . , ' +`
- Cualquier otro carácter se elimina y se registra en el log con el texto perdido.
- El recorte por longitud también se registra.

---

## Nombres de archivo y colisiones

El nombre de salida está limitado a **32 caracteres** (incluida la extensión), porque el canal SWIFT rechaza nombres más largos.

### Regla normal

```text
<stem del CAMT>_<ddMMyyyy de la última transacción BOOK>.txt
```

Ejemplo:

```text
test_camt053.xml  →  test_camt053_31082026.txt
```

La fecha es la **última transacción `BOOK`** (`BookgDt` o `ValDt`). Si no hay ninguna, se usa la fecha de la corrida. **No** es la fecha de hoy.

### Nombre compacto

Si el nombre normal supera los 32 caracteres, se usa:

```text
<BIC8 destino>_<YYMMDD transacción>_<ddMMyy corrida>.txt
```

Ejemplo:

```text
DEMORCVG_260831_051026.txt
```

- `BIC8`: primeros 8 caracteres alfanuméricos de `AppHdr/To`; si no hay Envelope, de `RECEIVER_ADDRESS`; si queda vacío, `XXXXXXXX`.
- `YYMMDD`: fecha de la última transacción `BOOK`.
- `ddMMyy`: fecha de la corrida.

### Colisiones

Si el destino ya existe, **nunca se sobrescribe**:

```text
Salida/
├── test_camt053_31082026.txt      ← primera corrida
├── test_camt053_31082026(1).txt   ← segunda corrida
└── test_camt053_31082026(2).txt   ← tercera corrida
```

Si el contador `(n)` no cabe en 32 caracteres, se aplica sobre el nombre compacto. La colisión se registra con `WARN`.

### Modo legado `split_files`

Con `OUTPUT_MODE = "split_files"` (no es el default), cada corte que cierra en `:62M:` genera un archivo nuevo con sufijos `_2`, `_3`, ... en lugar de un único archivo. Se conserva por compatibilidad; para uso normal, deja `single_file`.

---

## Configuración

Toda la configuración vive en **`Library/config.py`** y se lee en tiempo de ejecución. No necesitas tocar `camt_to_mt940.py` para adaptar el perfil.

### Perfil y envoltura

| Variable | Default | Descripción |
|---|---|---|
| `PROFILE` | `"fin"` | `"fin"` = perfil FIN validable (recomendado). `"legacy"` = perfil histórico del banco (F21, bloques 3/5). |
| `HEADER_SOURCE` | `"config"` | `"config"` usa `SENDER_LT`/`RECEIVER_ADDRESS`. `"apphdr"` deriva los LT del `AppHdr` del Envelope. |
| `SENDER_LT` | `"DEMOBKMMAXXX"` | LT emisor, 12 caracteres. |
| `RECEIVER_ADDRESS` | `"DEMORCVGXXXX"` | BIC receptor, 12 caracteres con `X` en la posición 9. |
| `MSG_TYPE` | `"940"` | Tipo de mensaje FIN. |
| `PRIORITY` | `"N"` | Prioridad del mensaje. |
| `SYS_SEQ` | `"0000000000"` | Secuencia de sistema del bloque 1 (10 dígitos). |
| `BLOCK1_ENABLED` | `True` | Emite el bloque 1. |
| `BLOCK2_ENABLED` | `True` | Emite el bloque 2. |
| `BLOCK3_ENABLED` | `False` | Emite el bloque 3 (`{108:...}`). |
| `BLOCK5_ENABLED` | `False` | Emite el bloque 5 (`{CHK:...}{S:{COP:P}}`). |
| `EOL` | `"\r\n"` | Fin de línea de los MT940. |
| `MSG_SEPARATOR` | `"$"` | Separador entre mensajes de un mismo archivo. |

### Paginado y archivos

| Variable | Default | Descripción |
|---|---|---|
| `PAGING_ENABLED` | `True` | `True` = paginado por conteo. `False` = un mensaje por `Stmt` (salvo que exceda `MAX_BLOCK4_CHARS`). |
| `ENTRIES_PER_MESSAGE` | `3` | Movimientos por mensaje (entero ≥ 1). |
| `MAX_BLOCK4_CHARS` | `9800` | Tope de tamaño del bloque 4 (red de seguridad). |
| `SPLIT_RESERVE_CHARS` | `120` | Margen reservado para el cierre `:62M:`. |
| `PAGE_REF20_STEP` | `2001` | Retroceso del `:20:` entre mensajes. |
| `OUTPUT_MODE` | `"single_file"` | `"single_file"` = un archivo por CAMT. `"split_files"` = legado `_2`, `_3`. |
| `OUT_EXTENSION` | `".txt"` | Extensión de salida. |
| `FILENAME_MAX_CHARS` | `32` | Tope del nombre con extensión. |
| `COMPACT_BIC_WIDTH` | `8` | Ancho del BIC en el nombre compacto. |
| `PROCESSED_DIRNAME` | `"Procesados"` | Subcarpeta de originales convertidos. |

### Campos `:61:` / `:86:`

| Variable | Default | Descripción |
|---|---|---|
| `PAD_61_REFS` | `True` | Owner/bank a 16 y línea suplementaria a 34. |
| `OWNER_REF_SOURCES` | `("EndToEndId", "InstrId")` | Orden de búsqueda del owner reference. |
| `BANK_REF_SOURCES` | `("TxDtls/Refs/AcctSvcrRef", "Ntry/AcctSvcrRef")` | Orden de búsqueda del bank reference. |
| `REF_FALLBACK` | `"NONE"` | Valor si no hay referencia. |
| `SUPP_LINE_WIDTH` | `34` | Ancho de la línea suplementaria. |
| `FIELD_86_FIRST_WIDTH` | `61` | Contenido de la primera línea del `:86:`. |
| `FIELD_86_NEXT_WIDTH` | `65` | Ancho de las continuaciones. |
| `FIELD_86_MAX_LINES` | `6` | Máximo de líneas del `:86:`. |
| `NARRATIVE_SPLIT_PATTERNS` | `(",\s+", ...)` | Patrones de corte de la narrativa. |
| `COLLAPSE_SPACES` | `False` | `False` conserva los espacios internos. |
| `TX_TYPE_MAP` | `{}` | Mapeo `BkTxCd` → código MT940. Sin match: usa el código de 4 caracteres si es válido; si no, `NMSC` + `WARN`. |
| `FALLBACK_TX_CODE` | `"NMSC"` | Código de respaldo. |

---

## Cómo adaptarlo a tu banco

1. **Identifica tu emisor y receptor.**
   - `SENDER_LT`: 12 caracteres.
   - `RECEIVER_ADDRESS`: 12 caracteres con `X` en la posición 9 (índice 8). Ejemplo válido: `DEMORCVGXXXX`. Ejemplo inválido: `DEMORCVGAXXX`.

2. **Elige el perfil.**
   - Deja `PROFILE = "fin"` para el perfil FIN validable.
   - Usa `"legacy"` solo si tu banco exige el wrapper F21 y los bloques 3/5. Ese perfil es histórico y no es el recomendado para gateways modernos.

3. **Ajusta el paginado.**
   - `ENTRIES_PER_MESSAGE = 3` es el valor del perfil de referencia.
   - Si tu gateway acepta más movimientos por mensaje, súbelo; si exige menos, bájalo.
   - `PAGING_ENABLED = False` genera un único mensaje por `Stmt` (salvo que el bloque exceda `MAX_BLOCK4_CHARS`; útil para reproducir el formato rechazado o para comparar).

4. **Deriva los LT del Envelope (opcional).**
   - `HEADER_SOURCE = "apphdr"` toma `AppHdr/Fr` y `AppHdr/To` y les inserta el LT code (`SENDER_LT_CODE = "A"`, `RECEIVER_LT_CODE = "X"`).
   - Si el CAMT no trae `AppHdr`, cae a `SENDER_LT`/`RECEIVER_ADDRESS`.

5. **Mapea los tipos de transacción (opcional).**
   - Si tu banco usa códigos `BkTxCd` que no son de 4 caracteres alfanuméricos, agrega el mapeo en `TX_TYPE_MAP`.
   - Sin mapeo, se usa `NMSC` y se registra un `WARN` con el código original.

6. **Ajusta los anchos (solo si tu banco lo exige).**
   - `PAD_61_REFS`, `SUPP_LINE_WIDTH`, `FIELD_86_FIRST_WIDTH`, `FIELD_86_NEXT_WIDTH` y `FIELD_86_MAX_LINES`.
   - Cambiar estos valores puede romper la validación SWIFT; hazlo con un golden de tu banco y vuelve a correr los tests.

7. **Valida con tu gateway.**
   - Genera un archivo de prueba y cárgalo en el canal de validación de tu banco.
   - No lo envíes a producción sin revisar la respuesta del gateway.

> **Regla de oro:** si tu banco no exige un cambio, no lo hagas. La configuración por defecto está alineada con el perfil `GOLDEN_940` de la SPEC.

---

## Arquitectura

### Estructura del repositorio

```text
TransformCAMT053toMT940/
├── camt_to_mt940.py          ← CLI y orquestación del lote
├── validate_mt940.py         ← validador externo opcional (requiere mt-940)
├── Library/
│   ├── __init__.py
│   ├── config.py             ← toda la configuración (perfiles, límites, templates)
│   ├── camt053.py            ← parser XML namespace-agnóstico → modelo tipado
│   ├── swift_charset.py      ← fold de acentos, filtrado y truncado SWIFT
│   ├── mt940_builder.py      ← tags del bloque 4 + envoltura + validadores
│   ├── mt940_splitter.py     ← paginado por conteo y por tamaño
│   └── runlog.py             ← registro de incidencias por corrida
├── tests/
│   ├── test_*.py             ← 343 tests (unittest)
│   ├── measure_coverage.py   ← cobertura best-effort con trace
│   └── fixtures/
│       ├── golden/           ← CAMT real, MT940 esperado y ejemplo aceptado
│       ├── plain/            ← CAMT sin Envelope
│       ├── envelope/         ← CAMT con AppHdr
│       ├── multipage/        ← páginas intermedias
│       ├── rejected/         ← forma rechazada (un solo mensaje)
│       └── synthetic_over_limit/
├── Entrada/                  ← carpeta de trabajo (solo se versiona .gitkeep)
├── Salida/                   ← carpeta de salida (solo se versiona .gitkeep)
├── SPEC.md                   ← especificación vigente v2.2
├── LICENSE
├── README.md
├── .gitattributes
└── .gitignore
```

### Responsabilidades

| Módulo | Responsabilidad | Idea clave |
|---|---|---|
| `config` | Constantes, perfiles y templates | Nada de la envoltura está *hard-coded* en el builder. |
| `camt053` | XML → modelo tipado | Coincidencia por *local name*: tolera namespaces y `Envelope`. |
| `swift_charset` | Sanear texto | Pliega acentos, filtra el charset SWIFT y reporta lo perdido. |
| `mt940_builder` | Tags y validación | `:61:` y `:86:` se validan **antes** de serializar. |
| `mt940_splitter` | División en mensajes | Un `:61:` + `:86:` nunca se parte; los saldos se encadenan. |
| `runlog` | Incidencias | Único canal de reporte; el progreso va a `stdout`. |
| `camt_to_mt940` | CLI y lote | Detecta, convierte, escribe, archiva y resume. |

### Orden de construcción

```text
config → swift_charset → camt053 → mt940_builder → mt940_splitter → camt_to_mt940
                                 ↘ runlog ↗
```

### Flujo interno

```text
1. Leer el archivo (bytes) y decodificar UTF-8 / UTF-16 con BOM.
2. Parsear el XML y localizar BkToCstmrStmt (por contenido).
3. Construir el bloque 4 de cada Stmt (tags :20:, :25:, :28C:, :60:, :61:, :86:, :62:, :64:).
4. Validar OPBD ± Σ:61: = CLBD y la gramática de :61:/:86:.
5. Paginar en mensajes de N entradas, encadenando :60M:/:62M:.
6. Envolver cada mensaje con los templates de config y validar bloques 1/2.
7. Resolver un nombre libre (≤32 chars, sin sobrescribir).
8. Escribir el archivo; si falla, borrar parciales y no mover el original.
9. Mover el original a Procesados/.
10. Escribir el log de la corrida.
```

---

## Pruebas

```bash
# Suite completa (343 tests, ~6 s en una máquina de desarrollo)
python -m unittest discover -s tests -v

# Un módulo concreto
python -m unittest discover -s tests -p "test_cli.py" -v
python -m unittest discover -s tests -p "test_integration.py" -v
python -m unittest discover -s tests -p "test_splitter.py" -v

# Cobertura (debe ser ≥ 90 %)
python tests/measure_coverage.py
```

### Cobertura actual

```text
módulo                 cubiertas  ejecutables      %
camt053.py                   168          175 96.0%  OK
mt940_builder.py             290          302 96.0%  OK
mt940_splitter.py            119          123 96.7%  OK
swift_charset.py              55           55 100.0%  OK
```

### Qué cubre cada grupo

| Archivo | Cubre |
|---|---|
| `test_camt053.py` | Parser, namespaces, `Envelope`, múltiples `Stmt`, decodificación. |
| `test_swift_charset.py` | Fold de acentos, filtrado, truncado y wrap. |
| `test_mt940_builder.py` | `:61:`/`:86:` byte a byte, envoltura y validadores. |
| `test_splitter.py` | Límites de paginado, cadena de saldos, `:20:`/`:28C:`. |
| `test_config.py` | Templates, validación de bloques 1/2 y perfiles. |
| `test_runlog.py` | Formato de línea y escaping de saltos. |
| `test_output_name.py` | Compactado a 32, colisiones, `(n)`, sin sobrescritura. |
| `test_integration.py` | Lote completo, fallos de escritura y re-ejecución. |
| `test_cli.py` | El CLI como proceso real (`subprocess`), exit codes, sin BOM. |
| `test_acceptance.py` | Criterios de aceptación, idempotencia y byte-equality. |
| `test_golden_profile.py` | Verificador independiente del golden `finalExample.TXT`. |
| `test_paging.py` | Matriz de paginado y comparación con el MT940 esperado. |
| `test_swift_conformance.py` | Conformidad SWIFT de los validadores. |
| `test_checkpoint_c.py` | Cierre de la envoltura y del perfil FIN. |
| `test_fixtures.py` | Layout y rol de cada fixture. |

> Los tests usan directorios temporales: **nunca** tocan `Entrada/` ni `Salida/` reales.

---

## Validador externo opcional

El proyecto no necesita dependencias, pero incluye un validador que comprueba los MT940 con la librería de terceros [`mt-940`](https://pypi.org/project/mt-940/):

```bash
pip install mt-940

# Valida todos los .txt de Salida/ (excluye logs y ocultos)
python validate_mt940.py

# Valida archivos concretos
python validate_mt940.py Salida/test_camt053_31082026.txt
```

El validador:

- Intenta parsear el archivo con `mt-940`.
- Extrae los saldos de apertura y cierre.
- Suma créditos y resta débitos.
- Comprueba `apertura + créditos − débitos = cierre` con tolerancia de 0.01.

> Es una comprobación **externa** y opcional. No forma parte de la suite de tests ni es necesaria para convertir.

---

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `python no se reconoce como comando` | Python no está en el `PATH`. | Usa `py` en Windows o reinstala Python marcando “Add Python to PATH”. |
| `No se encontraron archivos para convertir en <ruta>` | La carpeta está vacía o una corrida anterior movió los originales a `Procesados/`. | Copia de nuevo los CAMT en `Entrada/`. |
| `Omitido, no es un CAMT.053` | El archivo no contiene `BkToCstmrStmt`, es otro XML o no es XML. | Revisa que sea un estado `camt.053` real. |
| `ERROR: [CAMT.053 inválido: ...]` | Tiene `BkToCstmrStmt` pero el XML está roto o no tiene `Stmt`. | Corrige el XML; el original no se mueve y puedes reintentar. |
| `ERROR: [fallo de conversión: Faltan saldos OPBD/CLBD]` | El `Stmt` no trae saldo de apertura/cierre. | Agrega `OPBD`/`CLBD`; en páginas intermedias, `ITBD`. |
| `ERROR: [fallo de conversión: saldo no cuadra: ...]` | Los movimientos `BOOK` no reconcilian con `CLBD`. | Revisa importes, signos y que solo las entradas `BOOK` estén en el estado. |
| `RECEIVER_ADDRESS inválido ... el LT code debe ser 'X'` | El BIC receptor no cumple la regla del gateway. | Debe tener 12 caracteres con `X` en la posición 9 (por ejemplo `DEMORCVGXXXX`). |
| `destino ya existe, se guarda como: ...(1).txt` | Ya había un archivo con ese nombre. | Es un `WARN`, no un error; se resolvió sin sobrescribir. |
| El nombre de salida no es el de hoy | El nombre usa la última fecha de transacción `BOOK`, no la fecha de corrida. | Busca `test_camt053_31082026.txt`, no el archivo de hoy. |
| El `:86:` perdió texto | La narrativa supera 6 líneas de 65 caracteres. | Revisa el `WARN` `86_OVERFLOW`; el texto perdido queda en el log. |
| Aparecen caracteres raros o faltan acentos | El texto se filtró al charset SWIFT. | Es esperado; revisa el `WARN` de charset con el texto perdido. |
| `PermissionError` al mover a `Procesados/` | El archivo está abierto o bloqueado por otro proceso. | Cierra el programa que lo usa y vuelve a ejecutar. |
| El lote termina con código `1` | Hubo al menos un `ERROR`. | Revisa el log; los archivos con error no se movieron. |

### ¿Dónde está el log?

Cada corrida escribe:

```text
Salida/log_<ddMMyyyy>_<HHmmss>.txt
```

Formato de cada línea:

```text
DD/MM/YYYY HH:MM | archivo.xml | WARN: [regla] + texto perdido
DD/MM/YYYY HH:MM | archivo.xml | ERROR: [mensaje]
DD/MM/YYYY HH:MM | archivo.xml | INFO: [regla] + detalle
```

| Nivel | Significado |
|---|---|
| `INFO` | Aviso de consistencia (por ejemplo, `AppHdr` vs `config`). |
| `WARN` | Se perdió información o se resolvió una colisión; el archivo sí se genera. |
| `ERROR` | No se pudo convertir; el original no se mueve y el lote continúa. |

Si no hubo incidencias, el log puede quedar vacío. Esto es normal.

---

## Alcance y limitaciones

Este proyecto está enfocado en **CAMT.053 → MT940**. No intenta cubrir todo ISO 20022.

- **Solo CAMT.053.** No convierte CAMT.052, CAMT.054, pain.001, etc.
- **Solo entradas `BOOK`.** Las demás se registran con `WARN` y se omiten.
- **`:86:` solo desde `AddtlNtryInf`.** `RmtInf/Ustrd` y `UETR` se reportan como omitidos; no se concatenan.
- **Requiere saldos.** `OPBD` y `CLBD` (o `ITBD` en páginas intermedias) son obligatorios para validar.
- **El saldo debe cuadrar.** No se emite un MT940 con saldos inconsistentes.
- **Codificaciones limitadas.** UTF-8 y UTF-16 con BOM; otras codificaciones producen `ERROR`.
- **Nombres de 32 caracteres.** Es una restricción del canal SWIFT, no una decisión arbitraria.
- **Perfil `legacy`.** El wrapper F21 y los bloques 3/5 se conservan por compatibilidad histórica; no son el perfil recomendado.
- **No transmite.** No se conecta a SWIFT, a un banco ni a una base de datos. Solo lee y escribe archivos.
- **Sin garantía financiera.** Verifica siempre la salida con tu banco o gateway antes de usarla en producción.

### Sobre la SPEC

`SPEC.md` es el documento de diseño vigente (v2.2). Algunas secciones históricas pueden describir estados anteriores del proyecto. Si encuentras una contradicción entre una nota histórica y el comportamiento actual, abre un *issue*: el código y los tests son la referencia ejecutable.

---

## Privacidad

- El conversor **no hace llamadas de red** y no envía datos a ningún servicio.
- Los CAMT de entrada pueden contener datos financieros reales. **No los subas a issues, pull requests ni capturas públicas.**
- Los logs pueden incluir fragmentos de descripciones y referencias. Revísalos antes de compartirlos.
- Para reportar un problema, usa datos sintéticos o anonimiza el archivo.

---

## Contribuir

1. Haz un *fork* del repositorio.
2. Crea una rama para tu cambio:
   ```bash
   git checkout -b feature/mi-mejora
   ```
3. Agrega o ajusta tests. La suite completa debe pasar:
   ```bash
   python -m unittest discover -s tests -v
   python tests/measure_coverage.py
   ```
4. Si cambias comportamiento, actualiza `README.md` y, si aplica, `SPEC.md`.
5. Abre un *pull request* explicando:
   - Qué problema resuelve.
   - Cómo lo probaste.
   - Si cambia el formato de salida o la configuración.

### Estilo del proyecto

- Solo biblioteca estándar de Python.
- Sin dependencias obligatorias.
- Los tests usan `unittest`.
- Los mensajes de log y la documentación están en español.
- Cada pérdida de información debe registrarse; no se descarta texto en silencio.
- Los cambios de salida deben ir acompañados de un test byte a byte cuando sea posible.

### Reportar un bug

Incluye:

- Sistema operativo y versión de Python (`python --version`).
- Comando exacto que ejecutaste.
- Mensaje de consola y fragmento del log (sin datos sensibles).
- Un CAMT sintético o anonimizado que reproduzca el problema.

---

## Licencia

MIT License. Consulta [LICENSE](LICENSE).

Copyright (c) 2026 David Lucio.

---

<div align="center">

**Hecho con Python puro, sin dependencias y con la SPEC como referencia.**

_Cada pérdida de información queda registrada — nada se descarta en silencio._

</div>
