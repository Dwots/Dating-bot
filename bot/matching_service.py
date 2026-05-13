import json

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import Interaction, Match, Preference, Profile, Rating, User
from logger import setup_logging

logger = setup_logging("matching_service")


class MatchingService:
    """Business operations for candidate search, likes, skips and matches."""

    CACHE_TTL_SECONDS = 3600
    CACHE_PREFIX = "profiles_cache"

    def __init__(self, session: AsyncSession, redis, surreal):
        self.session = session
        self.redis = redis
        self.surreal = surreal
        self.last_cache_status = "miss"

    async def get_next_profile(self, current_user: User) -> dict | None:
        cache_key = self._cache_key(current_user.id)
        cached = await self.redis.rpop(cache_key)

        if cached:
            profile_data = json.loads(cached)
            excluded_ids = await self.get_excluded_profile_ids(current_user)
            if profile_data["user_id"] not in excluded_ids:
                self.last_cache_status = "hit"
                logger.info("cache_hit", user_id=current_user.id)
                return profile_data

            self.last_cache_status = "miss"
            logger.info("cache_stale", user_id=current_user.id)
            await self.redis.delete(cache_key)

        self.last_cache_status = "miss"
        logger.info("cache_miss", user_id=current_user.id)
        return await self._fetch_profiles_from_db(current_user, cache_key)

    async def record_view(self, from_user_id: int, to_user_id: int):
        self.session.add(
            Interaction(
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                action="view",
            )
        )
        await self.session.commit()
        await self.surreal.add_interaction(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            action="viewed",
        )

    async def like_profile(self, current_user: User, viewing_user_id: int) -> dict:
        self.session.add(
            Interaction(
                from_user_id=current_user.id,
                to_user_id=viewing_user_id,
                action="like",
            )
        )

        await self.surreal.add_interaction(
            from_user_id=current_user.id,
            to_user_id=viewing_user_id,
            action="liked",
        )

        is_mutual = await self.surreal.check_mutual_like(
            current_user.id,
            viewing_user_id,
        )
        if not is_mutual:
            await self.session.commit()
            return {"is_mutual": False, "is_new_match": False}

        user1_id = min(current_user.id, viewing_user_id)
        user2_id = max(current_user.id, viewing_user_id)
        await self._lock_match_pair(user1_id, user2_id)

        result = await self.session.execute(
            select(Match)
            .where(
                Match.user1_id == user1_id,
                Match.user2_id == user2_id,
                Match.is_active.is_(True),
            )
            .limit(1)
        )
        existing_match = result.scalar_one_or_none()
        is_new_match = existing_match is None

        if is_new_match:
            self.session.add(Match(user1_id=user1_id, user2_id=user2_id))

        await self.session.commit()
        return {"is_mutual": True, "is_new_match": is_new_match}

    async def skip_profile(self, current_user: User, viewing_user_id: int):
        self.session.add(
            Interaction(
                from_user_id=current_user.id,
                to_user_id=viewing_user_id,
                action="skip",
            )
        )
        await self.session.commit()
        await self.surreal.add_interaction(
            from_user_id=current_user.id,
            to_user_id=viewing_user_id,
            action="skipped",
        )

    async def get_active_matches(self, current_user_id: int) -> list[Match]:
        result = await self.session.execute(
            select(Match).where(
                or_(
                    Match.user1_id == current_user_id,
                    Match.user2_id == current_user_id,
                ),
                Match.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def delete_match(self, current_user_id: int, match_id: int) -> tuple[bool, int | None]:
        result = await self.session.execute(
            select(Match).where(
                Match.id == match_id,
                Match.is_active.is_(True),
                or_(
                    Match.user1_id == current_user_id,
                    Match.user2_id == current_user_id,
                ),
            )
        )
        match = result.scalar_one_or_none()
        if not match:
            return False, None

        other_user_id = (
            match.user2_id if match.user1_id == current_user_id else match.user1_id
        )
        user1_id = min(current_user_id, other_user_id)
        user2_id = max(current_user_id, other_user_id)
        await self._lock_match_pair(user1_id, user2_id)

        match.is_active = False
        await self.session.execute(
            delete(Interaction).where(
                or_(
                    (Interaction.from_user_id == current_user_id)
                    & (Interaction.to_user_id == other_user_id),
                    (Interaction.from_user_id == other_user_id)
                    & (Interaction.to_user_id == current_user_id),
                )
            )
        )
        await self.session.commit()

        try:
            await self.surreal.delete_interactions_between(current_user_id, other_user_id)
        except Exception as exc:
            logger.warning(
                "surreal_match_edges_delete_failed",
                match_id=match_id,
                error=str(exc),
            )

        await self.redis.delete(
            self._cache_key(current_user_id),
            self._cache_key(other_user_id),
        )
        return True, other_user_id

    async def get_excluded_profile_ids(self, current_user: User) -> list[int]:
        excluded_ids = {current_user.id}

        try:
            excluded_ids.update(await self.surreal.get_excluded_users(current_user.id))
        except Exception as exc:
            logger.warning(
                "surreal_interactions_read_failed",
                user_id=current_user.id,
                error=str(exc),
            )

        interactions_result = await self.session.execute(
            select(Interaction.to_user_id).where(
                Interaction.from_user_id == current_user.id,
                Interaction.action.in_(["like", "skip"]),
            )
        )
        excluded_ids.update(interactions_result.scalars().all())

        matches_result = await self.session.execute(
            select(Match).where(
                or_(
                    Match.user1_id == current_user.id,
                    Match.user2_id == current_user.id,
                ),
                Match.is_active.is_(True),
            )
        )
        for match in matches_result.scalars().all():
            other_user_id = (
                match.user2_id if match.user1_id == current_user.id else match.user1_id
            )
            excluded_ids.add(other_user_id)

        return list(excluded_ids)

    async def _fetch_profiles_from_db(
        self,
        current_user: User,
        cache_key: str,
    ) -> dict | None:
        pref_result = await self.session.execute(
            select(Preference).where(Preference.user_id == current_user.id)
        )
        preference = pref_result.scalar_one_or_none()
        excluded_ids = await self.get_excluded_profile_ids(current_user)

        query = (
            select(Profile)
            .join(User)
            .join(Rating, User.id == Rating.user_id)
            .where(
                Profile.user_id.not_in(excluded_ids),
                Profile.completeness > 0.3,
            )
        )

        if preference:
            if preference.preferred_gender:
                query = query.where(Profile.gender == preference.preferred_gender)
            if preference.min_age:
                query = query.where(Profile.age >= preference.min_age)
            if preference.max_age:
                query = query.where(Profile.age <= preference.max_age)
            if preference.preferred_city:
                query = query.where(Profile.city.ilike(preference.preferred_city))

        result = await self.session.execute(
            query.order_by(Rating.combined_score.desc()).limit(10)
        )
        profiles = list(result.scalars().all())
        if not profiles:
            return None

        profile_dicts = [self._profile_to_dict(profile) for profile in profiles]
        if len(profile_dicts) > 1:
            pipe = self.redis.pipeline()
            for profile_dict in profile_dicts[1:]:
                pipe.lpush(cache_key, json.dumps(profile_dict))
            pipe.expire(cache_key, self.CACHE_TTL_SECONDS)
            await pipe.execute()

        return profile_dicts[0]

    async def _lock_match_pair(self, user1_id: int, user2_id: int):
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"match:{user1_id}:{user2_id}"},
        )

    def _cache_key(self, user_id: int) -> str:
        return f"{self.CACHE_PREFIX}:{user_id}"

    @staticmethod
    def _profile_to_dict(profile: Profile) -> dict:
        return {
            "user_id": profile.user_id,
            "name": profile.name,
            "age": profile.age,
            "gender": profile.gender.value if profile.gender else None,
            "city": profile.city,
            "description": profile.description,
            "interests": profile.interests,
        }
