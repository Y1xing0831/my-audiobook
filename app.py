import asyncio
import base64
import os
import re
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

st.set_page_config(page_title="Speechify AI Web Reader", page_icon="🎧", layout="wide")

# 聲線清單
VOICES = {
    "台灣女聲 - 曉臻": "zh-TW-HsiaoChenNeural",
    "台灣男聲 - 雲哲": "zh-TW-YunJheNeural",
    "台灣女聲 - 曉涵": "zh-TW-HsiaoYuNeural",
    "普通話女聲 - 曉曉": "zh-CN-XiaoxiaoNeural",
    "普通話男聲 - 雲希": "zh-CN-YunxiNeural",
}

# --- 解析器模組 ---
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
    return "PDB 解析失敗"

def parse_mobi(file_bytes: bytes) -> str:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mobi") as tmp_in:
            tmp_in.write(file_bytes)
            tmp_in_path = tmp_in.name
        tempdir, filepath = mobi.extract(tmp_in_path)
        text = ""
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                raw = f.read()
                detected = chardet.detect(raw[:5000])
                enc = detected.get("encoding") or "utf-8"
                soup = BeautifulSoup(raw.decode(enc, errors="ignore"), "html.parser")
                text = soup.get_text()
        os.remove(tmp_in_path)
        return text
    except Exception as e:
        return f"MOBI 解析失敗: {str(e)}"

def extract_text(file) -> str:
    filename = file.name.lower()
    text = ""
    if filename.endswith(".txt"):
        raw = file.read()
        detected = chardet.detect(raw[:5000])
        enc = detected.get("encoding") or "utf-8"
        text = raw.decode(enc, errors="ignore")
    elif filename.endswith(".pdb"):
        text = parse_pdb_robust(file.read())
    elif filename.endswith(".mobi"):
        text = parse_mobi(file.read())
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

# 將文章切分為句子（Speechify 逐句流式高亮的核心基礎）
def split_into_sentences(text):
    sentences = re.split(r'(?<=[。！？；!?;\n])', text)
    cleaned = [s.strip() for s in sentences if s.strip()]
    return cleaned

async def generate_sentence_audio(text, voice_code, rate_str):
    communicate = edge_tts.Communicate(text, voice_code, rate=rate_str)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode("utf-8")

