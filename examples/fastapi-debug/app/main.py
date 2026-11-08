"""Disposable payment API used to exercise debugealo's Python attach workflow."""

import json
import logging
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.payments import PaymentDeclined, PaymentError, process_payment


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'level': record.levelname, 'event': record.getMessage(),
                           **getattr(record, 'fields', {})})


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger = logging.getLogger('payments')
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

app = FastAPI(title='debugealo FastAPI example')


class PaymentRequest(BaseModel):
    amount_cents: int
    currency: str
    card_token: str


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/payments')
def create_payment(request: PaymentRequest):
    logger.info('payment.received', extra={'fields': {
        'amount_cents': request.amount_cents, 'currency': request.currency}})
    try:
        settlement = process_payment(request.model_dump())
    except PaymentDeclined as error:
        logger.warning('payment.declined', extra={'fields': {'reason': str(error)}})
        raise HTTPException(status_code=402, detail=str(error)) from None
    except PaymentError as error:
        logger.warning('payment.rejected', extra={'fields': {'reason': str(error)}})
        raise HTTPException(status_code=422, detail=str(error)) from None
    logger.info('payment.captured', extra={'fields': settlement})
    return settlement


@app.get('/debug/error')
def debug_error():
    """Fail on purpose so an unhandled exception is reproducible."""
    logger.error('debug.error.requested')
    raise RuntimeError('Intentional failure from /debug/error')
