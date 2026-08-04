#!/usr/bin/env python3
"""
Busca candidatos de normas / recursos psicolingüísticos del español rioplatense
vía OpenAlex (índice académico abierto; comparable a Scholar sin scraping).

Flujo:
  1. Lee data/known.yml y data/rejected.yml
  2. Consulta OpenAlex con varias queries
  3. Filtra ya listados / rechazados
  4. Escribe candidates/pending.yml

Uso:
  python scripts/find_candidates.py
  python scripts/find_candidates.py --from-year 2015 --max-per-query 50
  python scripts/find_candidates.py --mailto tu@email.org   # cortesía OpenAlex
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "Falta PyYAML. Instalalo con:\n  pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
KNOWN_PATH = ROOT / "data" / "known.yml"
REJECTED_PATH = ROOT / "data" / "rejected.yml"
PENDING_PATH = ROOT / "candidates" / "pending.yml"
VOTOS_PATH = ROOT / "candidates" / "votos.txt"

# Import local ballot helpers without packaging
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from apply_votes import (  # type: ignore
        format_vote_line,
        item_key,
        parse_votos,
        write_votos,
    )
except ImportError:
    parse_votos = None  # type: ignore

OPENALEX = "https://api.openalex.org/works"
USER_AGENT = "che-Norma-finder/1.0 (https://github.com/almadana/rioplatense; academic index maintenance)"

# Queries orientadas a normas, recursos y español rioplatense / argentino
QUERIES = [
    "rioplatense normas",
    "rioplatense Spanish norms",
    '"Rioplatense Spanish" psycholinguistic',
    '"Spanish" "Argentina" "free association" norms',
    '"español argentino" normas léxicas',
    '"Argentine Spanish" lexical norms',
    '"semantic feature" norms Argentina Spanish',
    "normas categoriales español rioplatense",
    "picture norms Argentine Spanish",
    "asociación semántica rioplatense",
]

# Geografía / variedad (necesarios pero insuficientes solos)
GEO_TERMS = [
    "rioplatense",
    "argentin",
    "buenos aires",
    "uruguay",
    "montevideo",
    "córdoba",
    "cordoba",
    "porteño",
    "porteña",
]

# Dominio psicolingüístico / normas (sin al menos uno de estos, se descarta)
DOMAIN_TERMS = [
    "lexical norm",
    "lexical norms",
    "normas léxic",
    "normas lexical",
    "free association",
    "word association",
    "asociación libre",
    "asociacion libre",
    "asociación semántica",
    "asociacion semantica",
    "semantic feature",
    "feature production",
    "rasgos semántic",
    "rasgos semantic",
    "category norm",
    "categorical norm",
    "normas categorial",
    "picture naming",
    "picture norm",
    "normas de imágenes",
    "normas de imagenes",
    "psycholinguist",
    "psicolingüíst",
    "psicolinguist",
    "age of acquisition",
    "edad de adquisición",
    "edad de adquisicion",
    "subjective frequency",
    "frecuencia subjetiva",
    "concreteness rating",
    "concretud",
    "imageability",
    "imaginabilidad",
    "naming latency",
    "behavior research methods",
    "normas de",
    "normative data",
    "datos normativos",
    "corpus léxico",
    "lexical database",
    "word norms",
    "word association norms",
    "semantic norms",
    "hayling",
    "tecle",
]


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {"items": []}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "items" not in data or data["items"] is None:
        data["items"] = []
    return data


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similar(a: str, b: str, threshold: float = 0.88) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def collect_fingerprints(items: list[dict]) -> tuple[set[str], list[str]]:
    dois: set[str] = set()
    titles: list[str] = []
    for item in items:
        doi = normalize_doi(item.get("doi"))
        if doi:
            dois.add(doi)
        title = item.get("title")
        if title:
            titles.append(title)
    return dois, titles


def is_known(work: dict, known_dois: set[str], known_titles: list[str]) -> bool:
    doi = normalize_doi(work.get("doi"))
    if doi and doi in known_dois:
        return True
    title = work.get("title") or ""
    return any(title_similar(title, kt) for kt in known_titles)


def openalex_get(url: str, mailto: str | None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if mailto:
        # OpenAlex recomienda mailto en User-Agent o query para rate limit cortés
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}mailto={urllib.parse.quote(mailto)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_openalex(
    query: str,
    from_year: int,
    per_page: int,
    mailto: str | None,
) -> list[dict]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{from_year}-01-01",
        "per_page": str(per_page),
        "sort": "relevance_score:desc",
    }
    url = f"{OPENALEX}?{urllib.parse.urlencode(params)}"
    try:
        data = openalex_get(url, mailto)
    except urllib.error.HTTPError as e:
        print(f"  [aviso] OpenAlex HTTP {e.code} para query={query!r}", file=sys.stderr)
        return []
    except urllib.error.URLError as e:
        print(f"  [aviso] red: {e.reason} para query={query!r}", file=sys.stderr)
        return []

    results = []
    for w in data.get("results") or []:
        results.append(parse_work(w, query))
    return results


def parse_work(w: dict, source_query: str) -> dict:
    doi = None
    raw_doi = w.get("doi")
    if raw_doi:
        doi = normalize_doi(raw_doi)

    authors = []
    for a in (w.get("authorships") or [])[:12]:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)

    year = w.get("publication_year")
    title = w.get("title") or w.get("display_name") or ""

    abstract = invert_abstract(w.get("abstract_inverted_index"))
    oa = w.get("open_access") or {}
    primary = w.get("primary_location") or {}
    source = primary.get("source") or {}

    return {
        "title": title,
        "authors": "; ".join(authors),
        "year": year,
        "doi": doi,
        "url": (primary.get("landing_page_url") or w.get("id") or ""),
        "openalex_id": w.get("id"),
        "venue": source.get("display_name"),
        "abstract_snippet": (abstract[:400] + "…") if abstract and len(abstract) > 400 else abstract,
        "is_oa": bool(oa.get("is_oa")),
        "oa_url": oa.get("oa_url"),
        "cited_by": w.get("cited_by_count"),
        "source_query": source_query,
        "relevance_score": score_relevance(title, abstract),
    }


def invert_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    # abstract_inverted_index: {word: [positions]}
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


# Si no hay ancla rioplatense/argentina, descartar variedades lejanas
NEGATIVE_VARIETY = [
    "português brasileiro",
    "portuguese brazilian",
    "brazilian portuguese",
    "portugués brasileño",
    "galician",
    "galego",
    "catalan",
    "catalán",
    "mexican spanish",
    "español mexicano",
    "chilean",
    "chileno",
    "colombian",
    "colombiano",
    "peruvian",
    "peruano",
    "spain spanish",
    "español peninsular",
    "castilian",
]


def score_relevance(title: str, abstract: str) -> int:
    """Requiere señal de dominio (normas/psicoling); la geo suma bonus.

    Sin término de dominio, score=0 (evita historia, frontera, etc. con solo 'rioplatense').
    """
    tl = (title or "").lower()
    text = f"{title} {abstract}".lower()

    has_local_geo = any(t in text for t in ("rioplatense", "argentin", "uruguay", "montevideo", "buenos aires", "porteñ"))
    if not has_local_geo and any(n in text for n in NEGATIVE_VARIETY):
        return 0

    domain_hits = 0
    for term in DOMAIN_TERMS:
        if term in text:
            domain_hits += 3 if term in tl else 1
    if domain_hits == 0:
        return 0

    geo_hits = 0
    for term in GEO_TERMS:
        if term in text:
            geo_hits += 3 if term in tl else 1

    # Preferimos trabajos con anclaje geográfico; si no hay geo, score bajo
    # pero no cero (pueden ser normas de español argentino omitiendo el gentilicio).
    score = domain_hits + geo_hits
    if geo_hits == 0:
        score = max(1, score // 3)

    if "rioplatense" in tl and domain_hits:
        score += 4
    if "normas" in tl or "norms" in tl:
        score += 2
    return score


def format_markdown(candidates: list[dict]) -> str:
    lines = [
        "# Candidatos para revisión — che-Norma!",
        "",
        f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total: {len(candidates)}",
        "",
        "Marcá cada ítem: **aceptar** (agregar a `index.qmd` + `data/known.yml`) "
        "o **rechazar** (agregar a `data/rejected.yml`).",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        doi_line = f"https://doi.org/{c['doi']}" if c.get("doi") else "(sin DOI)"
        lines.extend(
            [
                f"## {i}. {c.get('title') or '(sin título)'}",
                "",
                f"- **Autores:** {c.get('authors') or '—'}",
                f"- **Año:** {c.get('year') or '—'}",
                f"- **DOI:** {doi_line}",
                f"- **Venue:** {c.get('venue') or '—'}",
                f"- **URL:** {c.get('url') or '—'}",
                f"- **Open access:** {c.get('oa_url') or ('sí' if c.get('is_oa') else 'no')}",
                f"- **Citas:** {c.get('cited_by') if c.get('cited_by') is not None else '—'}",
                f"- **Score heurístico:** {c.get('relevance_score', 0)}",
                f"- **Query:** {c.get('source_query')}",
                "",
            ]
        )
        if c.get("abstract_snippet"):
            lines.append(f"> {c['abstract_snippet']}")
            lines.append("")
    return "\n".join(lines)


def merge_unique(works: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for w in works:
        doi = normalize_doi(w.get("doi"))
        key = f"doi:{doi}" if doi else f"title:{normalize_title(w.get('title'))}"
        if not key.endswith(":") and key not in by_key:
            by_key[key] = w
        elif key not in by_key:
            continue
        else:
            # conservar el de mayor score / más citas
            prev = by_key[key]
            if (w.get("relevance_score") or 0) > (prev.get("relevance_score") or 0):
                by_key[key] = w
    return list(by_key.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca candidatos nuevos para che-Norma!")
    parser.add_argument("--from-year", type=int, default=2000, help="Año mínimo de publicación")
    parser.add_argument("--max-per-query", type=int, default=40, help="Resultados por query OpenAlex")
    parser.add_argument("--min-score", type=int, default=3, help="Score mínimo de relevancia heurística")
    parser.add_argument(
        "--mailto",
        default=None,
        help="Email de contacto para OpenAlex (recomendado; también env OPENALEX_MAILTO)",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ROOT / "candidates" / "pending.md",
        help="Ruta del resumen Markdown para revisión",
    )
    parser.add_argument(
        "--yaml-out",
        type=Path,
        default=PENDING_PATH,
        help="Ruta del YAML de candidatos",
    )
    parser.add_argument("--sleep", type=float, default=0.35, help="Pausa entre queries (seg)")
    args = parser.parse_args()

    import os

    mailto = args.mailto or os.environ.get("OPENALEX_MAILTO")

    known = load_yaml(KNOWN_PATH)
    rejected = load_yaml(REJECTED_PATH)
    known_dois, known_titles = collect_fingerprints(known["items"] + rejected["items"])

    print(f"Conocidos: {len(known['items'])} | Rechazados: {len(rejected['items'])}")
    print(f"Buscando en OpenAlex ({len(QUERIES)} queries)…")

    raw: list[dict] = []
    for q in QUERIES:
        print(f"  · {q}")
        batch = search_openalex(q, args.from_year, args.max_per_query, mailto)
        raw.extend(batch)
        time.sleep(args.sleep)

    unique = merge_unique(raw)
    candidates = []
    for w in unique:
        if is_known(w, known_dois, known_titles):
            continue
        if (w.get("relevance_score") or 0) < args.min_score:
            continue
        candidates.append(w)

    candidates.sort(
        key=lambda x: (-(x.get("relevance_score") or 0), -(x.get("year") or 0), x.get("title") or "")
    )

    payload = {
        "generated_at": date.today().isoformat(),
        "source": "openalex",
        "queries": QUERIES,
        "from_year": args.from_year,
        "min_score": args.min_score,
        "count": len(candidates),
        "items": candidates,
    }

    args.yaml_out.parent.mkdir(parents=True, exist_ok=True)
    with args.yaml_out.open("w", encoding="utf-8") as f:
        yaml.dump(payload, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    md = format_markdown(candidates)
    with args.md_out.open("w", encoding="utf-8") as f:
        f.write(md)

    # votos.txt: merge con pendientes previos (p.ej. de sugeridos.txt)
    prev_by_key: dict[str, dict] = {}
    if parse_votos is not None and VOTOS_PATH.exists():
        for r in parse_votos(VOTOS_PATH):
            prev_by_key[item_key(r.get("doi"), r.get("title") or "")] = {
                "vote": r["vote"] if r["vote"] in ("?", "si", "no") else "?",
                "year": r.get("year"),
                "doi": r.get("doi"),
                "title": r.get("title"),
            }

    ballot_rows: dict[str, dict] = dict(prev_by_key)
    for c in candidates:
        doi = normalize_doi(c.get("doi"))
        title = c.get("title") or ""
        k = item_key(doi, title)
        if k in ballot_rows:
            # conservar voto humano; refrescar metadatos de título/año si faltan
            if not ballot_rows[k].get("title") and title:
                ballot_rows[k]["title"] = title
            if not ballot_rows[k].get("year") and c.get("year"):
                ballot_rows[k]["year"] = c.get("year")
            continue
        ballot_rows[k] = {
            "vote": "?",
            "year": c.get("year"),
            "doi": doi,
            "title": title,
        }

    # quitar de la boleta lo que ya pasó a known/rejected
    known_dois_set = known_dois
    filtered_rows = []
    for row in ballot_rows.values():
        d = row.get("doi")
        if d and d in known_dois_set:
            continue
        if is_known(
            {"doi": d, "title": row.get("title")},
            known_dois_set,
            known_titles,
        ):
            continue
        filtered_rows.append(row)

    if parse_votos is not None:
        write_votos(filtered_rows, VOTOS_PATH)

    print(f"\nCandidatos nuevos (búsqueda): {len(candidates)}")
    print(f"  en votos (total cola): {len(filtered_rows)}")
    print(f"  YAML  → {args.yaml_out.relative_to(ROOT)}")
    print(f"  MD    → {args.md_out.relative_to(ROOT)}")
    print(f"  VOTOS → {VOTOS_PATH.relative_to(ROOT)}  ← editá esto (?/si/no)")
    if candidates or filtered_rows:
        if candidates:
            print("\nTop 5 búsqueda:")
            for c in candidates[:5]:
                print(f"  [{c.get('relevance_score', 0):2d}] {c.get('year')} — {c.get('title')}")
        print("\nPara votar: editá candidates/votos.txt y corré:")
        print("  python scripts/apply_votes.py")
        print("Sugerir por DOI:  candidates/sugeridos.txt  →  python scripts/from_dois.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
