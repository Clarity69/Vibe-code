import streamlit as st
import time
import requests
import json
import os
import uuid
import datetime
import extra_streamlit_components as stx
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client

load_dotenv()

# --- 1. Konfigurasi Halaman ---
st.set_page_config(page_title="VibeCode AI", layout="wide")

USER_ICON = "👤" 
AI_ICON = "🤖"

# --- 2. Inisialisasi Database & Cookie ---
@st.cache_resource
def init_supabase():
    # Mengambil dari secrets (Streamlit Cloud) atau .env (Lokal)
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager()

# --- 3. Logika Identitas Otomatis (Fix Refresh) ---
if "user_uuid" not in st.session_state:
    # Jeda tipis agar browser sempat kirim cookie
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

# --- 4. Fungsi Helper Database ---
def save_chat_to_db(chat_id, messages):
    try:
        data = {
            "user_id": st.session_state.user_uuid,
            "chat_id": chat_id,
            "messages": messages
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        print(f"Gagal simpan DB: {e}")

def load_user_chats():
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).execute()
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
    except:
        return "[Gagal membaca dokumen]"

# --- 5. Inisialisasi State Chat (PENTING: Cegah NameError) ---
# Kita load history DULU sebelum masuk ke sidebar atau main logic
db_history = load_user_chats()

if "current_chat_id" not in st.session_state:
    if db_history:
        # Kembalikan ke chat terakhir yang ada di database
        st.session_state.current_chat_id = sorted(db_history.keys(), reverse=True)[0]
    else:
        st.session_state.current_chat_id = "Chat 1"

if "messages" not in st.session_state:
    # Ambil pesan dari DB, jika tidak ada pakai sapaan default
    st.session_state.messages = db_history.get(
        st.session_state.current_chat_id, 
        [{"role": "assistant", "content": "wassup folks!"}]
    )

# --- 6. Sidebar UI ---
with st.sidebar:
    st.title("VibeCode")
    st.caption(f"User ID: {st.session_state.user_uuid[:8]}...")
    
    if st.button("+ New Chat", use_container_width=True):
        new_chat_name = f"Chat {len(db_history) + 1}"
        st.session_state.current_chat_id = new_chat_name
        st.session_state.messages = [{"role": "assistant", "content": "Ada yang bisa dibantu?"}]
        st.rerun()

    st.write("### Chat History")
    for cid in sorted(db_history.keys(), reverse=True):
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()
    
    st.divider()
    selected_model = st.selectbox("Model", ["meta-llama/Llama-3.2-3B-Instruct","deepseek-ai/DeepSeek-R1"])
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 7. Tampilan Chat Utama ---
# Tampilkan riwayat chat yang aktif
for msg in st.session_state.messages:
    # Filter konten untuk menyembunyikan log dokumen yang panjang di UI
    display_content = msg["content"]
    if msg["role"] == "user" and "[Isi Dokumen:" in display_content:
        display_content = display_content.split("\n\n[Isi Dokumen:")[0] + " *(dengan dokumen)*"
    
    with st.chat_message(msg["role"], avatar=USER_ICON if msg["role"]=="user" else AI_ICON):
        st.markdown(display_content)

# Input Chat
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    uploaded_files = prompt.files if hasattr(prompt, 'files') else []
    
    file_context = ""
    for f in uploaded_files:
        content = read_document(f)
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{content}\n"

    final_prompt = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(user_text if not uploaded_files else f"{user_text} *(Mengunggah {len(uploaded_files)} file)*")

    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        # Ambil Token
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        payload = {
            "model": selected_model, 
            "messages": st.session_state.messages, 
            "temperature": temp, 
            "stream": True
        }

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
                            placeholder.markdown(full_response + "▌")
                        except: continue
            
            placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            # Simpan ke Supabase setelah AI selesai bicara
            save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
        except Exception as e:
            st.error(f"Koneksi AI terputus: {e}")