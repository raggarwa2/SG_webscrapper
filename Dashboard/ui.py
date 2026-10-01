"""
Look-and-feel layer for the SG dashboard: design tokens, component CSS and
small HTML helpers (banner, headline cards, section headers, insight strips).

Layout language is borrowed from the Pricing Control Tower reference pages
(gradient banner, 3-up headline findings, accent-bar KPI cards, section
eyebrow + title + caption, underlined tab nav, soft-shadow cards); the
palette is a neutral clinical blue so it stays this project's own.
Colour tokens live in :root so a re-brand is a one-place change.
"""

import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

CSS = """
<style>
:root{
  --ink:#051F4A;--ink-2:#0B3556;--primary:#178197;--primary-2:#0A7CC1;
  --sky:#59A5D7;--wash:#E8F3F5;--wash-2:#F8F8F8;--line:#E1E7EE;
  --text:#1F2933;--muted:#64748B;--faint:#94A3B8;
  --pos:#0F766E;--neg:#B42318;--warn:#B7791F;--warn-bg:#FFF7E6;
}
.block-container{padding-top:3.6rem;padding-bottom:3rem;max-width:1400px}
h1,h2,h3{letter-spacing:-.01em}

/* ---- Banner ---- */
.sg-banner{position:relative;overflow:hidden;color:#fff;padding:22px 28px;border-radius:16px;margin-bottom:16px;
  background:radial-gradient(120% 180% at 8% -30%,#59A5D7 0,#178197 42%,#051F4A 100%)}
.sg-eyebrow{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#D6EEF3;font-weight:700}
.sg-title{font-weight:800;font-size:26px;letter-spacing:-.015em;margin-top:6px;line-height:1.2}
.sg-sub{font-size:12.5px;opacity:.85;margin-top:6px}
.sg-pills{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
.sg-pill{font-size:10.5px;font-weight:700;color:var(--ink);background:var(--sky);padding:4px 11px;border-radius:20px}

/* ---- Headline findings (3-up) ---- */
.sg-findings{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:18px}
@media(min-width:960px){.sg-findings{grid-template-columns:repeat(3,1fr)}}
.sg-finding{background:linear-gradient(135deg,var(--wash),#fff 62%);border:1px solid var(--line);
  border-top:4px solid var(--primary);border-radius:14px;padding:16px 20px;
  box-shadow:0 10px 24px -16px rgba(23,129,151,.35)}
.sg-finding.alert{border-top-color:var(--neg)}
.sg-finding.warn{border-top-color:var(--warn)}
.sg-finding-n{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--primary);margin-bottom:8px}
.sg-finding.alert .sg-finding-n{color:var(--neg)}.sg-finding.warn .sg-finding-n{color:var(--warn)}
.sg-finding-h{font-size:15px;font-weight:800;color:var(--ink);line-height:1.35;margin-bottom:7px}
.sg-finding-b{font-size:12.5px;line-height:1.55;color:var(--muted)}
.sg-finding-b b{color:var(--ink)}

/* ---- Section header + insight strip ---- */
.sg-sec{margin:22px 0 10px}
.sg-sec .eb{font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--primary)}
.sg-sec h2{font-size:18px;font-weight:800;color:var(--ink);margin:2px 0 0;padding:0}
.sg-sec .cap{font-size:12px;color:var(--muted);margin-top:3px}
.sg-insight{margin:8px 0 12px;padding:9px 14px;background:var(--wash);border-left:3px solid var(--primary);
  border-radius:0 8px 8px 0;font-size:12.5px;font-weight:600;color:var(--ink)}
.sg-insight.warn{background:var(--warn-bg);border-left-color:var(--warn)}
.caveat-box{background:var(--warn-bg);border:1px solid #F1DFB0;border-left:4px solid var(--warn);
  padding:10px 16px;border-radius:8px;margin-bottom:1rem;font-size:.88rem;color:#5B4514}

/* ---- Native widgets, restyled ---- */
div[data-testid="stMetric"]{position:relative;overflow:hidden;background:#fff;border:1px solid var(--line);
  border-radius:14px;padding:14px 18px 12px 20px;box-shadow:0 2px 12px rgba(5,31,74,.05);min-height:118px;
  display:flex;flex-direction:column;justify-content:center}
div[data-testid="stMetric"]::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--primary)}
div[data-testid="stMetricLabel"],div[data-testid="stMetricLabel"] *{overflow:visible !important;height:auto !important;max-width:none !important}
div[data-testid="stMetricLabel"] p{font-size:.68rem !important;font-weight:700 !important;text-transform:uppercase !important;
  letter-spacing:.07em !important;color:var(--muted) !important;white-space:normal !important;line-height:1.3 !important}
div[data-testid="stMetricValue"],div[data-testid="stMetricValue"] *{overflow:visible !important;height:auto !important;
  font-size:1.5rem !important;font-weight:700 !important;color:var(--ink-2) !important;white-space:normal !important;line-height:1.25 !important}

/* Tabs as an underlined nav row */
div[data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--line)}
button[data-baseweb="tab"]{padding:10px 14px;height:auto}
button[data-baseweb="tab"] p{font-size:12.5px !important;font-weight:700 !important;color:var(--muted)}
button[data-baseweb="tab"][aria-selected="true"] p{color:var(--primary) !important}
div[data-baseweb="tab-highlight"]{background:var(--primary) !important;height:2px !important}
div[data-baseweb="tab-border"]{background:transparent !important}

/* Bordered containers, dataframes and charts as soft cards */
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:14px;border-color:var(--line);box-shadow:0 2px 12px rgba(5,31,74,.04)}
div[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:10px;overflow:hidden}
div[data-testid="stPlotlyChart"]{background:#fff;border:1px solid var(--line);border-radius:14px;padding:6px 8px;
  box-shadow:0 2px 12px rgba(5,31,74,.04)}
div[data-testid="stExpander"]{border-radius:12px;border-color:var(--line)}
section[data-testid="stSidebar"]{background:var(--wash-2)}
section[data-testid="stSidebar"] h1{font-size:1.15rem;color:var(--ink)}
hr{border-color:var(--line)}
</style>
"""

