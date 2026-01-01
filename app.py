import streamlit as st
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# --- 1. Konfigurasi Halaman & File ---
st.set_page_config(page_title="VibeCode", layout="wide")
USER_ICON = "👤" 
AI_ICON = "🤖"
DB_FILE = "vibe_chat_db.json"  # File tempat menyimpan history

# Fungsi Internal untuk Automation
def load_saved_messages():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def auto_save_messages(messages):
    with open(DB_FILE, "w") as f:
        json.dump(messages, f)

# --- 2. Sidebar ---
with st.sidebar:
    st.title("VibeCode")
    
    # TOMBOL DI ATAS
    if st.button("New Chat", use_container_width=True):
        st.session_state.messages = []
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE) # Hapus file history saat New Chat
        st.rerun()
    
    # Mendorong konten ke bawah
    st.markdown("<br>" * 20, unsafe_allow_html=True)
    
    st.divider()
    # PENGATURAN DI BAWAH
    selected_model = st.selectbox(
        "Model", 
        ["meta-llama/Llama-3.2-3B-Instruct", "deepseek-ai/DeepSeek-R1"],
        index=0
    )
    
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 3. State & Auto-Load ---
if "messages" not in st.session_state:
    # Pertama kali dijalankan, ambil history dari file JSON
    st.session_state.messages = load_saved_messages()

# Render History
for msg in st.session_state.messages:
    avatar = USER_ICON if msg["role"] == "user" else AI_ICON
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# --- 4. Unified Input Logic ---
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []

    file_context = ""
    for f in files:
        try:
            content = f.read().decode("utf-8")
            file_context += f"\n\n[File: {f.name}]\n```\n{content}\n```"
        except:
            st.error(f"Could not read {f.name}")

    final_prompt = user_text + file_context

    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(final_prompt)
    
    # Tambah ke state dan AUTO-SAVE
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    auto_save_messages(st.session_state.messages)

    # --- 5. Generation ---
    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        HEADERS = {"Authorization": f"Bearer {os.getenv('HF_TOKEN')}"}
        
        payload = {
            "model": selected_model,
            "messages": st.session_state.messages,
            "temperature": temp,
            "stream": True
        }

        try:
            resp = requests.post(API_URL, headers=HEADERS, json=payload, stream=True)
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
                        except: continue
            
            placeholder.markdown(full_response)
            
            # Simpan jawaban AI dan AUTO-SAVE
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            auto_save_messages(st.session_state.messages)
            
        except Exception as e:
            st.error(f"Generation Error: {e}")