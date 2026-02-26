from typing import Dict, Any, List

def parse_ohlcv(data: Dict[str, Any]) -> List[List[float]]:
    """
    Convierte 'timescale_update' (formato sds_1.s[].v) en [[ts,o,h,l,c,v], ...]
    """
    try:
        seq = data.get("p", [])
        # Esperamos: ["cs_...", { "sds_1": { "s": [ {"i":0,"v":[ts,o,h,l,c,v]}, ... ] , ... } }, {...}]
        if not (isinstance(seq, list) and len(seq) >= 2 and isinstance(seq[1], dict)):
            return []
        sds = seq[1].get("sds_1", {})
        s_list = sds.get("s", [])
        out: List[List[float]] = []
        for item in s_list:
            v = item.get("v")
            if not isinstance(v, list) or len(v) < 5:
                continue

            # Índices (ej RUT) suelen venir sin volumen: [ts,o,h,l,c]
            ts, o, h, l, c = v[:5]
            vol = v[5] if len(v) >= 6 else 0.0  # sentinel

            out.append([int(ts), float(o), float(h), float(l), float(c), float(vol)])
        return out
    except Exception as e:
        #LOG.warning(f"No pude extraer candles de timescale_update: {e}")
        return []