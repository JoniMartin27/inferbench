"""Endpoint /api/hardware."""
from fastapi import APIRouter

from core.hardware import HardwareInfo, detect_hardware

router = APIRouter(prefix="/api", tags=["hardware"])


@router.get("/hardware", response_model=HardwareInfo)
async def get_hardware() -> HardwareInfo:
    return detect_hardware()
