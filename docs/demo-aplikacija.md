# Demo aplikacija: što je napravljeno i zašto

Ovaj dokument objašnjava dio projekta koji je napravljen na početku: repozitorij, malu aplikaciju
u Dockeru i generator prometa. Za korake instalacije na serveru pogledaj
[server/setup.md](../server/setup.md).

## Ukratko

LogSentry je alat koji čita i analizira logove. Da bi imao što analizirati, treba mu aplikacija
koja stvarno radi i stvarno griješi.

Zato projekt ima dva dijela:

| Dio | Mapa | Stanje |
|---|---|---|
| **Alat LogSentry**, koji se pokreće na tvom računalu | `logsentry/` | Zasad samo kostur i naredba `--version` |
| **Demo aplikacija**, koja radi na serveru i proizvodi logove | `server/` | Gotova |

Ovaj dokument opisuje drugi dio.

## Od čega se aplikacija sastoji

Aplikacija je mali web servis za narudžbe. Sam posao nije važan, važni su logovi koje proizvodi.
Sastoji se od četiri Docker kontejnera:

```text
   Internet
       |
       v
  +---------+       +---------+       +------------+
  |  nginx  | ----> |   api   | ----> |  postgres  |
  | port 80 |       | FastAPI |       |    baza    |
  +---------+       +---------+       +------------+
       ^                 |
       |                 v
  +-------------+   logovi u mapi logs/
  | traffic-gen |   i na stdoutu kontejnera
  +-------------+
```

| Kontejner | Što radi | Zašto postoji |
|---|---|---|
| `demo-nginx` | Prima zahtjeve izvana i prosljeđuje ih API-ju | Daje access log, na kojem se vide napadi i greške 502 |
| `demo-api` | Aplikacija: prijava, korisnici, narudžbe, izvještaji | Daje aplikacijske logove i tracebackove |
| `demo-postgres` | Baza podataka | Njezin ispad je glavni scenarij za demonstraciju |
| `demo-traffic` | Glumi korisnike i napadače | Bez njega bi server bio prazan i logovi ne bi nastajali |

## Što se dogodi kad stigne zahtjev

Primjer je zahtjev za korisnika koji ne postoji, `GET /users/4512`:

1. Zahtjev stiže na nginx, koji zapiše redak u `access.log`.
2. Nginx ga prosljeđuje API-ju.
3. API pita bazu postoji li korisnik i dobije prazan odgovor.
4. API zapiše upozorenje `User 4512 not found` i vrati 404.
5. API na kraju zapiše još jedan redak s metodom, putanjom, statusom i trajanjem zahtjeva.

Jedan zahtjev tako ostavlja trag na više mjesta, što je upravo ono što će LogSentry kasnije čitati
i povezivati.

## Tri vrste logova

Logovi namjerno nisu u istom formatu, jer stvarni serveri također miješaju formate. LogSentry će
morati razumjeti svaki od njih.

**1. Nginx access log** (`logs/access.log` i stdout kontejnera)

```text
203.0.113.170 - - [08/Nov/2026:19:06:46 +0000] "GET /config.php HTTP/1.1" 404 22 "-" "python-requests/2.32" rt=0.002 urt="0.002"
```

Svaki redak je jedan zahtjev: tko je pitao, što je pitao, koji je odgovor dobio i koliko je trajalo.

**2. JSON log aplikacije** (`logs/app.log`)

```json
{"ts": "2026-11-08T19:05:58.662+00:00", "level": "INFO", "logger": "demoapp.http", "message": "Request GET /orders -> 200 (19.6 ms)", "request_id": "521c4b51a508", "client_ip": "198.51.100.29", "method": "GET", "path": "/orders", "status": 200, "duration_ms": 19.6}
```

Strojno čitljiv format. Kad datoteka naraste do 5 MB, sažima se u `app.log.1.gz`, a čuva se
pet takvih arhiva.

