from decimal import Decimal

from shop.models import Card, PaymentRequest
from shop.payments.gateway import Gateway
from shop.payments.service import process_payment


def test_process_payment_charges():
    req = PaymentRequest(Decimal("10"), "USD", Card("4242424242424242", "123"))
    assert process_payment(req, Gateway("sk_test")).amount > 0
