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
# COOKIES (Perbaikan: Inisialisasi)
# =====================
cookies = EncryptedCookieManager(
    prefix="blueprint/",
    password=os.getenv("COOKIE_SECRET", "super-secret-password-123")
)

if not cookies.ready():
    # Menunggu cookie siap tanpa menghentikan total aplikasi
    st.info("Synchronizing session... Please wait.")
    st.stop()

# =====================
# SUPABASE
# =====================
@st.cache_resource
def get_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = get_supabase()

# =====================
# SESSION REHYDRATION (Perbaikan: Logika Load)
# =====================
if "user" not in st.session_state:
    token = cookies.get("access_token")
    refresh = cookies.get("refresh_token")
    
    if token and refresh:
        try:
            # Set session ke client supabase
            auth_res = supabase.auth.set_session(token, refresh)
            user_res = supabase.auth.get_user()
            
            if user_res.user:
                st.session_state.user = user_res.user
                st.session_state.username = user_res.user.user_metadata.get("username") or user_res.user.email.split("@")[0]
                st.session_state.temp = 0.4
                st.rerun() # Refresh untuk masuk ke dashboard
        except:
            # Jika token expired, hapus cookie
            cookies.delete("access_token")
            cookies.delete("refresh_token")
            cookies.save()

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
    except: return ""

def load_user_chats(uid):
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", uid).order("last_updated", desc=True).execute()
        return {r["chat_id"]: r["messages"] for r in res.data}
    except: return {}

def save_chat(uid, cid, msgs, uname):
    try:
        supabase.table("chat_history").upsert({
            "user_id": uid, "chat_id": cid, "messages": msgs,
            "username": uname, "last_updated": datetime.datetime.utcnow().isoformat()
        }, on_conflict="user_id,chat_id").execute()
    except: pass

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
            stay_logged = st.checkbox("Stay Logged In", value=True)

            if st.form_submit_button("Login", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if res.session:
                        # SIMPAN KE COOKIE
                        cookies["access_token"] = res.session.access_token
                        cookies["refresh_token"] = res.session.refresh_token
                        cookies.save() # Trigger browser save

                        st.session_state.user = res.user
                        st.session_state.username = res.user.user_metadata.get("username") or email.split("@")[0]
                        st.session_state.temp = 0.4
                        st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_reg:
        with st.form("register"):
            reg_uname = st.text_input("Username")
            reg_email = st.text_input("Email")
            reg_pass = st.text_input("Password", type="password")
            if st.form_submit_button("Register", use_container_width=True):
                try:
                    supabase.auth.sign_up({"email": reg_email, "password": reg_pass, "options": {"data": {"username": reg_uname}}})
                    st.success("Registration successful! Please log in.")
                except Exception as e:
                    st.error(f"Error: {e}")
    st.stop()

# =====================
# MAIN DASHBOARD
# =====================
uid = st.session_state.user.id
username = st.session_state.username
db_history = load_user_chats(uid)

# Chat State Initialization
if "messages" not in st.session_state:
    if db_history:
        first_cid = next(iter(db_history))
        st.session_state.current_chat_id = first_cid
        st.session_state.messages = db_history[first_cid]
    else:
        st.session_state.current_chat_id = "Main Blueprint"
        st.session_state.messages = [{"role": "assistant", "content": "Architect ready. System online."}]

# =====================
# SIDEBAR
# =====================
with st.sidebar:
    st.title("The Blueprint")
    st.write(f"Logged as: **{username}**")
    
    if st.button("+ New Blueprint", use_container_width=True, type="primary"):
        st.session_state.current_chat_id = f"Blueprint {len(db_history)+1}"
        st.session_state.messages = [{"role": "assistant", "content": "Architect ready."}]
        st.rerun()

    st.divider()
    st.subheader("Archived")
    for cid in db_history:
        is_active = "» " if cid == st.session_state.get("current_chat_id") else ""
        if st.button(f"{is_active}{cid}", key=f"nav_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

    st.divider()
    st.session_state.temp = st.slider("Creativity", 0.0, 1.0, st.session_state.temp, 0.1)
    
    if st.button("Logout", type="secondary", use_container_width=True):
        supabase.auth.sign_out()
        cookies.delete("access_token")
        cookies.delete("refresh_token")
        cookies.save()
        st.session_state.clear()
        st.rerun()

# =====================
# CHAT UI
# =====================
st.caption(f"Active Session: {st.session_state.current_chat_id}")
for msg in st.session_state.messages:
    role = "Architect" if msg["role"] == "assistant" else username
    with st.chat_message(msg["role"]):
        st.write(f"**{role}**")
        st.write(msg["content"])

# =====================
# INPUT & AI
# =====================
if prompt := st.chat_input("Describe your blueprint...", accept_file=True):
    # Gabungkan teks dan file content
    file_content = ""
    for f in prompt.files:
        file_content += f"\n\n[Document: {f.name}]\n{read_document(f)}"
    
    full_prompt = prompt.text + file_content
    st.session_state.messages.append({"role": "user", "content": full_prompt})
    
    # Auto-rename chat if it's new
    if st.session_state.current_chat_id.startswith("Blueprint"):
        st.session_state.current_chat_id = prompt.text[:25] + "..." if len(prompt.text) > 25 else prompt.text

    # AI Response Logic
    TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    with st.chat_message("assistant"):
        st.write("**Architect**")
        response_placeholder = st.empty()
        full_response = ""
        
        try:
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "model": DEDICATED_MODEL,
                    "messages": [{"role": "system", "content": f"You are VibeCode Architect. Senior developer. Address user as {username}."}] + st.session_state.messages,
                    "temperature": st.session_state.temp,
                    "stream": True
                },
                stream=True
            )
            
            for line in r.iter_lines():
                if line:
                    decoded = line.decode()
                    if decoded.startswith("data: ") and "[DONE]" not in decoded:
                        token = json.loads(decoded[6:])["choices"][0]["delta"].get("content", "")
                        full_response += token
                        response_placeholder.markdown(full_response + "▌")
            
            response_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_chat(uid, st.session_state.current_chat_id, st.session_state.messages, username)
            st.rerun()
            
        except Exception as e:
            st.error(f"Link lost: {e}")