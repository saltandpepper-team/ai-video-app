import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
  getAuth, signInAnonymously, onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";
import {
  getFirestore, doc, onSnapshot, collection, query, where, orderBy, limit, getDocs,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore.js";
import {
  getStorage, ref, uploadBytesResumable, getDownloadURL,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-storage.js";
import {
  getFunctions, httpsCallable,
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-functions.js";
import { firebaseConfig } from "./firebase-config.js";

const REGION = "asia-northeast1";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const storage = getStorage(app);
const functions = getFunctions(app, REGION);

const fileInput = document.getElementById("file-input");
const manualCutsArea = document.getElementById("manual-cuts-area");
const manualCutsInput = document.getElementById("manual-cuts");
const startButton = document.getElementById("start-button");
const statusArea = document.getElementById("status-area");
const statusText = document.getElementById("status-text");
const progressFill = document.getElementById("progress-fill");
const resultsCard = document.getElementById("results-card");
const resultsList = document.getElementById("results-list");
const historyList = document.getElementById("history-list");

document.querySelectorAll('input[name="mode"]').forEach((el) => {
  el.addEventListener("change", () => {
    manualCutsArea.classList.toggle("hidden", el.value !== "manual" || !el.checked);
  });
});

let currentUid = null;

onAuthStateChanged(auth, (user) => {
  if (user) {
    currentUid = user.uid;
    loadHistory();
  }
});
signInAnonymously(auth).catch((e) => {
  console.error("匿名ログインに失敗しました", e);
  setStatus("ログインに失敗しました。ページを再読み込みしてください。", true);
});

function setStatus(text, isError = false) {
  statusArea.classList.remove("hidden");
  statusText.textContent = text;
  statusText.classList.toggle("error-text", isError);
}

function setProgress(percent) {
  progressFill.style.width = `${percent}%`;
}

function makeJobId() {
  return (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9-]/g, "");
}

const STATUS_LABELS = {
  downloading: "動画をサーバーに取り込んでいます...",
  analyzing: "AIがハイライトシーンを分析しています...",
  cutting: "動画を切り抜いています...",
  done: "🎉 完成しました！",
  error: "エラーが発生しました",
};
const STATUS_PROGRESS = { downloading: 15, analyzing: 40, cutting: 70, done: 100, error: 0 };

startButton.addEventListener("click", async () => {
  const file = fileInput.files[0];
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const manualCuts = manualCutsInput.value.trim();

  if (!file) {
    setStatus("動画ファイルを選択してください。", true);
    return;
  }
  if (mode === "manual" && !manualCuts) {
    setStatus("切り抜きたい時間を入力してください。", true);
    return;
  }
  if (!currentUid) {
    setStatus("ログイン中です。少し待ってからもう一度お試しください。", true);
    return;
  }

  startButton.disabled = true;
  resultsCard.classList.add("hidden");
  resultsList.innerHTML = "";

  const jobId = makeJobId();
  const storagePath = `uploads/${currentUid}/${jobId}/${file.name}`;

  try {
    setStatus("動画をアップロードしています... 0%");
    setProgress(0);

    const storageRef = ref(storage, storagePath);
    const uploadTask = uploadBytesResumable(storageRef, file, { contentType: file.type || "video/mp4" });

    await new Promise((resolve, reject) => {
      uploadTask.on(
        "state_changed",
        (snapshot) => {
          const pct = Math.round((snapshot.bytesTransferred / snapshot.totalBytes) * 100);
          setStatus(`動画をアップロードしています... ${pct}%`);
          setProgress(pct * 0.3); // アップロードは全体の30%分として表示
        },
        reject,
        resolve,
      );
    });

    // Firestore の更新をリアルタイムで購読して進捗を表示する
    watchJob(jobId);

    const processVideo = httpsCallable(functions, "process_video");
    processVideo({
      jobId,
      storagePath,
      mode,
      manualCuts,
      fileName: file.name,
    }).catch((e) => {
      // 処理自体はサーバー側で継続するため、呼び出し失敗は Firestore の
      // 状態更新を優先し、ここではログのみに留める。
      console.warn("process_video 呼び出しでエラー(処理は継続する場合があります)", e);
    });
  } catch (e) {
    console.error(e);
    setStatus(`アップロードに失敗しました: ${e.message}`, true);
    startButton.disabled = false;
  }
});

function watchJob(jobId) {
  const jobRef = doc(db, "clip_jobs", jobId);
  const unsubscribe = onSnapshot(jobRef, (snap) => {
    if (!snap.exists()) return;
    const job = snap.data();

    if (job.status === "error") {
      setStatus(`エラーが発生しました: ${job.error || ""}`, true);
      startButton.disabled = false;
      unsubscribe();
      return;
    }

    setStatus(STATUS_LABELS[job.status] || job.status);
    setProgress(30 + (STATUS_PROGRESS[job.status] || 0) * 0.7);

    if (job.status === "done") {
      showResults(job.results || []);
      startButton.disabled = false;
      loadHistory();
      unsubscribe();
    }
  }, (e) => {
    console.error("Firestore購読エラー", e);
  });
}

async function showResults(results) {
  resultsCard.classList.remove("hidden");
  resultsList.innerHTML = "";
  for (const r of results) {
    const url = await getDownloadURL(ref(storage, r.path));
    const div = document.createElement("div");
    div.className = "result-item";
    div.innerHTML = `
      <strong>${escapeHtml(r.title)}</strong>（${r.start}〜${r.end}秒）
      <video src="${url}" controls></video>
      <a href="${url}" download>ダウンロード</a>
    `;
    resultsList.appendChild(div);
  }
}

async function loadHistory() {
  try {
    const q = query(
      collection(db, "clip_jobs"),
      where("uid", "==", currentUid),
      orderBy("created_at", "desc"),
      limit(10),
    );
    const snaps = await getDocs(q);
    historyList.innerHTML = "";
    snaps.forEach((snap) => {
      const job = snap.data();
      const created = job.created_at?.toDate ? job.created_at.toDate().toLocaleString("ja-JP") : "";
      const div = document.createElement("div");
      div.className = "history-item";
      const highlightsText = (job.highlights || [])
        .map((h) => `${h.start}〜${h.end}秒: ${escapeHtml(h.title)}`)
        .join("<br>");
      div.innerHTML = `<strong>${escapeHtml(job.file_name || "")}</strong>（${escapeHtml(job.mode || "")}） ${created}<br>${highlightsText}`;
      historyList.appendChild(div);
    });
  } catch (e) {
    console.error("履歴の取得に失敗しました", e);
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
