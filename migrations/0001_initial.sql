-- bTrack initial schema.
--
-- Applied to D1 with `wrangler d1 migrations apply btrack`, and to a local SQLite
-- file by the test fixtures and the local dev server. D1 is SQLite, so this file is
-- the single source of truth for both.
--
-- Dates and datetimes are stored as ISO-8601 text: 'YYYY-MM-DD' for dates and
-- 'YYYY-MM-DD HH:MM:SS' (naive UTC) for datetimes.

CREATE TABLE asset_type (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    -- Admins can order types by hand; equal values fall back to alphabetical.
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE asset (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    type_id      INTEGER NOT NULL REFERENCES asset_type(id),
    serial       TEXT    NOT NULL DEFAULT '',
    chip_mounted TEXT    NOT NULL DEFAULT '',
    location     TEXT    NOT NULL DEFAULT '',
    notes        TEXT    NOT NULL DEFAULT '',
    retired      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);

CREATE TABLE checkout (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id       INTEGER NOT NULL REFERENCES asset(id),
    user_email     TEXT    NOT NULL,
    user_name      TEXT    NOT NULL DEFAULT '',
    checked_out_at TEXT    NOT NULL,
    returned_at    TEXT,
    returned_by    TEXT,
    notes          TEXT    NOT NULL DEFAULT ''
);

-- At most one active (unreturned) checkout per asset, enforced by the database
-- rather than by UI checks alone.
CREATE UNIQUE INDEX uq_checkout_active_asset
    ON checkout (asset_id) WHERE returned_at IS NULL;
CREATE INDEX ix_checkout_user_email ON checkout (user_email);

CREATE TABLE fpga_type (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

CREATE TABLE fpga_server (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    NOT NULL UNIQUE,
    notes TEXT    NOT NULL DEFAULT ''
);

-- How many FPGAs of one type are installed in one server.
CREATE TABLE fpga_placement (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fpga_type_id INTEGER NOT NULL REFERENCES fpga_type(id) ON DELETE CASCADE,
    server_id    INTEGER NOT NULL REFERENCES fpga_server(id) ON DELETE CASCADE,
    quantity     INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_fpga_placement_type_server UNIQUE (fpga_type_id, server_id)
);

CREATE TABLE fpga_reservation (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fpga_type_id     INTEGER NOT NULL REFERENCES fpga_type(id),
    -- Nullable only for rows that predate servers being recorded; new
    -- reservations must name a server.
    server_id        INTEGER REFERENCES fpga_server(id),
    project          TEXT    NOT NULL,
    quantity         INTEGER NOT NULL DEFAULT 1,
    contact          TEXT    NOT NULL DEFAULT '',
    special_requests TEXT    NOT NULL DEFAULT '',
    start_date       TEXT    NOT NULL,
    end_date         TEXT    NOT NULL,
    created_by_email TEXT    NOT NULL,
    created_at       TEXT    NOT NULL
);

CREATE INDEX ix_fpga_reservation_dates ON fpga_reservation (start_date, end_date);

-- The FPGA models the lab has today; admins add more from the admin page.
INSERT INTO fpga_type (name) VALUES
    ('U250'), ('XB10'), ('VCU118'), ('U200'), ('U280'), ('V80'),
    ('RHS Research Nitefury II');
