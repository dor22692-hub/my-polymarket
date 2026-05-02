"""
מודיעין לווייתנים | Polymarket — לוח בקרה
הרצה:   streamlit run dashboard.py
עדכון:  python main.py
"""
import sqlite3
import json
import html as _html
from datetime import datetime

import pandas as pd
import streamlit as st
import demo_wallet as dw
import arbitrage_scanner as arb

dw.init_tables()

# ── תרגום (deep-translator — batch מובנה) ────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _batch_translate_api(texts_tuple: tuple) -> dict:
    """מתרגם כל הכותרות בבת אחת עם deep-translator."""
    if not texts_tuple:
        return {}
    try:
        from deep_translator import GoogleTranslator
        texts = list(texts_tuple)
        translated = GoogleTranslator(source="auto", target="iw").translate_batch(texts)
        if translated and len(translated) == len(texts):
            return {orig: (tr or orig) for orig, tr in zip(texts, translated)}
    except Exception:
        pass
    return {t: t for t in texts_tuple}


def maybe_translate(text: str) -> str:
    if not text or not st.session_state.get("translate_on", False):
        return text
    return st.session_state.get("_trans", {}).get(text, text)

# ── הגדרות עמוד ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="🐋 מודיעין לווייתנים | Polymarket",
    page_icon="🐋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.html("""
<style>
html, body, .stApp {
    direction: rtl;
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
}
.main .block-container { direction: rtl; padding-top: 1.2rem; padding-bottom: 2rem; }
.stMarkdown, .stMarkdown p, .stMarkdown li,
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 { direction: rtl; text-align: right; }
[data-testid="stSidebar"] { direction: rtl; }
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div { text-align: right; }
[data-testid="stSidebar"] .stButton > button { width: 100%; }
[data-testid="stMetric"] {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 12px;
    padding: 14px 18px;
    direction: rtl;
}
[data-testid="stMetricLabel"] { font-size: 12px; color: #888 !important; text-align: right; }
[data-testid="stMetricValue"] { font-size: 24px; font-weight: 700; text-align: right; }
[data-testid="stExpander"] {
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    margin-bottom: 8px !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    font-size: 14px !important;
    font-weight: 600 !important;
    padding: 10px 16px !important;
    direction: rtl;
}
[data-testid="stTabs"] { direction: rtl; }
[data-testid="stTabs"] button { font-size: 13px !important; font-weight: 600 !important; }
[data-testid="stHorizontalBlock"] { flex-direction: row-reverse; }
[data-testid="stAlert"] { direction: rtl; text-align: right; }
[data-testid="stCaptionContainer"] p { text-align: right; direction: rtl; }
[data-testid="stDivider"] { margin: 0.4rem 0; opacity: 0.2; }
</style>
""")

# ── קבועים ───────────────────────────────────────────────────────────────────

DB_PATH = "polymarket.db"

# ── עזרי נתונים ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def load_markets() -> pd.DataFrame:
    # נסה לטעון מ-Supabase (ענן)
    try:
        import urllib.request, urllib.parse
        import json as _j
        supa_url = st.secrets.get("SUPABASE_URL", "") or ""
        supa_key = st.secrets.get("SUPABASE_KEY", "") or ""
        if supa_url and supa_key:
            params = urllib.parse.urlencode({
                "select": "id,title,volume,confidence,yes_pct,no_pct,end_date,data",
                "order": "confidence.desc",
                "limit": "600"
            })
            req = urllib.request.Request(
                f"{supa_url}/rest/v1/markets?{params}",
                headers={"apikey": supa_key, "Authorization": f"Bearer {supa_key}",
                         "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                rows = _j.loads(r.read().decode())
            if rows:
                return pd.DataFrame(rows)
    except Exception:
        pass
    # Fallback — SQLite מקומי
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM markets ORDER BY confidence DESC", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def fetch_expiring_soon(days: int = 20) -> dict:
    """מביא מ-Gamma API שווקים שפגים ב-X ימים, מקובצים לפי אירוע."""
    import requests
    from datetime import timezone, timedelta
    try:
        cutoff  = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"active": "true", "closed": "false",
                    "end_date_max": cutoff, "end_date_min": now_str, "limit": 300},
            timeout=12,
        )
        if not r.ok:
            return {}
        raw_markets = r.json()
    except Exception:
        return {}

    from datetime import timezone
    events: dict[str, dict] = {}   # ev_key → event dict
    standalone: list[dict]  = []

    for m in raw_markets:
        try:
            end_raw    = m.get("endDate", "") or ""
            end_dt     = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            if hours_left < 0:
                continue

            volume = float(m.get("volume", 0) or 0)
            if volume < 500_000:
                continue

            # מחירים ותוצאות
            prices_raw   = m.get("outcomePrices", "[]")
            outcomes_raw = m.get("outcomes", "[]")
            prices   = [float(p) for p in (json.loads(prices_raw)   if isinstance(prices_raw,   str) else prices_raw)]
            outcomes = [(o)      for o in (json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw)]
            if not outcomes:
                outcomes = ["Yes", "No"] if len(prices) == 2 else [f"תוצאה {i+1}" for i in range(len(prices))]
            n = min(len(outcomes), len(prices))
            prices, outcomes = prices[:n], outcomes[:n]

            ev_slug   = str(m.get("event_slug",  "") or "")
            ev_title  = str(m.get("event_title", "") or m.get("question", ""))
            group_lbl = str(m.get("groupItemTitle", "") or m.get("question", ""))
            slug      = str(m.get("slug", "") or "")

            yes_p = prices[0] if prices else 0.5
            conf  = abs(yes_p - 0.5) * 200  # confidence proxy 0-100

            market_info = {
                # שדות בסיסיים
                "title":          m.get("question", ""),
                "group_lbl":      group_lbl,
                "prices":         prices,
                "outcomes":       outcomes,
                "volume":         volume,
                "slug":           slug,
                "ev_slug":        ev_slug,
                "hours_left":     hours_left,
                "end_date":       end_dt.strftime("%Y-%m-%d"),
                # שדות נדרשים ע"י פונקציות קיימות
                "conf":           conf,
                "scenario":       {},
                "desc":           str(m.get("description", "") or ""),
                "price_change_1d": float(m.get("oneDayPriceChange", 0) or 0),
                "vol_24h":        float(m.get("volume24hr", 0) or 0),
                "rec":            get_recommendation(prices, outcomes, conf),
            }

            if ev_slug:
                if ev_slug not in events:
                    events[ev_slug] = {
                        "ev_title":   ev_title,
                        "ev_slug":    ev_slug,
                        "hours_left": hours_left,
                        "end_date":   end_dt.strftime("%Y-%m-%d"),
                        "markets":    [],
                    }
                events[ev_slug]["markets"].append(market_info)
                # שמור את הזמן הקרוב ביותר לקבוצה
                events[ev_slug]["hours_left"] = min(events[ev_slug]["hours_left"], hours_left)
            else:
                standalone.append(market_info)
        except Exception:
            continue

    return {
        "events":     sorted(events.values(), key=lambda e: e["hours_left"]),
        "standalone": sorted(standalone,      key=lambda m: m["hours_left"]),
    }


def _time_badge(hours: float) -> tuple[str, str]:
    """מחזיר (תווית_זמן, צבע_border)."""
    d = hours / 24
    if hours < 24:
        return f"🔴 {hours:.0f}ש׳", "#ff4455"
    if d < 3:
        return f"🟠 {d:.1f} ימים", "#ff8c00"
    if d < 7:
        return f"🟡 {d:.1f} ימים", "#ffbb00"
    return f"🟢 {d:.0f} ימים", "#00cc66"


def _expiring_scenarios_table(markets: list[dict]) -> None:
    """טבלת תרחישים עם st.dataframe — אמינה בכל גרסאות Streamlit."""
    rows = []
    for m in sorted(markets, key=lambda x: x["prices"][0] if x["prices"] else 0, reverse=True):
        yes_p = m["prices"][0] if m["prices"] else 0.5
        no_p  = max(0.0, 1.0 - yes_p)
        rows.append({
            "תרחיש":    maybe_translate(m["group_lbl"]) or m["title"],
            "סיכוי %":  f"{yes_p*100:.0f}%",
            "Buy Yes":  fmt_cents(yes_p),
            "Buy No":   fmt_cents(no_p),
            "נפח":      fmt_vol(m["volume"]),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _flatten_markets(markets: list[dict]) -> list[dict]:
    """
    ממיר markets שיש להם outcomes מרובים לשורות נפרדות,
    כך שכל outcome יוצג כ-market עצמאי בטבלה.
    """
    result = []
    for m in markets:
        outcomes = m.get("outcomes", [])
        prices   = m.get("prices",   [])
        # שוק בינארי רגיל — השאר כמו שהוא
        if len(outcomes) <= 2:
            result.append(m)
            continue
        # שוק multi-outcome — פרק לשורה לכל outcome
        total_vol = m.get("volume", 0)
        for i, (outcome, price) in enumerate(zip(outcomes, prices)):
            share = price / sum(prices) if sum(prices) > 0 else 1 / len(prices)
            result.append({
                **m,
                "group_lbl": maybe_translate(str(outcome)),
                "prices":    [float(price), max(0.0, 1.0 - float(price))],
                "outcomes":  [str(outcome), "No"],
                "volume":    total_vol * share,
            })
    return result


def _expiring_event_body(ev_title: str, ev_slug: str, end_date: str,
                         time_str: str, total_vol: float,
                         poly_url: str, markets: list[dict]) -> None:
    """גוף expander עם 3 לשוניות — זהה לעמוד השווקים הרגיל."""
    ev_title = maybe_translate(ev_title)
    st.html(f"""
<div style="margin:4px 0 12px;direction:rtl">
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.14);
              border-radius:10px;padding:12px 18px;margin-bottom:10px">
    <span style="color:#fff;font-size:18px;font-weight:800">{_html.escape(ev_title)}</span>
    <div style="color:#555;font-size:11px;margin-top:4px">
      {fmt_vol(total_vol)} Vol. &nbsp;·&nbsp; תפוגה: {end_date}
      &nbsp;·&nbsp; <span style="color:#ffbb00;font-weight:700">{time_str}</span>
    </div>
  </div>
  <a href="{poly_url}" target="_blank"
     style="display:inline-flex;align-items:center;gap:6px;
            background:rgba(0,204,102,0.12);color:#00cc66;
            border:1px solid rgba(0,204,102,0.3);border-radius:8px;
            padding:7px 14px;font-size:13px;font-weight:700;text-decoration:none">
    🔗 פתח בפולימרקט
  </a>
