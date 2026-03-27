"""
Wynbrooke HOA — Rental Property Tracker Dashboard
"""

import os
import re

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Wynbrooke Rental Tracker",
    page_icon="🏘️",
    layout="wide",
)

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "wynbrooke_parcels.csv")


# ── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    df = pd.read_csv(DATA_PATH, dtype=str)
    df["likely_rental"] = df["likely_rental"].map({"True": True, "False": False})
    df["addr_match"] = df["addr_match"].map({"True": True, "False": False})
    df["status"] = df["likely_rental"].map({True: "Likely Rental", False: "Owner-Occupied"})

    # Extract section number from legal_desc
    def extract_section(desc):
        m = re.search(r'SEC\s*(\w+)', str(desc), re.IGNORECASE)
        return m.group(1) if m else "N/A"

    df["section"] = df["legal_desc"].apply(extract_section)

    # Build a combined mailing address column for display
    df["mailing_address"] = (
        df["owner_addr"] + ", " + df["owner_city"] + ", " +
        df["owner_state"] + " " + df["owner_zip"]
    )

    # Classify parcel type
    df["parcel_type"] = "Residential"
    df.loc[
        df["prop_addr"].str.contains("COMMON AREA", case=False, na=False),
        "parcel_type",
    ] = "Common Area"
    df.loc[
        df["legal_desc"].str.contains("APT|APARTMENT|UNITS", case=False, na=False),
        "parcel_type",
    ] = "Apartment Complex"

    # Refine status: common areas and apartments aren't "rentals"
    df.loc[df["parcel_type"] != "Residential", "status"] = df.loc[
        df["parcel_type"] != "Residential", "parcel_type"
    ]
    df.loc[df["parcel_type"] != "Residential", "likely_rental"] = False

    return df


df = load_data()

# ── Header ───────────────────────────────────────────────────────────────────

st.title("Wynbrooke Rental Property Tracker")
st.caption("Hendricks County, IN — Source: Indiana Gateway Real Property File (2024 pay 2025)")

residential = df[df["parcel_type"] == "Residential"]
total_res = len(residential)
rentals = residential["likely_rental"].sum()
owner_occ = total_res - rentals
rate = rentals / total_res * 100 if total_res else 0
common_areas = len(df[df["parcel_type"] == "Common Area"])
apartments = len(df[df["parcel_type"] == "Apartment Complex"])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Residential Parcels", total_res)
col2.metric("Owner-Occupied", int(owner_occ))
col3.metric("Likely Rentals", int(rentals))
col4.metric("Rental Rate", f"{rate:.1f}%")

st.caption(
    f"Excludes {common_areas} HOA common areas and {apartments} apartment complex parcel(s) "
    f"from rental calculation. Total parcels in dataset: {len(df)}."
)

# ── Sidebar filters ─────────────────────────────────────────────────────────

st.sidebar.header("Filters")

status_filter = st.sidebar.radio(
    "Occupancy Status",
    ["All", "Likely Rentals", "Owner-Occupied"],
)

owner_search = st.sidebar.text_input("Search Owner Name")

states = sorted(df["owner_state"].dropna().unique())
state_filter = st.sidebar.multiselect("Owner State", states, default=[])

sections = sorted(df["section"].unique(), key=lambda x: (x == "N/A", x))
section_filter = st.sidebar.multiselect("Wynbrooke Section", sections, default=[])

hide_non_residential = st.sidebar.checkbox("Hide common areas & apartments", value=True)

# Apply filters
filtered = df.copy()

if hide_non_residential:
    filtered = filtered[filtered["parcel_type"] == "Residential"]

if status_filter == "Likely Rentals":
    filtered = filtered[filtered["likely_rental"]]
elif status_filter == "Owner-Occupied":
    filtered = filtered[~filtered["likely_rental"]]

if owner_search:
    filtered = filtered[filtered["owner_name"].str.contains(owner_search, case=False, na=False)]

if state_filter:
    filtered = filtered[filtered["owner_state"].isin(state_filter)]

if section_filter:
    filtered = filtered[filtered["section"].isin(section_filter)]

# ── Main content ─────────────────────────────────────────────────────────────

tab_table, tab_analytics = st.tabs(["Property Table", "Analytics"])

# ── Table tab ────────────────────────────────────────────────────────────────

with tab_table:
    st.subheader(f"Properties ({len(filtered)} of {len(df)})")

    display_cols = [
        "status", "prop_addr", "prop_city", "owner_name",
        "mailing_address", "sale_date", "section", "legal_desc",
    ]
    display_names = {
        "status": "Status",
        "prop_addr": "Property Address",
        "prop_city": "City",
        "owner_name": "Owner",
        "mailing_address": "Owner Mailing Address",
        "sale_date": "Sale Date",
        "section": "Section",
        "legal_desc": "Legal Description",
    }

    st.dataframe(
        filtered[display_cols].rename(columns=display_names).sort_values(
            ["Status", "Property Address"]
        ),
        use_container_width=True,
        height=600,
        column_config={
            "Status": st.column_config.TextColumn(width="small"),
            "Section": st.column_config.TextColumn(width="small"),
            "Sale Date": st.column_config.TextColumn(width="small"),
        },
    )

# ── Analytics tab ────────────────────────────────────────────────────────────

with tab_analytics:
    st.subheader("Rental Analysis")

    a1, a2 = st.columns(2)

    # Rentals by section
    with a1:
        st.markdown("**Rentals by Wynbrooke Section**")
        section_counts = (
            filtered[filtered["likely_rental"]]
            .groupby("section")
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        if not section_counts.empty:
            st.bar_chart(section_counts.set_index("section")["count"])
        else:
            st.info("No rental properties in current filter.")

    # Top owner states (for rentals)
    with a2:
        st.markdown("**Rental Owner Locations (by State)**")
        rental_states = (
            filtered[filtered["likely_rental"]]
            .groupby("owner_state")
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        if not rental_states.empty:
            st.bar_chart(rental_states.set_index("owner_state")["count"])
        else:
            st.info("No rental properties in current filter.")

    st.markdown("---")

    # Repeat / institutional owners
    st.markdown("**Top Repeat Owners (likely investors)**")
    repeat_owners = (
        filtered[filtered["likely_rental"]]
        .groupby("owner_name")
        .agg(properties=("prop_addr", "count"), addresses=("prop_addr", list))
        .sort_values("properties", ascending=False)
        .head(15)
    )
    if not repeat_owners.empty:
        for owner, row in repeat_owners.iterrows():
            if row["properties"] > 1:
                with st.expander(f"{owner} — {row['properties']} properties"):
                    for addr in sorted(row["addresses"]):
                        st.write(f"- {addr}")
    else:
        st.info("No repeat rental owners in current filter.")
