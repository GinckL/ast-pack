import uuid

from ..models import PaymentRequest, Receipt

FEE_RATE = 0.029


class Gateway:
    """Talks to the card processor."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.sent = 0

    def charge(self, req: PaymentRequest) -> Receipt:
        fee = self._fee(req)
        self.sent += 1
        return Receipt(id=str(uuid.uuid4()), amount=req.amount + fee)

    def _fee(self, req: PaymentRequest):
        return req.amount * FEE_RATE

    def refund(self, receipt_id: str) -> bool:
        return bool(receipt_id)

    def health(self) -> str:
        return "ok"
