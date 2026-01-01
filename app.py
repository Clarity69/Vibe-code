import streamlit as st
import requests
import json
import os
import uuid
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

# --- 2. Inisialisasi Database & Privasi ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# Membuat User ID unik agar chat tidak bertabrakan dengan orang lain
if "user_uuid" not in st.session_state:
    st.session_state.user_uuid = str(uuid.uuid4())

# --- 3. Fungsi Database & Dokumen ---
def save_chat_to_db(chat_id, messages):
    data = {
        "user_id": st.session_state.user_uuid,
        "chat_id": chat_id,
        "messages": messages
    }
    try:
        # Menambahkan on_conflict agar sesuai dengan unique constraint (user_id, chat_id)
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except Exception as e:
        st.warning(f"Catatan: Riwayat gagal disimpan ke cloud ({e}). Namun chat tetap berjalan.")

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
    except Exception as e:
        return f"[Error membaca file: {e}]"

# --- 4. Sidebar Riwayat Chat ---
with st.sidebar:
    st.title("VibeCode")
    
    # Load riwayat dari DB
    db_history = load_user_chats()
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Halo! I'm **VibeCode AI**. what can i help ya?"}]
        st.rerun()

    st.write("### Chat History")
    for cid in sorted(db_history.keys()):
        if st.button(cid, key=cid, use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    selected_model = st.selectbox("Model", ["meta-llama/Llama-3.2-3B-Instruct", "deepseek-ai/DeepSeek-R1"])
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 5. State Management ---
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "Chat 1"

if "messages" not in st.session_state:
    # Ambil dari DB jika ada, jika tidak pakai Welcome Message
    st.session_state.messages = db_history.get(st.session_state.current_chat_id, [
        {"role": "assistant", "content": "Halo! I'm **VibeCode AI**. what can i help ya?"}
    ])

# Tampilkan Chat
for msg in st.session_state.messages:
    # Filter agar isi file yang sangat panjang tidak memenuhi tampilan chat history jika tidak perlu
    display_content = msg["content"]
    if msg["role"] == "user" and "[Isi Dokumen:" in display_content:
        display_content = display_content.split("\n\n[Isi Dokumen:")[0] + " *(dengan lampiran dokumen)*"
        
    with st.chat_message(msg["role"], avatar=USER_ICON if msg["role"]=="user" else AI_ICON):
        st.markdown(display_content)

# --- 6. Chat Input Logic ---
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []

    file_context = ""
    for f in files:
        content = read_document(f)
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{content}\n"

    final_prompt = user_text + file_context
    
    # Simpan pesan user
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(user_text if not files else f"{user_text} *(Mengunggah {len(files)} file)*")

    # --- 7. AI Generation ---
    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        TOKEN = os.getenv("HF_TOKEN") or (st.secrets["HF_TOKEN"] if "HF_TOKEN" in st.secrets else None)
        if not TOKEN:
            st.error("Token tidak ditemukan!")
            st.stop()

        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        
        payload = {"model": selected_model, "messages": st.session_state.messages, "temperature": temp, "stream": True}

        try:
            resp = requests.post(API_URL, headers=HEADERS, json=payload, stream=True)
            
            if resp.status_code != 200:
                st.error(f"API Error ({resp.status_code}): {resp.text}")
                st.stop()

            for line in resp.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        if data_str.strip() == "[DONE]": break
                        
                        try:
                            data_json = json.loads(data_str)
                            if "choices" in data_json and len(data_json["choices"]) > 0:
                                delta = data_json["choices"][0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    full_response += token
                                    placeholder.markdown(full_response + "▌")
                        except:
                            continue 
            
            if full_response:
                placeholder.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                # SIMPAN KE DATABASE SETELAH CHAT LENGKAP
                save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
            else:
                st.warning("AI tidak memberikan jawaban.")
            
        except Exception as e:
            st.error(f"Terjadi kesalahan: {e}")