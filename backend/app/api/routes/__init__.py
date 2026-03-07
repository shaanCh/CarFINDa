from app.api.routes.search import router as search_router
from app.api.routes.listings import router as listings_router
from app.api.routes.preferences import router as preferences_router
from app.api.routes.chat import router as chat_router
from app.api.routes.monitor import router as monitor_router
from app.api.routes.outreach import router as outreach_router
from app.api.routes.credentials import router as credentials_router

all_routers = [
    search_router,
    listings_router,
    preferences_router,
    chat_router,
    monitor_router,
    outreach_router,
    credentials_router,
]
