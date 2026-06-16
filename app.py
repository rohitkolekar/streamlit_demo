"""
Mutual Fund Portfolio Tracker
Run with: streamlit run app.py

View, add, edit, and delete snapshots in dbo.MUTUAL_FUND_PORTFOLIO on Azure SQL.
"""

import os
from datetime import date, datetime
from typing import Optional, Tuple

import streamlit as st
import pyodbc
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = "dbo.MUTUAL_FUND_PORTFOLIO"

st.set_page_config(page_title="Mutual Fund Portfolio Tracker", page_icon="📈", layout="wide")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def get_driver() -> Optional[str]:
    """Pick the newest installed Microsoft ODBC driver for SQL Server."""
    candidates = [d for d in pyodbc.drivers() if "ODBC Driver" in d and "SQL Server" in d]
    candidates.sort(reverse=True)
    return candidates[0] if candidates else None


def build_connection_string() -> str:
    driver = get_driver()
    if driver is None:
        raise RuntimeError(
            "No Microsoft ODBC Driver for SQL Server found. Install 'ODBC Driver 18 for SQL Server'."
        )
    
    server =  st.secrets["azure_sql"]["AZURE_SQL_SERVER"]
    database = st.secrets["azure_sql"]["AZURE_SQL_DATABASE"]
    username = st.secrets["azure_sql"]["AZURE_SQL_USERNAME"]
    password = st.secrets["azure_sql"]["AZURE_SQL_PASSWORD"]

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

    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


def get_connection():
    return pyodbc.connect(build_connection_string())


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
NUMERIC_COLS = ["Invested_L", "Current_L", "Absolute_PL_L", "Absolute_PL_Percent", "NIFTY50"]


@st.cache_data(ttl=300, show_spinner="Fetching portfolio data...")
def load_data() -> pd.DataFrame:
    conn = get_connection()
    try:
        df = pd.read_sql(f"SELECT * FROM {TABLE_NAME} ORDER BY As_On ASC", conn)
    finally:
        conn.close()
    df["As_On"] = pd.to_datetime(df["As_On"])
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def compute_pl(invested_l: float, current_l: float) -> Tuple[float, float]:
    pl_l = round(current_l - invested_l, 2)
    pl_pct = round((pl_l / invested_l) * 100, 2) if invested_l else 0.0
    return pl_l, pl_pct


def insert_row(invested_l: float, current_l: float, as_on: date, nifty50: int) -> None:
    pl_l, pl_pct = compute_pl(invested_l, current_l)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO {TABLE_NAME} "
            "(Invested_L, Current_L, Absolute_PL_L, Absolute_PL_Percent, As_On, NIFTY50) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (invested_l, current_l, pl_l, pl_pct, as_on, nifty50),
        )
        conn.commit()
    finally:
        conn.close()


def update_row(row_id: int, invested_l: float, current_l: float, as_on: date, nifty50: int) -> None:
    pl_l, pl_pct = compute_pl(invested_l, current_l)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE {TABLE_NAME} SET Invested_L=?, Current_L=?, Absolute_PL_L=?, "
            "Absolute_PL_Percent=?, As_On=?, NIFTY50=? WHERE ID=?",
            (invested_l, current_l, pl_l, pl_pct, as_on, nifty50, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_row(row_id: int) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE ID=?", (row_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📈 Mutual Fund Portfolio Tracker")

try:
    df = load_data()
except Exception as e:
    st.error("Couldn't connect to Azure SQL.")
    with st.expander("Error details"):
        st.code(str(e))
    st.caption(
        "Check your .env values, the server firewall rule for your current IP, "
        "and — if on a corporate network — whether SSL inspection is breaking the TLS handshake."
    )
    st.stop()

tab_view, tab_add, tab_edit = st.tabs(["📊 Dashboard", "➕ Add Entry", "✏️ Edit / Delete"])

