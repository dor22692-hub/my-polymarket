import httpx
import json
import sqlite3
from datetime import datetime, timezone
from loguru import logger


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_price_list(raw_prices) -> list[float]:
    """
    Gamma API returns outcomePrices as a JSON-encoded string, e.g.:
        '["0.525", "0.475"]'
    This function always returns a plain Python list of floats regardless of
    whether the input is already a list or still a string.
    """
    if isinstance(raw_prices, str):
        try:
            raw_prices = json.loads(raw_prices)
        except (ValueError, TypeError):
            return [0.5, 0.5]
    try:
        return [float(p) for p in (raw_prices or [])]
    except (TypeError, ValueError):
        return [0.5, 0.5]


def _is_future_date(date_str: str) -> bool:
    """Return True if date_str is in the future (or absent / unparseable)."""
    if not date_str:
        return True
    try:
        s = str(date_str).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        end_dt = datetime.fromisoformat(s)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return end_dt >= datetime.now(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return True   # cannot prove expiry → keep the market


# ── Whale Analyzer ────────────────────────────────────────────────────────────

class WhaleAnalyzer:
    @staticmethod
    def calculate_confidence(volume: float, prices: list[float]) -> float:
        """
        Confidence score 0–100.
          60 pts: volume score (saturates at $1 M)
          40 pts: proximity to 50/50 — near-parity means more uncertainty and
                  more opportunity for smart-money to add alpha
        """
        try:
            spread = abs(prices[0] - prices[1]) if len(prices) > 1 else 0.0
            volume_score = min(volume / 1_000_000, 1.0)
            return round((volume_score * 0.6 + (1.0 - spread) * 0.4) * 100, 1)
        except Exception:
            return 50.0

    @staticmethod
    def scenario_analysis(prices: list[float], volume: float) -> dict:
        """Build YES/NO scenario data for the dashboard expander."""
        try:
            yes_prob = prices[0] if prices else 0.5
            no_prob  = prices[1] if len(prices) > 1 else (1.0 - yes_prob)
            spread   = abs(yes_prob - no_prob)

            if spread < 0.10:
                certainty = "נמוכה מאוד — השוק פתוח לגמרי"
            elif spread < 0.30:
                certainty = "בינונית — ייתכן מהפך"
            elif spread < 0.60:
                certainty = "גבוהה — יש כיוון ברור"
            else:
                certainty = "גבוהה מאוד — השוק הכריע"

            if volume >= 1_000_000:
                volume_tier = "🐳 נפח לווייתן ($1M+)"
            elif volume >= 100_000:
                volume_tier = "🐬 נפח גבוה ($100K+)"
            elif volume >= 10_000:
                volume_tier = "🐟 נפח בינוני ($10K+)"
            else:
                volume_tier = "🦐 נפח נמוך"

            return {
                "yes_pct":     round(yes_prob * 100, 1),
                "no_pct":      round(no_prob  * 100, 1),
                "spread":      round(spread, 3),
                "certainty":   certainty,
                "volume_tier": volume_tier,
            }
        except Exception:
            return {
                "yes_pct": 50.0, "no_pct": 50.0, "spread": 0.0,
                "certainty": "לא ידוע", "volume_tier": "לא ידוע",
            }


# ── Database ──────────────────────────────────────────────────────────────────

class PolymarketDB:
    DB_PATH = "polymarket.db"

    @classmethod
    def save_markets(cls, markets: list[dict]) -> None:
        conn = sqlite3.connect(cls.DB_PATH)
        cur  = conn.cursor()

        # DROP + CREATE guarantees the schema is always correct
        cur.execute("DROP TABLE IF EXISTS markets")
        cur.execute("""
            CREATE TABLE markets (
                id          TEXT PRIMARY KEY,
                title       TEXT,
                volume      REAL,
                confidence  REAL,
                yes_pct     REAL,
                no_pct      REAL,
                end_date    TEXT,
                data        TEXT
            )
        """)

        for m in markets:
            cur.execute(
                "INSERT OR REPLACE INTO markets VALUES (?,?,?,?,?,?,?,?)",
                (
                    m["id"], m["title"], m["volume"], m["confidence"],
                    m["yes_pct"], m["no_pct"], m["end_date"],
                    json.dumps(m, ensure_ascii=False),
                ),
            )

        conn.commit()
        conn.close()
        logger.success(f"נשמרו {len(markets)} שווקים ב-polymarket.db")

        # שמור גם ב-Supabase אם מוגדר
        cls._save_to_supabase(markets)

    @classmethod
    def _save_to_supabase(cls, markets: list[dict]) -> None:
        import urllib.request, urllib.parse, os
        from datetime import datetime, timezone
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()
        if not url or not key:
            # נסה לטעון מ-.env
            try:
                from dotenv import load_dotenv
                load_dotenv()
                url = os.getenv("SUPABASE_URL", "").strip()
                key = os.getenv("SUPABASE_KEY", "").strip()
            except Exception:
                pass
        if not url or not key:
            return

        now = datetime.now(timezone.utc).isoformat()
        rows = [{
            "id":         m["id"],
            "title":      m["title"],
            "volume":     m["volume"],
            "confidence": m["confidence"],
            "yes_pct":    m["yes_pct"],
            "no_pct":     m["no_pct"],
            "end_date":   m["end_date"],
            "data":       json.dumps(m, ensure_ascii=False),
            "fetched_at": now,
        } for m in markets]

        # שלח ב-batches של 100
        headers = {
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        for i in range(0, len(rows), 100):
            batch = rows[i:i+100]
            data  = json.dumps(batch).encode()
            req   = urllib.request.Request(
                f"{url}/rest/v1/markets", data=data,
                headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception as e:
                logger.warning(f"Supabase upload batch {i//100}: {e}")
        logger.success(f"✅ {len(markets)} שווקים עודכנו ב-Supabase")


# ── Fetch & Analyse ───────────────────────────────────────────────────────────

def fetch_and_analyze() -> None:
    base = "https://gamma-api.polymarket.com/markets?closed=false&active=true"
    # שלב 1: שווקים פופולריים (לפי נפח)
    url_popular = f"{base}&limit=400&order=volume&ascending=false"
    # שלב 2: שווקים חדשים (לפי תאריך יצירה)
    url_new     = f"{base}&limit=200&order=startDate&ascending=false"

    raw_data: list[dict] = []
    seen_ids: set = set()

    for label, url in [("פופולריים", url_popular), ("חדשים", url_new)]:
        logger.info(f"מושך שווקים {label} מ-Gamma API")
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                batch = resp.json()
                for m in batch:
                    mid = m.get("conditionId") or m.get("id", "")
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        raw_data.append(m)
        except Exception as exc:
            logger.error(f"שגיאה בגישה ל-API ({label}): {exc}")

    logger.info(f"התקבלו {len(raw_data)} שווקים גולמיים מה-API")

    markets: list[dict] = []
    skipped = 0

    for raw in raw_data:
        end_date_str = raw.get("endDate", "")

        # Skip markets that have already expired
        if not _is_future_date(end_date_str):
            skipped += 1
            continue

        # outcomePrices comes as a JSON-encoded string from Gamma — always parse it
        prices = _parse_price_list(raw.get("outcomePrices", '["0.5","0.5"]'))
        if not prices:
            prices = [0.5, 0.5]

        # outcomes also arrives as a JSON-encoded string e.g. '["Yes","No"]'
        outcomes_raw = raw.get("outcomes", '["Yes","No"]')
        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except (ValueError, TypeError):
                outcomes = ["Yes", "No"]
        elif isinstance(outcomes_raw, list):
            outcomes = [str(o) for o in outcomes_raw]
        else:
            outcomes = ["Yes", "No"]

        volume     = float(raw.get("volume", 0) or 0)
        confidence = WhaleAnalyzer.calculate_confidence(volume, prices)
        scenario   = WhaleAnalyzer.scenario_analysis(prices, volume)

        market_id = raw.get("conditionId") or raw.get("id", "")
        if not market_id:
            continue

        slug = raw.get("slug", "")
        events = raw.get("events") or []
        event_slug  = events[0].get("slug",  "") if events else ""
        event_title = events[0].get("title", "") if events else ""
        group_label = raw.get("groupItemTitle", "")

        price_change_1d = float(raw.get("oneDayPriceChange", 0) or 0)
        vol_24h         = float(raw.get("volume24hr", 0) or 0)

        markets.append({
            "id":              market_id,
            "title":           raw.get("question", ""),
            "slug":            slug,
            "event_slug":      event_slug,
            "event_title":     event_title,
            "group_label":     group_label,
            "price_change_1d": round(price_change_1d, 4),
            "vol_24h":         vol_24h,
            "volume":      volume,
            "confidence":  confidence,
            "yes_pct":     scenario["yes_pct"],
            "no_pct":      scenario["no_pct"],
            "end_date":    end_date_str[:10] if end_date_str else "",
            "price":       prices,
            "outcomes":    outcomes,
            "description": raw.get("description", ""),
            "scenario":    scenario,
        })

    if skipped:
        logger.info(f"דולגו {skipped} שווקים שפגו תוקפם")

    if not markets:
        logger.warning("לא נמצאו שווקים חיים — הבדוק את ה-API")
        return

    # Sort by confidence descending before saving
    markets.sort(key=lambda m: m["confidence"], reverse=True)
    PolymarketDB.save_markets(markets)
    logger.success(f"ניתוח הושלם: {len(markets)} שווקים חיים עם ציוני ביטחון.")


if __name__ == "__main__":
    fetch_and_analyze()
