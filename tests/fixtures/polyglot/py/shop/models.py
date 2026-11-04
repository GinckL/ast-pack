"""Domain models for the shop."""
from dataclasses import dataclass, field
from decimal import Decimal

MAX_AMOUNT = Decimal("10000")
CURRENCIES = ("USD", "EUR")


@dataclass
class Card:
    number: str
    cvv: str

    def masked(self) -> str:
        return "*" * 12 + self.number[-4:]

    def brand(self) -> str:
        if self.number.startswith("4"):
            return "visa"
        return "other"


@dataclass
class PaymentRequest:
    """A request to charge a card."""

    amount: Decimal
    currency: str
    card: Card
    tags: list[str] = field(default_factory=list)

    def is_large(self) -> bool:
        return self.amount > MAX_AMOUNT / 2

    def describe(self) -> str:
        return f"{self.amount} {self.currency}"


@dataclass
class Receipt:
    id: str
    amount: Decimal


class Inventory:
    def reserve(self, sku: str) -> None:
        raise NotImplementedError

    def release(self, sku: str) -> None:
        raise NotImplementedError