**3. Tekstualni log aplikacije** (stdout, čita se s `docker logs`)

```text
2026-11-08 19:05:57,631 WARNING  demoapp.api: User 5221 not found
```

Lako se čita, ali je teži za parsiranje jer jedna greška može zauzeti više redaka:

```text
  File "/srv/app/main.py", line 195, in average_per_day
    return {"days": days, "average_per_day": round(float(total) / days, 2)}
ZeroDivisionError: float division by zero
```

Parser će takav traceback morati spojiti u jedan događaj, a ne tretirati ga kao tri odvojena retka.

PostgreSQL ima i vlastiti tekstualni format, koji se također vidi kroz `docker logs`.

## Što aplikacija nudi

| Adresa | Što radi | Kakve logove daje |
|---|---|---|
| `POST /login` | Prijava | Upozorenje i 401 na krivu lozinku |
| `GET /users/{id}` | Dohvat korisnika | Upozorenje i 404 ako ne postoji |
| `GET /orders` | Popis narudžbi | Običan promet |
| `POST /orders` | Nova narudžba | Upozorenje ako korisnik ne postoji |
| `GET /reports/daily` | Dnevni izvještaj | U 10 % slučajeva traje 1,2 s, pa nastaje upozorenje `Slow request` |
| `GET /reports/average?days=7` | Prosjek po danu | S `days=0` namjerno pada s tracebackom |
| `GET /health` | Radi li aplikacija i baza | Dostupno samo na serveru, kroz SSH tunel |
| `GET /metrics` | Brojači odgovora i grešaka baze | Dostupno samo na serveru, kroz SSH tunel |

## Generator prometa

Program `traffic_gen.py` šalje zahtjeve kao da dolaze od različitih ljudi. Ima četiri scenarija:

| Scenarij | Što simulira | Što se vidi u logovima |
|---|---|---|
| `normal` | Obične korisnike, jedan zahtjev u sekundi | Uglavnom uspješni zahtjevi i pokoja sitna greška |
| `bruteforce` | Pogađanje lozinki s jedne adrese | Puno odgovora 401 u kratkom vremenu |
| `scan` | Traženje ranjivih putanja, npr. `/.env` i `/wp-admin/` | Puno odgovora 404 s jedne adrese |
| `db-outage` | Ispad baze | Lanac grešaka kroz cijeli sustav, opisan ispod |

Scenarij `normal` radi stalno, a ostale pokrećeš ručno kad ih želiš pokazati.

Simulirani klijenti koriste adrese `198.51.100.x` i `203.0.113.x`. Ti su rasponi rezervirani za
dokumentaciju i ne postoje na internetu, pa se odmah vidi što je simulacija, a što pravi posjetitelj.

### Kako izgleda ispad baze

Ovo je stvarni rezultat lokalnog testa, u kojem je baza bila ugašena 12 sekundi:

1. `demo-postgres` se gasi.
2. API ne može do baze i vraća **503**.
3. Nakon pet uzastopnih neuspjeha API se sam ruši.
4. Docker ga ponovno pokreće, ali baze još nema, pa se opet ruši. U testu se to ponovilo 6 puta.
5. Dok API ne radi, nginx vraća **502**, a povremeno i **504**.
6. Baza se vraća, API se uspješno pokreće i aplikacija opet radi.

Jedan uzrok tako proizvede tri vrste simptoma na tri mjesta: gašenje baze, greške i restartove
API-ja te greške 502 u nginxu. Upravo to je slučaj koji je profesor naveo za proširenje koje
povezuje alerte u jedan incident.

## Zašto je napravljeno baš ovako

**Zašto se API namjerno ruši kad nema baze?**
Da je samo vraćao 503, nginx nikad ne bi vratio 502, a Docker ne bi zabilježio restartove. Ispad bi
izgledao puno jednostavnije nego u stvarnosti i korelacija ne bi imala što povezivati.

