from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker, Session
import os
from datetime import datetime, timedelta

# Импортируем модели из bot (Docker volume или копируем)
import sys
sys.path.append("/bot")
from database import User, Profile, Match, Interaction, Rating, Base

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
    
    db.close()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "total_users": total_users,
        "total_matches": total_matches,
        "active_users": active_users,
        "likes_today": likes_today,
    })


@app.get("/users")
async def users_list(request: Request):
    """Список пользователей с кнопками Ban/Unban"""
    db = get_db()
    
    users = db.query(User, Profile).join(Profile, User.id == Profile.user_id).all()
    
    db.close()
    
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
    })


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