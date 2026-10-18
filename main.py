import sys
import time

import pandas as pd

from src.extract import extract_airline_overrides, extract_airlines, extract_opensky
from src.load import create_tables, get_engine, load_staging, load_warehouse
from src.transform import (
    build_star_schema,
    clean_airlines,
    clean_states,
    convert_units,
    extract_airline_code,
    join_airlines,
)
from src.utils import get_logger

logger = get_logger("main")

# Bounding box : Maroc + sud de l'Europe
BBOX = {"lamin": 27.0, "lamax": 45.0, "lomin": -14.0, "lomax": 5.0}


def run_pipeline() -> None:
    start = time.time()
    logger.info("===== Pipeline started =====")

    # 1. EXTRACT
    raw_states = extract_opensky(BBOX)
    if raw_states.empty:
        logger.warning("No aircraft extracted, pipeline stopped")
        return
    airlines = extract_airlines()
    overrides = extract_airline_overrides()

    # 2. TRANSFORM
    states = clean_states(raw_states)
    states = convert_units(states)
    states = extract_airline_code(states)
    joined = join_airlines(states, clean_airlines(airlines, overrides))
    tables = build_star_schema(joined)

    # Toujours inclure les overrides dans dim_airline (même si absents du snapshot)
    overrides_dim = overrides.rename(columns={"icao": "airline_icao"})[
        ["airline_icao", "airline_name", "iata", "airline_country"]
    ]
    tables["dim_airline"] = (
        pd.concat([tables["dim_airline"], overrides_dim])
        .drop_duplicates(subset="airline_icao", keep="last")
        .reset_index(drop=True)
    )

    # 3. LOAD
    engine = get_engine()
    create_tables(engine)
    load_staging(engine, raw_states)
    load_warehouse(engine, tables)

    # RÉSUMÉ
    logger.info(
        "Summary: extracted=%d | rejected=%d | loaded_in_fact=%d | duration=%.1fs",
        len(raw_states),
        len(raw_states) - len(states),
        len(tables["fact_flight_states"]),
        time.time() - start,
    )
    logger.info("===== Pipeline finished =====")


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)