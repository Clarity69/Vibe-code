import streamlit as st
import requests
import json
import os
import uuid
import bcrypt
import datetime
import extra_streamlit_components as stx
import time
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client

load_dotenv()

# --- 1. Konfigurasi Halaman & UI ---
st.set_page_config(page_title="VibeCode", layout="wide")

USER_ICON = "👤" 
AI_ICON = "🤖"

st.markdown("""
    <style>
    div[data-baseweb="slider"] > div:first-child > div:first-child {
        background: linear-gradient(to right, rgb(255, 75, 75) 0%, rgb(255, 75, 75) var(--slider-value), rgba(151, 166, 195, 0.25) var(--slider-value));
    }
    span[data-baseweb="slider-thumb"] { background-color: #ff4b4b; border: 2px solid #ff4b4b; }
    [data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# --- 2. Inisialisasi Database & Cookie ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager() # Inisialisasi langsung
# --- 3. Fungsi Keamanan (Auth) ---
def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def login_user(user, pwd):
    res = supabase.table("users").select("*").eq("username", user).execute()
    if len(res.data) > 0:
        if check_password(pwd, res.data[0]['password']):
            return True
    return False

def register_user(user, pwd):
    hashed = hash_password(pwd)
    try:
        supabase.table("users").insert({"username": user, "password": hashed}).execute()
        return True
    except:
        return False

# --- 4. Fungsi Database Chat ---
def save_chat_to_db(chat_id, messages):
    data = {
        "user_id": st.session_state.username, # Menggunakan username sebagai kunci
        "chat_id": chat_id,
        "messages": messages
    }
    try:
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        st.warning(f"Gagal simpan cloud: {e}")

def load_user_chats():
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.username).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except:
        return {}

def read_document(file):
    name = file.name.lower()
    try:
        if name.endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except Exception as e:
        return f"[Error membaca file: {e}]"

# --- 5. Logika Stay Logged In (Ditingkatkan dengan Jeda Waktu) ---
if "logged_in" not in st.session_state:
    # Berikan jeda 0.5 - 1 detik agar CookieManager sempat membaca data dari browser
    time.sleep(0.6) 
    
    saved_user = cookie_manager.get("vibecode_user")
    
    if saved_user:
        st.session_state.logged_in = True
        st.session_state.username = saved_user
    else:
        st.session_state.logged_in = False

# --- 6. Tampilan Login/Register ---
if not st.session_state.logged_in:
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        st.title("VibeCode AI")
        tab1, tab2 = st.tabs(["Masuk", "Daftar Akun"])
        
        with tab1:
            u_log = st.text_input("Username", key="u_log")
            p_log = st.text_input("Password", type="password", key="p_log")
            if st.button("Login", use_container_width=True):
                if login_user(u_log, p_log):
                    st.session_state.logged_in = True
                    st.session_state.username = u_log
                    cookie_manager.set("vibecode_user", u_log, 
                                     expires_at=datetime.datetime.now() + datetime.timedelta(days=7))
                    st.rerun()
                else:
                    st.error("Gagal Masuk. Cek kembali username/password.")
        
        with tab2:
            u_reg = st.text_input("Buat Username", key="u_reg")
            p_reg = st.text_input("Buat Password", type="password", key="p_reg")
            if st.button("Daftar Sekarang", use_container_width=True):
                if register_user(u_reg, p_reg):
                    st.success("Akun dibuat! Silakan login di tab sebelah.")
                else:
                    st.error("Username sudah terdaftar.")
    st.stop()

# --- 7. Sidebar (Setelah Login) ---
with st.sidebar:
    st.title("VibeCode")
    st.write(f"Logged as: **{st.session_state.username}**")
    
    if st.button("Logout", use_container_width=True):
        cookie_manager.delete("vibecode_user")
        st.session_state.logged_in = False
        st.rerun()
    
    st.divider()
    db_history = load_user_chats()
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": f"Halo {st.session_state.username}! Ada yang bisa saya bantu?"}]
        st.rerun()

    st.write("### Chat History")
    for cid in sorted(db_history.keys(), reverse=True):
        if st.button(cid, key=cid, use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()
    
    st.markdown("<br>" * 5, unsafe_allow_html=True)
    st.divider()
    selected_model = st.selectbox("Model", ["deepseek-ai/DeepSeek-R1","meta-llama/Llama-3.2-3B-Instruct"])
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 8. Main Chat Logic ---
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "Chat 1"

if "messages" not in st.session_state:
    st.session_state.messages = db_history.get(st.session_state.current_chat_id, [
        {"role": "assistant", "content": f"Halo {st.session_state.username}! Ada yang bisa saya bantu?"}
    ])

for msg in st.session_state.messages:
    display_content = msg["content"]
    if msg["role"] == "user" and "[Isi Dokumen:" in display_content:
        display_content = display_content.split("\n\n[Isi Dokumen:")[0] + " *(dengan lampiran dokumen)*"
        
    with st.chat_message(msg["role"], avatar=USER_ICON if msg["role"]=="user" else AI_ICON):
        st.markdown(display_content)

if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []

    file_context = ""
    for f in files:
        content = read_document(f)
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{content}\n"

    final_prompt = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(user_text if not files else f"{user_text} *(Mengunggah {len(files)} file)*")

    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        TOKEN = os.getenv("HF_TOKEN") or (st.secrets["HF_TOKEN"] if "HF_TOKEN" in st.secrets else None)
        
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        payload = {"model": selected_model, "messages": st.session_state.messages, "temperature": temp, "stream": True}

        try:
            resp = requests.post("https://router.huggingface.co/v1/chat/completions", headers=HEADERS, json=payload, stream=True)
            for line in resp.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        if data_str.strip() == "[DONE]": break
                        try:
                            token = json.loads(data_str)["choices"][0].get("delta", {}).get("content", "")
                            full_response += token
                            placeholder.markdown(full_response + "▌")
                        except: continue 
            
            placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
            
        except Exception as e:
            st.error(f"Terjadi kesalahan: {e}")