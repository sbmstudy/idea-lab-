# EduBot – AI-powered student-teacher platform (Single file deployment)
# Deploy on Streamlit Cloud with secrets: SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY

import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import json
import re
import os

# Third‑party imports
from supabase import create_client, Client
import google.generativeai as genai

# ---------- Page Config ----------
st.set_page_config(page_title="EduBot", page_icon="🎓", layout="wide")

# ---------- Environment Setup ----------
# Streamlit secrets (deployment) take precedence, then .env (local)
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    st.error("Missing credentials. Please set SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY in Streamlit secrets or .env file.")
    st.stop()

# Initialize Supabase & Gemini
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = (
    "You are EduBot, a friendly and encouraging AI teacher. "
    "Explain concepts simply, use examples, and cheer the student up. "
    "If the student seems confused, gently guide them. "
    "Keep answers concise but thorough."
)
model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)

# ---------- Session State Initialisation ----------
if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": False,
        "role": None,
        "user_id": None,
        "name": None,
        "email": None,
        "messages": [],          # for student chat
        "page": "login"
    })

# ---------- Helper Functions ----------
def login_user(email: str, password: str, role: str) -> bool:
    """Authenticate user against Supabase students/teachers table."""
    table = "students" if role == "Student" else "teachers"
    try:
        res = supabase.table(table).select("*").eq("email", email).eq("password", password).execute()
        if res.data:
            user = res.data[0]
            st.session_state.authenticated = True
            st.session_state.role = role
            st.session_state.user_id = user["id"]
            st.session_state.name = user["name"]
            st.session_state.email = user["email"]
            return True
        else:
            return False
    except Exception as e:
        st.error(f"Login error: {e}")
        return False

def get_chat_response(user_message: str, history: list) -> str:
    """Generate a response from Gemini given conversation history."""
    chat = model.start_chat(history=history)
    response = chat.send_message(user_message)
    return response.text

