import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy.ext.asyncio import AsyncSession
from rabbitmq import RabbitMQClient
from minio_client import MinioClient
import redis.asyncio as aioredis
from surreal import SurrealClient
from logger import setup_logging
from metrics import REQUESTS_TOTAL, CACHE_HITS, CACHE_MISSES, REQUEST_DURATION
import time

logger = setup_logging("handlers")

from database import User, Gender
from database import Photo
from matching_service import MatchingService
from profile_service import ProfileService
from keyboards import (
    main_menu_kb, profile_menu_kb, edit_profile_kb, gender_kb,
    search_gender_kb, view_profile_kb, back_kb, search_settings_kb,
    photo_management_kb, matches_kb, profile_photos_kb
)

router = Router()
PHOTO_UPLOAD_LOCKS: dict[int, asyncio.Lock] = {}


# ─── FSM состояния ────────────────────────────────────────────────────────────

class ProfileForm(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    description = State()
    interests = State()
    photo = State()


class PreferenceForm(StatesGroup):
    # каждое поле — отдельный State
    gender = State()
    min_age = State()
    max_age = State()
    city = State()


# ─── Вспомогательные функции ──────────────────────────────────────────────────

async def replace_message_text(callback: CallbackQuery, text: str, reply_markup=None):
    """
    Inline-кнопки могут висеть как на обычном сообщении, так и на фото с caption.
    Telegram не даёт заменить photo-message через edit_text, поэтому в этом
    случае удаляем старое сообщение и отправляем новое.
    """
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=reply_markup)

def format_telegram_contact(user: User | None) -> str:
    if user and user.username:
        return f"@{user.username}"
    return "тег не указан"


async def get_photo_input(photo: Photo, minio: MinioClient):
    if photo.telegram_file_id:
        return photo.telegram_file_id

    loop = asyncio.get_event_loop()
    photo_bytes = await loop.run_in_executor(
        None, minio.get_photo_bytes, photo.s3_key
    )
    return BufferedInputFile(photo_bytes, filename="photo.jpg")


def get_photo_upload_lock(user_id: int) -> asyncio.Lock:
    lock = PHOTO_UPLOAD_LOCKS.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        PHOTO_UPLOAD_LOCKS[user_id] = lock
    return lock


async def clear_profile_search_cache(
    telegram_id: int,
    session: AsyncSession,
    redis: aioredis.Redis,
):
    current_user = await ProfileService(session).get_user_by_telegram_id(telegram_id)
    if current_user:
        await redis.delete(f"{MatchingService.CACHE_PREFIX}:{current_user.id}")


# ─── /start — с поддержкой реферальной ссылки ────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    REQUESTS_TOTAL.labels(handler="start").inc()

    profile_service = ProfileService(session)
    user = await profile_service.get_or_create_user(
        message.from_user.id,
        message.from_user.username,
    )

    # Проверяем бан
    if user.is_banned:
        await message.answer("🚫 Ваш аккаунт заблокирован.")
        return

    logger.info("user_started", user_id=user.telegram_id, username=user.username)

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        await profile_service.process_referral(user, args[1])

    await message.answer(
        f"👋 Привет! Добро пожаловать в Dating Bot!\n\n"
        f"Твой ID: {user.telegram_id}\n\n"
        "Заполни анкету, чтобы начать знакомиться!",
        reply_markup=main_menu_kb()
    )
    

# ─── Главное меню ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    await replace_message_text(
        callback,
        "📱 Главное меню\n\nВыбери действие:",
        main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


# ─── Профиль ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession):
    profile_service = ProfileService(session)
    profile = await profile_service.get_profile_by_telegram_id(callback.from_user.id)

    if profile:
        gender_text = "Мужской" if profile.gender == Gender.MALE else "Женский" if profile.gender == Gender.FEMALE else "Не указан"
        text = (
            "👤 Твоя анкета:\n\n"
            f"📛 Имя: {profile.name or 'Не указано'}\n"
            f"🎂 Возраст: {profile.age or 'Не указан'}\n"
            f"⚧ Пол: {gender_text}\n"
            f"🏙 Город: {profile.city or 'Не указан'}\n"
            f"📝 О себе: {profile.description or 'Не указано'}\n"
            f"💡 Интересы: {profile.interests or 'Не указаны'}\n\n"
            f"📊 Заполненность: {int(profile.completeness * 100)}%"
        )
    else:
        text = "Анкета не найдена. Начни с /start"

    await replace_message_text(callback, text, profile_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "profile_photos")