**Zašto `/reports/average?days=0` ima bug?**
Detektori trebaju prave tracebackove. Greška je stvarna i nastaje u normalnom toku programa, a u
kodu je označena komentarom da je namjerna.

**Zašto se `db-outage` pokreće na serveru, a ne iz kontejnera?**
Da bi kontejner mogao gasiti druge kontejnere, trebao bi pristup Docker socketu. To je praktički
root pristup cijelom serveru, što ne želimo dati generatoru prometa.

**Zašto `/health` i `/metrics` nisu javni?**
To su interni podaci o stanju sustava. API sluša samo na `127.0.0.1`, a nginx te adrese vraća
kao 404. Dolazi se do njih SSH tunelom, pa tunel u projektu ima stvarnu svrhu.

**Zašto dva korisnika na serveru?**
`deploy` administrira server. `logsentry` smije samo čitati logove i pokrenuti `docker ps`,
`docker logs` i `docker events`. Ako netko ukrade ključ alata, ne može ugasiti aplikaciju ni
dobiti root pristup.

**Može li netko izvana lažirati svoju IP adresu?**
Generator šalje simuliranu adresu u zaglavlju `X-Forwarded-For`, ali nginx tom zaglavlju vjeruje
samo kad zahtjev dolazi iz Docker mreže. Za vanjske posjetitelje zaglavlje se ignorira.

**Mogu li se u log podmetnuti lažni retci?**
Korisničko ime zapisuje se tako da se znakovi za novi redak ne izvrše, nego ostanu vidljivi kao
tekst. Napadač zato ne može kroz prijavu ubaciti izmišljeni zapis u log.

**Neće li logovi napuniti disk?**
Neće. `app.log` se rotira pri 5 MB, `access.log` jednom dnevno uz čuvanje 14 dana, a
`docker logs` je ograničen na tri datoteke od 10 MB po kontejneru.

## Gdje je što

```text
LogSentry/
├── logsentry/                 alat (zasad kostur)
│   └── cli.py                 ulazna točka, naredba --version
├── tests/test_cli.py          prvi test
├── pyproject.toml             ovisnosti i postavke alata
└── server/
    ├── docker-compose.yml     opis sva četiri kontejnera
    ├── .env.example           predložak za lozinku i postavke
    ├── setup.md               upute za instalaciju na VPS
    ├── api/app/
    │   ├── main.py            adrese aplikacije i bilježenje zahtjeva
    │   ├── db.py              spajanje na bazu i rušenje nakon pet neuspjeha
    │   └── logging_setup.py   tekstualni i JSON log, rotacija
    ├── nginx/default.conf     prosljeđivanje, format loga, skrivanje /health
    ├── postgres/init.sql      tablice i izmišljeni podaci
    ├── traffic_gen/           generator prometa
    ├── logrotate/demoapp      rotacija access.log na serveru
    └── logs/                  log datoteke kad se aplikacija pokrene lokalno
```

## Kako isprobati lokalno

Pokreni aplikaciju:

```bash
cd server
cp .env.example .env
```

U `.env` upiši bilo koju vrijednost za `POSTGRES_PASSWORD`, a zatim:

```bash
docker compose up -d --build
```

Gledaj logove uživo:

```bash
docker logs -f demo-api
```

Pokreni napad iz drugog terminala, iz mape `server/`:

```bash
docker compose run --rm traffic-gen bruteforce --base-url http://nginx
```

Pokreni ispad baze:

```bash
python3 traffic_gen/traffic_gen.py db-outage --duration 15
```

Ugasi sve i obriši podatke:

```bash
docker compose down -v
```

## Što slijedi

Sljedeći korak je sam alat: konfiguracija, SSH veza i naredba `fetch`, koja preuzima ove logove
sa servera u lokalnu bazu. Parseri će zatim razumjeti tri formata opisana u ovom dokumentu.
