/** Build the test database from the real migrations, in order, as D1 would. */
import initial from "../migrations/0001_initial.sql";
import units from "../migrations/0002_fpga_units.sql";

const MIGRATIONS = [initial, units];

// Dropped before each test; ordered so dependants go first.
const TABLES = [
  "fpga_reservation", "fpga_unit", "fpga_placement", "fpga_server", "fpga_type",
  "checkout", "asset", "asset_type",
];

export function statementsOf(sql: string): string[] {
  return sql
    .split("\n")
    .map((line) => line.replace(/--.*$/, "")) // strip comments; none contain a ';'
    .join("\n")
    .split(";")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export async function applySchema(db: D1Database): Promise<void> {
  for (const table of TABLES) {
    await db.prepare(`DROP TABLE IF EXISTS ${table}`).run();
  }
  for (const migration of MIGRATIONS) {
    for (const statement of statementsOf(migration)) {
      await db.prepare(statement).run();
    }
  }
}
