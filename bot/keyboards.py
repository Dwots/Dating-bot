from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Моя анкета", callback_data="my_profile")],
        [InlineKeyboardButton(text="💕 Смотреть анкеты", callback_data="view_profiles")],
        [InlineKeyboardButton(text="❤️ Мои мэтчи", callback_data="my_matches")],
        [InlineKeyboardButton(text="⚙️ Настройки поиска", callback_data="search_settings")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="referral")],  # ← новая
    ])


def profile_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_profile")],
        [InlineKeyboardButton(text="📷 Фотографии", callback_data="profile_photos")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
    ])


def profile_photos_kb(photo_count: int, index: int) -> InlineKeyboardMarkup:
    buttons = []
    if photo_count > 1:
        buttons.append([
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"profile_photo_{(index - 1) % photo_count}",
            ),
            InlineKeyboardButton(
                text=f"{index + 1}/{photo_count}",
                callback_data="noop",
            ),
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"profile_photo_{(index + 1) % photo_count}",
            ),
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ К анкете", callback_data="my_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)




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
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="search_settings")],
    ])


def view_profile_kb(photo_count: int = 0, photo_index: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    if photo_count > 1:
        buttons.append([
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"view_photo_{(photo_index - 1) % photo_count}",
            ),
            InlineKeyboardButton(
                text=f"{photo_index + 1}/{photo_count}",
                callback_data="noop",
            ),
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"view_photo_{(photo_index + 1) % photo_count}",
            ),
        ])

    buttons.append([
        InlineKeyboardButton(text="❤️ Лайк", callback_data="like"),
        InlineKeyboardButton(text="👎 Пропустить", callback_data="skip"),
    ])
    buttons.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb(callback_data: str = "back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)],
    ])


def photo_management_kb(photos) -> InlineKeyboardMarkup:
    buttons = []
    for index, photo in enumerate(photos, 1):
        status_value = getattr(getattr(photo, "status", None), "value", getattr(photo, "status", ""))
        status_icon = "✅" if status_value == "approved" else "⏳" if status_value == "pending" else "❌"
        label = f"{status_icon} Удалить {index}"
        if photo.is_primary and status_value == "approved":
            label += " ⭐"

        row = [InlineKeyboardButton(text=label, callback_data=f"delete_photo_{photo.id}")]
        if status_value == "approved" and not photo.is_primary:
            row.append(
                InlineKeyboardButton(
                    text=f"⭐ Главное {index}",
                    callback_data=f"set_primary_photo_{photo.id}",
                )
            )
        buttons.append(row)

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def matches_kb(matches) -> InlineKeyboardMarkup:
    buttons = []
    for index, match in enumerate(matches, 1):
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 Удалить мэтч {index}",
                callback_data=f"delete_match_{match.id}",
            )
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def search_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚧ Кого ищу", callback_data="edit_search_gender")],
        [InlineKeyboardButton(text="🎂 Возраст от", callback_data="edit_min_age")],
        [InlineKeyboardButton(text="🎂 Возраст до", callback_data="edit_max_age")],
        [InlineKeyboardButton(text="🏙 Город поиска", callback_data="edit_search_city")],
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
        [InlineKeyboardButton(text="📷 Фото", callback_data="edit_photo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")],
    ])
