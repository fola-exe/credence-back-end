from app.core.errors import AppError, Unauthorized, error_envelope, validation_fields


def test_error_envelope_shape():
    assert error_envelope(
        "CAPACITY_EXCEEDED",
        "Over limit.",
        fields={"override": "Send override=true."},
    ) == {
        "error": {
            "code": "CAPACITY_EXCEEDED",
            "message": "Over limit.",
            "fields": {"override": "Send override=true."},
        }
    }


def test_app_error_uses_class_defaults_and_headers():
    error = Unauthorized(headers={"WWW-Authenticate": "Bearer"})

    assert error.http_status == 401
    assert error.headers == {"WWW-Authenticate": "Bearer"}
    assert error.envelope() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "Authentication is required.",
            "fields": None,
        }
    }


def test_app_error_accepts_custom_message_and_fields():
    error = AppError("Bad input", fields={"email": "Invalid"})

    assert error.message == "Bad input"
    assert error.envelope()["error"]["fields"] == {"email": "Invalid"}


def test_validation_fields_flattens_pydantic_locations():
    fields = validation_fields(
        [
            {
                "loc": ("body", "credentials", "email"),
                "msg": "Value error, invalid email",
            },
            {
                "loc": ("query", "page"),
                "msg": "Input should be a valid integer",
            },
        ]
    )

    assert fields == {
        "credentials.email": "Value error, invalid email",
        "page": "Input should be a valid integer",
    }
