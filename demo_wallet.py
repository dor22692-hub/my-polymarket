"""
ארנק דמו — SQLite מקומי + Supabase REST API בענן (ללא חבילות חיצוניות)
"""
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = "polymarket.db"
STARTING_BALANCE = 1_000.0

# ── Supabase REST helpers ─────────────────────────────────────────────────────

_SUPA_URL = ""
_SUPA_KEY = ""


def _init_supa() -> None:
    global _SUPA_URL, _SUPA_KEY
    if _SUPA_URL:
        return
    try:
        import streamlit as st
        _SUPA_URL = (st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL", "")).strip()
        _SUPA_KEY = (st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY", "")).strip()
    except Exception:
        _SUPA_URL = os.getenv("SUPABASE_URL", "").strip()
        _SUPA_KEY = os.getenv("SUPABASE_KEY", "").strip()


def _use_cloud() -> bool:
    _init_supa()
    return bool(_SUPA_URL and _SUPA_KEY)


def _sb(method: str, table: str, params: dict = None,
        body=None, prefer: str = "return=minimal"):
    """HTTP call to Supabase REST API — no external packages needed."""
    import urllib.request, urllib.parse, json as _j
    _init_supa()
    url = f"{_SUPA_URL}/rest/v1/{table}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "apikey":        _SUPA_KEY,
        "Authorization": f"Bearer {_SUPA_KEY}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "Prefer":        prefer,
    }
    data = _j.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            txt = r.read().decode()
            return _j.loads(txt) if txt.strip() else []
    except Exception:
        return None


def _sb_get(table, filters=None, cols="*", order=None) -> list[dict]:
    p = {"select": cols}
    if filters:
        p.update({k: f"eq.{v}" for k, v in filters.items()})
    if order:
        p["order"] = order
    r = _sb("GET", table, params=p)
    return r if isinstance(r, list) else []


def _sb_post(table, body: dict, upsert=False) -> None:
    prefer = "resolution=merge-duplicates,return=minimal" if upsert else "return=minimal"
    _sb("POST", table, body=body, prefer=prefer)


def _sb_patch(table, filters: dict, body: dict) -> None:
    _sb("PATCH", table, params={k: f"eq.{v}" for k, v in filters.items()},
        body=body)


def _sb_delete(table, filters: dict) -> None:
    _sb("DELETE", table, params={k: f"eq.{v}" for k, v in filters.items()})


# ── SQLite ────────────────────────────────────────────────────────────────────

def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_tables() -> None:
    if _use_cloud():
        return  # טבלאות Supabase נוצרות דרך ה-dashboard
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS demo_wallets (
            username   TEXT PRIMARY KEY,
            balance    REAL NOT NULL DEFAULT 1000.0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demo_positions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL, market_id TEXT NOT NULL,
            market_title  TEXT NOT NULL, group_label TEXT NOT NULL,
            event_title   TEXT NOT NULL DEFAULT '',
            direction     TEXT NOT NULL, amount REAL NOT NULL,
            entry_price   REAL NOT NULL, current_price REAL NOT NULL,
            potential_win REAL NOT NULL, timestamp TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open',
            pnl           REAL NOT NULL DEFAULT 0.0,
            end_date      TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT NOT NULL, market_slug TEXT NOT NULL,
            market_title TEXT NOT NULL, added_at TEXT NOT NULL,
            UNIQUE(username, market_slug)
        );
        """)
        try:
            c.execute("ALTER TABLE demo_positions ADD COLUMN end_date TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass


# ── wallet ────────────────────────────────────────────────────────────────────

def get_wallet(username: str) -> dict | None:
    if _use_cloud():
        rows = _sb_get("demo_wallets", {"username": username})
        return rows[0] if rows else None
    with _conn() as c:
        row = c.execute("SELECT username,balance,created_at FROM demo_wallets WHERE username=?",
                        (username,)).fetchone()
    return {"username": row[0], "balance": row[1], "created_at": row[2]} if row else None


def create_wallet(username: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    if _use_cloud():
        _sb_post("demo_wallets",
                 {"username": username, "balance": STARTING_BALANCE, "created_at": now},
                 upsert=True)
    else:
        with _conn() as c:
            c.execute("INSERT OR IGNORE INTO demo_wallets VALUES (?,?,?)",
                      (username, STARTING_BALANCE, now))
    return get_wallet(username)


def get_or_create(username: str) -> dict:
    result = get_wallet(username) or create_wallet(username)
    if result is None:
        # fallback — מחזיר ברירת מחדל אם Supabase נכשל
        return {"username": username, "balance": STARTING_BALANCE, "created_at": ""}
    return result


def rename_wallet(old: str, new: str) -> bool:
    if get_wallet(new):
        return False
    if _use_cloud():
        _sb_patch("demo_wallets",  {"username": old}, {"username": new})
        _sb_patch("demo_positions",{"username": old}, {"username": new})
        _sb_patch("watchlist",     {"username": old}, {"username": new})
    else:
        with _conn() as c:
            c.execute("UPDATE demo_wallets   SET username=? WHERE username=?", (new, old))
            c.execute("UPDATE demo_positions SET username=? WHERE username=?", (new, old))
            c.execute("UPDATE watchlist      SET username=? WHERE username=?", (new, old))
    return True


def get_all_wallets() -> list[dict]:
    if _use_cloud():
        return _sb_get("demo_wallets", cols="username,balance,created_at", order="username")
    with _conn() as c:
        rows = c.execute("SELECT username,balance,created_at FROM demo_wallets ORDER BY username").fetchall()
    return [{"username": r[0], "balance": r[1], "created_at": r[2]} for r in rows]


def deposit(username: str, amount: float) -> bool:
    if amount <= 0:
        return False
    w = get_wallet(username)
    if not w:
        return False
    if _use_cloud():
        _sb_patch("demo_wallets", {"username": username}, {"balance": w["balance"] + amount})
    else:
        with _conn() as c:
            c.execute("UPDATE demo_wallets SET balance=balance+? WHERE username=?", (amount, username))
    return True


def _add_balance(username: str, delta: float, cur=None) -> None:
    if _use_cloud():
        w = get_wallet(username)
        if w:
            _sb_patch("demo_wallets", {"username": username}, {"balance": w["balance"] + delta})
    else:
        cur.execute("UPDATE demo_wallets SET balance=balance+? WHERE username=?", (delta, username))


# ── positions ─────────────────────────────────────────────────────────────────

def open_position(username, market_id, market_title, group_label, event_title,
                  direction, amount, entry_price, end_date="") -> tuple[bool, str]:
    w = get_wallet(username)
    if not w:                   return False, "ארנק לא נמצא"
    if amount <= 0:             return False, "סכום חייב להיות חיובי"
    if w["balance"] < amount:   return False, f"יתרה לא מספיקה (${w['balance']:.2f})"
    if not (0.001 < entry_price < 0.999): return False, "מחיר לא תקין"

    potential_win = amount / entry_price
    now = datetime.now(timezone.utc).isoformat()

    if _use_cloud():
        _sb_patch("demo_wallets", {"username": username}, {"balance": w["balance"] - amount})
        _sb_post("demo_positions", {
            "username": username, "market_id": market_id,
            "market_title": market_title, "group_label": group_label,
            "event_title": event_title, "direction": direction,
            "amount": amount, "entry_price": entry_price,
            "current_price": entry_price, "potential_win": potential_win,
            "timestamp": now, "status": "open", "pnl": 0.0, "end_date": end_date
        })
    else:
        with _conn() as c:
            _add_balance(username, -amount, c)
            c.execute("""INSERT INTO demo_positions
                (username,market_id,market_title,group_label,event_title,direction,
                 amount,entry_price,current_price,potential_win,timestamp,status,pnl,end_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'open',0,?)""",
                (username, market_id, market_title, group_label, event_title,
                 direction, amount, entry_price, entry_price, potential_win, now, end_date))
    return True, f"✅ קנית {direction.upper()} על '{group_label}' ב-${amount:.2f}"


def _get_position(pos_id: int, username: str) -> dict | None:
    if _use_cloud():
        rows = _sb_get("demo_positions", {"id": pos_id, "username": username})
        return rows[0] if rows else None
    with _conn() as c:
        row = c.execute("SELECT id,amount,potential_win,current_price,status FROM demo_positions WHERE id=? AND username=?",
                        (pos_id, username)).fetchone()
    if not row:
        return None
    return {"id": row[0], "amount": row[1], "potential_win": row[2], "current_price": row[3], "status": row[4]}


def close_position(pos_id: int, username: str, won: bool) -> tuple[bool, str]:
    p = _get_position(pos_id, username)
    if not p:              return False, "פוזיציה לא נמצאה"
    if p["status"] != "open": return False, "פוזיציה כבר סגורה"
    amount, potential_win = p["amount"], p["potential_win"]
    pnl    = potential_win - amount if won else -amount
    refund = potential_win if won else 0.0
    new_cp = 1.0 if won else 0.0
    status = "won" if won else "lost"
    if _use_cloud():
        _sb_patch("demo_positions", {"id": pos_id}, {"status": status, "pnl": pnl, "current_price": new_cp})
        w = get_wallet(username)
        _sb_patch("demo_wallets", {"username": username}, {"balance": w["balance"] + refund})
    else:
        with _conn() as c:
            c.execute("UPDATE demo_positions SET status=?,pnl=?,current_price=? WHERE id=?",
                      (status, pnl, new_cp, pos_id))
            _add_balance(username, refund, c)
    return (True, f"🏆 ניצחת! +${pnl:.2f}") if won else (True, f"❌ הפסדת ${amount:.2f}")


def sell_position(pos_id: int, username: str) -> tuple[bool, str]:
    p = _get_position(pos_id, username)
    if not p:              return False, "פוזיציה לא נמצאה"
    if p["status"] != "open": return False, "פוזיציה כבר סגורה"
    amount, potential_win, cp = p["amount"], p["potential_win"], p["current_price"]
    proceeds = potential_win * cp
    pnl  = proceeds - amount
    won  = pnl > 0
    status = "won" if won else "lost"
    if _use_cloud():
        _sb_patch("demo_positions", {"id": pos_id}, {"status": status, "pnl": pnl, "current_price": cp})
        w = get_wallet(username)
        _sb_patch("demo_wallets", {"username": username}, {"balance": w["balance"] + proceeds})
    else:
        with _conn() as c:
            c.execute("UPDATE demo_positions SET status=?,pnl=?,current_price=? WHERE id=?",
                      (status, pnl, cp, pos_id))
            _add_balance(username, proceeds, c)
    return (True, f"✅ מכרת ברווח! +${pnl:.2f}") if won else (True, f"📉 מכרת בהפסד ${abs(pnl):.2f}")


def get_positions(username: str, status: str | None = None) -> list[dict]:
    keys = ["id","market_id","market_title","group_label","event_title",
            "direction","amount","entry_price","current_price","potential_win",
            "timestamp","status","pnl","end_date"]
    if _use_cloud():
        params = {"select": ",".join(keys), "username": f"eq.{username}", "order": "timestamp.desc"}
        if status:
            params["status"] = f"eq.{status}"
        r = _sb("GET", "demo_positions", params=params)
        return r if isinstance(r, list) else []
    q = (f"SELECT {','.join(keys)} FROM demo_positions WHERE username=?")
    args = [username]
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY timestamp DESC"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(zip(keys, r)) for r in rows]


# ── price sync ────────────────────────────────────────────────────────────────

def _fetch_live_price(market_id: str) -> tuple[float, float] | None:
    import urllib.request, urllib.parse, json as _j

    def _get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return _j.loads(r.read().decode())

    def _best_ask(token_id):
        try:
            req = urllib.request.Request(
                f"https://clob.polymarket.com/book?token_id={token_id}",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                book = _j.loads(r.read().decode())
            asks = book.get("asks", [])
            return float(min(asks, key=lambda x: float(x["price"]))["price"]) if asks else None
        except Exception:
            return None

    market_data = None
    clob_ids = []
    base = "https://gamma-api.polymarket.com/markets"
    for param in [f"slug={urllib.parse.quote(market_id)}",
                  f"conditionIds={market_id}", f"id={market_id}"]:
        try:
            data = _get(f"{base}?{param}")
            if data:
                market_data = data[0] if isinstance(data, list) else data
                raw = market_data.get("clobTokenIds") or []
                if isinstance(raw, str): raw = _j.loads(raw)
                clob_ids = [str(t) for t in raw if t]
                break
        except Exception:
            continue
    if not market_data:
        return None
    if not clob_ids:
        cid = market_data.get("conditionId") or market_data.get("id") or market_id
        try:
            cm = _get(f"https://clob.polymarket.com/markets/{cid}")
            clob_ids = [t.get("token_id","") for t in cm.get("tokens",[]) if t.get("token_id")]
        except Exception:
            pass
    if len(clob_ids) >= 2:
        ya = _best_ask(clob_ids[0])
        na = _best_ask(clob_ids[1])
        if ya and na:
            return ya, na
    raw = market_data.get("outcomePrices","[]")
    prices = _j.loads(raw) if isinstance(raw,str) else raw
    return (float(prices[0]), float(prices[1])) if len(prices) >= 2 else None


def sync_prices(username: str) -> dict[int, float]:
    positions = get_positions(username, "open")
    if not positions: return {}
    live = {}
    for mid in {p["market_id"] for p in positions}:
        r = _fetch_live_price(mid)
        if r: live[mid] = r
    changes = {}
    for p in positions:
        mid = p["market_id"]
        if mid not in live: continue
        yes_p, no_p = live[mid]
        new_price = yes_p if p["direction"]=="yes" else no_p
        if new_price > 0:
            old = p["current_price"]
            if _use_cloud():
                _sb_patch("demo_positions", {"id": p["id"]}, {"current_price": new_price})
            else:
                with _conn() as c:
                    c.execute("UPDATE demo_positions SET current_price=? WHERE id=? AND status='open'",
                              (new_price, p["id"]))
            if old > 0: changes[p["id"]] = (new_price/old - 1)*100
    return changes


def auto_resolve_positions(username: str) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    resolved = 0
    for p in get_positions(username, "open"):
        ed = (p.get("end_date") or "").strip()[:10]
        if not ed or ed > today: continue
        cp = p["current_price"]
        d  = p["direction"]
        if   d=="yes" and cp>=0.95: close_position(p["id"],username,won=True);  resolved+=1
        elif d=="yes" and cp<=0.05: close_position(p["id"],username,won=False); resolved+=1
        elif d=="no"  and cp<=0.05: close_position(p["id"],username,won=True);  resolved+=1
        elif d=="no"  and cp>=0.95: close_position(p["id"],username,won=False); resolved+=1
    return resolved


def update_prices(positions, price_map):
    for p in positions:
        np = price_map.get(f"{p['market_id']}_{p['direction']}", p["current_price"])
        if _use_cloud():
            _sb_patch("demo_positions", {"id": p["id"]}, {"current_price": np})
        else:
            with _conn() as c:
                c.execute("UPDATE demo_positions SET current_price=? WHERE id=? AND status='open'",
                          (np, p["id"]))


# ── statistics ────────────────────────────────────────────────────────────────

def get_stats(username: str) -> dict:
    positions = get_positions(username)
    closed = [p for p in positions if p["status"] != "open"]
    wins   = [p for p in closed   if p["status"] == "won"]
    losses = [p for p in closed   if p["status"] == "lost"]
    open_p = [p for p in positions if p["status"] == "open"]
    ti = sum(p["amount"] for p in closed)
    tp = sum(p["pnl"]    for p in closed)
    oi = sum(p["amount"] for p in open_p)
    ou = sum((p["current_price"]/p["entry_price"]-1)*p["amount"]
             for p in open_p if p["entry_price"]>0)
    return {
        "total_trades":   len(closed),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       len(wins)/len(closed)*100 if closed else 0.0,
        "total_pnl":      tp,
        "roi":            tp/ti*100 if ti>0 else 0.0,
        "open_count":     len(open_p),
        "open_invested":  oi,
        "unrealized_pnl": ou,
        "best_win":       max((p["pnl"] for p in wins),   default=0.0),
        "worst_loss":     min((p["pnl"] for p in losses), default=0.0),
    }


# ── watchlist ─────────────────────────────────────────────────────────────────

def watchlist_add(username: str, slug: str, title: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    try:
        if _use_cloud():
            _sb_post("watchlist",
                     {"username": username, "market_slug": slug,
                      "market_title": title, "added_at": now},
                     upsert=True)
        else:
            with _conn() as c:
                c.execute("INSERT OR IGNORE INTO watchlist (username,market_slug,market_title,added_at) VALUES (?,?,?,?)",
                          (username, slug, title, now))
        return True
    except Exception:
        return False


def watchlist_remove(username: str, slug: str) -> bool:
    if _use_cloud():
        _sb_delete("watchlist", {"username": username, "market_slug": slug})
    else:
        with _conn() as c:
            c.execute("DELETE FROM watchlist WHERE username=? AND market_slug=?", (username, slug))
    return True


def watchlist_get(username: str) -> list[dict]:
    if _use_cloud():
        rows = _sb_get("watchlist", {"username": username},
                       cols="market_slug,market_title,added_at", order="added_at.desc")
        return [{"slug": r["market_slug"], "title": r["market_title"], "added_at": r["added_at"]}
                for r in rows]
    with _conn() as c:
        rows = c.execute("SELECT market_slug,market_title,added_at FROM watchlist WHERE username=? ORDER BY added_at DESC",
                         (username,)).fetchall()
    return [{"slug": r[0], "title": r[1], "added_at": r[2]} for r in rows]


def watchlist_has(username: str, slug: str) -> bool:
    if _use_cloud():
        return bool(_sb_get("watchlist", {"username": username, "market_slug": slug},
                            cols="market_slug"))
    with _conn() as c:
        return bool(c.execute("SELECT 1 FROM watchlist WHERE username=? AND market_slug=?",
                               (username, slug)).fetchone())
