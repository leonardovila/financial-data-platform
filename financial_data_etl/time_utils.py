import time as _time
import calendar as _calendar
import datetime as _dt
from typing import Optional

# Helpers de tiempo/validación ------------------------------------------------
def now_ts() -> int:
    return int(_time.time())

def parse_date_to_ts(date_or_ts: Optional[object]) -> Optional[int]:
    if date_or_ts is None:
        return None
    if isinstance(date_or_ts, (int, float)):
        return int(date_or_ts)
    if isinstance(date_or_ts, str):
        try:
            y, m, d = map(int, date_or_ts.split("-"))
            dt = _dt.datetime(y, m, d, 0, 0, 0)
            return int(_calendar.timegm(dt.timetuple()))
        except Exception as exc:
            raise ValueError(
                f"Fecha inválida: {date_or_ts!r}. Usá YYYY-MM-DD o epoch en segundos."
            ) from exc
    raise TypeError("since/until debe ser None, int, float, o 'YYYY-MM-DD'.")