</div>""")

    # פרק כל market multi-outcome לשורות נפרדות
    flat_markets = _flatten_markets(markets)
    sorted_m = sorted(flat_markets, key=lambda m: m["prices"][0] if m["prices"] else 0, reverse=True)

    # Radio במקום tabs/expanders מקוננים — מונע את שגיאת React removeChild
    view = st.radio(
        "",
        ["📋 תרחישים", "🐋 לווייתנים", "💼 קנה/מכור"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"exp_view_{ev_slug}",
    )

    if view == "📋 תרחישים":
        _expiring_scenarios_table(sorted_m)
        st.caption(f"📊 {len(flat_markets)} תרחישים · ממוין לפי הסתברות")
    elif view == "🐋 לווייתנים":
        ui_event_whale_tab(flat_markets)
    else:
        ui_trade_tab(ev_slug, ev_title, flat_markets)


def ui_expiring_soon(days: int = 20) -> None:
    st.html(f"""
<div style="direction:rtl;margin-bottom:8px">
  <h1 style="font-size:1.8rem;font-weight:800;margin:0">⏰ פגים ב-{days} ימים הקרובים</h1>
  <p style="color:#666;font-size:13px;margin-top:4px">
    ממוין לפי זמן שנותר · נתונים ישירות מ-Gamma API · מתרענן כל 2 דקות
  </p>
</div>""")

    with st.spinner("מביא שווקים..."):
        data = fetch_expiring_soon(days)

    events     = data.get("events", [])
    standalone = data.get("standalone", [])
    total      = len(events) + len(standalone)

    # ── תרגום: אסוף כל הטקסטים ותרגם בבת אחת ──────────────────────────────
    if st.session_state.get("translate_on", False):
        _exp_texts: set[str] = set()
        for _ev in events:
            _exp_texts.add(_ev.get("ev_title", ""))
            for _m in _ev.get("markets", []):
                _exp_texts.discard("")
                _exp_texts.update([_m.get("title", ""), _m.get("group_lbl", "")])
        for _m in standalone:
            _exp_texts.update([_m.get("title", ""), _m.get("group_lbl", "")])
        _exp_texts.discard("")
        existing = st.session_state.get("_trans", {})
        new_texts = tuple(t for t in sorted(_exp_texts) if t not in existing)
        if new_texts:
            with st.spinner("מתרגם כותרות..."):
                existing.update(_batch_translate_api(new_texts))
                st.session_state["_trans"] = existing

    if total == 0:
        st.info(f"לא נמצאו שווקים פעילים שפגים ב-{days} ימים הקרובים.")
        return

    st.caption(f"נמצאו **{total}** אירועים / שווקים")
    st.divider()

    # ── אירועים מקובצים ──────────────────────────────────────────────────────
    for ev in events:
        time_str, _ = _time_badge(ev["hours_left"])
        total_vol   = sum(m["volume"] for m in ev["markets"])
        poly_url    = f"https://polymarket.com/event/{ev['ev_slug']}"
        ev_title_d  = maybe_translate(ev["ev_title"])

        header = (
            f"{time_str}  │  {ev_title_d[:65]}{'…' if len(ev_title_d) > 65 else ''}  "
            f"│  {len(ev['markets'])} תרחישים  │  {fmt_vol(total_vol)}"
        )
        with st.expander(header, expanded=False):
            _expiring_event_body(ev["ev_title"], ev["ev_slug"], ev["end_date"],
                                 time_str, total_vol, poly_url, ev["markets"])
        st.html("<div style='height:4px'></div>")

    # ── שווקים עצמאיים ───────────────────────────────────────────────────────
    for m in standalone:
        time_str, _ = _time_badge(m["hours_left"])
        poly_url    = f"https://polymarket.com/event/{m['slug']}" if m["slug"] else "#"
        title_d     = maybe_translate(m["title"])
        header      = (
            f"{time_str}  │  {title_d[:65]}{'…' if len(title_d) > 65 else ''}  "
            f"│  {fmt_vol(m['volume'])}"
        )
        with st.expander(header, expanded=False):
            _expiring_event_body(m["title"], m["slug"], m["end_date"],
                                 time_str, m["volume"], poly_url, [m])
        st.html("<div style='height:4px'></div>")


def safe_json(val) -> dict:
    try:
        return json.loads(val) if isinstance(val, str) else {}
    except Exception:
        return {}


def safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def safe_prices(val) -> list[float]:
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return [0.5, 0.5]
    if isinstance(val, list) and val:
        try:
            return [float(p) for p in val]
        except Exception:
            return [0.5, 0.5]
    return [0.5, 0.5]


def safe_outcomes(val) -> list[str]:
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return []
    if isinstance(val, list):
        return [str(o) for o in val]
    return []


def fmt_vol(vol: float) -> str:
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f"${vol / 1_000:.1f}K"
    return f"${vol:.0f}"


def fmt_cents(price: float) -> str:
    c = round(price * 100, 1)
    return f"{int(c)}¢" if c == int(c) else f"{c}¢"


# ── עזרי צבעים ───────────────────────────────────────────────────────────────

def conf_color(s: float) -> str:
    return "#00cc66" if s >= 80 else ("#ffbb00" if s >= 50 else "#ff4455")

def conf_emoji(s: float) -> str:
    return "🟢" if s >= 80 else ("🟡" if s >= 50 else "🔴")

def conf_tier(s: float) -> str:
    return "ביטחון גבוה" if s >= 80 else ("בינוני" if s >= 50 else "אות חלשה")


# ── מנוע המלצות ──────────────────────────────────────────────────────────────

def get_recommendation(prices: list[float], outcomes: list[str], conf: float) -> dict:
    if not prices:
        return dict(text="אין נתונים", sub="", color="#888",
                    bg="rgba(255,255,255,0.03)", border="rgba(255,255,255,0.12)",
                    emoji="⏳", side=None)

    best_idx   = prices.index(max(prices))
    best_price = prices[best_idx]
    best_label = outcomes[best_idx] if best_idx < len(outcomes) else "YES"
    sorted_p   = sorted(prices, reverse=True)
    diff       = (sorted_p[0] - sorted_p[1]) * 100 if len(sorted_p) > 1 else best_price * 100

    if conf < 35:
        return dict(text="אין המלצה — ביטחון נמוך",
                    sub=f"ציון {conf:.0f}/100", color="#888",
                    bg="rgba(255,255,255,0.03)", border="rgba(255,255,255,0.12)",
                    emoji="⏳", side=None)

    if diff < 8:
        return dict(text="שוק מאוזן", sub=f"הפרש: {diff:.1f}%",
                    color="#ffbb00", bg="rgba(255,187,0,0.06)",
                    border="rgba(255,187,0,0.30)", emoji="⚖️", side="NEUTRAL")

    if diff >= 30 and conf >= 70:
        strength, se = "המלצה חזקה מאוד", "🔥"
    elif diff >= 20 or conf >= 75:
        strength, se = "המלצה חזקה", "💪"
    else:
        strength, se = "המלצה", "📌"

    return dict(
        text=f"{se} {strength}: {best_label}",
        sub=f"{best_price*100:.1f}% · הפרש {diff:.1f}% · ציון {conf:.0f}",
        color="#00cc66", bg="rgba(0,204,102,0.07)",
        border="rgba(0,204,102,0.40)", emoji="✅", side=best_label,
    )


# ── רכיבי UI ─────────────────────────────────────────────────────────────────

def ui_confidence_bar(score: float) -> None:
    color = conf_color(score)
    pct   = min(max(score, 0), 100)
    st.html(f"""
<div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:10px 14px;margin:6px 0">
  <div style="display:flex;justify-content:space-between;align-items:center;
              margin-bottom:7px;direction:rtl">
    <span style="color:#999;font-size:11px">{conf_tier(score)}</span>
    <span style="color:{color};font-weight:800;font-size:19px">
      {score:.1f}<span style="font-size:11px;color:#666;font-weight:400"> / 100</span>
    </span>
  </div>
  <div style="background:rgba(255,255,255,0.08);border-radius:6px;height:9px;overflow:hidden">
    <div style="background:linear-gradient(90deg,{color}88,{color});
                width:{pct:.1f}%;height:100%;border-radius:6px"></div>
  </div>
</div>""")


def ui_section(icon: str, label: str) -> None:
    st.html(f"""
<div style="display:flex;align-items:center;gap:8px;margin:12px 0 6px;direction:rtl">
  <span style="font-size:15px">{icon}</span>
  <span style="font-size:12px;font-weight:700;letter-spacing:0.5px;color:#ccc">{label}</span>
  <div style="flex:1;height:1px;background:rgba(255,255,255,0.09)"></div>
</div>""")


def ui_market_title(title: str, slug: str = "", event_slug: str = "") -> None:
    safe = _html.escape(title)
    # קישור לאירוע הראשי בפולימרקט (event_slug), אחרת לשוק הישיר
    target_slug = event_slug or slug
    poly_url = f"https://polymarket.com/event/{target_slug}" if target_slug else ""
    link_html = (
        f'<a href="{poly_url}" target="_blank" style="'
        f'display:inline-flex;align-items:center;gap:6px;'
        f'background:rgba(0,204,102,0.12);color:#00cc66;'
        f'border:1px solid rgba(0,204,102,0.3);border-radius:8px;'
        f'padding:7px 14px;font-size:13px;font-weight:700;'
        f'text-decoration:none;margin-top:10px;">'
        f'🔗 פתח בפולימרקט</a>'
    ) if poly_url else ""
    st.html(f"""
<div style="margin:4px 0 14px;direction:rtl">
  <div style="color:#555;font-size:10px;letter-spacing:1px;margin-bottom:6px;
              text-transform:uppercase">
    🔍 שם השוק — לחץ להעתקה
  </div>
  <div style="background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.14);
              border-radius:10px;padding:13px 18px;
              cursor:text;user-select:all">
    <span style="color:#ffffff;font-size:17px;font-weight:700;
                 line-height:1.45;letter-spacing:-0.2px">{safe}</span>
  </div>
  {link_html}
