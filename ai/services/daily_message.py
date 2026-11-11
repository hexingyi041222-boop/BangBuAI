"""Explicit, once-per-day AI work. GET reports remain pure reads."""

import logging

from app.core.config import settings
from app.services.doubao import get_doubao_client
from app.storage.repository import repository


logger = logging.getLogger(__name__)


def generate_daily_message(*, user_id: str, report_date: str) -> dict:
    summary = repository.get_daily_summary(user_id=user_id, report_date=report_date)
    count = summary["coverage_count"]
    if not count or settings.doubao_mode != "real":
        return {"status": "insufficient_data" if not count else "mock", "message": summary.get("daily_message"), "source": "template", "source_count": count, "cached": False}
    claimed = repository.claim_daily_message(user_id=user_id, report_date=report_date, source_count=count)
    if claimed:
        message = None
        try:
            # Deliberately no automatic retries: explicit generation has a hard daily call budget.
            text = get_doubao_client().summarize_day(summary, repository.get_persona(user_id))
            if isinstance(text, str) and text.strip():
                message = text.strip()[:240]
        except Exception:
            logger.warning("daily_message_generation_failed", exc_info=False)
        repository.finish_daily_message(user_id=user_id, report_date=report_date, message=message)
    saved = repository.get_daily_message(user_id=user_id, report_date=report_date)
    if not saved:
        return {"status": "insufficient_data", "message": None, "source": "template", "source_count": 0, "cached": False}
    return {
        "status": saved["status"], "message": saved["message"] or summary.get("daily_message"),
        "source": "model" if saved["status"] == "ready" else "template",
        "source_count": saved["source_count"], "cached": not claimed,
    }
