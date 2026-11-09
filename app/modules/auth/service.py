from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException, status

from pydantic import BaseModel, EmailStr, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.models import Business, BusinessCategory
from app.core.dependencies import DatabaseSession, AuthenticatedBusiness
from app.core.security import hash_password, verify_password, create_access_token


class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class RegisterSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    business_name: str
    registration_number: str
    phone: str
    address: str
    category: BusinessCategory

class BusinessSchema(BaseModel):
    id: UUID
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)

class RegisterResponse(BaseModel):
    user: BusinessSchema
    access_token: str
    token_type: str

class FullBusinessSchema(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    phone: str
    address: str
    registration_number: str
    category: str


    model_config = ConfigDict(from_attributes=True)
auth_routes = APIRouter()

@auth_routes.post("/auth/login")
async def login(db: DatabaseSession, credentials: LoginSchema):

    business = db.query(Business).filter(
        Business.email == credentials.email
    ).first()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    try:
        verify_password(
            credentials.password,
            business.hashed_password,
        )
    except VerifyMismatchError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token({
        "sub": str(business.id)
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }

@auth_routes.post(
    "/auth/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED)
async def register(db: DatabaseSession, credentials: RegisterSchema):
    business = db.query(Business).filter(Business.email == credentials.email).first()
    if business:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    new_business = Business(
        name=credentials.business_name,
        hashed_password=hash_password(credentials.password),
        category=credentials.category,
        address=credentials.address,
        phone=credentials.phone,
        email=credentials.email,
        registration_number=credentials.registration_number
    )
    db.add(new_business)
    try:
        db.commit()
        db.refresh(new_business)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )

    access_token = create_access_token({
        "sub": str(new_business.id)
    })

    return {
        "user": new_business,
        "access_token": access_token,
        "token_type": "bearer"
    }

@auth_routes.get("/me", response_model=FullBusinessSchema, status_code=status.HTTP_200_OK)
def me(current_user: AuthenticatedBusiness):
    return current_user