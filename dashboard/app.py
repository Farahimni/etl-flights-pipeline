import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

# Permet d'importer src/ quand on lance : streamlit run dashboard/app.py
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.load import get_engine  # noqa: E402

st.set_page_config(page_title="Flights ETL Dashboard", layout="wide")
st.title("✈️ Trafic aérien : Maroc et sud de l'Europe")
st.caption("Source : OpenSky Network, pipeline ETL → PostgreSQL (modèle en étoile)")


@st.cache_resource
def engine():
    return get_engine()


@st.cache_data(ttl=300)
def query(sql: str) -> pd.DataFrame:
    with engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


# ---------- dernier snapshot ----------
latest = query(
    "SELECT time_id, snapshot_time FROM warehouse.dim_time "
    "ORDER BY snapshot_time DESC LIMIT 1"
)
if latest.empty:
    st.warning("Aucune donnée : lance d'abord `python main.py`.")
    st.stop()

latest_id = int(latest.loc[0, "time_id"])
latest_time = latest.loc[0, "snapshot_time"]

# ---------- KPIs ----------
kpis = query("""
    SELECT
        (SELECT COUNT(*) FROM warehouse.dim_time)            AS snapshots,
        (SELECT COUNT(*) FROM warehouse.dim_aircraft)        AS aircraft,
        (SELECT COUNT(*) FROM warehouse.fact_flight_states)  AS observations
""").iloc[0]

positions = query(f"""
    SELECT callsign, latitude, longitude, altitude_ft, speed_kmh, on_ground
    FROM warehouse.fact_flight_states
    WHERE time_id = {latest_id}
""")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Avions (dernier snapshot)", len(positions))
c2.metric("Snapshots collectés", int(kpis["snapshots"]))
c3.metric("Avions distincts", int(kpis["aircraft"]))
c4.metric("Observations", int(kpis["observations"]))
st.caption(f"Dernier snapshot : {latest_time}")

# ---------- carte ----------
st.subheader("Positions des avions (dernier snapshot)")
st.map(positions, latitude="latitude", longitude="longitude")

# ---------- graphiques ----------
left, right = st.columns(2)

with left:
    st.subheader("Trafic par snapshot")
    traffic = query("""
        SELECT t.snapshot_time, COUNT(*) AS nb_avions
        FROM warehouse.fact_flight_states f
        JOIN warehouse.dim_time t ON t.time_id = f.time_id
        GROUP BY t.snapshot_time
        ORDER BY t.snapshot_time
    """)
    st.line_chart(traffic.set_index("snapshot_time"))

with right:
    st.subheader("Top 10 compagnies (dernier snapshot)")
    top = query(f"""
        SELECT a.airline_name, COUNT(*) AS nb_avions
        FROM warehouse.fact_flight_states f
        JOIN warehouse.dim_airline a ON a.airline_icao = f.airline_icao
        WHERE f.time_id = {latest_id}
        GROUP BY a.airline_name
        ORDER BY nb_avions DESC
        LIMIT 10
    """)
    st.bar_chart(top.set_index("airline_name"))

with st.expander("Données du dernier snapshot"):
    st.dataframe(positions)