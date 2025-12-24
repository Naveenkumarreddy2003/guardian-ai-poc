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

# --- 1a. LOGO FROM SECRETS (DEPLOYMENT SAFE) ---
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

def seed_demo_data(username):
    conn = init_db()
    c = conn.cursor()

    if username.lower() == "user1":
        records = [
            ("2023-10-12", "Xanax (Alprazolam)", "0.5mg (Prescribed Daily)", "Anxiety management"),
            ("2024-05-20", "Alcohol + Xanax", "3 beers", "Severe panic attack")
        ]
    elif username.lower() == "user2":
        records = [
            ("2023-08-15", "Metformin", "500mg (Prescribed Daily)", "Diabetes management"),
            ("2024-11-02", "Alcohol + Metformin", "2 glasses wine", "Nausea, panic")
        ]
    else:
        records = [("2025-01-01", "General", "N/A", "Initial baseline")]

    for r in records:
        c.execute(
            "INSERT INTO medical_history VALUES (?,?,?,?,?)",
            (username, r[0], r[1], r[2], r[3])
        )

    conn.commit()

# --- 3. AI ENGINE ---
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

# --- 4. UI ---
st.set_page_config(page_title="Guardian AI", layout="centered")
init_db()

render_logo()

# --- Authentication ---
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
            conn = init_db()

            try:
                conn.execute("INSERT INTO users VALUES (?,?)", (new_u, hashed))
                conn.commit()
                seed_demo_data(new_u)
                st.success("Account created successfully.")
            except sqlite3.IntegrityError:
                st.error("Username already exists")

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

    for _, row in chat_log.iterrows():
        with st.chat_message(row["role"]):
            st.write(row["content"])
            if row["role"] == "user":
                delete_button_html = f"""
                <button title="Delete chat" class="delete-btn" id="del_{row['timestamp']}">
                    <i class="fa fa-trash" style="font-size: 14px;"></i>
                </button>
                """
                st.markdown(delete_button_html, unsafe_allow_html=True)

                # Handle the delete action via JS
                if st.button(f"Delete {row['timestamp']}", key=f"del_{row['timestamp']}"):
                    delete_chat_pair(st.session_state.username, row["timestamp"])
                    st.experimental_rerun()

    if prompt := st.chat_input("What is happening?"):
        with st.chat_message("user"):
            st.write(prompt)

        save_chat_to_db(st.session_state.username, "user", prompt)

        with st.spinner("Analyzing interactions..."):
            response = get_ai_response(prompt, hidden_history, st.session_state.username)

        with st.chat_message("assistant"):
            st.markdown(response)

        save_chat_to_db(st.session_state.username, "assistant", response)

# Add some custom CSS to make the icon appear small and with hover tooltip
st.markdown("""
    <style>
        .delete-btn {
            background-color: transparent;
            border: none;
            cursor: pointer;
            display: inline-block;
            transition: all 0.3s ease;
        }
        .delete-btn:hover {
            color: red;
        }
        .delete-btn i {
            font-size: 16px;  /* Small icon size */
        }
        .delete-btn[title]:hover:after {
            content: attr(title);
            position: absolute;
            background: #333;
            color: #fff;
            border-radius: 4px;
            padding: 5px;
            font-size: 12px;
            top: -25px;
            left: 50%;
            transform: translateX(-50%);
            white-space: nowrap;
            visibility: visible;
        }
    </style>
""", unsafe_allow_html=True)
