"""
AI Response Composer — uses Gemini to produce natural-language answers
from a structured data context.

The Gemini model NEVER accesses the database. It receives pre-computed
data and must only explain it naturally.
"""
import json
import logging
import httpx

from ..config import settings

logger = logging.getLogger("smart_energy.ai.composer")

COMPOSER_SYSTEM_PROMPT = """You are Smart Energy Assistant, a specialised electricity monitoring assistant for Indian homes.

You answer questions using ONLY the trusted sensor, billing, and device context supplied with each query.

RULES — you MUST follow every rule:

1. NEVER invent measurements. Never invent prices. Never invent tariff values.
2. NEVER invent device states, relay states, or schedule states.
3. NEVER invent historical data or baselines.
4. NEVER claim an appliance is ON or OFF unless the supplied context confirms it.
5. If information is missing or unavailable, say so honestly and briefly.
6. Use Indian English naturally. Use ₹ for currency.
7. Keep answers concise (1-3 sentences for voice). Only use 3-5 sentences for complex questions.
8. Do NOT mention databases, APIs, Python, FastAPI, prompts, models, JSON, or any internal details.
9. Do NOT use markdown, tables, bullet lists, or symbols that sound awkward when spoken.
10. When comparing values (high/low/normal), use ONLY supplied baseline or recent average data.
11. If no baseline exists for comparison, say there is not enough historical data yet.
12. For power: use "watts" or "kilowatts". For energy: use "kilowatt-hours" or "units".
13. Format money as "₹1,850" or "rupees 850" naturally.
14. Be conversational and helpful. Sound like a knowledgeable energy advisor.
15. For follow-up questions ("is that high?"), use the conversation history to understand what "that" refers to.
16. If safety protection is active, explain it clearly and advise the user to wait.
17. If asked to control something, only report the actual status from context, never assume success.
"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _format_context_for_prompt(context: dict, conversation_history: list[dict] | None = None) -> str:
    lines = []

    intent = context.get("intent", "unknown")
    confidence = context.get("confidence", 0)
    lines.append(f"Detected intent: {intent} (confidence: {confidence})")

    device = context.get("device", {})
    if device.get("available") is not None:
        status = "online" if device.get("online") else "offline"
        lines.append(f"Device: {device.get('name', 'unknown')} ({status})")
        if device.get("last_seen_age"):
            lines.append(f"Last seen: {device['last_seen_age']}")

    live = context.get("live", {})
    if live.get("available"):
        parts = []
        if live.get("voltage") is not None:
            parts.append(f"{live['voltage']:.1f} V")
        if live.get("current") is not None:
            parts.append(f"{live['current']:.2f} A")
        if live.get("power_w") is not None:
            pw = live["power_w"]
            if pw >= 1000:
                parts.append(f"{pw / 1000:.2f} kW")
            else:
                parts.append(f"{pw:.0f} W")
        if live.get("frequency") is not None:
            parts.append(f"{live['frequency']:.1f} Hz")
        if live.get("power_factor") is not None:
            parts.append(f"PF {live['power_factor']:.2f}")
        lines.append(f"Live reading: {', '.join(parts)}")
        lines.append(f"Reading age: {live.get('age', 'unknown')}")
    else:
        lines.append("Live reading: unavailable")

    today = context.get("today", {})
    if today:
        lines.append(f"Today: {today.get('energy_kwh', 0):.2f} kWh energy used")
        if today.get("cost_inr") is not None:
            lines.append(f"Today cost: ₹{today['cost_inr']:.2f}")
        if today.get("peak_power_w") is not None:
            lines.append(f"Today peak: {today['peak_power_w']:.0f} W")
        if today.get("avg_power_w") is not None:
            lines.append(f"Today average: {today['avg_power_w']:.0f} W")

    recent = context.get("recent", {})
    if recent.get("available"):
        lines.append(f"Recent 7-day average: {recent.get('average_power_w', 0):.0f} W")
        lines.append(f"Recent 7-day peak: {recent.get('peak_power_w', 0):.0f} W")
        lines.append(f"Recent 7-day energy: {recent.get('energy_kwh', 0):.2f} kWh")
        lines.append(f"Recent avg daily: {recent.get('avg_daily_kwh', 0):.2f} kWh/day")
    else:
        lines.append("Recent data: insufficient for baseline comparison")

    billing = context.get("billing", {})
    if billing.get("available"):
        lines.append(f"Monthly bill projection: ₹{billing['monthly_projection_inr']:.2f}")
        lines.append(f"Billing period ({billing.get('billing_period_months', 2)} months) projection: ₹{billing['billing_period_projection_inr']:.2f}")
    else:
        reason = billing.get("reason", "unavailable")
        lines.append(f"Billing projection: {reason}")

    tariff = context.get("tariff", {})
    if tariff.get("available"):
        lines.append(f"Tariff: {tariff.get('name', 'unknown')} ({tariff.get('billing_period_months', 2)}-month billing)")

    safety = context.get("safety", {})
    if safety.get("over_voltage_active"):
        lines.append("SAFETY: Over-voltage protection is ACTIVE. Voltage exceeds safe limit.")

    if conversation_history:
        lines.append("\nRecent conversation:")
        for turn in conversation_history[-4:]:
            role = turn.get("role", "user")
            text = turn.get("text", "")
            lines.append(f"  {role}: {text}")

    return "\n".join(lines)


async def compose_response(
    user_query: str,
    context: dict,
    conversation_history: list[dict] | None = None,
) -> str | None:
    """Use Gemini to compose a natural-language response from trusted context.

    Returns the response text, or None on failure/timeout.
    """
    if not settings.GEMINI_ENABLED:
        return None
    if not settings.GEMINI_API_KEY:
        return None

    context_text = _format_context_for_prompt(context, conversation_history)
    user_message = f"Context:\n{context_text}\n\nUser question: {user_query}"

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": COMPOSER_SYSTEM_PROMPT}]},
                {"role": "user", "parts": [{"text": user_message}]},
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 200,
            },
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code != 200:
                logger.warning("Gemini composer returned status %d", response.status_code)
                return None

            data = response.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            return _strip_code_fences(text) if text else None

    except httpx.TimeoutException:
        logger.warning("Gemini composer timeout")
        return None
    except Exception as e:
        logger.error("Gemini composer error: %s", e)
        return None
