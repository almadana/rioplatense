# SITIO WEB cheNorma.uy

Un pequeño sitio web que lista publicaciones de normas psicolingüísticas del Español Rioplatense (y trabajos o herramientas relacionadas).

[www.chenorma.uy](https://www.chenorma.uy)

Por errores o adendas, hacer un pull request de este repo, o escribir a `acabana _arr_ psico edu uy`.

Realizado en Quarto.

---

## Mantener el índice: candidatos y votos

Hay un flujo simple en tres pasos: **buscar o sugerir** → **votar en un archivo de texto** → **aplicar** y actualizar el sitio.

### 1. Setup (una vez)

```bash
pip install -r scripts/requirements.txt
export OPENALEX_MAILTO="tu@email.org"   # recomendado (OpenAlex)
```

### 2a. Búsqueda automática (OpenAlex)

```bash
python scripts/find_candidates.py
```

Genera / actualiza:

| Archivo | Uso |
|---------|-----|
| `candidates/votos.txt` | Cola de votación (`?` / `si` / `no`) |
| `candidates/pending.yml` | Metadatos para armar entradas |
| `candidates/pending.md` | Vista legible (opcional) |

Opciones útiles:

```bash
python scripts/find_candidates.py --from-year 2018 --min-score 3 --max-per-query 50
```

Se usa [OpenAlex](https://openalex.org) (API abierta). Google Scholar no tiene API pública estable.

Para afinar las búsquedas, editá `QUERIES`, `GEO_TERMS` y `DOMAIN_TERMS` en `scripts/find_candidates.py`.

### 2b. Sugerir artículos por DOI

Editá `candidates/sugeridos.txt` (un DOI por línea):

```
# comentarios con #
10.3758/s13428-021-01660-z
https://doi.org/10.1234/ejemplo
```

```bash
python scripts/from_dois.py
# o con otro archivo:
python scripts/from_dois.py mi-lista.txt
```

Resuelve título y autores (OpenAlex; si falta, Crossref), los suma a `votos.txt` y marca cada DOI como `# enviado: …` en la lista. No aplica filtro de relevancia: si está en el archivo, entra a votación. Omite lo ya conocido, rechazado o en la cola.

### 3. Votar

Editá `candidates/votos.txt`:

```
# voto | año | doi-o-- | título
?  | 2015 | 10.35670/… | Normas categoriales…
si | 2018 | 10.1234/…  | Paper que sí va
no | 2020 | -          | Ruido que no va
```

| voto | significado |
|------|-------------|
| `?`  | pendiente |
| `si` | aceptar |
| `no` | rechazar (no se vuelve a proponer) |

```bash
python scripts/apply_votes.py
```

- `si` → `data/known.yml` **y también `index.qmd`** (sección *Recién aceptados*; podés mover el bullet a la categoría que corresponda)
- `no` → `data/rejected.yml`
- deja en `votos.txt` solo los que siguen en `?`

Si preferís ubicarlos a mano en otra sección, mové el bullet desde *Recién aceptados* y borrá la sección cuando quede vacía.

### Archivos de datos

| Archivo | Rol |
|---------|-----|
| `data/known.yml` | Ítems ya en el índice (deduplicación) |
| `data/rejected.yml` | Descartados en votación |
| `candidates/sugeridos.txt` | DOIs propuestos a mano |
| `candidates/votos.txt` | Boleta de votación del admin |

---

## Automatización en GitHub Actions

Ya existe el workflow [`.github/workflows/find-candidates.yml`](.github/workflows/find-candidates.yml).

**Qué hace**

- Corre cada **lunes ~9:00 AR/UY** (12:00 UTC)
- También se puede lanzar a mano: **Actions → “Buscar candidatos nuevos” → Run workflow**
- Si hay candidatos, commitea `candidates/votos.txt` (y pending) y abre un issue con resumen

**Para activarlo**

1. Pushear el workflow a la branch por defecto (`main`)
2. Tener **Actions** habilitadas en el repo
3. (Opcional) Settings → Secrets and variables → Actions → Variables → `OPENALEX_MAILTO` con tu correo

**Después del workflow (vos)**

1. Editá `candidates/votos.txt` en el repo
2. Localmente: `python scripts/apply_votes.py`
3. Actualizá `index.qmd` con los `si`
4. Commit y push

Más detalle de scripts: [`scripts/README.md`](scripts/README.md).
