#!/usr/bin/env python3
"""Generator prometa za demo aplikaciju.

Scenariji normal, bruteforce i scan mogu raditi u kontejneru ili na hostu.
Scenarij db-outage gasi kontejner baze, pa se pokreće na hostu.
Koristi samo standardnu biblioteku.
"""

import argparse
import json
import random
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable

# Rasponi rezervirani za dokumentaciju (RFC 5737): simulirani klijenti
# razlikuju se od stvarnih posjetitelja servera.
NORMAL_CLIENTS = [f"198.51.100.{n}" for n in range(10, 40)]
ATTACKER_NET = "203.0.113"

DEMO_USERS = ["alice", "bob", "carol", "dave", "erin"]
DEMO_PASSWORD = "demo-pass"
POSTGRES_CONTAINER = "demo-postgres"

COMMON_USERNAMES = ["admin", "root", "alice", "bob", "test", "user", "administrator", "postgres"]
COMMON_PASSWORDS = ["123456", "password", "admin", "qwerty", "letmein", "welcome", "abc123"]
SCAN_PATHS = [
    "/.env",
    "/.git/config",
    "/wp-admin/",
    "/wp-login.php",
    "/xmlrpc.php",
    "/phpmyadmin/",
    "/admin/",
    "/admin.php",
    "/config.php",
    "/backup.zip",
    "/db.sql",
    "/server-status",
    "/vendor/phpunit/phpunit/phpunit.php",
    "/cgi-bin/luci",
    "/actuator/env",
]
USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1",
]
ATTACK_USER_AGENT = "python-requests/2.32"


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.statuses: Counter[int | str] = Counter()

    def request(
        self,
        method: str,
        path: str,
        client_ip: str,
        user_agent: str,
        body: dict | None = None,
    ) -> int | str:
        headers = {"X-Forwarded-For": client_ip, "User-Agent": user_agent}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                status: int | str = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            status = "no-response"
        self.statuses[status] += 1
        return status

    def summary(self) -> str:
        parts = sorted(self.statuses.items(), key=lambda item: str(item[0]))
        return ", ".join(f"{status}: {count}" for status, count in parts) or "nema zahtjeva"


def _normal_request(client: Client) -> None:
    ip = random.choice(NORMAL_CLIENTS)
    agent = random.choice(USER_AGENTS)

    def get(path: str) -> None:
        client.request("GET", path, ip, agent)

    roll = random.random()
    if roll < 0.35:
        get(f"/orders?limit={random.randint(5, 50)}")
    elif roll < 0.60:
        get(f"/users/{random.randint(1, 5)}")
    elif roll < 0.68:
        get(f"/users/{random.randint(1000, 9999)}")
    elif roll < 0.78:
        get("/reports/daily")
    elif roll < 0.84:
        get(f"/reports/average?days={random.choice([7, 14, 30])}")
    elif roll < 0.85:
        get("/reports/average?days=0")
    elif roll < 0.93:
        body = {"username": random.choice(DEMO_USERS), "password": DEMO_PASSWORD}
        client.request("POST", "/login", ip, agent, body)
    elif roll < 0.94:
        body = {"username": random.choice(DEMO_USERS), "password": "wrong-password"}
        client.request("POST", "/login", ip, agent, body)
    else:
        body = {
            "user_id": random.randint(1, 5),
            "item": f"item-{random.randint(0, 11)}",
            "amount": round(random.uniform(10, 100), 2),
        }
        client.request("POST", "/orders", ip, agent, body)


def _paced(rate: float, duration: float | None, action: Callable[[], object]) -> None:
    """Izvodi akciju zadanim tempom, bez kraja ako duration nije zadan."""
    interval = 1 / rate
    deadline = None if duration is None else time.monotonic() + duration
    while deadline is None or time.monotonic() < deadline:
        action()
        time.sleep(interval)


def normal(client: Client, args: argparse.Namespace) -> None:
    _paced(args.rate, args.duration, lambda: _normal_request(client))


def bruteforce(client: Client, args: argparse.Namespace) -> None:
    ip = f"{ATTACKER_NET}.{random.randint(1, 254)}"
    print(f"bruteforce s adrese {ip}")

    def attempt() -> None:
        body = {
            "username": random.choice(COMMON_USERNAMES),
            "password": random.choice(COMMON_PASSWORDS),
        }
        client.request("POST", "/login", ip, ATTACK_USER_AGENT, body)

    _paced(args.rate, args.duration, attempt)


def scan(client: Client, args: argparse.Namespace) -> None:
    ip = f"{ATTACKER_NET}.{random.randint(1, 254)}"
    print(f"skeniranje s adrese {ip}")
    _paced(
        args.rate,
        args.duration,
        lambda: client.request("GET", random.choice(SCAN_PATHS), ip, ATTACK_USER_AGENT),
    )


def _docker(action: str) -> None:
    subprocess.run(["docker", action, POSTGRES_CONTAINER], check=True, capture_output=True)


def db_outage(client: Client, args: argparse.Namespace) -> None:
    if shutil.which("docker") is None:
        sys.exit("db-outage treba Docker CLI, pokreni scenarij na hostu.")

    print(f"gasim {POSTGRES_CONTAINER} na {args.duration:.0f} s")
    _docker("stop")
    try:
        _paced(args.rate, args.duration, lambda: _normal_request(client))
    finally:
        _docker("start")
    print("baza je ponovno pokrenuta, čekam oporavak aplikacije")

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if client.request("GET", "/orders?limit=1", NORMAL_CLIENTS[0], USER_AGENTS[0]) == 200:
            print("aplikacija se oporavila")
            return
        time.sleep(1)
    sys.exit("aplikacija se nije oporavila unutar 120 s")


# scenarij: (funkcija, zadano trajanje u sekundama, zadani broj zahtjeva u sekundi)
SCENARIOS = {
    "normal": (normal, None, 1.0),
    "db-outage": (db_outage, 60.0, 5.0),
    "bruteforce": (bruteforce, 15.0, 10.0),
    "scan": (scan, 10.0, 20.0),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generator prometa za demo aplikaciju.")
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument("--duration", type=float, help="trajanje u sekundama")
    parser.add_argument("--rate", type=float, help="broj zahtjeva u sekundi")
    args = parser.parse_args()

    _, default_duration, default_rate = SCENARIOS[args.scenario]
    args.duration = args.duration if args.duration is not None else default_duration
    args.rate = args.rate if args.rate is not None else default_rate
    if args.rate <= 0:
        parser.error("--rate mora biti veći od 0")
    return args


def main() -> None:
    # SIGTERM kao izlaz iz programa: docker stop završava odmah, a db-outage
    # kroz finally svejedno vraća bazu.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    args = parse_args()
    client = Client(args.base_url)
    run, _, _ = SCENARIOS[args.scenario]
    try:
        run(client, args)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"{args.scenario}: {client.summary()}")


if __name__ == "__main__":
    main()
