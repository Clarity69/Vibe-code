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

# Model khusus coding dari Qwen
DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. Inisialisasi DB & Cookie ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()
cookie_manager = stx.CookieManager()

# --- 3. Fungsi Helper & Dokumen ---
def read_document(file):
    try:
        name = file.name.lower()
        if name.endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except Exception as e:
        return f"\n[Error reading {file.name}: {e}]\n"

def save_chat_to_db(chat_id, messages):
    try:
        data = {
            "user_id": st.session_state.user_uuid, 
            "chat_id": chat_id, 
            "messages": messages,
            "last_updated": datetime.datetime.now().isoformat()
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except: pass

def load_user_chats():
    try:
        # Order by last_updated agar yang terbaru muncul di atas
        res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).order("last_updated", desc=True).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except: return {}

# --- 4. Logika Identitas (Cookie Sync) ---
if "user_uuid" not in st.session_state:
    time.sleep(0.5) # Jeda handshake cookie
    saved_uuid = cookie_manager.get("vibecode_user_id")
    if saved_uuid:
        st.session_state.user_uuid = saved_uuid
    else:
        new_id = str(uuid.uuid4())
        st.session_state.user_uuid = new_id
        cookie_manager.set("vibecode_user_id", new_id, expires_at=datetime.datetime.now() + datetime.timedelta(days=30))
        st.rerun()

# --- 5. Sinkronisasi Data ---
db_history = load_user_chats()

if "messages" not in st.session_state:
    if db_history:
        # Load chat terakhir jika ada history
        latest_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_id
        st.session_state.messages = db_history[latest_id]
    else:
        st.session_state.current_chat_id = "Chat 1"
        st.session_state.messages = [{"role": "assistant", "content": "VibeCode AI ready. Send me code or files!"}]

# --- 6. Sidebar ---
with st.sidebar:
    st.title("VibeCode AI")
    st.caption(f"User: {st.session_state.user_uuid[:8]}")
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "New session. What's the vibe today?"}]
        st.rerun()

    st.write("### History")
    for cid in db_history.keys():
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

# --- 7. Main UI ---
st.subheader(f"Current: {st.session_state.current_chat_id}")

# Display Chat
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="👤" if msg["role"]=="user" else "🤖"):
        content = msg["content"]
        # Sembunyikan isi dokumen yang panjang di UI agar bersih
        if msg["role"] == "user" and "[Isi Dokumen:" in content:
            clean_content = content.split("\n\n[Isi Dokumen:")[0] + " 📄 *(Attached Files)*"
            st.markdown(clean_content)
        else:
            st.markdown(content)

# Input Chat
if prompt_data := st.chat_input("Ask or drop files...", accept_file=True):
    user_text = prompt_data.text
    uploaded_files = prompt_data.files
    
    # Process Files
    file_context = ""
    for f in uploaded_files:
        file_context += f"\n\n[Isi Dokumen: {f.name}]\n{read_document(f)}\n"
    
    final_prompt = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    # Simpan judul chat otomatis dari prompt pertama
    if st.session_state.current_chat_id.startswith("Chat ") and len(user_text) > 0:
        st.session_state.current_chat_id = (user_text[:25] + '...') if len(user_text) > 25 else user_text

    st.rerun()

# Logic Generating Response
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    with st.chat_message("assistant", avatar="🤖"):
        res_box = st.empty()
        full_response = ""
        
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        
        # System prompt agar Qwen selalu pakai Markdown Code Blocks (Fitur Copy Code)
        messages = [
            {"role": "system", "content": "You are VibeCode AI. Expert in coding. Always wrap code snippets in markdown code blocks with the correct language tag for easy copying."}
        ] + st.session_state.messages

        try:
            resp = requests.post("https://router.huggingface.co/v1/chat/completions", 
                                 headers=HEADERS, 
                                 json={"model": DEDICATED_MODEL, "messages": messages, "temperature": 0.3, "stream": True}, 
                                 stream=True)
            
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
            save_chat_to_db(st.session_state.current_chat_id, st.session_state.messages)
            st.rerun() # Rerun untuk memastikan history sidebar terupdate
        except Exception as e:
            st.error(f"Error: {e}")