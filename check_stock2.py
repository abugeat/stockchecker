import os
import json
import re
import requests

PRODUCT_PAGE = os.environ["PRODUCT_PAGE"]
PRODUCT_URL = os.environ.get("PRODUCT_URL", PRODUCT_PAGE)

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_PATH = os.environ.get("STATE_PATH", ".state/last.json")

SIZE_TO_CHECK = os.environ.get("SIZE_TO_CHECK", "M")  # default: M

HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_product_html() -> str:
    r = requests.get(PRODUCT_PAGE, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def extract_swatches_jsonconfig(html: str) -> dict:
    """
    Extract the Magento swatch-renderer jsonConfig object from:
      "Magento_Swatches/js/swatch-renderer": { "jsonConfig": {...}, ... }
    We parse ONLY the jsonConfig sub-object (pure JSON).
    """
    # Find the start of `"jsonConfig": {` — try both double and single quotes
    m = re.search(r'(?:"jsonConfig"|\'jsonConfig\')\s*:\s*\{', html)
    if not m:
        raise ValueError("Could not find jsonConfig in HTML")

    start = m.end() - 1  # points to the '{' of jsonConfig
    # Balance braces to extract the full JSON object
    depth = 0
    i = start
    while i < len(html):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                json_str = html[start : i + 1]
                return json.loads(json_str)
        i += 1

    raise ValueError("Unterminated jsonConfig object")


def get_size_status_from_jsonconfig(cfg: dict, size_label: str) -> tuple[bool, str]:
    """
    Returns (in_stock_bool, human_status_string)
    Logic:
      - Find the size attribute (by label == 'Size' or code == 'taille')
      - Find option where label matches size_label (e.g. 'M')
      - Map to simple product id (first element in option.products)
      - Prefer cfg.dynamic.status[productId].value ('in-stock' / 'out-of-stock')
      - Fallback to option.stock numeric if present
    """
    attrs = cfg.get("attributes", {})
    if not attrs:
        return False, "unknown (no attributes in jsonConfig)"

    # Find the "Size" attribute id key (e.g. "219")
    size_attr_id = None
    for attr_id, attr in attrs.items():
        if (attr.get("label") or "").lower() == "size" or (attr.get("code") or "").lower() in ("taille", "size"):
            size_attr_id = attr_id
            break

    if size_attr_id is None:
        # As a fallback: if only one attribute exists, assume it's the size attribute
        if len(attrs) == 1:
            size_attr_id = next(iter(attrs.keys()))
        else:
            return False, "unknown (size attribute not found)"

    options = attrs[size_attr_id].get("options", [])
    target_opt = next((o for o in options if (o.get("label") or "").strip().upper() == size_label.strip().upper()), None)
    if not target_opt:
        return False, f"unknown (size {size_label} not found)"

    products = target_opt.get("products") or []
    if not products:
        return False, f"unknown (no simple product for size {size_label})"

    simple_id = str(products[0])

    # Prefer dynamic status
    dyn = cfg.get("dynamic", {})
    status_map = (((dyn.get("status") or {})).get(simple_id) or {}).get("value")
    if status_map:
        status_map_l = status_map.lower().strip()
        if status_map_l == "in-stock":
            return True, f"in-stock (simple_id={simple_id})"
        if status_map_l == "out-of-stock":
            # Often this store uses out-of-stock + "Backorder"
            backorder = (((dyn.get("calcul_pastille_stock") or {})).get(simple_id) or {}).get("value")
            ship = (((dyn.get("label_expedition") or {})).get(simple_id) or {}).get("value")
            extra = " / ".join(x for x in [backorder, ship] if x)
            return False, f"out-of-stock (simple_id={simple_id})" + (f" [{extra}]" if extra else "")

        # Unknown status string from site
        return False, f"unknown status='{status_map}' (simple_id={simple_id})"

    # Fallback: option stock numeric (sometimes present even when status says out-of-stock)
    raw_stock = target_opt.get("stock")
    if raw_stock is not None:
        try:
            n = int(str(raw_stock).strip())
            return (n > 0), f"stock={n} (simple_id={simple_id})"
        except ValueError:
            pass

    return False, f"unknown (no dynamic status; simple_id={simple_id})"


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
    html = fetch_product_html()
    try:
        cfg = extract_swatches_jsonconfig(html)
    except ValueError as exc:
        print(f"WARNING: Could not parse product page — {exc}")
        print("The product page structure may have changed. Stock status unknown.")
        return

    now, availability = get_size_status_from_jsonconfig(cfg, SIZE_TO_CHECK)

    last = load_last()
    prev = last.get("in_stock")

    # Notify only on transition False -> True
    if prev is False and now is True:
        notify(
            "AVAILABILITY ALERT",
            f"Size {SIZE_TO_CHECK} is available! Status: {availability}",
            PRODUCT_PAGE,
        )

    save_last(now, availability)

    # Useful logs
    print("size:", SIZE_TO_CHECK)
    print("availability:", availability)
    print("in_stock:", now, "prev:", prev)


if __name__ == "__main__":
    main()