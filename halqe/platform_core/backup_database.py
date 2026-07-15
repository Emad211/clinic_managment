from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg import sql

from platform_core.backup_canonical import (
    BackupVerificationError,
    aggregate_digest,
    canonical,
    digest_records,
)


PROTECTED_SCHEMAS = ["platform", "accounting", "clinical"]
REQUIRED_ROLES = ["platform_app", "accounting_app", "clinical_app"]


@dataclass(frozen=True)
class ColumnFingerprint:
    name: str
    data_type: str
    not_null: bool
    identity: str
    generated: str
    default: str | None


@dataclass(frozen=True)
class TableFingerprint:
    schema: str
    table: str
    columns: tuple[ColumnFingerprint, ...]
    primary_key: tuple[str, ...]
    row_count: int
    row_sha256: str


@dataclass(frozen=True)
class SequenceFingerprint:
    schema: str
    sequence: str
    last_value: int
    is_called: bool


@dataclass(frozen=True)
class CatalogFingerprint:
    category: str
    object_count: int
    sha256: str


@dataclass(frozen=True)
class DatabaseFingerprint:
    database_name: str
    server_version_num: int
    server_major: int
    encoding: str
    collate: str
    ctype: str
    timezone: str
    extensions: tuple[dict[str, Any], ...]
    required_roles: tuple[dict[str, Any], ...]
    schema_ledger: tuple[dict[str, Any], ...]
    catalogs: tuple[CatalogFingerprint, ...]
    tables: tuple[TableFingerprint, ...]
    sequences: tuple[SequenceFingerprint, ...]
    schema_sha256: str
    content_sha256: str
    database_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict_rows(cursor) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _catalog_queries() -> dict[str, str]:
    return {
        "schemas": """
            SELECT n.nspname AS schema_name,COALESCE(n.nspacl::text,'') AS acl
            FROM pg_namespace n WHERE n.nspname=ANY(%s)
            ORDER BY n.nspname
        """,
        "relations": """
            SELECT n.nspname AS schema_name,c.relname,c.relkind,
                   c.relrowsecurity,c.relforcerowsecurity,
                   COALESCE(c.relacl::text,'') AS acl
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p','v','m','S')
            ORDER BY n.nspname,c.relname,c.relkind
        """,
        "columns": """
            SELECT n.nspname AS schema_name,c.relname,a.attnum,a.attname,
                   format_type(a.atttypid,a.atttypmod) AS data_type,
                   a.attnotnull,a.attidentity,a.attgenerated,
                   COALESCE(coll.collname,'') AS collation,
                   pg_get_expr(d.adbin,d.adrelid,true) AS default_expression
            FROM pg_attribute a
            JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
            LEFT JOIN pg_collation coll ON coll.oid=a.attcollation
            WHERE n.nspname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
              AND c.relkind IN ('r','p','v','m')
            ORDER BY n.nspname,c.relname,a.attnum
        """,
        "constraints": """
            SELECT n.nspname AS schema_name,c.relname,con.conname,con.contype,
                   con.condeferrable,con.condeferred,con.convalidated,
                   pg_get_constraintdef(con.oid,true) AS definition
            FROM pg_constraint con
            JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname,con.conname
        """,
        "indexes": """
            SELECT n.nspname AS schema_name,t.relname AS table_name,
                   i.relname AS index_name,ix.indisunique,ix.indisprimary,ix.indisvalid,
                   pg_get_indexdef(ix.indexrelid,0,true) AS definition
            FROM pg_index ix
            JOIN pg_class t ON t.oid=ix.indrelid
            JOIN pg_class i ON i.oid=ix.indexrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=ANY(%s)
            ORDER BY n.nspname,t.relname,i.relname
        """,
        "policies": """
            SELECT n.nspname AS schema_name,c.relname,p.polname,
                   p.polpermissive,p.polcmd,
                   ARRAY(
                     SELECT COALESCE(r.rolname,'public')
                     FROM unnest(p.polroles) role_oid
                     LEFT JOIN pg_roles r ON r.oid=role_oid
                     ORDER BY COALESCE(r.rolname,'public')
                   ) AS roles,
                   pg_get_expr(p.polqual,p.polrelid,true) AS using_expression,
                   pg_get_expr(p.polwithcheck,p.polrelid,true) AS check_expression
            FROM pg_policy p
            JOIN pg_class c ON c.oid=p.polrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname,p.polname
        """,
        "triggers": """
            SELECT n.nspname AS schema_name,c.relname,t.tgname,t.tgenabled,
                   pg_get_triggerdef(t.oid,true) AS definition
            FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND NOT t.tgisinternal
            ORDER BY n.nspname,c.relname,t.tgname
        """,
        "functions": """
            SELECT n.nspname AS schema_name,p.proname,
                   pg_get_function_identity_arguments(p.oid) AS identity_arguments,
                   p.prokind,p.prosecdef,p.provolatile,p.proparallel,
                   COALESCE(p.proacl::text,'') AS acl,
                   pg_get_functiondef(p.oid) AS definition
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p')
            ORDER BY n.nspname,p.proname,identity_arguments
        """,
    }


