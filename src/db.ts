/**
 * D1 access.
 *
 * The SQL is written once and run directly; D1 is SQLite, so the statements are the
 * same ones the schema in migrations/ creates. Helpers here only cover the shapes the
 * app needs: a list of rows, one row, one value, and an atomic batch.
 */

export class UniqueViolation extends Error {}

function wrap(error: unknown): never {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("UNIQUE constraint failed")) throw new UniqueViolation(message);
  throw error;
}

export class Db {
  constructor(private readonly d1: D1Database) {}

  private stmt(sql: string, params: unknown[]): D1PreparedStatement {
    const prepared = this.d1.prepare(sql);
    return params.length ? prepared.bind(...params) : prepared;
  }

  async query<T = Record<string, unknown>>(sql: string, params: unknown[] = []): Promise<T[]> {
    try {
      const { results } = await this.stmt(sql, params).all<T>();
      return results ?? [];
    } catch (error) {
      wrap(error);
    }
  }

  async queryOne<T = Record<string, unknown>>(
    sql: string,
    params: unknown[] = [],
  ): Promise<T | null> {
    try {
      return (await this.stmt(sql, params).first<T>()) ?? null;
    } catch (error) {
      wrap(error);
    }
  }

  async value<T>(sql: string, params: unknown[] = []): Promise<T | null> {
    try {
      return (await this.stmt(sql, params).first<T>(undefined as never)) ?? null;
    } catch (error) {
      wrap(error);
    }
  }

  async run(sql: string, params: unknown[] = []): Promise<D1Result> {
    try {
      return await this.stmt(sql, params).run();
    } catch (error) {
      wrap(error);
    }
  }

  /** Several writes that must all land or none: D1's only atomic primitive. */
  async batch(statements: Array<[string, unknown[]]>): Promise<void> {
    if (!statements.length) return;
    try {
      await this.d1.batch(statements.map(([sql, params]) => this.stmt(sql, params)));
    } catch (error) {
      wrap(error);
    }
  }
}