# --- Dashboard tab -----------------------------------------------------------
with tab_view:
    if df.empty:
        st.info("No entries yet — add your first one in the 'Add Entry' tab.")
    else:
        view = df.sort_values("As_On").reset_index(drop=True)
        baseline = view["NIFTY50"].iloc[0]
        view["NIFTY50_Return_Percent"] = (view["NIFTY50"] / baseline - 1) * 100
        latest = view.iloc[-1]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invested", f"₹{latest['Invested_L']:.2f} L")
        c2.metric("Current Value", f"₹{latest['Current_L']:.2f} L")
        c3.metric(
            "Absolute P&L",
            f"₹{latest['Absolute_PL_L']:.2f} L",
            f"{latest['Absolute_PL_Percent']:.2f}%",
        )
        c4.metric("NIFTY50", f"{latest['NIFTY50']:,.0f}", f"{latest['NIFTY50_Return_Percent']:.2f}%")

        st.divider()

        st.subheader("Invested vs Current Value")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=view["As_On"], y=view["Invested_L"], name="Invested (₹L)", mode="lines+markers"))
        fig1.add_trace(go.Scatter(x=view["As_On"], y=view["Current_L"], name="Current (₹L)", mode="lines+markers"))
        fig1.update_layout(
            xaxis_title="Date",
            yaxis_title="₹ Lakhs",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=10),
        )
        st.plotly_chart(fig1, use_container_width=True)

        st.subheader("Portfolio Return vs NIFTY50")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=view["As_On"], y=view["Absolute_PL_Percent"], name="Portfolio Return %", mode="lines+markers"))
        fig2.add_trace(go.Scatter(x=view["As_On"], y=view["NIFTY50_Return_Percent"], name="NIFTY50 Return %", mode="lines+markers"))
        fig2.update_layout(
            xaxis_title="Date",
            yaxis_title="Return %",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.divider()
        st.subheader("All Entries")
        display_df = view.drop(columns=["ID"]).sort_values("As_On", ascending=False)
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "As_On": st.column_config.DateColumn("As On", format="DD MMM YYYY"),
                "Invested_L": st.column_config.NumberColumn("Invested (₹L)", format="%.2f"),
                "Current_L": st.column_config.NumberColumn("Current (₹L)", format="%.2f"),
                "Absolute_PL_L": st.column_config.NumberColumn("P&L (₹L)", format="%.2f"),
                "Absolute_PL_Percent": st.column_config.NumberColumn("P&L %", format="%.2f"),
                "NIFTY50": st.column_config.NumberColumn("NIFTY50", format="%d"),
                "NIFTY50_Return_Percent": st.column_config.NumberColumn("NIFTY50 Return %", format="%.2f"),
            },
        )
        st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y, %I:%M %p')}")

    if st.button("🔄 Refresh data"):
        load_data.clear()
        st.rerun()

# --- Add Entry tab -------------------------------------------------------------
with tab_add:
    st.subheader("Add a new snapshot")

    col1, col2 = st.columns(2)
    add_invested = col1.number_input("Invested (₹ Lakhs)", min_value=0.0, step=0.01, format="%.2f", key="add_invested")
    add_current = col2.number_input("Current Value (₹ Lakhs)", min_value=0.0, step=0.01, format="%.2f", key="add_current")
    col3, col4 = st.columns(2)
    add_as_on = col3.date_input("As On", value=date.today(), key="add_as_on")
    add_nifty = col4.number_input("NIFTY50", min_value=0, step=1, key="add_nifty")

    pl_l, pl_pct = compute_pl(add_invested, add_current)
    st.caption(f"Will save: P&L ₹{pl_l:.2f} L ({pl_pct:.2f}%)")

    if st.button("Add entry", type="primary"):
        if add_invested <= 0:
            st.error("Invested amount must be greater than 0.")
        else:
            try:
                insert_row(add_invested, add_current, add_as_on, int(add_nifty))
                load_data.clear()
                st.success("Entry added.")
                st.rerun()
            except Exception as e:
                st.error("Failed to add entry.")
                with st.expander("Error details"):
                    st.code(str(e))

# --- Edit / Delete tab -----------------------------------------------------------
with tab_edit:
    st.subheader("Edit or delete an existing entry")

    if df.empty:
        st.info("No entries to edit yet.")
    else:
        options = df.sort_values("As_On", ascending=False)
        labels = {
            int(row.ID): f"ID {row.ID} — {row.As_On.strftime('%d %b %Y')} — ₹{row.Current_L:.2f} L"
            for row in options.itertuples()
        }
        selected_id = st.selectbox("Select entry", options=list(labels.keys()), format_func=lambda i: labels[i])
        row = df[df["ID"] == selected_id].iloc[0]

        col1, col2 = st.columns(2)
        edit_invested = col1.number_input(
            "Invested (₹ Lakhs)", min_value=0.0, step=0.01, format="%.2f",
            value=float(row["Invested_L"]), key=f"edit_invested_{selected_id}",
        )
        edit_current = col2.number_input(
            "Current Value (₹ Lakhs)", min_value=0.0, step=0.01, format="%.2f",
            value=float(row["Current_L"]), key=f"edit_current_{selected_id}",
        )
        col3, col4 = st.columns(2)
        edit_as_on = col3.date_input("As On", value=row["As_On"].date(), key=f"edit_as_on_{selected_id}")
        edit_nifty = col4.number_input(
            "NIFTY50", min_value=0, step=1, value=int(row["NIFTY50"]), key=f"edit_nifty_{selected_id}",
        )

        pl_l, pl_pct = compute_pl(edit_invested, edit_current)
        st.caption(f"Will save: P&L ₹{pl_l:.2f} L ({pl_pct:.2f}%)")

        if st.button("Save changes", type="primary"):
            try:
                update_row(int(selected_id), edit_invested, edit_current, edit_as_on, int(edit_nifty))
                load_data.clear()
                st.success("Entry updated.")
                st.rerun()
            except Exception as e:
                st.error("Failed to update entry.")
                with st.expander("Error details"):
                    st.code(str(e))

        st.divider()
        confirm = st.checkbox(f"I'm sure I want to delete ID {selected_id}", key=f"confirm_delete_{selected_id}")
        if st.button("🗑️ Delete this entry", disabled=not confirm):
            try:
                delete_row(int(selected_id))
                load_data.clear()
                st.success("Entry deleted.")
                st.rerun()
            except Exception as e:
                st.error("Failed to delete entry.")
                with st.expander("Error details"):
                    st.code(str(e))