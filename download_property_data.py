"""
Download Hendricks County Real Property data from Indiana Gateway.

The site is an ASP.NET WebForms app that requires:
1. GET the page to capture __VIEWSTATE / __EVENTVALIDATION
2. POST back with dropdown selections to trigger the download
"""

import sys
import os
import requests
from bs4 import BeautifulSoup

URL = "https://gateway.ifionline.org/public/download.aspx"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
})


def get_hidden_fields(soup):
    """Extract ASP.NET hidden form fields."""
    fields = {}
    for tag in soup.find_all("input", type="hidden"):
        name = tag.get("name") or tag.get("id")
        if name:
            fields[name] = tag.get("value", "")
    return fields


def find_county_code(soup, county_name):
    """Find the option value for a county name in DropDownList3."""
    select = soup.find("select", {"name": "ctl00$ContentPlaceHolder1$DropDownList3"})
    for opt in select.find_all("option"):
        if county_name.lower() in opt.text.strip().lower():
            return opt["value"], opt.text.strip()
    return None, None


# Step 1: GET the page
print("Fetching download page...")
resp = session.get(URL)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")

# Find Hendricks County code
code, name = find_county_code(soup, "Hendricks")
print(f"Found county: {name} (code={code})")

# Step 2: POST to download Real Property file
hidden = get_hidden_fields(soup)
payload = {
    **hidden,
    # Property Files section dropdowns
    "ctl00$ContentPlaceHolder1$DropDownList1": "5",        # Real Property
    "ctl00$ContentPlaceHolder1$DropDownList2": "2024",     # 2024 pay 2025 (most recent)
    "ctl00$ContentPlaceHolder1$DropDownList3": code,       # Hendricks County
    # The download button for the Property Files section
    "ctl00$ContentPlaceHolder1$button2": "Download",
    # Keep the finance section defaults populated
    "ctl00$ContentPlaceHolder1$RadComboBox1": "Annual Financial Reports",
    "ctl00$ContentPlaceHolder1$RadComboBox2": "Capital Assets",
    "ctl00$ContentPlaceHolder1$DropDownListUnitType": "All",
    "ctl00$ContentPlaceHolder1$DropDownListYear": "2025",
}

print(f"\nDownloading Real Property data for {name}, 2024 pay 2025...")
resp = session.post(URL, data=payload, stream=True)
resp.raise_for_status()

# Check what we got back
content_type = resp.headers.get("Content-Type", "")
content_disp = resp.headers.get("Content-Disposition", "")
print(f"Content-Type: {content_type}")
print(f"Content-Disposition: {content_disp}")

if "text/html" in content_type and not content_disp:
    # We got a page back, not a file — inspect it for errors
    print("\nGot HTML instead of a file download. Checking for error messages...")
    error_soup = BeautifulSoup(resp.content, "html.parser")
    # Look for alert/error spans
    for span in error_soup.find_all("span", class_="error"):
        print(f"  ERROR: {span.text}")
    # Save for debugging
    debug_path = os.path.join(DATA_DIR, "debug_response.html")
    with open(debug_path, "wb") as f:
        f.write(resp.content)
    print(f"Saved response to {debug_path} for debugging")
    sys.exit(1)

# Save the file
outfile = os.path.join(DATA_DIR, f"hendricks_real_property_2024.txt")
size = 0
with open(outfile, "wb") as f:
    for chunk in resp.iter_content(chunk_size=8192):
        f.write(chunk)
        size += len(chunk)

print(f"\nSaved to {outfile} ({size:,} bytes)")

# Quick preview
print("\n=== FIRST 5 LINES ===")
with open(outfile, "r", encoding="utf-8", errors="replace") as f:
    for i, line in enumerate(f):
        if i >= 5:
            break
        # Truncate long lines for display
        if len(line) > 300:
            print(f"Line {i}: {line[:300]}...")
        else:
            print(f"Line {i}: {line.rstrip()}")
