import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

describe("test database isolation", () => {
  it("runs against a local database, never the deployed one", async () => {
    // A table that only exists here proves this isn't the production database.
    await env.DB.prepare("CREATE TABLE IF NOT EXISTS canary (id INTEGER PRIMARY KEY)").run();
    await env.DB.prepare("INSERT INTO canary (id) VALUES (1)").run();
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM canary").first<{ n: number }>();
    expect(row?.n).toBe(1);

    // Production has the real schema; a pristine local database does not.
    const tables = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='asset'",
    ).all();
    expect(tables.results.length, "local test DB should not contain production tables").toBe(0);
  });
});
