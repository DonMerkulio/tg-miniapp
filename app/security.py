import hashlib, hmac, urllib.parse, json
from .config import settings

def _webapp_secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

def validate_init_data(init_data: str) -> dict | None:
    if not init_data or not settings.bot_token:
        return None
    pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    hash_from_tg = data.pop("hash", None)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = _webapp_secret_key(settings.bot_token)
    calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hash_from_tg or not hmac.compare_digest(calc, hash_from_tg):
        return None
    return {"user": data.get("user"), "query_id": data.get("query_id")}

def extract_tg_id(user_json: str | None) -> str | None:
    if not user_json: return None
    try: u = json.loads(user_json); return str(u.get("id"))
    except Exception: return None
