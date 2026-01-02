import streamlit as st
import requests, json, os, datetime
from PyPDF2 import PdfReader
from docx import Document
from supabase import create_client
from dotenv import load_dotenv
from streamlit_cookies_manager import EncryptedCookieManager

# =====================
# CONFIG
# =====================
load_dotenv()

st.set_page_config(page_title="The Blueprint", layout="wide")

DEDICATED_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct"

# =====================
# SUPABASE (Cached - This is safe)
# =====================
@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL"),
        st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
    )

supabase = get_supabase()

# =====================
# COOKIES (NOT cached - widgets can't be cached)
# =====================
cookies = EncryptedCookieManager(
    prefix="blueprint_",
    password=os.getenv("COOKIE_SECRET", "dev-secret")
)

if not cookies.ready():
    st.stop()

# =====================
# SESSION REHYDRATION (Optimized)
# =====================
if "user" not in st.session_state and "access_token" in cookies:
    try:
        # Cek apakah ada cached user data di cookies
        if "user_email" in cookies:
            # Quick session restore tanpa API call
            st.session_state.user_id = cookies.get("user_id")
            st.session_state.user_email = cookies.get("user_email")
            st.session_state.username = cookies.get("username")
            st.session_state.temp = 0.4
            st.session_state.authenticated = True
            
            # Create dummy user object untuk kompatibilitas
            class DummyUser:
                def __init__(self, uid, email):
                    self.id = uid
                    self.email = email
            
            st.session_state.user = DummyUser(
                cookies.get("user_id"),
                cookies.get("user_email")
            )
        else:
            # Fallback: verify dengan Supabase
            supabase.auth.set_session(
                cookies["access_token"],
                cookies["refresh_token"]
            )
            user = supabase.auth.get_user().user
            
            st.session_state.user = user
            st.session_state.user_id = user.id
            st.session_state.user_email = user.email
            st.session_state.username = (
                user.user_metadata.get("username") or user.email.split("@")[0]
            )
            st.session_state.temp = 0.4
            st.session_state.authenticated = True
            
            # Cache untuk sesi berikutnya
            cookies["user_id"] = user.id
            cookies["user_email"] = user.email
            cookies["username"] = st.session_state.username
            cookies.save()
            
    except Exception as e:
        # Session invalid, clear everything
        cookies.clear()
        st.session_state.authenticated = False

# =====================
# HELPERS
# =====================
def read_document(file):
    try:
        if file.name.endswith(".pdf"):
            return "".join(p.extract_text() or "" for p in PdfReader(file).pages)
        if file.name.endswith(".docx"):
            return "\n".join(p.text for p in Document(file).paragraphs)
        return file.read().decode("utf-8")
    except:
        return ""

# Cache dengan TTL untuk menghindari query database terlalu sering
@st.cache_data(ttl=120, show_spinner=False)
def load_user_chats(_uid):
    """Load chat history dengan caching 2 menit"""
    try:
        res = supabase.table("chat_history") \
            .select("chat_id,messages,last_updated") \
            .eq("user_id", _uid) \
            .order("last_updated", desc=True) \
            .limit(15) \
            .execute()
        return {r["chat_id"]: r["messages"] for r in res.data}
    except Exception as e:
        st.error(f"Failed to load chats: {str(e)}")
        return {}

def save_chat(uid, cid, msgs, uname):
    """Save chat dengan error handling"""
    try:
        supabase.table("chat_history").upsert(
            {
                "user_id": uid,
                "chat_id": cid,
                "messages": msgs,
                "username": uname,
                "last_updated": datetime.datetime.utcnow().isoformat()
            },
            on_conflict="user_id,chat_id"
        ).execute()
        # Clear cache setelah save
        load_user_chats.clear()
    except Exception as e:
        st.toast(f"⚠️ Save failed: {str(e)}", icon="⚠️")

