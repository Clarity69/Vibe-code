import streamlit as st
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

# --- 1. Konfigurasi Halaman ---
st.set_page_config(page_title="VibeCode", layout="wide")

# CUSTOM ICONS
USER_ICON = "👤" 
AI_ICON = "🤖"

# Custom CSS untuk warna Slider Merah
st.markdown("""
    <style>
    .stSlider [data-baseweb="slider"] div { background-color: #ff4b4b; }
    </style>
""", unsafe_allow_html=True)

# --- 2. Sidebar Layout ---
with st.sidebar:
    st.title("VibeCode")
    
    # Reset Chat hanya untuk user yang menekan tombol
    if st.button("New Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    
    st.markdown("<br>" * 18, unsafe_allow_html=True)
    st.divider()
    
    selected_model = st.selectbox(
        "Model", 
        ["meta-llama/Llama-3.2-3B-Instruct", "deepseek-ai/DeepSeek-R1"]
    )
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 3. State & History Display ---
# session_state bersifat unik untuk setiap tab browser (Private)
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    avatar = USER_ICON if msg["role"] == "user" else AI_ICON
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# --- 4. Chat Input Logic ---
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []

    file_context = ""
    for f in files:
        try:
            content = f.read().decode("utf-8")
            file_context += f"\n\n[File: {f.name}]\n```\n{content}\n```"
        except:
            st.error(f"Gagal membaca {f.name}")

    final_prompt = user_text + file_context

    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(final_prompt)
    
    st.session_state.messages.append({"role": "user", "content": final_prompt})

    # --- 5. AI Generation ---
    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        # Token diambil dari Secrets (Cloud) atau .env (Lokal)
        TOKEN = st.secrets["HF_TOKEN"] if "HF_TOKEN" in st.secrets else os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        
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
                                token = data_json["choices"][0].get("delta", {}).get("content", "")
                                if token:
                                    full_response += token
                                    placeholder.markdown(full_response + "▌")
                        except: continue
            
            placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"Error: {e}")