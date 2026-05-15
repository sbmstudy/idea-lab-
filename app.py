import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import json
import re
import os
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv

# ---------- Setup ----------
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = (
    "You are EduBot, a friendly and encouraging AI teacher. "
    "Explain concepts simply, cheer the student up, and be patient."
)
model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)

# ---------- Session State ----------
def init_session():
    defaults = {
        "authenticated": False,
        "role": None,
        "user_id": None,
        "name": None,
        "email": None,
        "messages": [],
        "view": "login"
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

# ---------- Authentication ----------
def login_user(email, password, role):
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
    except Exception as e:
        st.error(f"Login error: {e}")
    return False

# ---------- Gemini Helpers ----------
def get_chat_response(user_message, history):
    chat = model.start_chat(history=history)
    return chat.send_message(user_message).text

def extract_weak_topics(conversation):
    conv_text = ""
    for msg in conversation:
        role = "Student" if msg["role"] == "user" else "Tutor"
        conv_text += f"{role}: {msg['content']}\n"
    prompt = (
        "Based on this conversation, return ONLY a JSON with keys 'weak_topics' (list of strings) "
        "and 'summary' (string). No extra text.\n\n" + conv_text
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

# ---------- UI Components ----------
def login_ui():
    st.title("🎓 EduBot - AI Learning Assistant")
    st.markdown("### Login")
    role = st.radio("I am a", ["Student", "Teacher"], horizontal=True)
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if login_user(email, password, role):
            st.success("Logged in!")
            st.rerun()
        else:
            st.error("Invalid credentials")

def student_dashboard():
    st.title("💬 Your AI Tutor")
    st.write(f"Welcome, **{st.session_state.name}**! Ask anything.")

    # Chat display
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Your doubt..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("EduBot is thinking..."):
                gemini_history = []
                for m in st.session_state.messages[:-1]:
                    gemini_history.append({
                        "role": "model" if m["role"] == "assistant" else "user",
                        "parts": [m["content"]]
                    })
                response = get_chat_response(prompt, gemini_history)
                st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

    # Session end
    if st.button("📊 End Session & Analyze"):
        if len(st.session_state.messages) < 2:
            st.warning("Have a conversation first.")
        else:
            with st.spinner("Analyzing..."):
                analysis = extract_weak_topics(st.session_state.messages)
                summary = analysis.get("summary", "")
                weak = analysis.get("weak_topics", [])
                # Save conversation
                supabase.table("conversations").insert({
                    "student_id": st.session_state.user_id,
                    "summary": summary,
                    "created_at": datetime.datetime.utcnow().isoformat()
                }).execute()
                # Save weak topics
                for topic in weak:
                    t = supabase.table("topics").select("*").eq("topic_name", topic).execute()
                    if not t.data:
                        t = supabase.table("topics").insert({"topic_name": topic, "subject": "General"}).execute()
                    topic_id = t.data[0]["id"]
                    supabase.table("weak_topics").insert({
                        "student_id": st.session_state.user_id,
                        "topic_id": topic_id,
                        "detected_at": datetime.datetime.utcnow().isoformat()
                    }).execute()
                st.subheader("📝 Summary")
                st.write(summary)
                if weak:
                    st.warning("🟡 Weak topics: " + ", ".join(weak))
                else:
                    st.balloons()
                    st.success("Great job!")
                st.session_state.messages = []

def teacher_dashboard():
    st.title("📊 Class Analytics")
    st.write(f"Welcome, **{st.session_state.name}**")

    # Fetch data
    weak = supabase.table("weak_topics").select(
        "id, student_id, topic_id, detected_at, students(name, email), topics(topic_name, subject)"
    ).execute()
    if not weak.data:
        st.info("No data yet.")
        return

    rows = []
    for w in weak.data:
        rows.append({
            "student": w["students"]["name"],
            "email": w["students"]["email"],
            "topic": w["topics"]["topic_name"],
            "subject": w["topics"]["subject"],
            "time": w["detected_at"]
        })
    df = pd.DataFrame(rows)

    # Class‑wide chart
    chart_df = df.groupby(["topic", "subject"])["student"].nunique().reset_index()
    chart_df.columns = ["Topic", "Subject", "Students"]
    fig = px.bar(chart_df, x="Topic", y="Students", color="Subject",
                 title="Students struggling per topic", text="Students")
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    # Detailed table
    pivot = df.pivot_table(index="student", columns="topic", aggfunc="size", fill_value=0)
    st.dataframe(pivot)

    st.download_button("Download CSV", df.to_csv(index=False), "report.csv")

# ---------- Main ----------
init_session()

# Sidebar: logout + navigation
if st.session_state.authenticated:
    st.sidebar.write(f"👤 {st.session_state.name} ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    st.sidebar.markdown("---")
    if st.session_state.role == "Student":
        student_dashboard()
    else:
        teacher_dashboard()
else:
    login_ui()