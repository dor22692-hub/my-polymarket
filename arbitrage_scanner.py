"""
Negative Spread Scanner — Polymarket
מציג רק שווקים שבהם Yes_Ask + No_Ask < 0.95 (רווח מובטח ≥ 5% לפני עמלות)
"""
import html as _html
import json
from datetime import datetime, timezone

import requests
import streamlit as st
import pandas as pd

# ── קבועים ───────────────────────────────────────────────────────────────────

GAMMA_API          = "https://gamma-api.polymarket.com/markets"
CLOB_API           = "https://clob.polymarket.com"

HIGH_PRIORITY_MAX  = 0.85   # gap ≥ 15% → HIGH PRIORITY (flash)
ALERT_MAX          = 0.90   # gap ≥ 10% → ALERT
MAIN_THRESHOLD     = 0.95   # ≥ 5% → גלוי בתוצאות
SAFE_LIQ_CAP       = 0.98   # גבול בדיקת נזילות
SLIPPAGE           = 0.005  # 0.5% עמלה + slippage
MIN_USD_PER_SIDE   = 100.0  # $100 לכל צד
MIN_VOLUME         = 5_000  # נפח מינימלי

# ── שכבת Data ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_gamma(limit: int = 500) -> list[dict]:
    try:
        r = requests.get(
            GAMMA_API,
            params={"active": "true", "closed": "false", "limit": limit},
            timeout=12,
        )
        return r.json() if r.ok else []
    except Exception:
        return []


