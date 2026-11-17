CREATE TABLE users (
    id              serial PRIMARY KEY,
    username        text NOT NULL UNIQUE,
    password_sha256 text NOT NULL
);

CREATE TABLE orders (
    id         serial PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES users (id),
    item       text NOT NULL,
    amount     numeric(10, 2) NOT NULL CHECK (amount > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Izmišljeni računi demo aplikacije.
INSERT INTO users (username, password_sha256)
SELECT name, encode(sha256('demo-pass'::bytea), 'hex')
FROM unnest(ARRAY['alice', 'bob', 'carol', 'dave', 'erin']) AS name;

INSERT INTO orders (user_id, item, amount, created_at)
SELECT (n % 5) + 1,
       'item-' || (n % 12),
       round((random() * 90 + 10)::numeric, 2),
       now() - (n % 14) * interval '1 day'
FROM generate_series(1, 200) AS n;