</div>""")


def ui_full_outcomes_table(outcomes: list[str], prices: list[float],
                           volume: float, rec_side: str | None) -> None:
    """טבלת תוצאות בסגנון Polymarket — כל התוצאות בטבלה אחת."""
    if not outcomes or not prices:
        return

    rows_html = ""
    for i, (label, price) in enumerate(zip(outcomes, prices)):
        yes_c    = fmt_cents(price)
        no_c     = fmt_cents(max(0.0, 1.0 - price))
        pct_raw  = price * 100
        pct_str  = "&lt;1%" if pct_raw < 1 else f"{pct_raw:.0f}%"
        safe_lbl = _html.escape(label)

        est_vol  = volume * price
        vol_html = (
            f'<div style="color:#555;font-size:11px;margin-top:3px">{fmt_vol(est_vol)} Vol.</div>'
            if est_vol >= 1_000 else ""
        )

        is_rec    = (label == rec_side)
        row_style = (
            "background:rgba(0,204,102,0.07);border-right:3px solid #00cc66;"
        ) if is_rec else (
            "background:rgba(255,255,255,0.015);" if i % 2 else ""
        )
        pct_color = "#00cc66" if is_rec else "#ffffff"
        badge = (
            '<span style="background:rgba(0,204,102,0.2);color:#00cc66;'
            'font-size:10px;font-weight:700;padding:2px 7px;'
            'border-radius:5px;margin-left:8px;">&#11088; מומלץ</span>'
        ) if is_rec else ""

        rows_html += f"""
<div style="display:grid;grid-template-columns:2.2fr 0.85fr 1.25fr 1.25fr;
            gap:6px;padding:13px 16px;{row_style}
            border-bottom:1px solid rgba(255,255,255,0.04);
            align-items:center;direction:rtl">
  <div>
    <div style="font-weight:700;font-size:14px;color:#eee;
                display:flex;align-items:center;flex-wrap:wrap;gap:4px">
      {badge}{safe_lbl}
    </div>
    {vol_html}
  </div>
  <div style="text-align:center">
    <span style="font-size:22px;font-weight:800;color:{pct_color}">{pct_str}</span>
  </div>
  <div style="text-align:center">
    <div style="background:#0e3d25;color:#00cc66;font-weight:700;
                padding:8px 10px;border-radius:8px;font-size:13px;
                border:1px solid rgba(0,204,102,0.2);white-space:nowrap">
      Buy Yes {yes_c}
    </div>
  </div>
  <div style="text-align:center">
    <div style="background:#3a1217;color:#ff6666;font-weight:700;
                padding:8px 10px;border-radius:8px;font-size:13px;
                border:1px solid rgba(255,68,85,0.2);white-space:nowrap">
      Buy No {no_c}
    </div>
  </div>
</div>"""

    st.html(f"""
<div style="background:rgba(255,255,255,0.02);
            border:1px solid rgba(255,255,255,0.08);
            border-radius:14px;overflow:hidden;margin:4px 0 0">
  <div style="display:grid;grid-template-columns:2.2fr 0.85fr 1.25fr 1.25fr;
              gap:6px;padding:9px 16px;
              background:rgba(255,255,255,0.05);
              border-bottom:1px solid rgba(255,255,255,0.07);direction:rtl">
    <span style="color:#555;font-size:11px;letter-spacing:0.3px">תוצאה</span>
    <span style="color:#555;font-size:11px;text-align:center">הסתברות</span>
    <span style="color:#555;font-size:11px;text-align:center">Buy Yes</span>
    <span style="color:#555;font-size:11px;text-align:center">Buy No</span>
  </div>
  {rows_html}
</div>""")


def ui_whale_tab(prices: list[float], outcomes: list[str],
                 volume: float, conf: float, scenario: dict) -> None:
    if not prices:
        return

    whale_threshold = 50_000
    dom_idx    = prices.index(max(prices))
    dom_label  = outcomes[dom_idx] if dom_idx < len(outcomes) else "YES"
    dom_vol    = volume * prices[dom_idx]
    dom_share  = dom_vol / volume * 100 if volume > 0 else 0
    dom_whales = max(1, int(dom_vol / whale_threshold))

    st.html(f"""
<div style="background:rgba(0,204,102,0.07);border:2px solid rgba(0,204,102,0.35);
            border-radius:14px;padding:16px 20px;text-align:center;margin:8px 0 14px">
  <div style="color:#00cc66;font-size:17px;font-weight:800;margin-bottom:4px">
    ✅ רוב הכסף הוזרם לצד: {_html.escape(dom_label)}
  </div>
  <div style="color:#aaa;font-size:12px">
    {dom_share:.1f}% מנפח המסחר · כ-{dom_whales} ארנקים גדולים מוערכים
  </div>
</div>""")

    ui_section("📊", "חלוקת הון לפי תוצאה")

    for label, price in zip(outcomes, prices):
        est_vol  = volume * price
        wallets  = max(0, int(est_vol / whale_threshold))
        share    = price * 100
        is_dom   = (label == dom_label)
        color    = "#00cc66" if is_dom else "#aaa"
        bar_col  = "#00cc66" if is_dom else "#555"
        st.html(f"""
<div style="margin:8px 0;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-weight:600;font-size:13px;color:{color}">{_html.escape(label)}</span>
    <span style="color:#aaa;font-size:12px">
      ~{wallets} ארנקים &nbsp;·&nbsp; {fmt_vol(est_vol)} &nbsp;·&nbsp;
      <b style="color:{color}">{share:.1f}%</b>
    </span>
  </div>
  <div style="background:rgba(255,255,255,0.07);border-radius:5px;height:7px;overflow:hidden">
    <div style="background:{bar_col};width:{share:.1f}%;height:100%;border-radius:5px"></div>
  </div>
</div>""")

    st.divider()
    ui_section("📋", "פרטי ניתוח ותשואה פוטנציאלית")
    certainty  = scenario.get("certainty",  "לא ידוע")
    vol_tier   = scenario.get("volume_tier", "לא ידוע")
    spread_val = safe_float(scenario.get("spread", 0.0))
    yes_p = prices[dom_idx] if prices else 0.5
    no_p  = max(0.0, 1.0 - yes_p)
    roi_yes = (1 / yes_p - 1) * 100 if yes_p > 0 else 0
    roi_no  = (1 / no_p  - 1) * 100 if no_p  > 0 else 0
    ret_yes = 100 / yes_p if yes_p > 0 else 0
    ret_no  = 100 / no_p  if no_p  > 0 else 0
    st.markdown(f"""
- **ודאות השוק:** {certainty}
- **סיווג נפח:** {vol_tier}
- **פיזור מחיר (Spread):** `{spread_val:.4f}`
- **ציון ביטחון:** {conf:.1f}/100
- **תשואה על Yes (+{roi_yes:.0f}%):** על $100 ← ${ret_yes:.0f}
- **תשואה על No (+{roi_no:.0f}%):** על $100 ← ${ret_no:.0f}
""")
    st.caption(f"⚠️ הערה: הערכת ארנקים מבוססת על ${whale_threshold:,} לארנק גדול.")


MIN_ROI = 30   # % — סף תשואה מינימלית להמלצה


def ui_trade_tab(ev_slug: str, ev_title: str, markets: list[dict]) -> None:
    """לשונית מסחר דמו — קנייה על תרחישים."""
    username = st.session_state.get("wallet_user", "")
    if not username:
        st.info("💼 צור ארנק דמו בסרגל הצד כדי לסחור")
        return

    wallet = dw.get_or_create(username)
    st.html(f"""
<div style="background:rgba(0,204,102,0.07);border:1px solid rgba(0,204,102,0.2);
            border-radius:10px;padding:10px 16px;direction:rtl;margin-bottom:12px">
  <span style="color:#00cc66;font-weight:700">👤 {_html.escape(username)}</span>
  &nbsp;·&nbsp;
  <span style="color:#fff;font-weight:800">יתרה: ${wallet['balance']:.2f}</span>
</div>""")

    sorted_m = sorted(markets, key=lambda m: m["prices"][0] if m["prices"] else 0, reverse=True)

    for m in sorted_m:
        lbl    = m["group_lbl"]
        yes_p  = m["prices"][0] if m["prices"] else 0.5
        no_p   = max(0.0, 1.0 - yes_p)
        yes_c  = fmt_cents(yes_p)
        no_c   = fmt_cents(no_p)
        ret_y  = 100 / yes_p if yes_p > 0.001 else 0
        ret_n  = 100 / no_p  if no_p  > 0.001 else 0
        mid    = m.get("slug") or ev_slug

        with st.expander(f"🎯 {lbl}  ({yes_p*100:.0f}%)", expanded=False):
            st.caption(f"Buy Yes {yes_c} → על $100 תקבל ${ret_y:.0f}  |  Buy No {no_c} → על $100 תקבל ${ret_n:.0f}")
            amount = st.number_input(
                "סכום ($)", min_value=1.0, max_value=float(max(1, wallet["balance"])),
                value=min(10.0, float(wallet["balance"])), step=5.0,
                key=f"amt_{ev_slug}_{lbl}"
            )
            end_date = m.get("end_date", "")
            col_y, col_n = st.columns(2)
            with col_y:
                if st.button(f"✅ Buy Yes {yes_c}", use_container_width=True, key=f"by_{ev_slug}_{lbl}"):
                    ok, msg = dw.open_position(
                        username, mid, m["title"], lbl, ev_title, "yes", amount, yes_p, end_date
                    )
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
            with col_n:
                if st.button(f"🔴 Buy No {no_c}", use_container_width=True, key=f"bn_{ev_slug}_{lbl}"):
                    ok, msg = dw.open_position(
                        username, mid, m["title"], lbl, ev_title, "no", amount, no_p, end_date
                    )
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()


def ui_watchlist_page() -> None:
    """עמוד רשימת מעקב — שווקים מסומנים + פוזיציות פתוחות."""
    username = st.session_state.get("wallet_user", "")

    st.markdown("## ⭐ רשימת מעקב")

    if not username:
        st.info("💼 התחבר לארנק בסרגל הצד כדי לראות את רשימת המעקב")
        return

    # ── פוזיציות פתוחות ──────────────────────────────────────────────────────
    open_pos = dw.get_positions(username, "open")
    if open_pos:
        st.markdown("### 🟢 פוזיציות פתוחות")
        for p in open_pos:
            unreal = (p["current_price"] / p["entry_price"] - 1) * p["amount"] if p["entry_price"] > 0 else 0
            uc = "#00cc66" if unreal >= 0 else "#ff4455"
            dir_l = "✅ YES" if p["direction"] == "yes" else "🔴 NO"
            chg = (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] > 0 else 0
            chg_icon = "📈" if chg > 0 else ("📉" if chg < 0 else "➡️")
            poly_url = f"https://polymarket.com/event/{p['market_id']}" if p.get("market_id") else "#"

            st.html(f"""
