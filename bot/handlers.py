from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from database import User, Profile, Preference, Match, Interaction, Rating, Gender, ModerationStatus
from keyboards import (
    main_menu_kb, profile_menu_kb, edit_profile_kb, gender_kb, 
    search_gender_kb, view_profile_kb, back_kb
)

router = Router()


class ProfileForm(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    description = State()
    interests = State()


class PreferenceForm(StatesGroup):
    gender = State()
    min_age = State()
    max_age = State()
    city = State()


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
    fields = [profile.name, profile.age, profile.gender, profile.city, profile.description, profile.interests]
    filled = sum(1 for f in fields if f)
    return filled / len(fields)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    user = await get_or_create_user(session, message.from_user.id, message.from_user.username)
    await message.answer(
        f"👋 Привет! Добро пожаловать в Dating Bot!\n\n"
        f"Твой ID: {user.telegram_id}\n\n"
        "Заполни анкету, чтобы начать знакомиться!",
        reply_markup=main_menu_kb()
    )


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📱 Главное меню\n\nВыбери действие:",
        reply_markup=main_menu_kb()
    )
    await callback.answer()


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


@router.callback_query(F.data == "search_settings")
async def search_settings(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(
        select(Preference).join(User).where(User.telegram_id == callback.from_user.id)
    )
    pref = result.scalar_one_or_none()
    
    if pref:
        gender_text = "Мужской" if pref.preferred_gender == Gender.MALE else "Женский" if pref.preferred_gender == Gender.FEMALE else "Любой"
        text = (
            "⚙️ Настройки поиска:\n\n"
            f"⚧ Искать: {gender_text}\n"
            f"🎂 Возраст: {pref.min_age}-{pref.max_age}\n"
            f"🏙 Город: {pref.preferred_city or 'Любой'}"
        )
    else:
        text = "Настройки не найдены"
    
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "view_profiles")
async def view_profiles(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    # Получаем текущего пользователя
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()
    
    if not current_user:
        await callback.message.edit_text("Сначала зарегистрируйся с /start")
        await callback.answer()
        return
    
    # Получаем настройки поиска
    pref_result = await session.execute(
        select(Preference).where(Preference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()
    
    # Получаем IDs уже просмотренных анкет
    viewed_result = await session.execute(
        select(Interaction.to_user_id).where(Interaction.from_user_id == current_user.id)
    )
    viewed_ids = [row[0] for row in viewed_result.fetchall()]
    viewed_ids.append(current_user.id)  # Исключаем себя
    
    # Строим запрос на поиск анкет
    query = select(Profile).join(User).join(Rating, User.id == Rating.user_id).where(
        Profile.user_id.not_in(viewed_ids),
        Profile.completeness > 0.3
    )
    
    # Применяем фильтры из настроек
    if pref:
        if pref.preferred_gender:
            query = query.where(Profile.gender == pref.preferred_gender)
        if pref.min_age:
            query = query.where(Profile.age >= pref.min_age)
        if pref.max_age:
            query = query.where(Profile.age <= pref.max_age)
        if pref.preferred_city:
            query = query.where(Profile.city == pref.preferred_city)
    
    # Сортируем по рейтингу
    query = query.order_by(Rating.combined_score.desc()).limit(1)
    
    result = await session.execute(query)
    profile = result.scalar_one_or_none()
    
    if profile:
        # Сохраняем ID просматриваемого профиля
        await state.update_data(viewing_user_id=profile.user_id)
        
        # Записываем просмотр
        view_interaction = Interaction(
            from_user_id=current_user.id,
            to_user_id=profile.user_id,
            action="view"
        )
        session.add(view_interaction)
        await session.commit()
        
        gender_text = "👨" if profile.gender == Gender.MALE else "👩" if profile.gender == Gender.FEMALE else ""
        text = (
            f"{gender_text} {profile.name or 'Без имени'}, {profile.age or '?'}\n"
            f"🏙 {profile.city or 'Город не указан'}\n\n"
            f"📝 {profile.description or 'Нет описания'}\n\n"
            f"💡 Интересы: {profile.interests or 'Не указаны'}"
        )
        await callback.message.edit_text(text, reply_markup=view_profile_kb())
    else:
        await callback.message.edit_text(
            "😔 Пока нет подходящих анкет.\n\nПопробуй изменить настройки поиска или зайди позже!",
            reply_markup=back_kb()
        )
    
    await callback.answer()


@router.callback_query(F.data == "like")
async def like_profile(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    viewing_user_id = data.get("viewing_user_id")
    
    if not viewing_user_id:
        await callback.answer("Ошибка")
        return
    
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()
    
    # Записываем лайк
    like_interaction = Interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="like"
    )
    session.add(like_interaction)
    
    # Проверяем взаимный лайк
    mutual_result = await session.execute(
        select(Interaction).where(
            Interaction.from_user_id == viewing_user_id,
            Interaction.to_user_id == current_user.id,
            Interaction.action == "like"
        )
    )
    mutual_like = mutual_result.scalar_one_or_none()
    
    if mutual_like:
        # Создаём мэтч
        user1_id = min(current_user.id, viewing_user_id)
        user2_id = max(current_user.id, viewing_user_id)
        
        match = Match(user1_id=user1_id, user2_id=user2_id)
        session.add(match)
        await session.commit()
        
        # Получаем профиль второго пользователя для уведомления
        other_result = await session.execute(
            select(Profile).where(Profile.user_id == viewing_user_id)
        )
        other_profile = other_result.scalar_one_or_none()
        
        await callback.message.edit_text(
            f"🎉 У вас взаимная симпатия с {other_profile.name if other_profile else 'пользователем'}!\n\n"
            "Можете начать общение!",
            reply_markup=main_menu_kb()
        )
    else:
        await session.commit()
        await view_profiles(callback, session, state)
    
    await callback.answer()


@router.callback_query(F.data == "skip")
async def skip_profile(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    data = await state.get_data()
    viewing_user_id = data.get("viewing_user_id")
    
    if not viewing_user_id:
        await callback.answer("Ошибка")
        return
    
    user_result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    current_user = user_result.scalar_one_or_none()
    
    skip_interaction = Interaction(
        from_user_id=current_user.id,
        to_user_id=viewing_user_id,
        action="skip"
    )
    session.add(skip_interaction)
    await session.commit()
    
    await view_profiles(callback, session, state)
    await callback.answer()


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
            Match.is_active == True
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


@router.callback_query(F.data == "back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback)
