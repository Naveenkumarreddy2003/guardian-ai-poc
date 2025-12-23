import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime
from groq import Groq
import os
import base64

# --- 1. CONFIGURATION ---
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except Exception:
    GROQ_API_KEY = ""

# --- 1a. Logo Base64 Helper ---
LOGO_PATH = "logo.png"

def get_base64_image(path):
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

logo_b64 = get_base64_image(LOGO_PATH)

# --- 2. DATABASE ENGINE ---
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

def save_chat_to_db(username, role, content):
    conn = init_db()
    conn.execute(
        "INSERT INTO chat_messages VALUES (?,?,?,?)",
        (username, role, content, datetime.now())
    )
    conn.commit()

def load_chat_history(username, limit=50):
    conn = init_db()
    rows = conn.execute(
        """
        SELECT role, content, timestamp
        FROM chat_messages
        WHERE username=?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (username, limit)
    ).fetchall()
    return [{"role": r, "content": c, "timestamp": t} for r, c, t in rows]

def delete_chat_pair(username, user_timestamp):
    conn = init_db()
    c = conn.cursor()
    # Delete user message
    c.execute(
        """
        DELETE FROM chat_messages
        WHERE username=? AND role='user' AND timestamp=?
        """,
        (username, user_timestamp)
    )
    # Delete immediate assistant response
    c.execute(
        """
        DELETE FROM chat_messages
        WHERE username=? AND role='assistant'
          AND timestamp > ?
        ORDER BY timestamp ASC
        LIMIT 1
        """,
        (username, user_timestamp)
    )
    conn.commit()

def seed_demo_data(username):
    conn = init_db()
    c = conn.cursor()
    if username.lower() == "user1":
        records = [
            ("2023-10-12", "Xanax (Alprazolam)", "0.5mg (Prescribed Daily)", "Anxiety management"),
            ("2024-05-20", "Alcohol + Xanax", "3 beers", "Severe panic attack, heart racing")
        ]
    elif username.lower() == "user2":
        records = [
            ("2023-08-15", "Metformin", "500mg (Prescribed Daily)", "Diabetes management"),
            ("2024-11-02", "Alcohol + Metformin", "2 glasses wine", "Panic, extreme nausea, cold sweats")
        ]
    else:
        records = [("2025-01-01", "General", "N/A", "Initial baseline")]

    for r in records:
        c.execute(
            "INSERT INTO medical_history VALUES (?,?,?,?,?)",
            (username, r[0], r[1], r[2], r[3])
        )
    conn.commit()

# --- 3. AI REASONING ENGINE ---
def get_ai_response(user_input, history_df, username):
    client = Groq(api_key=GROQ_API_KEY)
    history_context = history_df.to_string(index=False)

    system_msg = f"""
You are a Medical Guardian AI. You are reading from the user's secure 2-year medical database.

DATABASE RECORDS FOUND:
{history_context}

INSTRUCTIONS:
1. Read the database first.
2. Analyze alcohol + medication interactions.
3. Check dosage if pills are mentioned.
4. Suggest immediate recovery steps.
"""

    chat_history = load_chat_history(username)
    messages = [{"role": "system", "content": system_msg}]
    messages.extend(chat_history)
    messages.append({"role": "user", "content": user_input})

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.2
    )
    return completion.choices[0].message.content

# --- 4. UI FLOW ---
st.set_page_config(page_title="Guardian AI", layout="centered")
init_db()

# --- Render logo at top-right ---
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

# --- Authentication ---
if "logged_in" not in st.session_state:
    st.title("🛡️ Guardian AI: Secure Portal")
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Log In"):
            hashed = hashlib.sha256(str.encode(p)).hexdigest()
            conn = init_db()
            if conn.execute(
                "SELECT * FROM users WHERE username=? AND password=?",
                (u, hashed)
            ).fetchone():
                st.session_state.logged_in = True
                st.session_state.username = u
                st.rerun()
            else:
                st.error("Invalid credentials")

    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")
        if st.button("Create Account"):
            hashed = hashlib.sha256(str.encode(new_p)).hexdigest()
            conn = init_db()
            try:
                conn.execute("INSERT INTO users VALUES (?,?)", (new_u, hashed))
                conn.commit()
                seed_demo_data(new_u)
                st.success("Account created successfully.")
            except sqlite3.IntegrityError:
                st.error("Username already exists.")

else:
    with st.sidebar:
        st.write(f"🔐 User: **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Guardian Crisis Interface")

    conn = init_db()
    hidden_history = pd.read_sql_query(
        "SELECT * FROM medical_history WHERE user_id=?",
        conn,
        params=(st.session_state.username,)
    )

    chat_log = pd.read_sql_query(
        """
        SELECT role, content, timestamp
        FROM chat_messages
        WHERE username=?
        ORDER BY timestamp ASC
        """,
        conn,
        params=(st.session_state.username,)
    )

    # --- Render chat with delete icon ---
    for _, row in chat_log.iterrows():
        with st.chat_message(row["role"]):
            st.write(row["content"])
            if row["role"] == "user":
                col1, col2 = st.columns([0.95, 0.05])
                with col2:
                    if st.button(
                        "🗑️",
                        key=f"del_{row['timestamp']}",
                        help="Delete this chat message",
                        use_container_width=False
                    ):
                        delete_chat_pair(st.session_state.username, row["timestamp"])
                        st.experimental_rerun()

    # --- New message ---
    if prompt := st.chat_input("What is happening?"):
        with st.chat_message("user"):
            st.write(prompt)
        save_chat_to_db(st.session_state.username, "user", prompt)

        with st.spinner("Analyzing interactions..."):
            response = get_ai_response(
                prompt,
                hidden_history,
                st.session_state.username
            )

        with st.chat_message("assistant"):
            st.markdown(response)

        save_chat_to_db(st.session_state.username, "assistant", response)
