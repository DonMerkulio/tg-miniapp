# app/loaders.py
import json, os, time, asyncio, httpx, re
from typing import Set
from .schemas import Product
from .config import settings

# -------- TTL/версии --------
_REFRESH_TTL = 300
_last_fetch_ts = 0.0

AVAX_BASE = "https://admin.avaxmotors.ru"
API_URL = f"{AVAX_BASE}/api/items.php?action=list&filters[stock_status]=0&with_photo=1"

# Резервы
RESERVES_URL = ""
RESERVED_IDS: set[int] = set()
_last_reserves_ts = 0.0
_RESERVES_TTL = 30

INVENTORY_VERSION = 1


def get_inventory_version() -> int: return INVENTORY_VERSION


def bump_inventory_version() -> int:
    global INVENTORY_VERSION
    INVENTORY_VERSION += 1
    return INVENTORY_VERSION


# ------ поиск/бакеты (без изменений) ------
SEARCH_ALIASES = {"brand": ["МАРКА"], "model": ["МОДЕЛЬ"], "year": ["ГОД"], "part": ["ЗАПЧАСТЬ"],
                  "engine_mark": ["МАРКИРОВКА ДВИГАТЕЛЯ"], "sku_in": ["ВХОДНОЙ АРТИКУЛ"]}
# app/loaders.py
SEARCH_ALIASES = {
    "brand": ["МАРКА"],
    "model": ["МОДЕЛЬ"],
    "year": ["ГОД"],
    "part": ["ЗАПЧАСТЬ"],
    "engine_mark": ["МАРКИРОВКА ДВИГАТЕЛЯ"],
    "sku_in": ["ВХОДНОЙ АРТИКУЛ"],
}

PUBLIC_FIELDS = [
    "Склад", "ШРОТ", "ВХОДНОЙ АРТИКУЛ", "ЗАПЧАСТЬ", "МАРКА", "МОДЕЛЬ", "ГОД", "ТОПЛИВО", "ОБЪЕМ",
    "ТИП ДВИГАТЕЛЯ", "КОРОБКА", "МАРКИРОВКА ДВИГАТЕЛЯ", "ОПИСАНИЕ", "ЦЕНА", "ВАЛЮТА", "VIN", "VRN"
]


def _simplify_part(s: str) -> str: return (s or "").strip().replace("Передняя часть (ноускат) в сборе", "Ноускат")


_BUCKETS = [
    ("engine", "Двигатель", [r"двиг", r"мотор", r"шорт", r"лонг", r"головк", r"блок цилинд", r"поршен"]),
    ("nosecut", "Ноускат", [r"ноускат"]),
    ("gearbox", "КПП",
     [r"\bкпп\b", r"коробк", r"акпп", r"мкпп", r"гидротранс", r"вариатор", r"датчик селектор", r"кардан"]),
    ("body", "Кузовное",
     [r"крыло", r"двер", r"капот", r"крыш", r"бампер", r"порог", r"рам[аы]", r"панел", r"стойк", r"зерка"]),
    ("bolt_on", "Навесное",
     [r"стартер", r"генератор", r"компрессор", r"насос", r"форсун", r"турб", r"тнвд", r"коллект", r"катушк", r"поддо",
      r"заслонк"]),
    ("susp", "Подвеска", [r"рычаг", r"ступиц", r"амортиз", r"пружин", r"подрамн", r"сайлент"]),
    ("electro", "Электрика",
     [r"проводк", r"жгут", r"блок упр", r"эбу", r"мозг", r"датчик(?! селектор)", r"электро", r"батаре", r"блок предох",
      r"блок bsm"]),
    ("interior", "Салон", [r"сидень", r"торпед", r"обшив", r"руль", r"ремень безопас", r"ковролин", r"кнопк"]),
    ("lights", "Оптика", [r"фара", r"фонар", r"противотуман", r"повторител"]),
    ("brake", "Тормоза", [r"суппорт", r"диск торм", r"барабан", r"вакуумник", r"главн.*торм"]),
    ("exhaust", "Выхлоп", [r"глушит", r"катализ", r"паук", r"резонатор"]),
    ("cooling", "Охлаждение", [r"радиатор(?! печки)", r"вентилятор охлажд", r"интеркулер", r"помпа", r"интеркул"]),
    ("steer", "Рулевое", [r"рулев", r"рейк", r"карданчик руля", r"насос гур", r"гур"]),
]
_BUCKET_OTHER = ("other", "Другое")


def map_part_to_bucket(raw_part: str) -> tuple[str, str]:
    s = _simplify_part(raw_part or "")
    if not s: return _BUCKET_OTHER
    if s.lower() == "ноускат": return ("nosecut", "Ноускат")
    low = s.lower()
    for key, label, pats in _BUCKETS:
        for pat in pats:
            if re.search(pat, low): return (key, label)
    return _BUCKET_OTHER


# ------ маппинг нового API → Product ------
def _f(item: dict, key: str) -> str:
    fld = (item.get("fields") or {}).get(key) or {}
    return (fld.get("display_value") or fld.get("value") or "").strip()


def _photo_url(u: str) -> str:
    u = (u or "").strip()
    if not u: return ""
    if u.startswith("http://"): u = "https://" + u[7:]
    if u.startswith("//"): return "https:" + u
    if u.startswith("/"):  return AVAX_BASE + u
    if not u.startswith("http"): return AVAX_BASE + "/" + u
    return u


