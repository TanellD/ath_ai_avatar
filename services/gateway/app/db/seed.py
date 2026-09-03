"""Засев двух фиксированных пользователей — сотрудника и методиста.

Claude.md §2: ровно две роли, §4 явно исключает авторизацию. Реальных
аккаунтов нет и не планируется в этой фазе — `DEFAULT_EMPLOYEE_ID` нужен
только чтобы у `sessions.user_id` было на что ссылаться, и чтобы отчёт/
аналитика по артефактам уже сегодня были готовы к «пользователь» как
измерению, когда авторизация всё же понадобится.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserRow

DEFAULT_EMPLOYEE_ID = "employee-1"
DEFAULT_METHODIST_ID = "methodist-1"


async def seed_default_users(db: AsyncSession) -> None:
    existing = (await db.scalars(select(UserRow.id))).all()
    if DEFAULT_EMPLOYEE_ID not in existing:
        db.add(UserRow(id=DEFAULT_EMPLOYEE_ID, role="employee", display_name="Сотрудник"))
    if DEFAULT_METHODIST_ID not in existing:
        db.add(UserRow(id=DEFAULT_METHODIST_ID, role="methodist", display_name="Методист"))
    await db.commit()
