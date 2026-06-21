import httpx
from datetime import datetime, timedelta, timezone
from database import db

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
FINISHED_STATUSES = {"full time", "ft", "aet", "pen", "finished", "complete", "final", "postponed", "cancelled"}
SAUDI_OFFSET = timedelta(hours=3)  # ESPN returns UTC → نحوله لتوقيت السعودية


def _espn_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _parse_espn_event(event: dict) -> dict | None:
    """Extract match info from ESPN event. Returns None if invalid or finished."""
    comps = event.get("competitions", [{}])
    c = comps[0] if comps else {}
    teams = c.get("competitors", [])
    if len(teams) < 2:
        return None

    home = next((t["team"]["displayName"] for t in teams if t.get("homeAway") == "home"), None)
    away = next((t["team"]["displayName"] for t in teams if t.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    status_desc = c.get("status", {}).get("type", {}).get("description", "").lower()
    if status_desc in FINISHED_STATUSES:
        return None

    raw_date = event.get("date", "")
    if not raw_date:
        return None

    try:
        dt_utc = datetime.strptime(raw_date[:16], "%Y-%m-%dT%H:%M")  # UTC من ESPN
        dt_saudi = dt_utc + SAUDI_OFFSET  # تحويل لتوقيت السعودية
        # لا نستثني المباراة إلا إذا مضى عليها أكثر من ساعتين (هامش للتأخير)
        if dt_utc < datetime.utcnow() - timedelta(hours=2):
            return None
        match_time = dt_saudi.strftime("%Y-%m-%d %H:%M")  # نحفظ توقيت السعودية
    except ValueError:
        return None

    return {"home": home, "away": away, "match_time": match_time, "event_id": event.get("id", "")}


async def fetch_upcoming_matches(days_ahead: int = 30) -> list[dict]:
    """Fetch upcoming World Cup matches from ESPN for the next N days."""
    today = datetime.utcnow()
    end = today + timedelta(days=days_ahead)
    date_range = f"{_espn_date(today)}-{_espn_date(end)}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(ESPN_BASE, params={"dates": date_range})
        resp.raise_for_status()
        data = resp.json()

    events = data.get("events", [])
    matches = []
    seen = set()
    for event in events:
        parsed = _parse_espn_event(event)
        if parsed:
            key = (parsed["home"], parsed["away"], parsed["match_time"])
            if key not in seen:
                matches.append(parsed)
                seen.add(key)

    return matches


def sync_matches_to_db(matches: list[dict]) -> tuple[int, int]:
    """Insert new upcoming matches into DB, skip duplicates. Returns (added, skipped).
    Duplicate check: same team names on same date (ignores time to avoid UTC/Saudi confusion)."""
    added = 0
    skipped = 0

    with db() as conn:
        for m in matches:
            match_date = m["match_time"][:10]  # YYYY-MM-DD فقط
            existing = conn.execute(
                """SELECT id FROM matches
                   WHERE team_home=? AND team_away=?
                   AND DATE(match_time)=?""",
                (m["home"], m["away"], match_date),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            conn.execute(
                "INSERT INTO matches (team_home, team_away, match_time, status) VALUES (?, ?, ?, 'upcoming')",
                (m["home"], m["away"], m["match_time"]),
            )
            added += 1

    return added, skipped


def cleanup_past_unresolved_matches():
    """Mark matches whose time has passed but are still 'upcoming' as 'expired'.
    match_time is stored in Saudi time (UTC+3), so we compare with Saudi now."""
    now_saudi = datetime.utcnow() + SAUDI_OFFSET
    with db() as conn:
        conn.execute(
            "UPDATE matches SET status='expired' WHERE status='upcoming' AND match_time < ?",
            (now_saudi,),
        )
