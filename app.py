# EduBot – Premium AI Student-Teacher Platform (No Plotly, Bypassed Login for Testing)
# Deploy on Streamlit Cloud with secrets: SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY

import streamlit as st
import pandas as pd
import datetime
import json
import re
import os
from supabase import create_client, Client
import google.generativeai as genai

# ---------- Page Config & Premium CSS ----------
st.set_page_config(page_title="EduBot", page_icon="🎓", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"]  {
        font-family: 'Inter', sans-serif;
    }
    .main > div {
        padding-top: 2rem;
    }
    .glass-card {
        background: rgba(255,255,255,0.15);
        backdrop-filter: blur(12px);
        border-radius: 16px;
        padding: 1.5rem;
        margin: 1rem 0;
        border: 1px solid rgba(255,255,255,0.2);
        box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .glass-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 40px rgba(0,0,0,0.2);
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 20px;
        padding: 1.2rem;
        text-align: center;
        box-shadow: 0 10px 20px rgba(0,0,0,0.2);
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(118,75,162,0.6); }
        70% { box-shadow: 0 0 0 20px rgba(118,75,162,0); }
        100% { box-shadow: 0 0 0 0 rgba(118,75,162,0); }
    }
    .stChatMessage {
        animation: fadeInUp 0.5s ease;
    }
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    h1, h2, h3 {
        letter-spacing: -0.5px;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Environment Setup ----------
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    st.error("Missing credentials. Set SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY in Streamlit secrets.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = (
    "You are EduBot, a friendly and encouraging AI teacher. "
    "Explain concepts simply, use examples, and cheer the student up. "
    "If the student seems confused, gently guide them. "
    "Keep answers concise but thorough."
)
model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)

# ---------- Session State (bypassed login) ----------
if "authenticated" not in st.session_state:
    st.session_state.update({
        "authenticated": True,               # <-- Testing bypass
        "role": "Student",                   # <-- Testing bypass
        "user_id": "test-user-bypass-123",   # <-- dummy ID
        "name": "Tester",
        "email": "test@example.com",
        "messages": []
    })

# ---------- Helper Functions ----------
def login_user(email, password, role):
    # Not used in testing mode
    pass

def get_chat_response(user_message, history):
    chat = model.start_chat(history=history)
    return chat.send_message(user_message).text

def extract_weak_topics(conversation):
    conv_text = ""
    for m in conversation:
        role = "Student" if m["role"] == "user" else "Tutor"
        conv_text += f"{role}: {m['content']}\n"
    prompt = (
        "Based on the following conversation, identify topics the student struggles with. "
        "Return ONLY valid JSON: {weak_topics:[], summary:''}\n\n" + conv_text
    )
    extraction_model = genai.GenerativeModel("gemini-1.5-flash")
    res = extraction_model.generate_content(prompt)
    match = re.search(r'\{.*\}', res.text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    return {"weak_topics": [], "summary": "Summary not available."}

def save_session(weak_topics, summary):
    # Will fail silently because 'test-user-bypass-123' doesn't exist in Supabase
    try:
        supabase.table("conversations").insert({
            "student_id": st.session_state.user_id,
            "summary": summary,
            "created_at": datetime.datetime.utcnow().isoformat()
        }).execute()
        for topic in weak_topics:
            topic_res = supabase.table("topics").select("*").eq("topic_name", topic).execute()
            if not topic_res.data:
                topic_res = supabase.table("topics").insert({"topic_name": topic, "subject": "General"}).execute()
            topic_id = topic_res.data[0]["id"]
            supabase.table("weak_topics").insert({
                "student_id": st.session_state.user_id,
                "topic_id": topic_id,
                "detected_at": datetime.datetime.utcnow().isoformat()
            }).execute()
        return True
    except Exception as e:
        st.warning(f"Save skipped (test mode): {e}")
        return False

# ---------- Student Dashboard ----------
def student_dashboard():
    st.markdown(f"# 👋 Hi, {st.session_state.name.split()[0]}!")
    st.caption("Ask EduBot anything — I'm here to help you learn.")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Type your question..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                gemini_history = []
                for m in st.session_state.messages[:-1]:
                    gemini_history.append({
                        "role": "model" if m["role"] == "assistant" else "user",
                        "parts": [m["content"]]
                    })
                response = get_chat_response(prompt, gemini_history)
                st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

    if st.button("📊 End Session & Analyse", use_container_width=True):
        if len(st.session_state.messages) < 2:
            st.warning("Chat a bit first!")
        else:
            with st.spinner("Analysing your conversation..."):
                analysis = extract_weak_topics(st.session_state.messages)
                summary = analysis.get("summary", "")
                weak = analysis.get("weak_topics", [])
                if save_session(weak, summary):
                    st.success("Session saved!")
                with st.expander("📝 Session Summary"):
                    st.write(summary)
                    if weak:
                        st.warning("🟡 Weak topics: " + ", ".join(weak))
                    else:
                        st.balloons()
                        st.success("No weak topics — great job!")
                st.session_state.messages = []

# ---------- Teacher Dashboard ----------
def teacher_dashboard():
    st.markdown(f"# 📊 Class Analytics")
    st.caption(f"Welcome back, {st.session_state.name}")
    
    @st.cache_data(ttl=60)
    def load_data():
        try:
            weak_data = supabase.table("weak_topics") \
                .select("id, student_id, topic_id, detected_at, students(name, email), topics(topic_name, subject)") \
                .execute()
        except Exception as e:
            st.error(f"Database error: {e}")
            return pd.DataFrame()
        if not weak_data.data:
            return pd.DataFrame()
        rows = []
        for item in weak_data.data:
            rows.append({
                "student": item["students"]["name"],
                "email": item["students"]["email"],
                "topic": item["topics"]["topic_name"],
                "subject": item["topics"]["subject"],
                "time": item["detected_at"]
            })
        return pd.DataFrame(rows)
    
    df = load_data()
    if df.empty:
        st.info("No weak topic data yet.")
        return

    total_students = df["student"].nunique()
    total_topics = df["topic"].nunique()
    total_flags = len(df)
    
    col1, col2, col3 = st.columns(3)
    col1.markdown(f'<div class="metric-card"><h2>{total_students}</h2><p>Struggling Students</p></div>', unsafe_allow_html=True)
    col2.markdown(f'<div class="metric-card"><h2>{total_topics}</h2><p>Weak Topics</p></div>', unsafe_allow_html=True)
    col3.markdown(f'<div class="metric-card"><h2>{total_flags}</h2><p>Total Flags</p></div>', unsafe_allow_html=True)

    st.subheader("📈 Topics with Most Struggling Students")
    topic_counts = df.groupby("topic")["student"].nunique().sort_values(ascending=False)
    st.bar_chart(topic_counts, use_container_width=True)

    st.subheader("👥 Student Weakness Details")
    pivot = df.pivot_table(index="student", columns="topic", aggfunc="size", fill_value=0)
    st.dataframe(pivot, use_container_width=True)

    csv = df.to_csv(index=False).encode()
    st.download_button("📥 Download Full Report", csv, "edubot_report.csv")

# ---------- Main (bypass login completely) ----------
def main():
    # In testing mode, we go directly to the student dashboard
    # To restore login, uncomment the lines below and remove the direct call
    # if not st.session_state.authenticated:
    #     login_page()
    # else:
    if st.session_state.role == "Student":
        student_dashboard()
    else:
        teacher_dashboard()

if __name__ == "__main__":
    main()