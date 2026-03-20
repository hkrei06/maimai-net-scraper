import requests
from dotenv import load_dotenv
import os

load_dotenv()

CLAL = os.getenv("LNGCOOKIE")

AUTH_URL = (
    "https://lng-tgk-aime-gw.am-all.net/common_auth/login"
    "?site_id=maimaidxex"
    "&redirect_url=https://maimaidx-eng.com/maimai-mobile/"
    "&back_url=https://maimai.sega.com/"
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
session.cookies.set("clal", CLAL, domain="lng-tgk-aime-gw.am-all.net")

# Step 1: Auth
print("=== STEP 1: AUTH ===")
auth_response = session.get(AUTH_URL, allow_redirects=False)
print(f"Status: {auth_response.status_code}")
ssid_url = auth_response.headers.get("Location")
print(f"ssid URL: {ssid_url}")

# Step 2: Hit ssid with Referer set to AIME domain
# Step 2: Hit ssid with Referer, follow all redirects
print("\n=== STEP 2: SSID ===")
ssid_response = session.get(ssid_url, allow_redirects=True)
print(f"Status: {ssid_response.status_code}")
print(f"Final URL: {ssid_response.url}")

print("\n--- Redirect Chain ---")
for r in ssid_response.history:
    print(f"  {r.status_code} -> {r.url}")

print("\n--- SSID Response Headers ---")
for k, v in ssid_response.headers.items():
    print(f"  {k}: {v}")

print("\n--- Body ---")
print(ssid_response.text[:1000])

print("\n--- All cookies ---")
for cookie in session.cookies:
    print(f"  [{cookie.domain}] {cookie.name} = {cookie.value}")

