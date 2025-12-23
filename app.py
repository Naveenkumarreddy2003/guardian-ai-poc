import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import os
import base64
from datetime import datetime
from groq import Groq

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, "logo.png")

try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except Exception:
    GROQ_API_KEY = "your api key"  # DEV ONLY

def get_base64_image(path):
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect("medical_guardian.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS medical_history
                 (user_id TEXT, date TEXT, substance TEXT, dosage TEXT, reaction TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS chat_messages
                 (username TEXT, role TEXT, content TEXT, timestamp DATETIME)""")
    conn.commit()
    return conn

def save_chat(username, role, content):
    conn = init_db()
    conn.execute(
        "INSERT INTO chat_messages VALUES (?,?,?,?)",
        (username, role, content, datetime.now())
    )
    conn.commit()

def delete_chat_pair(username, ts_user, ts_assistant):
    conn = init_db()
    conn.execute(
        "DELETE FROM chat_messages WHERE username=? AND timestamp IN (?,?)",
        (username, ts_user, ts_assistant)
    )
    conn.commit()

# ---------------- AI ----------------
def get_ai_response(user_input, history_df):
    client = Groq(api_key=GROQ_API_KEY)
    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a Medical Guardian AI."},
            {"role": "user", "content": user_input}
        ],
        temperature=0.2
    )
    return res.choices[0].message.content

# ---------------- PAGE SETUP ----------------
st.set_page_config(page_title="Guardian AI", layout="centered")
init_db()

# ---------------- AUTH ----------------
if "logged_in" not in st.session_state:
    st.title("🛡️ Guardian AI – Secure Portal")

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username", key="login_user")
        p = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            hp = hashlib.sha256(p.encode()).hexdigest()
            if init_db().execute(
                "SELECT * FROM users WHERE username=? AND password=?", (u, hp)
            ).fetchone():
                st.session_state.logged_in = True
                st.session_state.username = u
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        nu = st.text_input("Username", key="reg_user")
        np = st.text_input("Password", type="password", key="reg_pass")
        if st.button("Register"):
            hp = hashlib.sha256(np.encode()).hexdigest()
            try:
                init_db().execute("INSERT INTO users VALUES (?,?)", (nu, hp))
                init_db().commit()
                st.success("Account created")
            except sqlite3.IntegrityError:
                st.error("User already exists")

# ---------------- MAIN APP ----------------
else:
    logo_b64 = get_base64_image(LOGO_PATH)

    # ---------- SIDEBAR ----------
    with st.sidebar:
        st.markdown(f"👤 **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    # ---------- LOAD CHAT ----------
    conn = init_db()
    chat_log = pd.read_sql_query(
        f"""
        SELECT role, content, timestamp
        FROM chat_messages
        WHERE username='{st.session_state.username}'
        ORDER BY timestamp
        """,
        conn
    )

    # ---------- SMALL DELETE BUTTON CSS ----------
    st.markdown(
        """
        <style>
        button[kind="secondary"] {
            padding: 0.15rem 0.35rem !important;
            font-size: 0.7rem !important;
            min-height: unset !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # ---------- CHAT HISTORY (PAIR-WISE DELETE) ----------
    i = 0
    while i < len(chat_log):
        row = chat_log.iloc[i]

        if row["role"] == "user" and i + 1 < len(chat_log):
            next_row = chat_log.iloc[i + 1]

            with st.container():
                col_msg, col_del = st.columns([20, 1])

                with col_msg:
                    with st.chat_message("user"):
                        st.write(row["content"])
                    if next_row["role"] == "assistant":
                        with st.chat_message("assistant"):
                            st.write(next_row["content"])

                with col_del:
                    if st.button(
                        "🗑",
                        key=f"del_pair_{row['timestamp']}",
                        help="Delete this conversation"
                    ):
                        delete_chat_pair(
                            st.session_state.username,
                            row["timestamp"],
                            next_row["timestamp"]
                        )
                        st.rerun()

            i += 2
        else:
            i += 1

    # ---------- CHAT INPUT ----------
    if prompt := st.chat_input("Input your concern..."):
        with st.chat_message("user"):
            st.write(prompt)
        save_chat(st.session_state.username, "user", prompt)

        with st.spinner("Analyzing medical history..."):
            reply = get_ai_response(prompt, pd.DataFrame())

        with st.chat_message("assistant"):
            st.markdown(reply)

        save_chat(st.session_state.username, "assistant", reply)

    # ---------- FIXED RIGHT-SIDE LOGO (RESTORED) ----------
    if logo_b64:
        st.markdown(
            f"""
            <style>
            .fixed-footer-logo {{
                position: fixed;
                bottom: 605px;
                left: 200px;
                z-index: 999;
                opacity: 0.9;
                pointer-events: none;
            }}
            </style>

            <div class="fixed-footer-logo">
                <img src="data:image/png;base64,{logo_b64}" width="120">
            </div>
            """,
            unsafe_allow_html=True
        )


