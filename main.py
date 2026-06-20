from fastapi import FastAPI

from core.views import router

app = FastAPI()
app.include_router(router)
