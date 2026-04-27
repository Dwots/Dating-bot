import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from rabbitmq import RabbitMQClient
from minio_client import MinioClient
import json
import redis.asyncio as aioredis
from surreal import SurrealClient
from logger import setup_logging
from metrics import REQUESTS_TOTAL, CACHE_HITS, CACHE_MISSES, REQUEST_DURATION
import time

logger = setup_logging("handlers")

from database import User, Profile, Preference, Match, Interaction, Rating, Referral, Gender, Photo
from keyboards import (
    main_menu_kb, profile_menu_kb, edit_profile_kb, gender_kb,
    search_gender_kb, view_profile_kb, back_kb, search_settings_kb
)

router = Router()


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

async def get_or_create_user(session: AsyncSession, telegram_id: int, username: str = None) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)

        profile = Profile(user_id=user.id)
        session.add(profile)

        preference = Preference(user_id=user.id)
        session.add(preference)

        rating = Rating(user_id=user.id)
        session.add(rating)

        await session.commit()

    return user


def calculate_completeness(profile: Profile) -> float:
    """
    Считаем заполненность анкеты:
    - 6 текстовых полей по 1 очку каждое
    - наличие фото — ещё 1 очко
    Итого максимум 7 очков → делим на 7
    """
    fields = [
        profile.name,
        profile.age,
        profile.gender,
        profile.city,
        profile.description,
        profile.interests,
    ]
    filled = sum(1 for f in fields if f)
    # photo_count > 0 даёт +1 очко
    if profile.photo_count and profile.photo_count > 0:
        filled += 1
    return filled / 7


# ─── /start — с поддержкой реферальной ссылки ────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    REQUESTS_TOTAL.labels(handler="start").inc()

    user = await get_or_create_user(
        session, message.from_user.id, message.from_user.username
    )

    # Проверяем бан
    if user.is_banned:
        await message.answer("🚫 Ваш аккаунт заблокирован.")
        return

    logger.info("user_started", user_id=user.telegram_id, username=user.username)

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        await process_referral(session, user, args[1])

    await message.answer(
        f"👋 Привет! Добро пожаловать в Dating Bot!\n\n"
        f"Твой ID: {user.telegram_id}\n\n"
        "Заполни анкету, чтобы начать знакомиться!",
        reply_markup=main_menu_kb()
    )
    

async def process_referral(session: AsyncSession, new_user: User, ref_code: str):
    """
    ref_code выглядит как "ref_5497326447"
    Извлекаем telegram_id реферера, находим его в БД,
    записываем связь в таблицу referrals
    """
    try:
        referrer_telegram_id = int(ref_code.replace("ref_", ""))
    except ValueError:
        return

    # Не записываем если человек сам себя пригласил
    if referrer_telegram_id == new_user.telegram_id:
        return

    # Находим реферера
    result = await session.execute(
        select(User).where(User.telegram_id == referrer_telegram_id)
    )
    referrer = result.scalar_one_or_none()
    if not referrer:
        return

    # Проверяем что этот пользователь ещё не был приглашён кем-то
    # (referred_id уникален в таблице)
    existing = await session.execute(
        select(Referral).where(Referral.referred_id == new_user.id)
    )
    if existing.scalar_one_or_none():
        return

    referral = Referral(referrer_id=referrer.id, referred_id=new_user.id)
    session.add(referral)
    await session.commit()


# ─── Главное меню ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📱 Главное меню\n\nВыбери действие:",
        reply_markup=main_menu_kb()
    )
    await callback.answer()


# ─── Профиль ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == callback.from_user.id)
    )
    profile = result.scalar_one_or_none()

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

    await callback.message.edit_text(text, reply_markup=profile_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_profile")
async def edit_profile_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "✏️ Что хочешь изменить?",
        reply_markup=edit_profile_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "edit_name")
async def edit_name(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.name)
    await callback.message.edit_text("Введи своё имя:", reply_markup=back_kb())
    await callback.answer()


