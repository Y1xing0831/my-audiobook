import asyncio
import io
import os
import re
import struct
import tempfile
import streamlit as st
import edge_tts
from pypdf import PdfReader
import docx
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import chardet
import mobi

# 1. 頁面佈局與 Speechify 風格 CSS 注入
st.set_page_config(page_title="Speechify AI 閱讀器", page_icon="🎧", layout="wide")

st.markdown(
    """
    <head>
        <link rel="apple-touch-icon" sizes="180x180" href="/app/static/apple-touch-icon.png">
        <link rel="apple-touch-icon-precomposed" href="/app/static/apple-touch-icon.png">
    </head>
    <style>
    .highlight-box {
        background-color: #f0f7ff;
        border-left: 6px solid #0066cc;
        padding: 20px;
        font-size: 20px;
        line-height: 1.8;
        border-radius: 8px;
        margin-top: 15px;
        margin-bottom: 20px;
        color: #1a1a1a;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    .stAudio { margin-top: 10px; }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("🎧 AI 邊聽邊讀閱讀器 (Speechify Style)")

# 聲線清單
VOICES = {
    "台灣女聲 - 曉臻": "zh-TW-HsiaoChenNeural",
    "台灣男聲 - 雲哲": "zh-TW-YunJheNeural",
    "台灣女聲 - 曉涵": "zh-TW-HsiaoYuNeural",
    "普通話女聲 - 曉曉": "zh-CN-XiaoxiaoNeural",
    "普通話男聲 - 雲希": "zh-CN-YunxiNeural",
}

# 1. 強效 PDB 解析器
def parse_pdb_robust(file_bytes: bytes) -> str:
    for enc in ["cp950", "big5", "gb18030", "utf-8"]:
        try:
            raw_text = file_bytes.decode(enc, errors="ignore")
            chinese_blocks = re.findall(r'[\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef\w\n\r]{4,}', raw_text)
            combined = "\n".join(chinese_blocks)
            if len(combined) > 50:
                return combined
        except Exception:
            continue
    return "PDB 解析失敗：無法讀取有效的中文文字內容。"

# 2. MOBI 解析器
def parse_mobi(file_bytes: bytes) -> str:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mobi") as tmp_in:
            tmp_in.write(file_bytes)
            tmp_in_path = tmp_in.name

        tempdir, filepath = mobi.extract(tmp_in_path)
        text = ""
        
        # 讀取拆解出來的 html/htmlx/txt 內容
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                raw = f.read()
                detected = chardet.detect(raw[:5000])
                enc = detected.get("encoding") or "utf-8"
                soup = BeautifulSoup(raw.decode(enc, errors="ignore"), "html.parser")
                text = soup.get_text()

        # 清理暫存檔
        os.remove(tmp_in_path)
        return text
    except Exception as e:
        return f"MOBI 解析失敗: {str(e)}"

# 3. 全格式通用文字提取
def extract_text(file) -> str:
    filename = file.name.lower()
    text = ""
    
    if filename.endswith(".txt"):
        raw = file.read()
        detected = chardet.detect(raw[:5000])
        enc = detected.get("encoding") or "utf-8"
        text = raw.decode(enc, errors="ignore")
        
    elif filename.endswith(".pdb"):
        file_bytes = file.read()
        text = parse_pdb_robust(file_bytes)

    elif filename.endswith(".mobi"):
        file_bytes = file.read()
        text = parse_mobi(file_bytes)
        
    elif filename.endswith(".pdf"):
        reader = PdfReader(file)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
                
    elif filename.endswith(".docx"):
        doc = docx.Document(file)
        text = "\n".join([p.text for p in doc.paragraphs if p.text])
        
    elif filename.endswith(".epub"):
        book = epub.read_epub(file)
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_body_content(), "html.parser")
            text += soup.get_text() + "\n"
            
    return text.strip()

# 4. 長文章切分為小段落 (極速預載關鍵)
def split_text_into_chunks(text, max_chars=350):
    sentences = re.split(r'(?<=[。！？\n])', text)
    chunks = []
    current_chunk = ""
    for s in sentences:
        if len(current_chunk) + len(s) <= max_chars:
            current_chunk += s
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = s
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks

# 5. 極速語音合成 (支援語速控制)
async def tts_fast(text, voice_code, rate_str):
    communicate = edge_tts.Communicate(text, voice_code, rate=rate_str)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# 側邊欄：控制中心
with st.sidebar:
    st.header("⚙️ 播放控制中心")
    selected_voice = st.selectbox("朗讀聲線", list(VOICES.keys()))
    
    speed = st.slider("朗讀速度 (Speed)", min_value=0.8, max_value=2.0, value=1.2, step=0.1)
    speed_percent = f"{int((speed - 1.0) * 100):+d}%"
    st.caption(f"當前語速加碼：**{speed_percent}**")

# 檔案上傳 (加入 mobi 支援)
uploaded_file = st.file_uploader(
    "上傳書籍檔案 (支援 .txt, .pdb, .mobi, .epub, .pdf, .docx)", 
    type=["txt", "pdb", "mobi", "epub", "pdf", "docx"]
)

if uploaded_file is not None:
    with st.spinner("正在解析檔案並進行智慧分段..."):
        full_text = extract_text(uploaded_file)
        
    if not full_text or "解析失敗" in full_text:
        st.error("無法提取文字內容，請確認檔案是否毀損或加密。")
    else:
        chunks = split_text_into_chunks(full_text)
        st.success(f"📖 書籍載入成功！已拆分為 {len(chunks)} 個即時朗讀區段。")

        if "current_idx" not in st.session_state:
            st.session_state.current_idx = 0

        # 控制按鈕
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("⬅️ 上一段") and st.session_state.current_idx > 0:
                st.session_state.current_idx -= 1
                st.rerun()
        with col3:
            if st.button("下一段 ➡️") and st.session_state.current_idx < len(chunks) - 1:
                st.session_state.current_idx += 1
                st.rerun()

        idx = st.session_state.current_idx
        current_text = chunks[idx]

        # Speechify 高亮顯示
        st.markdown(f"**閱讀進度：第 {idx + 1} / {len(chunks)} 段**")
        st.markdown(
            f'<div class="highlight-box">💡 <b>當前朗讀：</b><br>{current_text}</div>', 
            unsafe_allow_html=True
        )

        # 極速合成
        with st.spinner("⚡ AI 正在極速合成當前段落語音..."):
            voice_code = VOICES[selected_voice]
            audio_bytes = asyncio.run(tts_fast(current_text, voice_code, speed_percent))
            
            st.audio(audio_bytes, format="audio/mp3", autoplay=True)

        with st.expander("📥 想要下載這段的 MP3 檔？"):
            st.download_button(
                label="⬇️ 下載當前段落 MP3",
                data=audio_bytes,
                file_name=f"section_{idx+1}.mp3",
                mime="audio/mp3"
            )
