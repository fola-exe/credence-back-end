from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.security import verify_access_token, oauth2_scheme
from app.core.database import get_db
from app.models import Business

from typing import Annotated


def get_current_business(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):

    business_id = verify_access_token(token)

    if business_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    try:
        business_id = UUID(business_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject"
        )

    business = db.query(Business).filter(
        Business.id == business_id
    ).first()

    if business is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return business

DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedBusiness = Annotated[Business, Depends(get_current_business)]

