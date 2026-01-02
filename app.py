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
st.set_page_config(page_title="The Blueprint", layout="wide")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. INITIALIZE SUPABASE ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()

# --- 3. SESSION PERSISTENCE ---
# Memastikan sesi diambil secara benar dari Supabase Auth
if "user_data" not in st.session_state:
    try:
        # Cek apakah ada sesi aktif yang tersimpan di browser
        res = supabase.auth.get_session()
        if res and res.session:
            st.session_state.user_data = res.session.user
            # Ambil username dari metadata atau email
            st.session_state.username = res.session.user.user_metadata.get(
                "username", res.session.user.email.split('@')[0]
            )
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
    st.title("The Blueprint")
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

# FIX: Inisialisasi variabel state sebelum digunakan di sidebar
if "current_chat_id" not in st.session_state:
    if db_history:
        latest_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_id
        st.session_state.messages = db_history[latest_id]
    else:
        st.session_state.current_chat_id = "Main Blueprint"
        st.session_state.messages = [{"role": "assistant", "content": "Architect ready. System status: Online."}]

st.markdown("""
    <style>
        [data-testid="stSidebarNav"] {display: none;}
        .stButton button { border-radius: 4px; text-align: left; }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("The Blueprint")
    st.write(f"User: **{username}**")
    st.caption("● System Online")
    
    if st.button("+ New Blueprint", use_container_width=True, type="primary"):
        st.session_state.current_chat_id = f"Blueprint {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Architect ready. System status: Online."}]
        st.rerun()
    
    st.divider()
    
    st.subheader("Archive")
    history_container = st.container(height=350, border=False)
    with history_container:
        if not db_history:
            st.caption("No archived blueprints.")
        for cid in db_history.keys():
            # Gunakan .get() agar lebih aman dari AttributeError
            is_active = cid == st.session_state.get("current_chat_id")
            btn_label = f"» {cid}" if is_active else cid
            if st.button(btn_label, key=f"btn_{cid}", use_container_width=True):
                st.session_state.current_chat_id = cid
                st.session_state.messages = db_history[cid]
                st.rerun()

    st.divider()
    with st.expander("⚙️ System Control"):
        st.write("Model Settings")
        st.session_state.temp = st.slider("Creativity", 0.0, 1.0, st.session_state.temp, 0.1)
        
        st.divider()
        if st.button("Clear All Blueprints", use_container_width=True):
            try:
                supabase.table("chat_history").delete().eq("user_id", user_id).execute()
                # Reset state sepenuhnya setelah hapus data
                st.session_state.pop("messages", None)
                st.session_state.pop("current_chat_id", None)
                st.rerun()
            except:
                st.error("Error clearing data.")

        if st.button("Logout", use_container_width=True, type="primary"):
            supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()

# --- 7. CHAT DISPLAY ---
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

#if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    # Gunakan empty container untuk simulasi streaming tanpa avatar
    res_box = st.empty() 
    full_res = ""
    
    # Ambil token dari secrets atau env
    TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    
    # Header identitas asisten
    assistant_header = f"**:green[Architect]**: "
    
    sys_prompt = [{
        "role": "system", 
        "content": f"You are VibeCode Architect. Senior developer. Address user as {username}. Use markdown."
    }]
    
    try:
        resp = requests.post(
            "https://router.huggingface.co/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "model": DEDICATED_MODEL, 
                "messages": sys_prompt + st.session_state.messages, 
                "temperature": st.session_state.temp, 
                "stream": True
            },
            stream=True
        )
        
        # Proses chunk data streaming
        for line in resp.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith("data: ") and "[DONE]" not in decoded:
                    try:
                        # Parsing JSON dari stream HuggingFace
                        chunk = json.loads(decoded[6:])
                        token = chunk["choices"][0]["delta"].get("content", "")
                        full_res += token
                        # Update tampilan secara real-time dengan cursor
                        res_box.markdown(f"{assistant_header}{full_res}▌")
                    except:
                        continue
        
        # Tampilan final tanpa cursor
        res_box.markdown(f"{assistant_header}{full_res}")
        
        # Simpan ke session state dan database
        st.session_state.messages.append({"role": "assistant", "content": full_res})
        save_chat_to_db(
            st.session_state.user_data.id, 
            st.session_state.current_chat_id, 
            st.session_state.messages, 
            username
        )
        
        # Rerun untuk memastikan UI sinkron dengan state terbaru
        st.rerun()
        
    except Exception as e:
        st.error(f"Architect link lost: {e}")