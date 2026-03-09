import streamlit as st
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from src.github_ingestor import ingest_repo
from src.pattern_extractor import extract_patterns
from src.embedder import build_index
from src.cache_manager import load_cache, save_cache
from src.reviewer import review_code_async
from src.report_generator import generate_report
from src.models import IngestConfig

load_dotenv()


def extract_repo_name(url: str) -> str:
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else url


# --- UI CONFIGURATION ---
st.set_page_config(
    page_title="CodeReview-CLI v1.0",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- THEME INJECTION (Tokyo Night / Minimalist) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 13px;
    }

    div[data-testid="stVerticalBlock"] > div {
        border-radius: 4px !important;
    }
    
    [data-testid="stSidebar"] {
        background-color: #1a1b26;
        border-right: 1px solid #24283b;
    }
    
    .stTextArea textarea {
        background-color: #16161e !important;
        color: #c0caf5 !important;
        border: 1px solid #24283b !important;
        border-radius: 4px !important;
    }

    .terminal-output {
        background-color: #1a1b26;
        padding: 10px;
        border: 1px solid #414868;
        color: #73daca;
        font-size: 12px;
        height: 150px;
        overflow-y: auto;
    }
    
    .review-card {
        border: 1px solid #24283b;
        padding: 1rem;
        margin-bottom: 0.5rem;
        background-color: #1a1b26;
        border-left: 4px solid #7aa2f7;
    }
    .review-card.critical { border-left-color: #f7768e; }
    .review-card.warning { border-left-color: #e0af68; }
    .review-card.suggestion { border-left-color: #7aa2f7; }
    </style>
    """, unsafe_allow_html=True)

# --- SESSION STATE ---
if "pattern" not in st.session_state:
    st.session_state.pattern = None
if "repo_url" not in st.session_state:
    st.session_state.repo_url = ""
if "terminal_logs" not in st.session_state:
    st.session_state.terminal_logs = []
if "review_result" not in st.session_state:
    st.session_state.review_result = None
if "report_paths" not in st.session_state:
    st.session_state.report_paths = {}

# --- PERSISTENT TERMINAL (must exist before log_terminal is called) ---
terminal_placeholder = st.empty()


def log_terminal(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    color = "#73daca" if level == "INFO" else "#f7768e"
    log_line = f'<div style="color:{color}">[{timestamp}] [{level}] {message}</div>'
    st.session_state.terminal_logs.append(log_line)
    terminal_placeholder.markdown(
        f'<div class="terminal-output">{"".join(st.session_state.terminal_logs[-15:])}</div>',
        unsafe_allow_html=True,
    )


# --- SIDEBAR: CODING FINGERPRINT ---
with st.sidebar:
    st.title("📟 PROJECT_OS")
    st.markdown("---")
    st.subheader("Coding Fingerprint")

    if st.session_state.pattern:
        combined = st.session_state.pattern.combined
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Docstring %", f"{round(combined.docstring_coverage * 100)}%", delta=None)
            st.metric("Avg fn length", f"{combined.avg_function_length}", delta=None)
        with col2:
            st.metric("Functions", str(combined.total_functions_analyzed), delta=None)
            st.metric("Files", str(combined.total_files_analyzed), delta=None)
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Complexity", "—", delta=None)
            st.metric("Coverage", "—", delta=None)
        with col2:
            st.metric("Patterns", "—", delta=None)
            st.metric("Health", "—", delta=None)

    st.markdown("---")
    st.caption("v1.0.4-stable | Engine: Llama 3.3 70B + Gemini")

# --- MAIN UI LAYOUT ---
left_pane, right_pane = st.columns([1, 1], gap="medium")

with left_pane:
    st.subheader("Source Input")
    repo_url = st.text_input("GITHUB_REPOSITORY_URL", placeholder="https://github.com/org/repo", key="repo_input")
    raw_code = st.text_area("SCRATCHPAD_BUFFER", height=450, placeholder="// Paste code snippet to review against repo patterns...", key="code_input")
    analyze_btn = st.button("RUN_DIAGNOSTICS", use_container_width=True, type="primary")

with right_pane:
    st.subheader("Diagnostic Feedback")
    feedback_container = st.container()

    if not analyze_btn and not st.session_state.review_result:
        feedback_container.info("Awaiting execution... Enter a repository URL and paste code, then click RUN_DIAGNOSTICS.")

# --- ORCHESTRATION LOGIC ---
if analyze_btn:
    repo_url = (repo_url or "").strip()
    raw_code = (raw_code or "").strip()

    if not repo_url:
        feedback_container.error("Please enter a GitHub repository URL.")
        log_terminal("Aborted: missing GITHUB_REPOSITORY_URL", "ERROR")
    elif not raw_code:
        feedback_container.error("Please paste code in SCRATCHPAD_BUFFER to review.")
        log_terminal("Aborted: missing code in scratchpad", "ERROR")
    else:
        with st.status("Initializing Analysis Pipeline...", expanded=True) as status:
            try:
                # Step 1: Ingest
                log_terminal("Initializing IngestConfig...")
                config = IngestConfig(repo_url=repo_url)
                log_terminal(f"Ingesting repository: {repo_url}")
                cached = load_cache(repo_url)
                if cached:
                    pattern = cached[0] if isinstance(cached, tuple) else cached
                    log_terminal("Loaded pattern from cache.")
                else:
                    files, skipped = ingest_repo(config)
                    if not files:
                        log_terminal("No supported code files found.", "ERROR")
                        status.update(label="No files found", state="error")
                        st.stop()
                    repo_name_str = extract_repo_name(repo_url)
                    status.update(label="Scanning Patterns...", state="running")
                    log_terminal("Running pattern_extractor...")
                    pattern = extract_patterns(files, repo_url, repo_name_str)
                    log_terminal("Building vector index...")
                    build_index(files, repo_url)
                    file_paths = [f[0] for f in files]
                    save_cache(repo_url, pattern, file_paths)
                    log_terminal(f"Analyzed {len(files)} files.")

                st.session_state.pattern = pattern
                st.session_state.repo_url = repo_url

                status.update(label="Orchestrating Multi-Agent Review...", state="running")
                log_terminal("Initializing Async Review Pipeline...", "INFO")
                review_result = asyncio.run(
                    review_code_async(
                        code=raw_code,
                        repo_url=repo_url,
                        pattern=pattern,
                        log_callback=log_terminal,
                    )
                )

                status.update(label="Diagnostics Complete", state="complete")
                log_terminal("All agents reported back successfully.", "INFO")

                st.session_state.review_result = review_result
                repo_name = extract_repo_name(repo_url)
                paths = generate_report(
                    result=review_result,
                    repo_name=repo_name,
                    output_dir="reports",
                    export_pdf=True,
                    export_json=True,
                )
                st.session_state.report_paths = paths

            except Exception as e:
                log_terminal(str(e), "ERROR")
                status.update(label="Error", state="error")
                feedback_container.error(f"Error: {e}")
                raise

        # Display results in right pane
        result = st.session_state.review_result
        with feedback_container:
            st.markdown(f"**Score: {result.score}/100** · Language: **{result.detected_language.value.upper()}**")
            st.markdown(f"*{result.summary}*")
            st.markdown("---")

            for issue in result.issues:
                sev = issue.severity.value
                st.markdown(f"""
                    <div class="review-card {sev}">
                        <div style="font-weight:bold; color:#bb9af7;">Line {issue.line_number} · {issue.category.upper()} · {sev.upper()}</div>
                        <div style="margin-top:5px; color:#cfc9c2;">{issue.message}</div>
                        <div style="margin-top:4px; color:#9ece6a; font-size:12px;">Fix: {issue.suggestion}</div>
                    </div>
                """, unsafe_allow_html=True)

            if not result.issues:
                st.success("No issues found. Code matches repo patterns.")

            st.markdown("---")
            paths = st.session_state.report_paths
            if paths.get("pdf") and os.path.exists(paths["pdf"]):
                with open(paths["pdf"], "rb") as f:
                    st.download_button("DOWNLOAD_SUMMARY_LOG", data=f.read(), file_name=os.path.basename(paths["pdf"]), mime="application/pdf")
            if paths.get("json") and os.path.exists(paths["json"]):
                with open(paths["json"], "r", encoding="utf-8") as f:
                    st.download_button("DOWNLOAD_JSON", data=f.read(), file_name=os.path.basename(paths["json"]), mime="application/json")

# Show last result again if we have one (e.g. after rerun without clicking)
if st.session_state.review_result and not analyze_btn:
    result = st.session_state.review_result
    with feedback_container:
        st.markdown(f"**Score: {result.score}/100** · Language: **{result.detected_language.value.upper()}**")
        st.markdown(f"*{result.summary}*")
        st.markdown("---")
        for issue in result.issues:
            sev = issue.severity.value
            st.markdown(f"""
                <div class="review-card {sev}">
                    <div style="font-weight:bold; color:#bb9af7;">Line {issue.line_number} · {issue.category.upper()} · {sev.upper()}</div>
                    <div style="margin-top:5px; color:#cfc9c2;">{issue.message}</div>
                    <div style="margin-top:4px; color:#9ece6a; font-size:12px;">Fix: {issue.suggestion}</div>
                </div>
            """, unsafe_allow_html=True)
        if not result.issues:
            st.success("No issues found.")
        paths = st.session_state.report_paths
        if paths.get("pdf") and os.path.exists(paths["pdf"]):
            with open(paths["pdf"], "rb") as f:
                st.download_button("DOWNLOAD_SUMMARY_LOG", data=f.read(), file_name=os.path.basename(paths["pdf"]), mime="application/pdf")

# --- TERMINAL LOG AT BOTTOM ---
if st.session_state.terminal_logs:
    terminal_placeholder.markdown(
        f'<div class="terminal-output">{"".join(st.session_state.terminal_logs[-15:])}</div>',
        unsafe_allow_html=True,
    )

# Footer
st.markdown("---")
st.markdown("<p style='text-align: center; color: #565f89;'>System Status: Operational | Code Review Agent</p>", unsafe_allow_html=True)