async def show_profile_photos(
    callback: CallbackQuery,
    session: AsyncSession,
    minio: MinioClient,
):
    await show_profile_photo(callback, session, minio, 0)


@router.callback_query(F.data.startswith("profile_photo_"))
async def paginate_profile_photos(
    callback: CallbackQuery,
    session: AsyncSession,
    minio: MinioClient,
):
    try:
        index = int(callback.data.replace("profile_photo_", ""))
    except ValueError:
        await callback.answer("Некорректное фото", show_alert=True)
        return

    await show_profile_photo(callback, session, minio, index)


async def show_profile_photo(
    callback: CallbackQuery,
    session: AsyncSession,
    minio: MinioClient,
    index: int,
):
    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    photos = await profile_service.get_approved_photos(current_user.id)
    if not photos:
        await replace_message_text(
            callback,
            "📷 У тебя пока нет одобренных фото.\n\n"
            "Загрузи фото в редактировании анкеты и дождись проверки.",
            profile_menu_kb(),
        )
        await callback.answer()
        return

    index = index % len(photos)
    photo = photos[index]
    photo_input = await get_photo_input(photo, minio)
    caption = f"📷 Фото {index + 1}/{len(photos)}"

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer_photo(
        photo=photo_input,
        caption=caption,
        reply_markup=profile_photos_kb(len(photos), index),
    )
    await callback.answer()


@router.callback_query(F.data == "edit_profile")
async def edit_profile_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await replace_message_text(
        callback,
        "✏️ Что хочешь изменить?",
        edit_profile_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "edit_name")
async def edit_name(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.name)
    await callback.message.edit_text("Введи своё имя:", reply_markup=back_kb("edit_profile"))
    await callback.answer()


@router.message(ProfileForm.name)
async def process_name(message: Message, state: FSMContext, session: AsyncSession):
    await ProfileService(session).update_profile_field(
        message.from_user.id,
        "name",
        message.text,
    )
    await state.clear()
    await message.answer("✅ Имя сохранено. Что изменить дальше?", reply_markup=edit_profile_kb())


@router.callback_query(F.data == "edit_age")
async def edit_age(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.age)
    await callback.message.edit_text("Введи свой возраст (18-100):", reply_markup=back_kb("edit_profile"))
    await callback.answer()


@router.message(ProfileForm.age)
async def process_age(message: Message, state: FSMContext, session: AsyncSession):
    try:
        age = int(message.text)
        if 18 <= age <= 100:
            await ProfileService(session).update_profile_field(
                message.from_user.id,
                "age",
                age,
            )
            await state.clear()
            await message.answer("✅ Возраст сохранён. Что изменить дальше?", reply_markup=edit_profile_kb())
        else:
            await message.answer("❌ Возраст должен быть от 18 до 100")
    except ValueError:
        await message.answer("❌ Введи число")


@router.callback_query(F.data == "edit_gender")
async def edit_gender(callback: CallbackQuery):
    await callback.message.edit_text("Выбери свой пол:", reply_markup=gender_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("set_gender_"))
async def process_gender(callback: CallbackQuery, session: AsyncSession):
    gender = Gender.MALE if callback.data == "set_gender_male" else Gender.FEMALE
    await ProfileService(session).update_profile_field(
        callback.from_user.id,
        "gender",
        gender,
    )
    await callback.message.edit_text("✅ Пол сохранён. Что изменить дальше?", reply_markup=edit_profile_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_city")
async def edit_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.city)
    await callback.message.edit_text("Введи свой город:", reply_markup=back_kb("edit_profile"))
    await callback.answer()


@router.message(ProfileForm.city)
async def process_city(message: Message, state: FSMContext, session: AsyncSession):
    await ProfileService(session).update_profile_field(
        message.from_user.id,
        "city",
        message.text,
    )
    await state.clear()
    await message.answer("✅ Город сохранён. Что изменить дальше?", reply_markup=edit_profile_kb())


