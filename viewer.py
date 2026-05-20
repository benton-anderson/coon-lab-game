"""Read-only viewer for all players' bingo cards, ordered by recent activity."""
import json
import html as _html
from datetime import datetime, timezone
import streamlit as st
from streamlit.components.v1 import html as st_html


MINI_CARD_CSS = """
<style>
.mini-bingo {
    border-collapse: collapse;
    table-layout: fixed;
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
    font-size: 9.5px;
    line-height: 1.15;
}
.mini-bingo td {
    border: 1px solid rgba(128, 128, 128, 0.35);
    width: 20%;
    height: 50px;
    text-align: center;
    vertical-align: middle;
    padding: 2px;
    word-break: break-word;
    overflow: hidden;
}
.mini-bingo td.marked {
    background-color: rgba(255, 100, 50, 0.30);
    font-weight: 600;
}
.mini-bingo td.free {
    background-color: rgba(255, 215, 0, 0.22);
    font-weight: 600;
    font-size: 8.5px;
}
.mini-card-label {
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 4px;
    opacity: 0.75;
    text-align: center;
}
.player-block {
    margin-top: 22px;
    padding-top: 14px;
    border-top: 1px solid rgba(128, 128, 128, 0.25);
    scroll-margin-top: 70px;
}
.player-header {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 10px;
}
.player-activity {
    font-size: 11px;
    opacity: 0.6;
    font-weight: 400;
    margin-left: 8px;
}
</style>
"""


def ensure_schema(conn):
    """Idempotently add last_active column + a trigger that auto-bumps it
    whenever marked_a/marked_b are updated. Means bingo.py needs no changes."""
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE players "
            "ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ;"
        )
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_player_last_active()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.last_active = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        cur.execute(
            "DROP TRIGGER IF EXISTS players_last_active_trigger ON players;"
        )
        cur.execute("""
            CREATE TRIGGER players_last_active_trigger
            BEFORE UPDATE OF marked_a, marked_b ON players
            FOR EACH ROW EXECUTE FUNCTION update_player_last_active();
        """)


def load_all_players(conn, exclude_code):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT code, name, card_a, marked_a, card_b, marked_b, last_active
            FROM players
            WHERE code != %s
            ORDER BY last_active DESC NULLS LAST, name ASC
        """, (exclude_code,))
        rows = cur.fetchall()
    return [
        {
            "code": code, "name": name,
            "card_a":   json.loads(ca) if ca else None,
            "marked_a": json.loads(ma) if ma else None,
            "card_b":   json.loads(cb) if cb else None,
            "marked_b": json.loads(mb) if mb else None,
            "last_active": la,
        }
        for code, name, ca, ma, cb, mb, la in rows
    ]


def _mini_card_html(card_indices, marked, squares_pool, free_index):
    cells = []
    for i, idx in enumerate(card_indices):
        if idx == -1 or i == free_index:
            cells.append('<td class="free">⭐<br>FREE</td>')
        else:
            label = _html.escape(squares_pool[idx])
            css_class = "marked" if marked[i] else ""
            cells.append(f'<td class="{css_class}">{label}</td>')
    rows = "".join(
        f"<tr>{''.join(cells[r*5:(r+1)*5])}</tr>" for r in range(5)
    )
    return f'<table class="mini-bingo">{rows}</table>'


def _format_activity(ts):
    if ts is None:
        return "no marks yet"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    seconds = (now - ts).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    return f"{int(seconds // 86400)} d ago"


def render_viewer(conn, current_code, players_dict,
                  squares_dict, card_labels, free_index):
    ensure_schema(conn)
    st.markdown(MINI_CARD_CSS, unsafe_allow_html=True)
    st.divider()

    # Header row: title + refresh button
    h1, h2 = st.columns([5, 1])
    with h1:
        st.subheader("Other players")
    with h2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()

    players = load_all_players(conn, current_code)
    joined = [p for p in players if p["card_a"] is not None]
    if not joined:
        st.caption("No other players have opened their pages yet.")
        return

    # Dropdown: jump to anyone in the list below
    name_to_anchor = {p["name"]: f"player-{p['code']}" for p in joined}
    selected = st.selectbox(
        "Jump to a player",
        options=["— jump to a player —"] + list(name_to_anchor.keys()),
        index=0,
        label_visibility="collapsed",
    )
    if selected in name_to_anchor:
        if st.session_state.get("last_jumped") != selected:
            st.session_state["last_jumped"] = selected
            anchor = name_to_anchor[selected]
            st_html(f"""
                <script>
                  const target = window.parent.document.getElementById("{anchor}");
                  if (target) target.scrollIntoView({{behavior: "smooth", block: "start"}});
                </script>
            """, height=0)

    # Render every joined player, most-recently-active first
    for p in joined:
        anchor = f"player-{p['code']}"
        activity = _format_activity(p["last_active"])
        st.markdown(
            f'<div class="player-block" id="{anchor}">'
            f'<div class="player-header">{_html.escape(p["name"])}'
            f'<span class="player-activity">· {activity}</span>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        col_a, col_b = st.columns(2)
        for col, which in [(col_a, "a"), (col_b, "b")]:
            with col:
                card = p[f"card_{which}"]
                marked = p[f"marked_{which}"]
                n_marked = sum(
                    1 for j, x in enumerate(card) if x != -1 and marked[j]
                )
                st.markdown(
                    f'<div class="mini-card-label">{card_labels[which]} — '
                    f'{n_marked}/24</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    _mini_card_html(card, marked, squares_dict[which], free_index),
                    unsafe_allow_html=True,
                )