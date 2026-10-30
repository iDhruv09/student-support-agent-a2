"""
theme.py - Visual identity and UI components for the Student Support Agent.

Look and feel
  - Palette from the Adani brochure: brand purple, deep plum, soft lavender, sky blue.
  - White chat canvas + purple session panel (the brochure's white page | purple page spread).
  - Headings in Outfit, body in Inter (Google Fonts, with system fallbacks).
  - Fixed layout: the brand bar stays at the top while the chat scrolls,
    and the session panel fits the screen without its own scrollbar.
  - One motion moment: a "working" indicator, then the answer types itself in.

Everything here is presentation only. No agent, tool or security logic lives in this file.
"""
import base64
import html
import re
import time
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).parent / "assets"
LOGO_FILE = ASSETS / "aidtm_logo.png"
FAVICON_FILE = ASSETS / "favicon.png"

# ---------------------------------------------------------------- design tokens
PURPLE = "#8E278F"      # brand purple (sampled from the brochure)
PLUM = "#68246C"        # deep purple: hover and pressed states
LAVENDER = "#F6EFF7"    # soft surface
LAVENDER_LINE = "#E5CDE5"
INK = "#25232B"
MUTED = "#6B6873"
LINE = "#E7E4EA"
SKY = "#A5D3F2"         # sky blue from the brochure: evidence accents
GREEN = "#1F7A4D"
AMBER = "#9A5B00"
RED = "#B3261E"

MAX_MEMORY_CHIPS = 3    # keeps the session panel short enough to never scroll

# ---------------------------------------------------------------- labels
DECISIONS = {
    "answered_directly": ("Answered directly", "neutral"),
    "answered_from_memory": ("Answered from memory", "sky"),
    "retrieved_policy": ("Retrieved policy", "sky"),
    "used_tools": ("Used tools", "purple"),
    "empty_input": ("No question", "neutral"),
}
TOOL_STATUS = {
    "ok": "ok", "missing_data": "warn", "no_match": "warn",
    "not_saved": "warn", "error": "bad", None: "neutral",
}


def esc(value):
    return html.escape(str(value if value is not None else ""))


# ---------------------------------------------------------------- assets
def favicon():
    return str(FAVICON_FILE) if FAVICON_FILE.exists() else "🎓"


def _logo_data_uri():
    if not LOGO_FILE.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_FILE.read_bytes()).decode()


# ---------------------------------------------------------------- CSS
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@500;600&display=swap');

:root {{
  --purple: {PURPLE}; --plum: {PLUM}; --lavender: {LAVENDER}; --lav-line: {LAVENDER_LINE};
  --ink: {INK}; --muted: {MUTED}; --line: {LINE}; --sky: {SKY};
  --green: {GREEN}; --amber: {AMBER}; --red: {RED};
  --head: 'Outfit', 'Segoe UI', system-ui, sans-serif;
  --body: 'Inter', 'Segoe UI', system-ui, sans-serif;
  --col: 940px;
}}

html, body, .stApp, [data-testid="stAppViewContainer"] {{ font-family: var(--body); color: var(--ink); }}
[data-testid="stHeader"] {{ background: transparent; pointer-events: none; }}
[data-testid="stHeader"] button, [data-testid="stExpandSidebarButton"] {{ pointer-events: auto; }}
[data-testid="stExpandSidebarButton"] {{ color: var(--purple); }}
[data-testid="stMainMenu"], [data-testid="stToolbarActions"], [data-testid="stAppDeployButton"] {{ display: none; }}
footer, [data-testid="stDecoration"] {{ display: none; }}

/* ---------- main column ---------- */
[data-testid="stMainBlockContainer"] {{
  max-width: var(--col); margin-left: auto; margin-right: auto;
  padding-top: 0; padding-bottom: 2rem;
}}