@router.callback_query(F.data == "edit_description")
async def edit_description(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.description)
    await callback.message.edit_text("Расскажи о себе:", reply_markup=back_kb("edit_profile"))
    await callback.answer()


@router.message(ProfileForm.description)
async def process_description(message: Message, state: FSMContext, session: AsyncSession):
    await ProfileService(session).update_profile_field(
        message.from_user.id,
        "description",
        message.text,
    )
    await state.clear()
    await message.answer("✅ Описание сохранено. Что изменить дальше?", reply_markup=edit_profile_kb())


@router.callback_query(F.data == "edit_interests")
async def edit_interests(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.interests)
    await callback.message.edit_text("Укажи свои интересы (через запятую):", reply_markup=back_kb("edit_profile"))
    await callback.answer()


@router.message(ProfileForm.interests)
async def process_interests(message: Message, state: FSMContext, session: AsyncSession):
    await ProfileService(session).update_profile_field(
        message.from_user.id,
        "interests",
        message.text,
    )
    await state.clear()
    await message.answer("✅ Интересы сохранены. Что изменить дальше?", reply_markup=edit_profile_kb())


# ─── Фото ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "edit_photo")
async def edit_photo(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(ProfileForm.photo)

    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    photos = await profile_service.get_user_photos(current_user.id) if current_user else []
    approved_count, pending_count = profile_service.get_photo_counts(photos)

    await replace_message_text(
        callback,
        "📷 Фото профиля\n\n"
        f"Одобрено: {approved_count}/5\n"
        f"На проверке: {pending_count}\n\n"
        "Можно отправить одно фото или альбом из нескольких фото. "
        "Новые фото не показываются в профиле, пока админ их не одобрит.",
        photo_management_kb(photos)
    )
    await callback.answer()


@router.message(ProfileForm.photo, F.photo)
async def process_photo(message: Message, state: FSMContext, session: AsyncSession, minio: MinioClient):
    """
    F.photo — фильтр aiogram: срабатывает только если сообщение содержит фото

    message.photo — это список объектов PhotoSize в разных разрешениях
    [-1] — берём последний элемент = самое большое разрешение
    """
    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(message.from_user.id)

    if not current_user:
        await message.answer("Сначала зарегистрируйся с /start")
        await state.clear()
        return

    async with get_photo_upload_lock(current_user.id):
        await process_photo_upload(message, session, minio, current_user, profile_service)


async def process_photo_upload(
    message: Message,
    session: AsyncSession,
    minio: MinioClient,
    current_user: User,
    profile_service: ProfileService,
):

    existing_photos = await profile_service.get_user_photos(current_user.id)
    active_photos_count = sum(
        1
        for photo in existing_photos
        if getattr(photo.status, "value", photo.status) != "rejected"
    )

    if active_photos_count >= profile_service.MAX_ACTIVE_PHOTOS:
        await message.answer(
            "❌ Максимум 5 фото. Удали старое чтобы добавить новое.",
            reply_markup=photo_management_kb(existing_photos)
        )
        return

    photo = message.photo[-1]
    try:
        file = await message.bot.get_file(photo.file_id)
        file_bytes_io = await message.bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()
    except TelegramNetworkError as exc:
        logger.warning(
            "telegram_photo_download_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        await message.answer(
            "❌ Не удалось скачать фото из Telegram. Попробуй отправить его ещё раз.",
            reply_markup=photo_management_kb(existing_photos),
        )
        return

    loop = asyncio.get_event_loop()
    try:
        s3_key = await loop.run_in_executor(
            None,
            minio.upload_photo,
            file_bytes,
            current_user.telegram_id,
        )
    except Exception as exc:
        logger.warning(
            "minio_photo_upload_failed",
            user_id=current_user.id,
            error=str(exc),
        )
        await message.answer(
            "❌ Не удалось сохранить фото. Попробуй отправить его ещё раз.",
            reply_markup=photo_management_kb(existing_photos),
        )
        return

    added, photos = await profile_service.add_pending_photo(
        current_user.id,
        s3_key,
        photo.file_id,
    )
    if not added:
        try:
            await loop.run_in_executor(None, minio.delete_photo, s3_key)
        except Exception as exc:
            logger.warning(
                "minio_orphan_photo_delete_failed",
                user_id=current_user.id,
                s3_key=s3_key,
                error=str(exc),
            )

        await message.answer(
            "❌ Максимум 5 фото. Удали старое чтобы добавить новое.",
            reply_markup=photo_management_kb(photos),
        )
        return

    photos = await profile_service.get_user_photos(current_user.id)
    approved_count, pending_count = profile_service.get_photo_counts(photos)

    await message.answer(
        "⏳ Фото загружено и отправлено на проверку.\n"
        f"Одобрено: {approved_count}/5\n"
        f"На проверке: {pending_count}\n\n"
        "Пока фото не одобрят, оно не появится в профиле.",
        reply_markup=photo_management_kb(photos)
    )


@router.callback_query(F.data.startswith("delete_photo_"))
async def delete_photo(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    minio: MinioClient,
):
    await state.set_state(ProfileForm.photo)

    try:
        photo_id = int(callback.data.replace("delete_photo_", ""))
    except ValueError:
        await callback.answer("Некорректное фото", show_alert=True)
        return

    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    deleted, s3_key, photos = await profile_service.delete_photo(current_user.id, photo_id)
    if not deleted:
        await replace_message_text(
            callback,
            f"📷 Фото профиля\n\nЗагружено: {len(photos)}/5",
            photo_management_kb(photos)
        )
        await callback.answer("Фото уже удалено")
        return

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, minio.delete_photo, s3_key)
    except Exception as exc:
        logger.warning("minio_photo_delete_failed", photo_id=photo_id, error=str(exc))

    approved_count, pending_count = profile_service.get_photo_counts(photos)

    await replace_message_text(
        callback,
        "🗑 Фото удалено.\n\n"
        f"Одобрено: {approved_count}/5\n"
        f"На проверке: {pending_count}\n\n"
        "Можно отправить ещё фото или удалить лишние ниже.",
        photo_management_kb(photos)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_primary_photo_"))
async def set_primary_photo(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    await state.set_state(ProfileForm.photo)

    try:
        photo_id = int(callback.data.replace("set_primary_photo_", ""))
    except ValueError:
        await callback.answer("Некорректное фото", show_alert=True)
        return

    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    updated, photos = await profile_service.set_primary_photo(current_user.id, photo_id)
    approved_count, pending_count = profile_service.get_photo_counts(photos)
    if not updated:
        await replace_message_text(
            callback,
            "📷 Фото профиля\n\n"
            f"Одобрено: {approved_count}/5\n"
            f"На проверке: {pending_count}\n\n"
            "Главным можно сделать только одобренное фото.",
            photo_management_kb(photos),
        )
        await callback.answer("Фото недоступно", show_alert=True)
        return

    await replace_message_text(
        callback,
        "⭐ Главное фото обновлено.\n\n"
        f"Одобрено: {approved_count}/5\n"
        f"На проверке: {pending_count}\n\n"
        "Именно оно будет первым показываться в анкете.",
        photo_management_kb(photos),
    )
    await callback.answer()


@router.message(ProfileForm.photo)
async def process_photo_wrong(message: Message):
    """Если прислали не фото а что-то другое"""
    await message.answer(
        "❌ Пожалуйста, отправь именно фото (не файл, не документ)",
    )

# ─── Настройки поиска ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "search_settings")
async def search_settings(callback: CallbackQuery, session: AsyncSession):
    pref = await ProfileService(session).get_preference_by_telegram_id(
        callback.from_user.id
    )

    if pref:
        gender_text = (
            "👨 Мужчин" if pref.preferred_gender == Gender.MALE
            else "👩 Женщин" if pref.preferred_gender == Gender.FEMALE
            else "👥 Всех"
        )
        text = (
            "⚙️ Настройки поиска:\n\n"
            f"⚧ Ищу: {gender_text}\n"
            f"🎂 Возраст: {pref.min_age}–{pref.max_age}\n"
            f"🏙 Город: {pref.preferred_city or 'Любой'}\n\n"
            "Что хочешь изменить?"
        )
    else:
        text = "⚙️ Настройки поиска\n\nЧто хочешь изменить?"

    await callback.message.edit_text(text, reply_markup=search_settings_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_search_gender")
async def edit_search_gender(callback: CallbackQuery):
    await callback.message.edit_text(
        "Кого ищешь?",
        reply_markup=search_gender_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("search_"))
async def process_search_gender(
    callback: CallbackQuery,
    session: AsyncSession,
    redis: aioredis.Redis,
):
    """
    callback.data: "search_male" / "search_female" / "search_all"
    """
    # Не перехватываем search_settings — у него свой handler выше
    if callback.data == "search_settings":
        return

    gender_map = {
        "search_male": Gender.MALE,
        "search_female": Gender.FEMALE,
        "search_all": None,
    }
    preferred_gender = gender_map.get(callback.data)

    await ProfileService(session).update_preference_field(
        callback.from_user.id,
        "preferred_gender",
        preferred_gender,
    )
    await clear_profile_search_cache(callback.from_user.id, session, redis)

    await callback.message.edit_text("✅ Сохранено!", reply_markup=search_settings_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_min_age")
async def edit_min_age(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PreferenceForm.min_age)
    await callback.message.edit_text(
        "Введи минимальный возраст (18-99):",
        reply_markup=back_kb()
    )
    await callback.answer()


@router.message(PreferenceForm.min_age)
async def process_min_age(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    redis: aioredis.Redis,
):
    try:
        age = int(message.text)
        if 18 <= age <= 99:
            await ProfileService(session).update_preference_field(
                message.from_user.id,
                "min_age",
                age,
            )
            await clear_profile_search_cache(message.from_user.id, session, redis)
            await state.clear()
            await message.answer("✅ Минимальный возраст сохранён!", reply_markup=main_menu_kb())
        else:
            await message.answer("❌ Введи число от 18 до 99")
    except ValueError:
        await message.answer("❌ Введи число")


@router.callback_query(F.data == "edit_max_age")
async def edit_max_age(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PreferenceForm.max_age)
    await callback.message.edit_text(
        "Введи максимальный возраст (19-100):",
        reply_markup=back_kb()
    )
    await callback.answer()


@router.message(PreferenceForm.max_age)
async def process_max_age(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    redis: aioredis.Redis,
):
    try:
        age = int(message.text)
        if 19 <= age <= 100:
            await ProfileService(session).update_preference_field(
                message.from_user.id,
                "max_age",
                age,
            )
            await clear_profile_search_cache(message.from_user.id, session, redis)
            await state.clear()
            await message.answer("✅ Максимальный возраст сохранён!", reply_markup=main_menu_kb())
        else:
            await message.answer("❌ Введи число от 19 до 100")
    except ValueError:
        await message.answer("❌ Введи число")


@router.callback_query(F.data == "edit_search_city")
async def edit_search_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PreferenceForm.city)
    await callback.message.edit_text(
        'Введи город поиска\n(или напиши "любой" чтобы искать везде):',
        reply_markup=back_kb()
    )
    await callback.answer()


@router.message(PreferenceForm.city)
async def process_search_city(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    redis: aioredis.Redis,
):
    city_text = message.text.strip()
    preferred_city = None if city_text.lower() == "любой" else city_text
    await ProfileService(session).update_preference_field(
        message.from_user.id,
        "preferred_city",
        preferred_city,
    )
    await clear_profile_search_cache(message.from_user.id, session, redis)
    await state.clear()
    await message.answer("✅ Город поиска сохранён!", reply_markup=main_menu_kb())


# ─── Реферальная ссылка ───────────────────────────────────────────────────────

@router.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery, session: AsyncSession):
    """
    Генерируем ссылку вида: t.me/{bot_username}?start=ref_{telegram_id}
    Telegram сам передаст payload в /start команду
    """
    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    referrals_count = await profile_service.count_referrals(current_user.id)

    # Получаем username бота
    bot: Bot = callback.bot
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{callback.from_user.id}"

    text = (
        "👥 Реферальная программа\n\n"
        f"Приглашай друзей и повышай свой рейтинг!\n\n"
        f"Твоя ссылка:\n{ref_link}\n\n"
        f"Приглашено друзей: {referrals_count} 👤\n\n"
        "Каждый приглашённый друг увеличивает твой рейтинг в системе подбора!"
    )

    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


# ─── Просмотр анкет ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "view_profiles")
async def view_profiles(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    minio: MinioClient,
    rabbitmq: RabbitMQClient,
    redis: aioredis.Redis,
    surreal: SurrealClient,
):
    start_time = time.time()
    REQUESTS_TOTAL.labels(handler="view_profiles").inc()
    
    profile_service = ProfileService(session)
    matching_service = MatchingService(session, redis, surreal)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)

    if not current_user:
        await callback.message.edit_text("Сначала зарегистрируйся с /start")
        await callback.answer()
        return

    profile_data = await matching_service.get_next_profile(current_user)
    if matching_service.last_cache_status == "hit":
        CACHE_HITS.inc()
    else:
        CACHE_MISSES.inc()

    if not profile_data:
        await replace_message_text(
            callback,
            "😔 Пока нет подходящих анкет.\n\nПопробуй изменить настройки поиска!",
            back_kb()
        )
        await callback.answer()
        return

    await state.update_data(
        viewing_user_id=profile_data["user_id"],
        viewing_profile_data=profile_data,
        viewing_photo_index=0,
    )
    await _show_profile(callback, session, minio, profile_data, 0)
    await callback.answer()
    
    # Записываем время выполнения
    duration = time.time() - start_time
    REQUEST_DURATION.labels(handler="view_profiles").observe(duration)
    logger.info("request_completed", handler="view_profiles", duration=duration)


async def _show_profile(
    callback: CallbackQuery,
    session: AsyncSession,
    minio: MinioClient,
    profile_data: dict,
    photo_index: int = 0,
):
    """
    Показываем анкету пользователю.
    Если есть фото — отправляем с фото.
    Если нет — просто текст.
    """
    gender_emoji = ""
    if profile_data.get("gender") == "male":
        gender_emoji = "👨"
    elif profile_data.get("gender") == "female":
        gender_emoji = "👩"

    caption = (
        f"{gender_emoji} {profile_data.get('name') or 'Без имени'}, "
        f"{profile_data.get('age') or '?'}\n"
        f"🏙 {profile_data.get('city') or 'Город не указан'}\n\n"
        f"📝 {profile_data.get('description') or 'Нет описания'}\n\n"
        f"💡 Интересы: {profile_data.get('interests') or 'Не указаны'}"
    )

    photos = await ProfileService(session).get_approved_photos(profile_data["user_id"])

    if photos:
        photo_index = photo_index % len(photos)
        photo_input = await get_photo_input(photos[photo_index], minio)
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_input,
            caption=caption,
            reply_markup=view_profile_kb(len(photos), photo_index)
        )
    else:
        try:
            await callback.message.edit_text(caption, reply_markup=view_profile_kb())
        except Exception:
            await callback.message.answer(caption, reply_markup=view_profile_kb())


