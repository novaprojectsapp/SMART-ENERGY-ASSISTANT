import re
from dataclasses import dataclass


@dataclass
class Intent:
    intent: str
    confidence: float
    period: str = "NOW"
    basis: str = ""
    comparison: str = ""
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


INTENT_RULES = [
    {
        "intent": "CURRENT_POWER",
        "patterns": [
            r"current\s*(power|watt|load|consumption)",
            r"how\s*(much|many)\s*(watt|power|watts?)\s*(am?\s*i\s*using|now|current)",
            r"what.*power\s*(am?\s*i\s*using|now|current|right\s*now)",
            r"tell\s*me\s*(my\s*)?(current\s*)?power",
            r"power\s*(reading|now|current)",
            r"(watt|watts|w)\s*(am?\s*i|now|current)",
            r"electricity\s*(power|load)\s*(now|current)",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
    {
        "intent": "CURRENT_VOLTAGE",
        "patterns": [
            r"current\s*voltage",
            r"voltage\s*(reading|now|level)",
            r"how\s*much\s*voltage",
            r"what\s*(is|was)\s*the\s*voltage",
            r"voltage\s*(am?\s*i|now|current)",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
    {
        "intent": "CURRENT_CURRENT",
        "patterns": [
            r"current\s*(amp|ampere)",
            r"(amp|ampere)s?\s*(am?\s*i|now|current)",
            r"how\s*much\s*(amp|ampere|current)",
            r"how\s*many\s*amps?",
            r"(amp|ampere)s?\s*(reading|drawing|being\s*used|using)",
            r"what\s*(is|was)\s*the\s*(current|amp)",
            r"what\s*(is|was)\s*the\s*current\s*(reading|draw|amperage|usage)",
            r"current\s*amperage",
            r"amperage",
            r"amps?\s*now",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
    {
        "intent": "CURRENT_ENERGY",
        "patterns": [
            r"total\s*(energy|kwh|units?)\s*(today|so\s*far|used)",
            r"energy\s*(consumed|used)\s*(today|so\s*far)",
            r"how\s*much\s*(energy|kwh|units?)\s*(have?\s*i\s*used|today|so\s*far)",
            r"(kwh|units?)\s*(today|so\s*far|used)",
            r"electricity\s*(consumed|used|consumption)\s*(today|so\s*far)",
            r"today.*(energy|kwh|units?|consumption)",
            r"(energy|kwh|units?).*(today|so\s*far)",
        ],
        "period": "TODAY",
        "confidence": 0.92,
    },
    {
        "intent": "CURRENT_FREQUENCY",
        "patterns": [
            r"current\s*frequency",
            r"frequency\s*(reading|now|hz)",
            r"how\s*much\s*frequency",
            r"what\s*(is|was)\s*the\s*frequency",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
    {
        "intent": "CURRENT_POWER_FACTOR",
        "patterns": [
            r"(power\s*factor|pf)\s*(reading|now|value)",
            r"what\s*(is|was)\s*the\s*(power\s*factor|pf)",
            r"power\s*factor\s*(now|current)",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
    {
        "intent": "TODAY_COST",
        "patterns": [
            r"today.*(cost|bill|spend|charge|price|money)",
            r"(cost|bill|spend|charge|price|money).*today",
            r"how\s*(much|many).*today.*(cost|bill|spend|rupee|rs|inr)",
            r"today.*electricity.*(cost|bill|charge)",
            r"electricity.*cost.*today",
            r"daily\s*(cost|bill|charge)",
            r"today.*bill",
            r"how\s*much.*electricity.*(cost|bill|charge|spend)",
            r"how\s*much.*(cost|bill|spend|charge).*today",
            r"what\s*is\s*my\s*cost",
            r"what\s*is\s*my\s*electricity\s*cost",
            r"tell\s*me\s*my\s*cost",
            r"cost\s*of\s*electricity",
            r"what\s*(is|am\s*i)\s*(spending|paying)",
            r"(how\s*much\s*(am\s*i|do\s*i)\s*)?(spend|pay).*(electricity|power)",
            r"(cost|charge|price)\s*(right\s*now|currently|now)",
            r"my\s*(electricity\s*)?cost",
        ],
        "period": "TODAY",
        "confidence": 0.92,
    },
    {
        "intent": "TODAY_ENERGY",
        "patterns": [
            r"today.*(energy|kwh|units?|consumption|used|electricity)",
            r"(energy|kwh|units?|consumption|used|electricity).*today",
            r"how\s*much.*(today)",
            r"daily\s*(usage|consumption|energy|kwh)",
            r"what.*used\s*today",
        ],
        "period": "TODAY",
        "confidence": 0.9,
    },
    {
        "intent": "MONTHLY_BILL",
        "patterns": [
            r"(?<![a-z-])\bmonthly\b.*(bill|cost|charge)",
            r"(bill|cost|charge).*(?<![a-z-])\bmonthly\b",
            r"(bill|cost|charge).*(this\s*month|for\s*this\s*month|next\s*month)",
            r"(this\s*month|for\s*this\s*month|next\s*month).*(bill|cost|charge)",
            r"how\s*much.*(?:per\s*month|this\s*month|in\s*a\s*month).*(cost|bill|charge|spend)",
            r"electricity\s*bill\s*(for\s*)?(the\s*)?month(?!s)",
            r"(one\s*month|(?<![a-z-])\bmonthly\b).*electricity.*(cost|bill|charge)",
            r"what.*my\s*(monthly|this\s*month).*bill",
            r"estimate\s*monthly",
            r"per\s*month\s*(bill|cost|charge)",
        ],
        "period": "MONTHLY",
        "confidence": 0.95,
    },
    {
        "intent": "BILL_PREDICTION",
        "patterns": [
            r"(bill|cost)\s*predict",
            r"predict.*(bill|cost)",
            r"what\s*will.*bill\s*be",
            r"how\s*much.*bill\s*(will|going|expect)",
            r"two[\s-]*month.*(bill|cost|charge)",
            r"bimonthly.*(bill|cost|charge)",
            r"(bill|cost).*(two[\s-]*month|bimonthly|next|future|predict|estimate)",
            r"estimate.*(bill|cost)",
            r"what\s*will\s*be\s*the\s*bill\s*(for|be)?\s*2\s*months?",
            r"bill\s*for\s*(2|two)\s*months?",
            r"(bimonthly|bi-monthly)\s*bill",
            r"how\s*much.*spending.*electricity",
            r"electricity\s*cost\s*(these\s*days|lately|recently|now)",
            r"(spending|spend|cost|bill).*electricity",
            r"electricity.*(spending|spend|cost|bill|charge|expense)",
            r"how\s*much.*electricity\s*(cost|bill|charge)",
            r"what.*electricity\s*(cost|bill|charge)",
            r"what\s*(is|will\s*be)\s*my\s*bill",
            r"what\s*is\s*my\s*(electricity\s*)?bill",
            r"my\s*bill",
            r"(bill|cost)\s*for\s*the\s*billing\s*period",
        ],
        "period": "BILLING_PERIOD",
        "confidence": 0.92,
    },
    {
        "intent": "BILL_EXPLANATION",
        "patterns": [
            r"(explain|break\s*down|detail|slab).*bill",
            r"bill.*(explain|break\s*down|detail|slab)",
            r"how\s*(is|was)\s*the\s*bill\s*(calculated|computed|determined)",
            r"bill\s*(breakdown|detail|explanation|slab)",
        ],
        "period": "BILLING_PERIOD",
        "confidence": 0.92,
    },
    {
        "intent": "ENERGY_INSIGHT",
        "patterns": [
            r"(insight|analysis|summary|overview).*energy",
            r"energy.*(insight|analysis|summary|overview)",
            r"analyze\s*my\s*(energy|power|electricity|usage)",
            r"(energy|power|electricity)\s*analysis",
            r"give\s*me\s*(energy|usage)\s*(insight|summary|overview|report)",
        ],
        "period": "RECENT",
        "confidence": 0.85,
    },
    {
        "intent": "ENERGY_COMPARISON",
        "patterns": [
            r"compar.*energy",
            r"energy.*compar",
            r"how\s*(does|do)\s*(my|the)\s*(usage|energy|consumption)\s*compar",
            r"(normal|average|usual|baseline)\s*(vs|versus|compared|comparison)",
        ],
        "period": "RECENT",
        "comparison": "NORMAL_BASELINE",
        "confidence": 0.85,
    },
    {
        "intent": "NORMAL_USAGE",
        "patterns": [
            r"(normal|average|usual|typical)\s*(usage|consumption|energy)",
            r"what.*normal\s*(usage|consumption|energy)",
            r"(normal|average|usual|typical)\s*(pattern|profile)",
        ],
        "period": "BASELINE",
        "confidence": 0.88,
    },
    {
        "intent": "ANOMALY_STATUS",
        "patterns": [
            r"(anomal|abnormal|unusual|weird|strange|irregular)",
            r"is\s*(anything|something)\s*(wrong|unusual|abnormal|off)",
            r"any\s*(anomal|abnormal|unusual|weird)",
            r"detect\s*(anomal|abnormal|unusual)",
        ],
        "period": "RECENT",
        "confidence": 0.88,
    },
    {
        "intent": "PEAK_USAGE",
        "patterns": [
            r"(peak|highest|maximum|max)\s*(usage|consumption|power|load|time|hour|period)",
            r"when.*(peak|highest|maximum)\s*(usage|consumption|power)",
            r"what\s*time.*(peak|highest|most)",
        ],
        "period": "RECENT",
        "confidence": 0.88,
    },
    {
        "intent": "APPLIANCE_ACTIVITY",
        "patterns": [
            r"(appliance|device|bulb|light|fan|ac|air\s*conditioner).*(on|off|state|status|active|running)",
            r"(which|what)\s*(appliance|device|bulb|light|fan|load).*on",
            r"(appliance|device|bulb|light).*activity",
            r"appliance.*(recogni|detect|state|activity)",
        ],
        "period": "NOW",
        "confidence": 0.85,
    },
    {
        "intent": "DAILY_USAGE",
        "patterns": [
            r"daily\s*(usage|consumption|energy|kwh|average)",
            r"(usage|consumption|energy)\s*(per|each|every)\s*day",
            r"average\s*daily\s*(usage|consumption|energy)",
        ],
        "period": "DAILY",
        "confidence": 0.88,
    },
    {
        "intent": "WEEKLY_USAGE",
        "patterns": [
            r"weekly\s*(usage|consumption|energy|kwh)",
            r"(usage|consumption|energy)\s*(per|each|every)\s*week",
            r"this\s*week.*(usage|consumption|energy)",
        ],
        "period": "WEEKLY",
        "confidence": 0.88,
    },
    {
        "intent": "MONTHLY_USAGE",
        "patterns": [
            r"monthly\s*(usage|consumption|energy|kwh)",
            r"(usage|consumption|energy)\s*(per|each|every)\s*month",
            r"this\s*month.*(usage|consumption|energy)",
        ],
        "period": "MONTHLY",
        "confidence": 0.88,
    },
    {
        "intent": "SAVING_RECOMMENDATION",
        "patterns": [
            r"(save|saving|reduce|reduction|efficient|efficiently)",
            r"how\s*(can|do)\s*i\s*(save|reduce|cut)\s*(my|the)\s*(bill|cost|electricity|energy|consumption)",
            r"(recommend|suggestion|tip|advice).*(save|reduce|efficient)",
            r"(save|saving|reduce|reduction).*money",
            r"ways?\s*to\s*(save|reduce|cut)",
        ],
        "period": "RECENT",
        "confidence": 0.85,
    },
    {
        "intent": "ENERGY_COACH",
        "patterns": [
            r"(coach|coaching|guide|guidance|advice)",
            r"(help|helping)\s*me\s*(save|reduce|reduce|manage)",
            r"energy\s*(coach|coaching|guide|guidance|advice|tips)",
            r"teach\s*me\s*(about|to)\s*(save|reduce|manage|understand)",
        ],
        "period": "RECENT",
        "confidence": 0.82,
    },
    {
        "intent": "WHAT_IF",
        "patterns": [
            r"what\s*if",
            r"suppose\s*(i|we)\s*(reduce|increase|cut|add|change|switch)",
            r"(hypothetical|scenario|simulat)",
            r"if\s*i\s*(reduce|increase|cut|use|turn\s*off|switch)",
        ],
        "period": "SCENARIO",
        "confidence": 0.85,
    },
    {
        "intent": "DEVICE_STATUS",
        "patterns": [
            r"(device|sensor|esp|hardware)\s*(status|state|online|offline|connect)",
            r"is\s*(the|my)\s*(device|sensor|esp)\s*(online|offline|connected|working)",
            r"(device|sensor)\s*health",
            r"(device|sensor)\s*connection",
        ],
        "period": "NOW",
        "confidence": 0.92,
    },
    {
        "intent": "LAST_UPDATE",
        "patterns": [
            r"last\s*(update|reading|data|measurement|time)",
            r"when\s*(was|is)\s*the\s*last\s*(update|reading|data|measurement)",
            r"when\s*(did|does)\s*(the|my)\s*(device|sensor)\s*(send|update|read)",
        ],
        "period": "NOW",
        "confidence": 0.92,
    },
    {
        "intent": "HELP",
        "patterns": [
            r"^help$",
            r"what\s*can\s*you\s*(do|help|answer)",
            r"how\s*(do|does|can)\s*(i|you|this)\s*(use|work|help)",
            r"what\s*(do|does)\s*you\s*do",
            r"commands?",
            r"options?",
        ],
        "period": "NOW",
        "confidence": 0.95,
    },
]


def classify_intent(text: str) -> Intent:
    normalized = text.lower().strip()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("bi monthly", "bimonthly")

    best_match = None
    best_score = 0

    for rule in INTENT_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, normalized):
                score = rule["confidence"]
                if score > best_score:
                    best_score = score
                    best_match = rule
                break

    if best_match:
        return Intent(
            intent=best_match["intent"],
            confidence=best_match["confidence"],
            period=best_match.get("period", "NOW"),
            basis=best_match.get("basis", ""),
            comparison=best_match.get("comparison", ""),
        )

    return Intent(intent="UNKNOWN", confidence=0.0)
