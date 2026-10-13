"""Database access for both runtimes.

D1 is SQLite, so one set of SQL statements serves both backends:

- `D1Database` wraps the Worker's D1 binding (production).
- `SqliteDatabase` wraps a local sqlite3 file (tests and `uvicorn` dev).

Everything is async because D1 is. Rows come back as plain dicts so callers never
hold a runtime-specific object.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from starlette.requests import Request

Params = tuple[Any, ...]
Row = dict[str, Any]


class UniqueViolation(Exception):
    """A UNIQUE constraint rejected a write, in either backend."""


class Result:
    def __init__(self, last_row_id: int | None, rows_affected: int) -> None:
        self.last_row_id = last_row_id
        self.rows_affected = rows_affected


class Database:
    """Interface the services layer codes against."""

    async def query(self, sql: str, params: Params = ()) -> list[Row]:
        raise NotImplementedError

    async def query_one(self, sql: str, params: Params = ()) -> Row | None:
        rows = await self.query(sql, params)
        return rows[0] if rows else None

    async def value(self, sql: str, params: Params = ()) -> Any:
        """First column of the first row, or None."""
        row = await self.query_one(sql, params)
        return next(iter(row.values())) if row else None

    async def execute(self, sql: str, params: Params = ()) -> Result:
        raise NotImplementedError

    async def batch(self, statements: list[tuple[str, Params]]) -> None:
        """Run several writes atomically — all of them land, or none do."""
        raise NotImplementedError


# --- Production: Cloudflare D1 -------------------------------------------------


def _is_unique_violation(exc: Exception) -> bool:
    return "UNIQUE constraint failed" in str(exc)


class D1Database(Database):
    def __init__(self, binding: Any) -> None:
        self._db = binding

    def _prepare(self, sql: str, params: Params):
        statement = self._db.prepare(sql)
        return statement.bind(*params) if params else statement

    async def query(self, sql: str, params: Params = ()) -> list[Row]:
        try:
            response = await self._prepare(sql, params).all()
        except Exception as exc:  # noqa: BLE001 - JS exception surfaces untyped
            if _is_unique_violation(exc):
                raise UniqueViolation(str(exc)) from exc
            raise
        return _rows_to_dicts(response.results)

    async def execute(self, sql: str, params: Params = ()) -> Result:
        try:
            response = await self._prepare(sql, params).run()
        except Exception as exc:  # noqa: BLE001
            if _is_unique_violation(exc):
                raise UniqueViolation(str(exc)) from exc
            raise
        meta = response.meta
        return Result(
            last_row_id=getattr(meta, "last_row_id", None),
            rows_affected=getattr(meta, "changes", 0) or 0,
        )

    async def batch(self, statements: list[tuple[str, Params]]) -> None:
        if not statements:
            return
        prepared = [self._prepare(sql, params) for sql, params in statements]
        try:
            await self._db.batch(prepared)
        except Exception as exc:  # noqa: BLE001
            if _is_unique_violation(exc):
                raise UniqueViolation(str(exc)) from exc
            raise


def _rows_to_dicts(results: Any) -> list[Row]:
    """Convert D1's result set to plain dicts.

    Depending on the runtime, `results` can already be Python objects or a JS
    proxy, so unwrap whichever shape turns up rather than assuming one.
    """
    if results is None:
        return []
    to_py = getattr(results, "to_py", None)
    if to_py is not None:
        results = to_py()
    return [_row_to_dict(row) for row in results]


def _row_to_dict(row: Any) -> Row:
    if isinstance(row, dict):
        return row
    to_py = getattr(row, "to_py", None)
    if to_py is not None:
        converted = to_py()
        return converted if isinstance(converted, dict) else dict(converted)
    from js import Object  # type: ignore[import-not-found]

    return {key: getattr(row, key) for key in Object.keys(row)}


# --- Tests and local dev: a plain SQLite file ----------------------------------


class SqliteDatabase(Database):
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")

    async def query(self, sql: str, params: Params = ()) -> list[Row]:
        try:
            cursor = self._conn.execute(sql, params)
        except sqlite3.IntegrityError as exc:
            raise UniqueViolation(str(exc)) from exc
        return [dict(row) for row in cursor.fetchall()]

    async def execute(self, sql: str, params: Params = ()) -> Result:
        try:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise UniqueViolation(str(exc)) from exc
        return Result(last_row_id=cursor.lastrowid, rows_affected=cursor.rowcount)

    async def batch(self, statements: list[tuple[str, Params]]) -> None:
        try:
            for sql, params in statements:
                self._conn.execute(sql, params)
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            self._conn.rollback()
            raise UniqueViolation(str(exc)) from exc

    def close(self) -> None:
        self._conn.close()


async def get_db(request: Request) -> Database:
    """FastAPI dependency: the app's database, or this request's D1 binding.

    Async on purpose: Workers has no threads, and FastAPI runs sync dependencies
    in a threadpool.
    """
    database = request.app.state.database
    if database is not None:
        return database
    return D1Database(request.scope["env"].DB)


def apply_schema(path: str, schema_sql: str) -> None:
    """Create a local SQLite database from the D1 migration SQL."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