# --- UI 樣式注入 ---
st.markdown("""
<style>
    /* 全頁 Speechify 乾淨風格 */
    .main { background-color: #fcfcfc; }
    
    /* 閱讀器容器 */
    .speechify-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 40px 20px 120px 20px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 22px;
        line-height: 2.0;
        color: #2c3e50;
    }

    /* 句子節點 */
    .sentence {
        padding: 3px 6px;
        margin: 0 2px;
        border-radius: 6px;
        cursor: pointer;
        transition: all 0.2s ease;
        display: inline;
    }

    .sentence:hover {
        background-color: #e8f4ff;
        color: #0066cc;
    }

    /* 當前播放高亮 (Speechify 經典黃藍配色) */
    .sentence.active {
        background-color: #ffe885 !important;
        color: #000000 !important;
        font-weight: 600;
        box-shadow: 0 2px 8px rgba(255, 200, 0, 0.4);
    }

    /* 頂部導覽列 */
    .speechify-header {
        text-align: center;
        padding: 20px 0;
        border-bottom: 1px solid #eee;
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)

# 側邊欄控制
with st.sidebar:
    st.title("🎧 Speechify 設定")
    selected_voice = st.selectbox("朗讀聲音", list(VOICES.keys()))
    speed = st.slider("朗讀速度 (Speed)", min_value=0.8, max_value=2.5, value=1.2, step=0.1)
    speed_percent = f"{int((speed - 1.0) * 100):+d}%"
    st.info(f"⚡ 當前語速設定：**{speed}x**")

st.title("📖 Speechify 互動閱讀器")

uploaded_file = st.file_uploader("上傳書籍檔案 (.txt, .pdb, .mobi, .epub, .pdf, .docx)", type=["txt", "pdb", "mobi", "epub", "pdf", "docx"])

if uploaded_file:
    with st.spinner("正在優化書籍結構與進行智慧斷句..."):
        raw_text = extract_text(uploaded_file)
        sentences = split_into_sentences(raw_text)

    st.success(f"書籍載入完成，共解析出 {len(sentences)} 個語音句段！")

    # 為前 50 句生成即時音訊數據（提升預載速度）
    # 在前端透過 JavaScript 控制連續播放與即時點擊高亮
    if "audio_cache" not in st.session_state:
        st.session_state.audio_cache = {}

    voice_code = VOICES[selected_voice]

    # 批次預合成音訊 (非同步極速處理)
    with st.spinner("⚡ Speechify 引擎正在極速預載語音..."):
        async def prepare_audios():
            tasks = [generate_sentence_audio(s, voice_code, speed_percent) for s in sentences[:30]] # 先預載前30句
            return await asyncio.gather(*tasks)
        
        audio_b64_list = asyncio.run(prepare_audios())

    # 構建純 HTML/JS Speechify 互動元件
    sentences_json = []
    for idx, (s, b64) in enumerate(zip(sentences[:30], audio_b64_list)):
        sentences_json.append({
            "id": idx,
            "text": s,
            "audio": f"data:audio/mp3;base64,{b64}"
        })

    # 使用 HTML/JS 渲染 Speechify 控制器與高亮文字
    import json
    data_manifest = json.dumps(sentences_json)

    speechify_html = f"""
    <div class="speechify-container" id="reader-container">
        <div id="text-body"></div>
    </div>

    <!-- 底部 Speechify 懸浮控制 Bar -->
    <div id="speechify-bar" style="
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%);
        width: 90%;
        max-width: 650px;
        background: #1e1e1e;
        color: white;
        padding: 12px 25px;
        border-radius: 40px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        z-index: 9999;
    ">
        <button id="btn-prev" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">⏮️</button>
        <button id="btn-play" style="background:#0066cc;border:none;color:white;font-size:22px;padding:8px 20px;border-radius:20px;cursor:pointer;">▶️ 播放</button>
        <button id="btn-next" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">⏭️</button>
        <span id="progress-text" style="font-size:14px;color:#ccc;">1 / {len(sentences_json)}</span>
    </div>

    <audio id="global-audio" style="display:none;"></audio>

    <script>
        const manifest = {data_manifest};
        let currentIndex = 0;
        let isPlaying = false;
        
        const textBody = document.getElementById('text-body');
        const audioPlayer = document.getElementById('global-audio');
        const playBtn = document.getElementById('btn-play');
        const prevBtn = document.getElementById('btn-prev');
        const nextBtn = document.getElementById('btn-next');
        const progressText = document.getElementById('progress-text');

        // 1. 渲染句子並綁定 Speechify 點擊跳躍事件
        manifest.forEach((item, index) => {{
            const span = document.createElement('span');
            span.className = 'sentence';
            span.id = 'sentence-' + index;
            span.innerText = item.text + ' ';
            span.onclick = () => playSentence(index);
            textBody.appendChild(span);
        }});

        // 2. 播放指定句子（高亮 + 自動滾動）
        function playSentence(index) {{
            if (index < 0 || index >= manifest.length) return;
            
            // 移除舊高亮
            document.querySelectorAll('.sentence').forEach(el => el.classList.remove('active'));
            
            currentIndex = index;
            const currentItem = manifest[index];
            const activeSpan = document.getElementById('sentence-' + index);
            
            // 加入新高亮
            activeSpan.classList.add('active');
            
            // Speechify 智慧平滑自動捲動
            activeSpan.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            
            // 載入音訊並播放
            audioPlayer.src = currentItem.audio;
            audioPlayer.play();
            isPlaying = true;
            playBtn.innerText = '⏸️ 暫停';
            progressText.innerText = (index + 1) + ' / ' + manifest.length;
        }}

        // 3. 自動接續下一句 (Speechify 無縫播放)
        audioPlayer.onended = () => {{
            if (currentIndex + 1 < manifest.length) {{
                playSentence(currentIndex + 1);
            }} else {{
                isPlaying = false;
                playBtn.innerText = '▶️ 播放';
            }}
        }};

        // 4. 控制 Bar 按鈕事件
        playBtn.onclick = () => {{
            if (isPlaying) {{
                audioPlayer.pause();
                isPlaying = false;
                playBtn.innerText = '▶️ 播放';
            }} else {{
                if (!audioPlayer.src) {{
                    playSentence(0);
                }} else {{
                    audioPlayer.play();
                    isPlaying = true;
                    playBtn.innerText = '⏸️ 暫停';
                }}
            }}
        }};

        prevBtn.onclick = () => playSentence(currentIndex - 1);
        nextBtn.onclick = () => playSentence(currentIndex + 1);
    </script>
    """

    st.components.v1.html(speechify_html, height=700, scrolling=True)