# =====================
# AUTH GATE
# =====================
if "authenticated" not in st.session_state or not st.session_state.authenticated:

    st.title("🔷 The Blueprint")
    st.caption("Your AI Architecture Assistant")

    tab_login, tab_reg = st.tabs(["🔑 Login", "📝 Register"])

    with tab_login:
        with st.form("login", clear_on_submit=True):
            email = st.text_input("Email", placeholder="your@email.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")

            if st.form_submit_button("Login", use_container_width=True, type="primary"):
                if not email or not password:
                    st.error("Please fill all fields")
                else:
                    with st.spinner("🔐 Authenticating..."):
                        try:
                            res = supabase.auth.sign_in_with_password({
                                "email": email,
                                "password": password
                            })

                            # Save authentication
                            cookies["access_token"] = res.session.access_token
                            cookies["refresh_token"] = res.session.refresh_token
                            
                            username = res.user.user_metadata.get("username") or email.split("@")[0]
                            
                            # Cache user data
                            cookies["user_id"] = res.user.id
                            cookies["user_email"] = res.user.email
                            cookies["username"] = username
                            cookies.save()

                            # Session state
                            st.session_state.user = res.user
                            st.session_state.user_id = res.user.id
                            st.session_state.user_email = res.user.email
                            st.session_state.username = username
                            st.session_state.temp = 0.4
                            st.session_state.authenticated = True
                            
                            st.success("✅ Login successful!")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"❌ Login failed: {str(e)}")

    with tab_reg:
        with st.form("register", clear_on_submit=True):
            username = st.text_input("Username", placeholder="architect")
            email = st.text_input("Email", placeholder="your@email.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            password2 = st.text_input("Confirm Password", type="password", placeholder="••••••••")

            if st.form_submit_button("Register", use_container_width=True, type="primary"):
                if not username or not email or not password:
                    st.error("Please fill all fields")
                elif password != password2:
                    st.error("Passwords don't match")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters")
                else:
                    with st.spinner("📝 Creating account..."):
                        try:
                            supabase.auth.sign_up({
                                "email": email,
                                "password": password,
                                "options": {"data": {"username": username}}
                            })
                            st.success("✅ Registration successful! Please check your email, then login.")
                        except Exception as e:
                            st.error(f"❌ Registration failed: {str(e)}")

    st.stop()

# =====================
# USER CONTEXT
# =====================
user = st.session_state.user
uid = st.session_state.user_id
username = st.session_state.username

# =====================
# CHAT STATE (Lazy Load)
# =====================
# Load chat history hanya sekali per session
if "chats_loaded" not in st.session_state:
    with st.spinner("Loading blueprints..."):
        st.session_state.db_history = load_user_chats(uid)
        st.session_state.chats_loaded = True
else:
    st.session_state.db_history = load_user_chats(uid)

db_history = st.session_state.db_history

# Initialize current chat
if "current_chat_id" not in st.session_state:
    if db_history:
        cid = next(iter(db_history))
        st.session_state.current_chat_id = cid
        st.session_state.messages = db_history[cid]
    else:
        st.session_state.current_chat_id = "Main Blueprint"
        st.session_state.messages = [
            {"role": "assistant", "content": "⚡ Architect ready. System online."}
        ]

# =====================
# SIDEBAR
# =====================
with st.sidebar:
    st.title("🔷 The Blueprint")
    st.caption(f"👤 **{username}**")

    if st.button("➕ New Blueprint", use_container_width=True):
        st.session_state.current_chat_id = f"Blueprint {len(db_history)+1}"
        st.session_state.messages = [
            {"role": "assistant", "content": "⚡ Architect ready. System online."}
        ]
        st.rerun()

    st.divider()
    
    # Show recent chats
    if db_history:
        st.caption("📂 Recent Blueprints")
        for i, cid in enumerate(list(db_history.keys())[:10]):
            is_current = cid == st.session_state.current_chat_id
            if st.button(
                f"{'📍' if is_current else '📄'} {cid}", 
                key=f"chat_{i}",
                use_container_width=True,
                disabled=is_current
            ):
                st.session_state.current_chat_id = cid
                st.session_state.messages = db_history[cid]
                st.rerun()
    else:
        st.info("No blueprints yet. Start creating!")

    st.divider()
    st.session_state.temp = st.slider(
        "🎨 Creativity", 
        0.0, 1.0, 
        st.session_state.temp, 
        0.1,
        help="Higher = more creative, Lower = more focused"
    )

    st.divider()
    if st.button("🚪 Logout", type="primary", use_container_width=True):
        supabase.auth.sign_out()
        cookies.clear()
        st.session_state.clear()
        load_user_chats.clear()
        st.rerun()

# =====================
# MAIN CHAT UI
# =====================
st.title(f"💬 {st.session_state.current_chat_id}")

# Display messages
for msg in st.session_state.messages:
    role = msg["role"]
    with st.chat_message(role, avatar="⚡" if role == "assistant" else "👤"):
        st.markdown(msg["content"])

# =====================
# INPUT
# =====================
if prompt := st.chat_input("Describe your blueprint...", key="chat_input"):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message immediately
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    
    # Generate AI response
    with st.chat_message("assistant", avatar="⚡"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            TOKEN = st.secrets.get("HF_TOKEN") or os.getenv("HF_TOKEN")
            
            r = requests.post(
                "https://router.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "model": DEDICATED_MODEL,
                    "messages": [
                        {"role": "system", "content": f"You are VibeCode Architect. Address user as {username}."}
                    ] + st.session_state.messages,
                    "temperature": st.session_state.temp,
                    "stream": True,
                    "max_tokens": 2000
                },
                stream=True,
                timeout=60
            )

            for line in r.iter_lines():
                if line:
                    data = line.decode()
                    if data.startswith("data: ") and "[DONE]" not in data:
                        try:
                            token = json.loads(data[6:])["choices"][0]["delta"].get("content", "")
                            full_response += token
                            message_placeholder.markdown(full_response + "▌")
                        except:
                            continue

            message_placeholder.markdown(full_response)
            
            # Save to history
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_chat(uid, st.session_state.current_chat_id, st.session_state.messages, username)
            
        except Exception as e:
            st.error(f"⚠️ Error: {str(e)}")
            st.session_state.messages.pop()  # Remove failed user message