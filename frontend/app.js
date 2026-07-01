const state = {
  apiBase: "http://127.0.0.1:8010",
  pendingId: null,
  pendingQuestion: "",
  traceCollapsed: false,
};

const els = {
  apiBase: document.getElementById("api-base"),
  connectionBadge: document.getElementById("connection-badge"),
  currentStatus: document.getElementById("current-status"),
  pendingState: document.getElementById("pending-state"),
  preferenceCount: document.getElementById("preference-count"),
  preferencesEmpty: document.getElementById("preferences-empty"),
  preferencesList: document.getElementById("preferences-list"),
  decisionBadge: document.getElementById("decision-badge"),
  toolName: document.getElementById("tool-name"),
  retrievalCount: document.getElementById("retrieval-count"),
  learnedState: document.getElementById("learned-state"),
  expiredCount: document.getElementById("expired-count"),
  resultBanner: document.getElementById("result-banner"),
  unknownDimensions: document.getElementById("unknown-dimensions"),
  conversationMode: document.getElementById("conversation-mode"),
  chatLog: document.getElementById("chat-log"),
  chatHint: document.getElementById("chat-hint"),
  composer: document.getElementById("composer"),
  composerMode: document.getElementById("composer-mode"),
  userInput: document.getElementById("user-input"),
  pendingCard: document.getElementById("pending-card"),
  contextJson: document.getElementById("context-json"),
  candidatesJson: document.getElementById("candidates-json"),
  retrievedJson: document.getElementById("retrieved-json"),
  toolResult: document.getElementById("tool-result"),
  decisionJson: document.getElementById("decision-json"),
  traceJson: document.getElementById("trace-json"),
  tracePanel: document.getElementById("trace-panel"),
  messageTemplate: document.getElementById("message-template"),
  preferenceTemplate: document.getElementById("preference-template"),
  checkHealthBtn: document.getElementById("check-health-btn"),
  refreshBtn: document.getElementById("refresh-btn"),
  scenarioBtn: document.getElementById("scenario-btn"),
  summarizeBtn: document.getElementById("summarize-btn"),
  resetBtn: document.getElementById("reset-btn"),
  traceToggleBtn: document.getElementById("trace-toggle-btn"),
};

const scenarioSteps = [
  {
    type: "system",
    text: "Day 0 已播种基础空调偏好，开始送入家庭出游对话。",
  },
  {
    type: "turn",
    text: "这周末一家人去海边，先导航到东堤停车场吧。",
  },
  {
    type: "turn",
    text: "姐姐刚在后排睡着了，先别放音乐。",
  },
  {
    type: "turn",
    text: "一家人出去玩的时候，我一般不想车里太吵。",
  },
  {
    type: "system",
    text: "执行离线总结，尝试把家庭出游偏好写回偏好表。",
    action: "summarize",
  },
  {
    type: "turn",
    text: "周末一家人要去海边了，好热啊。",
  },
  {
    type: "clarification",
    text: "好多了，今天基本恢复了。",
  },
  {
    type: "turn",
    text: "下周一家人又要去郊游了，感冒恢复了，还是有点热。",
  },
];

function normalizeBaseUrl(value) {
  return (value || "").trim().replace(/\/+$/, "");
}

function setApiBase() {
  state.apiBase = normalizeBaseUrl(els.apiBase.value) || "http://127.0.0.1:8010";
  els.apiBase.value = state.apiBase;
}

function setConnectionBadge(kind, text) {
  els.connectionBadge.className = `badge ${kind}`;
  els.connectionBadge.textContent = text;
}

function setDecisionBadge(kind, text) {
  els.decisionBadge.className = `badge ${kind}`;
  els.decisionBadge.textContent = text;
}

function addMessage(role, text, tag = "") {
  const fragment = els.messageTemplate.content.cloneNode(true);
  const root = fragment.querySelector(".message");
  root.classList.add(role);
  fragment.querySelector(".message-role").textContent = role;
  fragment.querySelector(".message-body").textContent = text;
  fragment.querySelector(".message-tag").textContent = tag;
  els.chatLog.appendChild(fragment);
  els.chatLog.scrollTop = els.chatLog.scrollHeight;
}

function clearChat() {
  els.chatLog.innerHTML = "";
}

