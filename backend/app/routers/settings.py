"""
Settings and system configuration API routes.
Real persistence in MongoDB and Redis cache management.
"""
from fastapi import APIRouter
from app.core.mongodb import get_database
from app.db.services import cache_service
from app.schemas.settings import (
    SettingsRequest,
    SettingsResponse,
    ClearCacheResponse,
)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings():
    """Get system settings from database."""
    db = get_database()
    doc = await db.system_settings.find_one({"_id": "app_settings"})
    if not doc:
        return SettingsResponse(
            success=True,
            ocr_sensitivity="medium",
            ocr_confidence_threshold=0.75,
            marking_confidence_threshold=0.70,
            cache_enabled=True,
        )

    return SettingsResponse(
        success=True,
        ocr_sensitivity=doc.get("ocr_sensitivity", "medium"),
        ocr_confidence_threshold=float(doc.get("ocr_confidence_threshold", 0.75)),
        marking_confidence_threshold=float(doc.get("marking_confidence_threshold", 0.70)),
        cache_enabled=doc.get("cache_enabled", True),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(request: SettingsRequest):
    """Update and persist system settings."""
    db = get_database()
    doc = await db.system_settings.find_one({"_id": "app_settings"}) or {}
    ocr_sens = request.ocr_sensitivity or doc.get("ocr_sensitivity", "medium")
    ocr_thresh = request.ocr_confidence_threshold if request.ocr_confidence_threshold is not None else float(doc.get("ocr_confidence_threshold", 0.75))
    mark_thresh = request.marking_confidence_threshold if request.marking_confidence_threshold is not None else float(doc.get("marking_confidence_threshold", 0.70))

    update_data = {
        "ocr_sensitivity": ocr_sens,
        "ocr_confidence_threshold": ocr_thresh,
        "marking_confidence_threshold": mark_thresh,
        "cache_enabled": True,
    }
    await db.system_settings.update_one(
        {"_id": "app_settings"},
        {"$set": update_data},
        upsert=True,
    )
    return SettingsResponse(
        success=True,
        ocr_sensitivity=ocr_sens,
        ocr_confidence_threshold=ocr_thresh,
        marking_confidence_threshold=mark_thresh,
        cache_enabled=True,
    )


@router.post("/clear-cache", response_model=ClearCacheResponse)
async def clear_cache():
    """Clear Redis application cache."""
    stats_before = await cache_service.get_cache_stats()
    items_cleared = stats_before.get("total", 0)

    try:
        await cache_service.invalidate_pattern("*")
    except Exception:
        pass

    return ClearCacheResponse(
        success=True,
        message="Cache cleared successfully",
        cleared_items=items_cleared,
    )
