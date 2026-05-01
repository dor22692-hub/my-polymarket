"""
ארנק דמו — מסחר סימולציה על Polymarket
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "polymarket.db"
STARTING_BALANCE = 1_000.0


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_tables() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS demo_wallets (
            username   TEXT PRIMARY KEY,
            balance    REAL NOT NULL DEFAULT 1000.0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS demo_positions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL,
            market_id     TEXT    NOT NULL,
            market_title  TEXT    NOT NULL,
            group_label   TEXT    NOT NULL,
            event_title   TEXT    NOT NULL DEFAULT '',
            direction     TEXT    NOT NULL,
            amount        REAL    NOT NULL,
            entry_price   REAL    NOT NULL,
            current_price REAL    NOT NULL,
            potential_win REAL    NOT NULL,
            timestamp     TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'open',
            pnl           REAL    NOT NULL DEFAULT 0.0,
            end_date      TEXT    NOT NULL DEFAULT ''
        );
        """)
        # Migration: add end_date column if it doesn't exist yet
        try:
            c.execute("ALTER TABLE demo_positions ADD COLUMN end_date TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # Column already exists

        # Watchlist table
        c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL,
            market_slug  TEXT NOT NULL,
            market_title TEXT NOT NULL,
            added_at     TEXT NOT NULL,
            UNIQUE(username, market_slug)
        )""")


# ── watchlist ─────────────────────────────────────────────────────────────────

def watchlist_add(username: str, slug: str, title: str) -> bool:
    try:
        now = datetime.now(timezone.utc).isoformat()
        with _conn() as c:
            c.execute("INSERT OR IGNORE INTO watchlist (username,market_slug,market_title,added_at) VALUES (?,?,?,?)",
                      (username, slug, title, now))
        return True
    except Exception:
        return False

def watchlist_remove(username: str, slug: str) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE username=? AND market_slug=?", (username, slug))
    return True

def watchlist_get(username: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT market_slug, market_title, added_at FROM watchlist WHERE username=? ORDER BY added_at DESC",
            (username,)
        ).fetchall()
    return [{"slug": r[0], "title": r[1], "added_at": r[2]} for r in rows]

def watchlist_has(username: str, slug: str) -> bool:
    with _conn() as c:
        return bool(c.execute(
            "SELECT 1 FROM watchlist WHERE username=? AND market_slug=?", (username, slug)
        ).fetchone())


# ── wallet ────────────────────────────────────────────────────────────────────

def get_wallet(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT username, balance, created_at FROM demo_wallets WHERE username=?",
            (username,)
        ).fetchone()
    if row:
        return {"username": row[0], "balance": row[1], "created_at": row[2]}
    return None


def create_wallet(username: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO demo_wallets VALUES (?,?,?)",
            (username, STARTING_BALANCE, now)
        )
    return get_wallet(username)


def get_or_create(username: str) -> dict:
    return get_wallet(username) or create_wallet(username)


def rename_wallet(old: str, new: str) -> bool:
    if get_wallet(new):
        return False
    with _conn() as c:
        c.execute("UPDATE demo_wallets   SET username=? WHERE username=?", (new, old))
        c.execute("UPDATE demo_positions SET username=? WHERE username=?", (new, old))
    return True


def get_all_wallets() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT username, balance, created_at FROM demo_wallets ORDER BY username"
        ).fetchall()
    return [{"username": r[0], "balance": r[1], "created_at": r[2]} for r in rows]


def deposit(username: str, amount: float) -> bool:
    if amount <= 0:
        return False
    with _conn() as c:
        c.execute(
            "UPDATE demo_wallets SET balance = balance + ? WHERE username=?",
            (amount, username)
        )
    return True


def _update_balance(username: str, delta: float, cur) -> None:
    cur.execute(
        "UPDATE demo_wallets SET balance = balance + ? WHERE username=?",
        (delta, username)
    )


# ── positions ─────────────────────────────────────────────────────────────────

def open_position(
    username: str,
    market_id: str,
    market_title: str,
    group_label: str,
    event_title: str,
    direction: str,
    amount: float,
    entry_price: float,
    end_date: str = "",
) -> tuple[bool, str]:
    wallet = get_wallet(username)
    if not wallet:
        return False, "ארנק לא נמצא"
    if amount <= 0:
        return False, "סכום חייב להיות חיובי"
    if wallet["balance"] < amount:
        return False, f"יתרה לא מספיקה (${wallet['balance']:.2f})"
    if not (0.001 < entry_price < 0.999):
        return False, "מחיר לא תקין"

    potential_win = amount / entry_price
    now = datetime.now(timezone.utc).isoformat()

    with _conn() as c:
        _update_balance(username, -amount, c)
        c.execute("""
            INSERT INTO demo_positions
              (username,market_id,market_title,group_label,event_title,
               direction,amount,entry_price,current_price,potential_win,timestamp,status,pnl,end_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',0,?)
        """, (username, market_id, market_title, group_label, event_title,
              direction, amount, entry_price, entry_price, potential_win, now, end_date))

    return True, f"✅ קנית {direction.upper()} על '{group_label}' ב-${amount:.2f}"


def close_position(pos_id: int, username: str, won: bool) -> tuple[bool, str]:
    with _conn() as c:
        row = c.execute(
            "SELECT amount, potential_win, status FROM demo_positions WHERE id=? AND username=?",
            (pos_id, username)
        ).fetchone()
        if not row:
            return False, "פוזיציה לא נמצאה"
        if row[2] != "open":
            return False, "פוזיציה כבר סגורה"
        amount, potential_win, _ = row
        pnl    = potential_win - amount if won else -amount
        status = "won" if won else "lost"
        refund = potential_win if won else 0.0
        c.execute(
            "UPDATE demo_positions SET status=?, pnl=?, current_price=? WHERE id=?",
            (status, pnl, (1.0 if won else 0.0), pos_id)
        )
        _update_balance(username, refund, c)
    msg = f"🏆 ניצחת! +${pnl:.2f}" if won else f"❌ הפסדת ${amount:.2f}"
    return True, msg


def sell_position(pos_id: int, username: str) -> tuple[bool, str]:
    """מוכר פוזיציה במחיר השוק הנוכחי."""
    with _conn() as c:
        row = c.execute(
            "SELECT amount, potential_win, current_price, status FROM demo_positions WHERE id=? AND username=?",
            (pos_id, username)
        ).fetchone()
        if not row:
            return False, "פוזיציה לא נמצאה"
        if row[3] != "open":
            return False, "פוזיציה כבר סגורה"
        amount, potential_win, current_price, _ = row
        # proceeds = shares_bought * current_price = potential_win * current_price
        proceeds = potential_win * current_price
        pnl = proceeds - amount
        won = pnl > 0
        status = "won" if won else "lost"
        c.execute(
            "UPDATE demo_positions SET status=?, pnl=?, current_price=? WHERE id=?",
            (status, pnl, current_price, pos_id)
        )
        _update_balance(username, proceeds, c)
    if won:
        return True, f"✅ מכרת ברווח! +${pnl:.2f}"
    return True, f"📉 מכרת בהפסד ${abs(pnl):.2f}"


def _clob_best_ask(token_id: str) -> float | None:
    """מביא מחיר Ask הטוב ביותר מה-Order Book של CLOB."""
    import urllib.request
    import json as _json
    try:
        req = urllib.request.Request(
            f"https://clob.polymarket.com/book?token_id={token_id}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            book = _json.loads(resp.read().decode())
        asks = book.get("asks", [])
        if asks:
            return float(min(asks, key=lambda x: float(x["price"]))["price"])
    except Exception:
        pass
    return None


def _fetch_live_price(market_id: str) -> tuple[float, float] | None:
    """
    מביא מחיר Yes/No עדכני — Ask אמיתי מה-CLOB (זהה ל-UI של Polymarket).
    סדר: Gamma markets → CLOB (אם יש token_ids) → mid price כ-fallback.
    """
    import urllib.request, urllib.parse
    import json as _json

    def _get(url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return _json.loads(r.read().decode())

    market_data = None
    clob_ids: list[str] = []

    # שלב 1: Gamma markets endpoint
    base = "https://gamma-api.polymarket.com/markets"
    for param in [f"slug={urllib.parse.quote(market_id)}",
                  f"conditionIds={market_id}",
                  f"id={market_id}"]:
        try:
            data = _get(f"{base}?{param}")
            if data:
                market_data = data[0] if isinstance(data, list) else data
                raw_ids = market_data.get("clobTokenIds") or []
                # clobTokenIds עשוי להגיע כ-string JSON
                if isinstance(raw_ids, str):
                    raw_ids = _json.loads(raw_ids)
                clob_ids = [str(t) for t in raw_ids if t]
                break
        except Exception:
            continue

    if not market_data:
        return None

    # שלב 2: אם אין clobTokenIds מ-Gamma, חפש דרך CLOB markets endpoint
    if not clob_ids:
        condition_id = market_data.get("conditionId") or market_data.get("id") or market_id
        try:
            clob_market = _get(f"https://clob.polymarket.com/markets/{condition_id}")
            clob_ids = [
                clob_market.get("tokens", [{}])[0].get("token_id", ""),
                clob_market.get("tokens", [{}])[-1].get("token_id", ""),
            ] if clob_market.get("tokens") else []
        except Exception:
            pass

    # שלב 3: CLOB ask prices (זהים ל-UI של Polymarket)
    if len(clob_ids) >= 2 and clob_ids[0]:
        yes_ask = _clob_best_ask(clob_ids[0])
        no_ask  = _clob_best_ask(clob_ids[1])
        if yes_ask and no_ask:
            return yes_ask, no_ask

    # token_ids מ-Gamma
    tokens = market_data.get("tokens") or []
    if len(tokens) >= 2:
        yes_ask = _clob_best_ask(tokens[0].get("token_id", ""))
        no_ask  = _clob_best_ask(tokens[1].get("token_id", ""))
        if yes_ask and no_ask:
            return yes_ask, no_ask

    # Fallback: mid price מ-Gamma
    raw    = market_data.get("outcomePrices", "[]")
    prices = _json.loads(raw) if isinstance(raw, str) else raw
    if len(prices) >= 2:
        return float(prices[0]), float(prices[1])

    return None


def sync_prices(username: str) -> dict[int, float]:
    """
    מסנכרן מחירים עדכניים לפוזיציות הפתוחות.
    סדר עדיפויות: Gamma API (real-time) → DB מקומי.
    מחזיר dict של {pos_id: שינוי_אחוזי} לצורך הצגה.
    """
    positions = get_positions(username, "open")
    if not positions:
        return {}

    # קיבוץ לפי market_id כדי למנוע קריאות כפולות
    market_ids = list({p["market_id"] for p in positions})
    live_prices: dict[str, tuple[float, float]] = {}

    for mid in market_ids:
        result = _fetch_live_price(mid)
        if result:
            live_prices[mid] = result

    changes: dict[int, float] = {}
    with _conn() as c:
        for p in positions:
            mid = p["market_id"]
            direction = p["direction"]

            # נסה מחיר חי מה-API
            if mid in live_prices:
                yes_p, no_p = live_prices[mid]
                new_price = yes_p if direction == "yes" else no_p
            else:
                # fallback: DB מקומי — נסה לפי id ואחר כך לפי slug בתוך data JSON
                row = c.execute(
                    "SELECT yes_pct, no_pct FROM markets WHERE id=?", (mid,)
                ).fetchone()
                if not row:
                    row = c.execute(
                        "SELECT yes_pct, no_pct FROM markets "
                        "WHERE data LIKE ? OR data LIKE ?",
                        (f'%"slug": "{mid}"%', f'%"slug":"{mid}"%')
                    ).fetchone()
                if row and row[0] is not None:
                    new_price = (row[0] / 100.0) if direction == "yes" else (row[1] / 100.0)
                else:
                    continue

            if new_price > 0:
                old_price = p["current_price"]
                c.execute(
                    "UPDATE demo_positions SET current_price=? WHERE id=? AND status='open'",
                    (new_price, p["id"])
                )
                if old_price > 0:
                    changes[p["id"]] = (new_price / old_price - 1) * 100

    return changes


def auto_resolve_positions(username: str) -> int:
    """סוגר אוטומטית פוזיציות שהשוק שלהן פג תוקף עם תוצאה ברורה (>95% או <5%)."""
    today = datetime.now(timezone.utc).date().isoformat()
    positions = get_positions(username, "open")
    resolved = 0
    for p in positions:
        end_date = (p.get("end_date") or "").strip()[:10]
        if not end_date or end_date > today:
            continue
        current_price = p["current_price"]
        direction = p["direction"]
        if direction == "yes":
            if current_price >= 0.95:
                close_position(p["id"], username, won=True)
                resolved += 1
            elif current_price <= 0.05:
                close_position(p["id"], username, won=False)
                resolved += 1
        else:  # "no"
            if current_price <= 0.05:
                close_position(p["id"], username, won=True)
                resolved += 1
            elif current_price >= 0.95:
                close_position(p["id"], username, won=False)
                resolved += 1
    return resolved


def update_prices(positions: list[dict], price_map: dict[str, float]) -> None:
    with _conn() as c:
        for p in positions:
            key = f"{p['market_id']}_{p['direction']}"
            new_price = price_map.get(key, p["current_price"])
            c.execute(
                "UPDATE demo_positions SET current_price=? WHERE id=? AND status='open'",
                (new_price, p["id"])
            )


def get_positions(username: str, status: str | None = None) -> list[dict]:
    q = """SELECT id,market_id,market_title,group_label,event_title,direction,amount,
                  entry_price,current_price,potential_win,timestamp,status,pnl,end_date
           FROM demo_positions WHERE username=?"""
    args: list = [username]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY timestamp DESC"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    keys = ["id", "market_id", "market_title", "group_label", "event_title",
            "direction", "amount", "entry_price", "current_price", "potential_win",
            "timestamp", "status", "pnl", "end_date"]
    return [dict(zip(keys, r)) for r in rows]


# ── statistics ────────────────────────────────────────────────────────────────

def get_stats(username: str) -> dict:
    positions = get_positions(username)
    closed = [p for p in positions if p["status"] != "open"]
    wins   = [p for p in closed if p["status"] == "won"]
    losses = [p for p in closed if p["status"] == "lost"]
    open_p = [p for p in positions if p["status"] == "open"]

    total_invested  = sum(p["amount"] for p in closed)
    total_pnl       = sum(p["pnl"]    for p in closed)
    open_invested   = sum(p["amount"] for p in open_p)
    open_unrealized = sum(
        (p["current_price"] / p["entry_price"] - 1) * p["amount"]
        for p in open_p if p["entry_price"] > 0
    )

    return {
        "total_trades":   len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       len(wins) / len(closed) * 100 if closed else 0.0,
        "total_pnl":      total_pnl,
        "roi":            total_pnl / total_invested * 100 if total_invested > 0 else 0.0,
        "open_count":     len(open_p),
        "open_invested":  open_invested,
        "unrealized_pnl": open_unrealized,
        "best_win":       max((p["pnl"] for p in wins),   default=0.0),
        "worst_loss":     min((p["pnl"] for p in losses), default=0.0),
    }
