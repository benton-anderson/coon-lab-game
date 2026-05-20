import json, random
import streamlit as st
import psycopg
from streamlit_autorefresh import st_autorefresh
import viewer


PLAYERS = dict(st.secrets["players"])

SQUARES = {
    "a": [
        'Justin McKetney (Scientist, UCSF)',
        'Evgenia Shishkova (Scientist, Bay area)',
        'Jean Lodge (Scientist, Lilly)',
        'Yuchen He (Postdoc, Harvard)',
        'Nick Riley (Prof., Washington)',
        'Chris Rose (Director, Genentech)',
        'Danielle Swaney (Prof., UCSF)',
        'Trent Peters-Clarke (Postdoc, UCSF)',
        'Austin Salome (Scientist, Lilly)',
        'Kevin Schauer (Thermo, sales)',
        'Graeme McAlister (Thermo)',
        'Jesse Meyer (Prof., Cedars-Sinai)',
        'David Good (at nearest bar)',
        'Alicia Richards (Scientist, UCSF)',
        'Dain Brademan (Staff, Stanford)',
        'Gary Wilson (Scientist, Byonic)',
        'Nicole Nightingale (Student, U-Minn)',
        'Laura Muehlbauer (Scientist, Lilly)',
        'Greg Potts (Scientist, Abbvie)',
        'Yunyun Zhu (Scientist, Thermo)',
        'Erin Weisenhorn (Evotec, Seattle)',
        'Kenny Lee (Prof., BYU)',
        'Elyse (Scientist, Abbie)',
        'John Butler (Thermo, not alum)',
        'Steve Gygi (Prof, not alum)',
        'Neil Kelleher (Prof, not alum)',
        'Joe Loo (Prof, not alum)',
        'Mike MacCoss (Prof, not alum)',
    ],
    
    "b": [
        'Put name in raffle to win JACK',
        'Sprint for ice cream in afternoon',
        'Go to hotel bar',
        'Go to 2 workshops and ask question at both',
        'Chill out in Agilent suite',
        'Hear about mass spec pen',
        'Go bar hopping',
        'Get Shimadzu Tshirt or microbe',
        'Stand in line to ask question at oral',
        'Get like 6-7 hummus dips cuz hungry',
        'Attend opening ceremony Sunday',
        'Hear "Single Cell is the Future"',
        'Hear David Good tell stories',
        'Spicy comment or terse question at oral',
        'Get light-up swag',
        'Visit every Coon lab poster',
        "Feel lost and overwhelmed, OR, feel bored cuz it's all the same",
        'Talk to 5 presenters about esoteric yet amazing science',
        'Visit food analysis posters',
        'Visit paleo/archeology posters',
        'Visit ASMS showcase pieces in lobby',
        'Skip 1 oral session to rest',
        'Attend Bieman or Yergey award ceremony',
        'Yell in the Thermo suite (ITS TOO LOUD)',
        'See 10 other UW-Madison poster/talks',
        'Think: "Holy sheet that was cringe"',
    ],
}

CARD_LABELS = {"a": "Meet Alumni", "b": "ASMS To-dos"}
FREE_INDEX = 12

# ============================================================
# DB
# ============================================================
@st.cache_resource
def get_conn():
    return psycopg.connect(st.secrets["DATABASE_URL"], autocommit=True)

def init_db():
    with get_conn().cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
                code TEXT PRIMARY KEY,
                name TEXT,
                card_a TEXT, marked_a TEXT,
                card_b TEXT, marked_b TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                code TEXT NOT NULL,
                content TEXT NOT NULL,
                ts TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        for code, name in PLAYERS.items():
            cur.execute(
                "INSERT INTO players(code, name) VALUES (%s, %s) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
                (code, name),
            )

def deal_card(code, which):
    """Deterministic deal seeded by (code, which)."""
    rng = random.Random(f"{code}:{which}")
    idx = rng.sample(range(len(SQUARES[which])), 24)
    idx.insert(FREE_INDEX, -1)
    marked = [False] * 25
    marked[FREE_INDEX] = True
    return idx, marked

def load_player(code):
    with get_conn().cursor() as cur:
        cur.execute(
            "SELECT name, card_a, marked_a, card_b, marked_b FROM players WHERE code=%s",
            (code,),
        )
        row = cur.fetchone()
    if not row:
        return None
    name, ca, ma, cb, mb = row
    updates = []
    if ca is None:
        ca_idx, ma_arr = deal_card(code, "a")
        ca, ma = json.dumps(ca_idx), json.dumps(ma_arr)
        updates += [("card_a", ca), ("marked_a", ma)]
    if cb is None:
        cb_idx, mb_arr = deal_card(code, "b")
        cb, mb = json.dumps(cb_idx), json.dumps(mb_arr)
        updates += [("card_b", cb), ("marked_b", mb)]
    if updates:
        sets = ", ".join(f"{col}=%s" for col, _ in updates)
        vals = [v for _, v in updates] + [code]
        with get_conn().cursor() as cur:
            cur.execute(f"UPDATE players SET {sets} WHERE code=%s", vals)
    return {
        "name": name,
        "card_a": json.loads(ca), "marked_a": json.loads(ma),
        "card_b": json.loads(cb), "marked_b": json.loads(mb),
    }

