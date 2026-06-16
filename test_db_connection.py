"""
Azure SQL — Connection Test
Run with: streamlit run app.py

Purpose: confirm SQL-login credentials, network access, and the ODBC
driver all work before building out the full portfolio dashboard.
"""

import os
from typing import Optional, Tuple

import streamlit as st
import pyodbc
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Azure SQL Connection Test", page_icon="🔌")
st.title("🔌 Azure SQL Connection Test")
st.caption(
    "Checks that SQL-login credentials, network access, and the ODBC "
    "driver are all working — before we build the full dashboard."
)


def get_driver() -> Optional[str]:
    """Pick the newest installed Microsoft ODBC driver for SQL Server."""
    candidates = [d for d in pyodbc.drivers() if "ODBC Driver" in d and "SQL Server" in d]
    candidates.sort(reverse=True)  # "...18..." sorts before "...17..."
    return candidates[0] if candidates else None


def build_connection_string() -> Tuple[str, str]:
    driver = get_driver()
    if driver is None:
        raise RuntimeError(
            "No Microsoft ODBC Driver for SQL Server found on this machine. "
            "Install 'ODBC Driver 18 for SQL Server' and try again."
        )

    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    username = os.getenv("AZURE_SQL_USERNAME")
    password = os.getenv("AZURE_SQL_PASSWORD")

    missing = [
        name
        for name, val in [
            ("AZURE_SQL_SERVER", server),
            ("AZURE_SQL_DATABASE", database),
            ("AZURE_SQL_USERNAME", username),
            ("AZURE_SQL_PASSWORD", password),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required .env variable(s): {', '.join(missing)}. "
            "Check that .env exists next to app.py and is filled in."
        )

    conn_str = (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return conn_str, driver


if st.button("Test connection", type="primary"):
    try:
        conn_str, driver = build_connection_string()
        st.caption(f"Using driver: {driver}")

        with st.spinner("Connecting..."):
            conn = pyodbc.connect(conn_str)
            conn.cursor().execute("SELECT 1")

        st.success("✅ Connected — SQL login authentication works.")

        with st.spinner("Listing visible tables..."):
            tables = pd.read_sql(
                "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME",
                conn,
            )
        st.write("Tables this login can see:")
        st.dataframe(tables, use_container_width=True, hide_index=True)
        conn.close()

    except pyodbc.Error as e:
        st.error("❌ Connection failed.")
        with st.expander("Error details"):
            st.code(str(e))
        st.caption(
            "Common causes: the Azure SQL server firewall isn't allowing your "
            "current IP, wrong username/password, or — if you're on a corporate "
            "network — SSL inspection breaking the TLS handshake. Try from an "
            "unrestricted network (e.g. mobile hotspot) to rule that last one out."
        )
    except Exception as e:
        st.error("❌ Couldn't even attempt the connection.")
        with st.expander("Error details"):
            st.code(str(e))