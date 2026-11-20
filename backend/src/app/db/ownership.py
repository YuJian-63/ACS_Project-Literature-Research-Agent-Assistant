from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import PaperImport, User
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
