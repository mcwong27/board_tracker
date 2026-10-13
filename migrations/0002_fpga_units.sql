-- Individual FPGA boards, replacing the per-server counts.
--
-- fpga_placement recorded "how many of this model are in this server", which gave
-- boards no identity of their own: the timeline numbered them positionally, so
-- lowering a count silently moved bookings between boards. A row per board fixes
-- that and gives somewhere to record a serial.
--
-- Serials are optional (you may know a board exists before you have labelled it) and
-- unique when present, so a serial always identifies exactly one board. Blank serials
-- are stored as NULL so the partial unique index ignores them.

CREATE TABLE fpga_unit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fpga_type_id INTEGER NOT NULL REFERENCES fpga_type(id),
    server_id    INTEGER NOT NULL REFERENCES fpga_server(id),
    serial       TEXT,
    created_at   TEXT    NOT NULL
);

CREATE UNIQUE INDEX uq_fpga_unit_serial
    ON fpga_unit (serial) WHERE serial IS NOT NULL;
CREATE INDEX ix_fpga_unit_type_server ON fpga_unit (fpga_type_id, server_id);

-- Expand each count into that many unnamed boards, so existing capacity is preserved.
INSERT INTO fpga_unit (fpga_type_id, server_id, serial, created_at)
SELECT p.fpga_type_id, p.server_id, NULL, '2026-01-01 00:00:00'
FROM fpga_placement p
JOIN (
    WITH RECURSIVE counter(n) AS (
        SELECT 1
        UNION ALL
        SELECT n + 1 FROM counter
        WHERE n < (SELECT COALESCE(MAX(quantity), 0) FROM fpga_placement)
    )
    SELECT n FROM counter
) c ON c.n <= p.quantity;

DROP TABLE fpga_placement;
