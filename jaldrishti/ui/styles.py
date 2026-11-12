CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600;700&family=Inter:wght@400;600;700&family=Jost:wght@300;400;500&family=Cormorant+Garamond:wght@500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton, .stSelectbox, .stRadio, .stTabs, .stDataFrame {
  font-family: 'Inter', 'Noto Sans Devanagari', 'Nirmala UI', 'Mangal', 'Segoe UI', Arial, sans-serif;
}
/* Streamlit's fixed top bar is ~3.75rem tall; without this space the logo is hidden underneath it */
div.block-container { padding-top: 4.6rem !important; max-width: 1200px; }
:root { --navy:#0b2545; --teal:#0f766e; --teal-soft:#e3f3f0; --line:#d7e0e8; --ink:#16212e; --muted:#51606f; }

/* ---- brand ---- */
.jd-brand { background:#010b2e; color:#fff; border-radius:14px; padding:12px 18px; display:flex; align-items:center; gap:16px; overflow:visible; }
.jd-mark { height:68px; width:auto; flex-shrink:0; }
.jd-wordmark { display:flex; align-items:baseline; gap:.2em; line-height:1.5; white-space:nowrap; }
.jd-latin { font-family:'Jost','Inter',system-ui,sans-serif; font-weight:400; font-size:2rem; letter-spacing:.14em; color:#fff; }
.jd-deva { font-family:'Noto Sans Devanagari','Nirmala UI','Mangal',sans-serif; font-weight:400; font-size:2rem; line-height:1.6; color:#fff; }
.jd-tagline { font-family:'Cormorant Garamond',Georgia,'Times New Roman',serif; font-weight:500; font-size:.8rem; letter-spacing:.38em; color:#c9d6e6; margin-top:2px; }
.jd-tag2 { font-size:.78rem; color:#9bb0c8; margin-top:5px; }
.jd-logo-card { background:#010b2e; border-radius:14px; padding:18px; text-align:center; margin:8px 0 14px; }
.jd-logo-card img { max-width:min(360px,100%); height:auto; }

.jd-demo { background:#fff4e0; border:2px solid #e0a030; color:#5c3500; border-radius:10px; padding:10px 14px; margin:10px 0; font-weight:600; }
.jd-card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; box-shadow:0 1px 2px rgba(11,37,69,.06); color:var(--ink); }
.jd-status { border-left-width:8px; display:flex; gap:14px; align-items:flex-start; margin:8px 0 14px; padding:16px 18px; }
.jd-status .jd-icon { font-size:1.9rem; line-height:1; }
.jd-status .jd-label { font-size:1.35rem; font-weight:700; line-height:1.25; }
.jd-status .jd-reason { margin-top:6px; font-size:1.0rem; }
.jd-status .jd-meta { margin-top:6px; font-size:.88rem; color:var(--muted); }
.jd-s-normal { border-left:8px solid #0f766e; background:#eefaf7; }
.jd-s-investigate { border-left:8px solid #c2670a; background:#fff6e8; }
.jd-s-verified { border-left:8px solid #0b2545; background:#eaf0f9; }
.jd-s-unavailable { border-left:8px solid #5b6674; background:#f1f3f5; }
.jd-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:6px 0 14px; }
.jd-grid-big { grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); }
.jd-sensor .jd-sname { font-size:.9rem; font-weight:600; color:var(--muted); }
.jd-sensor .jd-val { font-size:2.0rem; font-weight:700; color:var(--navy); line-height:1.15; font-variant-numeric:tabular-nums; }
.jd-grid-big .jd-val { font-size:2.5rem; }
.jd-sensor .jd-unit { font-size:.95rem; font-weight:600; color:var(--muted); margin-left:6px; }
.jd-sensor .jd-sub { font-size:.9rem; margin-top:4px; font-weight:600; }
.jd-sensor .jd-exp { font-size:.85rem; color:var(--muted); margin-top:6px; }
.jd-warn { color:#8a4b00; }
.jd-ok { color:#0f766e; }
.jd-note { font-size:.85rem; color:var(--muted); }
.jd-whi-score { font-size:3rem; font-weight:700; color:var(--navy); line-height:1; }
.jd-badge { display:inline-block; border:1px solid var(--navy); color:var(--navy); border-radius:999px; padding:2px 12px; font-weight:700; margin-left:8px; }
.jd-prov { background:#fff4e0; border:1px solid #e0a030; color:#5c3500; border-radius:8px; padding:8px 12px; font-size:.88rem; margin-top:8px; }
.jd-footer { color:var(--muted); font-size:.8rem; margin-top:28px; border-top:1px solid var(--line); padding-top:10px; }
button:focus-visible, [role="tab"]:focus-visible { outline:3px solid #0f766e !important; outline-offset:2px; }

/* ---- touch-friendly controls (phones and tablets) ---- */
.stButton button, .stDownloadButton button, .stFormSubmitButton button { min-height:44px; }
div[role="radiogroup"] { flex-wrap:wrap; row-gap:.35rem; column-gap:1rem; }
div[role="radiogroup"] label { min-height:40px; align-items:center; }
div[data-baseweb="select"] > div { min-height:44px; }
[data-testid="stDataFrame"] { max-width:100%; }

/* ---- phones ---- */
@media (max-width: 640px) {
  div.block-container { padding-top: 4.2rem !important; padding-left: .9rem !important; padding-right: .9rem !important; }
  .jd-brand { padding:10px 12px; gap:12px; }
  .jd-mark { height:50px; }
  .jd-latin, .jd-deva { font-size:1.5rem; }
  .jd-tagline { font-size:.62rem; letter-spacing:.3em; }
  .jd-tag2 { display:none; }
  .jd-grid, .jd-grid-big { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
  .jd-sensor .jd-val { font-size:1.55rem; }
  .jd-grid-big .jd-val { font-size:1.75rem; }
  .jd-sensor .jd-sname { font-size:.8rem; }
  .jd-sensor .jd-exp { font-size:.76rem; }
  .jd-card { padding:12px; }
  .jd-status { padding:12px 14px; gap:10px; }
  .jd-status .jd-label { font-size:1.12rem; }
  .jd-status .jd-icon { font-size:1.5rem; }
  .jd-whi-score { font-size:2.4rem; }
  button[role="tab"] { padding:.45rem .65rem; }
  button[role="tab"] p { font-size:.9rem; }
}
@media (max-width: 380px) {
  .jd-grid, .jd-grid-big { grid-template-columns:minmax(0,1fr); }
}
</style>
"""
