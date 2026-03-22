from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.i18n import t


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang:uk")],
        [InlineKeyboardButton("🇵🇱 Polski", callback_data="lang:pl")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")],
    ])


def role_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "roles.director"), callback_data="role:director")],
        [InlineKeyboardButton(t(lang, "roles.join"), callback_data="role:join")],
    ])


def main_menu_keyboard(lang: str, role: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(t(lang, "menu.record_work"), callback_data="menu:work")],
        [InlineKeyboardButton(t(lang, "menu.reports"), callback_data="menu:reports")],
    ]
    if role in ("director", "brigadier"):
        buttons.append([InlineKeyboardButton(t(lang, "menu.brigades"), callback_data="menu:brigades")])
        buttons.append([InlineKeyboardButton(t(lang, "menu.projects"), callback_data="menu:projects")])
    if role == "director":
        buttons.append([InlineKeyboardButton(t(lang, "menu.rates"), callback_data="menu:rates")])
        buttons.append([InlineKeyboardButton(t(lang, "menu.work_types"), callback_data="menu:work_types")])
    buttons.append([InlineKeyboardButton(t(lang, "menu.settings"), callback_data="menu:settings")])
    return InlineKeyboardMarkup(buttons)


def back_button(lang: str, callback: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.back"), callback_data=callback)]
    ])


def confirm_cancel_keyboard(lang: str, confirm_cb: str, cancel_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(lang, "btn.confirm"), callback_data=confirm_cb),
            InlineKeyboardButton(t(lang, "btn.cancel"), callback_data=cancel_cb),
        ]
    ])


def items_keyboard(items: list[tuple[str, str]], lang: str, back_cb: str = "menu:main",
                    add_cb: str | None = None) -> InlineKeyboardMarkup:
    """Generic keyboard from list of (label, callback_data) tuples."""
    buttons = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in items]
    if add_cb:
        buttons.append([InlineKeyboardButton(t(lang, "btn.add_new"), callback_data=add_cb)])
    buttons.append([InlineKeyboardButton(t(lang, "btn.back"), callback_data=back_cb)])
    return InlineKeyboardMarkup(buttons)


def today_or_other_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "work.today"), callback_data="date:today")],
        [InlineKeyboardButton(t(lang, "work.other_date"), callback_data="date:other")],
    ])


def skip_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn.skip"), callback_data="skip")]
    ])
