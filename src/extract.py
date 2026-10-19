import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from src.utils import get_logger

load_dotenv()
logger = get_logger("extract")

# ---------- CSV : airports, airlines, overrides ----------

AIRLINE_COLUMNS = [
    "airline_id", "name", "alias", "iata", "icao",
    "callsign", "country", "active",
]


def extract_airports(path: str = "data/raw/airports.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    logger.info("Airports extracted: %d rows, %d columns", len(df), df.shape[1])
    return df


def extract_airlines(path: str = "data/raw/airlines.dat") -> pd.DataFrame:
    # Pas de header, et les valeurs nulles sont écrites "\N"
    df = pd.read_csv(path, header=None, names=AIRLINE_COLUMNS, na_values="\\N")
    logger.info("Airlines extracted: %d rows", len(df))
    return df


def extract_airline_overrides(path: str = "data/reference/airline_overrides.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    logger.info("Airline overrides extracted: %d rows", len(df))
    return df


# ---------- API : OpenSky ----------

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"

STATE_COLUMNS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact",
    "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
    "true_track", "vertical_rate", "sensors", "geo_altitude", "squawk",
    "spi", "position_source",
]


def _request_with_retry(method: str, url: str, retries: int = 4, wait: int = 20, **kwargs) -> requests.Response:
    """Réessaie en cas de problème réseau (ex. PC qui sort de veille) ou d'erreur serveur 5xx."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.request(method, url, timeout=30, **kwargs)
            if r.status_code < 500:
                return r
            logger.warning("Server error %s (attempt %d/%d)", r.status_code, attempt, retries)
        except (requests.ConnectionError, requests.Timeout) as e:
            logger.warning("Network error (attempt %d/%d): %s", attempt, retries, e)
        if attempt < retries:
            time.sleep(wait * attempt)
    raise RuntimeError(f"{method} {url} failed after {retries} attempts")


def get_token():
    """Retourne un token OAuth2, ou None (mode anonyme) si pas de clés."""
    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.info("No OpenSky credentials found, using anonymous access")
        return None
    r = _request_with_retry(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    r.raise_for_status()
    return r.json()["access_token"]


def extract_opensky(bbox: dict | None = None, save_raw: bool = True) -> pd.DataFrame:
    headers = {}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    r = _request_with_retry("GET", STATES_URL, params=bbox or {}, headers=headers)
    if r.status_code == 429:
        logger.warning("OpenSky rate limit reached (429)")
        return pd.DataFrame(columns=STATE_COLUMNS)
    r.raise_for_status()
    logger.info("OpenSky credits remaining: %s", r.headers.get("X-Rate-Limit-Remaining"))

    data = r.json()
    states = data.get("states") or []

    if save_raw:
        os.makedirs("data/raw/opensky", exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        path = f"data/raw/opensky/states_{stamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        logger.info("Raw OpenSky response saved to %s", path)

    df = pd.DataFrame(states, columns=STATE_COLUMNS)
    df["snapshot_time"] = pd.to_datetime(data["time"], unit="s", utc=True)
    logger.info("OpenSky extracted: %d aircraft", len(df))
    return df