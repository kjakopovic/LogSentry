# Pokretanje i testiranje demo servera

Ovaj vodič prolazi kroz lokalno pokretanje demo aplikacije, korak po korak, kako smo ga prošli
pri prvom testiranju. Za svaki korak piše što trebaš vidjeti i zašto je to važno.

Što je demo aplikacija i zašto postoji objašnjava [docs/demo-aplikacija.md](docs/demo-aplikacija.md).
Postavljanje na pravi VPS opisano je u [server/setup.md](server/setup.md).

## Pregled

| Korak | Što provjeravaš |
|---|---|
| [1. Preduvjeti](#1-preduvjeti) | Docker i Python su spremni |
| [2. Alat LogSentry](#2-alat-logsentry) | Alat se instalira i testovi prolaze |
| [3. Konfiguracija](#3-konfiguracija) | Postoji `.env` s lozinkom baze |
| [4. Pokretanje](#4-pokretanje) | Sva četiri kontejnera rade |
| [5. Osnovni zahtjevi](#5-osnovni-zahtjevi) | Aplikacija odgovara, interni endpointi nisu javni |
| [6. Logovi](#6-logovi) | Logovi postoje u tri formata |
| [7. Napadi](#7-napadi) | Brute-force i skeniranje ostavljaju trag |
| [8. Ispad baze](#8-ispad-baze) | Sustav pada lančano i sam se oporavlja |
| [9. Gašenje](#9-gašenje-i-čišćenje) | Sve je počišćeno |

Sve naredbe pokreću se iz korijena repozitorija, osim ako piše drukčije.

## 1. Preduvjeti

Trebaju ti Docker s Compose dodatkom i Python 3.12 ili noviji.

```bash
docker compose version
```

```bash
python3 --version
```

Ako `docker` javlja da se ne može spojiti na daemon, Docker nije pokrenut. Na Linuxu s Docker
Desktopom pokreće se ovako:

```bash
systemctl --user start docker-desktop
```

## 2. Alat LogSentry

Alat je zasad kostur, pa ovdje samo provjeravaš da se ispravno instalira.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

```bash
.venv/bin/logsentry --version
```

```bash
.venv/bin/pytest
```

✅ Ispis `logsentry 0.1.0` i `1 passed`.

Opcija `-e` instalira paket tako da se izmjene u kodu vide odmah, bez ponovne instalacije.

## 3. Konfiguracija

Postavke aplikacije čitaju se iz datoteke `server/.env`. Predložak je `server/.env.example`.

```bash
cp server/.env.example server/.env
```

Otvori `server/.env` i upiši lozinku baze u `POSTGRES_PASSWORD`. Lokalno može biti bilo što, a
nasumičnu lozinku dobiješ ovako:

```bash
openssl rand -hex 24
```

Ostale postavke:

| Postavka | Zadano | Kada je mijenjati |
|---|---|---|
| `HTTP_PORT` | `80` | Ako je port 80 zauzet, npr. stavi `8080` |
| `API_PORT` | `8000` | Ako je port 8000 zauzet |
| `APP_UID`, `APP_GID` | `1000` | Ako tvoj korisnik nema UID 1000 (provjeri s `id -u`) |
| `LOG_DIR` | `./logs` | Lokalno ne treba, na VPS-u je `/var/log/demoapp` |
| `TRAFFIC_RATE` | `1` | Broj zahtjeva u sekundi koje generator šalje |

`.env` je u `.gitignore`, pa lozinka nikad ne završi na GitHubu.

## 4. Pokretanje

```bash
cd server
```

```bash
docker compose up -d --build
```

Prvo pokretanje traje dulje jer se preuzimaju slike i grade kontejneri `api` i `traffic-gen`.

```bash
docker compose ps
```

✅ Četiri kontejnera: `demo-nginx`, `demo-api`, `demo-postgres` i `demo-traffic`.
`demo-api` i `demo-postgres` imaju oznaku `(healthy)`.

Redoslijed pokretanja nije slučajan. API čeka da baza bude spremna, nginx čeka API, a generator
prometa čeka nginx. Ako se `demo-api` ne pokaže kao `healthy`, pogledaj
[Česti problemi](#česti-problemi).

## 5. Osnovni zahtjevi

U ovom koraku `localhost` znači port iz `HTTP_PORT`. Ako si ga promijenio, piši npr.
`localhost:8080`.

```bash
curl -i http://localhost/users/1
```

✅ Status 200 i korisnik `alice`.

```bash
curl -i http://localhost/users/4512
```

✅ Status 404. U logu nastaje upozorenje `User 4512 not found`.

```bash
curl -i "http://localhost/reports/average?days=0"
```

✅ Status 500. Ovo je namjerni bug koji u logu ostavlja pravi traceback, materijal za buduće
detektore.

```bash
curl -i http://localhost/health
```

✅ Status **404**. Nginx ne pušta `/health` van, jer su to interni podaci o stanju sustava.

```bash
curl http://127.0.0.1:8000/health
```

✅ `"status":"ok"` i `"database":"up"`. Izravno na API-ju endpoint radi, ali API sluša samo na
`127.0.0.1`. Na VPS-u se do njega dolazi SSH tunelom.

```bash
curl http://127.0.0.1:8000/metrics
```

✅ Brojači odgovora po statusu, broj grešaka baze i vrijeme rada aplikacije.

## 6. Logovi

Ovo je najvažniji korak, jer su logovi upravo ono što će LogSentry čitati. Nastaju u tri formata.

**Nginx access log**, jedan redak po zahtjevu:

```bash
tail -n 5 logs/access.log
```

✅ IP adresa, zahtjev, status, veličina odgovora, preglednik i `rt=` (trajanje u sekundama).

**JSON log aplikacije**, za strojnu obradu:

```bash
tail -n 3 logs/app.log
```

✅ Svaki redak je JSON objekt s poljima `ts`, `level`, `message`, `request_id` i `client_ip`.

**Tekstualni log aplikacije**, na stdoutu kontejnera:

```bash
docker logs --tail 30 demo-api
```

✅ Čitljivi retci i višelinijski `ZeroDivisionError` traceback iz koraka 5.

Generator prometa stalno šalje zahtjeve, pa logovi rastu sami od sebe. Uživo ih pratiš ovako,
a izlaziš s Ctrl+C:

```bash
docker logs -f demo-api
```

Simulirani korisnici imaju adrese `198.51.100.x`. Taj je raspon rezerviran za dokumentaciju, pa
se simulacija ne može zamijeniti sa stvarnim posjetiteljima.

## 7. Napadi

Napadi se pokreću ručno, iz mape `server/`. Zahtjevi idu kroz nginx, kao i pravi napad.

**Brute-force:** pogađanje lozinki 15 sekundi, 10 pokušaja u sekundi.

```bash
docker compose run --rm traffic-gen bruteforce --base-url http://nginx
```

✅ Na kraju ispiše `bruteforce: 401: N`, gdje je N otprilike između 120 i 150.

**Skeniranje:** traženje ranjivih putanja 10 sekundi, 20 zahtjeva u sekundi.

```bash
docker compose run --rm traffic-gen scan --base-url http://nginx
```

✅ Ispiše niz odgovora 404.

Napadači dolaze iz raspona `203.0.113.x`:

```bash
grep 203.0.113 logs/access.log | tail -n 5
```

✅ Sve s jedne adrese, s putanjama poput `/.env`, `/wp-admin/` i `/phpmyadmin/`.

Upravo te uzorke (mnogo 401 ili 404 s jedne adrese u kratkom vremenu) kasnije trebaju
prepoznati detektori za brute-force i skeniranje.

## 8. Ispad baze

Ovo je glavni scenarij za demonstraciju. Trebaju ti dva terminala.

U **prvom terminalu** prati događaje Dockera:

```bash
docker events --filter type=container --filter event=die --filter event=start
```

U **drugom terminalu**, iz mape `server/`, pokreni ispad od 15 sekundi:

```bash
python3 traffic_gen/traffic_gen.py db-outage --duration 15
```

Ako si mijenjao `HTTP_PORT`, dodaj `--base-url http://127.0.0.1:8080`.

Scenarij se pokreće na računalu, a ne u kontejneru, jer mora ugasiti kontejner baze. Da bi to
mogao iz kontejnera, trebao bi pristup Docker socketu, a to je praktički root pristup.

✅ U prvom terminalu redom:
1. `die demo-postgres`: baza se gasi.
2. Više parova `die` i `start` za `demo-api`: API se ruši jer nema baze, a Docker ga ponovno pokreće.
3. `start demo-postgres`: baza se vraća.
4. Zadnji `start demo-api` nakon kojeg nema novog `die`: API je opet stabilan.

✅ U drugom terminalu na kraju piše `aplikacija se oporavila`, a sažetak sadrži statuse 502 i 503.

```bash
grep -c '" 502 ' logs/access.log
```

✅ Broj veći od nule.

Što se dogodilo:

| Status | Značenje |
|---|---|
| 503 | API radi, ali ne može do baze |
| 502 | API je pao, pa nginx nema kome proslijediti zahtjev |
| 504 | Povremeno: nginx se nije uspio spojiti na API na vrijeme |

Jedan uzrok, ispad baze, ostavlja simptome na tri mjesta: u Docker događajima, u logovima API-ja
i u access logu nginxa. Proširenje za korelaciju kasnije će od toga morati složiti **jedan**
incident s uzrokom `postgres`.

Ako scenarij prekineš s Ctrl+C, baza se svejedno ponovno pokreće.

## 9. Gašenje i čišćenje

Iz mape `server/`:

```bash
docker compose down -v
```

Opcija `-v` briše i podatke baze, pa sljedeće pokretanje kreće od početnih podataka.

```bash
rm -f logs/*.log logs/*.gz
```

## Česti problemi

**`postavi POSTGRES_PASSWORD u .env`**
Datoteka `server/.env` ne postoji ili je `POSTGRES_PASSWORD` prazan. Vrati se na
[korak 3](#3-konfiguracija).

**`port is already allocated`**
Port 80 ili 8000 koristi drugi program. Promijeni `HTTP_PORT` ili `API_PORT` u `server/.env` i
ponovno pokreni `docker compose up -d`.

**`demo-api` se stalno ponovno pokreće ili nije `healthy`**
Pogledaj zašto:

```bash
docker logs --tail 30 demo-api
```

Ako vidiš `PermissionError` za `/logs/app.log`, API ne smije pisati u `server/logs/`. U
`server/.env` postavi `APP_UID` i `APP_GID` na vrijednosti koje vraćaju `id -u` i `id -g`.

Ako vidiš `Database unavailable at startup`, baza još nije spremna ili je ugašena:

```bash
docker compose ps postgres
```

**`db-outage treba Docker CLI`**
Scenarij je pokrenut kroz `docker compose run`. Pokreni ga izravno s `python3`, kao u
[koraku 8](#8-ispad-baze).

**Nema novih redaka u logovima**
Provjeri radi li generator prometa:

```bash
docker logs --tail 5 demo-traffic
```

## Sljedeći korak

Kad sve ovo radi lokalno, ista aplikacija postavlja se na VPS prema
[server/setup.md](server/setup.md). Tamo se dodaju stvari koje lokalno nemaju smisla: zaštita SSH-a,
vatrozid, poseban korisnik `logsentry` s pravom samo na čitanje i rotacija `access.log`.
