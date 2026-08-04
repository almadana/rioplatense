# Buscador de candidatos — che-Norma!

Script que propone ítems nuevos; el admin vota editando un archivo de texto.

## Flujo (lo mínimo)

```bash
pip install -r scripts/requirements.txt
export OPENALEX_MAILTO="tu@email.org"

# 1. Buscar candidatos → genera candidates/votos.txt
python scripts/find_candidates.py

# 2. Editar el archivo: cambiá ? por si o no
#    candidates/votos.txt

# 3. Aplicar votos
python scripts/apply_votes.py
```

### `candidates/votos.txt`

```
# voto | año | doi-o-- | título
?  | 2015 | 10.35670/… | Normas categoriales…
si | 2018 | 10.1234/…  | Paper que sí va
no | 2020 | -          | Ruido que no va
```

| voto | efecto |
|------|--------|
| `?`  | pendiente |
| `si` | → `data/known.yml` (+ sugerencia para `index.qmd`) |
| `no` | → `data/rejected.yml` (no se re-propone) |

`index.qmd` se actualiza a mano (el script imprime un bullet sugerido al aceptar).

## ¿Por qué OpenAlex y no Google Scholar?

Google Scholar no ofrece API pública y el scraping se bloquea.
[OpenAlex](https://openalex.org) es abierto y estable; cubre bien normas y papers afines.

## Opciones del buscador

```bash
python scripts/find_candidates.py --from-year 2018 --min-score 3 --max-per-query 50
```

También escribe `candidates/pending.yml` / `pending.md` (detalle; la votación es en `votos.txt`).

## GitHub Actions

`.github/workflows/find-candidates.yml` corre semanalmente y actualiza candidatos.
La revisión del admin es local: editar `votos.txt` y correr `apply_votes.py`.

Opcional: variable de repo `OPENALEX_MAILTO`.

## Ajustar búsquedas

Editá `QUERIES`, `GEO_TERMS` y `DOMAIN_TERMS` en `scripts/find_candidates.py`.
