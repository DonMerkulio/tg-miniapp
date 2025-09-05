from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .db import Base, engine
from .routers import webapp, auth, products, admin_pages, shipments, moves, reserve_pages, reserves, user_pages, users, \
    broadcast_prices, broadcast_notify, realtime
import asyncio
from .loaders import refresh_from_api, background_refresher, PRODUCTS, load_products, refresh_reserves

Base.metadata.create_all(bind=engine)

app = FastAPI(title="TG MiniApp")
app.include_router(webapp.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(admin_pages.router)
app.include_router(shipments.router)
app.include_router(moves.router)
app.include_router(reserve_pages.router)
app.include_router(reserves.router)
app.include_router(user_pages.router)
app.include_router(users.router)
app.include_router(broadcast_prices.router)
app.include_router(broadcast_notify.router)
app.include_router(realtime.router)

app.mount("/static", StaticFiles(directory="static"), name="static")

# API refresh hooks


if not PRODUCTS:
    try:
        PRODUCTS[:] = load_products()
    except Exception:
        pass


@app.on_event("startup")
async def _startup():
    try:
        await refresh_from_api(force=True)
        await refresh_reserves(force=True)
    except Exception as e:
        print("startup refresh failed:", e)
    asyncio.create_task(background_refresher())


