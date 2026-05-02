"""
Polymarket Mobile — מותאם iPhone 16 Pro Max
"""
import json, sqlite3
from datetime import datetime, timezone, timedelta
import urllib.request, urllib.parse

import pandas as pd
import requests
import streamlit as st
import demo_wallet as dw

dw.init_tables()

st.set_page_config(
    page_title="🐋 Polymarket Mobile",
    page_icon="🐋",
    layout="centered",
    initial_sidebar_state="collapsed",
)
st.html("""
<link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🐋</text></svg>">
<meta name="apple-mobile-web-app-title" content="Polymarket">
""")

# ── viewport + CSS מותאם Android ─────────────────────────────────────────────

st.html("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#111318">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<style>
  /* ── צבעי בסיס ── */
  html, body, .stApp,
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"],
  section[data-testid="stMain"] > div {
    background: #111318 !important;
  }
  html, body, .stApp {
    direction: rtl;
    font-family: 'Google Sans', Roboto, -apple-system, Arial, sans-serif;
    background: #111318;
    color: #e8eaed;
    max-width: 440px;
    margin: 0 auto;
    -webkit-font-smoothing: antialiased;
  }

  /* ── הסתרת UI מיותר ── */
  [data-testid="stSidebar"],
  [data-testid="collapsedControl"],
  header[data-testid="stHeader"] { display: none !important; }

  /* ── container ── */
  .main .block-container {
    padding: 0 10px 90px !important;
    max-width: 440px !important;
  }

  /* ── כפתורים — Material Design ── */
  .stButton > button {
    min-height: 52px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    border-radius: 26px !important;
    width: 100% !important;
    letter-spacing: 0.3px !important;
    -webkit-tap-highlight-color: transparent !important;
    transition: all 0.15s ease !important;
  }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1a73e8, #0d47a1) !important;
    border: none !important;
    box-shadow: 0 2px 8px rgba(26,115,232,0.35) !important;
  }
  .stButton > button:active {
    transform: scale(0.97) !important;
    opacity: 0.9 !important;
  }

  /* ── כרטיסי מדד ── */
  [data-testid="stMetric"] {
    background: #1e2028 !important;
    border-radius: 20px !important;
    padding: 16px !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3) !important;
  }
  [data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 700 !important; }
  [data-testid="stMetricLabel"] { font-size: 11px !important; color: #9aa0a6 !important; }

  /* ── טאבים — Material style ── */
  [data-testid="stTabs"] {
    position: sticky; top: 0; z-index: 100;
    background: #111318;
    border-bottom: 1px solid rgba(255,255,255,0.07);
  }
  [data-testid="stTabs"] button {
    font-size: 13px !important;
    min-height: 48px !important;
    font-weight: 600 !important;
    background: transparent !important;
    letter-spacing: 0.2px !important;
  }

  /* ── inputs ── */
  .stTextInput input, .stNumberInput input {
    font-size: 16px !important;
    border-radius: 14px !important;
    min-height: 50px !important;
    background: #1e2028 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    padding: 0 16px !important;
  }
  .stTextInput input:focus, .stNumberInput input:focus {
    border-color: #1a73e8 !important;
    box-shadow: 0 0 0 2px rgba(26,115,232,0.2) !important;
  }

  /* ── expanders — Material cards ── */
  [data-testid="stExpander"] {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 18px !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    margin-bottom: 10px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.25) !important;
  }
  [data-testid="stExpander"] > div:first-child,
  [data-testid="stExpander"] details {
    background: transparent !important;
  }
  [data-testid="stExpander"] summary {
    background: transparent !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    min-height: 52px !important;
    padding: 0 16px !important;
    letter-spacing: 0.1px !important;
  }

  /* ── containers שקופים ── */
  .stApp > div, .main, .block-container,
  [data-testid="stVerticalBlock"] {
    background: transparent !important;
  }

  /* ── divider ── */
  [data-testid="stDivider"] { margin: 10px 0 !important; opacity: 0.08; }

  /* ── dataframe ── */
  [data-testid="stDataFrame"] {
    border-radius: 16px !important;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.06) !important;
  }

  /* ── slider ── */
  [data-testid="stSlider"] { padding: 10px 0 !important; }

  /* ── הסתר כל אלמנטי Streamlit ── */
  #MainMenu,
  footer,
  header,
  [data-testid="stToolbarActions"],
  [data-testid="stDecoration"],
  [data-testid="stStatusWidget"],
  [data-testid="stMainMenuButton"],
  [data-testid="baseButton-headerNoPadding"],
  .stDeployButton,
  .viewerBadge_container__r5tak,
  .styles_viewerBadge__CvC9N,
  [class*="viewerBadge"],
  [class*="toolbar"] { display: none !important; }

  /* הסתר כפתורים צפים בפינה */
  .st-emotion-cache-zq5wmm,
  .st-emotion-cache-1dp5vir,
  .e8zbici0 { display: none !important; }

  /* ── ripple effect לכפתורים ── */
  .stButton > button::after {
    content: '';
    position: absolute;
    border-radius: inherit;
    background: rgba(255,255,255,0.08);
    opacity: 0;
    transition: opacity 0.3s;
  }
  .stButton > button:active::after { opacity: 1; }

  /* ── select boxes ── */
  .stSelectbox > div > div {
    border-radius: 14px !important;
    background: #1e2028 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
  }

  /* ── radio buttons ── */
  [data-testid="stRadio"] label {
    font-size: 14px !important;
    padding: 6px 12px !important;
  }
