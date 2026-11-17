from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.modules.auth.service import auth_routes

app = FastAPI()
app.include_router(auth_routes)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://192.168.1.105:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "Working"}