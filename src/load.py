import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.dialects.postgresql import insert

from src.utils import get_logger

load_dotenv()
logger = get_logger("load")

ROOT = Path(__file__).resolve().parent.parent


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


def create_tables(engine) -> None:
    sql = (ROOT / "sql" / "create_tables.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    logger.info("Schemas and tables ready")


def _count(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def _insert_ignore(engine, df: pd.DataFrame, table_name: str, conflict_cols: list[str]) -> None:
    """Insère les lignes ; ignore celles dont la clé existe déjà (idempotent)."""
    if df.empty:
        logger.warning("%s: nothing to load", table_name)
        return
    table = Table(table_name, MetaData(), schema="warehouse", autoload_with=engine)
    clean = df.astype(object).where(df.notna(), None)   # NaN / NaT -> None
    records = clean.to_dict("records")
    stmt = insert(table).on_conflict_do_nothing(index_elements=conflict_cols)

    before = _count(engine, f"warehouse.{table_name}")
    with engine.begin() as conn:
        conn.execute(stmt, records)
    after = _count(engine, f"warehouse.{table_name}")
    logger.info("%s: %d rows sent, %d new (total %d)",
                table_name, len(df), after - before, after)


def _upsert(engine, df: pd.DataFrame, table_name: str, conflict_cols: list[str]) -> None:
    """Insère ou met à jour (les attributs de la dimension peuvent changer)."""
    if df.empty:
        logger.warning("%s: nothing to load", table_name)
        return
    table = Table(table_name, MetaData(), schema="warehouse", autoload_with=engine)
    clean = df.astype(object).where(df.notna(), None)
    records = clean.to_dict("records")
    stmt = insert(table)
    update_cols = {c: stmt.excluded[c] for c in df.columns if c not in conflict_cols}
    stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update_cols)
    with engine.begin() as conn:
        conn.execute(stmt, records)
    logger.info("%s: %d rows upserted", table_name, len(df))


def load_staging(engine, raw_df: pd.DataFrame) -> None:
    """Charge les données brutes d'un snapshot (remplace le même snapshot s'il existe)."""
    df = raw_df.drop(columns=["sensors"], errors="ignore")
    if df.empty:
        logger.warning("staging: nothing to load")
        return
    snapshot = df["snapshot_time"].iloc[0]
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM staging.opensky_states WHERE snapshot_time = :s"),
            {"s": snapshot},
        )
        df.to_sql("opensky_states", conn, schema="staging",
                  if_exists="append", index=False, chunksize=1000)
    logger.info("staging.opensky_states: %d rows loaded (snapshot %s)", len(df), snapshot)


def load_warehouse(engine, tables: dict[str, pd.DataFrame]) -> None:
    """Ordre important : les dimensions d'abord, la table de faits à la fin."""
    _insert_ignore(engine, tables["dim_country"], "dim_country", ["country_name"])
    _insert_ignore(engine, tables["dim_time"], "dim_time", ["time_id"])
    _upsert(engine, tables["dim_airline"], "dim_airline", ["airline_icao"])
    _insert_ignore(engine, tables["dim_aircraft"], "dim_aircraft", ["icao24"])
    _insert_ignore(engine, tables["fact_flight_states"], "fact_flight_states",
                   ["icao24", "time_id"])