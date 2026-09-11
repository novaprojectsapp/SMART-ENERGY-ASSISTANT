"""
Deterministic natural-language extraction for appliance scheduling.

Parses user text into:
  - appliance reference
  - action (ON/OFF)
  - time (HH:MM)
  - recurrence (ONCE/DAILY/WEEKLY)
  - days_of_week

Also detects missing required info for clarification and normalizes common
time/day phrases. No external LLM dependency is required for this layer.
"""
import re

TIME_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
TIME_12H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)\b", re.IGNORECASE)
DIGIT_MERIDIEM = re.compile(r"\b(\d{1,2})\s*(am|pm)\b", re.IGNORECASE)

WORD_TIME = {
    "one": 13, "two": 14, "three": 15, "four": 16, "five": 17,
    "six": 18, "seven": 19, "eight": 20, "nine": 21, "ten": 22,
    "eleven": 23, "twelve": 12,
}
# For "at six" -> 6 o'clock; without am/pm, treat 6 as 18:00 in evening context? Keep 06:00 for "6" but 12h ambiguous.
# We treat plain "six" as 18:00 when preceded by evening, else 06:00 / 12h. Simpler: "six" without suffix -> 06:00.
WORD_TIME_PLAIN = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}

DAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Contextual period phrases: "7 in the morning", "6 in the evening",
# "10 tonight", "11 at night". A word-clock heading (e.g. "six o'clock in
# the evening") is also supported.
PERIOD_MANNER = re.compile(
    r"\b(1[0-2]|[0-9]|[a-z]+)\s*(?:o['\u2019]?clock\s*)?"
    r"(?:in\s+the\s+|at\s+)?(morning|afternoon|evening|night|tonight)\b",
    re.IGNORECASE,
)
NOON_MIDNIGHT = re.compile(r"\b(noon|midnight)\b", re.IGNORECASE)
# A bare hour with no meridiem: "at 6", "by 8", "for 10", "at six".
BARE_HOUR = re.compile(
    r"\b(?:at|by|for|around|about)\s+"
    r"(1[0-2]|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
# Ordinals used to pick a specific schedule from a clarification list.
ORDINALS = {
    "1": 0, "2": 1, "3": 2, "4": 3,
    "1st": 0, "2nd": 1, "3rd": 2, "4th": 3,
    "first": 0, "second": 1, "third": 2, "fourth": 3,
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _period_context(text: str) -> str | None:
    """Return an inferred AM/PM from any contextual period word in the text."""
    if re.search(r"\bmorning\b", text, re.IGNORECASE):
        return "am"
    if re.search(r"\b(afternoon|evening|night|tonight)\b", text, re.IGNORECASE):
        return "pm"
    return None


def _apply_period(hour: int, period: str) -> str:
    if period == "am":
        return f"{0 if hour == 12 else hour:02d}:00"
    return f"{(hour if hour >= 12 else hour + 12):02d}:00"


def parse_time(text: str) -> str | None:
    """Return HH:MM (24h) from text, or None."""
    m = TIME_12H.search(text)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    m = TIME_24H.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"

    # Digit + am/pm without colon, e.g. "6 PM", "10 pm"
    m = DIGIT_MERIDIEM.search(text)
    if m:
        hour = int(m.group(1))
        meridiem = m.group(2).lower()
        if hour < 1 or hour > 12:
            return None
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"

    # Word time with am/pm
    for word, hour in WORD_TIME.items():
        if re.search(rf"\b{word}\s*(am|pm)\b", text):
            meridiem = "pm" if re.search(rf"\b{word}\s*pm\b", text) else "am"
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:00"

    # Contextual period: "7 in the morning" (AM), "6 in the evening",
    # "10 tonight", "11 at night" (PM), and word-clock forms like
    # "six o'clock in the evening".
    m = PERIOD_MANNER.search(text)
    if m:
        token = m.group(1)
        hour = int(token) if token.isdigit() else WORD_TIME_PLAIN.get(token)
        if hour is not None and 1 <= hour <= 12:
            return _apply_period(hour, "am" if m.group(2) == "morning" else "pm")

    # "noon" -> 12:00, "midnight" -> 00:00
    m = NOON_MIDNIGHT.search(text)
    if m:
        return "00:00" if m.group(1) == "midnight" else "12:00"

    # "half past ten" -> 10:30
    m = re.search(r"half\s+past\s+(\w+)", text)
    if m:
        hour = WORD_TIME_PLAIN.get(m.group(1))
        if hour is not None:
            hour = hour if hour < 12 else 12
            return f"{hour:02d}:30"

    # "quarter past / quarter to"
    m = re.search(r"quarter\s+(?:past|to)\s+(\w+)", text)
    if m:
        hour = WORD_TIME_PLAIN.get(m.group(1))
        if hour is not None:
            hour = hour if hour < 12 else 12
            return f"{hour:02d}:15"

    # Plain "at six" or "at 6": use a contextual period word if present
    # anywhere in the phrase, otherwise leave it ambiguous (returns None so
    # the assistant asks "6 AM or 6 PM?").
    m = BARE_HOUR.search(text)
    if m:
        token = m.group(1)
        hour = int(token) if token.isdigit() else WORD_TIME_PLAIN.get(token)
        if hour is not None and 1 <= hour <= 12:
            period = _period_context(text)
            if period:
                return _apply_period(hour, period)
            return None

    return None


def parse_time_pair(text: str) -> tuple[str | None, str | None]:
    """Extract (on_time, off_time) from an ON/OFF scheduling phrase.

    Handles forms like:
      - "turn on bulb 1 at 6 PM and turn it off at 11 PM"
      - "schedule bulb 1 from 6 PM to 11 PM every day"
      - "run bulb 2 from 7 PM to 10 PM Monday and Friday"
    Returns (on_time, off_time); missing values are None.
    """
    normalized = normalize_text(text)

    # Range form: "from T1 to T2" or "T1 to T2". parse_time ignores trailing
    # words, so reading the tail after "to " yields the second time reliably.
    m = re.search(r"\bfrom\s+(.+?)\s+to\s+", normalized)
    if m:
        t1 = parse_time(m.group(1))
        t2 = parse_time(normalized[m.end():])
        if t1 and t2:
            return t1, t2
    m = re.search(r"\b(on\s+|at\s+)?(.+?)\s+to\s+", normalized)
    if m:
        t1 = parse_time(m.group(2))
        t2 = parse_time(normalized[m.end():])
        if t1 and t2:
            return t1, t2

    # Position-based: find each on/off action verb (allowing pronouns), then
    # read the first time that follows it before the next action verb.
    verb_pattern = re.compile(
        r"\b(turn|switch|set|go|start|stop|run)\s+"
        r"(?:(?:it|them|this|these|that|the)\s+)?"
        r"(on|off)\b"
    )
    matches = list(verb_pattern.finditer(normalized))
    on_time = None
    off_time = None
    for i, m in enumerate(matches):
        bucket = m.group(2)
        segment_end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
        following = normalized[m.end():segment_end]
        t = parse_time(following) if following else None
        if t is None:
            continue
        if bucket == "on" and on_time is None:
            on_time = t
        elif bucket == "off" and off_time is None:
            off_time = t

    # Single-time fallbacks driven by the leading action.
    if on_time is None and off_time is None:
        only = parse_time(normalized)
        if re.search(r"\b(turn|switch|set|go|stop|run)\s+(?:(?:it|them|this|these|that|the)\s+)?off\b", normalized):
            return None, only
        return only, None

    return on_time, off_time


def parse_recurrence(text: str) -> tuple[str, list[int] | None]:
    """Return (schedule_type, days_of_week or None)."""
    if re.search(r"\b(once|one\s*time|tomorrow)\b", text):
        return "ONCE", None

    # weekly day detection
    mentioned_days = [DAYS[word] for word in list(DAYS.keys()) if re.search(rf"\b{word}\b", text)]

    if re.search(r"\b(every|on)\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text) or \
       re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b.*\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text) or \
       (mentioned_days and (re.search(r"\band\b", text) or re.search(r"\bevery\b", text))):
        return "WEEKLY", mentioned_days

    if re.search(r"\b(weekday|weekdays|mon\s*-\s*fri)\b", text):
        return "WEEKLY", [0, 1, 2, 3, 4]

    if re.search(r"\b(weekend|weekends|sat\s*[-&]\s*sun)\b", text):
        return "WEEKLY", [5, 6]

    if re.search(r"\b(every\s+day|daily|each\s+day|every\s+evening|every\s+night|every\s+morning|every\s+afternoon)\b", text):
        return "DAILY", None

    return "DAILY", None


def _detect_action(normalized: str) -> str | None:
    """Find the ON/OFF action following a turn/switch verb, tolerating an
    object in between ("turn it on", "turn the fan off")."""
    m = re.search(r"\b(turn|switch)\b", normalized)
    if not m:
        return None
    m2 = re.search(r"\b(on|off)\b", normalized[m.end():])
    if not m2:
        return None
    return "ON" if m2.group(1) == "on" else "OFF"


def extract_draft(text: str) -> dict:
    """Extract a scheduling draft. Missing fields are left as None."""
    normalized = normalize_text(text)

    action = _detect_action(normalized)

    schedule_type, days = parse_recurrence(normalized)
    on_time, off_time = parse_time_pair(normalized)

    # A range/pair without an explicit on/off verb still leads with ON
    # (e.g. "schedule bulb 1 from 7 PM to 10 PM").
    if action is None and on_time and off_time:
        action = "ON"

    start_time = on_time

    # "Turn the bulb off at 10 PM." -> a single OFF event at 10 PM.
    if action == "OFF" and off_time and not on_time:
        start_time = off_time
        off_time = None

    ambiguous_hour = None
    if start_time is None:
        m = BARE_HOUR.search(normalized)
        if m:
            token = m.group(1)
            hour = int(token) if token.isdigit() else WORD_TIME_PLAIN.get(token)
            if hour is not None:
                ambiguous_hour = hour

    return {
        "appliance_ref": extract_appliance_ref(normalized),
        "action": action,
        "start_time": start_time,
        "off_time": off_time,
        "schedule_type": schedule_type,
        "days_of_week": days,
        "time_ambiguous": ambiguous_hour,
    }


def extract_appliance_ref(text: str) -> str | None:
    """Return a raw appliance reference phrase (e.g. 'bulb 2', 'bedroom light')."""
    # Find phrase: (adjectives) + bulb/light/fan/appliance/etc with number
    m = re.search(r"\b((?:bedroom|living\s*room|kitchen|hall|bed|dining|front|back|room|main|side)\s+)?(bulb|light|fan|ac|air\s*conditioner|tv|pump|socket|appliance|device)\s*(1|2|3)?\b", text)
    if m:
        return " ".join(p for p in m.group(0).split() if p).strip()
    # generic "the/bulb schedule" without specific name -> the word "bulb"
    m2 = re.search(r"\b(bulb|light|fan|ac|pump|tv|appliance|device)\b", text)
    if m2:
        return m2.group(1)
    return None


def parse_manual_action(text: str) -> dict:
    """Parse a direct manual on/off command (no schedule)."""
    normalized = normalize_text(text)
    return {
        "appliance_ref": extract_appliance_ref(normalized),
        "action": _detect_action(normalized),
    }


def parse_schedule_selector(text: str | None) -> int | None:
    """Return the 0-based index of a schedule chosen via an ordinal word.

    Handles "the first one", "second", "3rd", etc. Returns None when no
    ordinal is present.
    """
    if not text:
        return None
    m = re.search(r"\b(first|second|third|fourth|\d+st|\d+nd|\d+rd|\d+th)\b", text, re.IGNORECASE)
    if not m:
        return None
    key = m.group(1).lower()
    if key in ORDINALS:
        return ORDINALS[key]
    return None