<div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);
            border-radius:14px;padding:16px 20px;margin-bottom:10px;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
    <div style="flex:1">
      <div style="font-size:14px;font-weight:700;color:#eee;margin-bottom:8px">
        {dir_l} · {_html.escape(p['group_label'][:60])}
      </div>
      <div style="display:flex;gap:14px;font-size:12px;color:#888;flex-wrap:wrap">
        <span>השקעה: <b style="color:#ccc">${p['amount']:.2f}</b></span>
        <span>כניסה: <b style="color:#ccc">{p['entry_price']*100:.1f}¢</b></span>
        <span>עכשיו: <b style="color:{uc}">{p['current_price']*100:.1f}¢</b></span>
        <span style="color:{uc}"><b>{chg_icon} {chg:+.1f}%</b></span>
      </div>
    </div>
    <div style="text-align:left;flex-shrink:0">
      <div style="color:{uc};font-size:22px;font-weight:900">${unreal:+.2f}</div>
      <div style="color:#555;font-size:11px">רווח/הפסד שוטף</div>
      <a href="{poly_url}" target="_blank"
         style="color:#00cc66;font-size:11px;text-decoration:none;font-weight:700">🔗 פולימרקט</a>
    </div>
  </div>
</div>""")

    # ── שווקים במעקב ─────────────────────────────────────────────────────────
    wl = dw.watchlist_get(username)
    if wl:
        st.divider()
        st.markdown(f"### ⭐ שווקים במעקב ({len(wl)})")
        for w in wl:
            title = maybe_translate(w["title"])
            poly_url = f"https://polymarket.com/event/{w['slug']}"
            col1, col2 = st.columns([5, 1])
            with col1:
                st.html(f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
            border-radius:12px;padding:14px 18px;direction:rtl">
  <div style="font-size:14px;font-weight:700;color:#eee;margin-bottom:6px">{_html.escape(title[:70])}</div>
  <div style="display:flex;gap:12px;align-items:center">
    <a href="{poly_url}" target="_blank"
       style="background:rgba(0,204,102,0.12);color:#00cc66;border:1px solid rgba(0,204,102,0.3);
              border-radius:8px;padding:5px 12px;font-size:12px;font-weight:700;text-decoration:none">
      🔗 פתח בפולימרקט
    </a>
    <span style="color:#555;font-size:11px">נוסף: {w['added_at'][:10]}</span>
  </div>
</div>""")
            with col2:
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                if st.button("🗑 הסר", key=f"wl_rm_{w['slug'][:15]}", use_container_width=True):
                    dw.watchlist_remove(username, w["slug"])
                    st.rerun()
    elif not open_pos:
        st.info("רשימת המעקב ריקה. לחץ ⭐ ליד שוק כלשהו כדי להוסיף אותו למעקב.")

    # ── כפתור רענון מחירים ───────────────────────────────────────────────────
    if open_pos:
        st.divider()
        if st.button("🔄 סנכרן מחירים מ-Polymarket", type="primary"):
            with st.spinner("מסנכרן..."):
                changes = dw.sync_prices(username)
            st.success(f"✅ עודכנו {len(changes)} פוזיציות")
            st.rerun()


def ui_portfolio_page() -> None:
    """עמוד ארנק מלא — פוזיציות + סטטיסטיקות."""
    username = st.session_state.get("wallet_user", "")
    if not username:
        st.info("💼 צור ארנק דמו בסרגל הצד")
        return

    # סנכרון מחירים ישירות מ-Polymarket API + פתרון אוטומטי
    with st.spinner("🔄 מסנכרן מחירים מ-Polymarket…"):
        price_changes = dw.sync_prices(username)
    resolved = dw.auto_resolve_positions(username)

    if price_changes:
        gainers = sum(1 for v in price_changes.values() if v > 0)
        losers  = sum(1 for v in price_changes.values() if v < 0)
        st.html(f"""
<div style="background:rgba(10,132,255,0.08);border:1px solid rgba(10,132,255,0.3);
            border-radius:10px;padding:10px 16px;direction:rtl;margin-bottom:8px">
  <span style="color:#0a84ff;font-weight:700">🔄 מחירים עודכנו מ-Polymarket</span>
  &nbsp;·&nbsp;
  <span style="color:#30d158">↑ {gainers} עלו</span>
  &nbsp;·&nbsp;
  <span style="color:#ff453a">↓ {losers} ירדו</span>
</div>""")
    if resolved > 0:
        st.success(f"✅ {resolved} פוזיציות נסגרו אוטומטית לפי תוצאות פולימרקט")

    wallet = dw.get_or_create(username)
    stats  = dw.get_stats(username)

    # ── כרטיסי סטטיסטיקה ────────────────────────────────────────────────────
    st.markdown(f"## 💼 ארנק: {username}")
    # שורה 1 — סטטיסטיקות כלליות
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("💵 יתרה",       f"${wallet['balance']:.2f}")
    s2.metric("🎯 עסקאות",     stats["total_trades"])
    s3.metric("🏆 אחוז הצלחה", f"{stats['win_rate']:.0f}%")
    s4.metric("📈 רווח/הפסד",  f"${stats['total_pnl']:+.2f}")
    s5.metric("📊 ROI",        f"{stats['roi']:+.1f}%")

    # שורה 2 — רווח ממומש ולא ממומש
    _open_invested  = stats["open_invested"]
    _unreal_pnl     = stats["unrealized_pnl"]
    _real_pnl       = stats["total_pnl"]
    _total_invested = sum(p["amount"] for p in dw.get_positions(username)
                          if p["status"] != "open") or 1

    _unreal_pct = (_unreal_pnl / _open_invested  * 100) if _open_invested  > 0 else 0.0
    _real_pct   = (_real_pnl   / _total_invested * 100) if _total_invested > 0 else 0.0
    _uc = "#00cc66" if _unreal_pnl >= 0 else "#ff4455"
    _rc = "#00cc66" if _real_pnl   >= 0 else "#ff4455"
    _us = "+" if _unreal_pnl >= 0 else ""
    _rs = "+" if _real_pnl   >= 0 else ""

    st.html(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0;direction:rtl">
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);
              border-radius:14px;padding:18px 20px">
    <div style="color:#888;font-size:12px;margin-bottom:6px">📊 רווח לא ממומש</div>
    <div style="color:{_uc};font-size:28px;font-weight:900;letter-spacing:-0.5px">
      {_us}${_unreal_pnl:.2f}
    </div>
    <div style="color:{_uc};font-size:13px;font-weight:700;margin-top:4px;opacity:0.85">
      {_us}{_unreal_pct:.1f}% &nbsp;·&nbsp; מושקע: ${_open_invested:.2f}
    </div>
  </div>
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);
              border-radius:14px;padding:18px 20px">
    <div style="color:#888;font-size:12px;margin-bottom:6px">✅ רווח ממומש</div>
    <div style="color:{_rc};font-size:28px;font-weight:900;letter-spacing:-0.5px">
      {_rs}${_real_pnl:.2f}
    </div>
    <div style="color:{_rc};font-size:13px;font-weight:700;margin-top:4px;opacity:0.85">
      {_rs}{_real_pct:.1f}% &nbsp;·&nbsp; מושקע: ${_total_invested:.2f}
    </div>
  </div>
</div>""")

    # ── הפקדת כסף ────────────────────────────────────────────────────────────
    st.divider()
    with st.expander("💰 הפקדת כסף"):
        dep_c1, dep_c2 = st.columns([3, 1])
        with dep_c1:
            dep_amount = st.number_input(
                "סכום להפקדה ($)", min_value=1.0, value=100.0, step=50.0, key="deposit_amount"
            )
        with dep_c2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("💵 הפקד", use_container_width=True, type="primary"):
                if dw.deposit(username, dep_amount):
                    st.success(f"✅ הופקדו ${dep_amount:.2f}")
                    st.rerun()

    st.divider()

    # ── פוזיציות פתוחות ──────────────────────────────────────────────────────
    open_pos = dw.get_positions(username, "open")
    if open_pos:
        st.markdown("### 🟢 פוזיציות פתוחות")
        for p in open_pos:
            unreal = (p["current_price"] / p["entry_price"] - 1) * p["amount"] if p["entry_price"] > 0 else 0
            dir_label = "✅ YES" if p["direction"] == "yes" else "🔴 NO"
            end_str = (p.get("end_date") or "")[:10] or "לא ידוע"
            trend = "📈" if unreal >= 0 else "📉"
            with st.expander(
                f"{dir_label}  {p['group_label']}  (${p['amount']:.0f})  {trend} ${unreal:+.2f}",
                expanded=False
            ):
                col1, col2, col3 = st.columns(3)
                col1.metric("השקעה",          f"${p['amount']:.2f}")
                col2.metric("רווח פוטנציאלי", f"${p['potential_win']:.2f}")
                col3.metric("רווח/הפסד שוטף", f"${unreal:+.2f}")
                price_chg = (p["current_price"] / p["entry_price"] - 1) * 100 if p["entry_price"] > 0 else 0
                chg_icon  = "📈" if price_chg > 0 else ("📉" if price_chg < 0 else "➡️")
                chg_color = "#00cc66" if price_chg > 0 else ("#ff4455" if price_chg < 0 else "#888")
                st.html(f"""
