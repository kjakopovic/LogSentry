# Deploy demo aplikacije na VPS

Upute su pisane za čisti Ubuntu 24.04. U naredbama `HOST` zamijeni adresom servera.

Na serveru postoje dva korisnika:

| Korisnik | Namjena | Prava |
|---|---|---|
| `deploy` | Administracija i pokretanje stacka | `sudo`, grupa `docker` |
| `logsentry` | Alat LogSentry | Čitanje logova i tri naredbe Dockera |

## 1. SSH ključevi

Na svom računalu napravi po jedan ključ za svakog korisnika:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/demoapp_deploy -C deploy
```

```bash
ssh-keygen -t ed25519 -f ~/.ssh/logsentry -C logsentry
```

## 2. Korisnici

Spoji se kao root ili početni korisnik koji ti je dao pružatelj usluge. Sadržaj datoteka
`~/.ssh/demoapp_deploy.pub` i `~/.ssh/logsentry.pub` upiši umjesto `KLJUC_*`.

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo adduser --disabled-password --gecos "" logsentry
sudo usermod -aG sudo deploy
echo "deploy ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/deploy
sudo chmod 440 /etc/sudoers.d/deploy

sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo "KLJUC_DEPLOY" | sudo tee /home/deploy/.ssh/authorized_keys
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys

sudo install -d -m 700 -o logsentry -g logsentry /home/logsentry/.ssh
echo "KLJUC_LOGSENTRY" | sudo tee /home/logsentry/.ssh/authorized_keys
sudo chown logsentry:logsentry /home/logsentry/.ssh/authorized_keys
sudo chmod 600 /home/logsentry/.ssh/authorized_keys
```

Prije nastavka provjeri u **novom terminalu** da prijava radi:

```bash
ssh -i ~/.ssh/demoapp_deploy deploy@HOST sudo -n whoami
```

Treba ispisati `root`.

## 3. Zaštita SSH-a

Naziv datoteke počinje s `10-` jer sshd uzima prvu pronađenu vrijednost, a slike za cloud
često imaju `50-cloud-init.conf` koji dopušta lozinke.

```bash
sudo tee /etc/ssh/sshd_config.d/10-hardening.conf > /dev/null <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers deploy logsentry

Match User logsentry
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:8000
    X11Forwarding no
    AllowAgentForwarding no
CONF
sudo sshd -t && sudo systemctl reload ssh
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication)'
```

Trenutnu sesiju ne zatvaraj dok u novom terminalu ponovno ne provjeriš prijavu.

## 4. Vatrozid

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
```

Docker objavljene portove otvara mimo `ufw` pravila. Zato API u `docker-compose.yml` sluša samo
na `127.0.0.1`, a PostgreSQL nema objavljen port.

## 5. Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git logrotate
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker deploy
```

Odjavi se i ponovno prijavi kao `deploy` da grupa počne vrijediti.

## 6. Prava korisnika logsentry

Članstvo u grupi `docker` jednako je root pristupu, pa `logsentry` u njoj nije.
Dopuštene su mu samo naredbe za čitanje:

```bash
sudo tee /etc/sudoers.d/logsentry > /dev/null <<'CONF'
logsentry ALL=(root) NOPASSWD: /usr/bin/docker ps, /usr/bin/docker ps *, /usr/bin/docker logs *, /usr/bin/docker events, /usr/bin/docker events *
CONF
sudo chmod 440 /etc/sudoers.d/logsentry
sudo visudo -cf /etc/sudoers.d/logsentry
```

## 7. Direktorij s logovima

Setgid bit daje novim datotekama grupu `logsentry`, pa ih alat može čitati.

```bash
sudo install -d -o deploy -g logsentry -m 2750 /var/log/demoapp
```

## 8. Pokretanje aplikacije

Kao korisnik `deploy`:

```bash
git clone git@github.com:kjakopovic/LogSentry.git
cd LogSentry/server
cp .env.example .env
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" .env
sed -i "s|^LOG_DIR=.*|LOG_DIR=/var/log/demoapp|" .env
sed -i "s|^APP_UID=.*|APP_UID=$(id -u)|" .env
sed -i "s|^APP_GID=.*|APP_GID=$(id -g)|" .env
docker compose up -d --build
docker compose ps
```

## 9. Rotacija access.log

`app.log` rotira sama aplikacija u `.gz` arhive. Za nginx se koristi `logrotate`:

```bash
sudo cp logrotate/demoapp /etc/logrotate.d/demoapp
sudo logrotate -d /etc/logrotate.d/demoapp
```

## 10. Provjera

Sa svog računala:

```bash
curl -i http://HOST/orders?limit=1
```

```bash
curl -i http://HOST/health
```

Prva naredba treba vratiti 200, a druga 404 jer `/health` nije javan.

Prava korisnika `logsentry`:

```bash
ssh -i ~/.ssh/logsentry logsentry@HOST sudo -n docker ps
```

```bash
ssh -i ~/.ssh/logsentry logsentry@HOST ls -l /var/log/demoapp
```

```bash
ssh -i ~/.ssh/logsentry logsentry@HOST sudo -n docker stop demo-api
```

Prve dvije naredbe trebaju raditi, a treća mora biti odbijena.

Tunel do internog endpointa pokreni u jednom terminalu:

```bash
ssh -i ~/.ssh/logsentry -N -L 8000:127.0.0.1:8000 logsentry@HOST
```

U drugom terminalu:

```bash
curl http://127.0.0.1:8000/health
```

## 11. Scenariji generatora prometa

Servis `traffic-gen` stalno šalje normalan promet. Napadi se pokreću iz direktorija `server/`:

```bash
docker compose run --rm traffic-gen bruteforce --base-url http://nginx
```

```bash
docker compose run --rm traffic-gen scan --base-url http://nginx
```

Scenarij `db-outage` gasi kontejner baze, pa se pokreće na hostu kao korisnik `deploy`:

```bash
python3 traffic_gen/traffic_gen.py db-outage --duration 60
```

Tijekom ispada API se ruši i ponovno pokreće, a nginx vraća 502. Baza se vraća i ako se
scenarij prekine s Ctrl+C.
