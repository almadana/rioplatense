#!/usr/bin/env python3
"""
Sugiere artículos a partir de una lista de DOIs.

Lee candidates/sugeridos.txt (un DOI por línea), resuelve metadatos
vía OpenAlex (fallback Crossref), y los agrega a:
  - candidates/votos.txt   (voto ?)
  - candidates/pending.yml (detalle para apply_votes)

No aplica score heurístico: si el admin lo escribió, entra a la cola de votos.
Omite ítems ya en data/known.yml, data/rejected.yml o votos.txt.

Uso:
  python scripts/from_dois.py
  python scripts/from_dois.py path/a/otra-lista.txt
  python scripts/from_dois.py --mailto tu@email.org
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Falta PyYAML: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_votes import (  # noqa: E402
    KNOWN_PATH,
    PENDING_PATH,
    REJECTED_PATH,
    VOTOS_PATH,
    has_item,
    item_key,
    load_yaml,
    normalize_doi,
    parse_votos,
    write_votos,
)

DEFAULT_SUGERIDOS = ROOT / "candidates" / "sugeridos.txt"
USER_AGENT = "che-Norma-from-dois/1.0 (https://github.com/almadana/rioplatense)"
OPENALEX_WORK = "https://api.openalex.org/works/"
CROSSREF_WORK = "https://api.crossref.org/works/"


def parse_doi_file(path: Path) -> list[str]:
    """Extrae DOIs activos (no comentarios)."""
    if not path.exists():
        return []
    dois: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # permitir "doi: 10.x" o URL
        line = re.sub(r"^doi:\s*", "", line, flags=re.I)
        doi = normalize_doi(line)
        if not doi:
            print(f"  [aviso] no es DOI: {raw[:80]}", file=sys.stderr)
            continue
        if doi not in seen:
            seen.add(doi)
            dois.append(doi)
    return dois


def http_json(url: str, mailto: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if mailto and "openalex.org" in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}mailto={urllib.parse.quote(mailto)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def invert_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def work_from_openalex(w: dict) -> dict:
    doi = normalize_doi(w.get("doi"))
    authors = []
    for a in (w.get("authorships") or [])[:12]:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    abstract = invert_abstract(w.get("abstract_inverted_index"))
    oa = w.get("open_access") or {}
    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}
    return {
        "title": w.get("title") or w.get("display_name") or "",
        "authors": "; ".join(authors),
        "year": w.get("publication_year"),
        "doi": doi,
        "url": primary.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else w.get("id")),
        "openalex_id": w.get("id"),
        "venue": source.get("display_name"),
        "abstract_snippet": (abstract[:400] + "…") if abstract and len(abstract) > 400 else abstract,
        "is_oa": bool(oa.get("is_oa")),
        "oa_url": oa.get("oa_url"),
        "cited_by": w.get("cited_by_count"),
        "source_query": "sugeridos.txt",
        "relevance_score": 99,  # sugerido a mano
    }


def work_from_crossref(msg: dict) -> dict:
    doi = normalize_doi(msg.get("DOI"))
    authors = []
    for a in msg.get("author") or []:
        given = a.get("given") or ""
        family = a.get("family") or ""
        name = f"{given} {family}".strip() or a.get("name")
        if name:
            authors.append(name)
    title_list = msg.get("title") or [""]
    title = title_list[0] if title_list else ""
    year = None
    for key in ("published-print", "published-online", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            year = parts[0][0]
            break
    container = msg.get("container-title") or [""]
    return {
        "title": title,
        "authors": "; ".join(authors[:12]),
        "year": year,
        "doi": doi,
        "url": msg.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
        "openalex_id": None,
        "venue": container[0] if container else None,
        "abstract_snippet": None,
        "is_oa": False,
        "oa_url": None,
        "cited_by": msg.get("is-referenced-by-count"),
        "source_query": "sugeridos.txt (crossref)",
        "relevance_score": 99,
    }


def fetch_doi(doi: str, mailto: str | None) -> dict | None:
    # OpenAlex
    oa_id = urllib.parse.quote(f"https://doi.org/{doi}", safe="")
    try:
        w = http_json(f"{OPENALEX_WORK}{oa_id}", mailto)
        return work_from_openalex(w)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  [aviso] OpenAlex HTTP {e.code} para {doi}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"  [aviso] OpenAlex red: {e.reason} para {doi}", file=sys.stderr)

    # Crossref fallback
    try:
        data = http_json(CROSSREF_WORK + urllib.parse.quote(doi))
        msg = data.get("message") or {}
        if msg:
            return work_from_crossref(msg)
    except urllib.error.HTTPError as e:
        print(f"  [aviso] Crossref HTTP {e.code} para {doi}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"  [aviso] Crossref red: {e.reason} para {doi}", file=sys.stderr)

    return None


def mark_sugeridos_processed(path: Path, processed: list[str], failed: list[str]) -> None:
    """Reescribe la lista: fallidos activos, enviados comentados, header conservado."""
    header = [
        "# sugeridos.txt — DOIs propuestos a mano (che-Norma!)",
        "#",
        "# Un DOI por línea. Acepta también URL https://doi.org/...",
        "# Luego: python scripts/from_dois.py",
        "# Los resueltos quedan como:  # enviado: 10.xxxx/...",
        "#",
    ]

    prev_enviados: list[str] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            s = raw.strip()
            if s.startswith("# enviado:"):
                d = normalize_doi(s[len("# enviado:") :].strip())
                if d and d not in prev_enviados:
                    prev_enviados.append(d)

    enviados: list[str] = []
    for d in prev_enviados + processed:
        if d and d not in enviados:
            enviados.append(d)

    lines = header + [""]
    for d in failed:
        lines.append(d)
    if failed:
        lines.append("")
    for d in enviados:
        lines.append(f"# enviado: {d}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def merge_into_pending(works: list[dict]) -> None:
    data = load_yaml(PENDING_PATH)
    existing_keys = set()
    for it in data.get("items") or []:
        existing_keys.add(item_key(normalize_doi(it.get("doi")), it.get("title") or ""))

    for w in works:
        k = item_key(w.get("doi"), w.get("title") or "")
        if k in existing_keys:
            continue
        data.setdefault("items", []).append(w)
        existing_keys.add(k)

    data["count"] = len(data.get("items") or [])
    data["generated_at"] = date.today().isoformat()
    data.setdefault("source", "mixed")
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def merge_into_votos(works: list[dict]) -> int:
    existing = parse_votos(VOTOS_PATH) if VOTOS_PATH.exists() else []
    by_key: dict[str, dict] = {}
    for r in existing:
        by_key[item_key(r.get("doi"), r.get("title") or "")] = {
            "vote": r["vote"],
            "year": r.get("year"),
            "doi": r.get("doi"),
            "title": r.get("title"),
        }

    added = 0
    for w in works:
        doi = w.get("doi")
        title = w.get("title") or ""
        k = item_key(doi, title)
        if k in by_key:
            continue
        by_key[k] = {
            "vote": "?",
            "year": w.get("year"),
            "doi": doi,
            "title": title,
        }
        added += 1

    write_votos(list(by_key.values()), VOTOS_PATH)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Suma DOIs sugeridos a la cola de votos")
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=DEFAULT_SUGERIDOS,
        help=f"Lista de DOIs (default: {DEFAULT_SUGERIDOS.relative_to(ROOT)})",
    )
    parser.add_argument("--mailto", default=None, help="Email para OpenAlex")
    parser.add_argument("--sleep", type=float, default=0.25)
    args = parser.parse_args()

    mailto = args.mailto or os.environ.get("OPENALEX_MAILTO")
    path = args.file if args.file.is_absolute() else ROOT / args.file

    dois = parse_doi_file(path)
    if not dois:
        print(f"No hay DOIs activos en {path}")
        print("Agregá uno por línea y volvé a correr.")
        return 0

    known = load_yaml(KNOWN_PATH)
    rejected = load_yaml(REJECTED_PATH)
    known_dois = {normalize_doi(i.get("doi")) for i in known["items"] if i.get("doi")}
    known_dois |= {normalize_doi(i.get("doi")) for i in rejected["items"] if i.get("doi")}
    known_dois.discard(None)

    existing_votos = parse_votos(VOTOS_PATH) if VOTOS_PATH.exists() else []
    voto_dois = {r.get("doi") for r in existing_votos if r.get("doi")}

    print(f"DOIs en lista: {len(dois)}")
    works: list[dict] = []
    processed: list[str] = []
    failed: list[str] = []
    skipped = 0

    for doi in dois:
        if doi in known_dois:
            print(f"  · skip (ya conocido/rechazado): {doi}")
            processed.append(doi)
            skipped += 1
            continue
        if doi in voto_dois:
            print(f"  · skip (ya en votos): {doi}")
            processed.append(doi)
            skipped += 1
            continue
        if has_item(known["items"], doi, "") or has_item(rejected["items"], doi, ""):
            print(f"  · skip (catálogo): {doi}")
            processed.append(doi)
            skipped += 1
            continue

        print(f"  · fetch {doi}")
        w = fetch_doi(doi, mailto)
        time.sleep(args.sleep)
        if not w:
            print(f"    !! no encontrado")
            failed.append(doi)
            continue
        print(f"    → {w.get('year')} — {w.get('title')}")
        works.append(w)
        processed.append(doi)

    if works:
        merge_into_pending(works)
        n = merge_into_votos(works)
    else:
        n = 0

    if path.resolve() == DEFAULT_SUGERIDOS.resolve() or path.name == "sugeridos.txt":
        mark_sugeridos_processed(path, processed, failed)
    elif processed:
        # para lista alternativa, solo reportamos
        pass

    print(f"\nListo: agregados a votos={n}  omitidos={skipped}  fallidos={len(failed)}")
    print(f"  votos  → {VOTOS_PATH.relative_to(ROOT)}")
    print(f"  pending→ {PENDING_PATH.relative_to(ROOT)}")
    print(f"  lista  → {path}")
    if n:
        print("\nSiguiente paso: editá candidates/votos.txt y corré:")
        print("  python scripts/apply_votes.py")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
