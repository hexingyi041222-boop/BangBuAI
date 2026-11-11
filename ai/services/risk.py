from app.core.config import settings
def classify_risk(text: str) -> str | None:
    if any(k in text for k in settings.risk_high_keywords): return 'high'
    if any(k in text for k in settings.risk_medium_keywords): return 'medium'
    return None
