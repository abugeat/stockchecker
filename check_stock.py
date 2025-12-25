import os
import json
import requests

PRODUCT_URL = os.environ["PRODUCT_URL"]

PRODUCT_PAGE = os.environ["PRODUCT_PAGE"]

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_PATH = os.environ.get("STATE_PATH", ".state/last.json")

PARAMS = {
  "dwvar_4164_pv_rahmenfarbe": "R138_P01",
  "dwvar_4164_pv_rahmengroesse": "M",
  "pid": "4164",
  "quantity": "1",
}

def get_availability() -> str:
    r = requests.get(
        PRODUCT_URL,
        params=PARAMS,
        headers={
            "accept": "application/json, text/javascript, */*; q=0.01",
            "x-requested-with": "XMLHttpRequest",
            "user-agent": "Mozilla/5.0",
            "referer": PRODUCT_PAGE,
        },
        timeout=30
    )
    r.raise_for_status()
    data = r.json()
    view_item = next((x for x in data.get("gtmModel", []) if x.get("event") == "view_item"), None)
    if not view_item:
        return "unknown"
    print(view_item["ecommerce"]["items"])
    return view_item["ecommerce"]["items"][0].get("item_availability", "unknown")

def is_in_stock(availability: str) -> bool:
    a = (availability or "").lower()
    return ("not available" not in a) and ("unavailable" not in a) and (a != "unknown")

def load_last() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"in_stock": None, "availability": None}

def save_last(in_stock: bool, availability: str):
    import pathlib
    pathlib.Path(os.path.dirname(STATE_PATH) or ".").mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"in_stock": in_stock, "availability": availability}, f)

def notify(title: str, message: str, click_url: str):
    requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Click": click_url,
            "Priority": "high",
        },
        timeout=30,
    ).raise_for_status()

def main():
    availability = get_availability()
    now = is_in_stock(availability)

    last = load_last()
    prev = last.get("in_stock")

    # Notifier uniquement sur transition False -> True
    if prev is False and now is True:
        notify(
            "AVAILABILITY ALERT",
            f"Dispo détectée ! Statut: {availability}",
            PRODUCT_PAGE,
        )
    # else :
    #     notify(
    #         "Stock check",
    #         f"Vérification du stock. Statut: {availability}",
    #         PRODUCT_PAGE,
    #     )

    save_last(now, availability)

    # logs utiles dans Actions
    print("availability:", availability)
    print("in_stock:", now, "prev:", prev)

if __name__ == "__main__":
    main()