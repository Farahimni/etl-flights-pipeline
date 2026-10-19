import pandas as pd
import pytest

from src.transform import (
    build_star_schema,
    clean_airlines,
    clean_states,
    convert_units,
    extract_airline_code,
    join_airlines,
)


# ---------- helpers : petits jeux de données fabriqués à la main ----------

def make_row(**overrides) -> dict:
    row = {
        "icao24": "abc123",
        "callsign": "TVF73DJ ",
        "origin_country": "France",
        "time_position": 1_700_000_000,
        "last_contact": 1_700_000_005,
        "longitude": -5.0,
        "latitude": 33.0,
        "baro_altitude": 1000.0,
        "on_ground": False,
        "velocity": 100.0,
        "true_track": 90.0,
        "vertical_rate": 0.0,
        "sensors": None,
        "geo_altitude": 1010.0,
        "squawk": "1234",
        "spi": False,
        "position_source": 0,
    }
    row.update(overrides)
    return row


def make_states(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def make_airlines(rows: list) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["airline_id", "name", "alias", "iata", "icao",
                 "callsign", "country", "active"],
    )


# ---------- clean_states ----------

def test_clean_states_strips_callsign_and_nulls_empty():
    df = make_states(
        make_row(icao24="a1", callsign="TVF73DJ "),
        make_row(icao24="a2", callsign="        "),
    )
    out = clean_states(df)
    assert out.loc[0, "callsign"] == "TVF73DJ"
    assert pd.isna(out.loc[1, "callsign"])


def test_clean_states_drops_rows_without_position():
    df = make_states(
        make_row(icao24="a1"),
        make_row(icao24="a2", latitude=None),
    )
    out = clean_states(df)
    assert out["icao24"].tolist() == ["a1"]


def test_clean_states_removes_duplicates():
    df = make_states(make_row(), make_row())
    assert len(clean_states(df)) == 1


def test_clean_states_renames_and_drops_columns():
    out = clean_states(make_states(make_row()))
    assert "sensors" not in out.columns
    assert "origin_country" not in out.columns
    assert out.loc[0, "registration_country"] == "France"


# ---------- convert_units ----------

def test_convert_units():
    df = clean_states(make_states(make_row(velocity=100.0, baro_altitude=1000.0)))
    out = convert_units(df)
    assert out.loc[0, "speed_kmh"] == pytest.approx(360.0)
    assert out.loc[0, "altitude_ft"] == pytest.approx(3280.84, rel=1e-4)
    assert "velocity" not in out.columns
    assert "baro_altitude" not in out.columns
    assert out["time_position"].dt.tz is not None


# ---------- extract_airline_code ----------

def test_extract_airline_code():
    df = pd.DataFrame({"callsign": ["TVF73DJ", "ANE007", "FCVRB", None]})
    out = extract_airline_code(df)
    assert out.loc[0, "airline_icao"] == "TVF"
    assert out.loc[1, "airline_icao"] == "ANE"
    assert pd.isna(out.loc[2, "airline_icao"])   # avion privé : pas de chiffre après 3 lettres
    assert pd.isna(out.loc[3, "airline_icao"])   # pas de callsign


# ---------- clean_airlines / join_airlines ----------

def test_clean_airlines_keeps_active_duplicate_and_drops_missing_icao():
    airlines = make_airlines([
        [1, "Old Air", None, "OA", "AAA", "OLD", "France", "N"],
        [2, "New Air", None, "NA", "AAA", "NEW", "France", "y"],
        [3, "No Code Air", None, None, None, None, "Spain", "Y"],
    ])
    out = clean_airlines(airlines)
    assert out["icao"].tolist() == ["AAA"]
    assert out.loc[0, "airline_name"] == "New Air"


def test_clean_airlines_overrides_win():
    airlines = make_airlines([[1, "Old Air", None, "OA", "AAA", "OLD", "France", "Y"]])
    overrides = pd.DataFrame([{
        "icao": "aaa", "airline_name": "Override Air",
        "iata": None, "airline_country": "Spain",
    }])
    out = clean_airlines(airlines, overrides)
    assert len(out) == 1
    assert out.loc[0, "airline_name"] == "Override Air"


def test_join_airlines_keeps_all_rows():
    states = pd.DataFrame({"airline_icao": ["TVF", "ZZZ", None]})
    airlines_clean = pd.DataFrame([{
        "icao": "TVF", "airline_name": "Transavia France",
        "iata": "TO", "airline_country": "France", "active": "Y",
    }])
    out = join_airlines(states, airlines_clean)
    assert len(out) == 3
    assert out.loc[0, "airline_name"] == "Transavia France"
    assert pd.isna(out.loc[1, "airline_name"])
    assert "icao" not in out.columns


# ---------- build_star_schema ----------

@pytest.fixture
def joined() -> pd.DataFrame:
    states = make_states(
        make_row(icao24="a1", callsign="TVF73DJ ", origin_country="France"),
        make_row(icao24="a2", callsign="XYZ123  ", origin_country="Spain"),
        make_row(icao24="a3", callsign="FCVRB   ", origin_country="France"),
    )
    airlines_clean = pd.DataFrame([{
        "icao": "TVF", "airline_name": "Transavia France",
        "iata": "TO", "airline_country": "France", "active": "Y",
    }])
    df = extract_airline_code(convert_units(clean_states(states)))
    df = join_airlines(df, airlines_clean)
    df["snapshot_time"] = pd.Timestamp("2026-10-18 23:40:52", tz="UTC")
    return df


def test_build_star_schema(joined):
    tables = build_star_schema(joined)

    assert set(tables) == {
        "dim_time", "dim_country", "dim_aircraft", "dim_airline", "fact_flight_states",
    }
    assert len(tables["fact_flight_states"]) == 3
    assert len(tables["dim_time"]) == 1
    assert tables["dim_country"]["country_name"].tolist() == ["France", "Spain"]
    assert tables["dim_aircraft"]["icao24"].is_unique

    airlines = tables["dim_airline"].set_index("airline_icao")
    assert airlines.loc["TVF", "airline_name"] == "Transavia France"
    assert airlines.loc["XYZ", "airline_name"] == "Unknown"   # code absent de airlines.dat
    assert "FCV" not in airlines.index                        # avion privé, pas de compagnie