@router.message(ProfileForm.name)
async def process_name(message: Message, state: FSMContext, session: AsyncSession):
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == message.from_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.name = message.text
        profile.completeness = calculate_completeness(profile)
        await session.commit()
    await state.clear()
    await message.answer("✅ Имя сохранено!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "edit_age")
async def edit_age(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.age)
    await callback.message.edit_text("Введи свой возраст (18-100):", reply_markup=back_kb())
    await callback.answer()


@router.message(ProfileForm.age)
async def process_age(message: Message, state: FSMContext, session: AsyncSession):
    try:
        age = int(message.text)
        if 18 <= age <= 100:
            result = await session.execute(
                select(Profile).join(User).where(User.telegram_id == message.from_user.id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.age = age
                profile.completeness = calculate_completeness(profile)
                await session.commit()
            await state.clear()
            await message.answer("✅ Возраст сохранён!", reply_markup=main_menu_kb())
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
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == callback.from_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.gender = gender
        profile.completeness = calculate_completeness(profile)
        await session.commit()
    await callback.message.edit_text("✅ Пол сохранён!", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "edit_city")
async def edit_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.city)
    await callback.message.edit_text("Введи свой город:", reply_markup=back_kb())
    await callback.answer()


@router.message(ProfileForm.city)
async def process_city(message: Message, state: FSMContext, session: AsyncSession):
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == message.from_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.city = message.text
        profile.completeness = calculate_completeness(profile)
        await session.commit()
    await state.clear()
    await message.answer("✅ Город сохранён!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "edit_description")
async def edit_description(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.description)
    await callback.message.edit_text("Расскажи о себе:", reply_markup=back_kb())
    await callback.answer()


@router.message(ProfileForm.description)
async def process_description(message: Message, state: FSMContext, session: AsyncSession):
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == message.from_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.description = message.text
        profile.completeness = calculate_completeness(profile)
        await session.commit()
    await state.clear()
    await message.answer("✅ Описание сохранено!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "edit_interests")
async def edit_interests(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.interests)
    await callback.message.edit_text("Укажи свои интересы (через запятую):", reply_markup=back_kb())
    await callback.answer()


@router.message(ProfileForm.interests)
async def process_interests(message: Message, state: FSMContext, session: AsyncSession):
    result = await session.execute(
        select(Profile).join(User).where(User.telegram_id == message.from_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.interests = message.text
        profile.completeness = calculate_completeness(profile)
        await session.commit()
    await state.clear()
    await message.answer("✅ Интересы сохранены!", reply_markup=main_menu_kb())


# ─── Фото ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "edit_photo")
async def edit_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.photo)
    await callback.message.edit_text(
        "📷 Отправь фото для профиля\n\n"
        "Требования:\n"
        "• Только фото (не документ)\n"
        "• Максимум 5 фото на профиль",
        reply_markup=back_kb()
    )
    await callback.answer()


@router.message(ProfileForm.photo, F.photo)
async def process_photo(message: Message, state: FSMContext, session: AsyncSession, minio: MinioClient):
    """
    F.photo — фильтр aiogram: срабатывает только если сообщение содержит фото

    message.photo — это список объектов PhotoSize в разных разрешениях
    [-1] — берём последний элемент = самое большое разрешение
    """
    user_result = await session.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    # Проверяем сколько фото уже загружено
    photos_result = await session.execute(
        select(Photo).where(Photo.user_id == current_user.id)
    )
    existing_photos = photos_result.scalars().all()

    if len(existing_photos) >= 5:
        await message.answer(
            "❌ Максимум 5 фото. Удали старое чтобы добавить новое.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    # Скачиваем фото из Telegram
    # message.photo[-1] — наибольшее разрешение
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)

    # download возвращает BytesIO объект
    file_bytes_io = await message.bot.download_file(file.file_path)
    file_bytes = file_bytes_io.read()

    # Загружаем в MinIO — получаем s3_key
    # boto3 синхронный, запускаем в executor чтобы не блокировать event loop
    loop = asyncio.get_event_loop()
    s3_key = await loop.run_in_executor(
        None,  # None = использовать ThreadPoolExecutor по умолчанию
        minio.upload_photo,
        file_bytes,
        current_user.telegram_id
    )

    # Первое фото — главное
    is_primary = len(existing_photos) == 0

    # Сохраняем метаданные в PostgreSQL
    # Сам файл в MinIO, в БД только путь к нему
    photo_record = Photo(
        user_id=current_user.id,
        s3_key=s3_key,
        is_primary=is_primary
    )
    session.add(photo_record)

    # Обновляем счётчик фото в профиле
    profile_result = await session.execute(
        select(Profile).where(Profile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile:
        profile.photo_count = len(existing_photos) + 1
        profile.completeness = calculate_completeness(profile)

    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Фото загружено! {'(главное фото профиля)' if is_primary else ''}\n"
        f"Всего фото: {len(existing_photos) + 1}/5",
        reply_markup=main_menu_kb()
    )


@router.message(ProfileForm.photo)
async def process_photo_wrong(message: Message):
    """Если прислали не фото а что-то другое"""
    await message.answer(
        "❌ Пожалуйста, отправь именно фото (не файл, не документ)",
    )

# ─── Настройки поиска ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "search_settings")
async def search_settings(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(
        select(Preference).join(User).where(User.telegram_id == callback.from_user.id)
    )
    pref = result.scalar_one_or_none()

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
async def process_search_gender(callback: CallbackQuery, session: AsyncSession):
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

    result = await session.execute(
        select(Preference).join(User).where(User.telegram_id == callback.from_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref:
        pref.preferred_gender = preferred_gender
        await session.commit()

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
async def process_min_age(message: Message, state: FSMContext, session: AsyncSession):
    try:
        age = int(message.text)
        if 18 <= age <= 99:
            result = await session.execute(
                select(Preference).join(User).where(User.telegram_id == message.from_user.id)
            )
            pref = result.scalar_one_or_none()
            if pref:
                pref.min_age = age
                await session.commit()
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
async def process_max_age(message: Message, state: FSMContext, session: AsyncSession):
    try:
        age = int(message.text)
        if 19 <= age <= 100:
            result = await session.execute(
                select(Preference).join(User).where(User.telegram_id == message.from_user.id)
            )
            pref = result.scalar_one_or_none()
            if pref:
                pref.max_age = age
                await session.commit()
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
async def process_search_city(message: Message, state: FSMContext, session: AsyncSession):
    result = await session.execute(
        select(Preference).join(User).where(User.telegram_id == message.from_user.id)
    )
    pref = result.scalar_one_or_none()
    if pref:
        # если написал "любой" — убираем фильтр по городу
        pref.preferred_city = None if message.text.lower() == "любой" else message.text
        await session.commit()
    await state.clear()
    await message.answer("✅ Город поиска сохранён!", reply_markup=main_menu_kb())


# ─── Реферальная ссылка ───────────────────────────────────────────────────────

@router.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery, session: AsyncSession):
    """
    Генерируем ссылку вида: t.me/{bot_username}?start=ref_{telegram_id}
    Telegram сам передаст payload в /start команду
    """
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    # Считаем сколько людей уже пришло по нашей ссылке
    referrals_result = await session.execute(
        select(Referral).where(Referral.referrer_id == current_user.id)
    )
    referrals_count = len(referrals_result.scalars().all())

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
    
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    if not current_user:
        await callback.message.edit_text("Сначала зарегистрируйся с /start")
        await callback.answer()
        return

    cache_key = f"profiles_cache:{current_user.id}"
    cached = await redis.rpop(cache_key)

    if cached:
        profile_data = json.loads(cached)
        CACHE_HITS.inc()  # метрика
        logger.info("cache_hit", user_id=current_user.id)
    else:
        CACHE_MISSES.inc()  # метрика
        logger.info("cache_miss", user_id=current_user.id)
        profile_data = await _fetch_profiles_from_db(
            session, current_user, redis, cache_key, surreal
        )

    if not profile_data:
        await callback.message.edit_text(
            "😔 Пока нет подходящих анкет.\n\nПопробуй изменить настройки поиска!",
            reply_markup=back_kb()
        )
        await callback.answer()
        return

    view_interaction = Interaction(
        from_user_id=current_user.id,
        to_user_id=profile_data["user_id"],
        action="view"
    )
    session.add(view_interaction)
    await session.commit()

    await surreal.add_interaction(
        from_user_id=current_user.id,
        to_user_id=profile_data["user_id"],
        action="viewed"
    )

    await state.update_data(viewing_user_id=profile_data["user_id"])
    await _show_profile(callback, session, minio, profile_data)
    await callback.answer()
    
    # Записываем время выполнения
    duration = time.time() - start_time
    REQUEST_DURATION.labels(handler="view_profiles").observe(duration)
    logger.info("request_completed", handler="view_profiles", duration=duration)


async def _fetch_profiles_from_db(
    session: AsyncSession,
    current_user: User,
    redis: aioredis.Redis,
    cache_key: str,
    surreal: SurrealClient,
) -> dict | None:
    pref_result = await session.execute(
        select(Preference).where(Preference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()

    # Получаем просмотренных из SurrealDB (граф)
    # Раньше: запрос в PostgreSQL SELECT to_user_id FROM interactions WHERE from_user_id = X
    # Теперь: обход графа — быстрее
    interacted_ids = await surreal.get_interacted_users(current_user.id)
    
    # Преобразуем в список для SQLAlchemy not_in
    viewed_ids = list(interacted_ids)
    viewed_ids.append(current_user.id)

    query = (
        select(Profile)
        .join(User)
        .join(Rating, User.id == Rating.user_id)
        .where(
            Profile.user_id.not_in(viewed_ids),
            Profile.completeness > 0.3,
        )
    )

    if pref:
        if pref.preferred_gender:
            query = query.where(Profile.gender == pref.preferred_gender)
        if pref.min_age:
            query = query.where(Profile.age >= pref.min_age)
        if pref.max_age:
            query = query.where(Profile.age <= pref.max_age)
        if pref.preferred_city:
            query = query.where(Profile.city == pref.preferred_city)

    query = query.order_by(Rating.combined_score.desc()).limit(10)
    result = await session.execute(query)
    profiles = result.scalars().all()

    if not profiles:
        return None

    def profile_to_dict(p: Profile) -> dict:
        return {
            "user_id": p.user_id,
            "name": p.name,
            "age": p.age,
            "gender": p.gender.value if p.gender else None,
            "city": p.city,
            "description": p.description,
            "interests": p.interests,
        }

    all_dicts = [profile_to_dict(p) for p in profiles]

    if len(all_dicts) > 1:
        rest = all_dicts[1:]
        pipe = redis.pipeline()
        for profile_dict in rest:
            pipe.lpush(cache_key, json.dumps(profile_dict))
        pipe.expire(cache_key, 3600)
        await pipe.execute()

    return all_dicts[0]


async def _show_profile(
    callback: CallbackQuery,
    session: AsyncSession,
    minio: MinioClient,
    profile_data: dict,
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

    # Ищем фото профиля
    photo_result = await session.execute(
        select(Photo).where(
            Photo.user_id == profile_data["user_id"],
            Photo.is_primary == True
        )
    )
    primary_photo = photo_result.scalar_one_or_none()

    if primary_photo:
        loop = asyncio.get_event_loop()
        photo_bytes = await loop.run_in_executor(
            None, minio.get_photo_bytes, primary_photo.s3_key
        )
        from aiogram.types import BufferedInputFile
        photo_file = BufferedInputFile(photo_bytes, filename="photo.jpg")
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=photo_file,
            caption=caption,
            reply_markup=view_profile_kb()
        )
    else:
        try:
            await callback.message.edit_text(caption, reply_markup=view_profile_kb())
        except Exception:
            await callback.message.answer(caption, reply_markup=view_profile_kb())
            
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

    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    # PostgreSQL
    like_interaction = Interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="like"
    )
    session.add(like_interaction)

    # SurrealDB граф
    await surreal.add_interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="liked"
    )

    # Проверка взаимного лайка — сначала через SurrealDB (быстрее)
    is_mutual = await surreal.check_mutual_like(current_user.id, viewing_user_id)

    if is_mutual:
        user1_id = min(current_user.id, viewing_user_id)
        user2_id = max(current_user.id, viewing_user_id)
        match = Match(user1_id=user1_id, user2_id=user2_id)
        session.add(match)
        await session.commit()

        other_result = await session.execute(
            select(Profile).where(Profile.user_id == viewing_user_id)
        )
        other_profile = other_result.scalar_one_or_none()

        other_user_result = await session.execute(
            select(User).where(User.id == viewing_user_id)
        )
        other_user = other_user_result.scalar_one_or_none()

        await rabbitmq.publish("match", {
            "user1_telegram_id": current_user.telegram_id,
            "user2_telegram_id": other_user.telegram_id,
            "user1_name": other_profile.name if other_profile else "Пользователь",
        })

        await callback.message.edit_text(
            f"🎉 У вас взаимная симпатия с "
            f"{other_profile.name if other_profile else 'пользователем'}!\n\n"
            "Можете начать общение!",
            reply_markup=main_menu_kb()
        )
    else:
        await session.commit()
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

    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    # PostgreSQL
    skip_interaction = Interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="skip"
    )
    session.add(skip_interaction)
    await session.commit()

    # SurrealDB граф
    await surreal.add_interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="skipped"
    )

    await rabbitmq.publish("skip", {
        "from_user_id": current_user.id,
        "to_user_id": viewing_user_id,
    })

    await view_profiles(callback, session, state, minio, rabbitmq, redis, surreal)
    await callback.answer()


# ─── Матчи ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_matches")
async def show_matches(callback: CallbackQuery, session: AsyncSession):
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()

    if not current_user:
        await callback.answer("Ошибка")
        return

    matches_result = await session.execute(
        select(Match).where(
            or_(
                Match.user1_id == current_user.id,
                Match.user2_id == current_user.id
            ),
            Match.is_active.is_(True)
        )
    )
    
    matches = matches_result.scalars().all()

    if matches:
        text = "💕 Твои мэтчи:\n\n"
        for i, match in enumerate(matches, 1):
            other_user_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
            profile_result = await session.execute(
                select(Profile).where(Profile.user_id == other_user_id)
            )
            profile = profile_result.scalar_one_or_none()
            if profile:
                text += f"{i}. {profile.name or 'Без имени'}, {profile.age or '?'}\n"
    else:
        text = "💔 Пока нет мэтчей.\n\nПродолжай смотреть анкеты!"

    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


# ─── Назад ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback)