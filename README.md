# AIショート動画職人

Streamlit アプリを Firebase プロジェクト `pstclondrina`（PSTCLondrina-Sns tool）で公開する構成です。

- 公開URL: https://pstc-londrina-ai-video.web.app （Firebase Hosting）
- アプリ本体: Cloud Run サービス `pstc-londrina-ai-video`（asia-northeast1）
- Firestore: `(default)` データベース。切り抜き履歴を `clip_jobs` コレクションに保存

Streamlit は WebSocket を使うため Firebase Hosting のリライトでは動きません。
そのため Hosting のページが Cloud Run の URL を iframe で全画面表示する構成にしています。

## 初回セットアップ

1. Google Cloud コンソール（プロジェクト `pstclondrina`）で「IAM と管理 → サービスアカウント」を開き、
   デプロイ用サービスアカウントを作成して次のロールを付与する
   - 編集者（Editor）
   - Firebase 管理者
   - Secret Manager 管理者
   - Cloud Run 管理者
   - プロジェクト IAM 管理者（実行用アカウントへの権限付与に使用）
2. そのサービスアカウントの JSON キーを作成する
3. GitHub リポジトリの Settings → Secrets and variables → Actions に次を登録する
   - `GCP_SA_KEY`: 手順2の JSON キーの中身
   - `GEMINI_API_KEY`: Gemini の API キー
4. Actions タブで「Deploy to Firebase (pstclondrina)」を手動実行する（以後は main への push で自動デプロイ）

初回実行時に Firestore データベース（asia-northeast1）と Hosting サイト `pstc-londrina-ai-video` が自動作成されます。
Firestore の場所は作成後に変更できないため、変える場合は初回実行前に `.github/workflows/deploy.yml` の `FIRESTORE_LOCATION` を編集してください。

## 注意

- Cloud Run の制限で、アップロードできる動画は 32MB までです。
- ローカル実行時は `.streamlit/secrets.toml` に `GEMINI_API_KEY` を書くか、環境変数で渡してください。