def extract_weak_topics(conversation: list) -> dict:
    """
    Analyse the full conversation and extract weak_topics (list) and summary (string).
    Returns a dict with keys 'weak_topics' and 'summary'.
    """
    conv_text = ""
    for msg in conversation:
        role = "Student" if msg["role"] == "user" else "Tutor"
        conv_text += f"{role}: {msg['content']}\n"
    
    prompt = (
        "Based on the following conversation, identify the topics the student seems to struggle with. "
        "Also provide a one-paragraph summary of the conversation.\n\n"
        "Return ONLY a valid JSON object with keys 'weak_topics' (array of strings) and 'summary' (string). "
        "No extra text.\n\n"
        f"{conv_text}"
    )
    
    # Use a separate model without system prompt for extraction
    extraction_model = genai.GenerativeModel("gemini-1.5-flash")
    res = extraction_model.generate_content(prompt)
    
    # Extract JSON from the response (may be wrapped in markdown)
    json_match = re.search(r'\{.*\}', res.text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    return {"weak_topics": [], "summary": "Summary not available."}

def save_session_and_weak_topics(summary: str, weak_topics: list):
    """Insert conversation record and link weak topics in Supabase."""
    try:
        # Save conversation
        conv_data = {
            "student_id": st.session_state.user_id,
            "summary": summary,
            "created_at": datetime.datetime.utcnow().isoformat()
        }
        supabase.table("conversations").insert(conv_data).execute()
        
        # For each weak topic, ensure it exists in topics table and add weak_topic record
        for topic_name in weak_topics:
            # Upsert topic
            topic_res = supabase.table("topics").select("*").eq("topic_name", topic_name).execute()
            if not topic_res.data:
                topic_res = supabase.table("topics").insert({"topic_name": topic_name, "subject": "General"}).execute()
            topic_id = topic_res.data[0]["id"]
            # Insert weak_topic link
            supabase.table("weak_topics").insert({
                "student_id": st.session_state.user_id,
                "topic_id": topic_id,
                "detected_at": datetime.datetime.utcnow().isoformat()
            }).execute()
        return True
    except Exception as e:
        st.error(f"Error saving session: {e}")
        return False

# ---------- UI Pages ----------
def login_page():
    st.title("🎓 EduBot – AI Learning Assistant")
    st.markdown("#### Login to your account")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        role = st.radio("I am a", ["Student", "Teacher"], horizontal=True)
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", use_container_width=True):
            if not email or not password:
                st.error("Please fill all fields.")
            elif login_user(email, password, role):
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid credentials or role. Check your details.")

def student_dashboard():
    st.title("💬 EduBot – Your Personal AI Tutor")
    st.markdown(f"Welcome, **{st.session_state.name}**! Ask me anything about your studies. 😊")
    
    # Chat history display
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    # Chat input
    if prompt := st.chat_input("Type your doubt here..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get AI response
        with st.chat_message("assistant"):
            with st.spinner("EduBot is thinking..."):
                # Convert history to Gemini format (excluding the just‑added user message)
                gemini_history = []
                for m in st.session_state.messages[:-1]:
                    gemini_history.append({
                        "role": "model" if m["role"] == "assistant" else "user",
                        "parts": [m["content"]]
                    })
                response = get_chat_response(prompt, gemini_history)
                st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
    
    # End session button
    if st.button("📊 End Session & Analyze My Understanding", use_container_width=True):
        if len(st.session_state.messages) < 2:
            st.warning("Have a conversation first before analysing.")
        else:
            with st.spinner("Analysing your conversation..."):
                analysis = extract_weak_topics(st.session_state.messages)
                summary = analysis.get("summary", "")
                weak_list = analysis.get("weak_topics", [])
                
                if save_session_and_weak_topics(summary, weak_list):
                    st.subheader("📝 Session Summary")
                    st.write(summary)
                    if weak_list:
                        st.warning("🟡 Topics you may need to work on:")
                        for t in weak_list:
                            st.markdown(f"- **{t}**")
                    else:
                        st.balloons()
                        st.success("Awesome! No weak topics detected. Keep it up!")
                    
                    # Clear chat for new session
                    st.session_state.messages = []
                    if st.button("Start New Chat", use_container_width=True):
                        st.rerun()

def teacher_dashboard():
    st.title("📊 Teacher Analytics Dashboard")
    st.markdown(f"Welcome, **{st.session_state.name}** – here's your class overview.")
    
    @st.cache_data(ttl=60)
    def load_analytics():
        """Fetch weak topic data with student and topic names."""
        try:
            weak_data = supabase.table("weak_topics") \
                .select("id, student_id, topic_id, detected_at, students(name, email), topics(topic_name, subject)") \
                .execute()
        except Exception as e:
            st.error(f"Database error: {e}")
            return pd.DataFrame(), pd.DataFrame()
        
        if not weak_data.data:
            return pd.DataFrame(), pd.DataFrame()
        
        rows = []
        for item in weak_data.data:
            rows.append({
                "student": item["students"]["name"],
                "email": item["students"]["email"],
                "topic": item["topics"]["topic_name"],
                "subject": item["topics"]["subject"],
                "detected_at": item["detected_at"]
            })
        df = pd.DataFrame(rows)
        
        # Class‑wide aggregation
        class_overview = df.groupby(["topic", "subject"])["student"].nunique().reset_index()
        class_overview.columns = ["Topic", "Subject", "Number of Students"]
        return class_overview, df
    
    class_overview, raw_df = load_analytics()
    
    if class_overview.empty:
        st.info("No weak topic data yet. Encourage your students to chat with EduBot!")
        return
    
    # Visualisation 1: Bar chart – weak topics across class
    st.subheader("🔍 Class Weak Topics (Unique Students per Topic)")
    fig = px.bar(
        class_overview,
        x="Topic",
        y="Number of Students",
        color="Subject",
        title="Topics with Struggling Students",
        text="Number of Students"
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)
    
    # Visualisation 2: Detailed table (student vs topics)
    st.subheader("👥 Student Weakness Breakdown")
    pivot = raw_df.pivot_table(index="student", columns="topic", aggfunc="size", fill_value=0)
    st.dataframe(pivot, use_container_width=True)
    
    # Downloadable report
    csv = raw_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Full Report (CSV)",
        data=csv,
        file_name="edubot_weak_topics_report.csv",
        mime="text/csv"
    )

# ---------- Main App Routing ----------
def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        # Sidebar with user info and logout
        with st.sidebar:
            st.markdown(f"### 👤 {st.session_state.name}")
            st.caption(f"{st.session_state.role} | {st.session_state.email}")
            st.divider()
            if st.button("🚪 Logout", use_container_width=True):
                # Reset session
                keys_to_keep = []
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
        
        # Role‑based dashboard
        if st.session_state.role == "Student":
            student_dashboard()
        else:
            teacher_dashboard()

if __name__ == "__main__":
    main()