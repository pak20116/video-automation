import os
import subprocess
import sys
from pathlib import Path

import requests
import streamlit as st
from dotenv import load_dotenv, set_key

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
ENV_FILE = PROJECT_ROOT / ".env"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGES_DIR = OUTPUT_DIR / "images"
AUDIO_PATH = OUTPUT_DIR / "audio" / "full_tts.mp3"
VIDEO_PATH = OUTPUT_DIR / "final_video.mp4"

st.set_page_config(
    page_title="Video Automation Pipeline",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    .step-box {
        background: #f8f9fa;
        border-left: 4px solid #dee2e6;
        border-radius: 4px;
        padding: 8px 14px;
        margin: 4px 0;
        font-size: 0.9rem;
    }
    .step-box.done  { border-color: #28a745; background: #f0fff4; }
    .step-box.run   { border-color: #007bff; background: #f0f4ff; }
    .step-box.error { border-color: #dc3545; background: #fff0f0; }
</style>
""", unsafe_allow_html=True)


# ── Helper: fetch ElevenLabs voices ───────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def fetch_voices(api_key: str):
    if not api_key:
        return []
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
            timeout=6,
        )
        if r.ok:
            return [
                (v["name"], v["voice_id"], v.get("category", "premade"))
                for v in r.json().get("voices", [])
            ]
    except Exception:
        pass
    return []


def update_env(key: str, value: str):
    set_key(str(ENV_FILE), key, value)


# ══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("⚙️ 설정")

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    el_key = os.getenv("ELEVENLABS_API_KEY", "")

    # API key status
    st.markdown("**API 키**")
    c1, c2 = st.columns(2)
    c1.markdown(f"{'✅' if gemini_key else '❌'} Gemini")
    c2.markdown(f"{'✅' if el_key else '❌'} ElevenLabs")

    if not gemini_key or not el_key:
        st.error("`.env` 파일에 API 키를 입력해주세요.")
        st.stop()

    st.divider()

    # ── Voice ───────────────────────────────────────────────────────
    st.markdown("**🎤 음성**")
    voices = fetch_voices(el_key)
    current_vid = os.getenv("ELEVENLABS_VOICE_ID", "")

    if voices:
        labels = [f"[{cat}] {name}" for name, _, cat in voices]
        ids    = [vid for _, vid, _ in voices]
        default = ids.index(current_vid) if current_vid in ids else 0
        chosen_label = st.selectbox("음성 선택", labels, index=default, label_visibility="collapsed")
        selected_vid = ids[labels.index(chosen_label)]
    else:
        selected_vid = st.text_input("Voice ID", value=current_vid)

    st.divider()

    # ── Video format ─────────────────────────────────────────────────
    st.markdown("**📐 비디오 해상도**")
    fmt_map = {
        "YouTube 가로  1920×1080": (1920, 1080),
        "HD  1280×720":            (1280,  720),
        "Shorts / TikTok  1080×1920": (1080, 1920),
        "Instagram 정사각  1080×1080": (1080, 1080),
    }
    sel_fmt = st.selectbox("해상도", list(fmt_map), label_visibility="collapsed")
    vid_w, vid_h = fmt_map[sel_fmt]

    st.divider()

    # ── Subtitle ─────────────────────────────────────────────────────
    st.markdown("**💬 자막**")
    subtitle_size = st.slider(
        "글자 크기", 14, 48,
        int(os.getenv("SUBTITLE_FONT_SIZE", "24")),
        label_visibility="collapsed",
    )
    words_per_line = st.slider(
        "줄당 최대 단어 수", 3, 10,
        int(os.getenv("SUBTITLE_WORDS_PER_LINE", "5")),
        help="숫자가 작을수록 자막이 더 자주 바뀝니다",
    )

    st.divider()

    # ── Start step ───────────────────────────────────────────────────
    st.markdown("**🔁 시작 스텝** (재실행 시)")
    step_labels = {
        1: "1 — 처음부터",
        2: "2 — 대본 분할",
        3: "3 — 이미지 프롬프트",
        4: "4 — 이미지 생성",
        5: "5 — TTS 음성",
        6: "6 — 자막",
        7: "7 — 영상 렌더링만",
    }
    start_step = st.selectbox(
        "시작 스텝",
        list(step_labels),
        format_func=lambda x: step_labels[x],
        label_visibility="collapsed",
    )

    if start_step <= 4:
        clear_images = st.checkbox("기존 이미지 삭제 후 재생성", value=(start_step <= 3))
    else:
        clear_images = False


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
st.title("🎬 Video Automation Pipeline")
st.caption("대본 입력 → AI 이미지 생성 → TTS 음성 → 자막 → MP4 자동 완성")

# ── Input area ────────────────────────────────────────────────────────
col_script, col_style = st.columns([3, 2], gap="large")

with col_script:
    st.markdown("### 📄 대본")
    method = st.radio("입력 방식", ["직접 입력", "파일 업로드"], horizontal=True, label_visibility="collapsed")

    if method == "직접 입력":
        script_text = st.text_area(
            "대본",
            height=300,
            placeholder="여기에 대본을 입력하세요.\n\n단락이 나뉘면 더 자연스럽게 장면이 분할됩니다.",
            label_visibility="collapsed",
            key="script_input",
        )
    else:
        uploaded = st.file_uploader("텍스트 파일 업로드 (.txt)", type=["txt"], label_visibility="collapsed")
        if uploaded:
            script_text = uploaded.read().decode("utf-8")
            st.text_area("미리보기", script_text, height=240, disabled=True, label_visibility="collapsed")
        else:
            script_text = ""

with col_style:
    st.markdown("### 🎨 캐릭터 & 스타일")

    character_desc = st.text_area(
        "캐릭터 설명",
        height=130,
        placeholder=(
            "예시:\n"
            "주인공(남성): 파란 넥타이, 검은 머리 스틱맨\n"
            "조연(여성): 빨간 드레스, 주황 묶음 머리 스틱맨\n\n"
            "비워두면 기본 스틱맨 스타일로 생성됩니다."
        ),
        help="모든 장면에서 캐릭터 외형을 일관되게 유지합니다.",
    )

    art_style = st.text_area(
        "아트 스타일",
        height=110,
        value=os.getenv(
            "IMAGE_STYLE",
            "YouTube educational animation style, simple 2D stick figure characters "
            "with perfect circle heads, bold black outlines, flat colors, clean white background",
        ),
        help="이미지 생성에 적용할 스타일 지침 (영어 권장)",
    )

    st.markdown("")
    run_btn = st.button(
        "🚀 영상 생성 시작",
        type="primary",
        use_container_width=True,
        disabled=not script_text.strip(),
    )

st.divider()

# ── Pipeline run ──────────────────────────────────────────────────────
STEP_NAMES = {
    1: "📄 스크립트 로드",
    2: "✂️  대본 분할 (Gemini)",
    3: "🖊️  이미지 프롬프트 생성 (Gemini)",
    4: "🖼️  이미지 생성 (Gemini Image)",
    5: "🎤 TTS 음성 생성 (ElevenLabs)",
    6: "💬 자막 생성",
    7: "🎬 영상 렌더링 (FFmpeg)",
}

if run_btn and script_text.strip():
    # ① 설정을 .env 에 저장
    update_env("ELEVENLABS_VOICE_ID", selected_vid)
    update_env("VIDEO_WIDTH", str(vid_w))
    update_env("VIDEO_HEIGHT", str(vid_h))
    update_env("SUBTITLE_FONT_SIZE", str(subtitle_size))
    update_env("SUBTITLE_WORDS_PER_LINE", str(words_per_line))
    update_env("IMAGE_STYLE", art_style)
    update_env("CHARACTER_DESCRIPTION", character_desc)

    # ② 대본 저장
    SCRIPTS_DIR.mkdir(exist_ok=True)
    script_file = SCRIPTS_DIR / "_ui_script.txt"
    script_file.write_text(script_text, encoding="utf-8")

    # ③ 기존 이미지 삭제 (옵션)
    if clear_images and IMAGES_DIR.exists():
        for f in IMAGES_DIR.glob("segment_*.png"):
            f.unlink()

    # ④ 스텝 상태 표시 영역
    st.markdown("### 🔄 파이프라인 진행 상황")
    step_placeholders = {i: st.empty() for i in range(1, 8)}

    def render_step(n: int, state: str, detail: str = ""):
        icon = {"pending": "⏳", "run": "🔵", "done": "✅", "skip": "⏭️", "error": "❌"}[state]
        css  = {"pending": "", "run": "run", "done": "done", "skip": "", "error": "error"}[state]
        step_placeholders[n].markdown(
            f'<div class="step-box {css}">{icon} <b>Step {n}</b>  {STEP_NAMES[n]}'
            + (f"  <span style='color:#666;font-size:0.85em'>— {detail}</span>" if detail else "")
            + "</div>",
            unsafe_allow_html=True,
        )

    for i in range(1, 8):
        if i < start_step:
            render_step(i, "skip", "건너뜀")
        else:
            render_step(i, "pending")

    # ⑤ subprocess 실행
    log_box = st.expander("📋 실행 로그", expanded=False)
    log_lines: list[str] = []
    current_step = start_step

    cmd = [
        sys.executable, str(PROJECT_ROOT / "main.py"),
        str(script_file),
        f"--start-step={start_step}",
    ]

    with st.spinner("파이프라인 실행 중..."):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_ROOT),
        )

        with log_box:
            log_placeholder = st.empty()

        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            log_lines.append(line)
            with log_box:
                log_placeholder.code("\n".join(log_lines[-40:]), language="")

            # 스텝 감지
            for n in range(1, 8):
                if f"[Step {n}/7]" in line:
                    if current_step < n:
                        render_step(current_step, "done")
                    current_step = n
                    if "SKIPPED" in line:
                        render_step(n, "skip", "건너뜀")
                    else:
                        render_step(n, "run", "실행 중...")

            if "Pipeline failed" in line or "[ERROR]" in line:
                render_step(current_step, "error", line.split("]", 1)[-1].strip())

        proc.wait()

    if proc.returncode == 0:
        render_step(current_step, "done")
        st.success("✅ 영상 생성 완료!")
    else:
        render_step(current_step, "error")
        st.error("❌ 파이프라인 실패. 로그를 확인하세요.")

    st.divider()

# ── Results ───────────────────────────────────────────────────────────
images = sorted(IMAGES_DIR.glob("segment_*.png")) if IMAGES_DIR.exists() else []

if VIDEO_PATH.exists() or images:
    st.markdown("### 🎬 결과물")

    tab_img, tab_audio, tab_video = st.tabs(["🖼️ 생성 이미지", "🔊 TTS 음성", "🎬 최종 영상"])

    with tab_img:
        if images:
            cols = st.columns(min(len(images), 5))
            for i, p in enumerate(images):
                with cols[i % 5]:
                    st.image(str(p), caption=f"Scene {i+1}", use_container_width=True)
        else:
            st.info("생성된 이미지가 없습니다.")

    with tab_audio:
        if AUDIO_PATH.exists():
            st.audio(str(AUDIO_PATH))
            st.caption(f"파일: {AUDIO_PATH.name}")
        else:
            st.info("생성된 음성이 없습니다.")

    with tab_video:
        if VIDEO_PATH.exists():
            st.video(str(VIDEO_PATH))
            with open(VIDEO_PATH, "rb") as f:
                st.download_button(
                    "⬇️ MP4 다운로드",
                    f,
                    file_name="final_video.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                )
        else:
            st.info("생성된 영상이 없습니다.")