def _catalogs(conn: psycopg.Connection) -> tuple[CatalogFingerprint, ...]:
    result: list[CatalogFingerprint] = []
    for category, query in _catalog_queries().items():
        with conn.cursor() as cursor:
            cursor.execute(query, [PROTECTED_SCHEMAS])
            records = _dict_rows(cursor)
        count, digest = digest_records(records)
        result.append(CatalogFingerprint(category, count, digest))
    return tuple(result)


def _table_metadata(
    conn: psycopg.Connection,
    relation_oid: int,
) -> tuple[tuple[ColumnFingerprint, ...], tuple[str, ...]]:
    rows = conn.execute(
        """
        SELECT a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
               a.attidentity,a.attgenerated,
               pg_get_expr(d.adbin,d.adrelid,true)
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        [relation_oid],
    ).fetchall()
    columns = tuple(
        ColumnFingerprint(
            name=row[0],
            data_type=row[1],
            not_null=bool(row[2]),
            identity=row[3] or "",
            generated=row[4] or "",
            default=row[5],
        )
        for row in rows
    )
    primary_key = tuple(
        row[0]
        for row in conn.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum,ord)
              ON TRUE
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
            WHERE i.indrelid=%s AND i.indisprimary
            ORDER BY k.ord
            """,
            [relation_oid],
        ).fetchall()
    )
    return columns, primary_key


def _table_fingerprint(
    conn: psycopg.Connection,
    *,
    relation_oid: int,
    schema_name: str,
    table_name: str,
) -> TableFingerprint:
    columns, primary_key = _table_metadata(conn, relation_oid)
    if not primary_key:
        raise BackupVerificationError(
            f"Cannot fingerprint table without a primary key: {schema_name}.{table_name}"
        )
    query = sql.SQL("SELECT {} FROM {}.{} ORDER BY {}").format(
        sql.SQL(",").join(sql.Identifier(column.name) for column in columns),
        sql.Identifier(schema_name),
        sql.Identifier(table_name),
        sql.SQL(",").join(sql.Identifier(column) for column in primary_key),
    )

    def records():
        with conn.cursor(name=f"backup_{relation_oid}") as cursor:
            cursor.itersize = 1000
            cursor.execute(query)
            for row in cursor:
                yield [canonical(value) for value in row]

    row_count, row_sha256 = digest_records(records())
    return TableFingerprint(
        schema=schema_name,
        table=table_name,
        columns=columns,
        primary_key=primary_key,
        row_count=row_count,
        row_sha256=row_sha256,
    )


def _tables(conn: psycopg.Connection) -> tuple[TableFingerprint, ...]:
    rows = conn.execute(
        """
        SELECT c.oid,n.nspname,c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind='r'
        ORDER BY n.nspname,c.relname
        """,
        [PROTECTED_SCHEMAS],
    ).fetchall()
    return tuple(
        _table_fingerprint(
            conn,
            relation_oid=int(oid),
            schema_name=schema_name,
            table_name=table_name,
        )
        for oid, schema_name, table_name in rows
    )