<div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:8px 12px;
            direction:rtl;margin:6px 0;font-size:12px;color:#888">
  כניסה: <b style="color:#ccc">{p['entry_price']*100:.1f}¢</b>
  &nbsp;→&nbsp;
  <b style="color:{chg_color}">{p['current_price']*100:.1f}¢ {chg_icon} {price_chg:+.1f}%</b>
  &nbsp;·&nbsp; {p['timestamp'][:10]}
  &nbsp;·&nbsp; <span style="color:#0a84ff;font-size:11px">🔄 Live Polymarket</span>
</div>""")
                st.caption(f"📅 תפוגה: {end_str}  |  אירוע: {p['event_title']}")
                if st.button("💰 מכור פוזיציה", key=f"sell_{p['id']}", use_container_width=True):
                    ok, msg = dw.sell_position(p["id"], username)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()
    else:
        st.info("אין פוזיציות פתוחות כרגע")

    # ── היסטוריה ─────────────────────────────────────────────────────────────
    closed_pos = [p for p in dw.get_positions(username) if p["status"] != "open"]
    if closed_pos:
        st.divider()
        st.markdown("### 📋 היסטוריית עסקאות")
        rows = []
        for p in closed_pos:
            rows.append({
                "תאריך":     p["timestamp"][:10],
                "תרחיש":     p["group_label"],
                "כיוון":     "YES" if p["direction"] == "yes" else "NO",
                "השקעה":     f"${p['amount']:.2f}",
                "תוצאה":     "🏆 ניצחון" if p["status"] == "won" else "❌ הפסד",
                "רווח/הפסד": f"${p['pnl']:+.2f}",
                "תפוגה":     (p.get("end_date") or "")[:10] or "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def smart_money_signals(m: dict) -> list[dict]:
    """
    מחזיר רשימת אותות 'כסף חכם' לתרחיש.
    מבוסס על: שינוי מחיר יומי חריג + נפח 24h גבוה + ריכוז נפח.
    """
    signals = []
    pc  = float(m.get("price_change_1d", 0) or 0)
    v24 = float(m.get("vol_24h", 0) or 0)
    vol = m.get("volume", 0)
    yes_p = m["prices"][0] if m.get("prices") else 0.5

    # שינוי מחיר חריג ב-24 שעות = מישהו גדול קנה/מכר
    if abs(pc) >= 0.08:
        direction = "כלפי מעלה 📈" if pc > 0 else "כלפי מטה 📉"
        signals.append({
            "icon": "🚨",
            "text": f"תנועת מחיר חריגה ב-24ש: {pc*100:+.1f}% {direction}",
            "color": "#00cc66" if pc > 0 else "#ff6666",
            "level": "high",
        })
    elif abs(pc) >= 0.04:
        signals.append({
            "icon": "⚡",
            "text": f"מחיר זז {pc*100:+.1f}% ב-24ש — פעילות חריגה",
            "color": "#ffbb00",
            "level": "medium",
        })

    # נפח יומי גבוה ביחס לנפח כולל = כסף חדש נכנס
    if vol > 0:
        ratio = v24 / vol
        if ratio >= 0.25:
            signals.append({
                "icon": "🐋",
                "text": f"{ratio*100:.0f}% מהנפח הכולל נסחר ב-24ש אחרונות — כסף גדול נכנס",
                "color": "#00cc66",
                "level": "high",
            })
        elif ratio >= 0.10:
            signals.append({
                "icon": "📊",
                "text": f"{ratio*100:.0f}% מהנפח נסחר ב-24ש — עניין מוגבר",
                "color": "#ffbb00",
                "level": "medium",
            })

    # נפח יומי גבוה במוחלט
    if v24 >= 500_000:
        signals.append({
            "icon": "💎",
            "text": f"נפח 24ש: {fmt_vol(v24)} — ארנקים גדולים פעילים",
            "color": "#00cc66",
            "level": "high",
        })

    # שוק קרוב לאיזון עם כסף גדול = הזדמנות
    if 0.40 <= yes_p <= 0.60 and v24 >= 100_000:
        signals.append({
            "icon": "⚖️",
            "text": "שוק מאוזן עם נפח גבוה — ארנקים מתמחרים מחדש",
            "color": "#ffbb00",
            "level": "medium",
        })

    return signals


def _whale_score(yes_p: float, vol_share: float) -> tuple[float, str]:
    """
    מחזיר (ציון, כיוון) עבור הימור — מבוסס על תנועת ארנקים + ROI > MIN_ROI.
    כיוון: 'yes' | 'no' | None
    """
    no_p    = max(0.0, 1.0 - yes_p)
    roi_yes = (1 / yes_p - 1) * 100 if yes_p > 0.01 else 0
    roi_no  = (1 / no_p  - 1) * 100 if no_p  > 0.01 else 0

    # Yes: יש סיכוי אמיתי + תשואה מינימלית
    yes_score = (vol_share * (1 + roi_yes / 100) * yes_p
                 if roi_yes >= MIN_ROI and 0.05 <= yes_p <= 0.90 else 0)
    # No: הסתברות לניצחון No גבוהה + תשואה מינימלית
    no_score  = (vol_share * (1 + roi_no / 100) * no_p
                 if roi_no  >= MIN_ROI and 0.05 <= no_p  <= 0.90 else 0)

    if yes_score >= no_score and yes_score > 0:
        return yes_score, "yes"
    if no_score > 0:
        return no_score, "no"
    return 0.0, "none"


def ui_event_whale_tab(markets: list[dict]) -> None:
    """ניתוח לווייתנים — רק הזדמנויות עם ROI > 30% ותנועת ארנקים."""
    whale_threshold = 50_000
    total_vol = sum(m["volume"] for m in markets)

    # מציאת ההמלצה הטובה ביותר לפי ציון
    best_m, best_dir, best_score = None, "none", 0.0
    for m in markets:
        yp    = m["prices"][0] if m["prices"] else 0.5
        share = m["volume"] / total_vol * 100 if total_vol > 0 else 0
        sc, dr = _whale_score(yp, share)
        if sc > best_score:
            best_score, best_m, best_dir = sc, m, dr

    # ── המלצה ראשית ─────────────────────────────────────────────────────────
    if best_m and best_dir != "none":
        yes_p     = best_m["prices"][0] if best_m["prices"] else 0.5
        no_p      = max(0.0, 1.0 - yes_p)
        vol_share = best_m["volume"] / total_vol * 100 if total_vol > 0 else 0
        whales    = max(1, int(best_m["volume"] / whale_threshold))

        if best_dir == "yes":
            roi_val   = (1 / yes_p - 1) * 100 if yes_p > 0 else 0
            ret_val   = 100 / yes_p if yes_p > 0 else 0
            btn_html  = f'<span style="background:#0e3d25;color:#00cc66;padding:5px 12px;border-radius:6px;font-size:13px;font-weight:700">Buy Yes {fmt_cents(yes_p)}</span>'
            dir_color = "#00cc66"
        else:
            roi_val   = (1 / no_p - 1) * 100 if no_p > 0 else 0
            ret_val   = 100 / no_p if no_p > 0 else 0
            btn_html  = f'<span style="background:#3a1217;color:#ff6666;padding:5px 12px;border-radius:6px;font-size:13px;font-weight:700">Buy No {fmt_cents(no_p)}</span>'
            dir_color = "#ff6666"

        icon = "🔥" if roi_val >= 80 else ("📌" if roi_val >= 50 else "✅")
        st.html(f"""
<div style="background:rgba(0,204,102,0.07);border:2px solid rgba(0,204,102,0.35);
            border-radius:14px;padding:18px 22px;margin:8px 0 16px;direction:rtl">
  <div style="color:#00cc66;font-size:13px;font-weight:700;margin-bottom:6px;letter-spacing:0.5px">
    {icon} המלצה ראשית — לווייתנים + ROI &gt; {MIN_ROI}%
  </div>
  <div style="color:#fff;font-size:20px;font-weight:900;margin-bottom:10px">
    {_html.escape(best_m["group_lbl"])}
  </div>
  <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
    {btn_html}
    <span style="color:{dir_color};font-size:14px;font-weight:700">
      +{roi_val:.0f}% תשואה · על $100 ← ${ret_val:.0f}
    </span>
  </div>
  <div style="color:#666;font-size:12px;line-height:1.8">
    📊 הסתברות: {yes_p*100:.0f}% &nbsp;·&nbsp;
    💰 {fmt_vol(best_m["volume"])} ({vol_share:.1f}% מהאירוע) &nbsp;·&nbsp;
    🐋 ~{whales} ארנקים גדולים
  </div>
</div>""")
    else:
        st.html(f"""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);
            border-radius:14px;padding:18px 22px;margin:8px 0 16px;direction:rtl;text-align:center">
  <div style="color:#888;font-size:15px;font-weight:700">⚠️ אין הזדמנות עם ROI &gt; {MIN_ROI}% כרגע</div>
  <div style="color:#555;font-size:12px;margin-top:6px">כל ההימורים בשוק זה מציעים תשואה נמוכה מדי ביחס לסיכון</div>