function setPending(pending) {
  state.pendingId = pending?.pending_id || null;
  state.pendingQuestion = pending?.question || "";
  els.pendingState.textContent = state.pendingId ? "等待澄清" : "无";
  els.composerMode.textContent = state.pendingId
    ? "当前发送到 /clarification"
    : "当前发送到 /turn";
  els.chatHint.textContent = state.pendingId
    ? "下一条输入会作为澄清回答提交"
    : "发送用户输入或运行快速演示";
  if (state.pendingId) {
    els.pendingCard.classList.remove("is-hidden");
    els.pendingCard.textContent = `pending_id: ${state.pendingId}\nquestion: ${pending.question}\noriginal_context: ${pending.original_context}`;
  } else {
    els.pendingCard.classList.add("is-hidden");
    els.pendingCard.textContent = "";
  }
}

function renderPreferences(preferences) {
  els.preferenceCount.textContent = `${preferences.length} 条`;
  els.preferencesList.innerHTML = "";
  els.preferencesEmpty.classList.toggle("is-hidden", preferences.length > 0);

  for (const item of preferences) {
    const fragment = els.preferenceTemplate.content.cloneNode(true);
    fragment.querySelector(".preference-name").textContent = item.preference;
    fragment.querySelector(".preference-status").textContent = item.status;
    fragment.querySelector(".preference-value").textContent = `value: ${item.value}`;
    fragment.querySelector(".preference-condition").textContent = `condition: ${formatCondition(item.condition)}`;
    fragment.querySelector(".preference-meta").textContent = `source: ${item.source}  ·  time: ${item.timestamp}`;
    fragment.querySelector(".preference-evidence").textContent = item.evidence || "无 evidence";
    els.preferencesList.appendChild(fragment);
  }
}

function formatCondition(condition) {
  if (!condition) return "-";
  if (condition.type === "default") return "默认（无特殊条件）";
  const operator = condition.operator ? ` ${condition.operator} ` : " ";
  const target = condition.target !== undefined ? condition.target : "";
  const unit = condition.unit ? ` ${condition.unit}` : "";
  return `${condition.type}${operator}${target}${unit}`.trim();
}

function updateSummary(result) {
  const status = result?.status || "idle";
  const toolName = result?.decision?.tool_name || "-";
  const retrievalHits = result?.retrieval_hits || [];
  const learned = result?.learned_preference;
  const expired = result?.expired_preferences || [];
  const trace = result?.decision_trace || {};
  const unknownDimensions = trace?.unknown_dimensions || [];
  const candidates = trace?.policy_candidates || [];
  const retrievedPrefs = result?.retrieved_preferences || trace?.retrieved_preferences || [];
  const context = trace?.parsed_context || trace?.context || "暂无";
  const mode = detectConversationMode(result, trace);

  els.currentStatus.textContent = status;
  els.toolName.textContent = toolName;
  els.retrievalCount.textContent = String(retrievalHits.length);
  els.learnedState.textContent = learned ? `${learned.preference} -> ${learned.value}` : "无";
  els.expiredCount.textContent = String(expired.length);
  els.unknownDimensions.textContent = unknownDimensions.length
    ? unknownDimensions.join(" / ")
    : "无";
  els.conversationMode.textContent = mode;
  els.resultBanner.textContent = result?.assistant_text || "等待后端返回当前回合结果。";
  els.contextJson.textContent = pretty(context);
  els.candidatesJson.textContent = pretty(candidates.length ? candidates : "暂无");
  els.retrievedJson.textContent = pretty(retrievedPrefs.length ? retrievedPrefs : "暂无");
  els.toolResult.textContent = pretty(result?.tool_result || "暂无");
  els.decisionJson.textContent = pretty(result?.decision || "暂无");
  els.traceJson.textContent = pretty(trace || "暂无");

  if (status === "needs_user_input") {
    setDecisionBadge("pending", "等待澄清");
  } else if (status === "acted") {
    setDecisionBadge("online", "已执行");
  } else if (status === "replied") {
    setDecisionBadge("neutral", "普通回复");
  } else {
    setDecisionBadge("neutral", "等待输入");
  }
}

function detectConversationMode(result, trace) {
  if (!result) return "自由输入";
  if (result.status === "needs_user_input") return "追问模式";
  if (result.decision?.tool_name === "general_chat") return "普通对话";
  if (trace?.parsed_context?.is_clarification) return "澄清回答";
  return "任务执行";
}

function pretty(value) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

async function apiGet(path) {
  setApiBase();
  const response = await fetch(`${state.apiBase}${path}`);
  return parseJsonResponse(response);
}

