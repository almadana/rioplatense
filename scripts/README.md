# Scripts del índice che-Norma!

Instrucciones completas en el [README principal](../README.md). Resumen:

```bash
pip install -r scripts/requirements.txt
export OPENALEX_MAILTO="tu@email.org"

# buscar en OpenAlex
python scripts/find_candidates.py

# o sugerir DOIs (candidates/sugeridos.txt)
python scripts/from_dois.py

# votar en candidates/votos.txt  (? → si | no)
python scripts/apply_votes.py
```

| Script | Rol |
|--------|-----|
| `find_candidates.py` | Búsqueda automática → cola de votos |
| `from_dois.py` | Lista de DOIs → cola de votos |
| `apply_votes.py` | Aplica `si`/`no` a known/rejected |