</div>""")

    # ── פירוט כל תרחיש ──────────────────────────────────────────────────────
    ui_section("📊", "פירוט לכל תרחיש")

    sorted_m = sorted(markets, key=lambda m: m["volume"], reverse=True)
    for m in sorted_m:
        lbl    = m["group_lbl"]
        vol    = m["volume"]
        yes_p  = m["prices"][0] if m["prices"] else 0.5
        no_p   = max(0.0, 1.0 - yes_p)
        share  = vol / total_vol * 100 if total_vol > 0 else 0
        whales = max(0, int(vol / whale_threshold))

        roi_yes = (1 / yes_p - 1) * 100 if yes_p > 0.01 else 0
        roi_no  = (1 / no_p  - 1) * 100 if no_p  > 0.01 else 0
        ret_yes = 100 / yes_p if yes_p > 0.01 else 0
        ret_no  = 100 / no_p  if no_p  > 0.01 else 0

        sc, dr  = _whale_score(yes_p, share)
        is_best = (best_m is not None and lbl == best_m["group_lbl"])
        signals = smart_money_signals(m)
        high_signals = [s for s in signals if s["level"] == "high"]

        if dr == "yes" and roi_yes >= MIN_ROI:
            rec_text  = f"✅ Buy Yes {fmt_cents(yes_p)} | +{roi_yes:.0f}% תשואה"
            rec_color = "#00cc66"
        elif dr == "no" and roi_no >= MIN_ROI:
            rec_text  = f"🔴 Buy No {fmt_cents(no_p)} | +{roi_no:.0f}% תשואה"
            rec_color = "#ff6666"
        else:
            rec_text  = f"⚠️ ROI נמוך מדי ({max(roi_yes,roi_no):.0f}%) — לא מומלץ"
            rec_color = "#555"

        # גבול בהיר יותר אם יש אות "כסף חכם" חזק
        has_alert = bool(high_signals)
        row_bg = "rgba(0,204,102,0.06)" if is_best else ("rgba(255,187,0,0.04)" if has_alert else "rgba(255,255,255,0.02)")
        border = ("2px solid rgba(0,204,102,0.3)" if is_best
                  else ("1px solid rgba(255,187,0,0.35)" if has_alert
                        else "1px solid rgba(255,255,255,0.06)"))

        signals_html = "".join(
            f'<div style="color:{s["color"]};font-size:11px;font-weight:600;margin-top:3px">'
            f'{s["icon"]} {_html.escape(s["text"])}</div>'
            for s in signals
        )

        st.html(f"""
<div style="background:{row_bg};border:{border};border-radius:12px;
            padding:14px 18px;margin:6px 0;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">
    <div style="flex:1;min-width:0">
      <div style="font-weight:800;font-size:14px;color:#eee;margin-bottom:4px">
        {"⭐ " if is_best else ""}{_html.escape(lbl)}
      </div>
      <div style="color:{rec_color};font-size:13px;font-weight:700;margin-bottom:4px">{rec_text}</div>
      {signals_html}
    </div>
    <div style="color:#888;font-size:12px;line-height:1.8;text-align:left;flex-shrink:0">
      <div>📈 <b style="color:#eee">{yes_p*100:.0f}%</b> הסתברות</div>
      <div>💰 <b style="color:#eee">{fmt_vol(vol)}</b> ({share:.1f}%)</div>
      <div>🐋 ~<b style="color:#eee">{whales}</b> ארנקים</div>
      <div style="margin-top:4px;border-top:1px solid rgba(255,255,255,0.07);padding-top:4px">
        $100 ←
        <span style="color:#00cc66;font-weight:700">Yes: ${ret_yes:.0f}</span> |
        <span style="color:#ff6666;font-weight:700">No: ${ret_no:.0f}</span>
      </div>
    </div>
  </div>
  <div style="margin-top:8px;background:rgba(255,255,255,0.06);border-radius:4px;height:5px;overflow:hidden">
    <div style="background:{'#00cc66' if is_best else ('#ffbb00' if has_alert else '#444')};width:{min(share*2,100):.0f}%;height:100%;border-radius:4px"></div>
  </div>
</div>""")

    st.caption(f"⚠️ סף תשואה מינימלי: {MIN_ROI}% · הערכת ארנקים: ${whale_threshold:,} לארנק")


# ── סרגל צד ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🐋 מודיעין לווייתנים")
    st.caption("Polymarket · Gamma API · 2026")
    st.divider()

    # ── ארנק דמו ────────────────────────────────────────────────────────────
    st.markdown("### 💼 ארנק דמו")

    # טעינת משתמש מ-URL params (זיכרון אוטומטי בין סשנים)
    if "wallet_user" not in st.session_state:
        _saved = st.query_params.get("user", "")
        if _saved:
            st.session_state.wallet_user = _saved  # קבל מ-URL בלי לאמת
        else:
            st.session_state.wallet_user = ""

    if not st.session_state.wallet_user:
        all_wallets = dw.get_all_wallets()
        if all_wallets:
            wallet_names = [w["username"] for w in all_wallets]
            _sel = st.selectbox("משתמש קיים:", ["— חדש —"] + wallet_names)
            if _sel != "— חדש —":
                if st.button("✅ כניסה", use_container_width=True, type="primary"):
                    st.session_state.wallet_user = _sel
                    st.query_params["user"] = _sel
                    st.rerun()
            else:
                new_name = st.text_input("שם משתמש חדש:", placeholder="לדוג׳: GamblerPro")
                if st.button("✅ צור ארנק", use_container_width=True, type="primary"):
                    if new_name.strip():
                        dw.get_or_create(new_name.strip())
                        st.session_state.wallet_user = new_name.strip()
                        st.query_params["user"] = new_name.strip()
                        st.rerun()
        else:
            new_name = st.text_input("בחר שם משתמש:", placeholder="לדוג׳: GamblerPro")
            if st.button("✅ צור ארנק", use_container_width=True, type="primary"):
                if new_name.strip():
                    dw.get_or_create(new_name.strip())
                    st.session_state.wallet_user = new_name.strip()
                    st.query_params["user"] = new_name.strip()
                    st.rerun()
    else:
        username = st.session_state.wallet_user
        wallet   = dw.get_or_create(username)
        stats    = dw.get_stats(username)

        st.html(f"""
<div style="background:rgba(0,204,102,0.08);border:1px solid rgba(0,204,102,0.25);
            border-radius:10px;padding:10px 14px;direction:rtl;margin-bottom:6px">
  <div style="color:#00cc66;font-size:12px;font-weight:700">👤 {_html.escape(username)}</div>
  <div style="color:#fff;font-size:22px;font-weight:900;margin:3px 0">${wallet['balance']:.2f}</div>
  <div style="color:#888;font-size:11px">
    יתרה זמינה &nbsp;·&nbsp; {stats['open_count']} פוזיציות פתוחות
  </div>
</div>""")

        if stats["total_trades"] > 0:
            wr_color  = "#00cc66" if stats["win_rate"] >= 50 else "#ff6666"
            pnl_color = "#00cc66" if stats["total_pnl"] >= 0 else "#ff6666"
            pnl_sign  = "+" if stats["total_pnl"] >= 0 else ""
            st.html(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px">
  <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:8px 10px;text-align:center">
    <div style="color:#888;font-size:10px">אחוז הצלחה</div>
    <div style="color:{wr_color};font-size:16px;font-weight:800">{stats['win_rate']:.0f}%</div>
    <div style="color:#666;font-size:10px">{stats['wins']}W / {stats['losses']}L</div>
  </div>
  <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:8px 10px;text-align:center">
    <div style="color:#888;font-size:10px">רווח/הפסד כולל</div>
    <div style="color:{pnl_color};font-size:16px;font-weight:800">{pnl_sign}${stats['total_pnl']:.2f}</div>
    <div style="color:#666;font-size:10px">ROI {pnl_sign}{stats['roi']:.1f}%</div>
  </div>
</div>""")

        # עריכת שם בלבד
        with st.expander("✏️ ערוך שם"):
            new_un = st.text_input("שם חדש:", key="rename_inp", placeholder="שם חדש")
            if st.button("שמור שם", use_container_width=True):
                if new_un.strip() and dw.rename_wallet(username, new_un.strip()):
                    st.session_state.wallet_user = new_un.strip()
                    st.query_params["user"] = new_un.strip()
                    st.rerun()
                else:
                    st.error("השם תפוס או זהה")

        if st.button("🚪 התנתק", use_container_width=True):
            st.session_state.wallet_user = ""
            st.query_params.pop("user", None)
            st.rerun()

    st.divider()
    st.markdown("### 🗂 ניווט")
    page = st.radio(
        "עמוד",
        ["📊 שווקים", "💼 הפורטפוליו שלי", "⏰ פגים בקרוב", "🎯 ארביטראז'", "⭐ מעקב"],
        label_visibility="collapsed",
    )
    st.session_state["_page"] = page

    # הגדרות ארביטראז' — מוצגות רק בעמוד הרלוונטי
    if page == "🎯 ארביטראז'":
        st.divider()
        st.markdown("### ⚙️ הגדרות סריקה")
        arb_clob = st.toggle("📡 מחירי CLOB (Ask אמיתי)", value=False,
                             help="OFF = Gamma mid prices (מהיר) · ON = Order Book ask prices (מדויק)")
        if st.button("🔄 סרוק מחדש", type="primary", use_container_width=True):
            arb._fetch_gamma.clear()
            arb._fetch_book.clear()
        st.session_state["_arb_clob"] = arb_clob
        st.caption("סף: Yes+No < 0.95 · Slippage: 0.5% · Vol min: $5K")

    st.divider()
    st.markdown("### 📡 בקרת נתונים")
    if st.button("🔄 רענן נתונים מ-Polymarket", use_container_width=True, type="primary"):
        import subprocess, sys
        with st.spinner("מעדכן נתונים מ-Polymarket... (30-60 שניות)"):
            try:
                result = subprocess.run(
                    [sys.executable, "main.py"],
                    capture_output=True, text=True,
                    timeout=120,
                    cwd=__import__("os").path.dirname(__file__) or "."
                )
                st.cache_data.clear()
                if result.returncode == 0:
                    st.success("✅ נתונים עודכנו בהצלחה!")
                else:
                    st.warning(f"⚠️ עודכן עם אזהרות")
            except subprocess.TimeoutExpired:
                st.warning("⏱ העדכון לקח יותר מדי — נסה שוב")
            except Exception as e:
                st.error(f"שגיאה: {e}")
        st.rerun()

    st.divider()
    st.markdown("### 🔍 סינון תצוגה")
    search = st.text_input("חיפוש שוק", placeholder="לדוג׳: bitcoin, israel…")
    live_search = st.toggle("🌐 חיפוש חי מ-Polymarket", value=False,
                            help="מחפש ישירות ב-Polymarket — מוצא שווקים שלא במסד הנתונים המקומי")
    sort_options = {"ציון ביטחון ↓": "confidence", "נפח מסחר ↓": "volume", "🆕 חדש ↓": "end_date"}
    sort_label = st.selectbox("מיון לפי", list(sort_options.keys()))
    sort_col   = sort_options[sort_label]
    min_conf   = st.slider("ציון ביטחון מינימלי", 0, 100, 0, step=5)
    tier_opts  = ["🟢 גבוה (≥80)", "🟡 בינוני (50–79)", "🔴 נמוך (<50)"]
    tier_filter = st.multiselect("רמת ביטחון", tier_opts, default=tier_opts)

    st.divider()
    st.markdown("### 📅 פילטר תפוגה")
    expiry_opts = {
        "הכל": None,
        "7 ימים": 7,
        "20 ימים": 20,
        "30 יום": 30,
        "90 יום": 90,
        "180 יום": 180,
    }
    expiry_label  = st.radio("תפוגה עד", list(expiry_opts.keys()), index=0, horizontal=True)
    expiry_days   = expiry_opts[expiry_label]

    st.divider()
    st.caption(f"⏱ עודכן: {datetime.utcnow().strftime('%H:%M')} UTC")

