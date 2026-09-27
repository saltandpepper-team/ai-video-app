"""
AIショート動画職人 - Cloud Functions (Python)

Firebase Storage にアップロードされた動画を Gemini で解析し、moviepy で
ハイライトシーンを切り抜いて Storage に書き戻す。進捗と結果は Firestore の
clip_jobs/{jobId} ドキュメントに書き込み、フロントエンドはそれを
リアルタイム購読して表示する。
"""

import json
import os
import re
import shutil
import time

from firebase_admin import firestore, initialize_app, storage
from firebase_functions import https_fn, options
from google import genai

initialize_app()

REGION = "asia-northeast1"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # storage.rules と合わせる

HIGHLIGHT_PROMPT = """
あなたはプロのスポーツ動画編集者です。アップロードされた動画を解析し、以下の指示に厳密に従ってください。
1. SNSで盛り上がるハイライトシーン（ゴール、素晴らしいパス、好プレイなど）を3つ抽出してください。
2. 【重要】動画内に「実際に存在するシーン」の開始秒数と終了秒数（タイムスタンプ）を正確に指定してください。架空のプレイを捏造しないでください。
3. 【重要】映像の内容に忠実なタイトルをつけてください。
4. 出力は以下のJSONフォーマットのみとしてください。Markdownは不要です。
[{"start": 15, "end": 45, "title": "素晴らしいロングパス"}]
"""


def _update_job(job_ref, **fields):
    fields["updated_at"] = firestore.SERVER_TIMESTAMP
    job_ref.set(fields, merge=True)


def _parse_manual_cuts(manual_cuts: str) -> list[dict]:
    highlights = []
    for i, cut in enumerate(manual_cuts.split(",")):
        cut = cut.strip()
        if "-" not in cut:
            continue
        start_t, end_t = cut.split("-", 1)
        highlights.append({
            "start": int(start_t.strip()),
            "end": int(end_t.strip()),
            "title": f"手動切り抜きシーン {i + 1}",
        })
    return highlights


def _run_ai_analysis(video_path: str) -> list[dict]:
    api_key = os.environ["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
    video_file = client.files.upload(file=video_path)

    while True:
        check_file = client.files.get(name=video_file.name)
        state = str(check_file.state)
        if "PROCESSING" in state:
            time.sleep(5)
        elif "FAILED" in state:
            raise RuntimeError("AIでの動画処理に失敗しました。")
        else:
            break

    response = client.models.generate_content(
        model="gemini-3.7-flash",
        contents=[video_file, HIGHLIGHT_PROMPT],
    )
    json_text = response.text.replace("```json", "").replace("```", "").strip()
    highlights = json.loads(json_text)
    client.files.delete(name=video_file.name)
    return highlights


@https_fn.on_call(
    region=REGION,
    memory=options.MemoryOption.GB_2,
    cpu=2,
    timeout_sec=1800,
    secrets=["GEMINI_API_KEY"],
)
def process_video(req: https_fn.CallableRequest) -> dict:
    if req.auth is None:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="ログインが必要です。",
        )
    uid = req.auth.uid

    data = req.data or {}
    job_id = str(data.get("jobId", ""))
    storage_path = str(data.get("storagePath", ""))
    mode = data.get("mode")
    manual_cuts = str(data.get("manualCuts", ""))
    file_name = str(data.get("fileName", ""))

    if not job_id or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="jobId が不正です。"
        )

    # 他人のアップロード領域を処理させない
    expected_prefix = f"uploads/{uid}/{job_id}/"
    if not storage_path.startswith(expected_prefix):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="不正なファイルパスです。",
        )

    db = firestore.client()
    job_ref = db.collection("clip_jobs").document(job_id)
    job_ref.set({
        "uid": uid,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "mode": mode,
        "file_name": file_name,
        "status": "downloading",
        "highlights": [],
        "results": [],
    })

    bucket = storage.bucket()
    tmp_dir = f"/tmp/{job_id}"
    os.makedirs(tmp_dir, exist_ok=True)
    video_path = os.path.join(tmp_dir, "input.mp4")

    try:
        blob = bucket.blob(storage_path)
        if blob.size and blob.size > MAX_UPLOAD_BYTES:
            raise RuntimeError("動画サイズが上限(500MB)を超えています。")
        blob.download_to_filename(video_path)

        if mode == "ai":
            _update_job(job_ref, status="analyzing")
            highlights = _run_ai_analysis(video_path)
        else:
            highlights = _parse_manual_cuts(manual_cuts)

        if not highlights:
            raise RuntimeError("切り抜くシーンが見つかりませんでした。")

        _update_job(job_ref, status="cutting", highlights=highlights)

        from moviepy.editor import VideoFileClip

        original_clip = VideoFileClip(video_path)
        results = []
        for i, h in enumerate(highlights):
            start_t, end_t, title = h["start"], h["end"], h["title"]
            out_path = os.path.join(tmp_dir, f"clip_{i + 1}.mp4")

            subclip = original_clip.subclip(start_t, end_t)
            subclip.write_videofile(out_path, codec="libx264", audio_codec="aac", logger=None)
            subclip.close()

            result_path = f"results/{uid}/{job_id}/clip_{i + 1}.mp4"
            bucket.blob(result_path).upload_from_filename(out_path, content_type="video/mp4")
            results.append({"path": result_path, "title": title, "start": start_t, "end": end_t})

            _update_job(job_ref, status="cutting", results=results)

        original_clip.close()
        _update_job(job_ref, status="done", results=results)
        return {"status": "done"}

    except Exception as e:  # noqa: BLE001 - フロントに理由を伝えるため意図的に広く捕捉
        _update_job(job_ref, status="error", error=str(e))
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INTERNAL, message=str(e))

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        try:
            bucket.blob(storage_path).delete()
        except Exception:
            pass
