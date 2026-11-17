# LogSentry

CLI alat u Pythonu koji se preko SSH-a spaja na server, preuzima povijest logova aplikacije,
prati ih uživo i sprema u lokalnu bazu. Nad prikupljenim podacima vlastitim algoritmima otkriva
greške, anomalije i napade.

Projekt je u izradi. Trenutno postoji struktura paketa.

## Struktura

| Putanja | Sadržaj |
|---|---|
| `logsentry/` | CLI alat |
| `server/` | Demo aplikacija u Dockeru (nginx, FastAPI, PostgreSQL) i generator prometa |
| `tests/` | Testovi |

## Razvoj

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/logsentry --version
.venv/bin/pytest
.venv/bin/ruff check .
```