# ── ניווט בין עמודים ─────────────────────────────────────────────────────────

if st.session_state.get("_page") == "💼 הפורטפוליו שלי":
    ui_portfolio_page()
    st.stop()

if st.session_state.get("_page") == "⏰ פגים בקרוב":
    ui_expiring_soon(days=20)
    st.stop()

if st.session_state.get("_page") == "🎯 ארביטראז'":
    arb.ui_arbitrage_page(use_clob=st.session_state.get("_arb_clob", False))
    st.stop()

if st.session_state.get("_page") == "⭐ מעקב":
    ui_watchlist_page()
    st.stop()

# ── טעינה וסינון ─────────────────────────────────────────────────────────────

df_raw = load_markets()
if df_raw.empty:
    st.error("⚠️ לא נמצאו נתונים. הרץ `python main.py` ואז לחץ **רענן נתונים**.")
    st.stop()

df = df_raw.copy()

# ── חיפוש חי מ-Polymarket API ────────────────────────────────────────────────
if search and live_search:
    @st.cache_data(ttl=300, show_spinner=False)
    def _translate_to_english(text: str) -> str:
        """מתרגם טקסט עברי לאנגלית לצורך חיפוש ב-API."""
        try:
            import urllib.request, urllib.parse
            payload = urllib.parse.urlencode({
                "client": "gtx", "sl": "auto", "tl": "en",
                "dt": "t", "q": text
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://translate.googleapis.com/translate_a/single",
                data=payload,
                headers={"User-Agent": "Mozilla/5.0",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
            return "".join(s[0] for s in data[0] if s[0]) or text
        except Exception:
            return text

    @st.cache_data(ttl=60, show_spinner=False)
    def _live_search(q: str) -> list[dict]:
        """מחפש דרך events endpoint — מביא כל האירועים ומוצא תוצאות מדויקות."""
        import requests as _req
        q_lower = q.lower()
        results = []

        # שלב 1: חיפוש דרך events (מקיף יותר)
        for offset in range(0, 3000, 100):
            try:
                r = _req.get(
                    "https://gamma-api.polymarket.com/events",
                    params={"active": "true", "closed": "false",
                            "limit": 100, "offset": offset,
                            "order": "volume", "ascending": "false"},
                    timeout=10,
                )
                if not r.ok:
                    break
                batch = r.json()
                if not batch:
                    break
                for ev in batch:
                    title = (ev.get("title") or "").lower()
                    desc  = (ev.get("description") or "").lower()
                    slug  = (ev.get("slug") or "").lower()
                    if q_lower in title or q_lower in desc or q_lower in slug:
                        # הוסף כל השווקים של האירוע
                        for m in ev.get("markets", []):
                            m["event_title"] = ev.get("title", "")
                            m["event_slug"]  = ev.get("slug", "")
                            results.append(m)
                if len(results) >= 50:
                    break
            except Exception:
                break

        # שלב 2: אם לא נמצא מספיק — חפש גם ב-markets ישירות
        if len(results) < 5:
            for offset in range(0, 3000, 100):
                try:
                    r = _req.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={"active": "true", "closed": "false",
                                "limit": 100, "offset": offset,
                                "order": "volume", "ascending": "false"},
                        timeout=8,
                    )
                    if not r.ok:
                        break
                    batch = r.json()
                    if not batch:
                        break
                    for m in batch:
                        text = " ".join([
                            m.get("question", ""),
                            m.get("groupItemTitle", "") or "",
                            m.get("event_title", "") or "",
                        ]).lower()
                        if q_lower in text:
                            results.append(m)
                    if len(results) >= 50:
                        break
                except Exception:
                    break

        return results[:50]

    # זיהוי עברית ותרגום לאנגלית לפני חיפוש
    is_hebrew = any("א" <= c <= "ת" for c in search)
    search_query = _translate_to_english(search) if is_hebrew else search

    with st.spinner(f"מחפש '{search_query}' ב-Polymarket…"):
        live_results = _live_search(search_query)

    if live_results:
        # המר לפורמט DataFrame זמני
        live_rows = []
        for m in live_results:
            try:
                import json as _j
                prices_raw = m.get("outcomePrices", "[0.5,0.5]")
                prices = _j.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                yes_p = float(prices[0]) if prices else 0.5
                live_rows.append({
                    "title":      m.get("question", ""),
                    "yes_pct":    yes_p * 100,
                    "no_pct":     (1 - yes_p) * 100,
                    "volume":     float(m.get("volume", 0) or 0),
                    "confidence": abs(yes_p - 0.5) * 200,
                    "end_date":   (m.get("endDate") or "")[:10],
                    "data":       _j.dumps({
                        "slug":        m.get("slug", ""),
                        "event_slug":  m.get("event_slug", ""),
                        "event_title": m.get("event_title", ""),
                        "group_label": m.get("groupItemTitle", "") or m.get("question", ""),
                        "price":       prices_raw,
                        "outcomes":    m.get("outcomes", '["Yes","No"]'),
                        "description": m.get("description", ""),
                        "scenario":    {},
                        "price_change_1d": float(m.get("oneDayPriceChange", 0) or 0),
                        "vol_24h":     float(m.get("volume24hr", 0) or 0),
                    }),
                })
            except Exception:
                continue
        df = pd.DataFrame(live_rows) if live_rows else df
        st.info(f"🌐 {len(live_rows)} תוצאות חיות מ-Polymarket עבור '{search}'")
    else:
        st.warning(f"לא נמצאו תוצאות עבור '{search}' גם ב-Polymarket.")

elif search:
    # חיפוש רגיל במסד הנתונים
    mask = df["title"].str.contains(search, case=False, na=False)
    _trans = st.session_state.get("_trans", {})
    if _trans:
        translated_matches = {
            orig for orig, translated in _trans.items()
            if search.lower() in translated.lower()
        }
        mask = mask | df["title"].isin(translated_matches)
    df = df[mask]
df = df[df["confidence"] >= min_conf]
if tier_filter:
    mask = pd.Series(False, index=df.index)
    if "🟢 גבוה (≥80)"     in tier_filter: mask |= df["confidence"] >= 80
    if "🟡 בינוני (50–79)" in tier_filter: mask |= (df["confidence"] >= 50) & (df["confidence"] < 80)
    if "🔴 נמוך (<50)"     in tier_filter: mask |= df["confidence"] < 50
    df = df[mask]
if expiry_days is not None:
    cutoff = (datetime.utcnow().date() + __import__("datetime").timedelta(days=expiry_days)).isoformat()
    df = df[df["end_date"].fillna("9999-12-31") <= cutoff]
if sort_col == "end_date":
    # מיון "חדש" — שווקים שנוצרו לאחרונה (end_date קצר = חדש יחסית)
    df = df.sort_values("end_date", ascending=True).reset_index(drop=True)
elif sort_col in df.columns:
    df = df.sort_values(sort_col, ascending=False).reset_index(drop=True)

# ── כותרת ────────────────────────────────────────────────────────────────────

st.html("""
<div style="margin-bottom:4px;direction:rtl">
  <h1 style="font-size:2rem;font-weight:800;margin:0">🐋 מודיעין לווייתנים | Polymarket</h1>
  <p style="color:#666;margin-top:4px;font-size:13px">
    ניתוח שווקי תחזיות בזמן אמת &nbsp;·&nbsp; Gamma API &nbsp;·&nbsp; 2026
  </p>
</div>""")
st.toggle("🇮🇱 תרגם כותרות לעברית", key="translate_on")

# ── מרכז פיקוד ───────────────────────────────────────────────────────────────

total_vol = df["volume"].sum()
avg_conf  = df["confidence"].mean() if len(df) else 0.0
high_n    = int((df["confidence"] >= 80).sum())
high_pct  = f"{high_n / len(df) * 100:.0f}%" if len(df) else "—"

c1, c2, c3, c4 = st.columns(4)
c1.metric("🌐 שווקים פעילים", len(df))
c2.metric("📈 ציון ממוצע",    f"{avg_conf:.1f}")
c3.metric("💰 נפח כולל",      fmt_vol(total_vol))
c4.metric("🏆 ביטחון גבוה",   f"{high_n}  ({high_pct})")

st.divider()

if len(df) == 0:
    st.info("אין שווקים התואמים את הסינון. נסה לשנות את ההגדרות בסרגל הצד.")
    st.stop()

st.html(
    f"<p style='color:#888;font-size:13px;margin-bottom:4px;direction:rtl'>"
    f"מציג <b style='color:#ccc'>{len(df)}</b> שווקים &nbsp;·&nbsp; "
    f"ממוין לפי <b style='color:#ccc'>{_html.escape(sort_label)}</b></p>"
)

# ── טרום-תרגום: אסוף את כל הכותרות ותרגם בבת אחת ────────────────────────────

if st.session_state.get("translate_on", False):
    _texts: set[str] = set()
    for _, _r in df.iterrows():
        _md = safe_json(_r.get("data", "{}"))
        _t  = str(_r.get("title", "") or "")
        _et = str(_md.get("event_title", "") or "")
        _gl = str(_md.get("group_label", "") or _t)
        for _x in [_t, _et, _gl]:
            if _x:
                _texts.add(_x)
    with st.spinner("מתרגם כותרות..."):
        st.session_state["_trans"] = _batch_translate_api(tuple(sorted(_texts)))
else:
    st.session_state["_trans"] = {}

# ── קיבוץ שווקים לפי אירוע ───────────────────────────────────────────────────

event_groups: dict[str, dict] = {}   # event_slug → event dict
standalone:   list[dict]      = []

for _, row in df.iterrows():
    m_data     = safe_json(row.get("data", "{}"))
    conf       = safe_float(row.get("confidence"), 50.0)
    volume     = safe_float(row.get("volume"),      0.0)
    end_date   = str(row.get("end_date", "") or "")
    title_raw  = str(row.get("title", "שוק לא ידוע") or "שוק לא ידוע")
    title      = maybe_translate(title_raw)
    slug       = str(m_data.get("slug",        "") or "")
    ev_slug    = str(m_data.get("event_slug",  "") or "")
    ev_title   = maybe_translate(str(m_data.get("event_title", "") or ""))
    group_lbl  = maybe_translate(str(m_data.get("group_label", "") or title_raw))
    scenario   = m_data.get("scenario", {})
    desc       = str(m_data.get("description", "") or "").strip()

    prices   = safe_prices(m_data.get("price", []))
    outcomes = safe_outcomes(m_data.get("outcomes", []))
    if not outcomes:
        outcomes = ["Yes", "No"] if len(prices) == 2 else [f"תוצאה {i+1}" for i in range(len(prices))]
    n = min(len(outcomes), len(prices))
    outcomes, prices = outcomes[:n], prices[:n]

    info = dict(
        conf=conf, volume=volume, end_date=end_date, title=title,
        slug=slug, ev_slug=ev_slug, group_lbl=group_lbl, scenario=scenario,
        desc=desc, prices=prices, outcomes=outcomes,
        price_change_1d=float(m_data.get("price_change_1d", 0) or 0),
        vol_24h=float(m_data.get("vol_24h", 0) or 0),
        rec=get_recommendation(prices, outcomes, conf),
    )

    if ev_slug:
        if ev_slug not in event_groups:
            event_groups[ev_slug] = dict(
                ev_title=ev_title, ev_slug=ev_slug,
                end_date=end_date, markets=[]
            )
        event_groups[ev_slug]["markets"].append(info)
    else:
        standalone.append(info)


def ui_event_table(event_markets: list[dict]) -> None:
    """טבלת אירוע — כל תרחיש שורה אחת בסגנון Polymarket."""
    rows_html = ""
    for i, m in enumerate(event_markets):
        yes_price = m["prices"][0] if m["prices"] else 0.5
        no_price  = max(0.0, 1.0 - yes_price)
        pct_raw   = yes_price * 100
        pct_str   = "&lt;1%" if pct_raw < 1 else f"{pct_raw:.0f}%"
        yes_c     = fmt_cents(yes_price)
        no_c      = fmt_cents(no_price)
        vol_str   = fmt_vol(m["volume"])
        safe_lbl  = _html.escape(m["group_lbl"])
        bg        = "background:rgba(255,255,255,0.015);" if i % 2 else ""
        pct_color = "#00cc66" if pct_raw >= 60 else ("#ffbb00" if pct_raw >= 40 else "#ff6666")

        rows_html += (
            f'<div style="display:grid;grid-template-columns:2.4fr 0.85fr 1.2fr 1.2fr 0.8fr;'
            f'gap:6px;padding:13px 16px;{bg}'
            f'border-bottom:1px solid rgba(255,255,255,0.04);align-items:center;direction:rtl">'
            f'<div>'
            f'<div style="font-weight:700;font-size:14px;color:#eee">{safe_lbl}</div>'
            f'<div style="color:#555;font-size:11px;margin-top:2px">{vol_str} Vol.</div>'
            f'</div>'
            f'<div style="text-align:center">'
            f'<span style="font-size:20px;font-weight:800;color:{pct_color}">{pct_str}</span>'
            f'</div>'
            f'<div style="text-align:center">'
            f'<div style="background:#0e3d25;color:#00cc66;font-weight:700;'
            f'padding:8px 10px;border-radius:8px;font-size:13px;'
            f'border:1px solid rgba(0,204,102,0.2);white-space:nowrap">Buy Yes {yes_c}</div>'
            f'</div>'
            f'<div style="text-align:center">'
            f'<div style="background:#3a1217;color:#ff6666;font-weight:700;'
            f'padding:8px 10px;border-radius:8px;font-size:13px;'
            f'border:1px solid rgba(255,68,85,0.2);white-space:nowrap">Buy No {no_c}</div>'
            f'</div>'
            f'<div style="text-align:center;color:#555;font-size:11px">{fmt_vol(m["volume"])}</div>'
            f'</div>'
        )

    st.html(
        f'<div style="background:rgba(255,255,255,0.02);'
        f'border:1px solid rgba(255,255,255,0.08);border-radius:14px;overflow:hidden;margin:4px 0">'
        f'<div style="display:grid;grid-template-columns:2.4fr 0.85fr 1.2fr 1.2fr 0.8fr;'
        f'gap:6px;padding:9px 16px;background:rgba(255,255,255,0.05);'
        f'border-bottom:1px solid rgba(255,255,255,0.07);direction:rtl">'
        f'<span style="color:#555;font-size:11px">תרחיש</span>'
        f'<span style="color:#555;font-size:11px;text-align:center">סיכוי</span>'
        f'<span style="color:#555;font-size:11px;text-align:center">Buy Yes</span>'
        f'<span style="color:#555;font-size:11px;text-align:center">Buy No</span>'
        f'<span style="color:#555;font-size:11px;text-align:center">נפח</span>'
        f'</div>'
        f'{rows_html}'
        f'</div>'
    )


# ── תצוגת אירועים מקובצים ─────────────────────────────────────────────────────

for ev_slug, ev in event_groups.items():
    markets    = ev["markets"]
    ev_title   = ev["ev_title"]
    total_vol  = sum(m["volume"] for m in markets)
    avg_conf   = sum(m["conf"] for m in markets) / len(markets)
    end_date   = ev["end_date"]
    poly_url   = f"https://polymarket.com/event/{ev_slug}"
    emoji      = conf_emoji(avg_conf)

    header = (
        f"{emoji}  {ev_title[:70]}{'…' if len(ev_title) > 70 else ''}  "
        f"│  {len(markets)} תרחישים  │  נפח: {fmt_vol(total_vol)}"
    )

    with st.expander(header, expanded=False):
        # כותרת + קישור + כפתור מעקב
        _wl_user = st.session_state.get("wallet_user", "")
        _hc1, _hc2 = st.columns([5, 1])
        with _hc1:
            st.html(f"""
<div style="margin:4px 0 12px;direction:rtl">
  <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.14);
              border-radius:10px;padding:12px 18px;margin-bottom:10px">
    <span style="color:#fff;font-size:18px;font-weight:800">{_html.escape(ev_title)}</span>
    <div style="color:#555;font-size:11px;margin-top:4px">
      {fmt_vol(total_vol)} Vol. &nbsp;·&nbsp; {end_date if end_date else ""}
    </div>
  </div>
  <a href="{poly_url}" target="_blank" style="display:inline-flex;align-items:center;gap:6px;
     background:rgba(0,204,102,0.12);color:#00cc66;border:1px solid rgba(0,204,102,0.3);
     border-radius:8px;padding:7px 14px;font-size:13px;font-weight:700;text-decoration:none">
    🔗 פתח בפולימרקט
  </a>
</div>""")
        with _hc2:
            if _wl_user:
                _is_wl = dw.watchlist_has(_wl_user, ev_slug)
                _wl_label = "⭐ במעקב" if _is_wl else "☆ מעקב"
                if st.button(_wl_label, key=f"wl_{ev_slug[:15]}", use_container_width=True):
                    if _is_wl:
                        dw.watchlist_remove(_wl_user, ev_slug)
                    else:
                        dw.watchlist_add(_wl_user, ev_slug, ev_title)
                    st.rerun()

        tab_scenarios, tab_whales, tab_trade = st.tabs(["🔍 תרחישים", "🐋 לווייתנים", "💼 קנה/מכור"])

        with tab_scenarios:
            sorted_markets = sorted(markets, key=lambda m: m["prices"][0] if m["prices"] else 0, reverse=True)
            ui_event_table(sorted_markets)
            st.caption(f"📊 {len(markets)} תרחישים · ממוין לפי הסתברות")

        with tab_whales:
            ui_event_whale_tab(markets)

        with tab_trade:
            ui_trade_tab(ev_slug, ev_title, markets)

    st.html("<div style='height:4px'></div>")

# ── שווקים עצמאיים (ללא אירוע) ───────────────────────────────────────────────

for info in standalone:
    conf     = info["conf"]
    volume   = info["volume"]
    title    = info["title"]
    slug     = info["slug"]
    ev_slug  = info["ev_slug"]
    end_date = info["end_date"]
    prices   = info["prices"]
    outcomes = info["outcomes"]
    rec      = info["rec"]
    scenario = info["scenario"]
    desc     = info["desc"]
    vol_str  = fmt_vol(volume)
    emoji    = conf_emoji(conf)

    header = (
        f"{emoji}  {title[:65]}{'…' if len(title) > 65 else ''}  "
        f"│  ציון: {conf:.0f}/100  │  נפח: {vol_str}"
    )

    with st.expander(header, expanded=False):
        tab_market, tab_scenarios, tab_whales = st.tabs(["📋 שוק", "🔍 תרחישים", "🐋 לווייתנים"])

        with tab_market:
            ui_market_title(title, slug, ev_slug)
            d1, d2 = st.columns(2)
            d1.metric("💰 נפח מסחר כולל", vol_str)
            d2.metric("📅 תאריך תפוגה",   end_date if end_date else "לא צוין")
            ui_section("🗳️", "תוצאות השוק")
            ui_full_outcomes_table(outcomes, prices, volume, rec.get("side"))
            ui_section("📊", "ציון ביטחון")
            ui_confidence_bar(conf)
            if desc:
                ui_section("📖", "תיאור")
                st.caption(desc[:400])

        with tab_scenarios:
            ui_market_title(title, slug, ev_slug)
            ui_section("🗳️", "תרחישים ואפשרויות הימור")
            ui_full_outcomes_table(outcomes, prices, volume, rec.get("side"))

        with tab_whales:
            ui_whale_tab(prices, outcomes, volume, conf, scenario)

    st.html("<div style='height:4px'></div>")
