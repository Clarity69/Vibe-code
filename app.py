import streamlit as st
import time
import requests
import json
import os
import datetime
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="VibeCode Architect", layout="wide")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. INITIALIZE SUPABASE ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()

# --- 3. SESSION PERSISTENCE ---
if "user_data" not in st.session_state:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.user_data = session.user
            st.session_state.username = session.user.user_metadata.get("username", session.user.email.split('@')[0])
    except:
        pass

# --- 4. HELPERS ---
def read_document(file):
    try:
        name = file.name.lower()
        if name.endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except Exception as e:
        return f"\n[Error reading file {file.name}: {e}]\n"

def load_user_chats(user_id):
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", user_id).order("last_updated", desc=True).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except:
        return {}

def save_chat_to_db(user_id, chat_id, messages, username):
    try:
        data = {
            "user_id": user_id, 
            "chat_id": chat_id, 
            "messages": messages,
            "username": username,
            "last_updated": datetime.datetime.now().isoformat()
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except:
        pass

# --- 5. AUTHENTICATION UI ---
if "user_data" not in st.session_state:
    st.title("VibeCode Architect")
    tab_login, tab_reg = st.tabs(["Login", "Register"])
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user_data = res.user
                    st.session_state.username = res.user.user_metadata.get("username", email.split('@')[0])
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")
    with tab_reg:
        with st.form("register_form"):
            u_name = st.text_input("Username")
            email_r = st.text_input("Email")
            pass_r = st.text_input("Password", type="password")
            if st.form_submit_button("Register", use_container_width=True):
                try:
                    supabase.auth.sign_up({"email": email_r, "password": pass_r, "options": {"data": {"username": u_name}}})
                    st.success("Success! Please Login.")
                except Exception as e:
                    st.error(f"Failed: {e}")
    st.stop()

# --- 6. SIDEBAR REORGANIZATION ---
user_id = st.session_state.user_data.id
username = st.session_state.username
db_history = load_user_chats(user_id)

with st.sidebar:
    # TOP SECTION
    st.title("VibeCode")
    st.write(f"User: **{username}**")
    st.divider()
    
    if st.button("+ New Blueprint", use_container_width=True):
        st.session_state.current_chat_id = f"Blueprint {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "New architectural session started."}]
        st.rerun()
    
    st.write("### History")
    for cid in db_history.keys():
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

    # PUSH CONTENT TO BOTTOM
    # This creates flexible space
    for _ in range(15): st.write("") 
    
    st.divider()
    # BOTTOM SECTION (Gear Icon / Settings)
    with st.expander("⚙️ Settings"):
        # Theme toggle (Streamlit's internal theme is handled by user, 
        # but we can add a visual indicator or extra settings here)
        st.info("Theme follows system/browser settings.")
        
        if st.button("Logout", use_container_width=True, type="primary"):
            supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()

# --- 7. CHAT LOGIC ---
if "messages" not in st.session_state:
    if db_history:
        latest_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_id
        st.session_state.messages = db_history[latest_id]
    else:
        st.session_state.current_chat_id = "Main Blueprint"
        st.session_state.messages = [{"role": "assistant", "content": "Architect ready. System status: Online."}]

st.caption(f"Project Session: {st.session_state.current_chat_id}")

for msg in st.session_state.messages:
    if msg["role"] == "user":
        content = msg["content"]
        if "[Document Content:" in content:
            content = content.split("\n\n[Document Content:")[0] + " (Files attached)"
        st.markdown(f"**:blue[{username}]**: {content}")
    else:
        st.markdown(f"**:green[Architect]**: {msg['content']}")
    st.write("") 

if prompt_data := st.chat_input("Input system requirements...", accept_file=True):
    user_text = prompt_data.text
    file_ctx = "".join([f"\n\n[Document Content: {f.name}]\n{read_document(f)}\n" for f in prompt_data.files])
    st.session_state.messages.append({"role": "user", "content": user_text + file_ctx})
    if st.session_state.current_chat_id.startswith("Blueprint") or st.session_state.current_chat_id == "Main Blueprint":
        st.session_state.current_chat_id = (user_text[:30] + '...') if len(user_text) > 30 else user_text
    st.rerun()

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    with st.chat_message("assistant", avatar=None):
        res_box = st.empty()
        full_res = ""
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        sys_prompt = [{"role": "system", "content": f"You are VibeCode Architect. Senior developer. Address user as {username}. Use markdown."}]
        try:
            resp = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"model": DEDICATED_MODEL, "messages": sys_prompt + st.session_state.messages, "temperature": 0.4, "stream": True},
                stream=True
            )
            for line in resp.iter_lines():
                if line:
                    data = line.decode('utf-8')
                    if data.startswith("data: ") and "[DONE]" not in data:
                        token = json.loads(data[6:])["choices"][0]["delta"].get("content", "")
                        full_res += token
                        res_box.markdown(f"**:green[Architect]**: {full_res}▌")
            res_box.markdown(f"**:green[Architect]**: {full_res}")
            st.session_state.messages.append({"role": "assistant", "content": full_res})
            save_chat_to_db(user_id, st.session_state.current_chat_id, st.session_state.messages, username)
            st.rerun()
        except:
            st.error("Connection error.")