#!/usr/bin/env python3
"""
Aplica votos del admin en candidates/votos.txt.

Formato de cada línea (votable):
  <voto> | <año> | <doi-o--> | <título>

  voto:  ?  pendiente   |   si  aceptar   |   no  rechazar

Ejemplo:
  ?  | 2015 | 10.35670/1667-4545.v15.n1.14907 | Normas categoriales...
  si | 2018 | 10.1234/ejemplo               | Un paper aceptado
  no | 2020 | -                             | Algo que no va

Luego:
  python scripts/apply_votes.py

Los "si" se agregan a data/known.yml y a index.qmd (sección Recién aceptados).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Falta PyYAML: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
VOTOS_PATH = ROOT / "candidates" / "votos.txt"
KNOWN_PATH = ROOT / "data" / "known.yml"
REJECTED_PATH = ROOT / "data" / "rejected.yml"
PENDING_PATH = ROOT / "candidates" / "pending.yml"
INDEX_PATH = ROOT / "index.qmd"

# Bloque en index.qmd donde se agregan los "si" automáticamente
INDEX_MARKER_START = "<!-- che-norma:aceptados:start -->"
INDEX_MARKER_END = "<!-- che-norma:aceptados:end -->"
INDEX_SECTION_TITLE = "## Recién aceptados"

HEADER = """\
# votos.txt — che-Norma! (editá esto para votar)
#
# En cada línea, cambiá el primer campo:
#   ?   = pendiente
#   si  = aceptar (pasa a data/known.yml y a index.qmd)
#   no  = rechazar (pasa a data/rejected.yml)
#
# Formato:
#   voto | año | doi-o-- | título
#
# Aplicar:  python scripts/apply_votes.py
#
"""

VOTE_RE = re.compile(
    r"^\s*(?P<vote>\?|si|no)\s*\|\s*(?P<year>[^|]*)\|\s*(?P<doi>[^|]*)\|\s*(?P<title>.+?)\s*$",
    re.IGNORECASE,
)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {"items": []}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "items" not in data or data["items"] is None:
        data["items"] = []
    return data


def save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    if doi in ("", "-", "—", "–", "none", "null"):
        return None
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def parse_votos(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = VOTE_RE.match(line)
        if not m:
            print(f"  [aviso] línea {lineno} ignorada (formato): {raw[:80]}", file=sys.stderr)
            continue
        year_s = m.group("year").strip()
        year = None
        if year_s and year_s not in ("-", "—"):
            try:
                year = int(re.sub(r"\D", "", year_s)[:4] or 0) or None
            except ValueError:
                year = None
        rows.append(
            {
                "vote": m.group("vote").lower(),
                "year": year,
                "doi": normalize_doi(m.group("doi")),
                "title": m.group("title").strip(),
                "raw": raw,
            }
        )
    return rows


def item_key(doi: str | None, title: str) -> str:
    if doi:
        return f"doi:{doi}"
    return f"title:{(title or '').lower().strip()}"


def has_item(items: list[dict], doi: str | None, title: str) -> bool:
    k = item_key(doi, title)
    for it in items:
        d = normalize_doi(it.get("doi"))
        t = (it.get("title") or "").strip()
        if item_key(d, t) == k:
            return True
        if d and doi and d == doi:
            return True
    return False


def lookup_pending(doi: str | None, title: str) -> dict:
    """Completa campos desde pending.yml si existe."""
    data = load_yaml(PENDING_PATH) if PENDING_PATH.exists() else {"items": []}
    for it in data.get("items") or []:
        d = normalize_doi(it.get("doi"))
        if doi and d == doi:
            return it
        if title and (it.get("title") or "").strip().lower() == title.lower():
            return it
    return {}


def format_vote_line(vote: str, year, doi: str | None, title: str) -> str:
    y = str(year) if year else "-"
    d = doi or "-"
    # una sola línea; pipes del título se aplastan
    t = (title or "").replace("|", "/").strip()
    return f"{vote} | {y} | {d} | {t}"


def write_votos(rows: list[dict], path: Path) -> None:
    lines = [HEADER]
    if not rows:
        lines.append("# (sin candidatos pendientes)\n")
    else:
        for r in rows:
            lines.append(format_vote_line(r["vote"], r.get("year"), r.get("doi"), r.get("title")))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def suggest_markdown(item: dict) -> str:
    authors = item.get("authors") or "Autores, A."
    # estilo de cita del sitio: comas en vez de ;
    authors = authors.replace(";", ",")
    year = item.get("year") or "AAAA"
    title = item.get("title") or "Título"
    doi = normalize_doi(item.get("doi"))
    url = item.get("url") or (f"https://doi.org/{doi}" if doi else "")
    venue = item.get("venue") or ""
    if url:
        line = f"-   {authors} ({year}). [{title}]({url})."
        if venue:
            line += f" *{venue}*."
        return line
    line = f"-   {authors} ({year}). {title}."
    if venue:
        line += f" *{venue}*."
    return line


def index_already_has(qmd: str, item: dict) -> bool:
    doi = normalize_doi(item.get("doi"))
    if doi and doi in qmd.lower():
        return True
    title = (item.get("title") or "").strip()
    if len(title) >= 24 and title[:24].lower() in qmd.lower():
        return True
    return False


def append_accepted_to_index(accepted: list[dict]) -> list[dict]:
    """Agrega bullets al bloque de recién aceptados en index.qmd. Devuelve los escritos."""
    if not accepted or not INDEX_PATH.exists():
        return []

    qmd = INDEX_PATH.read_text(encoding="utf-8")
    to_add = [a for a in accepted if not index_already_has(qmd, a)]
    if not to_add:
        return []

    bullets = "\n".join(suggest_markdown(a) for a in to_add) + "\n"

    if INDEX_MARKER_START in qmd and INDEX_MARKER_END in qmd:
        pre, rest = qmd.split(INDEX_MARKER_START, 1)
        mid, post = rest.split(INDEX_MARKER_END, 1)
        # mid puede tener intro + bullets previos
        if mid.strip() == "" or mid.strip() == INDEX_SECTION_TITLE:
            mid = f"\n\n{INDEX_SECTION_TITLE}\n\nÍtems aceptados por votación; movelos a la sección que corresponda.\n\n"
        new_qmd = pre + INDEX_MARKER_START + mid.rstrip() + "\n\n" + bullets + INDEX_MARKER_END + post
    else:
        block = (
            f"\n\n{INDEX_MARKER_START}\n"
            f"{INDEX_SECTION_TITLE}\n\n"
            f"Ítems aceptados por votación; movelos a la sección que corresponda.\n\n"
            f"{bullets}"
            f"{INDEX_MARKER_END}\n"
        )
        new_qmd = qmd.rstrip() + block

    INDEX_PATH.write_text(new_qmd, encoding="utf-8")
    return to_add


def main() -> int:
    rows = parse_votos(VOTOS_PATH)
    if not rows:
        print(f"No hay votos en {VOTOS_PATH.relative_to(ROOT)}")
        print("Generá la lista con:  python scripts/find_candidates.py")
        return 0

    known = load_yaml(KNOWN_PATH)
    rejected = load_yaml(REJECTED_PATH)

    accepted, refused, pending = [], [], []
    n_si = n_no = n_pending = 0

    for r in rows:
        vote = r["vote"]
        if vote == "?":
            pending.append(r)
            n_pending += 1
            continue

        meta = lookup_pending(r["doi"], r["title"])
        entry = {
            "title": meta.get("title") or r["title"],
            "authors": meta.get("authors"),
            "year": meta.get("year") or r.get("year"),
            "doi": normalize_doi(meta.get("doi")) or r["doi"],
            "url": meta.get("url"),
            "venue": meta.get("venue"),
            "section": None,
            "notes": "vía votos.txt",
        }

        if vote == "si":
            n_si += 1
            if not has_item(known["items"], entry["doi"], entry["title"]):
                known["items"].append(
                    {
                        "title": entry["title"],
                        "authors": entry["authors"],
                        "year": entry["year"],
                        "doi": entry["doi"],
                        "section": "por clasificar",
                        "notes": "aceptado desde votos.txt",
                    }
                )
            accepted.append(entry)
        elif vote == "no":
            n_no += 1
            if not has_item(rejected["items"], entry["doi"], entry["title"]):
                rejected["items"].append(
                    {
                        "title": entry["title"],
                        "doi": entry["doi"],
                        "year": entry["year"],
                    }
                )
            refused.append(entry)

    save_yaml(KNOWN_PATH, known)
    save_yaml(REJECTED_PATH, rejected)

    # Dejar solo pendientes en votos.txt
    write_votos(
        [{"vote": "?", "year": p.get("year"), "doi": p.get("doi"), "title": p.get("title")} for p in pending],
        VOTOS_PATH,
    )

    written = append_accepted_to_index(accepted)

    print(f"Aplicado:  si={n_si}  no={n_no}  quedan pendientes={n_pending}")
    print(f"  known    → {KNOWN_PATH.relative_to(ROOT)} ({len(known['items'])} ítems)")
    print(f"  rejected → {REJECTED_PATH.relative_to(ROOT)} ({len(rejected['items'])} ítems)")
    print(f"  votos    → {VOTOS_PATH.relative_to(ROOT)}")
    if written:
        print(f"  index    → {INDEX_PATH.relative_to(ROOT)} (+{len(written)} en “Recién aceptados”)")
    elif accepted:
        print(f"  index    → sin cambios (ya estaban en index.qmd)")

    if accepted:
        print("\nAceptados:")
        for a in accepted:
            print(f"  · {suggest_markdown(a)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
