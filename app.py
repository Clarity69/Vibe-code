import streamlit as st
import requests, json, os, datetime
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager

# =====================
# CONFIG
# =====================
load_dotenv()

st.set_page_config(page_title="The Blueprint", layout="wide")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# =====================
# COOKIES
# =====================
cookies = EncryptedCookieManager(
    prefix="blueprint_",
    password=os.getenv("COOKIE_SECRET", "dev-secret")
)

if not cookies.ready():
    st.stop()

# =====================
# SUPABASE
# =====================
def get_supabase():
    return create_client(
        st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL"),
        st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    )

supabase = get_supabase()

# =====================
# SESSION REHYDRATION
# =====================
if "user" not in st.session_state and "access_token" in cookies:
    try:
        supabase.auth.set_session(
            cookies["access_token"],
            cookies["refresh_token"]
        )
        user = supabase.auth.get_user().user
        st.session_state.user = user
        st.session_state.username = (
            user.user_metadata.get("username")
            or user.email.split("@")[0]
        )
        st.session_state.temp = 0.4
    except:
        cookies.clear()

# =====================
# HELPERS
# =====================
def read_document(file):
    try:
        if file.name.endswith(".pdf"):
            return "".join(p.extract_text() or "" for p in PdfReader(file).pages)
        if file.name.endswith(".docx"):
            return "\n".join(p.text for p in Document(file).paragraphs)
        return file.read().decode("utf-8")
    except:
        return ""

def load_user_chats(uid):
    try:
        res = supabase.table("chat_history") \
            .select("*") \
            .eq("user_id", uid) \
            .order("last_updated", desc=True) \
            .execute()
        return {r["chat_id"]: r["messages"] for r in res.data}
    except:
        return {}

def save_chat(uid, cid, msgs, uname):
    supabase.table("chat_history").upsert(
        {
            "user_id": uid,
            "chat_id": cid,
            "messages": msgs,
            "username": uname,
            "last_updated": datetime.datetime.utcnow().isoformat()
        },
        on_conflict="user_id,chat_id"
    ).execute()

# =====================
# AUTH GATE
# =====================
if "user" not in st.session_state:

    st.title("The Blueprint")

    tab_login, tab_reg = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Login", use_container_width=True):
                res = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })

                cookies["access_token"] = res.session.access_token
                cookies["refresh_token"] = res.session.refresh_token
                cookies.save()

                st.session_state.user = res.user
                st.session_state.username = (
                    res.user.user_metadata.get("username")
                    or email.split("@")[0]
                )
                st.session_state.temp = 0.4
                st.rerun()

    with tab_reg:
        with st.form("register"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Register", use_container_width=True):
                supabase.auth.sign_up({
                    "email": email,
                    "password": password,
                    "options": {"data": {"username": username}}
                })
                st.success("Registered. Please login.")

    st.stop()

# =====================
# USER CONTEXT
# =====================
user = st.session_state.user
uid = user.id
username = st.session_state.username

# =====================
# CHAT STATE
# =====================
db_history = load_user_chats(uid)

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

    if st.button("+ New Blueprint", use_container_width=True):
        st.session_state.current_chat_id = f"Blueprint {len(db_history)+1}"
        st.session_state.messages = [
            {"role": "assistant", "content": "Architect ready. System online."}
        ]
        st.rerun()

    st.divider()
    for cid in db_history:
        if st.button(cid, key=cid, use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

    st.divider()
    st.session_state.temp = st.slider("Creativity", 0.0, 1.0, st.session_state.temp, 0.1)

    if st.button("Logout", type="primary", use_container_width=True):
        supabase.auth.sign_out()
        cookies.clear()
        st.session_state.clear()
        st.rerun()

# =====================
# CHAT UI
# =====================
for msg in st.session_state.messages:
    name = "Architect" if msg["role"] == "assistant" else username
    st.markdown(f"**{name}:** {msg['content']}")

# =====================
# INPUT
# =====================
if prompt := st.chat_input("Describe your blueprint...", accept_file=True):
    content = prompt.text + "".join(
        f"\n\n[Document]\n{read_document(f)}" for f in prompt.files
    )
    st.session_state.messages.append({"role": "user", "content": content})
    st.rerun()

# =====================
# AI RESPONSE
# =====================
if st.session_state.messages[-1]["role"] == "user":

    TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    box, full = st.empty(), ""

    r = requests.post(
        "https://router.huggingface.co/v1/chat/completions",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "model": DEDICATED_MODEL,
            "messages": [{"role": "system", "content": f"You are VibeCode Architect. Address user as {username}."}]
                        + st.session_state.messages,
            "temperature": st.session_state.temp,
            "stream": True
        },
        stream=True
    )

    for line in r.iter_lines():
        if line:
            data = line.decode()
            if data.startswith("data: ") and "[DONE]" not in data:
                token = json.loads(data[6:])["choices"][0]["delta"].get("content", "")
                full += token
                box.markdown(f"**:green[Architect]:** {full}▌")

    st.session_state.messages.append({"role": "assistant", "content": full})
    save_chat(uid, st.session_state.current_chat_id, st.session_state.messages, username)
    st.rerun()
