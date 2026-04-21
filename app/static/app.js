/**
 * Research Agent — Web UI JavaScript
 *
 * Логіка:
 *  1. Відправка запиту → підключення до SSE /stream?query=...
 *  2. Рендеринг повідомлень по агентах (кольори, collapsed tool calls)
 *  3. HITL картка при interrupt → POST /approve або /reject
 *  4. Markdown preview (marked.js) у правій панелі
 *  5. History sidebar → GET /sessions
 *
 * EventSource (SSE):
 *  - Аналогія Java: SSE client у JAX-RS / Retrofit EventSource
 *  - Однонаправлений push від сервера
 *  - Автоматично перепідключається (не потрібно в нашому випадку)
 */

// ─── Стан ─────────────────────────────────────────────────
const state = {
  sessionId: null,          // поточний session_id (отримуємо від сервера)
  es: null,                 // EventSource з'єднання
  busy: false,              // true поки агент виконується
  hitlPending: false,       // true поки є активний HITL interrupt
  reportContent: "",        // поточний Markdown звіт для preview
  reportFilename: null,     // назва файлу звіту (для Download)
};

// ─── DOM refs ──────────────────────────────────────────────
const chatLog       = document.getElementById("chat-log");
const queryInput    = document.getElementById("query-input");
const inputForm     = document.getElementById("input-form");
const btnSend       = document.getElementById("btn-send");
const btnNewChat    = document.getElementById("btn-new-chat");
const hitlCard      = document.getElementById("hitl-card");
const hitlFilename  = document.getElementById("hitl-filename");
const hitlSize      = document.getElementById("hitl-size");
const hitlPreview   = document.getElementById("hitl-preview");
const btnApprove    = document.getElementById("btn-approve");
const btnReject     = document.getElementById("btn-reject");
const previewContent = document.getElementById("preview-content");
const btnDownload   = document.getElementById("btn-download");
const sessionList   = document.getElementById("session-list");


// ─── Ініціалізація ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  fetchSessions();
  inputForm.addEventListener("submit", onSubmit);
  btnNewChat.addEventListener("click", onNewChat);
  btnApprove.addEventListener("click", () => sendHitlDecision("approve"));
  btnReject.addEventListener("click", () => sendHitlDecision("reject"));

  // Enter надсилає, Shift+Enter — новий рядок
  queryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      inputForm.dispatchEvent(new Event("submit"));
    }
  });
});


// ─── Надсилання запиту ──────────────────────────────────────
function onSubmit(e) {
  e.preventDefault();
  const query = queryInput.value.trim();
  if (!query || state.busy) return;

  // Скидаємо preview і state
  clearPreview();
  clearChat();

  // Показуємо запит у чаті
  appendUserMessage(query);

  queryInput.value = "";
  setBusy(true);

  // Підключаємось до SSE
  startStream(query);
}


