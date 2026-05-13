from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    ModerationStatus,
    Photo,
    Preference,
    Profile,
    Rating,
    Referral,
    User,
)


class ProfileService:
    """Business operations for users, profiles, preferences, photos and referrals."""

    MAX_ACTIVE_PHOTOS = 5

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: str | None = None,
    ) -> User:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(telegram_id=telegram_id, username=username)
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)

            self.session.add(Profile(user_id=user.id))
            self.session.add(Preference(user_id=user.id))
            self.session.add(Rating(user_id=user.id))
            await self.session.commit()
            return user

        if user.username != username:
            user.username = username
            await self.session.commit()

        return user

    async def get_profile_by_telegram_id(self, telegram_id: int) -> Profile | None:
        result = await self.session.execute(
            select(Profile).join(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_profile_by_user_id(self, user_id: int) -> Profile | None:
        result = await self.session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update_profile_field(
        self,
        telegram_id: int,
        field_name: str,
        value,
    ) -> Profile | None:
        profile = await self.get_profile_by_telegram_id(telegram_id)
        if not profile:
            return None

        setattr(profile, field_name, value)
        profile.completeness = self.calculate_completeness(profile)
        await self.session.commit()
        return profile

    async def get_preference_by_telegram_id(self, telegram_id: int) -> Preference | None:
        result = await self.session.execute(
            select(Preference).join(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def update_preference_field(
        self,
        telegram_id: int,
        field_name: str,
        value,
    ) -> Preference | None:
        preference = await self.get_preference_by_telegram_id(telegram_id)
        if not preference:
            return None

        setattr(preference, field_name, value)
        await self.session.commit()
        return preference

    async def process_referral(self, new_user: User, ref_code: str):
        try:
            referrer_telegram_id = int(ref_code.replace("ref_", ""))
        except ValueError:
            return

        if referrer_telegram_id == new_user.telegram_id:
            return

        referrer = await self.get_user_by_telegram_id(referrer_telegram_id)
        if not referrer:
            return

        existing = await self.session.execute(
            select(Referral).where(Referral.referred_id == new_user.id)
        )
        if existing.scalar_one_or_none():
            return

        self.session.add(Referral(referrer_id=referrer.id, referred_id=new_user.id))
        await self.session.commit()

    async def count_referrals(self, referrer_id: int) -> int:
        result = await self.session.execute(
            select(Referral).where(Referral.referrer_id == referrer_id)
        )
        return len(result.scalars().all())

    async def get_primary_photo(self, user_id: int) -> Photo | None:
        result = await self.session.execute(
            select(Photo)
            .where(
                Photo.user_id == user_id,
                Photo.status == ModerationStatus.APPROVED,
            )
            .order_by(Photo.is_primary.desc(), Photo.created_at.asc(), Photo.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_approved_photos(self, user_id: int) -> list[Photo]:
        result = await self.session.execute(
            select(Photo)
            .where(
                Photo.user_id == user_id,
                Photo.status == ModerationStatus.APPROVED,
            )
            .order_by(Photo.is_primary.desc(), Photo.created_at.asc(), Photo.id.asc())
        )
        return list(result.scalars().all())

    async def get_user_photos(self, user_id: int) -> list[Photo]:
        result = await self.session.execute(
            select(Photo)
            .where(Photo.user_id == user_id)
            .order_by(Photo.created_at.asc(), Photo.id.asc())
        )
        return list(result.scalars().all())

    def get_photo_counts(self, photos: list[Photo]) -> tuple[int, int]:
        approved_count = sum(
            1 for photo in photos if photo.status == ModerationStatus.APPROVED
        )
        pending_count = sum(
            1 for photo in photos if photo.status == ModerationStatus.PENDING
        )
        return approved_count, pending_count

    async def add_pending_photo(
        self,
        user_id: int,
        s3_key: str,
        telegram_file_id: str | None = None,
    ) -> tuple[bool, list[Photo]]:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": user_id},
        )

        photos = await self.get_user_photos(user_id)
        active_photos_count = sum(
            1
            for photo in photos
            if getattr(photo.status, "value", photo.status) != "rejected"
        )
        if active_photos_count >= self.MAX_ACTIVE_PHOTOS:
            await self.session.commit()
            return False, photos

        self.session.add(
            Photo(
                user_id=user_id,
                s3_key=s3_key,
                telegram_file_id=telegram_file_id,
                status=ModerationStatus.PENDING,
                is_primary=False,
            )
        )
        await self.session.flush()
        await self.update_photo_stats(user_id)
        photos = await self.get_user_photos(user_id)
        await self.session.commit()
        return True, photos

    async def delete_photo(self, user_id: int, photo_id: int) -> tuple[bool, str | None, list[Photo]]:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": user_id},
        )

        result = await self.session.execute(
            select(Photo).where(Photo.id == photo_id, Photo.user_id == user_id)
        )
        photo = result.scalar_one_or_none()
        if not photo:
            photos = await self.get_user_photos(user_id)
            await self.session.commit()
            return False, None, photos

        was_primary = bool(photo.is_primary)
        s3_key = photo.s3_key

        await self.session.delete(photo)
        await self.session.flush()

        remaining_photos = await self.get_user_photos(user_id)
        approved_remaining_photos = [
            photo for photo in remaining_photos if photo.status == ModerationStatus.APPROVED
        ]
        if approved_remaining_photos and (
            was_primary or not any(p.is_primary for p in approved_remaining_photos)
        ):
            await self.session.execute(
                update(Photo).where(Photo.user_id == user_id).values(is_primary=False)
            )
            approved_remaining_photos[0].is_primary = True
            await self.session.flush()

        await self.update_photo_stats(user_id)
        photos = await self.get_user_photos(user_id)
        await self.session.commit()
        return True, s3_key, photos

    async def set_primary_photo(self, user_id: int, photo_id: int) -> tuple[bool, list[Photo]]:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": user_id},
        )

        result = await self.session.execute(
            select(Photo).where(
                Photo.id == photo_id,
                Photo.user_id == user_id,
                Photo.status == ModerationStatus.APPROVED,
            )
        )
        photo = result.scalar_one_or_none()
        if not photo:
            photos = await self.get_user_photos(user_id)
            await self.session.commit()
            return False, photos

        await self.session.execute(
            update(Photo).where(Photo.user_id == user_id).values(is_primary=False)
        )
        photo.is_primary = True
        await self.session.commit()
        photos = await self.get_user_photos(user_id)
        return True, photos

    async def update_photo_stats(self, user_id: int) -> list[Photo]:
        result = await self.session.execute(
            select(Photo).where(
                Photo.user_id == user_id,
                Photo.status == ModerationStatus.APPROVED,
            )
        )
        approved_photos = list(result.scalars().all())
        profile = await self.get_profile_by_user_id(user_id)
        if profile:
            profile.photo_count = len(approved_photos)
            profile.completeness = self.calculate_completeness(profile)
        return approved_photos

    @staticmethod
    def calculate_completeness(profile: Profile) -> float:
        fields = [
            profile.name,
            profile.age,
            profile.gender,
            profile.city,
            profile.description,
            profile.interests,
        ]
        filled = sum(1 for field in fields if field)
        if profile.photo_count and profile.photo_count > 0:
            filled += 1
        return filled / 7
