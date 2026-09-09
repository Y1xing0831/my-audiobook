import asyncio
import streamlit as st
import edge_tts

# 1. 設定網頁頁面標題與圖示
st.set_page_config(page_title="AI 有聲書轉換器", page_icon="🎧", layout="centered")

# 2. 注入 iOS 主畫面 Icon 的 HTML 標籤
st.markdown(
    """
    <head>
        <link rel="apple-touch-icon" sizes="180x180" href="/app/static/apple-touch-icon.png">
        <link rel="apple-touch-icon-precomposed" href="/app/static/apple-touch-icon.png">
    </head>
    """,
    unsafe_allow_html=True
)

st.title("🎧 AI 有聲書轉檔神器")
st.caption("將長篇文字檔輕鬆轉為自然流暢的 AI 語音 MP3")

# 可選的聲線清單
VOICES = {
    "台灣女聲 - 曉臻 (HsiaoChen)": "zh-TW-HsiaoChenNeural",
    "台灣男聲 - 雲哲 (YunJhe)": "zh-TW-YunJheNeural",
    "台灣女聲 - 曉涵 (HsiaoYu)": "zh-TW-HsiaoYuNeural",
    "普通話女聲 - 曉曉 (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",
    "普通話男聲 - 雲希 (Yunxi)": "zh-CN-YunxiNeural",
}

# 異步合成語音函式
async def text_to_speech(text, voice_code):
    communicate = edge_tts.Communicate(text, voice_code)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data

# UI 佈局：檔案上傳與選項
uploaded_file = st.file_uploader("請上傳文字檔 (.txt)", type=["txt"])
selected_voice = st.selectbox("選擇喜歡的聲線：", list(VOICES.keys()))

if uploaded_file is not None:
    # 讀取文字內容
    text_content = uploaded_file.read().decode("utf-8")
    
    st.subheader("📄 文本預覽")
    st.text_area("上傳內容：", text_content, height=150)

    # 轉換按鈕
    if st.button("🚀 開始轉換成有聲書", type="primary"):
        if not text_content.strip():
            st.warning("檔案內容為空！")
        else:
            with st.spinner("AI 正在為您朗讀並合成語音中，請稍候..."):
                voice_code = VOICES[selected_voice]
                # 執行語音轉換
                audio_bytes = asyncio.run(text_to_speech(text_content, voice_code))
                
                st.success("🎉 轉換完成！")
                
                # 試聽播放器
                st.audio(audio_bytes, format="audio/mp3")
                
                # 下載按鈕
                st.download_button(
                    label="⬇️ 下載 MP3 檔案",
                    data=audio_bytes,
                    file_name=f"audiobook_{uploaded_file.name.replace('.txt', '')}.mp3",
                    mime="audio/mp3"
                )
