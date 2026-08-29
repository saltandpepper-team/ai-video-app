import streamlit as st
from google import genai
import json
import time
import tempfile
from moviepy.editor import VideoFileClip

# 画面のデザイン設定
st.set_page_config(page_title="AIショート動画職人", page_icon="✂️")
st.title("✂️ AIショート動画 自動切り抜きアプリ")
st.write("10分の動画をアップロードするだけで、バズるシーンをAIが自動で切り抜きます！")

# 1. APIキーと動画の入力エリア
api_key = st.text_input("Google AI StudioのAPIキーを入力（AQ.から始まるキー）", type="password")
uploaded_file = st.file_uploader("動画ファイルを選択 (MP4など)", type=["mp4", "mov"])

# 「切り抜き開始」ボタンが押された時の処理
if st.button("切り抜きを開始する"):
    if not api_key or not uploaded_file:
        st.warning("APIキーと動画ファイルを両方セットしてください。")
    else:
        try:
            status_text = st.empty()
            progress_bar = st.progress(0)
            
            # 最新のGeminiクライアントの準備
            client = genai.Client(api_key=api_key)
            
            status_text.text("動画を一時保存しています...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
                tmp_file.write(uploaded_file.read())
                video_path = tmp_file.name

            # 2. Geminiへアップロード
            status_text.text("AIに動画を送信中... (数分かかる場合があります)")
            progress_bar.progress(20)
            
            video_file = client.files.upload(file=video_path)

            # 動画の処理完了を待機
            while True:
                video_file = client.files.get(name=video_file.name)
                state = str(video_file.state)
                if "PROCESSING" in state:
                    time.sleep(5)
                elif "FAILED" in state:
                    st.error("AIでの動画処理に失敗しました。")
                    st.stop()
                else:
                    break

            # 3. AIにプロンプトを送信
            status_text.text("AIが面白いシーンを探しています...")
            progress_bar.progress(50)
            
            prompt = """
            あなたはプロの動画編集者です。
            アップロードされた動画から、TikTokやYouTubeショートでバズるような、最も面白くて惹きつけられるシーンを3つ抽出してください。
            出力は以下のJSONフォーマットのみとし、Markdownの装飾は一切含めないでください。
            [{"start": 15, "end": 45, "title": "シーンのタイトル1"}]
            """
            
            response = client.models.generate_content(
                model="gemini-3.7-flash",
                contents=[video_file, prompt]
            )

            # JSONの解析
            json_text = response.text.replace("```json", "").replace("```", "").strip()
            highlights = json.loads(json_text)
            
            # 4. 動画の切り抜き処理
            status_text.text("AIがシーンを見つけました！動画の切り抜きを開始します...")
            progress_bar.progress(70)
            
            original_clip = VideoFileClip(video_path)
            (w, h) = original_clip.size
            target_w = h * 9 / 16  
            
            created_files = []
            
            for i, highlight in enumerate(highlights):
                start_t, end_t, title = highlight["start"], highlight["end"], highlight["title"]
                output_filename = f"short_{i+1}.mp4"
                
                status_text.text(f"「{title}」を作成中... ({i+1}/{len(highlights)})")
                
                subclip = original_clip.subclip(start_t, end_t)
                cropped_clip = subclip.crop(x_center=w/2, y_center=h/2, width=target_w, height=h)
                cropped_clip.write_videofile(output_filename, codec="libx264", audio_codec="aac", logger=None)
                
                created_files.append((output_filename, title))
            
            original_clip.close()
            client.files.delete(name=video_file.name)
            
            # 5. 完成と画面への表示
            progress_bar.progress(100)
            status_text.success("🎉 すべてのショート動画が完成しました！")
            
            st.subheader("完成した動画")
            for file_name, title in created_files:
                st.write(f"**{title}**")
                st.video(file_name)
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")