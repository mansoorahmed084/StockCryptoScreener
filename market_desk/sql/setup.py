"""One-time setup of the Market Desk database on Supabase.

  .venv/Scripts/python.exe -m market_desk.sql.setup --token-file <path to a .env with SUPABASE_ACCESS_TOKEN>

Needs MARKET_DESK_SUPABASE_REF in this repo's .env. It runs 001_schema.sql
through the Supabase Management API, makes (or resets) the two logins
desk_writer and desk_viewer with new random passwords, and writes

  MARKET_DESK_DB_URL       desk_writer: the server jobs and the laptop
  MARKET_DESK_VIEW_DB_URL  desk_viewer: the Streamlit Cloud page

into .env. Passwords are never printed. Safe to run again (it resets the
two passwords, so copy the new lines to the server and Streamlit after).
"""
from __future__ import annotations

import argparse
import re
import secrets
import string
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"
API = "https://api.supabase.com/v1"


def _env_value(path: Path, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", path.read_text(encoding="utf-8"), re.M)
    if not m or not m.group(1).strip():
        raise SystemExit(f"{key} is not in {path}")
    return m.group(1).strip().strip("\"'")


def _set_env(key: str, value: str) -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=", text, re.M):
        text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    ENV.write_text(text, encoding="utf-8")


def _password() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", required=True, type=Path)
    args = ap.parse_args()
    token = _env_value(args.token_file, "SUPABASE_ACCESS_TOKEN")
    ref = _env_value(ENV, "MARKET_DESK_SUPABASE_REF")
    client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"})

    def sql(query: str) -> list:
        r = client.post(f"{API}/projects/{ref}/database/query", json={"query": query})
        if r.status_code >= 300:
            raise SystemExit(f"SQL failed ({r.status_code}): {r.text[:300]}")
        return r.json()

    sql((Path(__file__).with_name("001_schema.sql")).read_text(encoding="utf-8"))
    print("schema desk: tables ready")

    pw = {"desk_writer": _password(), "desk_viewer": _password()}
    roles = "\n".join(
        f"if exists (select 1 from pg_roles where rolname = '{r}') then "
        f"alter role {r} with login password '{p}'; "
        f"else create role {r} with login password '{p}'; end if;"
        for r, p in pw.items())
    sql(f"do $$ begin\n{roles}\nend $$;")
    sql("""
grant usage on schema desk to desk_writer, desk_viewer;
grant select, insert, update, delete on all tables in schema desk to desk_writer;
grant usage, select on all sequences in schema desk to desk_writer;
grant select on all tables in schema desk to desk_viewer;
grant insert, delete on desk.alerts to desk_viewer;
grant usage, select on all sequences in schema desk to desk_viewer;
alter default privileges in schema desk grant select, insert, update, delete on tables to desk_writer;
alter default privileges in schema desk grant usage, select on sequences to desk_writer;
alter default privileges in schema desk grant select on tables to desk_viewer;
alter role desk_writer set search_path = desk;
alter role desk_viewer set search_path = desk;
alter role desk_viewer set statement_timeout = '20s';
""")
    print("logins desk_writer + desk_viewer: ready")

    r = client.get(f"{API}/projects/{ref}/config/database/pooler")
    r.raise_for_status()
    pools = r.json()
    pool = next((p for p in pools if p.get("database_type") == "PRIMARY"), pools[0])
    host = pool["db_host"]
    for key, role in (("MARKET_DESK_DB_URL", "desk_writer"),
                      ("MARKET_DESK_VIEW_DB_URL", "desk_viewer")):
        _set_env(key, f"postgresql://{role}.{ref}:{pw[role]}@{host}:5432/postgres"
                      "?sslmode=require")
    print(f"pooler {host}:5432 (session mode); MARKET_DESK_DB_URL and "
          "MARKET_DESK_VIEW_DB_URL written to .env")


if __name__ == "__main__":
    main()
