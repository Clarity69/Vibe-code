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

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="VibeCode AI | Architect", layout="wide", page_icon="🏗️")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# --- 2. INITIALIZE SUPABASE ---
@st.cache_resource
def init_supabase():
    url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()

# --- 3. SESSION PERSISTENCE LOGIC ---
if "user_data" not in st.session_state:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.user_data = session.user
            # Fetch username from metadata
            st.session_state.username = session.user.user_metadata.get("username", session.user.email.split('@')[0])
    except:
        pass

# --- 4. HELPER FUNCTIONS ---
def read_document(file):
    try:
        name = file.name.lower()
        if name.endswith('.pdf'):
            return "".join([p.extract_text() or "" for p in PdfReader(file).pages])
        elif name.endswith('.docx'):
            return "\n".join([p.text for p in Document(file).paragraphs])
        return file.read().decode("utf-8")
    except Exception as e:
        return f"\n[Error reading file {file.name}: {e}]\n"

def load_user_chats(user_id):
    try:
        res = supabase.table("chat_history").select("*").eq("user_id", user_id).order("last_updated", desc=True).execute()
        return {item['chat_id']: item['messages'] for item in res.data}
    except:
        return {}

def save_chat_to_db(user_id, chat_id, messages, username):
    try:
        data = {
            "user_id": user_id, 
            "chat_id": chat_id, 
            "messages": messages,
            "username": username, # Explicitly save the username
            "last_updated": datetime.datetime.now().isoformat()
        }
        supabase.table("chat_history").upsert(data, on_conflict="user_id,chat_id").execute()
    except:
        pass

# --- 5. AUTHENTICATION UI ---
if "user_data" not in st.session_state:
    st.title("🏗️ VibeCode Architect")
    st.info("Log in to access your architectural blueprints and code.")
    
    tab_login, tab_reg = st.tabs(["Login", "Register"])
    
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            btn_login = st.form_submit_button("Login", use_container_width=True)
            if btn_login:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user_data = res.user
                    st.session_state.username = res.user.user_metadata.get("username", email.split('@')[0])
                    st.success("Architect authenticated!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_reg:
        with st.form("register_form"):
            u_name = st.text_input("Desired Username")
            email_r = st.text_input("Email Address")
            pass_r = st.text_input("Password (Min 6 chars)", type="password")
            btn_reg = st.form_submit_button("Register Architect", use_container_width=True)
            if btn_reg:
                try:
                    supabase.auth.sign_up({
                        "email": email_r, 
                        "password": pass_r,
                        "options": {"data": {"username": u_name}}
                    })
                    st.success("Registration successful! Proceed to Login.")
                except Exception as e:
                    st.error(f"Registration failed: {e}")
    st.stop()

# --- 6. INTERFACE SETUP ---
user_id = st.session_state.user_data.id
username_display = st.session_state.username # Using the stored username
db_history = load_user_chats(user_id)

if "messages" not in st.session_state:
    if db_history:
        latest_id = list(db_history.keys())[0]
        st.session_state.current_chat_id = latest_id
        st.session_state.messages = db_history[latest_id]
    else:
        st.session_state.current_chat_id = "Initial Blueprint"
        st.session_state.messages = [{"role": "assistant", "content": f"Architect ready. How can I help you design today, {username_display}?"}]

# --- 7. SIDEBAR ---
with st.sidebar:
    st.title("🏗️ VibeCode")
    st.write(f"Logged in as: **{username_display}**")
    
    if st.button("Logout", type="secondary", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state.clear()
        st.rerun()
        
    st.divider()
    if st.button("+ New Blueprint", use_container_width=True, type="primary"):
        st.session_state.current_chat_id = f"Blueprint {len(db_history) + 1}"
        st.session_state.messages = [{"role": "assistant", "content": f"New design session started, {username_display}."}]
        st.rerun()

    st.write("### Project History")
    for cid in db_history.keys():
        if st.button(cid, key=f"btn_{cid}", use_container_width=True):
            st.session_state.current_chat_id = cid
            st.session_state.messages = db_history[cid]
            st.rerun()

# --- 8. MAIN CHAT AREA ---
st.subheader(f"Project: {st.session_state.current_chat_id}")

for msg in st.session_state.messages:
    # Set the display name: Use Username for user, "Architect" for assistant
    display_name = username_display if msg["role"] == "user" else "Architect"
    with st.chat_message(msg["role"], avatar="👤" if msg["role"]=="user" else "🏗️"):
        st.write(f"**{display_name}**")
        content = msg["content"]
        if msg["role"] == "user" and "[Document Content:" in content:
            display_text = content.split("\n\n[Document Content:")[0] + " 📄 *(Specifications attached)*"
            st.markdown(display_text)
        else:
            st.markdown(content)

if prompt_data := st.chat_input("Submit requirements or upload files...", accept_file=True):
    user_text = prompt_data.text
    file_context = ""
    for f in prompt_data.files:
        file_context += f"\n\n[Document Content: {f.name}]\n{read_document(f)}\n"
    
    final_prompt = user_text + file_context
    st.session_state.messages.append({"role": "user", "content": final_prompt})
    
    if st.session_state.current_chat_id.startswith("Blueprint ") or st.session_state.current_chat_id == "Initial Blueprint":
        if user_text:
            st.session_state.current_chat_id = (user_text[:30] + '...') if len(user_text) > 30 else user_text
    st.rerun()

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    with st.chat_message("assistant", avatar="🏗️"):
        res_box = st.empty()
        full_response = ""
        TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
        HEADERS = {"Authorization": f"Bearer {TOKEN}"}
        
        # --- ARCHITECT SYSTEM PROMPT ---
        system_msg = [{
            "role": "system", 
            "content": f"You are VibeCode Architect, a world-class software architect. Your goal is to provide high-level design, scalable patterns, and robust code. Address the user as {username_display}. Use markdown blocks for all code and diagrams."
        }]
        
        try:
            resp = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers=HEADERS,
                json={"model": DEDICATED_MODEL, "messages": system_msg + st.session_state.messages, "temperature": 0.4, "stream": True},
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
            save_chat_to_db(user_id, st.session_state.current_chat_id, st.session_state.messages, username_display)
            st.rerun()
        except Exception as e:
            st.error(f"Architectural link lost: {e}")