</style>
""")

# ── תרגום אוטומטי ────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def translate_batch(texts: tuple) -> dict:
    if not texts:
        return {}
    SEP = " ||| "
    results = {}
    batch_size = 30
    lst = list(texts)
    for i in range(0, len(lst), batch_size):
        batch = lst[i:i+batch_size]
        try:
            payload = urllib.parse.urlencode({
                "client": "gtx", "sl": "en", "tl": "iw",
                "dt": "t", "q": SEP.join(batch)
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://translate.googleapis.com/translate_a/single",
                data=payload,
                headers={"User-Agent": "Mozilla/5.0",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            translated = "".join(s[0] for s in data[0] if s[0])
            parts = translated.split(SEP)
            if len(parts) == len(batch):
                results.update(zip(batch, parts))
            else:
                for t in batch: results[t] = t
        except Exception:
            for t in batch: results[t] = t
    return results


def tr(text: str) -> str:
    if not text: return text
    return st.session_state.get("_mob_trans", {}).get(text, text)

# ── נתונים ────────────────────────────────────────────────────────────────────

DB_PATH = "polymarket.db"

@st.cache_data(ttl=60, show_spinner=False)
def load_markets() -> pd.DataFrame:
    # Supabase (ענן)
    try:
        import urllib.request, urllib.parse, json as _j
        supa_url = st.secrets.get("SUPABASE_URL", "") or ""
        supa_key = st.secrets.get("SUPABASE_KEY", "") or ""
        if supa_url and supa_key:
            params = urllib.parse.urlencode({
                "select": "id,title,volume,confidence,yes_pct,no_pct,end_date,data",
                "order": "confidence.desc", "limit": "600"
            })
            req = urllib.request.Request(
                f"{supa_url}/rest/v1/markets?{params}",
                headers={"apikey": supa_key,
                         "Authorization": f"Bearer {supa_key}",
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

@st.cache_data(ttl=90, show_spinner=False)
def fetch_expiring(days: int) -> list[dict]:
    try:
        cutoff  = (datetime.now(timezone.utc)+timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get("https://gamma-api.polymarket.com/markets",
            params={"active":"true","closed":"false",
                    "end_date_max":cutoff,"end_date_min":now_str,"limit":150},
            timeout=10)
        if not r.ok: return []
        out = []
        for m in r.json():
            try:
                end_dt = datetime.fromisoformat((m.get("endDate","")or"").replace("Z","+00:00"))
                hours  = (end_dt-datetime.now(timezone.utc)).total_seconds()/3600
                if hours < 0: continue
                prices_raw = m.get("outcomePrices","[]")
                prices = json.loads(prices_raw) if isinstance(prices_raw,str) else prices_raw
                yes_p = float(prices[0]) if prices else 0.5
                out.append({
                    "title": m.get("question","")[:80],
                    "yes_pct": yes_p*100,
                    "volume": float(m.get("volume",0)or 0),
                    "hours_left": hours,
                    "slug": m.get("slug",""),
                    "end_date": end_dt.strftime("%d/%m/%y"),
                })
            except: continue
        return sorted(out, key=lambda x: x["hours_left"])
    except: return []

def fmt_vol(v):
    if v>=1_000_000: return f"${v/1_000_000:.1f}M"
    if v>=1_000: return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

# ── זיכרון משתמש ─────────────────────────────────────────────────────────────

if "wallet_user" not in st.session_state:
    saved = st.query_params.get("user", "")
    if saved:
        # נסה לאמת מול Supabase — אם נכשל, בכל זאת קבל את המשתמש
        w = dw.get_wallet(saved)
        st.session_state.wallet_user = saved if (w or saved) else ""
    else:
        st.session_state.wallet_user = ""

# ── כותרת ────────────────────────────────────────────────────────────────────

user = st.session_state.wallet_user
try:
    _w = dw.get_or_create(user) if user else None
    wallet_bal = f"${_w['balance']:.0f}" if _w else ""
except Exception:
    wallet_bal = ""

st.html(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:16px 4px 8px;direction:rtl">
  <div>
    <div style="font-size:24px;font-weight:800;letter-spacing:-0.5px">🐋 Polymarket</div>
    <div style="color:#636366;font-size:12px;margin-top:2px">ניתוח שווקים בזמן אמת</div>
  </div>
  {"<div style='background:#1a1d24;border:1px solid #30d158;border-radius:12px;padding:8px 14px;text-align:center'>"
  +f"<div style='color:#636366;font-size:10px'>👤 {user}</div>"
  +f"<div style='color:#30d158;font-size:18px;font-weight:800'>{wallet_bal}</div></div>" if user else ""}
</div>
""")

# ── כפתור רענון נתונים ───────────────────────────────────────────────────────

