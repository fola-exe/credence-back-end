from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException
from app.core.dependencies import DatabaseSession
from app.core.security import hash_password, verify_password, create_access_token
from pydantic import BaseModel, EmailStr

from app.models import Business, BusinessCategory


class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class RegisterSchema(BaseModel):
    email: EmailStr
    password: str
    business_name: str
    registration_number: str
    phone: str
    address: str
    category: BusinessCategory

auth_routes = APIRouter()

@auth_routes.post("/auth/login")
async def login(db: DatabaseSession, credentials: LoginSchema):

    business = db.query(Business).filter(
        Business.email == credentials.email
    ).first()

    if not business:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    try:
        verify_password(
            credentials.password,
            business.hashed_password,
        )
    except VerifyMismatchError:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    access_token = create_access_token({
        "sub": str(business.id)
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@auth_routes.post("/auth/register")
async def register(db: DatabaseSession, credentials: RegisterSchema):
    business = db.query(Business).filter(Business.email == credentials.email).first()
    if business:
        raise HTTPException(
            status_code=401,
            detail="Business already exists with this email"
        )

    business = Business(
        name=credentials.business_name,
        hashed_password=hash_password(credentials.password),
        category=credentials.category,
        address=credentials.address,
        phone=credentials.phone,
        email=credentials.email,
        registration_number=credentials.registration_number
    )
    db.add(business)
    db.commit()

    return {"status": "Registered"}

@auth_routes.get("/me")
def me():
    pass