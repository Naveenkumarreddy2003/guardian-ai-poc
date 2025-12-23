import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime
from groq import Groq

# --- 1. CONFIGURATION ---
try:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
except Exception:
    GROQ_API_KEY = ""   # Never hardcode secrets

# --- 2. DATABASE ENGINE ---
def init_db():
    conn = sqlite3.connect('medical_guardian.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS medical_history (user_id TEXT, date TEXT, substance TEXT, dosage TEXT, reaction TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS chat_messages (username TEXT, role TEXT, content TEXT, timestamp DATETIME)')
    conn.commit()
    return conn

def save_chat_to_db(username, role, content):
    conn = init_db()
    conn.execute(
        'INSERT INTO chat_messages VALUES (?,?,?,?)',
        (username, role, content, datetime.now())
    )
    conn.commit()

def load_chat_history(username, limit=20):
    conn = init_db()
    rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE username=?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (username, limit)
    ).fetchall()
    return [{"role": r, "content": c} for r, c in rows]

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

    for rec in records:
        c.execute(
            "INSERT INTO medical_history VALUES (?,?,?,?,?)",
            (username, rec[0], rec[1], rec[2], rec[3])
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
1. READ DATABASE: Start by saying "I am accessing your encrypted medical records..."
2. ANALYZE INTERACTIONS: If alcohol is mentioned, check medication conflicts.
3. CHECK DOSAGE if pills are mentioned.
4. SUGGEST immediate recovery steps.
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

if 'logged_in' not in st.session_state:
    st.title("🛡️ Guardian AI: Secure Portal")
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username", key="login_u")
        p = st.text_input("Password", type="password", key="login_p")
        if st.button("Log In"):
            hashed_p = hashlib.sha256(str.encode(p)).hexdigest()
            conn = init_db()
            if conn.execute(
                'SELECT * FROM users WHERE username=? AND password=?',
                (u, hashed_p)
            ).fetchone():
                st.session_state.logged_in = True
                st.session_state.username = u
                st.rerun()
            else:
                st.error("Invalid Username or Password")

    with tab2:
        new_u = st.text_input("Username", key="reg_u")
        new_p = st.text_input("Password", type="password", key="reg_p")
        if st.button("Create Account"):
            hashed = hashlib.sha256(str.encode(new_p)).hexdigest()
            conn = init_db()
            try:
                conn.execute('INSERT INTO users VALUES (?,?)', (new_u, hashed))
                conn.commit()
                seed_demo_data(new_u)
                st.success("Registration successful! Medical history synced.")
            except sqlite3.IntegrityError:
                st.error("Username already exists.")

else:
    with st.sidebar:
        st.write(f"🔐 Database: **{st.session_state.username}**")
        if st.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    st.title("Guardian Crisis Interface")
    st.caption("AI monitoring medication interactions based on historical data.")

    conn = init_db()
    hidden_history = pd.read_sql_query(
        "SELECT * FROM medical_history WHERE user_id=?",
        conn,
        params=(st.session_state.username,)
    )

    chat_log = pd.read_sql_query(
        "SELECT role, content FROM chat_messages WHERE username=? ORDER BY timestamp ASC",
        conn,
        params=(st.session_state.username,)
    )

    for _, row in chat_log.iterrows():
        with st.chat_message(row["role"]):
            st.write(row["content"])

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
