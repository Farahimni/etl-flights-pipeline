import pandas as pd
from src.utils import get_logger

logger = get_logger("transform")


def clean_states(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    n_start = len(df)

    df = df.drop(columns=["sensors"])
    df["callsign"] = df["callsign"].str.strip()
    df["callsign"] = df["callsign"].mask(df["callsign"] == "")
    df = df.dropna(subset=["icao24", "latitude", "longitude"])
    df = df.drop_duplicates(subset=["icao24", "time_position"])
    df = df.rename(columns={"origin_country": "registration_country"})

    logger.info("clean_states: %d -> %d rows", n_start, len(df))
    return df.reset_index(drop=True)


def convert_units(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["speed_kmh"] = df["velocity"] * 3.6
    df["altitude_ft"] = df["baro_altitude"] * 3.28084
    df["time_position"] = pd.to_datetime(df["time_position"], unit="s", utc=True)
    df["last_contact"] = pd.to_datetime(df["last_contact"], unit="s", utc=True)
    return df.drop(columns=["velocity", "baro_altitude"])


def extract_airline_code(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 3 lettres suivies d'un chiffre : TVF73DJ -> TVF
    df["airline_icao"] = df["callsign"].str.extract(r"^([A-Z]{3})\d", expand=False)
    return df


def clean_airlines(airlines: pd.DataFrame, overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    df = airlines.copy()
    df["active"] = df["active"].str.upper()
    df = df.dropna(subset=["icao"])
    df["icao"] = df["icao"].str.upper().str.strip()
    df = df.sort_values("active", ascending=False)   # "Y" avant "N"
    df = df.drop_duplicates(subset="icao", keep="first")
    df = df.rename(columns={"name": "airline_name", "country": "airline_country"})
    result = df[["icao", "airline_name", "iata", "airline_country", "active"]]

    if overrides is not None and not overrides.empty:
        ov = overrides.copy()
        ov["icao"] = ov["icao"].str.upper().str.strip()
        ov["active"] = "Y"
        ov = ov[["icao", "airline_name", "iata", "airline_country", "active"]]
        # les overrides en premier : ils gagnent sur airlines.dat
        result = pd.concat([ov, result]).drop_duplicates(subset="icao", keep="first")

    logger.info("clean_airlines: %d -> %d rows", len(airlines), len(result))
    return result.reset_index(drop=True)


def join_airlines(states: pd.DataFrame, airlines_clean: pd.DataFrame) -> pd.DataFrame:
    n_before = len(states)
    out = states.merge(
        airlines_clean,
        how="left",
        left_on="airline_icao",
        right_on="icao",
    ).drop(columns=["icao"])
    assert len(out) == n_before, "La jointure a dupliqué des lignes"
    return out
def build_star_schema(joined: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df = joined.copy()

    # --- dim_time (une ligne par snapshot) ---
    df["time_id"] = df["snapshot_time"].dt.strftime("%Y%m%d%H%M%S").astype("int64")
    dim_time = df[["time_id", "snapshot_time"]].drop_duplicates("time_id").copy()
    dim_time["date"] = dim_time["snapshot_time"].dt.date
    dim_time["year"] = dim_time["snapshot_time"].dt.year
    dim_time["month"] = dim_time["snapshot_time"].dt.month
    dim_time["day"] = dim_time["snapshot_time"].dt.day
    dim_time["hour"] = dim_time["snapshot_time"].dt.hour
    dim_time["day_of_week"] = dim_time["snapshot_time"].dt.day_name()
    dim_time = dim_time.reset_index(drop=True)

    # --- dim_country ---
    dim_country = (
        df[["registration_country"]]
        .dropna()
        .drop_duplicates()
        .rename(columns={"registration_country": "country_name"})
        .sort_values("country_name")
        .reset_index(drop=True)
    )

    # --- dim_aircraft ---
    dim_aircraft = (
        df[["icao24", "registration_country"]]
        .drop_duplicates("icao24")
        .reset_index(drop=True)
    )

    # --- dim_airline ---
    dim_airline = (
        df.loc[df["airline_icao"].notna(),
               ["airline_icao", "airline_name", "iata", "airline_country"]]
        .drop_duplicates("airline_icao")
        .reset_index(drop=True)
    )
    dim_airline["airline_name"] = dim_airline["airline_name"].fillna("Unknown")

    # --- fact_flight_states ---
    fact = df[[
        "icao24", "airline_icao", "time_id", "callsign",
        "time_position", "last_contact", "longitude", "latitude",
        "altitude_ft", "geo_altitude", "speed_kmh", "true_track",
        "vertical_rate", "on_ground", "squawk", "position_source",
    ]].reset_index(drop=True)

    # --- contrôles de qualité ---
    assert dim_aircraft["icao24"].is_unique, "icao24 dupliqué dans dim_aircraft"
    assert dim_airline["airline_icao"].is_unique, "airline_icao dupliqué"
    assert dim_time["time_id"].is_unique, "time_id dupliqué"
    assert fact[["icao24", "time_id"]].notna().all().all(), "clé nulle dans fact"

    tables = {
        "dim_time": dim_time,
        "dim_country": dim_country,
        "dim_aircraft": dim_aircraft,
        "dim_airline": dim_airline,
        "fact_flight_states": fact,
    }
    for name, t in tables.items():
        logger.info("%s: %d rows", name, len(t))
    return tables