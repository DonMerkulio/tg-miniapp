import json, os, time, asyncio, httpx, re
from .schemas import Product
from typing import Set

DATA_PATHS = ["./data/data.json", "/mnt/data/data.json"]

SEARCH_ALIASES = {
    "brand": ["МАРКА"],
    "model": ["МОДЕЛЬ"],
    "year": ["ГОД"],
    "part": ["ЗАПЧАСТЬ"],
    "engine_mark": ["МАРКИРОВКА ДВИГАТЕЛЯ"],
    "sku_in": ["ВХОДНОЙ АРТИКУЛ"],
}

PUBLIC_FIELDS = [
    "Склад","ШРОТ","ВХОДНОЙ АРТИКУЛ","ЗАПЧАСТЬ","МАРКА","МОДЕЛЬ","ГОД","ТОПЛИВО","ОБЪЕМ",
    "ТИП ДВИГАТЕЛЯ","КОРОБКА","МАРКИРОВКА ДВИГАТЕЛЯ","ОПИСАНИЕ","ЦЕНА","ВАЛЮТА","VIN","VRN"
]

def all_categories():
    vals = {}
    for p in PRODUCTS:
        v = (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip()
        if not v: continue
        vals[v] = vals.get(v, 0) + 1
    return vals

def _find_path():
    for p in DATA_PATHS:
        if os.path.exists(p): return p
    return None

def _simplify_part(s: str) -> str:
    s = (s or "").strip()
    if not s: return s
    return s.replace("Передняя часть (ноускат) в сборе","Ноускат")

def all_parts():
    vals = {}
    for p in PRODUCTS:
        raw = p.__dict__.get("_raw", {})
        v = _simplify_part(raw.get("ЗАПЧАСТЬ",""))
        if not v: continue
        vals[v] = vals.get(v, 0) + 1
    return vals

def load_products() -> list[Product]:
    path = _find_path()
    if not path: return []
    with open(path,"r",encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for row in raw:
        photos = [x.strip() for x in (row.get("ФОТО") or "").split(",") if x.strip()]
        p = Product(
            id=int(row.get("id")),
            brand=row.get("МАРКА","").strip(),
            model=row.get("МОДЕЛЬ","").strip(),
            year=str(row.get("ГОД","")).strip(),
            part=row.get("ЗАПЧАСТЬ","").strip(),
            price=float(row.get("ЦЕНА") or 0),
            currency=row.get("ВАЛЮТА","").strip() or "USD",
            photos=photos,
            description=row.get("ОПИСАНИЕ","").strip(),
            warehouse=row.get("Склад")
        )
        p.__dict__["_raw"] = row
        out.append(p)
    return out

def searchable_fields() -> list[str]:
    keys = set()
    for p in PRODUCTS:
        keys.update(p.__dict__.get("_raw", {}).keys())
    return sorted({*keys, *[v for vs in SEARCH_ALIASES.values() for v in vs]})

_BUCKETS = [
    ("engine","Двигатель",[r"двиг",r"мотор",r"шорт",r"лонг",r"головк",r"блок цилинд",r"поршен"]),
    ("nosecut","Ноускат",[r"ноускат"]),
    ("gearbox","КПП",[r"\bкпп\b",r"коробк",r"акпп",r"мкпп",r"гидротранс",r"вариатор",r"датчик селектор",r"кардан"]),
    ("body","Кузовное",[r"крыло",r"двер",r"капот",r"крыш",r"бампер",r"порог",r"рам[аы]",r"панел",r"стойк",r"зерка"]),
    ("bolt_on","Навесное",[r"стартер",r"генератор",r"компрессор",r"насос",r"форсун",r"турб",r"тнвд",r"коллект",r"катушк",r"поддо",r"заслонк"]),
    ("susp","Подвеска",[r"рычаг",r"ступиц",r"амортиз",r"пружин",r"подрамн",r"сайлент"]),
    ("electro","Электрика",[r"проводк",r"жгут",r"блок упр",r"эбу",r"мозг",r"датчик(?! селектор)",r"электро",r"батаре",r"блок предох",r"блок bsm"]),
    ("interior","Салон",[r"сидень",r"торпед",r"обшив",r"руль",r"ремень безопас",r"ковролин",r"кнопк"]),
    ("lights","Оптика",[r"фара",r"фонар",r"противотуман",r"повторител"]),
    ("brake","Тормоза",[r"суппорт",r"диск торм",r"барабан",r"вакуумник",r"главн.*торм"]),
    ("exhaust","Выхлоп",[r"глушит",r"катализ",r"паук",r"резонатор"]),
    ("cooling","Охлаждение",[r"радиатор(?! печки)",r"вентилятор охлажд",r"интеркулер",r"помпа",r"интеркул"]),
    ("steer","Рулевое",[r"рулев",r"рейк",r"карданчик руля",r"насос гур",r"гур"]),
]
_BUCKET_OTHER = ("other","Другое")

def map_part_to_bucket(raw_part: str) -> tuple[str,str]:
    s = _simplify_part(raw_part or "")
    if not s: return _BUCKET_OTHER
    if s.lower()=="ноускат": return ("nosecut","Ноускат")
    low = s.lower()
    for key,label,pats in _BUCKETS:
        for pat in pats:
            if re.search(pat, low): return (key,label)
    return _BUCKET_OTHER

def parts_buckets():
    out: dict[str, dict] = {}
    for p in PRODUCTS:
        raw = p.__dict__.get("_raw", {})
        k,lbl = map_part_to_bucket(raw.get("ЗАПЧАСТЬ",""))
        if not k: continue
        d = out.setdefault(k, {"key":k,"label":lbl,"count":0})
        d["count"] += 1
    return sorted(out.values(), key=lambda x: (-x["count"], x["label"]))

PRODUCTS: list[Product] = load_products()

# ---------- API refresh ----------
API_URL = "https://avax.by/api/all_zap/DueMQ88!Sm43"
DATA_FILE = "./data/data.json"
_REFRESH_TTL = 300
_last_fetch_ts = 0.0

def _row_to_product(row: dict) -> Product:
    photos = [x.strip() for x in (row.get("ФОТО") or "").split(",") if x.strip()]
    p = Product(
        id=int(row.get("id")),
        brand=(row.get("МАРКА") or "").strip(),
        model=(row.get("МОДЕЛЬ") or "").strip(),
        year=str(row.get("ГОД") or "").strip(),
        part=(row.get("ЗАПЧАСТЬ") or "").strip(),
        price=float(row.get("ЦЕНА") or 0),
        currency=(row.get("ВАЛЮТА") or "").strip() or "USD",
        photos=photos,
        description=(row.get("ОПИСАНИЕ") or "").strip(),
        warehouse=row.get("Склад")
    )
    p.__dict__["_raw"] = row
    return p

def _save_rows_to_file(rows: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE,"w",encoding="utf-8") as f:
            json.dump(rows,f,ensure_ascii=False,indent=2)
    except Exception as e:
        print("save_to_file error:", e)

async def refresh_from_api(force: bool=False) -> None:
    global PRODUCTS, _last_fetch_ts
    now = time.time()
    if not force and (now - _last_fetch_ts) < _REFRESH_TTL:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.get(API_URL)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list): return
        items=[]
        for row in data:
            try: items.append(_row_to_product(row))
            except: continue
        if items:
            PRODUCTS = items
            _save_rows_to_file(data)
            _last_fetch_ts = now
            print(f"API refresh ok: {len(PRODUCTS)} items")
    except Exception as e:
        print("API refresh failed:", e)

async def background_refresher():
    while True:
        try:
            await refresh_from_api()
        except Exception as e:
            print("background_refresher error:", e)
        await asyncio.sleep(60)


PRODUCTS: list[Product] = load_products()

# ---------- RESERVES + VERSION ----------
RESERVES_URL = "https://avax.by/api/all_reserves/DueMQ88!Sm43"
RESERVED_IDS: set[int] = set()
_last_reserves_ts = 0.0
_RESERVES_TTL = 30  # сек

INVENTORY_VERSION = 1

def get_inventory_version() -> int:
    return INVENTORY_VERSION

def bump_inventory_version() -> int:
    global INVENTORY_VERSION
    INVENTORY_VERSION += 1
    return INVENTORY_VERSION

async def refresh_reserves(force: bool = False) -> bool:
    """
    Обновляет множество ID в резервах. Возвращает True, если состав изменился.
    """
    global RESERVED_IDS, _last_reserves_ts
    now = time.time()
    if not force and (now - _last_reserves_ts) < _RESERVES_TTL:
        return False
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.get(RESERVES_URL)
            r.raise_for_status()
            data = r.json()
            ids = {int(x.get("id")) for x in data if str(x.get("id", "")).isdigit()}
    except Exception as e:
        print("refresh_reserves error:", e)
        return False

    changed = ids != RESERVED_IDS
    RESERVED_IDS = ids
    _last_reserves_ts = now
    if changed:
        bump_inventory_version()
    return changed