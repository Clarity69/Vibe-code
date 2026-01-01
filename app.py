import streamlit as st
import time
import requests
import json
import os
import uuid
import datetime
import re
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="VibeCode AI", layout="wide", page_icon="🚀")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. INITIALIZE SUPABASE ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()

# --- 3. HELPER FUNCTIONS ---
def read_document(file):
    try:
        name = file.name.lower()
        if name.endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except Exception as e:
        return f"\n[Error membaca file {file.name}: {e}]\n"

def load_user_chats(user_id):
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", user_id).order("last_updated", desc=True).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except:
        return {}

def save_chat_to_db(user_id, chat_id, messages):
    try:
        data = {
            "user_id": user_id, 
            "chat_id": chat_id, 
            "messages": messages,
            "last_updated": datetime.datetime.now().isoformat()
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        st.error(f"Gagal simpan cloud: {e}")

# --- 4. AUTH LOGIC ---
if "user_data" not in st.session_state:
    st.title("🚀 VibeCode AI")
    st.info("Satu akun untuk semua kodinganmu. Masuk atau Daftar dulu!")
    
    tab_login, tab_reg = st.tabs(["Login", "Daftar Baru"])
    
    with tab_login:
        with st.form("form_login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            btn_login = st.form_submit_button("Masuk", use_container_width=True)
            if btn_login:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user_data = res.user
                    st.success("Berhasil masuk!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal login: {e}")

    with tab_reg:
        with st.form("form_reg"):
            email_r = st.text_input("Email Baru")
            pass_r = st.text_input("Password Baru (Min 6 karakter)", type="password")
            btn_reg = st.form_submit_button("Daftar Sekarang", use_container_width=True)
            if btn_reg:
                try:
                    supabase.auth.sign_up({"email": email_r, "password": pass_r})
                    st.success("Berhasil daftar! Silahkan coba Login.")
                except Exception as e:
                    st.error(f"Gagal daftar: {e}")
    st.stop()

# --- 5. CHAT SYSTEM (Jika sudah login) ---
user_id = st.session_state.user_data.id
db_history = load_user_chats(user_id)

# Inisialisasi State Chat
if "messages" not in st.session_state:
    if db_history:
        # Load chat terakhir yang pernah dibuka
        latest_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_id
        st.session_state.messages = db_history[latest_id]
    else:
        st.session_state.current_chat_id = "Chat 1"
        st.session_state.messages = [{"role": "assistant", "content": f"Halo {st.session_state.user_data.email}! Mau bikin kode apa hari ini?"}]

# --- 6. SIDEBAR (History & Logout) ---
with st.sidebar:
    st.title("VibeCode AI")
    st.write(f"👤 {st.session_state.user_data.email}")
    
    if st.button("Logout", type="secondary", use_container_width=True):
        supabase.auth.sign_out()
        del st.session_state.user_data
        st.rerun()
        
    st.divider()
    if st.button("+ New Chat", use_container_width=True, type="primary"):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Chat baru dimulai. Kirim kode atau file!"}]
        st.rerun()

    st.write("### Riwayat Chat")
    for cid in db_history.keys():
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

# --- 7. MAIN UI CHAT ---
st.subheader(f"📂 {st.session_state.current_chat_id}")

# Display messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="👤" if msg["role"]=="user" else "🤖"):
        content = msg["content"]
        # Membersihkan tampilan UI dari isi dokumen yang panjang
        if msg["role"] == "user" and "[Isi Dokumen:" in content:
            display_text = content.split("\n\n[Isi Dokumen:")[0] + " 📄 *(File terlampir)*"
            st.markdown(display_text)
        else:
            st.markdown(content)

# Input dengan Upload File
if prompt_data := st.chat_input("Tanya sesuatu atau lampirkan file...", accept_file=True):
    user_text = prompt_data.text
    uploaded_files = prompt_data.files
    
    # Baca konten file jika ada
    file_context = ""
    for f in uploaded_files:
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{read_document(f)}\n"
    
    final_prompt = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    # Beri judul otomatis jika masih "Chat X"
    if st.session_state.current_chat_id.startswith("Chat ") and user_text:
        st.session_state.current_chat_id = (user_text[:30] + '...') if len(user_text) > 30 else user_text
    
    st.rerun()

# Logika Respon AI
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    with st.chat_message("assistant", avatar="🤖"):
        res_box = st.empty()
        full_response = ""
        
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        
        # System prompt agar AI selalu disiplin pakai Markdown (fitur copy code)
        messages_to_send = [
            {"role": "system", "content": "You are VibeCode AI. Always use markdown for code blocks. Be concise and helpful."}
        ] + st.session_state.messages
        
        try:
            resp = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers=HEADERS,
                json={"model": DEDICATED_MODEL, "messages": messages_to_send, "temperature": 0.3, "stream": True},
                stream=True
            )
            
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
            # Simpan ke DB Cloud
            save_chat_to_db(user_id, st.session_state.current_chat_id, st.session_state.messages)
            st.rerun()
            
        except Exception as e:
            st.error(f"Koneksi terputus: {e}")