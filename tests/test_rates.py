"""Тесты получения и форматирования курса USDT/THB."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_format_usdt_thb_success():
    """Проверяем форматирование при успешном ответе API."""
    from taskbot.rates import format_usdt_thb

    mock_data = {
        "symbol": "USDT_THB",
        "last": "31.07",
        "high_24_hr": "31.20",
        "low_24_hr": "30.90",
        "percent_change": "-0.15",
        "base_volume": "1234567.89",
        "quote_volume": "38400000.00",
        "highest_bid": "31.06",
        "lowest_ask": "31.08",
    }

    with patch("taskbot.rates.fetch_bitkub_v3", new=AsyncMock(return_value=mock_data)):
        result = await format_usdt_thb()

    assert "31.07" in result
    assert "USDT" in result
    assert "THB" in result
    assert "-1.6%" in result
    assert "-2%" in result
    assert "-5%" in result


@pytest.mark.asyncio
async def test_format_usdt_thb_calculates_discounts():
    """Проверяем корректность расчёта скидок."""
    from taskbot.rates import format_usdt_thb

    mock_data = {"last": "100.00"}

    with patch("taskbot.rates.fetch_bitkub_v3", new=AsyncMock(return_value=mock_data)):
        result = await format_usdt_thb()

    # -1.6% от 100 = 98.4
    assert "98.4" in result
    # -2% от 100 = 98.0
    assert "98.0" in result
    # -5% от 100 = 95.0
    assert "95.0" in result


@pytest.mark.asyncio
async def test_format_usdt_thb_api_error():
    """При ошибке API возвращается сообщение об ошибке."""
    from taskbot.rates import format_usdt_thb

    with patch("taskbot.rates.fetch_bitkub_v3", new=AsyncMock(return_value=None)):
        result = await format_usdt_thb()

    assert "⚠️" in result or "Не удалось" in result


@pytest.mark.asyncio
async def test_fetch_bitkub_v3_finds_symbol():
    """fetch_bitkub_v3 возвращает нужный символ из списка."""
    from taskbot.rates import fetch_bitkub_v3

    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"symbol": "BTC_THB", "last": "100"},
        {"symbol": "USDT_THB", "last": "31.07"},
        {"symbol": "ETH_THB", "last": "50"},
    ]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_bitkub_v3("USDT_THB")

    assert result is not None
    assert result["last"] == "31.07"


@pytest.mark.asyncio
async def test_fetch_bitkub_v3_symbol_not_found():
    """fetch_bitkub_v3 возвращает None если символ не найден."""
    from taskbot.rates import fetch_bitkub_v3

    mock_response = MagicMock()
    mock_response.json.return_value = [{"symbol": "BTC_THB", "last": "100"}]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await fetch_bitkub_v3("USDT_THB")

    assert result is None