def _sequences(conn: psycopg.Connection) -> tuple[SequenceFingerprint, ...]:
    rows = conn.execute(
        """
        SELECT n.nspname,c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind='S'
        ORDER BY n.nspname,c.relname
        """,
        [PROTECTED_SCHEMAS],
    ).fetchall()
    result: list[SequenceFingerprint] = []
    for schema_name, sequence_name in rows:
        query = sql.SQL("SELECT last_value,is_called FROM {}.{}").format(
            sql.Identifier(schema_name),
            sql.Identifier(sequence_name),
        )
        last_value, is_called = conn.execute(query).fetchone()
        result.append(
            SequenceFingerprint(
                schema=schema_name,
                sequence=sequence_name,
                last_value=int(last_value),
                is_called=bool(is_called),
            )
        )
    return tuple(result)


def capture_database_fingerprint(conn: psycopg.Connection) -> DatabaseFingerprint:
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    metadata = conn.execute(
        """
        SELECT current_database(),current_setting('server_version_num')::integer,
               pg_encoding_to_char(encoding),datcollate,datctype,
               current_setting('TimeZone')
        FROM pg_database WHERE datname=current_database()
        """
    ).fetchone()
    database_name, version_num, encoding, collate, ctype, timezone = metadata
    extensions = tuple(
        {"name": row[0], "version": row[1], "schema": row[2]}
        for row in conn.execute(
            """
            SELECT e.extname,e.extversion,n.nspname
            FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
            ORDER BY e.extname
            """
        ).fetchall()
    )
    required_roles = tuple(
        {
            "name": row[0],
            "superuser": bool(row[1]),
            "inherit": bool(row[2]),
            "create_role": bool(row[3]),
            "create_db": bool(row[4]),
            "can_login": bool(row[5]),
            "replication": bool(row[6]),
            "bypass_rls": bool(row[7]),
        }
        for row in conn.execute(
            """
            SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
                   rolcanlogin,rolreplication,rolbypassrls
            FROM pg_roles WHERE rolname=ANY(%s) ORDER BY rolname
            """,
            [REQUIRED_ROLES],
        ).fetchall()
    )
    if {role["name"] for role in required_roles} != set(REQUIRED_ROLES):
        raise BackupVerificationError("Required Halqe database roles are missing")
    has_ledger = conn.execute(
        "SELECT to_regclass('platform.schema_version') IS NOT NULL"
    ).fetchone()[0]
    schema_ledger = tuple(
        {"filename": row[0], "checksum": row[1]}
        for row in (
            conn.execute(
                "SELECT filename,checksum FROM platform.schema_version ORDER BY filename"
            ).fetchall()
            if has_ledger
            else []
        )
    )
    catalogs = _catalogs(conn)
    tables = _tables(conn)
    sequences = _sequences(conn)
    schema_payload = {
        "catalogs": [asdict(item) for item in catalogs],
        "extensions": extensions,
        "required_roles": required_roles,
        "schema_ledger": schema_ledger,
        "encoding": encoding,
        "collate": collate,
        "ctype": ctype,
    }
    content_payload = {
        "tables": [asdict(item) for item in tables],
        "sequences": [asdict(item) for item in sequences],
    }
    schema_sha256 = aggregate_digest(schema_payload)
    content_sha256 = aggregate_digest(content_payload)
    server_major = int(version_num) // 10000
    database_sha256 = aggregate_digest(
        {
            "server_major": server_major,
            "timezone": timezone,
            "schema_sha256": schema_sha256,
            "content_sha256": content_sha256,
        }
    )
    return DatabaseFingerprint(
        database_name=database_name,
        server_version_num=int(version_num),
        server_major=server_major,
        encoding=encoding,
        collate=collate,
        ctype=ctype,
        timezone=timezone,
        extensions=extensions,
        required_roles=required_roles,
        schema_ledger=schema_ledger,
        catalogs=catalogs,
        tables=tables,
        sequences=sequences,
        schema_sha256=schema_sha256,
        content_sha256=content_sha256,
        database_sha256=database_sha256,
    )
