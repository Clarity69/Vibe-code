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
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager()

# --- 3. Logika Identitas (Cookie) ---
if "user_uuid" not in st.session_state:
    time.sleep(0.6) # Jeda untuk sinkronisasi cookie
    saved_uuid = cookie_manager.get("vibecode_user_id")
    
    if saved_uuid:
        st.session_state.user_uuid = saved_uuid
    else:
        new_id = str(uuid.uuid4())
        st.session_state.user_uuid = new_id
        cookie_manager.set("vibecode_user_id", new_id, 
                           expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
        st.rerun()

# --- 4. Fungsi Helper ---
def save_chat_to_db(chat_id, messages):
    try:
        data = {"user_id": st.session_state.user_uuid, "chat_id": chat_id, "messages": messages}
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        print(f"Error DB: {e}")

def load_user_chats():
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except:
        return {}

def read_document(file):
    try:
        if file.name.lower().endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif file.name.lower().endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except:
        return "[Error membaca dokumen]"

# --- 5. Inisialisasi State Chat ---
db_history = load_user_chats()

if "current_chat_id" not in st.session_state:
    if db_history:
        st.session_state.current_chat_id = sorted(db_history.keys(), reverse=True)[0]
    else:
        st.session_state.current_chat_id = "Chat 1"

if "messages" not in st.session_state:
    st.session_state.messages = db_history.get(
        st.session_state.current_chat_id, 
        [{"role": "assistant", "content": "wassup folks!"}]
    )

# --- 6. Sidebar UI ---
with st.sidebar:
    st.title("VibeCode")
    st.caption(f"ID: {st.session_state.user_uuid[:8]}")
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Ada yang bisa dibantu?"}]
        st.rerun()

    st.write("### Riwayat Chat")
    for cid in sorted(db_history.keys(), reverse=True):
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()
    
    st.divider()
    selected_model = st.selectbox("Model", ["meta-llama/Llama-3.2-3B-Instruct","deepseek-ai/DeepSeek-R1"])
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 7. Main Chat Display & Logic ---

# A. Tampilkan chat yang sudah ada (Agar tidak menghilang)
for msg in st.session_state.messages:
    display_content = msg["content"]
    # Sembunyikan teks dokumen yang panjang dari tampilan bubble
    if msg["role"] == "user" and "[Isi Dokumen:" in display_content:
        display_content = display_content.split("\n\n[Isi Dokumen:")[0] + " *(dengan lampiran)*"
    
    with st.chat_message(msg["role"], avatar=USER_ICON if msg["role"]=="user" else AI_ICON):
        st.markdown(display_content)

# B. Input Chat
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []
    
    # Proses dokumen
    file_context = ""
    for f in files:
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{read_document(f)}\n"
    
    # Simpan pesan user
    full_user_input = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": full_user_input})
    
    # Tampilkan bubble user secara instan
    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(user_text if not files else f"{user_text} *(Mengunggah {len(files)} file)*")

    # Generate Respon AI
    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        
        # Kirim riwayat ke API (tanpa modifikasi agar model tetap punya konteks)
        payload = {
            "model": selected_model, 
            "messages": st.session_state.messages, 
            "temperature": temp, 
            "stream": True
        }

        try:
            resp = requests.post("https://router.huggingface.co/v1/chat/completions", headers=HEADERS, json=payload, stream=True)
            
            if resp.status_code == 200:
                for line in resp.iter_lines():
                    if line:
                        line_text = line.decode('utf-8')
                        if line_text.startswith("data: "):
                            data_str = line_text[6:]
                            if data_str.strip() == "[DONE]": break
                            try:
                                chunk = json.loads(data_str)
                                token = chunk["choices"][0]["delta"].get("content", "")
                                full_response += token
                                placeholder.markdown(full_response + "▌")
                            except: continue
                
                placeholder.markdown(full_response)
                # Simpan jawaban ke state dan Database
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
            else:
                st.error(f"API Error: {resp.status_code}")
        except Exception as e:
            st.error(f"Koneksi terputus: {e}")
    
    # Penting: Jangan gunakan rerun di sini agar bubble tidak berkedip/hilang saat proses streaming