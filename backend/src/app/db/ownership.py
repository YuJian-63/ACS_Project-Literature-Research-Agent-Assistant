from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PaperImport, Task, User
from app.errors import APIError


def lock_active_user(session: Session, user_id: UUID) -> User:
    user = session.scalar(select(User).where(User.id == user_id).with_for_update(key_share=True))
    if user is None or user.status != "active":
        raise APIError(401, "AUTH_REQUIRED", "登录状态已失效，请重新登录")
    return user


def check_import_capacity(session: Session, user_id: UUID, maximum: int) -> None:
    active = session.scalar(select(func.count()).select_from(PaperImport).where(
        PaperImport.user_id == user_id, PaperImport.status.in_(("queued", "running")),
    ))
    if active >= maximum:
        raise APIError(429, "IMPORT_CAPACITY_EXCEEDED", "正在导入的论文已达上限，请等待现有导入完成", headers={"Retry-After": "30"})


def check_task_capacity(session: Session, user_id: UUID, active_maximum: int, daily_maximum: int) -> None:
    active = session.scalar(select(func.count()).select_from(Task).where(
        Task.user_id == user_id, Task.status.in_(("queued", "running")),
    ))
    if active >= active_maximum:
        raise APIError(429, "TASK_CAPACITY_EXCEEDED", "正在执行的任务已达上限，请等待现有任务完成", headers={"Retry-After": "30"})
    daily = session.scalar(select(func.count()).select_from(Task).where(
        Task.user_id == user_id,
        Task.created_at >= func.date_trunc("day", func.timezone("UTC", func.clock_timestamp())).op("AT TIME ZONE")("UTC"),
    ))
    if daily >= daily_maximum:
        raise APIError(429, "DAILY_TASK_LIMIT", "今日新建任务已达上限，请明日再试", headers={"Retry-After": "3600"})
