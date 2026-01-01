import streamlit as st
import requests
import json
import os
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from docx import Document

load_dotenv()

# --- 1. Konfigurasi Halaman ---
st.set_page_config(page_title="VibeCode", layout="wide")

USER_ICON = "👤" 
AI_ICON = "🤖"

# --- STYLE CSS (Slider & UI) ---
st.markdown("""
    <style>
    div[data-baseweb="slider"] > div:first-child > div:first-child {
        background: linear-gradient(to right, rgb(255, 75, 75) 0%, rgb(255, 75, 75) var(--slider-value), rgba(151, 166, 195, 0.25) var(--slider-value));
    }
    span[data-baseweb="slider-thumb"] {
        background-color: #ff4b4b;
        border: 2px solid #ff4b4b;
    }
    [data-testid="stSidebarNav"] {display: none;}
    </style>
""", unsafe_allow_html=True)

# --- FUNGSI PEMBACA DOKUMEN ---
def read_document(file):
    name = file.name.lower()
    if name.endswith('.pdf'):
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    elif name.endswith('.docx'):
        doc = Document(file)
        return "\n".join([para.text for para in doc.paragraphs])
    else: 
        return file.read().decode("utf-8")

# --- 2. Sidebar Layout ---
with st.sidebar:
    st.title("VibeCode")
    
    if st.button("New Chat", use_container_width=True):
        st.session_state.messages = [
            {"role": "assistant", "content": "Halo! Sesi telah direset. Ada yang bisa saya bantu? 🚀"}
        ]
        st.rerun()
    
    st.markdown("<br>" * 18, unsafe_allow_html=True)
    st.divider()
    
    selected_model = st.selectbox(
        "Model", 
        ["meta-llama/Llama-3.2-3B-Instruct", "deepseek-ai/DeepSeek-R1"]
    )
    temp = st.slider("Creativity", 0.0, 1.0, 0.40)

# --- 3. State & Welcome Message ---
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Halo! I'm **VibeCode AI**. what can i help ya?"}
    ]

for msg in st.session_state.messages:
    avatar = USER_ICON if msg["role"] == "user" else AI_ICON
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# --- 4. Chat Input & Document Logic ---
if prompt := st.chat_input("Message VibeCode...", accept_file=True):
    
    user_text = prompt.text if hasattr(prompt, 'text') else prompt
    files = prompt.files if hasattr(prompt, 'files') else []

    file_context = ""
    for f in files:
        try:
            content = read_document(f)
            file_context += f"\n\n[Isi Dokumen: {f.name}]\n{content}\n"
        except Exception as e:
            st.error(f"Gagal membaca {f.name}: {e}")

    # Prompt akhir dikirim ke AI (dengan isi file), tapi di UI hanya tampil teks user
    final_prompt = user_text + file_context

    with st.chat_message("user", avatar=USER_ICON):
        st.markdown(user_text if not files else f"{user_text} *(Mengunggah {len(files)} file)*")
    
    st.session_state.messages.append({"role": "user", "content": final_prompt})

    # --- 5. AI Generation ---
    with st.chat_message("assistant", avatar=AI_ICON):
        placeholder = st.empty()
        full_response = ""
        
        # LOGIKA TOKEN AMAN
        TOKEN = os.getenv("HF_TOKEN")
        if not TOKEN:
            try:
                if "HF_TOKEN" in st.secrets:
                    TOKEN = st.secrets["HF_TOKEN"]
            except: pass

        if not TOKEN:
            st.error("Token tidak ditemukan!")
            st.stop()

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