@router.callback_query(F.data.startswith("view_photo_"))
async def paginate_view_profile_photos(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    minio: MinioClient,
):
    try:
        photo_index = int(callback.data.replace("view_photo_", ""))
    except ValueError:
        await callback.answer("Некорректное фото", show_alert=True)
        return

    data = await state.get_data()
    profile_data = data.get("viewing_profile_data")
    if not profile_data:
        await callback.answer("Анкета не найдена", show_alert=True)
        return

    await state.update_data(viewing_photo_index=photo_index)
    await _show_profile(callback, session, minio, profile_data, photo_index)
    await callback.answer()
            
# ─── Лайк / Пропуск ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "like")
async def like_profile(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    rabbitmq: RabbitMQClient,
    minio: MinioClient,
    redis: aioredis.Redis,
    surreal: SurrealClient,
):
    data = await state.get_data()
    viewing_user_id = data.get("viewing_user_id")

    if not viewing_user_id:
        await callback.answer("Ошибка: анкета не найдена")
        return

    profile_service = ProfileService(session)
    matching_service = MatchingService(session, redis, surreal)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    result = await matching_service.like_profile(current_user, viewing_user_id)

    if result["is_mutual"]:
        other_profile = await profile_service.get_profile_by_user_id(viewing_user_id)
        other_user = await profile_service.get_user_by_id(viewing_user_id)
        if not other_user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        if result["is_new_match"]:
            await rabbitmq.publish("match", {
                "user1_telegram_id": current_user.telegram_id,
                "user2_telegram_id": other_user.telegram_id,
                "user1_name": other_profile.name if other_profile else "Пользователь",
            })

        await replace_message_text(
            callback,
            (
                f"🎉 У вас взаимная симпатия с "
                f"{other_profile.name if other_profile else 'пользователем'}!\n\n"
                f"Куда писать: {format_telegram_contact(other_user)}"
            ),
            main_menu_kb()
        )
    else:
        await rabbitmq.publish("like", {
            "from_user_id": current_user.id,
            "to_user_id": viewing_user_id,
        })
        await view_profiles(callback, session, state, minio, rabbitmq, redis, surreal)

    await callback.answer()


