import streamlit as st
import requests
import json
import os
import uuid
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client, Client

# --- 1. Konfigurasi Halaman & CSS ---
st.set_page_config(page_title="VibeCode AI", layout="wide")

st.markdown("""
    <style>
    div[data-baseweb="slider"] > div:first-child > div:first-child {
        background: linear-gradient(to right, rgb(255, 75, 75) 0%, rgb(255, 75, 75) var(--slider-value), rgba(151, 166, 195, 0.25) var(--slider-value));
    }
    span[data-baseweb="slider-thumb"] { background-color: #ff4b4b; border: 2px solid #ff4b4b; }
    </style>
""", unsafe_allow_html=True)

# --- 2. Database & User ID ---
@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

if "user_uuid" not in st.session_state:
    st.session_state.user_uuid = str(uuid.uuid4())

# --- 3. Fungsi Database ---
def save_to_supabase(chat_id, messages):
    data = {"user_id": st.session_state.user_uuid, "chat_id": chat_id, "messages": messages}
    supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()

def load_user_chats():
    res = supabase.table("chat_history").select("*").eq("user_id", st.session_state.user_uuid).execute()
    return {item['chat_id']: item['messages'] for item in res.data}

# --- 4. Sidebar Riwayat ---
with st.sidebar:
    st.title("VibeCode")
    user_history = load_user_chats()
    
    if st.button("+ New Chat", use_container_width=True):
        st.session_state.current_chat_id = f"Chat {len(user_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": "Halo! Sesi baru dimulai. 🚀"}]
        st.rerun()

    st.write("### Riwayat")
    for cid in user_history.keys():
        if st.button(cid, key=cid, use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = user_history[cid]
            st.rerun()

# --- 5. Logika Utama Chat ---
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "Chat 1"
if "messages" not in st.session_state:
    st.session_state.messages = user_history.get("Chat 1", [{"role": "assistant", "content": "Halo! Saya VibeCode AI. Ada yang bisa dibantu? 🚀"}])

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🤖" if msg["role"]=="assistant" else "👤"):
        st.markdown(msg["content"])

if prompt := st.chat_input("Tulis pesan..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"): st.markdown(prompt)
    
    # ... (Bagian AI Generation tetap sama seperti sebelumnya) ...
    
    # Simpan otomatis setelah AI menjawab
    save_to_supabase(st.session_state.current_chat_id, st.session_state.messages)