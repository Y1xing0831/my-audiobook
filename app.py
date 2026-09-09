import asyncio
import io
import struct
import streamlit as st
import edge_tts
from pypdf import PdfReader
import docx
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

# 1. 頁面佈局與 iOS Icon 注入
st.set_page_config(page_title="AI 多功能有聲書轉檔器", page_icon="📚", layout="centered")

st.markdown(
    """
    <head>
        <link rel="apple-touch-icon" sizes="180x180" href="/app/static/apple-touch-icon.png">
        <link rel="apple-touch-icon-precomposed" href="/app/static/apple-touch-icon.png">
    </head>
    """,
    unsafe_allow_html=True
)

st.title("📚 AI 全格式有聲書轉檔神器")
st.caption("支援 EPUB、PDB、PDF、DOCX、TXT 格式，輕鬆轉為自然流暢的 AI 語音 MP3")

# 聲線清單
VOICES = {
    "台灣女聲 - 曉臻 (HsiaoChen)": "zh-TW-HsiaoChenNeural",
    "台灣男聲 - 雲哲 (YunJhe)": "zh-TW-YunJheNeural",
    "台灣女聲 - 曉涵 (HsiaoYu)": "zh-TW-HsiaoYuNeural",
    "普通話女聲 - 曉曉 (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",
    "普通話男聲 - 雲希 (Yunxi)": "zh-CN-YunxiNeural",
}

# PDB 檔案專用解析函式
def parse_pdb(file_bytes: bytes) -> str:
    try:
        # PDB 標頭資訊解析
        num_records = struct.unpack(">H", file_bytes[76:78])[0]
        record_offsets = []
        for i in range(num_records):
            offset = struct.unpack(">I", file_bytes[78 + i * 8 : 82 + i * 8])[0]
            record_offsets.append(offset)
            
        text_chunks = []
        for i in range(num_records):
            start = record_offsets[i]
            end = record_offsets[i + 1] if i + 1 < num_records else len(file_bytes)
            chunk = file_bytes[start:end]
            text_chunks.append(chunk)
            
        raw_data = b"".join(text_chunks)
        
        # 嘗試以常見的中文編碼解碼 (Big5 / UTF-8 / GB18030)
        for encoding in ["cp950", "big5", "utf-8", "gb18030", "utf-16"]:
            try:
                decoded = raw_data.decode(encoding)
                # 過濾非列印控制字元
                clean_text = "".join(char for char in decoded if char.isprintable() or char in "\n\r\t")
                if len(clean_text) > 10:
                    return clean_text
            except UnicodeDecodeError:
                continue
        return raw_data.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"PDB 解析失敗: {str(e)}"

# 通用文本解析函式
def extract_text(file) -> str:
    filename = file.name.lower()
    text = ""
    
    if filename.endswith(".txt"):
        text = file.read().decode("utf-8", errors="ignore")
        
    elif filename.endswith(".pdb"):
        file_bytes = file.read()
        text = parse_pdb(file_bytes)
        
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

# 語音合成函式
async def text_to_speech(text, voice_code):
    communicate = edge_tts.Communicate(text, voice_code)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# 介面佈局
uploaded_file = st.file_uploader(
    "上傳書籍檔案 (支援 .txt, .pdb, .epub, .pdf, .docx)", 
    type=["txt", "pdb", "epub", "pdf", "docx"]
)
selected_voice = st.selectbox("選擇喜歡的聲線：", list(VOICES.keys()))

if uploaded_file is not None:
    with st.spinner("正在解析書籍檔案內容..."):
        text_content = extract_text(uploaded_file)
        
    if not text_content or text_content.startswith("PDB 解析失敗"):
        st.error("無法從檔案中提取出文字內容（可能是加密、損壞或不支援的 PDB 格式）。")
    else:
        st.subheader("📄 內容預覽")
        st.text_area("提取文字（前 1000 字）：", text_content[:1000] + ("..." if len(text_content) > 1000 else ""), height=180)
        
        if st.button("🚀 開始轉換成有聲書", type="primary"):
            with st.spinner("AI 正在合成語音中，長篇書籍需稍作等待..."):
                voice_code = VOICES[selected_voice]
                audio_bytes = asyncio.run(text_to_speech(text_content, voice_code))
                
                st.success("🎉 轉換完成！")
                st.audio(audio_bytes, format="audio/mp3")
                
                base_name = uploaded_file.name.rsplit(".", 1)[0]
                st.download_button(
                    label="⬇️ 下載完整 MP3 檔案",
                    data=audio_bytes,
                    file_name=f"audiobook_{base_name}.mp3",
                    mime="audio/mp3"
                )