// ─── SSE стрімінг ───────────────────────────────────────────
function startStream(query) {
  // Закриваємо попередній EventSource якщо є
  if (state.es) {
    state.es.close();
    state.es = null;
  }

  const url = `/stream?query=${encodeURIComponent(query)}`;

  // EventSource — браузерний SSE клієнт
  // Автоматично підключається і читає "data: <json>\n\n" рядки
  const es = new EventSource(url);
  state.es = es;

  // session_start — отримуємо session_id для HITL
  es.addEventListener("session_start", (e) => {
    const data = JSON.parse(e.data);
    state.sessionId = data.session_id;
    console.log("Session:", state.sessionId);
  });

  // agent_message — текст відповіді агента
  es.addEventListener("agent_message", (e) => {
    const data = JSON.parse(e.data);
    if (data.content) {
      const node = data.node || "supervisor";
      appendAgentMessage(node, data.content);

      // Якщо це великий Markdown — оновлюємо preview
      if (data.content.length > 200 && data.content.includes("#")) {
        updatePreview(data.content);
      }
    }
  });

  // tool_call — агент збирається виконати tool
  es.addEventListener("tool_call", (e) => {
    const data = JSON.parse(e.data);
    appendToolCall(data.tool, data.args, data.node);
  });

  // tool_result — результат виконання tool
  es.addEventListener("tool_result", (e) => {
    const data = JSON.parse(e.data);
    appendToolResult(data.tool, data.result, data.node);
  });

  // hitl_interrupt — потрібне схвалення
  es.addEventListener("hitl_interrupt", (e) => {
    const data = JSON.parse(e.data);
    showHitlCard(data.filename, data.preview, data.content, data.content_length);
    state.reportContent = data.content;
    state.reportFilename = data.filename;
    updatePreview(data.content);
  });

  // hitl_resolved — HITL завершено
  es.addEventListener("hitl_resolved", (e) => {
    const data = JSON.parse(e.data);
    hideHitlCard();

    if (data.decision === "approve") {
      appendSystemMessage(`✓ Report approved — saving as "${data.filename}"`);
      showDownloadButton(data.filename);
    } else {
      appendSystemMessage("✗ Report rejected");
      previewContent.classList.add("rejected");
    }
  });

  // done — виконання завершено
  es.addEventListener("done", (e) => {
    es.close();
    state.es = null;
    setBusy(false);
    fetchSessions(); // оновлюємо history sidebar
  });

  // error від сервера (не мережева помилка)
  es.addEventListener("error_event", (e) => {
    const data = JSON.parse(e.data);
    appendSystemMessage(`⚠ Error: ${data.message}`, true);
  });

  // Мережева помилка EventSource (з'єднання упало)
  es.onerror = (err) => {
    console.error("SSE error:", err);
    es.close();
    state.es = null;
    setBusy(false);
    appendSystemMessage("Connection error. Please try again.", true);
  };
}


// ─── HITL ───────────────────────────────────────────────────
function showHitlCard(filename, preview, fullContent, size) {
  hitlFilename.textContent = filename;
  hitlSize.textContent = size.toLocaleString();
  hitlPreview.textContent = preview + (size > 1000 ? "\n\n... (truncated)" : "");
  hitlCard.style.display = "block";
  state.hitlPending = true;

  // Дізейблимо інпут поки є HITL
  queryInput.disabled = true;
  btnSend.disabled = true;
}

function hideHitlCard() {
  hitlCard.style.display = "none";
  state.hitlPending = false;
}

async function sendHitlDecision(decision) {
  if (!state.sessionId) return;

  btnApprove.disabled = true;
  btnReject.disabled = true;

  try {
    const endpoint = decision === "approve" ? "/approve" : "/reject";
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      appendSystemMessage(`HITL error: ${err.detail}`, true);
    }
  } catch (err) {
    appendSystemMessage(`Network error: ${err}`, true);
  } finally {
    btnApprove.disabled = false;
    btnReject.disabled = false;
  }
}


// ─── Markdown Preview ────────────────────────────────────────
function updatePreview(markdown) {
  if (!markdown) return;
  previewContent.classList.remove("rejected");
  // marked.parse() — Markdown → HTML
  previewContent.innerHTML = marked.parse(markdown);
}

function clearPreview() {
  previewContent.innerHTML = '<p class="placeholder">Звіт з\'явиться тут після завершення дослідження.</p>';
  previewContent.classList.remove("rejected");
  state.reportContent = "";
  state.reportFilename = null;
  btnDownload.style.display = "none";
}

function showDownloadButton(filename) {
  btnDownload.style.display = "inline-block";
  btnDownload.onclick = () => {
    // Завантажуємо через /reports/<filename>
    window.location.href = `/reports/${encodeURIComponent(filename)}`;
  };
}


// ─── Chat Rendering ──────────────────────────────────────────

function clearChat() {
  chatLog.innerHTML = "";
}

/**
 * Визначає label і CSS клас для вузла LangGraph.
 * Назви вузлів у LangGraph — довільні рядки (supervisor, agent, tools тощо).
 */
function nodeInfo(nodeName) {
  const n = (nodeName || "").toLowerCase();
  if (n.includes("planner"))    return { label: "Planner",    cls: "planner" };
  if (n.includes("research"))   return { label: "Researcher", cls: "researcher" };
  if (n.includes("critic"))     return { label: "Critic",     cls: "critic" };
  if (n.includes("supervisor")) return { label: "Supervisor", cls: "supervisor" };
  return { label: nodeName || "Agent", cls: "supervisor" };
}

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `
    <div class="msg-header">You</div>
    <div class="msg-body">${escapeHtml(text)}</div>
  `;
  chatLog.appendChild(div);
  scrollChatBottom();
}

