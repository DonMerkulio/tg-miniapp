from io import BytesIO
from openpyxl import Workbook
from .loaders import PRODUCTS, PUBLIC_FIELDS

def build_prices_xlsx(products=None) -> BytesIO:
    wb = Workbook(); ws = wb.active; ws.title = "Прайс"
    ws.append(PUBLIC_FIELDS)
    items = products or PRODUCTS
    for p in items:
        r = p.__dict__.get("_raw", {})
        row = [r.get(k, "") for k in PUBLIC_FIELDS]
        ws.append(row)
    out = BytesIO(); wb.save(out); out.seek(0); return out