@router.callback_query(F.data == "skip")
async def skip_profile(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    rabbitmq: RabbitMQClient,
    minio: MinioClient,
    redis: aioredis.Redis,
    surreal: SurrealClient,
):
    data = await state.get_data()
    viewing_user_id = data.get("viewing_user_id")

    if not viewing_user_id:
        await callback.answer("Ошибка: анкета не найдена")
        return

    current_user = await ProfileService(session).get_user_by_telegram_id(
        callback.from_user.id
    )
    if not current_user:
        await callback.answer("Сначала зарегистрируйся с /start", show_alert=True)
        return

    await MatchingService(session, redis, surreal).skip_profile(
        current_user,
        viewing_user_id,
    )

    await rabbitmq.publish("skip", {
        "from_user_id": current_user.id,
        "to_user_id": viewing_user_id,
    })

    await view_profiles(callback, session, state, minio, rabbitmq, redis, surreal)
    await callback.answer()


# ─── Матчи ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_matches")
async def show_matches(callback: CallbackQuery, session: AsyncSession, answer_callback: bool = True):
    profile_service = ProfileService(session)
    current_user = await profile_service.get_user_by_telegram_id(callback.from_user.id)

    if not current_user:
        await callback.answer("Ошибка")
        return

    matches = await MatchingService(session, None, None).get_active_matches(current_user.id)

    if matches:
        text = "💕 Твои мэтчи:\n\n"
        for i, match in enumerate(matches, 1):
            other_user_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
            other_user = await profile_service.get_user_by_id(other_user_id)
            profile = await profile_service.get_profile_by_user_id(other_user_id)
            if other_user and profile:
                text += (
                    f"{i}. {profile.name or 'Без имени'}, {profile.age or '?'}\n"
                    f"   Куда писать: {format_telegram_contact(other_user)}\n\n"
                )
    else:
        text = "💔 Пока нет мэтчей.\n\nПродолжай смотреть анкеты!"

    await replace_message_text(callback, text, matches_kb(matches) if matches else back_kb())
    if answer_callback:
        await callback.answer()


@router.callback_query(F.data.startswith("delete_match_"))
async def delete_match(
    callback: CallbackQuery,
    session: AsyncSession,
    redis: aioredis.Redis,
    surreal: SurrealClient,
):
    try:
        match_id = int(callback.data.replace("delete_match_", ""))
    except ValueError:
        await callback.answer("Некорректный мэтч", show_alert=True)
        return

    current_user = await ProfileService(session).get_user_by_telegram_id(
        callback.from_user.id
    )
    if not current_user:
        await callback.answer("Ошибка", show_alert=True)
        return

    matching_service = MatchingService(session, redis, surreal)
    deleted, _ = await matching_service.delete_match(current_user.id, match_id)
    if not deleted:
        await show_matches(callback, session, answer_callback=False)
        await callback.answer("Мэтч уже удалён")
        return
    await show_matches(callback, session, answer_callback=False)
    await callback.answer("Мэтч удалён")


# ─── Назад ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback)
