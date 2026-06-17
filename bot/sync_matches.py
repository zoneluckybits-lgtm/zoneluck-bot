import httpx
from database import db

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
WORLD_CUP_LEAGUE_ID = "4429"


async def fetch_upcoming_matches() -> list[dict]:
    """Fetch upcoming World Cup matches from TheSportsDB."""
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

    return results


def parse_match_time(date_str: str, time_str: str) -> str:
    """Convert TheSportsDB date+time to DB format YYYY-MM-DD HH:MM."""
    if not date_str:
        return ""
    time_part = "00:00"
    if time_str:
        time_part = time_str[:5]
    return f"{date_str} {time_part}"


def sync_matches_to_db(events: list[dict]) -> tuple[int, int]:
    """Insert new matches into DB, skip duplicates. Returns (added, skipped)."""
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
