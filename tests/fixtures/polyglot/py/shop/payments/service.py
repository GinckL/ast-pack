import logging

from ..models import PaymentRequest, Receipt
from .gateway import Gateway
from .validation import normalize_tags, validate_request

log = logging.getLogger(__name__)


def process_payment(req: PaymentRequest, gateway: Gateway) -> Receipt:
    """Validate and charge a payment request."""
    validate_request(req)
    req.tags = normalize_tags(req.tags)
    receipt = gateway.charge(req)
    log.info("charged %s", receipt.id)
    return receipt


def refund_payment(receipt_id: str, gateway: Gateway) -> bool:
    return gateway.refund(receipt_id)


def daily_report(receipts: list[Receipt]) -> str:
    total = sum(r.amount for r in receipts)
    lines = [f"{r.id}: {r.amount}" for r in receipts]
    lines.append(f"total: {total}")
    return "\n".join(lines)