@st.cache_data(ttl=20, show_spinner=False)
def _fetch_book(token_id: str) -> dict | None:
    try:
        r = requests.get(f"{CLOB_API}/book", params={"token_id": token_id}, timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None


def _best_ask(book: dict | None, fallback: float) -> float:
    """מחיר Ask הנמוך ביותר מה-Order Book."""
    if not book:
        return fallback
    asks = book.get("asks", [])
    if not asks:
        return fallback
    return float(min(asks, key=lambda x: float(x["price"]))["price"])


def _available_usd(book: dict | None) -> float:
    """כמה $ זמינים לקנייה ב-Ask לפני שהמחיר יחצה את SAFE_LIQ_CAP."""
    if not book:
        return 0.0
    asks = sorted(book.get("asks", []), key=lambda x: float(x["price"]))
    total = 0.0
    for lvl in asks:
        p = float(lvl["price"])
        s = float(lvl.get("size", 0))
        if p >= SAFE_LIQ_CAP:
            break
        total += p * s
    return total


# ── לוגיקת סריקה ─────────────────────────────────────────────────────────────

def _parse_market(m: dict, use_clob: bool) -> dict | None:
    try:
        raw = m.get("outcomePrices", "[]")
        prices = json.loads(raw) if isinstance(raw, str) else raw
        if len(prices) < 2:
            return None

        yes_mid = float(prices[0])
        no_mid  = float(prices[1])

        # סינון מהיר לפני CLOB
        if yes_mid + no_mid >= MAIN_THRESHOLD + 0.03:
            return None

        yes_ask = yes_mid
        no_ask  = no_mid
        yes_liq = 0.0
        no_liq  = 0.0

        if use_clob:
            tokens = m.get("tokens", [])
            if len(tokens) >= 2:
                yb = _fetch_book(tokens[0].get("token_id", ""))
                nb = _fetch_book(tokens[1].get("token_id", ""))
                yes_ask = _best_ask(yb, yes_mid)
                no_ask  = _best_ask(nb, no_mid)
                yes_liq = _available_usd(yb)
                no_liq  = _available_usd(nb)

        total = yes_ask + no_ask
        if total >= MAIN_THRESHOLD:
            return None

        # פילטר נפח
        volume = float(m.get("volume", 0) or 0)
        if volume < MIN_VOLUME:
            return None

        # פילטר תפוגה (> 1 שעה)
        remaining_h: float | None = None
        end_date = m.get("endDate", "")
        if end_date:
            try:
                exp = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                remaining_h = (exp - datetime.now(timezone.utc)).total_seconds() / 3600
                if remaining_h < 1:
                    return None
            except Exception:
                pass

        # בדיקת נזילות מינימלית — $100 לכל צד
        liq_ok = (yes_liq >= MIN_USD_PER_SIDE and no_liq >= MIN_USD_PER_SIDE) if use_clob else True

        # מדדי רווח
        profit_gap    = 1.0 - total                       # Gap טרם עמלות
        yes_eff       = yes_ask * (1 + SLIPPAGE)
        no_eff        = no_ask  * (1 + SLIPPAGE)
        total_eff     = yes_eff + no_eff
        net_profit    = 1.0 - total_eff                   # רווח לאחר slippage

        if net_profit <= 0:
            return None

        # סיווג עדיפות
        if total <= HIGH_PRIORITY_MAX:
            priority = "HIGH"
        elif total <= ALERT_MAX:
            priority = "ALERT"
        else:
            priority = "STANDARD"

        return {
            "question":    m.get("question", "")[:90],
            "yes_ask":     yes_ask,
            "no_ask":      no_ask,
            "total":       total,
            "profit_gap":  profit_gap,
            "net_profit":  net_profit,
            "total_eff":   total_eff,
            "priority":    priority,
            "volume":      volume,
            "remaining_h": remaining_h,
            "liq_ok":      liq_ok,
            "min_liq":     min(yes_liq, no_liq) if use_clob else None,
            "slug":        m.get("slug", ""),
        }
    except Exception:
        return None


def scan(use_clob: bool = False) -> list[dict]:
    """מחזיר רשימה ממוינת לפי profit_gap (הגבוה ביותר ראשון)."""
    markets = _fetch_gamma()
    opps = [o for m in markets if (o := _parse_market(m, use_clob))]
    return sorted(opps, key=lambda x: x["profit_gap"], reverse=True)


# ── רכיבי UI ─────────────────────────────────────────────────────────────────

def _fmt_vol(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def _flash_alert_html(opps_high: list[dict]) -> None:
    """רכיב Flash Alert — מופיע רק כשיש הזדמנות > 10% רווח."""
    if not opps_high:
        return
    items_html = "".join(
        f'<div style="margin:3px 0;font-size:13px">'
        f'🔴 <b>{_html.escape(o["question"][:60])}…</b> '
        f'→ Gap: <b>{o["profit_gap"]*100:.1f}%</b></div>'
        for o in opps_high[:3]
    )
    st.html(f"""
<style>
@keyframes arb-flash {{
  0%,100% {{ background:rgba(255,50,50,0.10); border-color:rgba(255,50,50,0.5); }}
  50%     {{ background:rgba(255,50,50,0.25); border-color:rgba(255,50,50,0.9); }}
}}
.arb-flash {{
  animation: arb-flash 1.4s ease-in-out infinite;
  border: 2px solid;
  border-radius: 14px;
  padding: 14px 20px;
  direction: rtl;
  margin-bottom: 12px;
}}
</style>
<div class="arb-flash">
  <div style="color:#ff4455;font-size:15px;font-weight:800;margin-bottom:6px">
    ⚡ FLASH ALERT — {len(opps_high)} הזדמנות עם רווח ≥ 10%!
  </div>
  {items_html}
</div>""")


def _quick_math_badge(total: float) -> str:
    gap = (1.0 - total) * 100
    color = "#00cc66" if gap >= 10 else ("#ffbb00" if gap >= 5 else "#ff9944")
    return (
        f'<span style="background:rgba(255,255,255,0.06);border:1px solid {color}33;'
        f'border-radius:6px;padding:3px 8px;font-size:12px;font-weight:700;color:{color}">'
        f'1.00 − {total:.3f} = <b>{gap:.2f}%</b></span>'
    )


def _priority_card(opp: dict) -> None:
    pri      = opp["priority"]
    total    = opp["total"]
    gap_pct  = opp["profit_gap"] * 100
    net_pct  = opp["net_profit"] * 100
    q        = _html.escape(opp["question"])
    expiry   = f"{opp['remaining_h']:.1f}h" if opp["remaining_h"] else "—"
    poly_url = f"https://polymarket.com/event/{opp['slug']}" if opp["slug"] else "#"

    if pri == "HIGH":
        bg, border, badge, rc = (
            "rgba(255,50,50,0.10)", "2px solid #ff4455",
            "🔴 HIGH PRIORITY ≥15%", "#ff4455"
        )
    elif pri == "ALERT":
        bg, border, badge, rc = (
            "rgba(255,140,0,0.08)", "2px solid #ff8c00",
            "🟠 ALERT ≥10%", "#ff8c00"
        )
    else:
        bg, border, badge, rc = (
            "rgba(0,204,102,0.07)", "2px solid #00cc66",
            "🟢 STANDARD ≥5%", "#00cc66"
        )

    liq_html = ""
    if opp["min_liq"] is not None:
        liq_color = "#00cc66" if opp["liq_ok"] else "#ff4455"
        liq_label = "✅ נזילות OK" if opp["liq_ok"] else "⚠️ נזילות נמוכה"
        liq_html = (
            f'<span style="color:{liq_color};font-size:11px;font-weight:700">'
            f'{liq_label} (${opp["min_liq"]:.0f})</span>'
        )

    st.html(f"""
<div style="background:{bg};border:{border};border-radius:14px;
            padding:18px 22px;margin:8px 0;direction:rtl">

  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              gap:12px;flex-wrap:wrap">

    <div style="flex:1;min-width:220px">
      <div style="color:{rc};font-size:11px;font-weight:800;
                  letter-spacing:0.5px;margin-bottom:6px">{badge}</div>
      <div style="font-size:15px;font-weight:700;color:#eee;
                  margin-bottom:10px;line-height:1.45">{q}</div>

      <!-- מחירים -->
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
        <span style="background:#0e3d25;color:#00cc66;padding:5px 12px;
                     border-radius:7px;font-size:14px;font-weight:800;
                     border:1px solid rgba(0,204,102,0.3)">
          Yes Ask {opp['yes_ask']*100:.1f}¢
        </span>
        <span style="background:#3a1217;color:#ff6666;padding:5px 12px;
                     border-radius:7px;font-size:14px;font-weight:800;
                     border:1px solid rgba(255,68,85,0.3)">
          No Ask {opp['no_ask']*100:.1f}¢
        </span>
      </div>

      <!-- Quick Math -->
      <div style="margin-bottom:6px">{_quick_math_badge(total)}</div>
      {liq_html}
    </div>

    <!-- מדדי רווח -->
    <div style="text-align:left;flex-shrink:0;min-width:140px">
      <div style="color:{rc};font-weight:900;font-size:30px;line-height:1">
        {gap_pct:.2f}%
      </div>
      <div style="color:#888;font-size:11px;margin-top:2px">Profit Gap (ברוטו)</div>
      <div style="color:#ccc;font-size:14px;font-weight:700;margin-top:6px">
        {net_pct:.2f}% נטו
      </div>
      <div style="color:#555;font-size:11px">לאחר {SLIPPAGE*100:.1f}% slippage</div>
      <div style="color:#555;font-size:12px;margin-top:4px">
        סכום: <b style="color:#fff">{total:.4f}</b>
      </div>
    </div>
  </div>

  <!-- מטא-דטה -->
  <div style="margin-top:12px;padding-top:10px;
              border-top:1px solid rgba(255,255,255,0.07);
              display:flex;gap:20px;flex-wrap:wrap;font-size:12px;
              color:#555;align-items:center">
    <span>💰 נפח: <b style="color:#888">{_fmt_vol(opp['volume'])}</b></span>
    <span>⏱ תפוגה: <b style="color:#888">{expiry}</b></span>
    <span>Total: <b style="color:#aaa">{total:.4f}</b></span>
    <a href="{poly_url}" target="_blank"
       style="color:#00cc66;text-decoration:none;font-weight:700;margin-right:auto">
      🔗 פתח בפולימרקט ↗
    </a>
  </div>
</div>""")


# ── עמוד ראשי ────────────────────────────────────────────────────────────────

def ui_arbitrage_page(use_clob: bool = False) -> None:

    # כותרת
    st.html("""
<div style="direction:rtl;margin-bottom:6px">
  <h1 style="font-size:1.8rem;font-weight:800;margin:0">
    🎯 Negative Spread Scanner
  </h1>
  <p style="color:#666;font-size:13px;margin-top:4px">
    מציג <b style="color:#ccc">רק</b> שווקים שבהם Yes_Ask + No_Ask &lt; 0.95
    &nbsp;·&nbsp; ממוין לפי Profit Gap (הגדול ביותר ראשון)
    &nbsp;·&nbsp; עדכון כל 30 שניות
  </p>
</div>""")

    # סריקה
    with st.spinner("🔍 סורק שווקים פעילים..."):
        opps = scan(use_clob=use_clob)

    if not opps:
        st.html("""
<div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);
            border-radius:14px;padding:30px;text-align:center;direction:rtl">
  <div style="font-size:18px;color:#888;margin-bottom:8px">
    🔍 לא נמצאו הזדמנויות Negative Spread כרגע
  </div>
  <div style="font-size:13px;color:#555">
    כל השווקים הפעילים מציגים Yes + No ≥ 0.95 · הסריקה תתרענן אוטומטית
  </div>
</div>""")
        return

    # Flash Alert
    high_opps = [o for o in opps if o["total"] <= ALERT_MAX]
    _flash_alert_html(high_opps)

    # מדדי סיכום
    best   = opps[0]
    n_high = sum(1 for o in opps if o["priority"] == "HIGH")
    n_alrt = sum(1 for o in opps if o["priority"] == "ALERT")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🎯 סה״כ הזדמנויות",  len(opps))
    c2.metric("🔴 HIGH (≥15%)",      n_high)
    c3.metric("🟠 ALERT (≥10%)",     n_alrt)
    c4.metric("🏆 Gap מקסימלי",      f"{best['profit_gap']*100:.2f}%")
    c5.metric("📊 Net מקסימלי",      f"{best['net_profit']*100:.2f}%")

    st.divider()

    # סטטוס CLOB
    mode_label = "📡 CLOB (Ask אמיתי)" if use_clob else "📊 Gamma (Mid Price)"
    st.caption(f"מקור מחירים: **{mode_label}** · Slippage: {SLIPPAGE*100:.1f}% · Min Volume: ${MIN_VOLUME:,}")

    # ── כרטיסי הזדמנויות ───────────────────────────────────────────────────
    for opp in opps:
        _priority_card(opp)

    # ── טבלת Quick Math ───────────────────────────────────────────────────
    st.divider()
    st.markdown("### 📋 Quick Math Table")

    rows = []
    for o in opps:
        rows.append({
            "עדיפות":          o["priority"],
            "שוק":             o["question"][:55] + ("…" if len(o["question"]) > 55 else ""),
            "Yes Ask ¢":       f"{o['yes_ask']*100:.1f}",
            "No Ask ¢":        f"{o['no_ask']*100:.1f}",
            "1−(Y+N)=Gap%":    f"{o['profit_gap']*100:.2f}%",
            "Net% (−0.5%)":    f"{o['net_profit']*100:.2f}%",
            "נפח":             _fmt_vol(o["volume"]),
            "תפוגה":           f"{o['remaining_h']:.1f}h" if o["remaining_h"] else "—",
        })

    df = pd.DataFrame(rows)

    def _row_color(row):
        pri = row["עדיפות"]
        if pri == "HIGH":
            return ["background-color: rgba(255,50,50,0.15)"] * len(row)
        if pri == "ALERT":
            return ["background-color: rgba(255,140,0,0.12)"] * len(row)
        return ["background-color: rgba(0,204,102,0.07)"] * len(row)

    st.dataframe(
        df.style.apply(_row_color, axis=1),
        use_container_width=True,
        hide_index=True,
    )
