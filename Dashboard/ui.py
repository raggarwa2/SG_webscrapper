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
.block-container{padding-top:2.4rem;padding-bottom:1.5rem;max-width:1400px}
div[data-testid="stVerticalBlock"]{gap:.55rem}
div[data-testid="stCaptionContainer"] p,[data-testid="stCaption"]{font-size:.76rem;line-height:1.35}
h1,h2,h3{letter-spacing:-.01em}

/* ---- Banner ---- */
.sg-banner{position:relative;overflow:hidden;color:#fff;padding:22px 28px;border-radius:14px;margin-bottom:18px;
  background:radial-gradient(120% 180% at 8% -30%,#59A5D7 0,#178197 42%,#051F4A 100%)}
.sg-eyebrow{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#D6EEF3;font-weight:700}
.sg-title{font-weight:800;font-size:22px;letter-spacing:-.015em;margin-top:8px;line-height:1.2}
.sg-sub{font-size:12px;opacity:.85;margin-top:8px}
.sg-pills{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
.sg-pill{font-size:10.5px;font-weight:700;color:var(--ink);background:var(--sky);padding:4px 11px;border-radius:20px}

/* ---- Headline findings (3-up) ---- */
.sg-findings{display:grid;grid-template-columns:1fr;gap:16px;margin-bottom:18px}
@media(min-width:960px){.sg-findings{grid-template-columns:repeat(3,1fr)}}
.sg-finding{background:linear-gradient(135deg,var(--wash),#fff 62%);border:1px solid var(--line);
  border-top:4px solid var(--primary);border-radius:12px;padding:16px 20px;
  box-shadow:0 6px 16px -16px rgba(23,129,151,.35)}
.sg-finding.alert{border-top-color:var(--neg)}
.sg-finding.warn{border-top-color:var(--warn)}
.sg-finding-n{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--primary);margin-bottom:8px}
.sg-finding.alert .sg-finding-n{color:var(--neg)}.sg-finding.warn .sg-finding-n{color:var(--warn)}
.sg-finding-h{font-size:14px;font-weight:800;color:var(--ink);line-height:1.3;margin-bottom:6px}
.sg-finding-b{font-size:12px;line-height:1.4;color:var(--muted)}
.sg-finding-b b{color:var(--ink)}

/* ---- Section header + insight strip ---- */
.sg-sec{margin:10px 0 4px}
.sg-sec .eb{font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--primary)}
.sg-sec h2{font-size:16px;line-height:1.3;font-weight:800;color:var(--ink);margin:2px 0 0;padding:0}
.sg-sec .cap{font-size:11.5px;color:var(--muted);margin-top:1px}
.sg-insight{margin:4px 0 6px;padding:6px 12px;background:var(--wash);border-left:3px solid var(--primary);
  border-radius:0 8px 8px 0;font-size:12.5px;font-weight:600;color:var(--ink);line-height:1.4}
.sg-insight.warn{background:var(--warn-bg);border-left-color:var(--warn)}
.caveat-box{background:var(--warn-bg);border:1px solid #F1DFB0;border-left:4px solid var(--warn);
  padding:10px 16px;border-radius:8px;margin-bottom:.5rem;font-size:.84rem;color:#5B4514}

/* ---- Fact / Direction chip ---- */
.sg-chip{display:inline-block;font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  padding:1px 7px;border-radius:10px;margin-right:7px;vertical-align:1px}
.sg-chip.fact{background:#E3F4F0;color:#0F766E}
.sg-chip.dir{background:#FFF1D6;color:#8A5A0B}

/* ---- Stage 1 read-out: page header + evidence-strength tags ---- */
.ev-head{margin:2px 0 8px;padding:8px 14px;background:#fff;border:1px solid var(--line);border-left:4px solid var(--primary);border-radius:10px}
.ev-q{font-size:15px;font-weight:800;color:var(--ink);line-height:1.35}
.ev-meta{font-size:11.5px;color:var(--muted);margin:3px 0 8px}
.ev{display:inline-block;font-size:10.5px;font-weight:700;padding:3px 10px;border-radius:20px;margin:0 6px 4px 0}
.ev-fact{background:#E3F4F0;color:#0F766E}
.ev-dir{background:#FFF1D6;color:#8A5A0B}
.ev-int{background:#E9EEF4;color:#475569}
.ev-limits{background:#F4F6F9;border:1px solid var(--line);border-left:4px solid var(--faint);padding:10px 16px;
  border-radius:8px;margin:14px 0;font-size:.86rem;color:#334155}
.ev-limits b{color:var(--ink)}
.ev-limits ul{margin:6px 0 0 18px;padding:0}

/* ---- Native widgets, restyled ---- */
div[data-testid="stMetric"]{position:relative;overflow:hidden;background:#fff;border:1px solid var(--line);
  border-radius:12px;padding:8px 14px 8px 16px;box-shadow:0 2px 12px rgba(5,31,74,.05);min-height:84px;
  display:flex;flex-direction:column;justify-content:center}
div[data-testid="stMetric"]::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--primary)}
div[data-testid="stMetricLabel"],div[data-testid="stMetricLabel"] *{overflow:visible !important;height:auto !important;max-width:none !important}
div[data-testid="stMetricLabel"] p{font-size:.68rem !important;font-weight:700 !important;text-transform:uppercase !important;
  letter-spacing:.07em !important;color:var(--muted) !important;white-space:normal !important;line-height:1.3 !important}
div[data-testid="stMetricValue"],div[data-testid="stMetricValue"] *{overflow:visible !important;height:auto !important;
  font-size:1.3rem !important;font-weight:700 !important;color:var(--ink-2) !important;white-space:normal !important;line-height:1.25 !important}

/* Tabs as an underlined nav row */
div[data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--line)}
button[data-baseweb="tab"]{padding:6px 12px;height:auto}
button[data-baseweb="tab"] p{font-size:12.5px !important;font-weight:700 !important;color:var(--muted)}
button[data-baseweb="tab"][aria-selected="true"] p{color:var(--primary) !important}
div[data-baseweb="tab-highlight"]{background:var(--primary) !important;height:2px !important}
div[data-baseweb="tab-border"]{background:transparent !important}

/* Bordered containers, dataframes and charts as soft cards */
div[data-testid="stVerticalBlockBorderWrapper"]{border-radius:14px;border-color:var(--line);box-shadow:0 2px 12px rgba(5,31,74,.04)}
div[data-testid="stVerticalBlockBorderWrapper"] li{margin:0 !important;padding:0 !important;line-height:1.45 !important}
div[data-testid="stVerticalBlockBorderWrapper"] li p{margin:0 !important}
div[data-testid="stVerticalBlockBorderWrapper"] ul{margin:0 !important;padding-left:1.1rem}
div[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:10px;overflow:hidden}
div[data-testid="stPlotlyChart"]{background:#fff;border:1px solid var(--line);border-radius:12px;padding:2px 4px;
  box-shadow:0 2px 12px rgba(5,31,74,.04)}
div[data-testid="stExpander"]{border-radius:12px;border-color:var(--line)}
section[data-testid="stSidebar"]{background:var(--wash-2)}
section[data-testid="stSidebar"] h1{font-size:1.15rem;color:var(--ink)}
hr{border-color:var(--line)}
</style>
"""

_TEMPLATE_DONE = False
_TEXT = "#191919"  # colors.md text black


def _patch_plotly_chart() -> None:
    """Streamlit's chart theme overrides the template with pale grey tick labels; set them explicitly on every
    figure so axis, legend and colorbar labels stay readable. Explicit colours set by a caller are kept."""
    orig = st.plotly_chart

    def plotly_chart(fig, *args, **kwargs):
        try:
            fig.update_xaxes(tickfont=dict(color=_TEXT), title_font=dict(color=_TEXT), selector=dict(), overwrite=False)
            fig.update_yaxes(tickfont=dict(color=_TEXT), title_font=dict(color=_TEXT), overwrite=False)
            fig.update_layout(legend=dict(font=dict(color=_TEXT)), overwrite=False)
        except Exception:
            pass
        return orig(fig, *args, **kwargs)

    st.plotly_chart = plotly_chart


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
        _patch_plotly_chart()
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
    {"", "alert", "warn"}; an optional 4th item "fact"/"dir" adds a Fact/Direction chip.
    headline/body may contain trusted inline HTML."""
    cards = "".join(
        f'<div class="sg-finding {it[2]}"><div class="sg-finding-n">{chip(it[3]) if len(it) > 3 else ""}{i:02d}</div>'
        f'<div class="sg-finding-h">{it[0]}</div><div class="sg-finding-b">{it[1]}</div></div>'
        for i, it in enumerate(items, start=1)
    )
    st.markdown(f'<div class="sg-findings">{cards}</div>', unsafe_allow_html=True)


_KIND = {"fact": "Fact", "dir": "Direction"}


def chip(kind: str) -> str:
    """Small label saying whether a line states a fact (counted from data) or a direction (an action or an
    inference). Empty string for an unknown kind."""
    return f'<span class="sg-chip {kind}">{_KIND[kind]}</span>' if kind in _KIND else ""


def section(title: str, caption: str = "", eyebrow: str = "", kind: str = "") -> None:
    """Section header. `title` should be a full insight/action sentence; `kind` ("fact"/"dir") tags it."""
    st.markdown(
        '<div class="sg-sec">'
        + (f'<div class="eb">{html.escape(eyebrow)}</div>' if eyebrow else "")
        + f"<h2>{chip(kind)}{html.escape(title)}</h2>"
        + (f'<div class="cap">{caption}</div>' if caption else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def subheader(text: str, caption: str = "", eyebrow: str = "", kind: str = "") -> None:
    """Drop-in for st.subheader with the section-header styling."""
    section(text, caption, eyebrow, kind)


def insight(text_html: str, tone: str = "", kind: str = "") -> None:
    st.markdown(f'<div class="sg-insight {tone}">{chip(kind)}{text_html}</div>', unsafe_allow_html=True)


def takeaway(text_html: str, kind: str = "fact") -> None:
    """One-line chart lead: a sentence stating what the chart shows (fact) or what to do about it (dir)."""
    insight(text_html, "" if kind == "fact" else "warn", kind)


def plot(fig, say: str = "", kind: str = "fact", note: str = "", height: int = 300) -> None:
    """Render a Plotly figure under a one-line lead sentence (`say`, tagged fact/dir) with a short source note.
    The sentence replaces the in-chart title, so the chart gives its headroom back to the data."""
    if say:
        takeaway(say, kind)
        fig.update_layout(title_text=None)
    if fig.layout.height is None:
        fig.update_layout(height=height)
    fig.update_layout(margin=dict(l=10, r=10, t=10 if say else 40, b=10))
    st.plotly_chart(fig, width="stretch")
    if note:
        st.caption(note)
