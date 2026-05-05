from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
import os
import io
import boto3
from datetime import datetime, timedelta

# Импортируем модели из bot (Docker volume или копируем)
import sys
sys.path.append("/bot")
from database import User, Profile, Match, Interaction, Rating, Photo, ModerationStatus

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Подключение к БД
DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('DB_USER', 'postgres')}:"
    f"{os.environ.get('DB_PASSWORD', 'postgres')}@"
    f"{os.environ.get('DB_HOST', 'postgres')}:"
    f"{os.environ.get('DB_PORT', '5432')}/"
    f"{os.environ.get('DB_NAME', 'dating_bot')}"
)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "profiles")

s3_client = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_ENDPOINT}",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    region_name="us-east-1",
)


def get_db() -> Session:
    return SessionLocal()


@app.get("/")
async def index(request: Request):
    """Главная страница — статистика"""
    db = get_db()
    
    # Считаем метрики
    total_users = db.query(func.count(User.id)).scalar()
    total_matches = db.query(func.count(Match.id)).scalar()
    
    # Активные за последние 24 часа
    active_users = db.query(func.count(User.id)).filter(
        User.last_active_at > datetime.utcnow() - timedelta(hours=24)
    ).scalar()
    
    # Количество лайков сегодня
    likes_today = db.query(func.count(Interaction.id)).filter(
        Interaction.action == "like",
        Interaction.created_at > datetime.utcnow() - timedelta(days=1)
    ).scalar()
    pending_photos = db.query(func.count(Photo.id)).filter(
        Photo.status == ModerationStatus.PENDING
    ).scalar()
    
    db.close()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "total_users": total_users,
        "total_matches": total_matches,
        "active_users": active_users,
        "likes_today": likes_today,
        "pending_photos": pending_photos,
    })


@app.get("/users")
async def users_list(request: Request):
    """Список пользователей с кнопками Ban/Unban"""
    db = get_db()
    
    rows = db.query(User, Profile).join(Profile, User.id == Profile.user_id).all()
    users = []
    for user, profile in rows:
        primary_photo = db.query(Photo).filter(
            Photo.user_id == user.id,
            Photo.status == ModerationStatus.APPROVED,
        ).order_by(
            Photo.is_primary.desc(),
            Photo.created_at.asc(),
            Photo.id.asc(),
        ).first()
        users.append((user, profile, primary_photo))
    
    db.close()
    
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
    })


@app.get("/photos/{photo_id}")
async def photo_preview(photo_id: int):
    """Отдаём фото из MinIO для превью в админке."""
    db = get_db()
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    db.close()

    if not photo:
        return RedirectResponse(url="/users", status_code=303)

    response = s3_client.get_object(Bucket=MINIO_BUCKET, Key=photo.s3_key)
    content = response["Body"].read()
    content_type = response.get("ContentType") or "image/jpeg"
    return StreamingResponse(io.BytesIO(content), media_type=content_type)


@app.get("/moderation/photos")
async def moderation_photos(request: Request):
    db = get_db()
    rows = db.query(Photo, User, Profile).join(
        User, User.id == Photo.user_id
    ).join(
        Profile, Profile.user_id == User.id
    ).filter(
        Photo.status == ModerationStatus.PENDING
    ).order_by(Photo.created_at.asc()).all()
    db.close()

    return templates.TemplateResponse("moderation_photos.html", {
        "request": request,
        "photos": rows,
    })


@app.post("/moderation/photos/{photo_id}/approve")
async def approve_photo(photo_id: int):
    db = get_db()
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if photo:
        approved_exists = db.query(Photo.id).filter(
            Photo.user_id == photo.user_id,
            Photo.status == ModerationStatus.APPROVED,
            Photo.is_primary.is_(True),
        ).first()
        if not approved_exists:
            db.query(Photo).filter(Photo.user_id == photo.user_id).update({"is_primary": False})
            photo.is_primary = True
        photo.status = ModerationStatus.APPROVED

        approved_count = db.query(func.count(Photo.id)).filter(
            Photo.user_id == photo.user_id,
            Photo.status == ModerationStatus.APPROVED,
        ).scalar()

        profile = db.query(Profile).filter(Profile.user_id == photo.user_id).first()
        if profile:
            profile.photo_count = approved_count
            filled_fields = [
                profile.name,
                profile.age,
                profile.gender,
                profile.city,
                profile.description,
                profile.interests,
            ]
            profile.completeness = (sum(1 for value in filled_fields if value) + 1) / 7
        db.commit()
    db.close()
    return RedirectResponse(url="/moderation/photos", status_code=303)


@app.post("/moderation/photos/{photo_id}/reject")
async def reject_photo(photo_id: int):
    db = get_db()
    photo = db.query(Photo).filter(Photo.id == photo_id).first()
    if photo:
        photo.status = ModerationStatus.REJECTED
        photo.is_primary = False

        approved_count = db.query(func.count(Photo.id)).filter(
            Photo.user_id == photo.user_id,
            Photo.status == ModerationStatus.APPROVED,
        ).scalar()
        approved_primary = db.query(Photo).filter(
            Photo.user_id == photo.user_id,
            Photo.status == ModerationStatus.APPROVED,
            Photo.is_primary.is_(True),
        ).first()
        if approved_count and not approved_primary:
            fallback_photo = db.query(Photo).filter(
                Photo.user_id == photo.user_id,
                Photo.status == ModerationStatus.APPROVED,
            ).order_by(Photo.created_at.asc(), Photo.id.asc()).first()
            if fallback_photo:
                fallback_photo.is_primary = True

        profile = db.query(Profile).filter(Profile.user_id == photo.user_id).first()
        if profile:
            profile.photo_count = approved_count
            filled_fields = [
                profile.name,
                profile.age,
                profile.gender,
                profile.city,
                profile.description,
                profile.interests,
            ]
            profile.completeness = (sum(1 for value in filled_fields if value) + (1 if approved_count else 0)) / 7
        db.commit()
    db.close()
    return RedirectResponse(url="/moderation/photos", status_code=303)


@app.post("/users/{user_id}/ban")
async def ban_user(user_id: int):
    """Бан пользователя"""
    db = get_db()
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_banned = True
        db.commit()
    db.close()
    return RedirectResponse(url="/users", status_code=303)


@app.post("/users/{user_id}/unban")
async def unban_user(user_id: int):
    """Разбан пользователя"""
    db = get_db()
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_banned = False
        db.commit()
    db.close()
    return RedirectResponse(url="/users", status_code=303)


@app.get("/stats")
async def stats(request: Request):
    """Подробная статистика"""
    db = get_db()
    
    # TOP-10 по рейтингу
    top_users = db.query(User, Profile, Rating).join(
        Profile, User.id == Profile.user_id
    ).join(
        Rating, User.id == Rating.user_id
    ).order_by(Rating.combined_score.desc()).limit(10).all()
    
    # Графики активности по дням (последние 7 дней)
    activity = []
    for i in range(7):
        day_start = datetime.utcnow() - timedelta(days=i+1)
        day_end = datetime.utcnow() - timedelta(days=i)
        
        count = db.query(func.count(Interaction.id)).filter(
            Interaction.created_at >= day_start,
            Interaction.created_at < day_end
        ).scalar()
        
        activity.append({
            "date": day_start.strftime("%d.%m"),
            "count": count
        })
    
    db.close()
    
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "top_users": top_users,
        "activity": reversed(activity),
    })