function appendAgentMessage(node, content) {
  const { label, cls } = nodeInfo(node);
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  // Якщо контент виглядає як Markdown — рендеримо
  const rendered = content.includes("#") || content.includes("**")
    ? marked.parse(content)
    : `<p>${escapeHtml(content)}</p>`;
  div.innerHTML = `
    <div class="msg-header"><span class="spinner" style="display:none"></span>${label}</div>
    <div class="msg-body">${rendered}</div>
  `;
  chatLog.appendChild(div);
  scrollChatBottom();
}

function appendToolCall(toolName, args, node) {
  const { label } = nodeInfo(node);
  const argsStr = JSON.stringify(args, null, 2);
  const details = document.createElement("details");
  details.className = "tool-block";
  details.innerHTML = `
    <summary>${label} → ${escapeHtml(toolName)}()</summary>
    <pre>${escapeHtml(argsStr)}</pre>
  `;
  chatLog.appendChild(details);
  scrollChatBottom();
}

function appendToolResult(toolName, result, node) {
  // Tool results — компактний рядок, не розгорнутий блок
  const div = document.createElement("div");
  div.className = "tool-block";
  div.style.color = "var(--text-muted)";
  div.innerHTML = `↩ ${escapeHtml(toolName)}: ${escapeHtml(result)}`;
  chatLog.appendChild(div);
  scrollChatBottom();
}

function appendSystemMessage(text, isError = false) {
  const div = document.createElement("div");
  div.style.cssText = `
    padding: 6px 12px;
    font-size: 12px;
    color: ${isError ? "var(--reject)" : "var(--text-muted)"};
    font-style: italic;
  `;
  div.textContent = text;
  chatLog.appendChild(div);
  scrollChatBottom();
}

function scrollChatBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}


// ─── Busy state ──────────────────────────────────────────────
function setBusy(busy) {
  state.busy = busy;
  queryInput.disabled = busy || state.hitlPending;
  btnSend.disabled = busy;
  if (!busy && !state.hitlPending) {
    queryInput.disabled = false;
    queryInput.focus();
  }
}


// ─── New Chat ────────────────────────────────────────────────
function onNewChat() {
  if (state.es) {
    state.es.close();
    state.es = null;
  }
  state.sessionId = null;
  state.busy = false;
  state.hitlPending = false;
  hideHitlCard();
  clearChat();
  clearPreview();
  setBusy(false);
  chatLog.innerHTML = `
    <div class="welcome-msg">
      <p>Введи запит нижче щоб почати дослідження.</p>
      <p class="hint">Приклад: <em>What is RAG and how does it work?</em></p>
    </div>
  `;
}


// ─── History Sidebar ─────────────────────────────────────────
async function fetchSessions() {
  try {
    const resp = await fetch("/sessions?limit=20");
    if (!resp.ok) return;
    const sessions = await resp.json();

    sessionList.innerHTML = "";

    if (!sessions.length) {
      sessionList.innerHTML = '<li class="session-item placeholder">No history yet</li>';
      return;
    }

    for (const s of sessions) {
      const li = document.createElement("li");
      li.className = "session-item";
      if (s.session_id === state.sessionId) li.classList.add("active");

      const timeStr = s.created_at
        ? new Date(s.created_at).toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })
        : "";

      li.innerHTML = `
        <div>${escapeHtml(s.query.substring(0, 40))}${s.query.length > 40 ? "..." : ""}</div>
        <div class="session-time">${timeStr}${s.report_path ? " ✓" : ""}</div>
      `;

      li.addEventListener("click", () => {
        // При кліку на сесію — показуємо query (повне відновлення поза скопом hw13)
        appendSystemMessage(`Session: ${s.query}`, false);
      });

      sessionList.appendChild(li);
    }
  } catch (err) {
    console.warn("Failed to fetch sessions:", err);
  }
}


// ─── Utils ───────────────────────────────────────────────────
function escapeHtml(str) {
  if (typeof str !== "string") str = String(str ?? "");
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
