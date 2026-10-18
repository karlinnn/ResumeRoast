"""Razorpay payment helpers."""
import hashlib
import hmac
import logging
import os

import razorpay

logger = logging.getLogger(__name__)

_client: razorpay.Client | None = None


def _get_client() -> razorpay.Client:
    global _client
    if _client is None:
        key_id = os.environ.get("RAZORPAY_KEY_ID")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        if not key_id or not key_secret:
            raise RuntimeError("Razorpay env vars not set.")
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


def _price_paise() -> int:
    return int(os.environ.get("UNLOCK_PRICE_PAISE", "3000"))


def create_order(report_id: str) -> dict:
    """Create a Razorpay order and return {order_id, amount, currency, key_id}."""
    client = _get_client()
    amount = _price_paise()
    order = client.order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": report_id[:40],
        "notes": {"report_id": report_id},
    })
    logger.info("razorpay_order_created order_id=%s report_id=%s", order["id"], report_id)
    return {
        "order_id": order["id"],
        "amount": amount,
        "currency": "INR",
        "key_id": os.environ.get("RAZORPAY_KEY_ID", ""),
    }


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Return True if the webhook signature is valid.

    Returns False immediately (without computing) if secret is not configured,
    so an empty secret never accidentally validates any request.
    """
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning("verify_webhook_signature: RAZORPAY_WEBHOOK_SECRET not set")
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify Razorpay payment signature from checkout callback.

    Returns False immediately if secret is not configured.
    """
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not secret:
        logger.warning("verify_payment_signature: RAZORPAY_KEY_SECRET not set")
        return False
    msg = f"{order_id}|{payment_id}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