/* ---------- frozen brand bar ---------- */
[data-testid="stElementContainer"]:has(.brand-bar) {{
  position: sticky; top: 0; z-index: 50; background: #fff;
}}
.brand-bar {{
  display: flex; align-items: center; gap: 1rem;
  padding: 1rem 0 0.85rem; border-bottom: 1px solid var(--line); background: #fff;
}}
.brand-logo {{ height: 38px; width: auto; display: block; }}
.brand-app {{
  margin-left: auto; text-align: right; line-height: 1.25;
}}
.brand-app b {{ display: block; font: 600 1rem var(--head); color: var(--purple); }}
.brand-app span {{ font: 400 0.75rem var(--body); color: var(--muted); }}

.app-head {{ padding: 1.2rem 0 0.2rem; }}
.app-head h1.app-title {{
  font: 600 2.1rem/1.15 var(--head); color: var(--purple);
  letter-spacing: -0.01em; margin: 0; padding: 0;
}}
.app-head p.app-sub {{ font: 400 1rem/1.55 var(--body); color: var(--muted); margin: 0.45rem 0 0; max-width: 62ch; }}

/* ---------- empty state ---------- */
.empty-head {{ font: 600 1.15rem var(--head); color: var(--ink); margin: 1rem 0 0.2rem; }}
.empty-sub {{ font: 400 0.95rem var(--body); color: var(--muted); margin: 0 0 0.9rem; }}

/* ---------- login card (A2) ---------- */
[data-testid="stForm"] {{ border: 1px solid var(--lav-line); border-radius: 12px; background: #fff; padding: 1.1rem 1.2rem; }}
[data-testid="stForm"] label p {{ font: 500 0.85rem var(--body); color: var(--ink); }}
[data-testid="stForm"] [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: var(--purple); border-color: var(--purple); color: #fff; font: 600 0.92rem var(--body); border-radius: 8px;
}}
[data-testid="stForm"] [data-testid="stBaseButton-primaryFormSubmit"]:hover {{ background: var(--plum); border-color: var(--plum); }}
.demo-logins {{ font: 400 0.8rem/1.5 var(--body); color: var(--muted); margin-top: 0.6rem; text-align: center; }}
.demo-logins code {{ font: 500 0.78rem ui-monospace, Consolas, monospace; background: var(--lavender); color: var(--plum); padding: 0.05rem 0.3rem; border-radius: 4px; }}

/* ---------- demo question buttons ---------- */
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] {{
  font: 500 0.92rem/1.4 var(--body); color: var(--ink); background: #fff;
  border: 1px solid var(--lav-line); border-radius: 10px; padding: 0.5rem 0.9rem;
  height: 4.2rem; width: 100%; justify-content: flex-start; text-align: left;
  transition: border-color .15s, background-color .15s;
}}
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] > div,
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] > div > span,
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] [data-testid="stMarkdownContainer"] {{
  width: 100%; justify-content: flex-start; text-align: left;
}}
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"]:hover {{
  border-color: var(--purple); background: var(--lavender); color: var(--plum);
}}
[data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] p {{ text-align: left; margin: 0; }}

