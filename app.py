import streamlit as st
import requests
import json
import os
import datetime
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client
from dotenv import load_dotenv

# =====================
# ENV & CONFIG
# =====================
load_dotenv()

st.set_page_config(
    page_title="The Blueprint",
    layout="wide"
)

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# =====================
# SUPABASE (NO CACHE!)
# =====================
def get_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = get_supabase()

# =====================
# SESSION REHYDRATION
# =====================
if "user" not in st.session_state:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.user = session.user
            st.session_state.username = (
                session.user.user_metadata.get("username")
                or session.user.email.split("@")[0]
            )
            if "temp" not in st.session_state:
                st.session_state.temp = 0.4
    except:
        pass


# =====================
# HELPERS
# =====================
def read_document(file):
    try:
        name = file.name.lower()
        if name.endswith(".pdf"):
            return "".join(p.extract_text() or "" for p in PdfReader(file).pages)
        if name.endswith(".docx"):
            return "\n".join(p.text for p in Document(file).paragraphs)
        return file.read().decode("utf-8")
    except Exception as e:
        return f"\n[Error reading {file.name}: {e}]\n"

def load_user_chats(user_id):
    try:
        res = (
            supabase.table("chat_history")
            .select("*")
            .eq("user_id", user_id)
            .order("last_updated", desc=True)
            .execute()
        )
        return {row["chat_id"]: row["messages"] for row in res.data}
    except:
        return {}

def save_chat(user_id, chat_id, messages, username):
    try:
        supabase.table("chat_history").upsert(
            {
                "user_id": user_id,
                "chat_id": chat_id,
                "messages": messages,
                "username": username,
                "last_updated": datetime.datetime.utcnow().isoformat()
            },
            on_conflict="user_id,chat_id"
        ).execute()
    except:
        pass

# =====================
# AUTH GATE (HARD)
# =====================
if "user" not in st.session_state:

    st.title("The Blueprint")

    tab_login, tab_reg = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Login", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({
                        "email": email,
                        "password": password
                    })

                    st.session_state.user = res.user
                    st.session_state.username = (
                        res.user.user_metadata.get("username")
                        or email.split("@")[0]
                    )
                    st.session_state.temp = 0.4
                    st.rerun()

                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_reg:
        with st.form("register"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Register", use_container_width=True):
                try:
                    supabase.auth.sign_up({
                        "email": email,
                        "password": password,
                        "options": {"data": {"username": username}}
                    })
                    st.success("Registered. Please login.")
                except Exception as e:
                    st.error(f"Register failed: {e}")

    st.stop()

# =====================
# USER CONTEXT
# =====================
user = st.session_state.user
user_id = user.id
username = st.session_state.username

# =====================
# LOAD CHAT STATE
# =====================
db_history = load_user_chats(user_id)

if "current_chat_id" not in st.session_state:
    if db_history:
        cid = next(iter(db_history))
        st.session_state.current_chat_id = cid
        st.session_state.messages = db_history[cid]
    else:
        st.session_state.current_chat_id = "Main Blueprint"
        st.session_state.messages = [
            {"role": "assistant", "content": "Architect ready. System online."}
        ]

# =====================
# SIDEBAR
# =====================
with st.sidebar:
    st.title("The Blueprint")
    st.write(f"User: **{username}**")
    st.caption("● System Online")

    if st.button("+ New Blueprint", use_container_width=True):
        st.session_state.current_chat_id = f"Blueprint {len(db_history) + 1}"
        st.session_state.messages = [
            {"role": "assistant", "content": "Architect ready. System online."}
        ]
        st.rerun()

    st.divider()
    st.subheader("Archive")

    for cid in db_history:
        active = cid == st.session_state.current_chat_id
        label = f"» {cid}" if active else cid
        if st.button(label, key=f"chat_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

    st.divider()
    st.session_state.temp = st.slider(
        "Creativity",
        0.0, 1.0,
        st.session_state.temp,
        0.1
    )

    if st.button("Logout", type="primary", use_container_width=True):
        supabase.auth.sign_out()   # <- WAJIB
        st.session_state.clear()
        st.rerun()


# =====================
# CHAT UI
# =====================
st.caption(f"Session: {st.session_state.current_chat_id}")

for msg in st.session_state.messages:
    role = "Architect" if msg["role"] == "assistant" else username
    color = "green" if msg["role"] == "assistant" else "blue"
    st.markdown(f"**:{color}[{role}]**: {msg['content']}")

# =====================
# INPUT
# =====================
if prompt := st.chat_input("Describe your blueprint...", accept_file=True):
    text = prompt.text
    files = "".join(
        f"\n\n[Document {f.name}]\n{read_document(f)}"
        for f in prompt.files
    )
    st.session_state.messages.append({
        "role": "user",
        "content": text + files
    })
    st.rerun()

# =====================
# AI RESPONSE
# =====================
if st.session_state.messages[-1]["role"] == "user":

    TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    box = st.empty()
    full = ""

    try:
        r = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "model": DEDICATED_MODEL,
                "messages": [
                    {"role": "system", "content": f"You are VibeCode Architect. Address user as {username}."}
                ] + st.session_state.messages,
                "temperature": st.session_state.temp,
                "stream": True
            },
            stream=True
        )

        for line in r.iter_lines():
            if not line:
                continue
            data = line.decode()
            if data.startswith("data: ") and "[DONE]" not in data:
                token = json.loads(data[6:])["choices"][0]["delta"].get("content", "")
                full += token
                box.markdown(f"**:green[Architect]**: {full}▌")

        box.markdown(f"**:green[Architect]**: {full}")
        st.session_state.messages.append({"role": "assistant", "content": full})
        save_chat(user_id, st.session_state.current_chat_id, st.session_state.messages, username)
        st.rerun()

    except Exception as e:
        st.error(f"Model error: {e}")