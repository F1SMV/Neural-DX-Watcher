"""expedition.py — croise briefing (RSS/HTML) et spots DX Wanted. Autonome, sans dépendance."""
import re
from datetime import date

_CALL_RE = re.compile(r'(?<![A-Z0-9/])([A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](?:/[A-Z0-9]{1,4})?)(?![A-Z0-9])')
_END_RE = re.compile(r'(?:→|->|until|to)\s*(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})', re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}


def base_call(call):
    """'DL/RI1FJZ/P' -> 'RI1FJZ' ; 'W1AW/4' -> 'W1AW' ; None/'' -> ''."""
    if not call or not isinstance(call, str):
        return ""
    parts = [p for p in call.upper().strip().split("/") if p]
    parts = [p for p in parts if any(c.isdigit() for c in p)] or parts
    return max(parts, key=len) if parts else ""


def _end_date(text):
    m = _END_RE.search(text or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(2).lower())
    try:
        return date(int(m.group(3)), mon, int(m.group(1))) if mon else None
    except ValueError:
        return None


def extract_expeditions(data, today=None):
    """Parcourt récursivement n'importe quelle structure JSON du briefing.
    Retourne {CALL: {"title","link","until"}} ; ignore les expéditions terminées."""
    today = today or date.today()
    found = {}

    def walk(node):
        if isinstance(node, dict):
            title = node.get("title")
            if isinstance(title, str):
                until = _end_date(title)
                if not (until and until < today):
                    for c in _CALL_RE.findall(title.upper()):
                        b = base_call(c)
                        if b and b not in found:
                            found[b] = {"title": title,
                                        "link": node.get("link", ""),
                                        "until": until.isoformat() if until else None}
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return found


def match_calls(calls, expeditions):
    """calls: itérable de callsigns (spots wanted). Retourne {call_original: info}."""
    out = {}
    for c in calls or []:
        info = expeditions.get(base_call(c))
        if info:
            out[c] = info
    return out
