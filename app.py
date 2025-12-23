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
    GROQ_API_KEY = "your_api_key"

# --- 2. DATABASE ENGINE ---
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
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_messages VALUES (?,?,?,?)",
        (username, role, content, datetime.now())
    )
    conn.commit()


# --- 3. DEMO MEDICAL DATA ---
def seed_demo_data(username):
    conn = init_db()
    c = conn.cursor()

    if username.lower() == "user@123":
        records = [
            ("2023-10-12", "Xanax (Alprazolam)", "0.5mg (Prescribed Daily)", "Anxiety management"),
            ("2024-05-20", "Alcohol + Xanax", "3 beers", "Severe panic attack, heart racing")
        ]
    elif username.lower() == "bt@123":
        records = [
            ("2023-08-15", "Metformin", "500mg (Prescribed Daily)", "Diabetes management"),
            ("2024-11-02", "Alcohol + Metformin", "2 glasses wine", "Panic, extreme nausea, cold sweats")
        ]
    else:
        records = [
            ("2025-01-01", "General", "N/A", "Initial baseline")
        ]

    for rec in records:
        c.execute(
            "INSERT INTO medical_history VALUES (?,?,?,?,?)",
            (username, rec[0], rec[1], rec[2], rec[3])
        )

    conn.commit()


# --- 🔥 DEPLOYMENT FIX (IMPORTANT) ---
def ensure_medical_history(username):
    conn = init_db()
    c = conn.cursor()

    count = c.execute(
        "SELECT COUNT(*) FROM medical_history WHERE user_id = ?",
        (username,)
    ).fetchone()[0]

    if count == 0:
        seed_demo_data(username)


# --- 4. AI ENGINE ---
def get_ai_response(user_input, history_df):
    client = Groq(api_key=GROQ_API_KEY)

    history_context = history_df.to_string(index=False)

    system_msg = f"""
You are a Medical Guardian AI. You are reading from the user's secure medical database.

DATABASE RECORDS FOUND:
{history_context}

INSTRUCTIONS:
1. Start with: "I am accessing your encrypted medical records..."
2. If alcohol + Xanax or Metformin → explain panic cause.
3. Ask about dosage if pills are mentioned.
4. Provide immediate safety guidance.
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


# --- 5. UI ---
st.set_page_config(page_title="Guardian AI", layout="centered")
init_db()

if "logged_in" not in st.session_state:

    st.title("🛡️ Guardian AI: Secure Portal")
    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")

        if st.button("Log In"):
            hashed_p = hashlib.sha256(p.encode()).hexdigest()
            conn = init_db()

            if conn.execute(
                "SELECT * FROM users WHERE username=? AND password=?",
                (u, hashed_p)
            ).fetchone():

                st.session_state.logged_in = True
                st.session_state.username = u

                # 🔥 FIX EXECUTED HERE
                ensure_medical_history(u)

                st.rerun()
            else:
                st.error("Invalid username or password")

    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")

        if st.button("Create Account"):
            hashed = hashlib.sha256(new_p.encode()).hexdigest()
            conn = init_db()
            try:
                conn.execute("INSERT INTO users VALUES (?,?)", (new_u, hashed))
                conn.commit()

                seed_demo_data(new_u)

                st.success("Registration successful! Medical history synced.")
            except sqlite3.IntegrityError:
                st.error("Username already exists")

else:
    with st.sidebar:
        st.write(f"🔐 Logged in as **{st.session_state.username}**")
        if st.button("Logout"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    st.title("Guardian Crisis Interface")

    st.warning(
        "⚠️ This AI provides informational guidance only. "
        "It is NOT a substitute for professional medical advice."
    )

    conn = init_db()

    hidden_history = pd.read_sql_query(
        "SELECT * FROM medical_history WHERE user_id = ?",
        conn,
        params=(st.session_state.username,)
    )

    chat_log = pd.read_sql_query(
        "SELECT role, content FROM chat_messages WHERE username = ? ORDER BY timestamp",
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

        with st.spinner("Analyzing medical history..."):
            response = get_ai_response(prompt, hidden_history)

        with st.chat_message("assistant"):
            st.markdown(response)

        save_chat_to_db(st.session_state.username, "assistant", response)

