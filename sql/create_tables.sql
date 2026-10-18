CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;

-- ---------- STAGING : données brutes ----------
CREATE TABLE IF NOT EXISTS staging.opensky_states (
    icao24           TEXT,
    callsign         TEXT,
    origin_country   TEXT,
    time_position    BIGINT,
    last_contact     BIGINT,
    longitude        DOUBLE PRECISION,
    latitude         DOUBLE PRECISION,
    baro_altitude    DOUBLE PRECISION,
    on_ground        BOOLEAN,
    velocity         DOUBLE PRECISION,
    true_track       DOUBLE PRECISION,
    vertical_rate    DOUBLE PRECISION,
    geo_altitude     DOUBLE PRECISION,
    squawk           TEXT,
    spi              BOOLEAN,
    position_source  INTEGER,
    snapshot_time    TIMESTAMPTZ
);

-- ---------- WAREHOUSE : modèle en étoile ----------
CREATE TABLE IF NOT EXISTS warehouse.dim_time (
    time_id        BIGINT PRIMARY KEY,
    snapshot_time  TIMESTAMPTZ NOT NULL,
    date           DATE,
    year           INTEGER,
    month          INTEGER,
    day            INTEGER,
    hour           INTEGER,
    day_of_week    TEXT
);

CREATE TABLE IF NOT EXISTS warehouse.dim_country (
    country_name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS warehouse.dim_aircraft (
    icao24                TEXT PRIMARY KEY,
    registration_country  TEXT REFERENCES warehouse.dim_country (country_name)
);

CREATE TABLE IF NOT EXISTS warehouse.dim_airline (
    airline_icao     TEXT PRIMARY KEY,
    airline_name     TEXT NOT NULL,
    iata             TEXT,
    airline_country  TEXT
);

CREATE TABLE IF NOT EXISTS warehouse.fact_flight_states (
    fact_id          BIGSERIAL PRIMARY KEY,
    icao24           TEXT   NOT NULL REFERENCES warehouse.dim_aircraft (icao24),
    airline_icao     TEXT   REFERENCES warehouse.dim_airline (airline_icao),
    time_id          BIGINT NOT NULL REFERENCES warehouse.dim_time (time_id),
    callsign         TEXT,
    time_position    TIMESTAMPTZ,
    last_contact     TIMESTAMPTZ,
    longitude        DOUBLE PRECISION,
    latitude         DOUBLE PRECISION,
    altitude_ft      DOUBLE PRECISION,
    geo_altitude     DOUBLE PRECISION,
    speed_kmh        DOUBLE PRECISION,
    true_track       DOUBLE PRECISION,
    vertical_rate    DOUBLE PRECISION,
    on_ground        BOOLEAN,
    squawk           TEXT,
    position_source  INTEGER,
    UNIQUE (icao24, time_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_time    ON warehouse.fact_flight_states (time_id);
CREATE INDEX IF NOT EXISTS idx_fact_airline ON warehouse.fact_flight_states (airline_icao);