import httpx
from datetime import datetime, timezone
from database import db

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
WORLD_CUP_LEAGUE_ID = "4429"


def _is_finished(event: dict) -> bool:
    """Return True if the match already has a result (played)."""
    home_score = event.get("intHomeScore")
    away_score = event.get("intAwayScore")
    status = (event.get("strStatus") or "").lower()
    finished_keywords = {"ft", "aet", "pen", "finished", "complete", "مكتمل"}
    if status in finished_keywords:
        return True
    if home_score not in (None, "", "null") and away_score not in (None, "", "null"):
        try:
            int(home_score)
            int(away_score)
            return True
        except (ValueError, TypeError):
            pass
    return False


def _is_past_date(date_str: str, time_str: str) -> bool:
    """Return True if the match date+time is strictly in the past."""
    if not date_str:
        return False
    try:
        time_part = (time_str or "00:00")[:5]
        dt = datetime.strptime(f"{date_str} {time_part}", "%Y-%m-%d %H:%M")
        now = datetime.utcnow()
        return dt < now
    except ValueError:
        return False


async def fetch_upcoming_matches() -> list[dict]:
    """Fetch upcoming World Cup matches from TheSportsDB (not yet played)."""
    results = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{THESPORTSDB_BASE}/eventsnextleague.php",
            params={"id": WORLD_CUP_LEAGUE_ID},
        )
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events") or []
        results.extend(events)

        resp2 = await client.get(
            f"{THESPORTSDB_BASE}/eventsseason.php",
            params={"id": WORLD_CUP_LEAGUE_ID, "s": "2026"},
        )
        resp2.raise_for_status()
        data2 = resp2.json()
        events2 = data2.get("events") or []
        seen_ids = {e.get("idEvent") for e in results}
        for e in events2:
            if e.get("idEvent") not in seen_ids:
                results.append(e)
                seen_ids.add(e.get("idEvent"))

    upcoming = [
        e for e in results
        if not _is_finished(e) and not _is_past_date(
            e.get("dateEvent", ""),
            e.get("strTime", "") or e.get("strTimeLocal", ""),
        )
    ]
    return upcoming


def parse_match_time(date_str: str, time_str: str) -> str:
    """Convert TheSportsDB date+time to DB format YYYY-MM-DD HH:MM."""
    if not date_str:
        return ""
    time_part = "00:00"
    if time_str:
        time_part = time_str[:5]
    return f"{date_str} {time_part}"


def sync_matches_to_db(events: list[dict]) -> tuple[int, int]:
    """Insert new upcoming matches into DB, skip duplicates. Returns (added, skipped)."""
    added = 0
    skipped = 0

    with db() as conn:
        for event in events:
            home = event.get("strHomeTeam", "").strip()
            away = event.get("strAwayTeam", "").strip()
            date_str = event.get("dateEvent", "")
            time_str = event.get("strTime", "") or event.get("strTimeLocal", "")
            match_time = parse_match_time(date_str, time_str)

            if not home or not away or not match_time:
                skipped += 1
                continue

            existing = conn.execute(
                "SELECT id FROM matches WHERE team_home=? AND team_away=? AND match_time=?",
                (home, away, match_time),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            conn.execute(
                "INSERT INTO matches (team_home, team_away, match_time, status) VALUES (?, ?, ?, 'upcoming')",
                (home, away, match_time),
            )
            added += 1

    return added, skipped


def cleanup_past_unresolved_matches():
    """Mark matches whose date has passed but are still 'upcoming' as 'expired'."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        conn.execute(
            "UPDATE matches SET status='expired' WHERE status='upcoming' AND match_time < ?",
            (now,),
        )
