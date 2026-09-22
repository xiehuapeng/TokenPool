"""Classify cache input without storing prompts or double counting input tokens."""
from decimal import Decimal, InvalidOperation


def request_cache_context(provider: str, payload: dict) -> dict:
    if provider not in ("kimi", "qwen"):
        return {}
    def explicit(value):
        if isinstance(value, dict):
            control = value.get("cache_control")
            if isinstance(control, dict) and control.get("type") == "ephemeral":
                return True
            return any(explicit(v) for v in value.values())
        return isinstance(value, list) and any(explicit(v) for v in value)

    options = payload.get("prompt_cache_options")
    ttl = options.get("ttl", "5m") if isinstance(options, dict) else "5m"
    return {"provider": provider, "explicit": explicit(payload),
            "ttl": ttl if ttl in ("5m", "1h") else "unknown"}


def cache_adjustment(rules, usage, context, input_tokens, cached_tokens, input_price, cached_price, tier):
    """Return adjustment to ordinary cost numerator plus a safe audit snapshot.

    Missing/inconsistent telemetry is flagged instead of pretending that a
    request option proves the TTL of an existing upstream cache entry.
    """
    context = context or {}
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, dict) else {}
    rules = rules or {}
    kind = rules.get("kind") or context.get("provider")
    field = "cache_write_tokens" if kind == "kimi" else "cache_creation_input_tokens"
    raw = details.get(field)
    reasons = []
    if raw is None and not context.get("explicit") and context.get("ttl") != "1h":
        return Decimal(0), {}
    write_tokens = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    if write_tokens is None:
        reasons.append("cache_write_usage_missing")
        write_tokens = 0
    if write_tokens < 0 or write_tokens > max(0, input_tokens - cached_tokens):
        reasons.append("cache_write_usage_invalid")
        write_tokens = 0
    explicit = bool(context.get("explicit")) or (kind == "qwen" and write_tokens > 0)
    adjustment = Decimal(0)
    snapshot = {"write_tokens": write_tokens, "explicit": explicit}
    if kind == "kimi":
        ttl = context.get("ttl", "5m")
        # Kimi locks TTL at initial creation. Request TTL alone is an estimate.
        # Even 5m writes may extend a previously created 1h prefix.
        price_key = "write_1h_price" if ttl == "1h" else "write_price"
        snapshot["requested_ttl"] = ttl
        if write_tokens:
            reasons.append("cache_ttl_not_reported_by_upstream")
    else:
        price_key = "write_price"
    prefix = "high_" if tier == "high" else ""

    def price(key):
        value = rules.get(prefix + key, rules.get(key))
        try:
            result = Decimal(str(value))
            return result if result.is_finite() and result >= 0 else None
        except (InvalidOperation, ValueError):
            return None

    if write_tokens:
        write_price = price(price_key)
        if write_price is None:
            reasons.append("cache_write_price_unverified")
        else:
            adjustment += Decimal(write_tokens) * (write_price - input_price)
            snapshot["write_price"] = str(write_price)
    if explicit and cached_tokens:
        read_price = price("read_price")
        if read_price is None:
            reasons.append("explicit_cache_read_price_unverified")
        else:
            adjustment += Decimal(cached_tokens) * (read_price - cached_price)
            snapshot["read_price"] = str(read_price)
    if rules.get("estimated") and (write_tokens or explicit):
        reasons.append("cache_price_requires_bill_confirmation")
    if reasons:
        snapshot["estimate_reasons"] = sorted(set(reasons))
    return adjustment, snapshot
