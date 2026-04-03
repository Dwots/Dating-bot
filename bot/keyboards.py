from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Моя анкета", callback_data="my_profile")],
        [InlineKeyboardButton(text="💕 Смотреть анкеты", callback_data="view_profiles")],
        [InlineKeyboardButton(text="❤️ Мои мэтчи", callback_data="my_matches")],
        [InlineKeyboardButton(text="⚙️ Настройки поиска", callback_data="search_settings")],
    ])


def profile_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_profile")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])


def edit_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📛 Имя", callback_data="edit_name")],
        [InlineKeyboardButton(text="🎂 Возраст", callback_data="edit_age")],
        [InlineKeyboardButton(text="⚧ Пол", callback_data="edit_gender")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="edit_city")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="edit_description")],
        [InlineKeyboardButton(text="💡 Интересы", callback_data="edit_interests")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")],
    ])


def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужской", callback_data="set_gender_male")],
        [InlineKeyboardButton(text="👩 Женский", callback_data="set_gender_female")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_profile")],
    ])


def search_gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужчин", callback_data="search_male")],
        [InlineKeyboardButton(text="👩 Женщин", callback_data="search_female")],
        [InlineKeyboardButton(text="👥 Всех", callback_data="search_all")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])


def view_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❤️ Лайк", callback_data="like"),
            InlineKeyboardButton(text="👎 Пропустить", callback_data="skip"),
        ],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back")],
    ])
