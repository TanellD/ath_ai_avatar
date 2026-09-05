"""Dev-эндпоинт для управляемых сбоев STT.

Роутер подключается, только когда `STT_DEBUG_FAULTS_ENABLED=true`: в обычной
конфигурации этих путей не существует, а не «существуют и запрещены».
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.stt.debug_faults import FaultMode, get_switch

router = APIRouter(prefix="/debug/stt-fault", tags=["debug"])


class ArmRequest(BaseModel):
    mode: FaultMode
    captures: int = Field(default=1, ge=0, le=10)


class SwitchState(BaseModel):
    mode: FaultMode
    captures: int


@router.get("", response_model=SwitchState)
async def read_state() -> SwitchState:
    switch = get_switch()
    return SwitchState(mode=switch.mode, captures=switch.captures)


@router.post("", response_model=SwitchState)
async def arm(payload: ArmRequest) -> SwitchState:
    switch = get_switch()
    switch.arm(payload.mode, 0 if payload.mode is FaultMode.OFF else payload.captures)
    return SwitchState(mode=switch.mode, captures=switch.captures)
