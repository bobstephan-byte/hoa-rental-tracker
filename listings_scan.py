"""
Wynbrooke HOA — Market Monitor: Active Listing Scanner

Query the RentCast API for active for-sale and for-rent listings in
zip code 46234, cross-reference against Wynbrooke parcels, and annotate
each match with its current rental/owner-occupied status.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

from parse_property_data import normalize_addr

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(_BASE_DIR, "data", "wynbrooke_parcels.csv")
OVERRIDES_PATH = os.path.join(_BASE_DIR, "data", "overrides.json")
OUTPUT_PATH = os.path.join(_BASE_DIR, "data", "market_monitor_listings.json")

RENTCAST_BASE = "https://api.rentcast.io/v1"
ZIP_CODE = "46234"
PROPERTY_TYPE = "Single Family"


def get_api_key():
    key = os.environ.get("RENTCAST_API_KEY")
    if not key:
        print("ERROR: RENTCAST_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_listings(endpoint, api_key):
    """Fetch listings from a RentCast endpoint. Returns a list of listings."""
    url = f"{RENTCAST_BASE}/{endpoint}"
    headers = {"X-Api-Key": api_key}
    params = {
        "zipCode": ZIP_CODE,
        "propertyType": PROPERTY_TYPE,
        "status": "Active",
        "limit": 500,
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 429:
            print(f"ERROR: RentCast API rate limit exceeded for {endpoint}.", file=sys.stderr)
        else:
            print(f"ERROR: RentCast API returned {resp.status_code} for {endpoint}: {resp.text}", file=sys.stderr)
        return []
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Network error fetching {endpoint}: {e}", file=sys.stderr)
        return []

    data = resp.json()
    # RentCast may return a list directly or a dict with a key
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Try common wrapper keys
        for key in ("listings", "data", "results"):
            if key in data:
                return data[key]
        return []
    return []


def extract_street_address(formatted_address):
    """Extract just the street address from a full formatted address.

    RentCast formattedAddress looks like: "1234 Main St, Indianapolis, IN 46234"
    We want just "1234 Main St".
    """
    if not formatted_address:
        return ""
    # Split on comma and take the first part (street address)
    return formatted_address.split(",")[0].strip()


def load_parcel_data():
    """Load Wynbrooke parcels and build a normalized address lookup."""
    df = pd.read_csv(DATA_PATH, dtype=str)
    df["likely_rental"] = df["likely_rental"].map({"True": True, "False": False})
    df["addr_match"] = df["addr_match"].map({"True": True, "False": False})
    return df


def load_overrides():
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH, "r") as f:
            return json.load(f)
    return {}


def get_current_status(parcel_row, overrides):
    """Determine current status for a parcel: check overrides first, then parcel data."""
    parcel_id = parcel_row["parcel_number"].strip()
    override = overrides.get(parcel_id, {})

    if override.get("status") == "Confirmed Rental":
        return "Rental"
    if override.get("status") == "False Positive":
        return "Owner-Occupied"

    # Fall back to parcel data
    if parcel_row.get("likely_rental") is True or str(parcel_row.get("likely_rental")).lower() == "true":
        return "Rental"
    if parcel_row.get("addr_match") is True or str(parcel_row.get("addr_match")).lower() == "true":
        return "Owner-Occupied"

    return "Unknown"


def match_and_annotate(listings, listing_type, parcels_df, overrides, scan_time):
    """Match listings against Wynbrooke parcels and annotate each match."""
    # Build lookup: normalized address -> parcel row
    addr_lookup = {}
    for _, row in parcels_df.iterrows():
        norm = row.get("prop_addr_norm", "")
        if norm:
            addr_lookup[norm] = row

    matched = []
    for listing in listings:
        formatted = listing.get("formattedAddress", "")
        street = extract_street_address(formatted)
        if not street:
            continue

        normalized = normalize_addr(street)
        parcel_row = addr_lookup.get(normalized)
        if parcel_row is None:
            continue

        # Extract agent info
        agent_info = listing.get("listingAgent") or {}
        agent_name = agent_info.get("name", "")
        agent_phone = agent_info.get("phone", "")
        listing_agent = agent_name
        if agent_phone:
            listing_agent = f"{agent_name} ({agent_phone})" if agent_name else agent_phone

        record = {
            "address": parcel_row["prop_addr"].strip(),
            "parcel_number": parcel_row["parcel_number"].strip(),
            "current_status": get_current_status(parcel_row, overrides),
            "list_price": listing.get("price"),
            "days_on_market": listing.get("daysOnMarket"),
            "listing_agent": listing_agent,
            "listing_type": listing_type,
            "last_scanned": scan_time,
        }
        matched.append(record)

    return matched


def run_scan():
    """Run the full listing scan. Returns the list of matched/annotated listings."""
    api_key = get_api_key()
    scan_time = datetime.now(timezone.utc).isoformat()

    parcels_df = load_parcel_data()
    overrides = load_overrides()

    # Fetch sale listings
    print("Fetching active for-sale listings in 46234...")
    sale_listings = fetch_listings("listings/sale", api_key)
    print(f"  Found {len(sale_listings)} for-sale listings in zip code.")

    # Fetch rental listings
    print("Fetching active for-rent listings in 46234...")
    rental_listings = fetch_listings("listings/rental/long-term", api_key)
    print(f"  Found {len(rental_listings)} for-rent listings in zip code.")

    # Match against Wynbrooke parcels
    sale_matched = match_and_annotate(sale_listings, "for_sale", parcels_df, overrides, scan_time)
    rental_matched = match_and_annotate(rental_listings, "for_rent", parcels_df, overrides, scan_time)

    all_matched = sale_matched + rental_matched

    # Write results
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_matched, f, indent=2)

    # Print summary
    print()
    print("=" * 60)
    print("MARKET MONITOR SCAN SUMMARY")
    print("=" * 60)
    print(f"Total for-sale listings in {ZIP_CODE}:    {len(sale_listings)}")
    print(f"Total for-rent listings in {ZIP_CODE}:    {len(rental_listings)}")
    print(f"Matched to Wynbrooke (for-sale):       {len(sale_matched)}")
    print(f"Matched to Wynbrooke (for-rent):       {len(rental_matched)}")
    print()

    # Breakdown by category
    at_risk = [r for r in sale_matched if r["current_status"] == "Owner-Occupied"]
    relief = [r for r in sale_matched if r["current_status"] == "Rental"]
    rental_ads = rental_matched
    print(f"At-Risk Sales (owner-occ for sale):    {len(at_risk)}")
    print(f"Relief Watch (rentals for sale):        {len(relief)}")
    print(f"Active Rental Ads:                     {len(rental_ads)}")
    print()
    print(f"Results written to {OUTPUT_PATH}")

    return all_matched


if __name__ == "__main__":
    run_scan()
