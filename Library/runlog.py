# -*- coding: utf-8 -*-
"""Registro de incidencias por corrida (WARN/ERROR/INFO + texto perdido).

Es el único canal de reporte del convertidor (nunca print). Cada corrida
produce un archivo `log_<ddMMyyyy>_<HHmmss>.txt` en el directorio de
salida con una línea por evento:

    DD/MM/YYYY HH:MM | archivo.xml | WARN: [regla] + texto perdido
    DD/MM/YYYY HH:MM | archivo.xml | ERROR: [mensaje]
    DD/MM/YYYY HH:MM | archivo.xml | INFO: [regla] + detalle
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

_DATE = "%d/%m/%Y %H:%M"
_WHITESPACE_CRLF = re.compile(r"[\r\n\t]+")


@dataclass(frozen=True)
class LogEvent:
    """Un evento de incidencia de la corrida."""

    when: datetime
    filename: str
    level: str
    text: str

    def __str__(self) -> str:
        return (
            f"{self.when.strftime(_DATE)} | {self.filename} "
            f"| {self.level}: {self.text}"
        )


class RunLog:
    """Acumula WARN/ERROR de una corrida y los escribe en un archivo."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now: Callable[[], datetime] = now or datetime.now
        self.events: list[LogEvent] = []

    @staticmethod
    def _one_line(value: str) -> str:
        return _WHITESPACE_CRLF.sub(" ", value).strip()

    def warn(self, filename: str, rule: str, lost_text: str | None = None) -> None:
        """Registra un WARN. rule es la regla; lost_text, lo perdido."""
        text = f"[{self._one_line(rule)}]"
        if lost_text is not None:
            text += f" + {self._one_line(lost_text)}"
        self.events.append(LogEvent(
            when=self._now(), filename=self._one_line(filename),
            level="WARN", text=text,
        ))

    def error(self, filename: str, message: str) -> None:
        """Registra un ERROR con el mensaje descriptivo."""
        self.events.append(LogEvent(
            when=self._now(), filename=self._one_line(filename),
            level="ERROR", text=f"[{self._one_line(message)}]",
        ))

    def info(self, filename: str, rule: str, detail: str | None = None) -> None:
        """Registra un INFO. rule es la regla; detail, el contexto."""
        text = f"[{self._one_line(rule)}]"
        if detail is not None:
            text += f" + {self._one_line(detail)}"
        self.events.append(LogEvent(
            when=self._now(), filename=self._one_line(filename),
            level="INFO", text=text,
        ))

    def write(self, output_dir: Path) -> Path:
        """Escribe el log de la corrida en output_dir y devuelve su Path."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        run_at = self._now()
        name = f"log_{run_at.strftime('%d%m%Y_%H%M%S')}.txt"
        path = output_dir / name
        lines = [str(event) for event in self.events]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path