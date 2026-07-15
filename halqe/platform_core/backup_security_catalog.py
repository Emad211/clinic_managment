from __future__ import annotations

from typing import Any

import psycopg

from platform_core._backup_database_core import (
    CatalogFingerprint,
    PROTECTED_SCHEMAS,
    REQUIRED_ROLES,
)
from platform_core.backup_canonical import digest_records


def _dict_rows(cursor) -> list[dict[str, Any]]:
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _query_specs() -> dict[str, tuple[str, list[Any]]]:
    return {
        "database_security": (
            """
            SELECT current_database() AS database_name,
                   pg_get_userbyid(d.datdba) AS owner,
                   COALESCE(ts.spcname, '') AS tablespace,
                   COALESCE(shobj_description(d.oid, 'pg_database'), '') AS comment,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(d.datacl) item
                   ), ARRAY[]::text[]) AS acl
            FROM pg_database d
            LEFT JOIN pg_tablespace ts ON ts.oid=d.dattablespace
            WHERE d.datname=current_database()
            """,
            [],
        ),
        "schema_security": (
            """
            SELECT n.nspname AS schema_name,
                   pg_get_userbyid(n.nspowner) AS owner,
                   COALESCE(obj_description(n.oid, 'pg_namespace'), '') AS comment,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(n.nspacl) item
                   ), ARRAY[]::text[]) AS acl
            FROM pg_namespace n
            WHERE n.nspname=ANY(%s)
            ORDER BY n.nspname
            """,
            [PROTECTED_SCHEMAS],
        ),
        "relation_security": (
            """
            SELECT n.nspname AS schema_name,c.relname,c.relkind,
                   pg_get_userbyid(c.relowner) AS owner,
                   c.relpersistence,c.relreplident,
                   COALESCE(c.reloptions, ARRAY[]::text[]) AS options,
                   COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(c.relacl) item
                   ), ARRAY[]::text[]) AS acl
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s)
              AND c.relkind IN ('r','p','v','m','S','i')
            ORDER BY n.nspname,c.relname,c.relkind
            """,
            [PROTECTED_SCHEMAS],
        ),
        "default_acl": (
            """
            SELECT COALESCE(n.nspname, '') AS schema_name,
                   owner.rolname AS owner,
                   d.defaclobjtype AS object_type,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(d.defaclacl) item
                   ), ARRAY[]::text[]) AS grants
            FROM pg_default_acl d
            JOIN pg_roles owner ON owner.oid=d.defaclrole
            LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
            WHERE n.nspname=ANY(%s)
               OR (d.defaclnamespace=0 AND owner.rolname=ANY(%s))
            ORDER BY COALESCE(n.nspname, ''),owner.rolname,d.defaclobjtype
            """,
            [PROTECTED_SCHEMAS, REQUIRED_ROLES],
        ),
        "views": (
            """
            SELECT n.nspname AS schema_name,c.relname,c.relkind,
                   pg_get_userbyid(c.relowner) AS owner,
                   COALESCE(c.reloptions, ARRAY[]::text[]) AS options,
                   pg_get_viewdef(c.oid, true) AS definition,
                   COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND c.relkind IN ('v','m')
            ORDER BY n.nspname,c.relname,c.relkind
            """,
            [PROTECTED_SCHEMAS],
        ),
        "function_security": (
            """
            SELECT n.nspname AS schema_name,p.proname,
                   pg_get_function_identity_arguments(p.oid) AS identity_arguments,
                   p.prokind,pg_get_userbyid(p.proowner) AS owner,
                   p.prosecdef,p.proleakproof,p.provolatile,p.proparallel,
                   COALESCE(obj_description(p.oid, 'pg_proc'), '') AS comment,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(p.proacl) item
                   ), ARRAY[]::text[]) AS acl,
                   pg_get_functiondef(p.oid) AS definition
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p')
            ORDER BY n.nspname,p.proname,identity_arguments
            """,
            [PROTECTED_SCHEMAS],
        ),
        "types": (
            """
            SELECT n.nspname AS schema_name,t.typname,t.typtype,t.typcategory,
                   pg_get_userbyid(t.typowner) AS owner,
                   COALESCE(obj_description(t.oid, 'pg_type'), '') AS comment,
                   COALESCE((
                       SELECT array_agg(item::text ORDER BY item::text)
                       FROM unnest(t.typacl) item
                   ), ARRAY[]::text[]) AS acl,
                   CASE WHEN t.typtype='d' THEN format_type(t.typbasetype,t.typtypmod)
                        ELSE '' END AS domain_base_type,
                   COALESCE((
                       SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder)
                       FROM pg_enum e WHERE e.enumtypid=t.oid
                   ), ARRAY[]::text[]) AS enum_labels
            FROM pg_type t
            JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname=ANY(%s)
              AND t.typtype IN ('c','d','e','r','m')
            ORDER BY n.nspname,t.typname
            """,
            [PROTECTED_SCHEMAS],
        ),
        "comments": (
            """
            WITH described AS (
                SELECT 'schema'::text AS object_type,n.nspname AS schema_name,
                       n.nspname AS object_name,''::text AS sub_name,
                       obj_description(n.oid,'pg_namespace') AS comment
                FROM pg_namespace n
                WHERE n.nspname=ANY(%s)
                UNION ALL
                SELECT 'relation',n.nspname,c.relname,'',
                       obj_description(c.oid,'pg_class')
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s)
                UNION ALL
                SELECT 'column',n.nspname,c.relname,a.attname,
                       col_description(c.oid,a.attnum)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
                UNION ALL
                SELECT 'function',n.nspname,p.proname,
                       pg_get_function_identity_arguments(p.oid),
                       obj_description(p.oid,'pg_proc')
                FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p')
                UNION ALL
                SELECT 'constraint',n.nspname,COALESCE(c.relname,t.typname,''),
                       con.conname,obj_description(con.oid,'pg_constraint')
                FROM pg_constraint con
                JOIN pg_namespace n ON n.oid=con.connamespace
                LEFT JOIN pg_class c ON c.oid=con.conrelid
                LEFT JOIN pg_type t ON t.oid=con.contypid
                WHERE n.nspname=ANY(%s)
                UNION ALL
                SELECT 'policy',n.nspname,c.relname,p.polname,
                       obj_description(p.oid,'pg_policy')
                FROM pg_policy p
                JOIN pg_class c ON c.oid=p.polrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s)
                UNION ALL
                SELECT 'trigger',n.nspname,c.relname,tr.tgname,
                       obj_description(tr.oid,'pg_trigger')
                FROM pg_trigger tr
                JOIN pg_class c ON c.oid=tr.tgrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s) AND NOT tr.tgisinternal
                UNION ALL
                SELECT 'type',n.nspname,t.typname,'',
                       obj_description(t.oid,'pg_type')
                FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                WHERE n.nspname=ANY(%s)
            )
            SELECT object_type,schema_name,object_name,sub_name,comment
            FROM described
            WHERE comment IS NOT NULL
            ORDER BY object_type,schema_name,object_name,sub_name
            """,
            [PROTECTED_SCHEMAS] * 8,
        ),
    }


def capture_security_catalogs(
    conn: psycopg.Connection,
) -> tuple[CatalogFingerprint, ...]:
    result: list[CatalogFingerprint] = []
    for category, (query, params) in _query_specs().items():
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            records = _dict_rows(cursor)
        count, digest = digest_records(records)
        result.append(CatalogFingerprint(category, count, digest))
    return tuple(result)
