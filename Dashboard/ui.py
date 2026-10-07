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
import re

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

import ebi
from sg_common import BRAND_COLORS

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

/* ---- Sample-size strip: sits directly under every chart ---- */
.sg-base{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin:.2rem 0 .45rem;padding:7px 12px;
  background:#F8FAFC;border:1px solid var(--line);border-radius:10px;font-size:11.5px;color:var(--muted)}
.sg-base.attached{margin-top:-.25rem}
.sg-base.thin{background:var(--warn-bg);border-color:#F1DFB0}
.sg-base-h{font-size:9.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-right:2px}
.sg-base-unit{font-size:11px;color:var(--muted);margin-right:2px}
.sg-n{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;background:#fff;
  border:1px solid var(--line);color:var(--text);font-weight:600;white-space:nowrap}
.sg-n i{width:8px;height:8px;border-radius:50%;display:inline-block;flex:none}
.sg-n b{color:var(--ink);font-weight:800;font-variant-numeric:tabular-nums}
.sg-n.thin{background:#FFF1D6;border-color:#E9C877;color:#7A4E07}
.sg-n.thin b{color:#7A4E07}
.sg-n em{font-style:normal;font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;
  background:var(--warn);color:#fff;border-radius:999px;padding:1px 8px}
.sg-n.none{background:#F1F5F9;border-style:dashed;color:var(--faint)}
.sg-n.none b{color:var(--faint);font-weight:700}
.sg-base-note{margin-left:auto;font-size:10.5px;color:var(--muted)}
.sg-base.thin .sg-base-note{color:#7A4E07}
.sg-key{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin:-6px 0 12px;font-size:11.5px;color:var(--muted)}
.sg-key .sg-n{font-size:11px;padding:1px 9px}

/* ---- Pyramid summary: answer first, then the arguments, then the action ---- */
.sg-ans{font-size:19px;font-weight:800;color:var(--ink);line-height:1.35;margin:4px 0 12px}
.sg-args{display:grid;gap:7px;margin:2px 0 10px}
.sg-arg{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;line-height:1.45;color:var(--text)}
.sg-arg .n{flex:none;width:22px;height:22px;border-radius:50%;background:var(--primary);color:#fff;font-weight:800;
  font-size:12px;display:flex;align-items:center;justify-content:center;margin-top:1px}

/* circular icon badge sitting on the top border of the summary card, centred */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.sg-badge-anchor){position:relative;margin-top:30px;overflow:visible}
div[data-testid="stElementContainer"]:has(.sg-badge-anchor){height:0;margin:0;padding:0;overflow:visible}
.sg-badge{position:absolute;left:50%;top:-40px;transform:translateX(-50%);width:46px;height:46px;border-radius:50%;
  background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:center;z-index:5;
  border:4px solid #fff;box-shadow:0 0 0 1px var(--line),0 4px 10px rgba(5,31,74,.18)}
.sg-badge .sg-ico{width:22px;height:22px;margin:0;vertical-align:0}
/* ---- Summary card: headline, finding tiles, implication bar ---- */
.sg-sum{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 22px 16px;
  box-shadow:0 2px 12px rgba(5,31,74,.05);margin:6px 0 16px}
.sg-sum .bl-eb{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--primary)}
.sg-sum .bl-eb .sg-ico{margin:0;width:14px;height:14px}
.sg-sum .bl{font-size:20px;font-weight:800;color:var(--ink);line-height:1.3;margin:6px 0 16px;max-width:1150px}
.sg-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px}
.sg-tile{--tone:#475569;background:var(--wash-2);border:1px solid var(--line);border-top:3px solid var(--tone);border-radius:10px;padding:10px 13px 11px}
.sg-tile.good{--tone:#168012}.sg-tile.bad{--tone:#C0392B}.sg-tile.watch{--tone:#B7791F}.sg-tile.flat{--tone:#475569}
.sg-tile .t-eb{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.sg-tile .t-eb .sg-ico{margin:0;width:14px;height:14px;color:var(--tone)}
.sg-tile .t-val{font-size:23px;font-weight:800;color:var(--tone);line-height:1.15;margin:5px 0 3px}
.sg-tile .t-txt{font-size:12.5px;color:var(--text);line-height:1.4}
.sg-impl{display:flex;gap:10px;align-items:flex-start;margin-top:14px;padding:10px 14px;background:var(--warn-bg);
  border-left:3px solid var(--warn);border-radius:0 8px 8px 0;font-size:13px;color:#4A3A12;line-height:1.45}
.sg-impl .sg-ico{flex:none;margin:2px 0 0;width:16px;height:16px;color:var(--warn)}
.sg-impl .lab{font-weight:800;color:var(--ink);margin-right:4px}
.sg-ico{width:15px;height:15px;vertical-align:-3px;margin-right:6px;fill:none;stroke:currentColor;stroke-width:2;
  stroke-linecap:round;stroke-linejoin:round}
.sg-arg .ic{flex:none;color:var(--primary);margin-top:2px;display:flex}
.sg-arg .ic .sg-ico{width:18px;height:18px;margin:0}

/* ---- Summary: compact executive layout (tone vars drive accent bar, icon tint and sub-line colour) ---- */
.tone-pos{--tone:#0F766E;--tone-bg:#E3F4F0}.tone-neg{--tone:#B42318;--tone-bg:#FDECEA}
.tone-warn{--tone:#B7791F;--tone-bg:#FFF1D6}.tone-info{--tone:#178197;--tone-bg:#E8F3F5}
.sx-head{margin:0 0 4px}
.sx-head .eb{font-size:10px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--primary)}
.sx-head h2{font-size:20px;line-height:1.25;font-weight:800;color:var(--ink);margin:2px 0 6px;padding:0}
.sx-meta{display:flex;flex-wrap:wrap;gap:6px}
.sx-pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;color:var(--muted);background:#fff;
  border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.sx-pill .sg-ico{width:13px;height:13px;margin:0;color:var(--primary)}
.sx-pill.warn{background:var(--warn-bg);border-color:#E9C877;color:#7A4E07}.sx-pill.warn .sg-ico{color:var(--warn)}
.sx-kw{container-type:inline-size;margin:2px 0 8px}
.sx-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@container (min-width:560px){.sx-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@container (min-width:1180px){.sx-kpis{grid-template-columns:repeat(6,minmax(0,1fr))}}
.sx-kpi{position:relative;overflow:hidden;display:flex;gap:10px;align-items:center;background:#fff;border:1px solid var(--line);
  border-radius:12px;padding:10px 10px 10px 14px;box-shadow:0 2px 12px rgba(5,31,74,.05)}
.sx-kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--tone)}
.sx-ico{flex:none;width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;
  background:var(--tone-bg);color:var(--tone)}
.sx-ico .sg-ico{width:18px;height:18px;margin:0}
.sx-kpi .tx{min-width:0}
.sx-kpi .l{font-size:10px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);line-height:1.2}
.sx-kpi .v{font-size:21px;font-weight:800;color:var(--ink);line-height:1.15;font-variant-numeric:tabular-nums}
.sx-kpi .v.sm{font-size:13.5px;line-height:1.25}
.sx-kpi .s{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--muted);margin-top:2px;line-height:1.25}
.sx-kpi .s.t{color:var(--tone);font-weight:700}
.sx-kpi .s .sg-ico{width:13px;height:13px;margin:0}
.sx-take{display:flex;gap:10px;align-items:flex-start;background:#fff;border:1px solid var(--line);border-radius:12px;
  padding:8px 12px;margin-bottom:8px;box-shadow:0 2px 12px rgba(5,31,74,.04)}
.sx-take .sx-ico{width:30px;height:30px}
.sx-take .h{font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--tone)}
.sx-take .b{font-size:12.5px;line-height:1.4;color:var(--text)}
.sx-key{display:flex;flex-wrap:wrap;align-items:center;gap:6px 6px;margin:2px 0 8px;font-size:11px;color:var(--muted)}
.sx-key .sx-tag:not(:first-child){margin-left:12px}
.sx-key .sep{flex-basis:100%;height:0}
.sx-tag{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:999px;
  background:var(--tone-bg);color:var(--tone);white-space:nowrap}
.sx-tag .sg-ico{width:12px;height:12px;margin:0}
.sx-card .top{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.sx-card .top .sx-ico{width:28px;height:28px;border-radius:8px}
.sx-card .top .sx-ico .sg-ico{width:15px;height:15px}
.sx-card .n{font-size:11px;font-weight:600;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.sx-card .top .sx-tag{margin-left:auto}
.sx-card .stat{font-size:24px;margin-top:2px;font-weight:800;line-height:1.1;color:var(--tone);font-variant-numeric:tabular-nums}
.sx-card .sl{font-size:11.5px;color:var(--muted);line-height:1.3;margin:0 0 6px}
.sx-card .hd{font-size:13px;font-weight:700;color:var(--ink);line-height:1.3}
.sx-card{display:flow-root;padding-bottom:0}
.sx-card .go{display:flex;align-items:center;gap:4px;font-size:10.5px;color:var(--muted);margin-top:3px}
.sx-card .hd{margin-bottom:2px}
.sx-thin .hd{min-height:0}
div[class*="st-key-sxc-"]>div:last-child{margin-top:auto}
button[data-testid="stPopoverButton"]{padding:2px 8px;min-height:0;font-size:12px;color:var(--primary)}
.sx-card .go .sg-ico{width:12px;height:12px;margin:0}

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
            # Neutral sequence for anything not coloured by brand, sentiment or channel, so a stray series never borrows a brand colour.
            colorway=["#6B7A90", "#C98B2B", "#B5838D", "#7A8450", "#9C6644", "#4F6D7A"],
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


_ICON_PATHS = {
    "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "checks": '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
    "compass": '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    "bars": '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "alert": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    "phone": '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    "megaphone": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
    "message": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
    "tag": '<path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/><path d="M7 7h.01"/>',
    "ban": '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "route": '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/><path d="M3.22 12H9.5l.5-1 2 4.5 2-7 1.5 3.5h5.27"/>',
    "trophy": '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-1.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98 1.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
    "trend-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "trend-down": '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
    "pie": '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    "cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "arrow": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "flask": '<path d="M10 2v7.31"/><path d="M14 9.3V1.99"/><path d="M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0"/><path d="M5.52 16h12.96"/>',
}
# argument / section label -> icon, so a numbered argument in the summary and its section below share one icon
_LABEL_ICON = {
    "Position": "bars", "Channels": "grid", "Complaints": "alert", "Owned experience": "phone",
    "Barrier": "ban", "Stage": "route", "Voice": "megaphone", "Reaction": "message", "Themes": "tag",
    "Evidence base": "database", "Research check": "flask", "Bottom line": "target", "Key findings": "checks", "Implication": "compass",
}


def icon(name: str) -> str:
    """Inline line icon (inherits the text colour); empty string for an unknown name."""
    paths = _ICON_PATHS.get(name)
    return f'<svg class="sg-ico" viewBox="0 0 24 24" aria-hidden="true">{paths}</svg>' if paths else ""


def _eyebrow(text: str) -> str:
    """Eyebrow text with its icon. "2 · Channels" and "Channels" both resolve to the Channels icon."""
    label = text.split("·", 1)[1].strip() if "·" in text else text
    return icon(_LABEL_ICON.get(label, "")) + html.escape(text)


def section(title: str, caption: str = "", eyebrow: str = "", kind: str = "") -> None:
    """Section header. `title` should be a full insight/action sentence; `kind` ("fact"/"dir") tags it."""
    st.markdown(
        '<div class="sg-sec">'
        + (f'<div class="eb">{_eyebrow(eyebrow)}</div>' if eyebrow else "")
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


def story(shows: str, matters: str, insight_text: str) -> None:
    """The three-line read at the top of a story page: what the data shows, why it matters, what insight it supports.
    Each argument is trusted inline HTML. The insight is a hypothesis to test, so it carries the Direction chip."""
    with st.container(border=True):
        for label, text, kind in (("What the data shows", shows, "fact"),
                                  ("Why it matters", matters, "fact"),
                                  ("What insight it supports", insight_text, "dir")):
            st.markdown(f'<div class="sg-sec"><div class="eb">{label}</div></div>', unsafe_allow_html=True)
            insight(text, "" if kind == "fact" else "warn", kind)


def pyramid(bottom_line: str, findings: list, implication: str = "") -> None:
    """Summary card at the top of a story page (Pyramid Principle): the bottom line in one sentence, the 2-4 findings that
    support it as tiles, and the implication as a slim bar. A finding is a dict {label, value, text, tone}: `label` names the
    section below ("Position" -> "1 · Position", the same words and icon as that section's eyebrow), `value` is the one number
    to read, `text` is one short claim, `tone` is good / bad / watch / flat and colours the tile. A plain string is accepted
    and shown as a tile with text only. All text is trusted inline HTML. The implication is a hypothesis to test."""
    tiles = ""
    for i, f in enumerate(findings, start=1):
        if isinstance(f, str):
            f = {"label": "", "value": "", "text": f, "tone": "flat"}
        ic = icon(_LABEL_ICON.get(f.get("label", ""), ""))
        label = f"{i} · {html.escape(f['label'])}" if f.get("label") else str(i)
        tiles += (f'<div class="sg-tile {f.get("tone", "flat")}"><div class="t-eb">{ic}{label}</div>'
                  + (f'<div class="t-val">{f["value"]}</div>' if f.get("value") else "")
                  + f'<div class="t-txt">{f["text"]}</div></div>')
    st.markdown(
        '<div class="sg-sum">'
        f'<div class="bl-eb">{icon("target")}Bottom line</div>'
        f'<div class="bl">{bottom_line}</div>'
        + (f'<div class="sg-tiles">{tiles}</div>' if tiles else "")
        + (f'<div class="sg-impl">{icon("arrow")}<span><span class="lab">Implication.</span>{implication}</span></div>' if implication else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def _chip(label: str, n, noun: str = "") -> str:
    """One sample-size pill: [dot] label  n  [DIRECTIONAL ONLY]. Amber under ebi.MIN_N, dashed grey when empty."""
    dot = BRAND_COLORS.get(label)
    dot_html = f'<i style="background:{dot}"></i>' if dot else ""
    name = f"{html.escape(str(label))} " if label else ""
    if n is None or n == 0:
        return f'<span class="sg-n none">{dot_html}{name}<b>No usable data</b></span>'
    unit = f" {html.escape(noun)}" if noun and not label else ""
    if ebi.is_thin(n):
        return f'<span class="sg-n thin">{dot_html}{name}<b>n={int(n):,}</b>{unit}<em>Directional</em></span>'
    return f'<span class="sg-n">{dot_html}{name}<b>n={int(n):,}</b>{unit}</span>'


def n_strip(items=None, noun: str = "items", note: str = "", attached: bool = False) -> None:
    """The sample-size strip that sits directly under a chart.

    `items` is one count, a {label: count} dict (brand labels get their colour dot), or a plain string for a
    chart that has no sample (official statistics, an index). A count under ebi.MIN_N turns amber and says
    "Directional only"; zero says "No usable data". `attached` pulls it up against a chart above it. Nothing is shown
    for None."""
    if items is None:
        return
    if isinstance(items, str):
        chips, thin = f'<span class="sg-n none"><b>{html.escape(items)}</b></span>', False
    else:
        pairs = list(items.items()) if isinstance(items, dict) else [("", items)]
        chips = "".join(_chip(k, v, noun) for k, v in pairs)
        if isinstance(items, dict) and noun:
            chips = f'<span class="sg-base-unit">{html.escape(noun)}:</span>' + chips
        counts = [v for _, v in pairs if v]
        thin = any(ebi.is_thin(v) for v in counts)
    msg = note or (f"Under {ebi.MIN_N} is directional only: a pointer, not a rate." if thin else "")
    st.markdown(
        f'<div class="sg-base{" thin" if thin else ""}{" attached" if attached else ""}"><span class="sg-base-h">Sample size</span>{chips}'
        + (f'<span class="sg-base-note">{html.escape(msg)}</span>' if msg else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def sample_key() -> None:
    """One-line legend explaining the sample-size strips, shown once near the top of the dashboard."""
    st.markdown(
        '<div class="sg-key"><span>Every chart states how many items it is built from:</span>'
        f'<span class="sg-n"><b>n=120</b></span><span>enough to read as a rate</span>'
        f'<span class="sg-n thin"><b>n=12</b><em>Directional only</em></span>'
        f'<span>under {ebi.MIN_N} items: a pointer, not a measurement</span></div>',
        unsafe_allow_html=True,
    )


def plot(fig, say: str = "", kind: str = "fact", note: str = "", height: int = 300, key: str | None = None,
         bases: dict | int | str | None = None, noun: str = "items") -> None:
    """Render a Plotly figure under a one-line lead sentence (`say`, tagged fact/dir), then its sample-size strip
    (`bases`: a count, a {label: count} dict, or text for a chart with no sample) and a short source note.
    The sentence replaces the in-chart title, so the chart gives its headroom back to the data."""
    if say:
        takeaway(say, kind)
        fig.update_layout(title_text=None)
    if fig.layout.height is None:
        fig.update_layout(height=height)
    fig.update_layout(margin=dict(l=10, r=10, t=10 if say else 40, b=10))
    st.plotly_chart(fig, width="stretch", key=key)   # key: needed when two charts on a page could look identical
    n_strip(bases, noun, attached=True)
    if note:
        st.caption(note)
