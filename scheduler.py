import random
from datetime import date, datetime, timedelta


def is_quiet_time(now: datetime, quiet_hours: str) -> bool:
    for period in (quiet_hours or "").split(","):
        if "-" not in period:
            continue
        start, end = period.split("-", 1)
        try:
            sh, sm = (int(value) for value in start.strip().split(":", 1))
            eh, em = (int(value) for value in end.strip().split(":", 1))
        except ValueError:
            continue
        current = now.hour * 60 + now.minute
        start_minute = sh * 60 + sm
        end_minute = eh * 60 + em
        if start_minute <= end_minute and start_minute <= current <= end_minute:
            return True
        if start_minute > end_minute and (current >= start_minute or current <= end_minute):
            return True
    return False


def generate_daily_schedule(
    day: date,
    count: int,
    start_minute: int = 9 * 60,
    end_minute: int = 24 * 60,
    min_gap_minutes: int = 180,
    rng: random.Random | None = None,
) -> list[datetime]:
    if count <= 0:
        return []
    rng = rng or random.SystemRandom()
    start = max(0, start_minute)
    end = min(24 * 60, end_minute)
    if end <= start:
        return []
    candidates = list(range(start + 7, end))
    rng.shuffle(candidates)
    selected: list[int] = []
    for candidate in candidates:
        if all(abs(candidate - existing) >= max(0, min_gap_minutes) for existing in selected):
            selected.append(candidate)
            if len(selected) == count:
                break
    selected.sort()
    return [datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute) for minute in selected]

