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
    GROQ_API_KEY = None  # Never hardcode secrets

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS medical_history (
            user_id TEXT,
            date TEXT,
            substance TEXT,
            dosage TEXT,
            reaction TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            username TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME
        )
    """)
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

# ---------------- AI (DB-AWARE) ----------------
def get_ai_response(user_input, history_df):
    client = Groq(api_key=GROQ_API_KEY)
    history_context = history_df.to_string(index=False)

    system_msg = f"""
You are a Medical Guardian AI.

You are accessing the user's secure medical database.

DATABASE RECORDS FOUND:
{history_context}

INSTRUCTIONS:
1. Start by explicitly stating that you are reviewing the user's medical records.
2. Analyze medication and alcohol interactions if mentioned.
3. Warn clearly about dangerous combinations (e.g., Xanax + alcohol, Metformin + alcohol).
4. Ask about dosage if pills are mentioned and compare with prescribed dose.
5. Provide immediate safety guidance.
"""

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_input}
        ],
        temperature=0.2
    )
    return completion.choices[0].message.content

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

    with st.sidebar:
        st.write(f"🔐 Database: **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Guardian Crisis Interface")
    st.caption("AI is actively monitoring your medication interactions based on historical data.")

    conn = init_db()

    # Load medical history (DB CONTEXT)
    hidden_history = pd.read_sql_query(
        "SELECT * FROM medical_history WHERE user_id=?",
        conn,
        params=(st.session_state.username,)
    )

    chat_log = pd.read_sql_query(
        "SELECT role, content, timestamp FROM chat_messages WHERE username=? ORDER BY timestamp",
        conn,
        params=(st.session_state.username,)
    )

    # ---------- CHAT HISTORY (PAIR DELETE) ----------
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
                    if st.button("🗑", key=f"del_{row['timestamp']}"):
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
    if prompt := st.chat_input("What is happening?"):
        with st.chat_message("user"):
            st.write(prompt)
        save_chat(st.session_state.username, "user", prompt)

        with st.spinner("Querying database and analyzing interactions..."):
            response = get_ai_response(prompt, hidden_history)

        with st.chat_message("assistant"):
              st.markdown(response)
        save_chat(st.session_state.username, "assistant", response)

# 🔴 Force reload so delete button appears immediately
        st.rerun()


    # ---------- LOGO ----------
    if logo_b64:
        st.markdown(
            f"""
            <div style="position:fixed; bottom:600px; left:200px; opacity:0.9;">
                <img src="data:image/png;base64,{logo_b64}" width="120">
            </div>
            """,
            unsafe_allow_html=True
        )
