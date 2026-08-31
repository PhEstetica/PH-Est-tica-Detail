"""Migra os dados do SQLite da PH ESTÉTICA & DETAIL para PostgreSQL.

Uso futuro (quando houver servidor PostgreSQL):
  pip install -r requirements-postgres.txt
  set PH_POSTGRES_URL=postgresql+psycopg://usuario:senha@host:5432/banco
  python migrate_to_postgres.py

O app local continua usando SQLite; este utilitário prepara a migração do banco quando a
operação passar a usar um servidor centralizado.
"""
from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import MetaData, create_engine, text

BASE_DIR = Path(__file__).resolve().parent
SQLITE_PATH = Path(os.getenv("PH_DB_PATH", str(BASE_DIR / "ph_estetica.db")))
POSTGRES_URL = os.getenv("PH_POSTGRES_URL", "").strip()

if not POSTGRES_URL:
    raise SystemExit("Defina PH_POSTGRES_URL antes de executar.")
if not SQLITE_PATH.exists():
    raise SystemExit(f"Banco SQLite não encontrado: {SQLITE_PATH}")

source = create_engine(f"sqlite:///{SQLITE_PATH}")
target = create_engine(POSTGRES_URL)
metadata = MetaData()
metadata.reflect(bind=source)
metadata.create_all(bind=target)

with source.connect() as src, target.begin() as dst:
    # Limpa em ordem reversa para permitir repetir a migração em um banco de destino vazio/de teste.
    for table in reversed(metadata.sorted_tables):
        dst.execute(table.delete())
    for table in metadata.sorted_tables:
        rows = [dict(r._mapping) for r in src.execute(table.select()).fetchall()]
        if rows:
            dst.execute(table.insert(), rows)
            print(f"{table.name}: {len(rows)} registro(s)")

# Ajusta sequences de IDs no PostgreSQL após inserir chaves primárias vindas do SQLite.
with target.begin() as conn:
    for table in metadata.sorted_tables:
        pks = list(table.primary_key.columns)
        if len(pks) != 1:
            continue
        pk = pks[0]
        if str(pk.type).upper() not in {"INTEGER", "BIGINT", "SMALLINT"}:
            continue
        try:
            conn.execute(text(
                "SELECT setval(pg_get_serial_sequence(:table_name,:pk_name), "
                "GREATEST(COALESCE((SELECT MAX(\"%s\") FROM \"%s\"),1),1), true)" % (pk.name, table.name)
            ), {"table_name": table.name, "pk_name": pk.name})
        except Exception:
            # Algumas tabelas podem não usar sequence; isso não invalida a cópia dos dados.
            pass

print("Migração concluída. Valide o banco PostgreSQL antes de trocar o ambiente de produção.")
