import json
import os
from functools import lru_cache

LOCALES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "locales")


@lru_cache(maxsize=5)
def _load_locale(lang: str) -> dict:
    path = os.path.join(LOCALES_DIR, f"{lang}.json")
    if not os.path.exists(path):
        path = os.path.join(LOCALES_DIR, "uk.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def t(lang: str, key: str, **kwargs) -> str:
    """Get translated text. Supports nested keys with dots: 'menu.record_work'"""
    data = _load_locale(lang)
    parts = key.split(".")
    val = data
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            val = None
            break
    if val is None:
        # Fallback to Ukrainian
        if lang != "uk":
            return t("uk", key, **kwargs)
        return f"[{key}]"
    if kwargs:
        try:
            return str(val).format(**kwargs)
        except (KeyError, IndexError):
            return str(val)
    return str(val)


UNIT_LABELS = {
    "m2": {"uk": "м²", "pl": "m²", "ru": "м²"},
    "mp": {"uk": "мп", "pl": "mb", "ru": "мп"},
    "h":  {"uk": "год", "pl": "godz", "ru": "ч"},
}


def unit_label(unit: str, lang: str) -> str:
    return UNIT_LABELS.get(unit, {}).get(lang, unit)


CURRENCY_SYMBOLS = {"PLN": "zł", "EUR": "€", "UAH": "₴"}


def currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, currency)
