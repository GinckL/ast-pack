from decimal import Decimal

from .models import Card, PaymentRequest
from .payments.gateway import Gateway
from .payments.service import process_payment, refund_payment


def checkout_handler(body: dict) -> dict:
    req = PaymentRequest(
        amount=Decimal(body["amount"]),
        currency=body["currency"],
        card=Card(body["card"], body["cvv"]),
    )
    receipt = process_payment(req, Gateway("sk_live"))
    return {"id": receipt.id}


def refund_handler(body: dict) -> dict:
    return {"ok": refund_payment(body["id"], Gateway("sk_live"))}


def health_handler() -> dict:
    return {"status": "up"}