_TEMPLATE_DONE = False


def inject_css() -> None:
    """Page CSS + a shared Plotly template (soft grid, transparent paper,
    consistent font/margins) so every chart matches the cards around it."""
    global _TEMPLATE_DONE
    st.markdown(CSS, unsafe_allow_html=True)
    if not _TEMPLATE_DONE:
        pio.templates["sg"] = go.layout.Template(layout=go.Layout(
            font=dict(family="Segoe UI, system-ui, sans-serif", size=12, color="#191919"),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            title=dict(font=dict(size=14, color="#051F4A"), x=0.01),
            margin=dict(l=48, r=20, t=52, b=44),
            xaxis=dict(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False),
            yaxis=dict(gridcolor="#EEF2F6", linecolor="#CBD5E1", zeroline=False),
            legend=dict(orientation="h", y=-0.2, title_text=""),
            colorway=["#178197", "#0A7CC1", "#A51890", "#051F4A", "#59A5D7"],
        ))
        pio.templates.default = "plotly_white+sg"
        _TEMPLATE_DONE = True


def banner(title: str, eyebrow: str = "", subtitle: str = "", pills: list | None = None) -> None:
    pills_html = "".join(f'<span class="sg-pill">{html.escape(p)}</span>' for p in (pills or []))
    st.markdown(
        '<div class="sg-banner">'
        + (f'<div class="sg-eyebrow">{html.escape(eyebrow)}</div>' if eyebrow else "")
        + f'<div class="sg-title">{html.escape(title)}</div>'
        + (f'<div class="sg-sub">{html.escape(subtitle)}</div>' if subtitle else "")
        + (f'<div class="sg-pills">{pills_html}</div>' if pills_html else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def findings(items: list) -> None:
    """3-up headline cards. items = [(headline, body_html, tone)], tone in
    {"", "alert", "warn"}. headline/body may contain trusted inline HTML."""
    cards = "".join(
        f'<div class="sg-finding {tone}"><div class="sg-finding-n">{i:02d}</div>'
        f'<div class="sg-finding-h">{head}</div><div class="sg-finding-b">{body}</div></div>'
        for i, (head, body, tone) in enumerate(items, start=1)
    )
    st.markdown(f'<div class="sg-findings">{cards}</div>', unsafe_allow_html=True)


def section(title: str, caption: str = "", eyebrow: str = "") -> None:
    st.markdown(
        '<div class="sg-sec">'
        + (f'<div class="eb">{html.escape(eyebrow)}</div>' if eyebrow else "")
        + f"<h2>{html.escape(title)}</h2>"
        + (f'<div class="cap">{caption}</div>' if caption else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def subheader(text: str, caption: str = "", eyebrow: str = "") -> None:
    """Drop-in for st.subheader with the section-header styling."""
    section(text, caption, eyebrow)


def insight(text_html: str, tone: str = "") -> None:
    st.markdown(f'<div class="sg-insight {tone}">{text_html}</div>', unsafe_allow_html=True)