def _row_to_product(item: dict) -> Product:
    pid = int(item.get("id"))
    brand = _f(item, "car_brand_id")
    model = _f(item, "car_model_id")
    year = (_f(item, "year") or "").strip()
    part = _f(item, "part_id")
    price = float(item.get("price_dollar") or 0)
    currency = "USD"
    photos = []
    for ph in (item.get("photos") or []):
        url = _photo_url(ph.get("url") or ph.get("thumbnail_url") or "")
        if url: photos.append(url)
    raw = {
        "МАРКА": brand, "МОДЕЛЬ": model, "ГОД": year, "ЗАПЧАСТЬ": part,
        "ЦЕНА": price, "ВАЛЮТА": currency,
        "Склад": (_f(item, "stock_id") or "").replace("#", "").strip(),
        "ШРОТ": ((item.get("fields") or {}).get("shrot_id") or {}).get("display_value") or "",
        "ВХОДНОЙ АРТИКУЛ": ((item.get("fields") or {}).get("input_article") or {}).get("value") or "",
        "ТОПЛИВО": _f(item, "type_id"),
        "ОБЪЕМ": _f(item, "capacity_id"),
        "ТИП ДВИГАТЕЛЯ": _f(item, "type_id"),
        "МАРКИРОВКА ДВИГАТЕЛЯ": (_f(item, "mark_engine") or "").strip(),
        "КОРОБКА": _f(item, "kpp_id"),
        "ТИП КУЗОВА": _f(item, "body_id"),
        "ПРИВОД": _f(item, "drive_id"),
        "VIN": _f(item, "vin_number"), "VRN": _f(item, "vrn_number"),
        "ОРИГИНАЛЬНЫЙ НОМЕР": _f(item, "oem_number"),
        "ОПИСАНИЕ": (_f(item, "description") or "").strip(),
        "ВИДЕО": (item.get("video_url") or "").strip(),
        "ФОТО": "",  # не используется дальше
    }
    stock_status = str(item.get("stock_status") or "0").strip()
    deleted = str(item.get("deleted") or "0").strip()
    quantity = int(float(item.get("quantity") or 0))

    p = Product(
        id=pid, brand=brand, model=model, year=str(year or ""),
        part=part, price=price, currency=currency,
        photos=photos, description=raw["ОПИСАНИЕ"], warehouse=raw["Склад"]
    )
    p.__dict__["_raw"] = raw
    # ↓↓↓ ЭТО ВАЖНО: статус и удалённость для фильтрации витрины
    p.__dict__["_stock_status"] = str(item.get("stock_status") or "0")  # 0=активен, 2=резерв, 3=продан…
    p.__dict__["_deleted"] = str(item.get("deleted") or "0")
    return p


# -------- публичные помощники (без изменений) --------
def all_categories():
    vals = {}
    for p in PRODUCTS:
        v = (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip()
        if v: vals[v] = vals.get(v, 0) + 1
    return vals


def all_parts():
    vals = {}
    for p in PRODUCTS:
        raw = p.__dict__.get("_raw", {})
        v = _simplify_part(raw.get("ЗАПЧАСТЬ", ""))
        if v: vals[v] = vals.get(v, 0) + 1
    return vals


def searchable_fields() -> list[str]:
    keys = set()
    for p in PRODUCTS:
        keys.update(p.__dict__.get("_raw", {}).keys())
    return sorted(keys)


def parts_buckets():
    out: dict[str, dict] = {}
    for p in PRODUCTS:
        raw = p.__dict__.get("_raw", {})
        k, lbl = map_part_to_bucket(raw.get("ЗАПЧАСТЬ", ""))
        if not k: continue
        d = out.setdefault(k, {"key": k, "label": lbl, "count": 0})
        d["count"] += 1
    return sorted(out.values(), key=lambda x: (-x["count"], x["label"]))


# -------- глобальное хранилище ТОЛЬКО в памяти --------
PRODUCTS: list[Product] = []  # ← никаких файлов


async def refresh_from_api(force: bool = False) -> None:
    global PRODUCTS, _last_fetch_ts
    now = time.time()
    if not force and (now - _last_fetch_ts) < _REFRESH_TTL:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(API_URL)
            r.raise_for_status()
            data = r.json()
        items = None
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            items = data["data"].get("items")
        if items is None and isinstance(data, dict):
            items = data.get("items")
        if not isinstance(items, list):
            print("API: unexpected payload");
            return

        mapped: list[Product] = []
        for it in items:
            try:
                mapped.append(_row_to_product(it))
            except:
                pass

        if mapped:
            PRODUCTS.clear()
            PRODUCTS.extend(mapped)
            _last_fetch_ts = now
            print(f"API refresh ok: {len(PRODUCTS)} items")
    except Exception as e:
        print("API refresh failed:", e)


async def _fetch_reserved_ids_from_admin() -> set[int]:
    headers = {}
    if settings.inventory_auth:
        headers["Authorization"] = settings.inventory_auth
    params = {"action": "list", "limit": "10000", "with_photo": "0", "filters[stock_status]": "2"}
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.get(settings.inventory_api, params=params, headers=headers)
        r.raise_for_status()
        js = r.json()
        items = (js.get("data") or {}).get("items") or []
        ids: set[int] = set()
        for it in items:
            try:
                ids.add(int(it.get("id")))
            except:
                pass
        return ids


async def refresh_reserves(force: bool = False) -> bool:
    global RESERVED_IDS, _last_reserves_ts
    now = time.time()
    if not force and (now - _last_reserves_ts) < _RESERVES_TTL:
        return False
    try:
        ids = await _fetch_reserved_ids_from_admin()
    except Exception as e:
        print("refresh_reserves error:", e);
        return False
    changed = ids != RESERVED_IDS
    if changed:
        RESERVED_IDS.clear();
        RESERVED_IDS.update(ids)
        bump_inventory_version()
    _last_reserves_ts = now
    return changed


async def background_refresher():
    while True:
        try:
            await refresh_from_api()
            await refresh_reserves()
        except Exception as e:
            print("background_refresher error:", e)
        await asyncio.sleep(60)
