/** Apply the real migration SQL to the test database, exactly as D1 would. */
import schema from "../migrations/0001_initial.sql";

const TABLES = [
  "fpga_reservation", "fpga_placement", "fpga_server", "fpga_type",
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
  for (const statement of statementsOf(schema)) {
    await db.prepare(statement).run();
  }
}
