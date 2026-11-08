from fastapi import FastAPI
from app.modules.auth.service import auth_routes

app = FastAPI()
app.include_router(auth_routes)

@app.get("/health")
def health():
    return {"status": "Working"}