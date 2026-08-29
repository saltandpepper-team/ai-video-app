import streamlit as st
from google import genai
import json
import time
import tempfile
from moviepy.editor import VideoFileClip

# 画面のデザイン設定
st.set_page_config(page_title="AIショート動画職人", page_icon="✂️")
st.title("✂️ AIショート動画 自動切り抜きアプリ")
st.warning("⚠️ 無料サーバーの制限により、動画は50MB以下（約3〜5分以内）を推奨します。重い動画はフリーズする可能性があります。")

# 1. 基本入力エリア
api_key = st.text_input("Google AI StudioのAPIキーを入力（AQ.から始まるキー）", type="password")
uploaded_file = st.file_uploader("動画ファイルを選択 (MP4など)", type=["mp4", "mov"])

# 2. モード選択
st.markdown("---")
mode = st.radio("切り抜きの方法を選んでください", ["🤖 AIにおまかせ", "⏱️ 手動で時間を指定"])

# 手動モードの場合の入力欄
manual_cuts = ""
if mode == "⏱️ 手動で時間を指定":
    st.info("切り抜きたい時間を「開始秒-終了秒」の形式で入力してください。複数ある場合はカンマ（,）で区切ります。")
    manual_cuts = st.text_input("入力例：60-90, 343-363", "60-90")

st.markdown("---")

# 切り抜き処理
if st.button("切り抜きを開始する"):
    if not api_key or not uploaded_file:
        st.warning("APIキーと動画ファイルを両方セットしてください。")
    elif mode == "⏱️ 手動で時間を指定" and not manual_cuts:
        st.warning("切り抜きたい時間を入力してください。")
    else:
        try:
            status_text = st.empty()
            progress_bar = st.progress(0)
            client = genai.Client(api_key=api_key)
            
            # 動画の一時保存
            status_text.text("動画をシステムに読み込んでいます...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
                tmp_file.write(uploaded_file.read())
                video_path = tmp_file.name
            progress_bar.progress(20)

            highlights = []

            # ==========================================
            # A. AIにおまかせモード
            # ==========================================
            if mode == "🤖 AIにおまかせ":
                status_text.text("AIに動画を送信中... (数分かかる場合があります)")
                video_file = client.files.upload(file=video_path)

                while True:
                    check_file = client.files.get(name=video_file.name)
                    state = str(check_file.state)
                    if "PROCESSING" in state:
                        time.sleep(5)
                    elif "FAILED" in state:
                        st.error("AIでの動画処理に失敗しました。")
                        st.stop()
                    else:
                        break

                status_text.text("AIがスポーツのハイライトシーンを分析しています...")
                progress_bar.progress(50)
                
                # プロンプト（指示）を大幅に強化
                prompt = """
                あなたはプロのスポーツ動画編集者です。アップロードされた動画を解析し、以下の指示に厳密に従ってください。
                1. SNSで盛り上がるハイライトシーン（ゴール、素晴らしいパス、好プレイなど）を3つ抽出してください。
                2. 【重要】動画内に「実際に存在するシーン」の開始秒数と終了秒数（タイムスタンプ）を正確に指定してください。架空のプレイを捏造しないでください。
                3. 【重要】映像の内容に忠実なタイトルをつけてください。
                4. 出力は以下のJSONフォーマットのみとしてください。Markdownは不要です。
                [{"start": 15, "end": 45, "title": "素晴らしいロングパス"}]
                """
                
                response = client.models.generate_content(
                    model="gemini-3.7-flash",
                    contents=[video_file, prompt]
                )

                json_text = response.text.replace("```json", "").replace("```", "").strip()
                highlights = json.loads(json_text)
                
                # AI側の動画ファイルを削除
                client.files.delete(name=video_file.name)

            # ==========================================
            # B. 手動指定モード
            # ==========================================
            else:
                status_text.text("指定された時間を解析しています...")
                progress_bar.progress(50)
                
                # 入力された文字（例: "60-90, 343-363"）を分割してリストにする
                cut_list = manual_cuts.split(",")
                for i, cut in enumerate(cut_list):
                    cut = cut.strip()
                    if "-" in cut:
                        start_t, end_t = cut.split("-")
                        highlights.append({
                            "start": int(start_t.strip()),
                            "end": int(end_t.strip()),
                            "title": f"手動切り抜きシーン {i+1}"
                        })

            # ==========================================
            # 共通: 動画のカット処理（見切れ防止のためクロップ廃止）
            # ==========================================
            status_text.text("動画の切り出しを開始します...")
            progress_bar.progress(70)
            
            original_clip = VideoFileClip(video_path)
            created_files = []
            
            for i, highlight in enumerate(highlights):
                start_t, end_t, title = highlight["start"], highlight["end"], highlight["title"]
                output_filename = f"short_{i+1}.mp4"
                
                status_text.text(f"「{title}」を作成中... ({i+1}/{len(highlights)})")
                
                # クロップ（画面中央のくり抜き）をやめ、指定秒数でカットするだけにする
                subclip = original_clip.subclip(start_t, end_t)
                subclip.write_videofile(output_filename, codec="libx264", audio_codec="aac", logger=None)
                
                created_files.append((output_filename, title))
            
            original_clip.close()
            
            # 完成
            progress_bar.progress(100)
            status_text.success("🎉 動画の作成が完了しました！")
            
            st.subheader("完成した動画")
            for file_name, title in created_files:
                st.write(f"**{title}**")
                st.video(file_name)
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
