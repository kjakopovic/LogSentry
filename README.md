# LogSentry

CLI alat u Pythonu koji se preko SSH-a spaja na server, preuzima povijest logova aplikacije,
prati ih uživo i sprema u lokalnu bazu. Nad prikupljenim podacima vlastitim algoritmima otkriva
greške, anomalije i napade.

Projekt je u izradi. Trenutno postoji struktura paketa i demo aplikacija koja proizvodi logove.

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

## Demo aplikacija

Lokalno pokretanje:

```bash
cd server
cp .env.example .env    # zatim upiši POSTGRES_PASSWORD
docker compose up -d --build
```

Logovi se pišu u `server/logs/`, a aplikacija je dostupna na `http://localhost`.
Deploy na VPS opisan je u [server/setup.md](server/setup.md).
