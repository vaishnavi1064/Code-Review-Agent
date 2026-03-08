import streamlit as st
import os
from dotenv import load_dotenv

from src.github_ingestor import ingest_repo
from src.pattern_extractor import extract_patterns
from src.embedder import build_index, search_similar
from src.cache_manager import load_cache, save_cache
from src.reviewer import review_code
from src.report_generator import generate_report
from src.models import IngestConfig

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title='Code Review Agent',
    page_icon='🔍',
    layout='wide',
    initial_sidebar_state='collapsed',
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #1E1E2E; color: #CDD6F4; }
    .block-container { padding: 2rem 3rem; }
    h1, h2, h3 { color: #CDD6F4 !important; }
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        background-color: #313244 !important;
        color: #CDD6F4 !important;
        border: 1px solid #45475A !important;
        border-radius: 8px !important;
    }
    .stButton > button {
        background-color: #89B4FA !important;
        color: #1E1E2E !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 0.5rem 1.5rem !important;
        width: 100%;
    }
    .stButton > button:hover { background-color: #74C7EC !important; }
    .stCheckbox > label { color: #CDD6F4 !important; }
    .score-card {
        background: #313244;
        border-radius: 12px;
        padding: 1.5rem;
        text-align: center;
        border: 1px solid #45475A;
    }
    .score-number { font-size: 4rem; font-weight: 900; line-height: 1; }
    .score-label { font-size: 0.85rem; font-weight: 700; letter-spacing: 2px; margin-top: 0.25rem; }
    .stat-card {
        background: #313244;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #45475A;
    }
    .stat-number { font-size: 2rem; font-weight: 800; }
    .stat-label  { font-size: 0.7rem; color: #6C7086; letter-spacing: 1px; margin-top: 2px; }
    .issue-card {
        background: #313244;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.6rem;
        border-left: 4px solid;
    }
    .issue-card.critical   { border-color: #F38BA8; }
    .issue-card.warning    { border-color: #F9E2AF; }
    .issue-card.suggestion { border-color: #89B4FA; }
    .issue-meta { font-size: 0.72rem; color: #6C7086; margin-bottom: 0.3rem; }
    .issue-msg  { font-size: 0.9rem;  color: #CDD6F4; margin-bottom: 0.4rem; }
    .issue-fix  { font-size: 0.8rem;  color: #A6E3A1; }
    .issue-diff {
        font-family: monospace;
        font-size: 0.78rem;
        background: #1E1E2E;
        border-radius: 6px;
        padding: 0.5rem 0.8rem;
        margin-top: 0.4rem;
        color: #CDD6F4;
        white-space: pre;
    }
    .section-divider { border: none; border-top: 1px solid #45475A; margin: 1.5rem 0; }
    .lang-badge {
        display: inline-block;
        background: #45475A;
        color: #89B4FA;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 0.2rem 0.7rem;
        border-radius: 20px;
        letter-spacing: 1px;
    }
    .summary-box {
        background: #313244;
        border-radius: 10px;
        padding: 1rem 1.5rem;
        border: 1px solid #45475A;
        color: #CDD6F4;
        font-size: 0.95rem;
        line-height: 1.6;
    }
    .step-header {
        background: #313244;
        border-radius: 10px;
        padding: 0.75rem 1.2rem;
        border: 1px solid #45475A;
        margin-bottom: 1rem;
        font-weight: 700;
        color: #89B4FA;
        font-size: 1rem;
    }
    .success-banner {
        background: #1E3A2F;
        border: 1px solid #A6E3A1;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        color: #A6E3A1;
        font-size: 0.9rem;
        margin-bottom: 0.5rem;
    }
    .error-banner {
        background: #3A1E2F;
        border: 1px solid #F38BA8;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        color: #F38BA8;
        font-size: 0.9rem;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def score_color(score: int) -> str:
    if score >= 90: return '#A6E3A1'
    if score >= 70: return '#89B4FA'
    if score >= 50: return '#F9E2AF'
    return '#F38BA8'

def score_label(score: int) -> str:
    if score >= 90: return 'EXCELLENT'
    if score >= 70: return 'GOOD'
    if score >= 50: return 'NEEDS WORK'
    return 'CRITICAL ISSUES'

def severity_color(sev: str) -> str:
    return {'critical': '#F38BA8', 'warning': '#F9E2AF', 'suggestion': '#89B4FA'}.get(sev, '#89B4FA')

def extract_repo_name(url: str) -> str:
    parts = url.rstrip('/').split('/')
    return parts[-1] if parts else url


# ── Session state init ────────────────────────────────────────────────────────
if 'pattern'       not in st.session_state: st.session_state.pattern       = None
if 'repo_url'      not in st.session_state: st.session_state.repo_url      = ''
if 'repo_ready'    not in st.session_state: st.session_state.repo_ready    = False
if 'review_result' not in st.session_state: st.session_state.review_result = None
if 'report_paths'  not in st.session_state: st.session_state.report_paths  = {}


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom: 1.5rem;">
    <h1 style="font-size:2.2rem; font-weight:900; margin-bottom:0.2rem;">
        🔍 Code Review Agent
    </h1>
    <p style="color:#6C7086; font-size:0.95rem; margin:0;">
        Personalized AI code review based on <em>your</em> coding fingerprint — not generic rules.
    </p>
</div>
<hr class="section-divider">
""", unsafe_allow_html=True)


# ── STEP 1: Repo Analysis ─────────────────────────────────────────────────────
st.markdown('<div class="step-header">Step 1 — Analyze a GitHub Repository</div>', unsafe_allow_html=True)

col1, col2 = st.columns([3, 1])
with col1:
    repo_url = st.text_input(
        'GitHub Repository URL',
        placeholder='https://github.com/username/repository',
        label_visibility='collapsed',
    )
with col2:
    github_token = st.text_input(
        'GitHub Token (optional)',
        type='password',
        placeholder='ghp_... (private repos)',
        label_visibility='collapsed',
    )

force_refresh = st.checkbox('Force refresh (ignore cache)', value=False)
analyze_clicked = st.button('🔬 Analyze Repository', key='analyze_btn')

if analyze_clicked:
    if not repo_url.strip():
        st.markdown('<div class="error-banner">⚠ Please enter a GitHub repository URL.</div>', unsafe_allow_html=True)
    else:
        token = github_token.strip() or os.getenv('GITHUB_TOKEN')

        with st.spinner('Fetching repository and extracting your coding fingerprint...'):
            try:
                cached = None if force_refresh else load_cache(repo_url)

                if cached:
                    st.session_state.pattern = cached
                    st.markdown('<div class="success-banner">✓ Loaded from cache. Use "Force refresh" to re-analyze.</div>', unsafe_allow_html=True)
                else:
                    # ── FIXED: use IngestConfig ──
                    config = IngestConfig(repo_url=repo_url, github_token=token)
                    files, errors = ingest_repo(config)

                    if not files:
                        st.markdown('<div class="error-banner">⚠ No supported code files found in this repository.</div>', unsafe_allow_html=True)
                        st.stop()

                    pattern = extract_patterns(files, repo_url)
                    build_index(files, repo_url)
                    save_cache(repo_url, pattern)

                    st.session_state.pattern = pattern
                    st.markdown(f'<div class="success-banner">✓ Analyzed {len(files)} files and built your coding fingerprint.</div>', unsafe_allow_html=True)

                st.session_state.repo_url   = repo_url
                st.session_state.repo_ready = True

            except Exception as e:
                st.markdown(f'<div class="error-banner">✗ Error: {str(e)}</div>', unsafe_allow_html=True)


# ── Fingerprint summary ───────────────────────────────────────────────────────
if st.session_state.repo_ready and st.session_state.pattern:
    pattern  = st.session_state.pattern
    combined = pattern.combined

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown('**📊 Your Coding Fingerprint**')

    fp1, fp2, fp3, fp4 = st.columns(4)
    with fp1:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-number" style="color:#89B4FA;">{combined.naming_convention}</div>
            <div class="stat-label">NAMING STYLE</div>
        </div>''', unsafe_allow_html=True)
    with fp2:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-number" style="color:#A6E3A1;">{round(combined.docstring_coverage * 100)}%</div>
            <div class="stat-label">DOCSTRING COVERAGE</div>
        </div>''', unsafe_allow_html=True)
    with fp3:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-number" style="color:#F9E2AF;">{combined.avg_function_length}</div>
            <div class="stat-label">AVG FUNCTION LENGTH</div>
        </div>''', unsafe_allow_html=True)
    with fp4:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-number" style="color:#CBA6F7;">{"Yes" if combined.uses_type_hints else "No"}</div>
            <div class="stat-label">TYPE HINTS</div>
        </div>''', unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)


# ── STEP 2: Code Review ───────────────────────────────────────────────────────
st.markdown('<div class="step-header">Step 2 — Paste Code to Review</div>', unsafe_allow_html=True)

if not st.session_state.repo_ready:
    st.markdown('<p style="color:#6C7086; font-size:0.9rem;">Complete Step 1 first to load your coding fingerprint.</p>', unsafe_allow_html=True)
else:
    code_input = st.text_area(
        'Paste your code here',
        height=280,
        placeholder='Paste any Python, Java, Kotlin, JavaScript, or TypeScript code...',
        label_visibility='collapsed',
    )

    st.markdown('**Export Options**')
    ecol1, ecol2 = st.columns(2)
    with ecol1:
        export_pdf  = st.checkbox('📄 Export PDF Report', value=True)
    with ecol2:
        export_json = st.checkbox('📦 Export JSON Report', value=True)

    review_clicked = st.button('🚀 Review Code', key='review_btn')

    if review_clicked:
        if not code_input.strip():
            st.markdown('<div class="error-banner">⚠ Please paste some code to review.</div>', unsafe_allow_html=True)
        else:
            with st.spinner('Reviewing your code against your personal coding patterns...'):
                try:
                    result = review_code(
                        code=code_input,
                        repo_url=st.session_state.repo_url,
                        pattern=st.session_state.pattern,
                    )
                    st.session_state.review_result = result

                    repo_name = extract_repo_name(st.session_state.repo_url)
                    paths = generate_report(
                        result=result,
                        repo_name=repo_name,
                        output_dir='reports',
                        export_pdf=export_pdf,
                        export_json=export_json,
                    )
                    st.session_state.report_paths = paths

                except Exception as e:
                    st.markdown(f'<div class="error-banner">✗ Review failed: {str(e)}</div>', unsafe_allow_html=True)


# ── Results ───────────────────────────────────────────────────────────────────
if st.session_state.review_result:
    result = st.session_state.review_result
    paths  = st.session_state.report_paths

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown('## Review Results')

    sc1, sc2, sc3, sc4, sc5 = st.columns([2, 1, 1, 1, 1])
    col = score_color(result.score)
    lbl = score_label(result.score)

    with sc1:
        st.markdown(f'''<div class="score-card">
            <div class="score-number" style="color:{col};">{result.score}</div>
            <div class="score-label"  style="color:{col};">{lbl}</div>
            <div style="color:#6C7086; font-size:0.75rem; margin-top:0.5rem;">
                <span class="lang-badge">{result.detected_language.value.upper()}</span>
            </div>
        </div>''', unsafe_allow_html=True)
    with sc2:
        st.markdown(f'''<div class="stat-card" style="border-color:#F38BA8;">
            <div class="stat-number" style="color:#F38BA8;">{result.critical_count}</div>
            <div class="stat-label">CRITICAL</div>
        </div>''', unsafe_allow_html=True)
    with sc3:
        st.markdown(f'''<div class="stat-card" style="border-color:#F9E2AF;">
            <div class="stat-number" style="color:#F9E2AF;">{result.warning_count}</div>
            <div class="stat-label">WARNINGS</div>
        </div>''', unsafe_allow_html=True)
    with sc4:
        st.markdown(f'''<div class="stat-card" style="border-color:#89B4FA;">
            <div class="stat-number" style="color:#89B4FA;">{result.suggestion_count}</div>
            <div class="stat-label">SUGGESTIONS</div>
        </div>''', unsafe_allow_html=True)
    with sc5:
        st.markdown(f'''<div class="stat-card">
            <div class="stat-number" style="color:#CDD6F4;">{result.total_issues}</div>
            <div class="stat-label">TOTAL ISSUES</div>
        </div>''', unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)

    # Summary
    st.markdown('**Summary**')
    st.markdown(f'<div class="summary-box">{result.summary}</div>', unsafe_allow_html=True)
    st.markdown('<br>', unsafe_allow_html=True)

    # Issues
    if result.issues:
        st.markdown('**Issues**')
        for sev_label, sev_val in [('Critical', 'critical'), ('Warning', 'warning'), ('Suggestion', 'suggestion')]:
            group = [i for i in result.issues if i.severity.value == sev_val]
            if not group:
                continue

            sev_col = severity_color(sev_val)
            st.markdown(f'<p style="color:{sev_col}; font-weight:700; margin:0.8rem 0 0.4rem;">● {sev_label} ({len(group)})</p>', unsafe_allow_html=True)

            for issue in group:
                diff_html = ''
                if issue.diff:
                    diff_html = f'<div class="issue-diff">{issue.diff}</div>'

                st.markdown(f'''
                <div class="issue-card {sev_val}">
                    <div class="issue-meta">Line {issue.line_number} &nbsp;·&nbsp; {issue.category.upper()}</div>
                    <div class="issue-msg">{issue.message}</div>
                    <div class="issue-fix">💡 {issue.suggestion}</div>
                    {diff_html}
                </div>''', unsafe_allow_html=True)
    else:
        st.markdown('<div class="success-banner">✓ No issues found. Code matches your personal patterns perfectly.</div>', unsafe_allow_html=True)

    # Downloads
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
    st.markdown('**Download Reports**')

    dl1, dl2, _ = st.columns([1, 1, 2])

    if 'pdf' in paths and os.path.exists(paths['pdf']):
        with open(paths['pdf'], 'rb') as f:
            with dl1:
                st.download_button(
                    label='📄 Download PDF',
                    data=f.read(),
                    file_name=os.path.basename(paths['pdf']),
                    mime='application/pdf',
                )

    if 'json' in paths and os.path.exists(paths['json']):
        with open(paths['json'], 'r') as f:
            with dl2:
                st.download_button(
                    label='📦 Download JSON',
                    data=f.read(),
                    file_name=os.path.basename(paths['json']),
                    mime='application/json',
                )