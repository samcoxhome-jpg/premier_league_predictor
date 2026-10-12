#Prints what the FPL API returns for one finished match and one team
#Run with: python check_api_fields.py
import json
import requests
from src.api_client import BASE_URL, HEADERS

fixtures = requests.get(f"{BASE_URL}/fixtures/", headers=HEADERS, timeout=20).json()
finished = [f for f in fixtures if f["finished"]]

if not finished:
    print("No finished matches yet this season.")
else:
    print("One finished fixture:")
    print(json.dumps({k: v for k, v in finished[0].items() if k != "stats"}, indent=2))

teams = requests.get(f"{BASE_URL}/bootstrap-static/", headers=HEADERS, timeout=20).json()["teams"]
print("\nOne team:")
print(json.dumps(teams[0], indent=2))
