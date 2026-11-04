import re

from ..models import CURRENCIES, MAX_AMOUNT, PaymentRequest

CARD_RE = re.compile(r"^\d{16}$")


class ValidationError(Exception):
    pass


def luhn_ok(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_request(req: PaymentRequest) -> None:
    if req.amount <= 0 or req.amount > MAX_AMOUNT:
        raise ValidationError("amount out of range")
    if req.currency not in CURRENCIES:
        raise ValidationError("unsupported currency")
    if not CARD_RE.match(req.card.number) or not luhn_ok(req.card.number):
        raise ValidationError("invalid card")


def normalize_tags(tags: list[str]) -> list[str]:
    return sorted({t.strip().lower() for t in tags if t.strip()})
