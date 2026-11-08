"""Payment rules kept free of web concerns so breakpoints show plain values."""

SUPPORTED_CURRENCIES = {'EUR', 'USD'}
DECLINED_CARD = 'tok_declined'
FEE_PERCENT = 3


class PaymentError(ValueError):
    """A payment rule rejected the request."""


class PaymentDeclined(PaymentError):
    """The card issuer refused an otherwise valid payment."""


def process_payment(payment):
    """Validate one payment mapping and return its settlement."""
    amount = payment['amount_cents']
    currency = payment['currency']
    if amount <= 0:
        raise PaymentError('amount_cents must be positive')
    if currency not in SUPPORTED_CURRENCIES:
        raise PaymentError(f'unsupported currency: {currency}')
    if payment['card_token'] == DECLINED_CARD:
        raise PaymentDeclined('card declined')
    fee_cents = amount * FEE_PERCENT // 100
    net_cents = amount - fee_cents
    return {'status': 'captured', 'currency': currency,
            'amount_cents': amount, 'fee_cents': fee_cents, 'net_cents': net_cents}