/* ---------- chat messages ---------- */
[data-testid="stChatMessage"] {{ background: transparent; padding: 0.35rem 0; gap: 0.8rem; }}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {{
  background: var(--lavender); border: 1px solid var(--lav-line); border-radius: 12px;
  padding: 0.75rem 1rem; width: fit-content; max-width: 88%; margin-left: auto;
}}
[data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) {{
  border-left: 3px solid var(--purple); padding-left: 1rem; border-radius: 0; margin-top: 0.4rem;
}}
[data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"]) [data-testid="stChatMessageAvatarCustom"] {{ background: var(--purple); }}
[data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) [data-testid="stChatMessageAvatarCustom"] {{ background: var(--plum); }}
[data-testid="stChatMessageAvatarCustom"] {{ border: 0; }}
[data-testid="stChatMessageAvatarCustom"] span,
[data-testid="stChatMessageAvatarCustom"] [data-testid="stIconMaterial"] {{ color: #fff !important; }}
[data-testid="stChatMessageContent"] p, [data-testid="stChatMessageContent"] li {{ font: 400 0.94rem/1.6 var(--body); }}

/* ---------- "working" indicator ---------- */
.working {{ display: flex; align-items: center; gap: 0.7rem; padding: 0.35rem 0; color: var(--muted); font: 400 0.92rem var(--body); }}
.dots {{ display: inline-flex; gap: 5px; }}
.dots i {{ width: 7px; height: 7px; border-radius: 50%; background: var(--purple); opacity: .25;
          animation: pulse 1.1s ease-in-out infinite; }}
.dots i:nth-child(2) {{ animation-delay: .18s; }}
.dots i:nth-child(3) {{ animation-delay: .36s; }}
@keyframes pulse {{ 0%, 100% {{ opacity: .25; transform: translateY(0); }} 40% {{ opacity: 1; transform: translateY(-3px); }} }}

.caret {{ display: inline-block; width: 2px; height: 1.05em; margin-left: 2px; vertical-align: -0.15em;
          background: var(--purple); animation: blink .9s steps(1) infinite; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}

/* no grey-out of the screen while the agent works: the indicator already shows progress */
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}

/* ---------- chat input ---------- */
[data-testid="stBottomBlockContainer"] {{ max-width: var(--col); margin: 0 auto; }}
[data-testid="stChatInput"], [data-testid="stChatInput"] > div, [data-testid="stChatInput"] textarea {{ background: #fff; }}
[data-testid="stChatInput"] {{ border: 1px solid var(--lav-line); border-radius: 12px; }}
[data-testid="stChatInput"]:focus-within {{ border-color: var(--purple); box-shadow: none; }}
[data-testid="stChatInput"] textarea {{ font: 400 0.95rem var(--body); }}
[data-testid="stChatInput"] textarea:focus, [data-testid="stChatInput"] textarea:focus-visible {{ outline: none !important; box-shadow: none !important; }}

/* ---------- expander (trace, demo questions) ---------- */
[data-testid="stExpander"] details {{ border: 1px solid var(--line); border-radius: 10px; background: #fff; }}
[data-testid="stExpander"] summary {{ font: 500 0.86rem var(--head); color: var(--plum); padding-top: 0.45rem; padding-bottom: 0.45rem; }}
[data-testid="stExpanderDetails"] {{ padding: 0.2rem 0.75rem 0.75rem; }}
[data-testid="stExpander"] summary:hover {{ color: var(--purple); }}

/* ---------- session panel (the purple page): fits the screen, never scrolls ---------- */
[data-testid="stSidebar"] {{ background: var(--purple); }}
section[data-testid="stSidebar"][aria-expanded="true"] {{ width: 15.5rem !important; min-width: 15.5rem !important; max-width: 15.5rem !important; }}
[data-testid="stSidebarUserContent"] {{ padding-left: 1rem; padding-right: 1rem; }}
[data-testid="stSidebar"] * {{ color: #fff; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{ margin-bottom: 0; }}
[data-testid="stSidebarContent"] {{ scrollbar-width: none; }}
[data-testid="stSidebarContent"]::-webkit-scrollbar {{ display: none; }}
[data-testid="stSidebarHeader"] {{ height: 1.6rem; min-height: 1.6rem; padding-top: 0.3rem; padding-bottom: 0; margin: 0; }}
[data-testid="stSidebarUserContent"] {{ padding-top: 0; padding-bottom: 0.6rem; }}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {{ gap: 0.45rem; }}
.side-title {{ font: 600 0.96rem var(--head); margin: 0; padding: 0; }}
.side-title.ruled {{ border-top: 1px solid rgba(255,255,255,.25); padding-top: 0.75rem; margin-top: 0.35rem; }}
.side-rule {{ border: 0; border-top: 1px solid rgba(255,255,255,.25); margin: 0.2rem 0 0; }}
[data-testid="stSidebar"] label p {{ font: 500 0.82rem var(--body); color: rgba(255,255,255,.9); }}
[data-testid="stSidebar"] [data-baseweb="select"] > div {{ background: #fff; border-radius: 8px; border: 0; min-height: 2.4rem; }}
[data-testid="stSidebar"] [data-baseweb="select"] * {{ color: var(--ink); }}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{
  background: transparent; color: #fff; border: 1px solid rgba(255,255,255,.65);
  border-radius: 8px; font: 500 0.86rem var(--body); min-height: 2.25rem; padding: 0.25rem 0.75rem;
  transition: background-color .15s;
}}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {{ background: rgba(255,255,255,.14); border-color: #fff; color: #fff; }}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p {{ color: #fff; }}
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] svg {{ stroke: rgba(255,255,255,.8); }}

/* signed-in card (A2) */
.who {{ display: flex; align-items: center; gap: 0.6rem; }}
.who .av {{ width: 2.1rem; height: 2.1rem; border-radius: 50%; background: #fff; color: var(--purple) !important;
           display: flex; align-items: center; justify-content: center; font: 600 0.85rem var(--head); flex: none; }}
.who b {{ display: block; font: 600 0.95rem/1.2 var(--head); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.who span {{ display: block; font: 400 0.75rem var(--body); color: rgba(255,255,255,.8); }}

.mem {{ background: rgba(255,255,255,.14); border-radius: 8px; padding: 0.35rem 0.65rem; margin: 0 0 0.25rem;
        font: 400 0.84rem/1.35 var(--body); display: flex; justify-content: space-between; gap: 0.5rem; }}
.mem span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }}
.mem small {{ color: rgba(255,255,255,.72); font-size: 0.72rem; white-space: nowrap; }}
.mem-empty {{ font: 400 0.8rem/1.45 var(--body); color: rgba(255,255,255,.8); margin: 0; }}
.mem-more {{ font: 400 0.76rem var(--body); color: rgba(255,255,255,.75); margin: 0; }}

/* ---------- compact KPI tiles (trace + session panel) ---------- */
.kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.4rem; margin: 0 0 0.6rem; }}
.kpi {{ background: var(--lavender); border: 1px solid var(--lav-line); border-radius: 8px; padding: 0.35rem 0.55rem; min-width: 0; }}
.kpi b {{ display: block; font: 600 0.98rem/1.2 var(--head); color: var(--plum); font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.kpi span {{ display: block; font: 400 0.68rem/1.2 var(--body); color: var(--muted); white-space: nowrap; }}
.kpi.accent {{ border-left: 3px solid var(--purple); }}
.side-kpis {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.35rem; }}
.side-kpis .kpi {{ background: rgba(255,255,255,.13); border-color: rgba(255,255,255,.18); padding: 0.3rem 0.5rem; }}
.side-kpis .kpi b {{ color: #fff; font-size: 0.95rem; }}
.side-kpis .kpi span {{ color: rgba(255,255,255,.78); }}

/* ---------- trace card (compact) ---------- */
.trace {{ font: 400 0.84rem/1.45 var(--body); color: var(--ink); }}
.trace .row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; margin-bottom: 0.55rem; }}
.pill {{ display: inline-block; font: 500 0.74rem/1 var(--head); padding: 0.3rem 0.6rem; border-radius: 999px;
         border: 1px solid var(--line); color: var(--ink); background: #fff; white-space: nowrap; }}
.pill.purple {{ background: var(--purple); border-color: var(--purple); color: #fff; }}
.pill.sky {{ background: #E6F3FC; border-color: var(--sky); color: #0B4A75; }}
.pill.ok {{ background: #E8F5EE; border-color: #A9D8BF; color: var(--green); }}
.pill.warn {{ background: #FFF3DF; border-color: #EBC98A; color: var(--amber); }}
.pill.bad {{ background: #FCE9E7; border-color: #EBB1AC; color: var(--red); }}
.pill.neutral {{ background: var(--lavender); border-color: var(--lav-line); color: var(--plum); }}
.pill.mono {{ font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; }}

.trace table {{ width: 100%; border-collapse: collapse; margin: 0; }}
.trace table, .trace tr, .trace td, .trace th {{ border: 0; background: none; }}
.trace td, .trace th {{ padding: 0.32rem 0.45rem; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; font-size: 0.82rem; }}
.trace tr:last-child td {{ border-bottom: 0; }}
.trace td.k {{ width: 8rem; color: var(--plum); font: 600 0.8rem var(--head); white-space: nowrap; }}
.trace th {{ font: 600 0.74rem var(--head); color: var(--muted); text-transform: uppercase; letter-spacing: .03em; background: var(--lavender); }}
.trace td.num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--muted); }}
.trace code {{ font: 500 0.78rem ui-monospace, Consolas, monospace; color: var(--ink); background: var(--lavender); padding: 0.05rem 0.3rem; border-radius: 4px; }}
.trace .none {{ color: var(--muted); }}
.trace .sub {{ color: var(--muted); font-size: 0.76rem; }}
.trace .wrap {{ word-break: break-word; }}

.trace details.more {{ margin-top: 0.55rem; border: 1px solid var(--line); border-radius: 8px; }}
.trace details.more summary {{ cursor: pointer; padding: 0.4rem 0.6rem; font: 500 0.8rem var(--head); color: var(--plum); list-style: none; }}
.trace details.more summary::-webkit-details-marker {{ display: none; }}
.trace details.more summary::before {{ content: "+ "; }}
.trace details.more[open] summary::before {{ content: "– "; }}
.trace details.more .scroll {{ overflow-x: auto; }}

/* ---------- accessibility ---------- */
:focus-visible {{ outline: 2px solid var(--purple); outline-offset: 2px; }}
[data-testid="stSidebar"] :focus-visible {{ outline-color: #fff; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}

/* ---------- phones ---------- */
@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"], [data-testid="stBottomBlockContainer"] {{ padding-left: 1rem; padding-right: 1rem; }}
  .brand-bar {{ padding-left: 2.2rem; }}
  .brand-logo {{ height: 28px; }} .brand-app {{ display: none; }}
  .app-head h1.app-title {{ font-size: 1.55rem; }}
  .app-head p.app-sub {{ font-size: 0.9rem; }}
  [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-secondary"] {{ height: auto; min-height: 3rem; }}
  [data-testid="stChatMessage"]:has([aria-label="Chat message from user"]) {{ max-width: 100%; }}
  .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .trace td.k {{ width: 6.5rem; white-space: normal; }}
}}
</style>
"""


def apply():
    """Inject the stylesheet. Call once, right after st.set_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------- main components
def header(model_name=""):
    """Frozen brand bar (stays on top while chatting)."""
    logo = _logo_data_uri()
    img = (f'<img class="brand-logo" src="{logo}" '
           f'alt="Adani Institute of Digital Technology Management">') if logo else ""
    model = f"<span>Model: {esc(model_name)}</span>" if model_name else ""
    st.markdown(f'<div class="brand-bar">{img}<div class="brand-app"><b>Student Support Agent</b>{model}</div></div>',
                unsafe_allow_html=True)


def page_title(title, subtitle=""):
    """Large page title + one-line description (scrolls away; the brand bar stays)."""
    sub = f'<p class="app-sub">{esc(subtitle)}</p>' if subtitle else ""
    st.markdown(f'<div class="app-head"><h1 class="app-title">{esc(title)}</h1>{sub}</div>',
                unsafe_allow_html=True)


def intro():
    page_title("Student Support Agent",
               "Ask about your fees, scholarships, course changes or institute policies. "
               "I can also raise a support request for you.")


def empty_state():
    st.markdown('<div class="empty-head">How can I help today?</div>'
                '<div class="empty-sub">Pick a question to see how the agent works, or type your own below.</div>',
                unsafe_allow_html=True)


def demo_logins(pairs):
    """Small line under the login form listing demo accounts: [(id, password), ...]."""
    items = " · ".join(f"<code>{esc(u)}</code> / <code>{esc(p)}</code>" for u, p in pairs)
    st.markdown(f'<div class="demo-logins">Demo accounts: {items}</div>', unsafe_allow_html=True)


def working_html(text="Checking your records and the handbook"):
    return f'<div class="working"><span class="dots"><i></i><i></i><i></i></span>{esc(text)}</div>'


_TOKEN_RE = re.compile(r"\*\*[^*\n]+\*\*\S*\s*|`[^`\n]+`\S*\s*|\S+\s*|\s+")
_CURSOR = '<span class="caret"></span>'


def type_out(placeholder, text, target_s=1.4):
    """
    Show the answer a few words at a time in `placeholder` (an st.empty()), like live typing.
    Bold and code spans are kept whole so half-written markdown never flashes on screen.
    The whole answer takes about target_s seconds, whatever its length.
    """
    text = text or ""
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        placeholder.markdown(text)
        return
    delay = min(0.04, max(0.008, target_s / len(tokens)))
    step = max(1, len(tokens) // 120)            # long answers: several words per frame
    shown = ""
    for i, tok in enumerate(tokens, 1):
        shown += tok
        if i % step == 0 or i == len(tokens):
            placeholder.markdown(shown + _CURSOR if i < len(tokens) else shown, unsafe_allow_html=True)
            time.sleep(delay * step)


# ---------------------------------------------------------------- session panel components
def side_title(text, ruled=False):
    """Section title in the session panel. ruled=True draws the divider above it."""
    st.markdown(f'<div class="side-title{" ruled" if ruled else ""}">{esc(text)}</div>', unsafe_allow_html=True)


def side_rule():
    st.markdown('<hr class="side-rule">', unsafe_allow_html=True)


def signed_in(name, user_id, role):
    """Signed-in card at the top of the session panel: initials, name, ID and role."""
    initials = "".join(w[0] for w in str(name).split()[:2]).upper() or "?"
    st.markdown(f'<div class="who"><div class="av">{esc(initials)}</div>'
                f'<div><b>{esc(name)}</b><span>{esc(user_id)} · {esc(str(role).capitalize())}</span></div></div>',
                unsafe_allow_html=True)


def memory_chips(items):
    if not items:
        st.markdown('<div class="mem-empty">Nothing saved yet. Tell me your programme or how you like answers.</div>',
                    unsafe_allow_html=True)
        return
    shown = items[-MAX_MEMORY_CHIPS:]
    chips = "".join(
        f'<div class="mem" title="{esc(i.get("fact"))}"><span>{esc(i.get("fact"))}</span>'
        f'<small>{esc(str(i.get("category", "other")).capitalize())}</small></div>' for i in shown)
    more = len(items) - len(shown)
    if more:
        chips += f'<div class="mem-more">+{more} older fact{"s" if more != 1 else ""}</div>'
    st.markdown(chips, unsafe_allow_html=True)


def _compact(n):
    """12345 -> 12.3k so numbers stay short."""
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


def _kpis(cells, cls="kpis"):
    """Row of small number tiles. The first tile gets a purple accent."""
    body = "".join(f'<div class="kpi{" accent" if i == 0 else ""}"><b>{esc(v)}</b><span>{esc(k)}</span></div>'
                   for i, (k, v) in enumerate(cells))
    return f'<div class="{cls}">{body}</div>'


def stats_grid(stats):
    """2 x 2 compact tiles: questions, average time, tokens in, tokens out."""
    avg = f'{stats["avg_latency"]:.1f}s' if stats["questions"] else "-"
    st.markdown(_kpis([("Asked", stats["questions"]), ("Avg time", avg),
                       ("Tokens in", _compact(stats["in_tokens"])),
                       ("Tokens out", _compact(stats["out_tokens"]))], "side-kpis"),
                unsafe_allow_html=True)


# ---------------------------------------------------------------- trace card
def _pill(text, kind="neutral", mono=False):
    return f'<span class="pill {kind}{" mono" if mono else ""}">{esc(text)}</span>'


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _short_value(value, limit=60):
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(v) for v in value) or "-"
    elif isinstance(value, dict):
        text = ", ".join(f"{k}={v}" for k, v in value.items()) or "-"
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def _result_summary(result):
    """Main fields of a tool result, without long text."""
    if not isinstance(result, dict):
        return _short_value(result)
    keep = {k: v for k, v in result.items()
            if k not in ("status", "auth", "text", "message", "suggestion", "created_at", "expected_response")}
    if "message" in result and len(keep) <= 2:
        keep["message"] = result["message"]
    if "error" in result:
        keep = {"error": result["error"]}
    return _short_value(keep, 110)


def trace_html(trace, history_sent=0):
    """
    Compact view of one agent run, one row per assignment measure:
    decision, latency, tokens, tools, policy evidence, memory, context. Tool details as a table.
    """
    label, kind = DECISIONS.get(trace.get("decision"), (trace.get("decision") or "Answered", "neutral"))
    pills = [_pill(label, kind)]
    if trace.get("status", "ok") != "ok":
        pills.append(_pill("Service problem", "bad"))
    if trace.get("language_guard") in ("rewritten_ok", "stripped"):
        pills.append(_pill("Language check applied", "warn"))
    tin, tout = trace.get("input_tokens", 0), trace.get("output_tokens", 0)

    tools = trace.get("tools", [])
    if tools:
        tools_cell = " ".join(
            f'<code>{esc(t.get("tool"))}</code> '
            f'{_pill(t.get("status") or "done", TOOL_STATUS.get(t.get("status"), "neutral"))}' for t in tools)
    else:
        tools_cell = '<span class="none">None needed</span>'

    chunks = trace.get("evidence", {}).get("policy_chunks", [])
    evid_cell = (" ".join(f'<code>{esc(c["id"])}</code> <span class="sub">{c["score"]:.2f}</span>' for c in chunks)
                 if chunks else '<span class="none">None retrieved</span>')

    mem = trace.get("evidence", {}).get("memory", [])
    mem_cell = (", ".join(esc(m["fact"]) for m in mem) if mem else '<span class="none">None used</span>')

    sent_mem = len(trace.get("context_memory", []))
    ctx_cell = (f'{_plural(sent_mem, "memory fact")} · {_plural(history_sent, "earlier message")} · '
                f'{_plural(len(chunks), "policy section")} + question '
                f'<span class="sub">(full handbook never sent)</span>')

    rows = [("Tools called", tools_cell), ("Policy evidence", evid_cell),
            ("Memory used", mem_cell), ("Context sent", ctx_cell)]
    summary = "".join(f'<tr><td class="k">{k}</td><td class="wrap">{v}</td></tr>' for k, v in rows)

    details = ""
    if tools:
        trs = "".join(
            f'<tr><td class="num">{t.get("step", "")}</td><td><code>{esc(t.get("tool"))}</code></td>'
            f'<td class="wrap">{esc(_short_value(t.get("args") or "-"))}</td>'
            f'<td>{_pill(t.get("status") or "done", TOOL_STATUS.get(t.get("status"), "neutral"))}</td>'
            f'<td class="wrap">{esc(_result_summary(t.get("result")))}</td>'
            f'<td class="num">{t.get("latency_ms", 0):g} ms</td></tr>' for t in tools)
        details = ('<details class="more"><summary>Tool call details</summary><div class="scroll"><table>'
                   '<tr><th>Step</th><th>Tool</th><th>Input</th><th>Status</th><th>Result</th><th>Time</th></tr>'
                   f'{trs}</table></div></details>')

    trace_id = trace.get("trace_id")
    footer = (f'<div class="sub" style="margin-top:0.45rem">Trace ID {esc(trace_id)} · saved to data/traces.jsonl</div>'
              if trace_id else "")

    tiles = _kpis([("Response time", f'{trace.get("latency_s", 0):.2f}s'),
                   ("Input tokens", f"{tin:,}"), ("Output tokens", f"{tout:,}"),
                   ("Model calls", trace.get("llm_calls", 0))])
    return (f'<div class="trace"><div class="row">{"".join(pills)}</div>{tiles}'
            f'<table>{summary}</table>{details}{footer}</div>')
