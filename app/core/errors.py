from typing import Any

FieldErrors = dict[str, Any]


def error_envelope(
    code: str,
    message: str,
    *,
    fields: FieldErrors | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(extra or {})
    payload.update({"code": code, "message": message, "fields": fields})
    return {"error": payload}


def validation_fields(errors: list[dict[str, Any]]) -> FieldErrors:
    fields: FieldErrors = {}
    for error in errors:
        location = [
            str(part)
            for part in error.get("loc", ())
            if part not in ("body", "query", "path")
        ]
        key = ".".join(location) or "body"
        message = str(error.get("msg", "Invalid value"))
        existing = fields.get(key)
        if existing is None:
            fields[key] = message
        elif isinstance(existing, list):
            existing.append(message)
        else:
            fields[key] = [existing, message]
    return fields


class AppError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        fields: FieldErrors | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.fields = fields
        self.extra = extra or {}
        self.headers = headers or {}
        super().__init__(self.message)

    def envelope(self) -> dict[str, Any]:
        return error_envelope(
            self.code,
            self.message,
            fields=self.fields,
            extra=self.extra,
        )


class Unauthorized(AppError):
    code = "UNAUTHORIZED"
    http_status = 401
    default_message = "Authentication is required."


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422
    default_message = "The request is invalid."


class NotFound(AppError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "The requested resource was not found."


class Conflict(AppError):
    code = "CONFLICT"
    http_status = 409
    default_message = "The request conflicts with the current state."


class CapacityExceeded(AppError):
    code = "CAPACITY_EXCEEDED"
    http_status = 422
    default_message = "This transaction exceeds the available credit capacity."


class InvalidDateRange(AppError):
    code = "INVALID_DATE_RANGE"
    http_status = 422
    default_message = "The supplied date range is invalid."


class DebtorExists(Conflict):
    code = "DEBTOR_EXISTS"
    default_message = "A debtor with these details already exists."


class TransactionNotPayable(Conflict):
    code = "TXN_NOT_PAYABLE"
    default_message = "This transaction cannot be paid."


class TransactionNotFound(NotFound):
    code = "TXN_NOT_FOUND"
    default_message = "The transaction was not found."


class TransactionSettled(Conflict):
    code = "TXN_SETTLED"
    default_message = "This transaction has already been settled."


class TransactionCancelled(Conflict):
    code = "TXN_CANCELLED"
    default_message = "This transaction has been cancelled."


class TransactionNotCancellable(Conflict):
    code = "TXN_NOT_CANCELLABLE"
    default_message = "This transaction cannot be cancelled."


class PromiseWindowInvalid(AppError):
    code = "PROMISE_WINDOW_INVALID"
    http_status = 422
    default_message = "The promised date must be within the allowed window."


class DisputeAlreadyOpen(Conflict):
    code = "DISPUTE_ALREADY_OPEN"
    default_message = "This transaction already has an open dispute."


class DisputeNotOpen(Conflict):
    code = "DISPUTE_NOT_OPEN"
    default_message = "This transaction has no open dispute."


class ReminderTooSoon(AppError):
    code = "REMINDER_TOO_SOON"
    http_status = 429
    default_message = "A reminder was sent too recently."


class ReminderNotAllowed(Conflict):
    code = "REMINDER_NOT_ALLOWED"
    default_message = "A reminder cannot be sent for this transaction."


class PaymentInitFailed(AppError):
    code = "PAYMENT_INIT_FAILED"
    http_status = 502
    default_message = "Payment initialization failed."


class IdempotencyKeyReused(Conflict):
    code = "IDEMPOTENCY_KEY_REUSED"
    default_message = "The idempotency key was already used for a different payment."


class AmountOutOfRange(AppError):
    code = "AMOUNT_OUT_OF_RANGE"
    http_status = 422
    default_message = "The payment amount is outside the allowed range."


class WebhookSignatureInvalid(AppError):
    code = "WEBHOOK_SIGNATURE_INVALID"
    http_status = 401
    default_message = "The webhook signature is invalid."


class PaymentNotFound(NotFound):
    code = "PAYMENT_NOT_FOUND"
    default_message = "The payment was not found."


class RateLimited(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    default_message = "Too many requests. Please try again later."


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    http_status = 500
    default_message = "An unexpected error occurred."
