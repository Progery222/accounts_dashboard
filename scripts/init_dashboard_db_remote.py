#!/usr/bin/env python3
"""Создать роль/БД dashboard в shared-postgres на VPS."""
import re
import subprocess
from pathlib import Path

env_path = Path("/opt/dashboard/.env")
env = env_path.read_text(encoding="utf-8")
m = re.search(r"^DB_PASSWORD=(.+)$", env, re.M)
pwd = (m.group(1).strip() if m else "").replace("'", "''")

sql_role = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dashboard') THEN
    CREATE ROLE dashboard LOGIN PASSWORD '{pwd}';
  ELSE
    ALTER ROLE dashboard WITH PASSWORD '{pwd}';
  END IF;
END $$;
"""

subprocess.run(
    [
        "docker",
        "exec",
        "-i",
        "shared-postgres",
        "psql",
        "-U",
        "zavod",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql_role,
    ],
    check=True,
)

r = subprocess.run(
    [
        "docker",
        "exec",
        "shared-postgres",
        "psql",
        "-U",
        "zavod",
        "-d",
        "postgres",
        "-tAc",
        "SELECT 1 FROM pg_database WHERE datname='dashboard'",
    ],
    capture_output=True,
    text=True,
    check=True,
)
if r.stdout.strip() != "1":
    subprocess.run(
        [
            "docker",
            "exec",
            "shared-postgres",
            "psql",
            "-U",
            "zavod",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE DATABASE dashboard OWNER dashboard;",
        ],
        check=True,
    )
print("db_ok")
