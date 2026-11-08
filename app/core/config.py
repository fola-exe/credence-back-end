from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_token_expiry_minutes: int = 30
    jwt_algorithm: str = "HS256"


    model_config: dict = {"env_file": ".env"}



settings = Settings()
