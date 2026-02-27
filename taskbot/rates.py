"""Получение курсов с биржи Bitkub через публичный API."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BITKUB_V3_TICKER_URL = "https://api.bitkub.com/api/v3/market/ticker"
_TIMEOUT = 8.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 1.5  # секунды между попытками


async def fetch_bitkub_v3(sym: str) -> Optional[dict]:
    """Возвращает dict для нужного символа из v3 API или None при ошибке.

    При сетевых ошибках делает до _RETRY_ATTEMPTS попыток с экспоненциальным backoff.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_BITKUB_V3_TICKER_URL)
                resp.raise_for_status()
                items = resp.json()
                for item in items:
                    if item.get("symbol") == sym:
                        return item
            return None
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            wait = _RETRY_BACKOFF * (2 ** attempt)
            logger.warning("fetch_bitkub_v3 attempt %d/%d failed, retry in %.1fs", attempt + 1, _RETRY_ATTEMPTS, wait)
            if attempt < _RETRY_ATTEMPTS - 1:
                await asyncio.sleep(wait)
        except Exception as exc:
            logger.warning("fetch_bitkub_v3 failed sym=%s", sym, exc_info=True)
            return None

    logger.warning("fetch_bitkub_v3 all retries exhausted sym=%s: %s", sym, last_exc)
    return None


async def format_usdt_thb() -> str:
    """Возвращает готовую строку с курсом USDT/THB для отображения в панели."""
    data = await fetch_bitkub_v3("USDT_THB")
    if data is None:
        return "💱 USDT/THB\n⚠️ Не удалось получить данные. Попробуй позже."

    last = data.get("last", "—")

    price = float(last)
    p16 = round(price * (1 - 0.016), 2)
    p20 = round(price * (1 - 0.02), 2)
    p50 = round(price * (1 - 0.05), 2)

    lines = [
        "💱 USDT / THB  (Bitkub)",
        "",
        f"Курс:   {last} ฿",
        "",
        f"-1.6%   {p16} ฿",
        f"-2%     {p20} ฿",
        f"-5%     {p50} ฿",
    ]
    return "\n".join(lines)
