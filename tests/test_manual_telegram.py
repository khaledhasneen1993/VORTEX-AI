import pytest

from vortex.manual_telegram import ManualTelegram, format_card


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('VORTEX_TELEGRAM_TOKEN', '123:secret')
    monkeypatch.setenv('VORTEX_TELEGRAM_CHAT_ID', '123456')
    calls = []
    monkeypatch.setattr('vortex.manual_telegram.notify', lambda text: calls.append(text) or True)
    card = {'created_ms': 300005, 'expires_ms': 389999, 'leverage': 5,
            'quantity': None, 'margin_usdt': None,
            'signal': {'symbol': 'BTCUSDT', 'side': 'LONG', 'ts': 0,
                       'entry': 100, 'stop': 90, 'target': 130, 'score': 7,
                       'votes': ['trend', 'breakout']}}
    return tmp_path / 'state.sqlite3', card, calls


def test_success_is_deduplicated_across_restarts(setup):
    path, card, calls = setup
    sender = ManualTelegram(path)
    assert sender.send(card, 300006) == 'sent'
    sender.close()
    sender = ManualTelegram(path)
    assert sender.send(card, 300007) == 'duplicate'
    assert len(calls) == 1
    sender.close()


@pytest.mark.parametrize('now', [300004, 389999, 400000])
def test_expired_and_future_cards_never_send(setup, now):
    path, card, calls = setup
    sender = ManualTelegram(path)
    assert sender.send(card, now) == 'expired'
    assert not calls
    sender.close()


def test_uncertain_send_is_not_replayed(setup, monkeypatch):
    path, card, calls = setup
    monkeypatch.setattr('vortex.manual_telegram.notify', lambda text: False)
    sender = ManualTelegram(path)
    assert sender.send(card, 300006) == 'failed_or_uncertain'
    sender.close()
    sender = ManualTelegram(path)
    assert sender.send(card, 300007) == 'duplicate'
    sender.close()


def test_message_is_manual_and_amount_unset(setup):
    _, card, _ = setup
    text = format_card(card)
    assert 'BTCUSDT | LONG' in text
    assert 'غير محددين' in text
    assert 'لا تنفيذ تلقائي' in text
    assert 'UTC' in text
    assert 'secret' not in text


def test_missing_credentials_fail_before_scan(tmp_path, monkeypatch):
    monkeypatch.delenv('VORTEX_TELEGRAM_TOKEN', raising=False)
    with pytest.raises(ValueError, match='TOKEN'):
        ManualTelegram(tmp_path / 'state.sqlite3')
