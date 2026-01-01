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
# Streamlit secara default sudah mendukung copy code pada blok markdown ``` 
st.set_page_config(page_title="VibeCode AI", layout="wide")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. Inisialisasi DB & Cookie ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager()

# --- 3. Logika Identitas & Sinkronisasi History ---
# Kita butuh variabel penanda agar loading data hanya terjadi sekali saat refresh
if "data_fetched" not in st.session_state:
    st.session_state.data_fetched = False

if "user_uuid" not in st.session_state:
    # Beri waktu sebentar untuk membaca cookie
    time.sleep(0.5) 
    saved_uuid = cookie_manager.get("vibecode_user_id")
    if saved_uuid:
        st.session_state.user_uuid = saved_uuid
    else:
        new_id = str(uuid.uuid4())
        st.session_state.user_uuid = new_id
        cookie_manager.set("vibecode_user_id", new_id, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
        st.rerun()

# --- 4. Fungsi Database (Fixed) ---
def load_user_chats():
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).execute()
        # Mengembalikan list chat diurutkan berdasarkan update terbaru
        return {item['chat_id']: item['messages'] for item in res.data}
    except Exception as e:
        print(f"Error load DB: {e}")
        return {}

def save_chat_to_db(chat_id, messages):
    try:
        data = {
            "user_id": st.session_state.user_uuid, 
            "chat_id": chat_id, 
            "messages": messages,
            "last_updated": datetime.datetime.now().isoformat()
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        st.error(f"Gagal save ke Cloud: {e}")

# --- 5. Initial Load (Kunci agar history muncul balik) ---
db_history = load_user_chats()

if not st.session_state.data_fetched:
    if db_history:
        # Ambil chat terakhir yang ada di database
        latest_chat_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_chat_id
        st.session_state.messages = db_history[latest_chat_id]
    st.session_state.data_fetched = True

if "messages" not in st.session_state:
    st.session_state.current_chat_id = "Chat 1"
    st.session_state.messages = [{"role": "assistant", "content": "VibeCode AI ready. What are we building?"}]

# --- 6. Sidebar UI ---
with st.sidebar:
    st.title("🚀 VibeCode")
    st.caption(f"ID: {st.session_state.user_uuid[:8]}")
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "New session started!"}]
        st.rerun()

    st.write("---")
    st.write("### Recent Vibe")
    for cid in db_history.keys():
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

# --- 7. Chat Display ---
# Streamlit secara otomatis memberikan tombol "Copy" pada blok kode (```)
for msg in st.session_state.messages:
    role = "user" if msg["role"] == "user" else "assistant"
    avatar = "👤" if msg["role"] == "user" else "🤖"
    with st.chat_message(role, avatar=avatar):
        # Menampilkan isi chat (Markdown sudah include syntax highlighting & copy button)
        content = msg["content"]
        if msg["role"] == "user" and "[Isi Dokumen:" in content:
             content = content.split("\n\n[Isi Dokumen:")[0] + " 📄 *(Document attached)*"
        st.markdown(content)

# --- 8. Input Logic ---
if prompt_data := st.chat_input("Ask anything..."):
    user_text = prompt_data # Versi standar chat_input
    
    # Tambahkan ke session
    st.session_state.messages.append({"role": "user", "content": user_text})
    
    # Tampilkan langsung ke UI
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_text)

    # Generate Response
    with st.chat_message("assistant", avatar="🤖"):
        res_box = st.empty()
        full_response = ""
        
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        # Tambahkan system prompt agar AI selalu menggunakan markdown block untuk kode
        messages_with_system = [
            {"role": "system", "content": "You are VibeCode AI. Always use markdown code blocks for code snippets to allow users to copy them easily."}
        ] + st.session_state.messages
        
        payload = {"model": DEDICATED_MODEL, "messages": messages_with_system, "temperature": 0.3, "stream": True}

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
                            res_box.markdown(full_response + "▌")
                        except: continue
            
            res_box.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
            # SIMPAN KE DATABASE SETIAP KALI CHAT SELESAI
            save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
            
        except Exception as e:
            st.error(f"Connection Lost: {e}")