if st.button("🔄 רענן נתונים מ-Polymarket", type="primary", use_container_width=True):
    import subprocess, sys, os
    with st.spinner("מעדכן נתונים... (כ-30 שניות)"):
        try:
            result = subprocess.run(
                [sys.executable, "main.py"],
                capture_output=True, text=True, timeout=120,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            st.cache_data.clear()
            if result.returncode == 0:
                st.success("✅ נתונים עודכנו!")
            else:
                st.warning("⚠️ עודכן עם אזהרות")
        except subprocess.TimeoutExpired:
            st.warning("⏱ לקח יותר מדי — נסה שוב")
        except Exception as e:
            st.error(f"שגיאה: {e}")
    st.rerun()

# ── ניווט (radio — נשמר אחרי rerun) ─────────────────────────────────────────

_nav = st.radio(
    "", ["📊 שווקים", "⏰ פגים", "💼 ארנק", "🎯 ארביטראז'", "⭐ מעקב"],
    horizontal=True, key="mob_nav", label_visibility="collapsed"
)

# ════════════════════════════════════════════════════════
# 📊 שווקים
# ════════════════════════════════════════════════════════

if _nav == "📊 שווקים":
    df_raw = load_markets()

    # ── חיפוש תמיד גלוי ─────────────────────────────────
    search = st.text_input("🔍 חפש שוק", placeholder="bitcoin, trump, israel…", key="m_s")

    # ── פילטרים נוספים ──────────────────────────────────
    with st.expander("⚙️ פילטרים", expanded=False):
        min_conf = st.slider("ציון ביטחון מינימלי", 0, 100, 0, step=10, key="m_c")
        sort_by  = st.segmented_control("מיון", ["ביטחון ↓","נפח ↓","תפוגה ↑"], default="ביטחון ↓", key="m_sort")
        exp_days = st.select_slider("תפוגה עד (ימים)", options=[7,14,20,30,60,90,"הכל"], value="הכל", key="m_exp")

    if df_raw.empty:
        st.warning("אין נתונים. הרץ `python main.py` במחשב.")
        st.stop()

    df = df_raw.copy()
    if search:
        df = df[df["title"].str.contains(search, case=False, na=False)]
    df = df[df["confidence"] >= min_conf]
    if exp_days != "הכל":
        cutoff = (datetime.utcnow().date() + timedelta(days=int(exp_days))).isoformat()
        df = df[df["end_date"].fillna("9999-12-31").str[:10] <= cutoff]
    if sort_by == "נפח ↓":
        df = df.sort_values("volume", ascending=False)
    elif sort_by == "תפוגה ↑":
        df = df.sort_values("end_date", ascending=True)

    # תרגום אוטומטי של כל הכותרות
    all_titles = tuple(df["title"].dropna().unique())
    if "_mob_trans" not in st.session_state or len(st.session_state.get("_mob_trans",{})) < len(all_titles):
        with st.spinner("מתרגם כותרות לעברית…"):
            st.session_state["_mob_trans"] = translate_batch(all_titles)

    # קיבוץ לפי אירוע
    event_groups: dict[str, dict] = {}
    standalone_list: list[dict]   = []

    for _, row in df.head(60).iterrows():
        try:
            m_data   = json.loads(row.get("data","{}") or "{}")
            conf     = float(row.get("confidence", 50))
            volume   = float(row.get("volume", 0))
            title    = str(row.get("title",""))
            end      = str(row.get("end_date","") or "")[:10]
            ev_slug  = str(m_data.get("event_slug","") or "")
            ev_title = str(m_data.get("event_title","") or title)
            grp_lbl  = str(m_data.get("group_label","") or title)
            slug     = str(m_data.get("slug","") or "")
            prices_r = m_data.get("price",[])
            outcomes_r = m_data.get("outcomes",[])
            prices   = [float(p) for p in (json.loads(prices_r) if isinstance(prices_r,str) else prices_r)] if prices_r else []
            outcomes = json.loads(outcomes_r) if isinstance(outcomes_r,str) else outcomes_r
            if not outcomes: outcomes = ["Yes","No"] if len(prices)==2 else []
            n = min(len(outcomes),len(prices))
            prices,outcomes = prices[:n],outcomes[:n]
            if not prices: prices=[float(row.get("yes_pct",50))/100, float(row.get("no_pct",50))/100]
            info = dict(title=title, ev_title=ev_title, grp_lbl=grp_lbl,
                       slug=slug, ev_slug=ev_slug, conf=conf, volume=volume,
                       end=end, prices=prices, outcomes=outcomes,
                       vol_24h=float(m_data.get("vol_24h",0) or 0))
            if ev_slug:
                if ev_slug not in event_groups:
                    event_groups[ev_slug] = dict(ev_title=ev_title, ev_slug=ev_slug,
                                                  end=end, markets=[], total_vol=0, avg_conf=0)
                event_groups[ev_slug]["markets"].append(info)
                event_groups[ev_slug]["total_vol"] += volume
            else:
                standalone_list.append(info)
        except: continue

    st.caption(f"מציג {len(event_groups)+len(standalone_list)} אירועים")
    username = st.session_state.wallet_user

    def _mob_market_body(markets: list[dict], ev_slug: str, ev_title_raw: str) -> None:
        """תוכן expander: תרחישים + קנייה + לווייתנים."""
        wallet_now = dw.get_or_create(username) if username else None

        # ── לשונית בחירה ─────────────────────────────────────
        view = st.radio("תצוגה:", ["📋 תרחישים","💼 קנה/מכור","🐋 לווייתנים"],
                        horizontal=True, key=f"view_{ev_slug}",
                        label_visibility="collapsed")

        if view == "📋 תרחישים":
            for m in sorted(markets, key=lambda x: x["prices"][0] if x["prices"] else 0, reverse=True):
                yes_p = m["prices"][0] if m["prices"] else 0.5
                no_p  = max(0.0, 1-yes_p)
                lbl = tr(m["grp_lbl"])
                poly = f"https://polymarket.com/event/{m['slug']}" if m["slug"] else "#"
                st.html(f"""
<div style="background:#22252e;border-radius:14px;padding:14px;margin-bottom:8px;direction:rtl">
  <div style="font-size:14px;font-weight:700;color:#f2f2f7;margin-bottom:10px;line-height:1.3">{lbl}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
    <div style="background:#0d3320;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">Yes</div>
      <div style="color:#30d158;font-weight:800;font-size:17px">{yes_p*100:.0f}%</div>
      <div style="color:#30d158;font-size:12px">{int(yes_p*100)}¢</div>
    </div>
    <div style="background:#1f0a0d;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">No</div>
      <div style="color:#ff453a;font-weight:800;font-size:17px">{no_p*100:.0f}%</div>
      <div style="color:#ff453a;font-size:12px">{int(no_p*100)}¢</div>
    </div>
    <div style="background:#1a1d24;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">נפח</div>
      <div style="color:#f2f2f7;font-weight:700;font-size:14px">{fmt_vol(m['volume'])}</div>
      <a href="{poly}" target="_blank" style="color:#0a84ff;font-size:11px;text-decoration:none">פתח ↗</a>
    </div>
  </div>
</div>""")

        elif view == "💼 קנה/מכור":
            if not username:
                st.info("💼 התחבר לארנק בטאב 'ארנק' כדי לסחור")
            else:
                bal = wallet_now["balance"] if wallet_now else 0
                st.html(f"""<div style="background:#1c1c2e;border:1px solid #30d158;border-radius:12px;
                    padding:10px 14px;margin-bottom:12px;direction:rtl">
                  <span style="color:#30d158;font-weight:700">👤 {username}</span>
                  &nbsp;·&nbsp;<span style="color:#f2f2f7;font-weight:800">יתרה: ${bal:.2f}</span>
                </div>""")
                for m in sorted(markets, key=lambda x: x["prices"][0] if x["prices"] else 0, reverse=True):
                    yes_p = m["prices"][0] if m["prices"] else 0.5
                    no_p  = max(0.0, 1-yes_p)
                    lbl   = tr(m["grp_lbl"])
                    mid_slug = m["slug"] or ev_slug
                    with st.expander(f"🎯 {lbl[:45]}  ({yes_p*100:.0f}%)", expanded=False):
                        st.caption(f"Yes {int(yes_p*100)}¢ → על $100 תקבל ${100/yes_p:.0f}  |  No {int(no_p*100)}¢ → ${100/no_p:.0f}")
                        amt = st.number_input("סכום ($)", 1.0, float(max(1,bal)), min(10.0,float(bal)),
                                             5.0, key=f"mob_amt_{ev_slug}_{m['grp_lbl'][:20]}")
                        c1,c2 = st.columns(2)
                        with c1:
                            if st.button(f"✅ Yes {int(yes_p*100)}¢", use_container_width=True,
                                        key=f"mob_by_{ev_slug}_{m['grp_lbl'][:20]}"):
                                ok,msg = dw.open_position(username, mid_slug, m["title"],
                                    m["grp_lbl"], ev_title_raw, "yes", amt, yes_p, m.get("end",""))
                                (st.success if ok else st.error)(msg)
                                if ok: st.rerun()
                        with c2:
                            if st.button(f"🔴 No {int(no_p*100)}¢", use_container_width=True,
                                        key=f"mob_bn_{ev_slug}_{m['grp_lbl'][:20]}"):
                                ok,msg = dw.open_position(username, mid_slug, m["title"],
                                    m["grp_lbl"], ev_title_raw, "no", amt, no_p, m.get("end",""))
                                (st.success if ok else st.error)(msg)
                                if ok: st.rerun()

        else:  # 🐋 לווייתנים
            total_vol = sum(m["volume"] for m in markets)
            sorted_m  = sorted(markets, key=lambda x: x["volume"], reverse=True)
            dom = sorted_m[0] if sorted_m else None
            if dom:
                yes_p = dom["prices"][0] if dom["prices"] else 0.5
                dom_lbl = tr(dom["grp_lbl"])
                st.html(f"""
<div style="background:#0d3320;border:2px solid #30d158;border-radius:14px;
            padding:14px;margin-bottom:12px;text-align:center">
  <div style="color:#30d158;font-size:13px;font-weight:700;margin-bottom:4px">
    ✅ רוב הכסף הגדול זורם ל:
  </div>
  <div style="color:#f2f2f7;font-size:17px;font-weight:800">{dom_lbl}</div>
  <div style="color:#636366;font-size:12px;margin-top:4px">
    {dom['volume']/total_vol*100:.0f}% מנפח האירוע · ~{max(1,int(dom['volume']/50000))} ארנקים גדולים
  </div>
</div>""")
            for m in sorted_m[:6]:
                yes_p = m["prices"][0] if m["prices"] else 0.5
                share = m["volume"]/total_vol*100 if total_vol>0 else 0
                lbl   = tr(m["grp_lbl"])
                roi_y = (1/yes_p-1)*100 if yes_p>0.01 else 0
                bar_w = min(share*2, 100)
                st.html(f"""
<div style="margin:6px 0;direction:rtl">
  <div style="display:flex;justify-content:space-between;margin-bottom:4px">
    <span style="font-size:13px;font-weight:600;color:#f2f2f7">{lbl[:40]}</span>
    <span style="font-size:12px;color:#636366">{share:.0f}% · {fmt_vol(m['volume'])} · +{roi_y:.0f}% ROI</span>
  </div>
  <div style="background:#22252e;border-radius:6px;height:8px;overflow:hidden">
    <div style="background:#30d158;width:{bar_w:.0f}%;height:100%;border-radius:6px"></div>
  </div>
</div>""")

    # ── תצוגת אירועים ────────────────────────────────────
    for ev_slug, ev in event_groups.items():
        ev_t    = tr(ev["ev_title"])
        total_v = ev["total_vol"]
        n_mrk   = len(ev["markets"])
        poly_u  = f"https://polymarket.com/event/{ev_slug}"

        header = f"{ev_t[:50]}{'…' if len(ev_t)>50 else ''}  │  {n_mrk} תרחישים  │  {fmt_vol(total_v)}"
        with st.expander(header, expanded=False):
            hc1, hc2 = st.columns([4, 1])
            with hc1:
                st.html(f"""<div style="display:flex;justify-content:space-between;align-items:center;
                            margin-bottom:6px;direction:rtl">
                  <span style="color:#636366;font-size:11px">📅 {ev['end']}</span>
                  <a href="{poly_u}" target="_blank"
                     style="color:#0a84ff;font-size:12px;font-weight:700;text-decoration:none">
                    🔗 פתח</a>
                </div>""")
            with hc2:
                if username:
                    is_w = dw.watchlist_has(username, ev_slug)
                    if st.button("⭐" if is_w else "☆", key=f"wl_ev_{ev_slug[:15]}", help="הוסף/הסר ממעקב"):
                        if is_w: dw.watchlist_remove(username, ev_slug)
                        else: dw.watchlist_add(username, ev_slug, ev["ev_title"])
                        st.rerun()
            _mob_market_body(ev["markets"], ev_slug, ev["ev_title"])
        st.html("<div style='height:4px'></div>")

    # ── שווקים עצמאיים ───────────────────────────────────
    for m in standalone_list:
        title_d = tr(m["title"])
        poly_u  = f"https://polymarket.com/event/{m['slug']}" if m["slug"] else "#"
        yes_p   = m["prices"][0] if m["prices"] else 0.5
        header  = f"{title_d[:55]}{'…' if len(title_d)>55 else ''}  │  {yes_p*100:.0f}%  │  {fmt_vol(m['volume'])}"
        with st.expander(header, expanded=False):
            hc1, hc2 = st.columns([4, 1])
            with hc1:
                st.html(f"""<div style="display:flex;justify-content:space-between;margin-bottom:6px">
                  <span style="color:#636366;font-size:11px">📅 {m['end']}</span>
                  <a href="{poly_u}" target="_blank"
                     style="color:#0a84ff;font-size:12px;font-weight:700;text-decoration:none">🔗 פתח</a>
                </div>""")
            with hc2:
                if username:
                    is_w = dw.watchlist_has(username, m["slug"])
                    if st.button("⭐" if is_w else "☆", key=f"wl_m_{m['slug'][:15]}", help="הוסף/הסר ממעקב"):
                        if is_w: dw.watchlist_remove(username, m["slug"])
                        else: dw.watchlist_add(username, m["slug"], m["title"])
                        st.rerun()
            _mob_market_body([m], m["slug"], m["title"])
        st.html("<div style='height:4px'></div>")

# ════════════════════════════════════════════════════════
# ⏰ פגים בקרוב
# ════════════════════════════════════════════════════════

elif _nav == "⏰ פגים":
    days_sel = st.select_slider("תפוגה עד", options=[1,3,7,14,20], value=7, key="exp_d")

    with st.spinner("מביא נתונים…"):
        expiring = fetch_expiring(days_sel)

    if not expiring:
        st.info(f"אין שווקים שפגים ב-{days_sel} ימים הקרובים.")
    else:
        # תרגום
        exp_titles = tuple(set(m["title"] for m in expiring))
        existing = st.session_state.get("_mob_trans", {})
        new_t = tuple(t for t in exp_titles if t not in existing)
        if new_t:
            with st.spinner("מתרגם…"):
                existing.update(translate_batch(new_t))
                st.session_state["_mob_trans"] = existing

        st.caption(f"נמצאו {len(expiring)} שווקים")

        for m in expiring:
            h = m["hours_left"]
            d = h/24
            if h < 24:   badge,bc = f"🔴 {h:.0f} שעות", "#ff453a"
            elif d < 3:  badge,bc = f"🟠 {d:.1f} ימים",  "#ff9f0a"
            elif d < 7:  badge,bc = f"🟡 {d:.1f} ימים",  "#ffd60a"
            else:        badge,bc = f"🟢 {d:.0f} ימים",  "#30d158"

            poly_url = f"https://polymarket.com/event/{m['slug']}" if m["slug"] else "#"
            title    = tr(m["title"])

            st.html(f"""
<div style="background:#1a1d24;border-radius:16px;padding:16px;margin-bottom:10px;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:10px">
    <div style="font-size:14px;font-weight:700;color:#f2f2f7;line-height:1.4;flex:1">{title}</div>
    <div style="color:{bc};font-weight:800;font-size:13px;white-space:nowrap;flex-shrink:0">{badge}</div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="display:flex;gap:8px">
      <span style="background:#0d3320;color:#30d158;padding:6px 12px;border-radius:10px;
                   font-size:13px;font-weight:700">Yes {m['yes_pct']:.0f}%</span>
      <span style="color:#636366;font-size:13px;padding:6px 0">{fmt_vol(m['volume'])}</span>
    </div>
    <a href="{poly_url}" target="_blank"
       style="background:#0a84ff;color:#fff;padding:8px 16px;border-radius:10px;
              font-size:13px;font-weight:700;text-decoration:none">פתח ↗</a>
  </div>
</div>""")

# ════════════════════════════════════════════════════════
# 💼 ארנק
# ════════════════════════════════════════════════════════

elif _nav == "💼 ארנק":
    if not st.session_state.wallet_user:
        st.markdown("## 💼 התחבר לארנק שלך")
        all_w = dw.get_all_wallets()

        # משתמשים קיימים
        if all_w:
            names = [w["username"] for w in all_w]
            sel = st.selectbox("👤 משתמש קיים:", ["— בחר —"] + names, key="mob_sel")
            if sel != "— בחר —":
                if st.button("✅ כניסה", type="primary", key="mob_in", use_container_width=True):
                    st.session_state.wallet_user = sel
                    st.query_params["user"] = sel
                    st.rerun()
            st.divider()

        # יצירת ארנק חדש — תמיד גלוי
        st.markdown("**או צור ארנק חדש:**")
        nn = st.text_input("שם משתמש:", placeholder="לדוג׳: GamblerPro", key="mob_nn")
        if st.button("✅ צור ארנק חדש", type="primary", key="mob_cr", use_container_width=True):
            if nn.strip():
                dw.get_or_create(nn.strip())
                st.session_state.wallet_user = nn.strip()
                st.query_params["user"] = nn.strip()
                st.rerun()
            else:
                st.warning("הכנס שם משתמש")
    else:
        username = st.session_state.wallet_user
        with st.spinner("🔄 מסנכרן מחירים…"):
            price_changes = dw.sync_prices(username)
        wallet = dw.get_or_create(username)
        stats  = dw.get_stats(username)
        if price_changes:
            g = sum(1 for v in price_changes.values() if v > 0)
            l = sum(1 for v in price_changes.values() if v < 0)
            st.html(f"""<div style="background:rgba(10,132,255,0.1);border:1px solid #0a84ff;
                border-radius:12px;padding:10px 14px;margin-bottom:10px;text-align:center">
              <span style="color:#0a84ff;font-weight:700">🔄 עודכן מ-Polymarket</span>
              &nbsp; <span style="color:#30d158">↑{g}</span>
              &nbsp; <span style="color:#ff453a">↓{l}</span>
            </div>""")

        st.html(f"""
<div style="background:linear-gradient(135deg,#0d3320,#0d1f3c);border-radius:20px;
            padding:24px;margin:8px 0 16px;text-align:center">
  <div style="color:#636366;font-size:12px;margin-bottom:6px">👤 {username}</div>
  <div style="color:#f2f2f7;font-size:40px;font-weight:900;letter-spacing:-1px">
    ${wallet['balance']:.2f}
  </div>
  <div style="color:#636366;font-size:12px;margin-top:6px">יתרה זמינה</div>
</div>""")

        c1,c2,c3 = st.columns(3)
        wr_c  = "#30d158" if stats["win_rate"]>=50 else "#ff453a"
        c1.metric("🎯 עסקאות",  stats["total_trades"])
        c2.metric("🏆 הצלחה",   f"{stats['win_rate']:.0f}%")
        c3.metric("📈 P&L",     f"${stats['total_pnl']:+.2f}")

        # ── רווח ממומש / לא ממומש ────────────────────────────────
        _open_inv  = stats["open_invested"]
        _unreal    = stats["unrealized_pnl"]
        _real      = stats["total_pnl"]
        _closed_inv = sum(p["amount"] for p in dw.get_positions(username) if p["status"]!="open") or 1
        _uc = "#30d158" if _unreal>=0 else "#ff453a"
        _rc = "#30d158" if _real>=0   else "#ff453a"
        _us = "+" if _unreal>=0 else ""
        _rs = "+" if _real>=0   else ""
        _up = (_unreal/_open_inv*100) if _open_inv>0 else 0
        _rp = (_real/_closed_inv*100) if _closed_inv>0 else 0

        st.html(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0;direction:rtl">
  <div style="background:#1a1d24;border-radius:16px;padding:14px;border:1px solid rgba(255,255,255,0.06)">
    <div style="color:#9aa0a6;font-size:11px;margin-bottom:6px">📊 לא ממומש</div>
    <div style="color:{_uc};font-size:22px;font-weight:800">{_us}${_unreal:.2f}</div>
    <div style="color:{_uc};font-size:12px;margin-top:3px">{_us}{_up:.1f}%</div>
  </div>
  <div style="background:#1a1d24;border-radius:16px;padding:14px;border:1px solid rgba(255,255,255,0.06)">
    <div style="color:#9aa0a6;font-size:11px;margin-bottom:6px">✅ ממומש</div>
    <div style="color:{_rc};font-size:22px;font-weight:800">{_rs}${_real:.2f}</div>
    <div style="color:{_rc};font-size:12px;margin-top:3px">{_rs}{_rp:.1f}%</div>
  </div>
</div>""")

        # ── סנכרון מחירים חי ─────────────────────────────────────
        if st.button("🔄 סנכרן מחירים מ-Polymarket", use_container_width=True, key="mob_sync"):
            with st.spinner("מסנכרן..."):
                changes = dw.sync_prices(username)
            st.success(f"✅ עודכנו {len(changes)} פוזיציות")
            st.rerun()

        # הפקדה
        with st.expander("💰 הפקד כסף"):
            dep = st.number_input("סכום ($)", 1.0, 10000.0, 100.0, 50.0, key="mob_dep")
            if st.button("💵 הפקד", type="primary", key="mob_dep_b"):
                if dw.deposit(username, dep):
                    st.success(f"✅ הופקדו ${dep:.2f}")
                    st.rerun()

        # פוזיציות פתוחות
        open_p = dw.get_positions(username, "open")
        if open_p:
            st.markdown(f"### 🟢 {len(open_p)} פוזיציות פתוחות")
            for p in open_p:
                unreal = (p["current_price"]/p["entry_price"]-1)*p["amount"] if p["entry_price"]>0 else 0
                dir_l  = "✅ YES" if p["direction"]=="yes" else "🔴 NO"
                uc     = "#30d158" if unreal>=0 else "#ff453a"
                end_s  = (p.get("end_date",""))[:10] or "—"

                st.html(f"""
<div style="background:#1a1d24;border-radius:16px;padding:16px;margin-bottom:10px;direction:rtl">
  <div style="font-size:13px;font-weight:700;color:#f2f2f7;margin-bottom:10px">
    {dir_l} · {p['group_label'][:45]}
  </div>
  <!-- מדדי פוזיציה -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px">
    <div style="background:#22252e;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">השקעה</div>
      <div style="font-weight:800;font-size:15px">${p['amount']:.2f}</div>
    </div>
    <div style="background:#22252e;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">פוטנציאל</div>
      <div style="font-weight:800;font-size:15px">${p['potential_win']:.2f}</div>
    </div>
    <div style="background:#22252e;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">P&L</div>
      <div style="font-weight:800;font-size:15px;color:{uc}">${unreal:+.2f}</div>
    </div>
  </div>
  <!-- מחירי קנייה נוכחיים -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
    <div style="background:#0d3320;border:1px solid rgba(48,209,88,0.3);
                border-radius:12px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px;margin-bottom:3px">Buy Yes</div>
      <div style="color:#30d158;font-weight:800;font-size:18px">{int(round(p['current_price']*100))}¢</div>
      <div style="color:#636366;font-size:10px;margin-top:2px">
        {'▲' if p['current_price'] > p['entry_price'] else ('▼' if p['current_price'] < p['entry_price'] else '—')}
        כניסה: {int(round(p['entry_price']*100))}¢
      </div>
    </div>
    <div style="background:#1f0a0d;border:1px solid rgba(255,69,58,0.3);
                border-radius:12px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px;margin-bottom:3px">Buy No</div>
      <div style="color:#ff453a;font-weight:800;font-size:18px">{int(round(max(0,1-p['current_price'])*100))}¢</div>
      <div style="color:#636366;font-size:10px;margin-top:2px">
        תשואה: +{((1/p['current_price']-1)*100):.0f}% על Yes
      </div>
    </div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center">
    <span style="color:#636366;font-size:11px">📅 תפוגה: {end_s}</span>
    <span style="color:{uc};font-size:12px;font-weight:700">
      {'📈' if unreal >= 0 else '📉'} {((p['current_price']/p['entry_price']-1)*100):+.1f}%
    </span>
  </div>
</div>""")
                if st.button(f"💰 מכור פוזיציה", key=f"mob_sell_{p['id']}", type="primary"):
                    ok, msg = dw.sell_position(p["id"], username)
                    (st.success if ok else st.error)(msg)
                    if ok: st.rerun()

        # היסטוריה
        closed = [p for p in dw.get_positions(username) if p["status"]!="open"]
        if closed:
            with st.expander(f"📋 היסטוריה ({len(closed)} עסקאות)"):
                rows = [{"תאריך": p["timestamp"][:10],
                         "תרחיש": p["group_label"][:28],
                         "תוצאה": "🏆" if p["status"]=="won" else "❌",
                         "P&L": f"${p['pnl']:+.2f}"} for p in closed[:30]]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.divider()
        if st.button("🚪 התנתק", key="mob_out"):
            st.session_state.wallet_user = ""
            st.query_params.pop("user", None)
            st.rerun()

# ════════════════════════════════════════════════════════
# 🎯 ארביטראז'
# ════════════════════════════════════════════════════════

elif _nav == "🎯 ארביטראז'":
    st.html("""
<div style="padding:8px 0 14px;direction:rtl">
  <div style="font-size:18px;font-weight:800">🎯 Negative Spread Scanner</div>
  <div style="color:#636366;font-size:12px;margin-top:4px">Yes + No &lt; 0.95 = הזדמנות</div>
</div>""")

    if st.button("🔍 סרוק הזדמנויות", type="primary", key="mob_arb"):
        with st.spinner("סורק שווקים…"):
            try:
                import arbitrage_scanner as am
                opps = am.scan(use_clob=False)
            except Exception as e:
                opps = []
                st.error(str(e))

        if not opps:
            st.info("לא נמצאו הזדמנויות כרגע.")
        else:
            st.success(f"✅ נמצאו {len(opps)} הזדמנויות!")

            # תרגום שמות השווקים
            arb_titles = tuple(set(o["question"] for o in opps))
            existing = st.session_state.get("_mob_trans", {})
            new_arb = tuple(t for t in arb_titles if t not in existing)
            if new_arb:
                existing.update(translate_batch(new_arb))
                st.session_state["_mob_trans"] = existing

            for o in opps[:15]:
                roi   = o["roi"]
                total = o["total"]
                rc    = "#ff453a" if total<=0.85 else ("#ff9f0a" if total<=0.90 else "#30d158")
                badge = "🔴 HIGH" if total<=0.85 else ("🟠 ALERT" if total<=0.90 else "🟢 STD")
                poly  = f"https://polymarket.com/event/{o['slug']}" if o.get("slug") else "#"
                title = tr(o["question"])

                st.html(f"""
<div style="background:#1a1d24;border-radius:16px;padding:16px;margin-bottom:10px;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:10px">
    <div style="font-size:13px;font-weight:700;color:#f2f2f7;flex:1;line-height:1.4">{title[:65]}</div>
    <div style="color:{rc};font-weight:900;font-size:22px;flex-shrink:0">{roi:.1f}%</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px">
    <div style="background:#0d3320;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">Yes Ask</div>
      <div style="color:#30d158;font-weight:800;font-size:16px">{o['yes_ask']*100:.1f}¢</div>
    </div>
    <div style="background:#1f0a0d;border-radius:10px;padding:10px;text-align:center">
      <div style="color:#636366;font-size:10px">No Ask</div>
      <div style="color:#ff453a;font-weight:800;font-size:16px">{o['no_ask']*100:.1f}¢</div>
    </div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="display:flex;gap:10px;font-size:11px;color:#636366">
      <span>{badge}</span>
      <span>סכום: {total:.4f}</span>
      <span>Gap: {o['profit_gap']*100:.2f}%</span>
    </div>
    <a href="{poly}" target="_blank"
       style="background:#0a84ff;color:#fff;padding:8px 16px;border-radius:10px;
              font-size:13px;font-weight:700;text-decoration:none">פתח ↗</a>
  </div>
</div>""")

# ════════════════════════════════════════════════════════
# ⭐ מעקב
# ════════════════════════════════════════════════════════

elif _nav == "⭐ מעקב":
    username = st.session_state.wallet_user
    st.html("""
<div style="padding:8px 0 14px;direction:rtl">
  <div style="font-size:20px;font-weight:800">⭐ רשימת מעקב</div>
  <div style="color:#636366;font-size:12px;margin-top:4px">שווקים שסימנת + פוזיציות פתוחות</div>
</div>""")

    if not username:
        st.info("💼 התחבר לארנק כדי לראות את רשימת המעקב")
    else:
        # פוזיציות פתוחות
        open_p = dw.get_positions(username, "open")
        if open_p:
            st.markdown("### 🟢 פוזיציות פתוחות")
            for p in open_p:
                unreal = (p["current_price"]/p["entry_price"]-1)*p["amount"] if p["entry_price"]>0 else 0
                uc = "#30d158" if unreal>=0 else "#ff453a"
                dir_l = "✅ YES" if p["direction"]=="yes" else "🔴 NO"
                poly_u = f"https://polymarket.com/event/{p['market_id']}" if p.get("market_id") else "#"
                st.html(f"""
<div style="background:#1a1d24;border-radius:14px;padding:14px;margin-bottom:8px;direction:rtl">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <div style="font-size:13px;font-weight:700;color:#e8eaed;flex:1">{dir_l} · {p['group_label'][:40]}</div>
    <div style="color:{uc};font-weight:800;font-size:16px">${unreal:+.2f}</div>
  </div>
  <div style="display:flex;gap:12px;font-size:12px;color:#9aa0a6">
    <span>השקעה: ${p['amount']:.2f}</span>
    <span>כניסה: {p['entry_price']*100:.0f}¢</span>
    <span>עכשיו: {p['current_price']*100:.0f}¢</span>
    <a href="{poly_u}" target="_blank" style="color:#1a73e8;text-decoration:none;margin-right:auto">↗</a>
  </div>
</div>""")

        # Watchlist
        wl = dw.watchlist_get(username)
        if wl:
            st.markdown(f"### ⭐ במעקב ({len(wl)})")
            for w in wl:
                title = tr(w["title"])
                poly_u = f"https://polymarket.com/event/{w['slug']}"
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.html(f"""
<div style="background:#1a1d24;border-radius:12px;padding:12px 14px;direction:rtl">
  <div style="font-size:13px;font-weight:600;color:#e8eaed;margin-bottom:4px">{title[:55]}</div>
  <a href="{poly_u}" target="_blank" style="color:#1a73e8;font-size:11px;text-decoration:none">🔗 פתח בפולימרקט</a>
</div>""")
                with col2:
                    if st.button("🗑", key=f"wl_rm_{w['slug'][:15]}", help="הסר ממעקב"):
                        dw.watchlist_remove(username, w["slug"])
                        st.rerun()
        elif not open_p:
            st.info("רשימת המעקב ריקה. סמן שווקים בכוכב ⭐ מלשונית השווקים.")