def toggle(code, which, i):
    p = load_player(code)
    marked = p[f"marked_{which}"]
    marked[i] = not marked[i]
    with get_conn().cursor() as cur:
        cur.execute(
            f"UPDATE players SET marked_{which}=%s WHERE code=%s",
            (json.dumps(marked), code),
        )

def post_message(code, content):
    content = (content or "").strip()[:500]
    if not content:
        return
    with get_conn().cursor() as cur:
        cur.execute(
            "INSERT INTO messages(code, content) VALUES (%s, %s)", (code, content)
        )

def feed(limit=80):
    with get_conn().cursor() as cur:
        cur.execute("""
            SELECT p.name, m.content, m.ts
            FROM messages m JOIN players p ON p.code = m.code
            ORDER BY m.id DESC LIMIT %s
        """, (limit,))
        return list(reversed(cur.fetchall()))

# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="Bingo", layout="centered")

st.markdown("""
<style>
/* Bingo grid containers: scroll horizontally on narrow screens */
.st-key-bingo_grid_a, .st-key-bingo_grid_b {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 8px;
}
/* Force the 5 columns to stay side-by-side, never stacking */
.st-key-bingo_grid_a [data-testid="stHorizontalBlock"],
.st-key-bingo_grid_b [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    min-width: 720px;
    gap: 6px !important;
}
.st-key-bingo_grid_a [data-testid="stColumn"],
.st-key-bingo_grid_b [data-testid="stColumn"] {
    flex: 0 0 140px !important;
    min-width: 140px !important;
    max-width: 140px !important;
    width: 140px !important;
}
/* Consistent tile sizing and readable text */
.st-key-bingo_grid_a [data-testid="stButton"] > button,
.st-key-bingo_grid_b [data-testid="stButton"] > button {
    min-height: 110px;
    height: 110px;
    white-space: normal;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.25;
    padding: 6px;
    width: 100%;
}
/* Tighter chat layout */
[data-testid="stSidebar"] .stMarkdown p {
    margin-bottom: 0.4rem;
}
</style>
""", unsafe_allow_html=True)

init_db()

# --- Auth ---
code = st.query_params.get("code") or st.text_input("Access code")
if not code:
    st.caption("Enter the code you were given to access your bingo card.")
    st.stop()
player = load_player(code)
if not player:
    st.error("Unknown access code.")
    st.stop()

st.title(f"Bingo — {player['name']}")

# --- Confirmation dialog (state-tracked so autorefresh doesn't dismiss it) ---
@st.dialog("Unmark this square?")
def confirm_unmark():
    which, i, label = st.session_state["confirm"]
    st.write(f"Remove your mark from **{label}**?")
    c1, c2 = st.columns(2)
    if c1.button("Yes, unmark", use_container_width=True, type="primary"):
        toggle(code, which, i)
        del st.session_state["confirm"]
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        del st.session_state["confirm"]
        st.rerun()

if "confirm" in st.session_state:
    confirm_unmark()

# --- Render a card ---
def render_card(which):
    card = player[f"card_{which}"]
    marked = player[f"marked_{which}"]
    n_marked = sum(1 for j, x in enumerate(card) if x != -1 and marked[j])
    st.caption(f"{n_marked} / 24 marked")
    with st.container(key=f"bingo_grid_{which}"):
        for row in range(5):
            cols = st.columns(5, gap="small")
            for c in range(5):
                i = row * 5 + c
                sq_idx = card[i]
                if sq_idx == -1:
                    cols[c].button("⭐ FREE", key=f"{which}_free_{i}",
                                   disabled=True, use_container_width=True)
                    continue
                label = SQUARES[which][sq_idx]
                btn_type = "primary" if marked[i] else "secondary"
                if cols[c].button(label, key=f"{which}_{i}",
                                  type=btn_type, use_container_width=True):
                    if marked[i]:
                        st.session_state["confirm"] = (which, i, label)
                        st.rerun()
                    else:
                        toggle(code, which, i)
                        st.rerun()

tabs = st.tabs([CARD_LABELS["a"], CARD_LABELS["b"]])
with tabs[0]: render_card("a")
with tabs[1]: render_card("b")

viewer.render_viewer(
    conn=get_conn(),
    current_code=code,
    players_dict=PLAYERS,
    squares_dict=SQUARES,
    card_labels=CARD_LABELS,
    free_index=FREE_INDEX,
)

# --- Chat (sidebar, collapses on mobile) ---
with st.sidebar:
    st.subheader("Chat")
    st_autorefresh(interval=3000, key="chat_poll")
    with st.container(height=400):
        for name, content, ts in feed():
            who = "You" if name == player["name"] else name
            time_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else ""
            st.markdown(f"**{who}** · *{time_str}*  \n{content}")
    with st.form("chat_form", clear_on_submit=True):
        msg = st.text_input(
            "Message", max_chars=500,
            label_visibility="collapsed",
            placeholder="Type a message...",
        )
        if st.form_submit_button("Send", use_container_width=True):
            if msg.strip():
                post_message(code, msg)
                st.rerun()