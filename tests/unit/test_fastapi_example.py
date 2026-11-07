"""Static contract and payment rules of the FastAPI debug example."""

import importlib.util
import re
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parents[2] / 'examples' / 'fastapi-debug'


@pytest.fixture
def payments():
    spec = importlib.util.spec_from_file_location(
        'fastapi_example_payments', EXAMPLE / 'app' / 'payments.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(**changes):
    return {'amount_cents': 1000, 'currency': 'EUR', 'card_token': 'tok_ok', **changes}


def test_process_payment_returns_settlement(payments):
    assert payments.process_payment(request()) == {
        'status': 'captured', 'currency': 'EUR', 'amount_cents': 1000,
        'fee_cents': 30, 'net_cents': 970}


@pytest.mark.parametrize(('changes', 'message'), [
    ({'amount_cents': 0}, 'amount_cents must be positive'),
    ({'currency': 'XXX'}, 'unsupported currency: XXX'),
])
def test_process_payment_rejects_invalid_rules(payments, changes, message):
    with pytest.raises(payments.PaymentError, match=message):
        payments.process_payment(request(**changes))


def test_process_payment_declines_known_card(payments):
    with pytest.raises(payments.PaymentDeclined, match='card declined'):
        payments.process_payment(request(card_token=payments.DECLINED_CARD))


def test_compose_publishes_ports_on_host_loopback_only():
    content = (EXAMPLE / 'compose.yaml').read_text(encoding='utf-8')
    ports = re.findall(r'(?m)^\s+- "(.+:\d+)"$', content)
    assert len(ports) == 2
    assert all(port.startswith('127.0.0.1:') for port in ports)


def test_image_runs_one_debuggable_worker_without_autoreload():
    content = (EXAMPLE / 'Dockerfile').read_text(encoding='utf-8')
    command = next(line for line in content.splitlines() if line.startswith('CMD'))
    assert '"debugpy", "--listen", "0.0.0.0:5678"' in command
    assert '"--workers", "1"' in command
    assert '--reload' not in command
    assert '--wait-for-client' not in command


def test_app_declares_the_specified_routes():
    content = (EXAMPLE / 'app' / 'main.py').read_text(encoding='utf-8')
    for route in ("@app.get('/health')", "@app.post('/payments')", "@app.get('/debug/error')"):
        assert route in content
