import json
import logging
import httpx
from ..config import settings

logger = logging.getLogger("smart_energy.ai.llm")

LLM_SYSTEM_PROMPT = """You are an energy assistant intent parser. Given a user query about electricity/energy, return ONLY a JSON object with the user's intent.

Valid intents:
CURRENT_POWER, CURRENT_CURRENT, CURRENT_VOLTAGE, CURRENT_ENERGY, CURRENT_FREQUENCY, CURRENT_POWER_FACTOR
TODAY_ENERGY, TODAY_COST
MONTHLY_BILL, BILL_PREDICTION, BILL_EXPLANATION
ENERGY_INSIGHT, ENERGY_COMPARISON, NORMAL_USAGE, ANOMALY_STATUS, PEAK_USAGE
APPLIANCE_ACTIVITY
DAILY_USAGE, WEEKLY_USAGE, MONTHLY_USAGE
SAVING_RECOMMENDATION, ENERGY_COACH
WHAT_IF
DEVICE_STATUS, LAST_UPDATE
HELP

Valid periods: NOW, TODAY, WEEKLY, MONTHLY, BILLING_PERIOD, RECENT, BASELINE, SCENARIO

JSON format:
{"intent": "INTENT_NAME", "period": "PERIOD", "confidence": 0.0-1.0}

Rules:
- Return ONLY valid JSON, no explanation
- Choose the MOST SPECIFIC intent
- confidence must be 0.0-1.0
- If you cannot determine intent, use {"intent": "UNKNOWN", "period": "NOW", "confidence": 0.0}"""


async def call_llm_fallback(user_text: str) -> dict | None:
    if not settings.GEMINI_ENABLED:
        logger.info("Gemini disabled, skipping LLM fallback")
        return None

    if not settings.GEMINI_API_KEY:
        logger.info("No Gemini API key configured, skipping LLM fallback")
        return None

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": LLM_SYSTEM_PROMPT}]},
                {"role": "user", "parts": [{"text": f"User query: {user_text}"}]},
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 200,
            },
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)

            if response.status_code != 200:
                logger.warning("Gemini API returned status %d", response.status_code)
                return None

            data = response.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            parsed = json.loads(text)

            if "intent" not in parsed or "confidence" not in parsed:
                logger.warning("LLM response missing required fields: %s", parsed)
                return None

            return {
                "intent": parsed["intent"],
                "period": parsed.get("period", "NOW"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "basis": parsed.get("basis", ""),
                "comparison": parsed.get("comparison", ""),
                "source": "LLM",
            }

    except json.JSONDecodeError as e:
        logger.warning("LLM response not valid JSON: %s", e)
        return None
    except httpx.TimeoutException:
        logger.warning("Gemini API timeout")
        return None
    except Exception as e:
        logger.error("LLM fallback error: %s", e)
        return None
