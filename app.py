import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime
from groq import Groq
import base64
from io import BytesIO
from PIL import Image

# --- 1. CONFIGURATION ---
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")

# --- 1a. LOGO FROM SECRETS ---
def render_logo():
    if "LOGO_BASE64" in st.secrets:
        try:
            img_bytes = base64.b64decode(st.secrets["LOGO_BASE64"])
            img = Image.open(BytesIO(img_bytes))
            col1, col2 = st.columns([8, 1])
            with col2:
                st.image(img, width=120)
        except Exception:
            pass

# --- 2. DATABASE ---
def init_db():
    conn = sqlite3.connect("medical_guardian.db", check_same_thread=False)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT
        )
    """)

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

def save_chat_to_db(username, role, content):
    conn = init_db()
    conn.execute(
        "INSERT INTO chat_messages VALUES (?,?,?,?)",
        (username, role, content, datetime.now())
    )
    conn.commit()

def delete_chat_pair(username, user_timestamp):
    conn = init_db()
    c = conn.cursor()

    c.execute(
        "DELETE FROM chat_messages WHERE username=? AND role='user' AND timestamp=?",
        (username, user_timestamp)
    )

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

# --- 3. AI ---
def get_ai_response(user_input, history_df, username):
    client = Groq(api_key=GROQ_API_KEY)
    history_context = history_df.to_string(index=False)

    system_msg = f"""
You are a Medical Guardian AI.

DATABASE RECORDS:
{history_context}

RULES:
1. Read records first
2. Detect alcohol + medication interaction
3. Ask dosage questions
4. Give safety steps
"""

    conn = init_db()
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE username=? ORDER BY timestamp ASC",
        (username,)
    ).fetchall()

    messages = [{"role": "system", "content": system_msg}]
    messages.extend([{"role": r, "content": c} for r, c in rows])
    messages.append({"role": "user", "content": user_input})

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.2
    )

    return completion.choices[0].message.content

# --- 4. UI ---
st.set_page_config(page_title="Guardian AI", layout="centered")
init_db()
render_logo()

# --- AUTH ---
if "logged_in" not in st.session_state:
    st.title("🛡️ Guardian AI: Secure Portal")
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Log In"):
            hashed = hashlib.sha256(p.encode()).hexdigest()
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
            hashed = hashlib.sha256(new_p.encode()).hexdigest()
            try:
                init_db().execute(
                    "INSERT INTO users VALUES (?,?)", (new_u, hashed)
                )
                init_db().commit()
                st.success("Account created")
            except sqlite3.IntegrityError:
                st.error("Username exists")

# --- MAIN APP ---
else:
    with st.sidebar:
        st.write(f"🔐 **{st.session_state.username}**")
        if st.button("Logout"):
            st.session_state.clear()
            st.rerun()

    st.title("Guardian Crisis Interface")

    conn = init_db()

    history_df = pd.read_sql_query(
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

    # --- CHAT RENDER ---
    for _, row in chat_log.iterrows():
        if row["role"] == "user":
            col_msg, col_del = st.columns([20, 1])

            with col_msg:
                with st.chat_message("user"):
                    st.write(row["content"])

            with col_del:
                if st.button(
                    "🗑️",
                    key=f"del_{row['timestamp']}",
                    help="Delete chat",
                ):
                    delete_chat_pair(
                        st.session_state.username,
                        row["timestamp"]
                    )
                    st.rerun()

        else:
            with st.chat_message("assistant"):
                st.write(row["content"])

    # --- INPUT ---
    if prompt := st.chat_input("What is happening?"):
        with st.chat_message("user"):
            st.write(prompt)

        save_chat_to_db(st.session_state.username, "user", prompt)

        with st.spinner("Analyzing interactions..."):
            response = get_ai_response(
                prompt,
                history_df,
                st.session_state.username
            )

        with st.chat_message("assistant"):
            st.markdown(response)

        save_chat_to_db(st.session_state.username, "assistant", response)