async function apiPost(path, payload) {
  setApiBase();
  const response = await fetch(`${state.apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response);
}

async function parseJsonResponse(response) {
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }
  if (!response.ok) {
    const message = payload?.error || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

async function refreshPreferences() {
  const payload = await apiGet("/preferences");
  renderPreferences(payload.preferences || []);
  return payload;
}

async function checkHealth() {
  try {
    const payload = await apiGet("/health");
    setConnectionBadge("online", "在线");
    addMessage("system", `健康检查成功：session_id=${payload.session_id}`, "health");
    return payload;
  } catch (error) {
    setConnectionBadge("offline", "离线");
    addMessage("system", `健康检查失败：${error.message}`, "health");
    throw error;
  }
}

async function submitTurn(text) {
  const trimmed = text.trim();
  if (!trimmed) return;

  addMessage("user", trimmed, state.pendingId ? "clarification" : "turn");
  const payload = state.pendingId
    ? await apiPost("/clarification", {
        session_id: "default",
        pending_id: state.pendingId,
        answer: trimmed,
      })
    : await apiPost("/turn", {
        session_id: "default",
        text: trimmed,
      });

  addMessage("assistant", payload.assistant_text || "(无回复)", payload.status);
  setPending(payload.pending);
  updateSummary(payload);
  await refreshPreferences();
  return payload;
}

async function doSummarize() {
  const payload = await apiPost("/summarize", { session_id: "default" });
  addMessage("system", `离线总结完成，新增 ${payload.count} 条偏好。`, "summarize");
  await refreshPreferences();
  return payload;
}

async function doReset() {
  const payload = await apiPost("/reset", { session_id: "default" });
  state.pendingId = null;
  state.pendingQuestion = "";
  clearChat();
  addMessage("system", "已重置 demo 状态。", "reset");
  setPending(null);
  updateSummary(null);
  await refreshPreferences();
  return payload;
}

async function seedFamilyTripDemo() {
  const payload = await apiPost("/demo/family_trip", { session_id: "default" });
  addMessage("system", `已播种家庭出游演示初始偏好，共 ${payload.count} 条。`, "seed");
  await refreshPreferences();
  return payload;
}

async function runScenario() {
  clearChat();
  setPending(null);
  updateSummary(null);
  await seedFamilyTripDemo();
  addMessage("system", "开始一键全流程：家庭出游长期记忆闭环。", "scenario");
  for (const step of scenarioSteps) {
    if (step.type === "system") {
      addMessage("system", step.text, "scenario");
      if (step.action === "summarize") {
        await doSummarize();
      }
    } else if (step.type === "clarification") {
      if (!state.pendingId) {
        addMessage("system", "当前没有待回答追问，跳过澄清步骤。", "scenario");
        continue;
      }
      await submitTurn(step.text);
    } else {
      await submitTurn(step.text);
    }
  }
  addMessage("system", "一键全流程结束。当前状态已经进入“学到后直接执行”的复现阶段。", "scenario");
}

function withBusy(button, fn) {
  return async (...args) => {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "处理中...";
    try {
      await fn(...args);
    } catch (error) {
      addMessage("system", `操作失败：${error.message}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  };
}

function initTraceToggle() {
  els.traceToggleBtn.addEventListener("click", () => {
    state.traceCollapsed = !state.traceCollapsed;
    els.tracePanel.classList.toggle("trace-collapsed", state.traceCollapsed);
    els.traceToggleBtn.textContent = state.traceCollapsed ? "展开 Trace" : "折叠 Trace";
  });
}

function bindEvents() {
  els.apiBase.addEventListener("change", setApiBase);
  els.composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = els.userInput.value;
    if (!value.trim()) return;
    els.userInput.value = "";
    try {
      await submitTurn(value);
    } catch (error) {
      addMessage("system", `发送失败：${error.message}`, "error");
    }
  });

  els.checkHealthBtn.addEventListener("click", withBusy(els.checkHealthBtn, checkHealth));
  els.refreshBtn.addEventListener("click", withBusy(els.refreshBtn, refreshPreferences));
  els.scenarioBtn.addEventListener("click", withBusy(els.scenarioBtn, runScenario));
  els.summarizeBtn.addEventListener("click", withBusy(els.summarizeBtn, doSummarize));
  els.resetBtn.addEventListener("click", withBusy(els.resetBtn, doReset));
}

async function bootstrap() {
  setApiBase();
  bindEvents();
  initTraceToggle();
  addMessage("system", "页面已就绪。先做健康检查，再开始演示。", "init");
  try {
    await checkHealth();
    await refreshPreferences();
  } catch (error) {
    updateSummary(null);
  }
}

bootstrap();
