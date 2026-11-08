from sqlalchemy import String, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.mixins import BaseMixin
from enum import Enum

class BusinessCategory(str, Enum):
    BANKING_FINANCIAL_SERVICES = "banking_financial_services"
    MICROFINANCE = "microfinance"
    FINTECH_DIGITAL_LENDING = "fintech_digital_lending"
    COOPERATIVES_CREDIT_UNIONS = "cooperatives_credit_unions"
    WHOLESALE_DISTRIBUTION = "wholesale_distribution"
    MANUFACTURING = "manufacturing"
    RETAIL_ECOMMERCE = "retail_ecommerce"
    EDUCATION = "education"
    HEALTHCARE = "healthcare"
    REAL_ESTATE_PROPERTY_MANAGEMENT = "real_estate_property_management"
    LOGISTICS_TRANSPORTATION = "logistics_transportation"
    EQUIPMENT_LEASING_RENTALS = "equipment_leasing_rentals"
    AGRICULTURE_AGRIBUSINESS = "agriculture_agribusiness"
    PROFESSIONAL_SERVICES = "professional_services"
    UTILITIES_TELECOMMUNICATIONS = "utilities_telecommunications"
    OTHER = "other"


class Business(Base, BaseMixin):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[BusinessCategory] = mapped_column(SQLEnum(BusinessCategory), nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    registration_number: Mapped[str] = mapped_column(String(20))

