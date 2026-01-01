import streamlit as st
import time
import requests
import json
import os
import uuid
import datetime
import re
import extra_streamlit_components as stx
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client

load_dotenv()

# --- 1. Konfigurasi Halaman ---
st.set_page_config(page_title="VibeCode AI", layout="wide")

# MODEL DEDIKASI
DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. Inisialisasi DB & Cookie ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager()

# --- 3. Logika Identitas Otomatis ---
if "user_uuid" not in st.session_state:
    time.sleep(0.6)
    saved_uuid = cookie_manager.get("vibecode_user_id")
    
    if saved_uuid:
        st.session_state.user_uuid = saved_uuid
    else:
        new_id = str(uuid.uuid4())
        st.session_state.user_uuid = new_id
        cookie_manager.set("vibecode_user_id", new_id, 
                           expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
        st.rerun()

# --- 4. Fungsi Database & Dokumen ---
def save_chat_to_db(chat_id, messages):
    try:
        data = {"user_id": st.session_state.user_uuid, "chat_id": chat_id, "messages": messages}
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except: pass

def load_user_chats():
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except: return {}

# --- 5. Inisialisasi State Chat ---
db_history = load_user_chats()

if "current_chat_id" not in st.session_state:
    if db_history:
        st.session_state.current_chat_id = sorted(db_history.keys(), reverse=True)[0]
    else:
        st.session_state.current_chat_id = "Chat 1"

if "messages" not in st.session_state:
    st.session_state.messages = db_history.get(st.session_state.current_chat_id, [
        {"role": "assistant", "content": "Wassup! Judge siap memberikan keputusan."}
    ])

# --- 6. Sidebar ---
with st.sidebar:
    st.title("VibeCode")
    st.caption(f"Model: {DEDICATED_MODEL.split('/')[-1]}")
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Ada yang bisa saya bantu?"}]
        st.rerun()

    st.write("### Riwayat")
    for cid in sorted(db_history.keys(), reverse=True):
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

# --- 7. Main Chat Display (Tanpa Avatar) ---
chat_placeholder = st.container()

with chat_placeholder:
    for msg in st.session_state.messages:
        content = msg["content"]
        if msg["role"] == "user":
            # Filter tampilan dokumen di chat
            if "[Isi Dokumen:" in content:
                content = content.split("\n\n[Isi Dokumen:")[0] + " *(dengan dokumen)*"
            st.markdown(f"**YOU:** {content}")
        else:
            st.markdown(f"**Judge:** {content}")
        st.write("") # Memberi jarak antar pesan

# Input Chat
if prompt := st.chat_input("Input Here..."):
    # Tampilkan input user secara instan
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun() # Rerun agar pesan YOU muncul sebelum Judge mulai mengetik

# Logika Respon Judge (Jika pesan terakhir dari User)
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    full_response = ""
    # Header Judge untuk streaming
    st.write("**Judge:**")
    res_box = st.empty()
    
    TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    HEADERS = {"Authorization": f"Bearer {TOKEN}"}
    payload = {"model": DEDICATED_MODEL, "messages": st.session_state.messages, "temperature": 0.4, "stream": True}

    try:
        resp = requests.post("https://router.huggingface.co/v1/chat/completions", headers=HEADERS, json=payload, stream=True)
        for line in resp.iter_lines():
            if line:
                line_text = line.decode('utf-8')
                if line_text.startswith("data: "):
                    data_str = line_text[6:]
                    if data_str.strip() == "[DONE]": break
                    try:
                        token = json.loads(data_str)["choices"][0]["delta"].get("content", "")
                        full_response += token
                        
                        # Bersihkan tag think secara real-time
                        clean_view = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL)
                        clean_view = re.sub(r'<think>.*', '', clean_view, flags=re.DOTALL)
                        res_box.markdown(clean_view + "▌")
                    except: continue
        
        final_clean = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL)
        res_box.markdown(final_clean)
        
        # Simpan ke state dan DB
        st.session_state.messages.append({"role": "assistant", "content": final_clean})
        save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
        st.rerun() # Sinkronisasi tampilan akhir
        
    except Exception as e:
        st.error(f"Error: {e}")