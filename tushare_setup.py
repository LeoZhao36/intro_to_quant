"""
Tushare Pro client setup.

Loads token from .env at project root, exposes an authenticated
pro_api object as a module-level singleton.

Usage:
    from tushare_client import pro
    df = pro.daily_basic(trade_date='20241231')
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import tushare as ts


def _load_token() -> str:
    """Walk up from this file to find .env at project root."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            break
        current = current.parent
    else:
        raise FileNotFoundError(
            "Could not find .env file. Expected at project root."
        )

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN not found in .env. Check that .env contains "
            "TUSHARE_TOKEN=your_actual_token"
        )
    return token


# Created once on first import; reused across all callers
pro = ts.pro_api(_load_token())