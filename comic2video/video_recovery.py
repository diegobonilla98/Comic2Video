def failure_category(record):
    status = record.get("status")
    if status == "succeeded":
        return "preserve_success"
    if status != "failed":
        return "unresolved"
    error = str(record.get("error", "")).lower()
    if any(term in error for term in ("e005", "flagged as sensitive", "moderation", "content policy", "safety filter")):
        return "provider_content_block"
    if any(term in error for term in ("timeout", "timed out", "deadline exceeded")):
        return "timeout"
    if any(term in error for term in ("rate limit", "too many requests", "429")):
        return "rate_limit"
    if any(term in error for term in ("service unavailable", "internal server error", "bad gateway", "503", "502")):
        return "service_error"
    return "unclassified"


def recovery_plan(records, settings):
    result = []
    for record in records:
        category = failure_category(record)
        eligible = category in settings["eligible_failures"]
        result.append({"shot_id": record["key"], "prediction_id": record.get("prediction_id"), "status": record["status"], "category": category, "eligible_for_fallback": eligible, "fallback_models": settings["fallback_models"] if eligible else [], "error": record.get("error")})
    return result
