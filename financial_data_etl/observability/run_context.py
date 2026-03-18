# financial_data_etl/observability/run_context.py
from __future__ import annotations
import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Iterator, List, IO
from contextlib import contextmanager
from financial_data_etl.storage.paths import LOGS_DIR
from contextvars import ContextVar

# Variable global segura para hilos y asincronismo
_span_stack_var: ContextVar[tuple] = ContextVar("span_stack", default=())

# Timestamp ISO en timezone local del sistema (ideal para operador humano).
# Incluye offset (ej: -03:00) si el sistema tiene TZ configurado.
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()

# Convierte “lo que sea” a algo serializable en JSON (primitivos, listas, dicts). Si no puede, hace repr(obj). Ventaja: nunca explota el logger porque le pasaste un Path, un datetime, un Exception, un set, etc. Esto es crítico: el logger no puede caerse.
def _safe_json(obj: Any) -> Any:
    """Best-effort JSON-serializable conversion (no magic, no deep recursion)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    return repr(obj)

@dataclass
class RunContext:
    run_name: str # nombre humano (ej: “tv_websocket_scraper”, “macro_snapshot”).
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d_%H-%M-%S")) 
    logs_dir: Path = field(default_factory=lambda: LOGS_DIR)
    log_path: Path = field(init=False) # se calcula en __post_init__.
    report_path: Path = field(init=False)
    report: Dict[str, Any] = field(default_factory=dict) # diccionario resumen (stages + estado final).
    _t0: float = field(default_factory=time.perf_counter) # contador de perf para duración precisa (mejor que time.time() para medir).
    _log_fh: Optional[IO[str]] = field(default=None, init=False, repr=False)
    console: bool = True          # imprime cada evento en consola
    console_flush: bool = False   # si querés ver output inmediato sí o sí

    def __post_init__(self) -> None:
        self.log_path = self.logs_dir / f"RUN_{self.run_id}_{self.run_name}.jsonl"
        self._log_fh = open(self.log_path, "a", encoding="utf-8")
        self.report_path = self.logs_dir / f"REPORT_{self.run_id}_{self.run_name}.json"
        # Inicializa report shell: started_at, status=running, stages={}
        self.report = {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "started_at": _now_iso(),
            "status": "running",
            "stages": {},
        }
        self.event("run_start", level="INFO", run_name=self.run_name) # Emite un evento run_start

    # ts, run_id, level, event, stage, y el resto de data sanitizado. Luego lo escribe como UNA línea JSON + \n.
    # Este es el corazón: “append-only log”. 
    def event(self, name: str, *, level: str = "INFO", stage: Optional[str] = None, **data: Any) -> None:
        rec = {
            "ts": _now_iso(),
            "run_id": self.run_id,
            "level": level,
            "event": name,
            "stage": stage,
            **_safe_json(data),
        }
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        if self.console:
            print(line, end="")
            if self.console_flush:
                try:
                    import sys
                    sys.stdout.flush()
                except Exception:
                    pass
        if self._log_fh is None:
            # fallback defensivo (por si alguien instancia mal)
            self._log_fh = open(self.log_path, "a", encoding="utf-8")
        self._log_fh.write(line)
    
    def stage_ok(self, stage: str, **data: Any) -> None:
        payload = {"status": "ok", **_safe_json(data)}
        self.report["stages"][stage] = payload # Guarda en report["stages"][stage]
        self.event("stage_ok", level="INFO", stage=stage, **payload) # Emite evento stage_ok con ese payload
        # O sea: queda tanto en el resumen final como en el stream.

    # Traceback tomado del exception real (funciona aunque se llame fuera del except).
    def stage_err(self, stage: str, exc: BaseException, **data: Any) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        payload = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error_msg": str(exc),
            "traceback": tb,
            **_safe_json(data),
        } # Arma payload con status error + tipo + msg + traceback + data
        self.report["stages"][stage] = payload # Guarda en report["stages"][stage]
        self.event("stage_err", level="ERROR", stage=stage, **payload) # Emite evento stage_err nivel ERROR

    @property
    def _span_stack(self) -> list:
        return list(_span_stack_var.get())

    @contextmanager
    def span(self, stage: str, **kwargs) -> Iterator[None]:
        current = _span_stack_var.get()
        token = _span_stack_var.set(current + (stage,))
        
        t0 = time.perf_counter()
        parent_stage = current[-1] if current else None

        self.event("stage_start", stage=stage, parent_stage=parent_stage, **kwargs)

        status = "error"
        try:
            yield
            status = "ok"
        except Exception as e:
            self.event("stage_error", level="ERROR", stage=stage, error=str(e))
            raise
        finally:
            dt = time.perf_counter() - t0
            
            # Guardamos la métrica en el reporte JSON (arregla el reporte vacío)
            if "stages" not in self.report:
                self.report["stages"] = {}
                
            self.report["stages"][stage] = {
                "status": status,
                "duration_s": round(dt, 6),
                "parent_stage": parent_stage,
                **kwargs
            }

            if status == "ok":
                self.event(
                    "stage_ok", 
                    stage=stage, 
                    status=status, 
                    duration_s=round(dt, 6), 
                    parent_stage=parent_stage, 
                    **kwargs
                )
            _span_stack_var.reset(token)

    def write_report(self) -> None:
        with open(self.report_path, "w", encoding="utf-8") as f:
            json.dump(_safe_json(self.report), f, ensure_ascii=False, indent=2)

    def finalize(self, *, status: str) -> Dict[str, Any]:
        if status not in ("success", "error"):
            status = "error"
        dt = time.perf_counter() - self._t0 # Calcula duración con perf_counter
        self.report["finished_at"] = _now_iso() # Setea finished_at, duration_s, status
        self.report["duration_s"] = round(dt, 6) 
        self.report["status"] = status
        self.event("run_finish", level="INFO" if status == "success" else "ERROR", status=status, duration_s=self.report["duration_s"]) # Emite evento run_finish con status/duración
        if self._log_fh is not None:
            try:
                self._log_fh.flush()
            finally:
                self._log_fh.close()
                self._log_fh = None
        self.write_report()
        return self.report
    
    def __del__(self) -> None:
        try:
            if self._log_fh is not None:
                self._log_fh.close()
        except Exception:
            pass