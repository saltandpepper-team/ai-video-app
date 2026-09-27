# AIショート動画職人

Firebase プロジェクト `pstclondrina`（PSTCLondrina-Sns tool）だけで完結する構成です。
Cloud Run は使わず、Firebase Hosting / Firebase Functions（Python） / Firestore /
Firebase Storage / Firebase Authentication（匿名ログイン）で動作します。

- 公開URL: https://pstc-londrina-ai-video.web.app
- アップロード・結果の保存先: Firebase Storage（`uploads/`, `results/`）
- 解析・切り抜き処理: Firebase Functions（Python, `asia-northeast1`）
- 履歴・進捗の管理: Firestore（`clip_jobs` コレクション）

## 構成の考え方

Streamlit（Pythonで画面もサーバーも兼ねる仕組み）は「動き続けるサーバー」が
必要で、Firebase Hosting だけでは動かせません。そこで画面を素朴な HTML/JS に
作り替え、次の流れにしました。

1. ブラウザから **Firebase Storage に直接動画をアップロード**（Cloud Run/Functions
   を経由しないので、Cloud Run にあった 32MB の壁がなく、大きい動画でも扱えます）
2. アップロード完了後、`process_video` という Cloud Function を呼び出す
3. Function が Storage から動画を取得し、Gemini で解析（AIおまかせモード）または
   指定秒数（手動モード）に従って moviepy で切り抜く
4. 進捗・結果は Firestore の `clip_jobs/{jobId}` に書き込み、画面はそれを
   リアルタイムに購読して表示する
5. 完成した動画は Storage の `results/` に保存され、そこからダウンロードする

他人のファイルを見られないよう、匿名ログイン（Firebase Authentication）で
利用者ごとに `uid` を持たせ、Firestore/Storage のセキュリティルールで
「自分の uid のデータだけ読める」ように制限しています。

## 初回セットアップ

1. Google Cloud コンソール（プロジェクト `pstclondrina`）で「IAM と管理 →
   サービスアカウント」を開き、デプロイ用サービスアカウントを作成して
   「編集者」ロールを付与する（Functions/Hosting/Firestore/Storage/Secret Manager
   をまとめて操作するため）
2. そのサービスアカウントの JSON キーを作成する
3. GitHub リポジトリの Settings → Secrets and variables → Actions に次を登録する
   - `GCP_SA_KEY`: 手順2の JSON キーの中身
   - `GEMINI_API_KEY`: Gemini の API キー
4. Firebase コンソール → Authentication → Sign-in method で
   **「匿名」を有効化**する（これだけは手動での一回限りの設定です）
5. Actions タブで「Deploy to Firebase (pstclondrina)」を手動実行する
   （以後は main への push で自動デプロイ）

初回実行時に Firestore データベース（asia-northeast1）と Hosting サイト
`pstc-londrina-ai-video` が自動作成されます。Firestore の場所は作成後に
変更できないため、変える場合は初回実行前に `.github/workflows/deploy.yml` の
`FIRESTORE_LOCATION` を編集してください。

## 注意

- 動画アップロードは 500MB まで（`storage.rules` / `functions/main.py` の
  `MAX_UPLOAD_BYTES` で変更可能）
- ローカルでの動作確認は `firebase emulators:start` を利用してください
  （`functions/requirements.txt` を仮想環境にインストールした上で）
