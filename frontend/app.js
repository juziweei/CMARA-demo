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
    text: "Day 0 baseline climate preferences are seeded. Starting the family-trip dialogue.",
  },
  {
    type: "turn",
    text: "This weekend our family is going to the coast. Please navigate to the East Pier parking lot first.",
  },
  {
    type: "turn",
    text: "My daughter just fell asleep in the back seat, so do not play music for now.",
  },
  {
    type: "turn",
    text: "When the family goes out together, I usually prefer the car cabin to stay quiet.",
  },
  {
    type: "system",
    text: "Running offline summarization to write family-trip preferences back into the preference table.",
    action: "summarize",
  },
  {
    type: "turn",
    text: "We are taking a family trip to the coast this weekend, and it feels hot.",
  },
  {
    type: "clarification",
    text: "I feel much better today, basically recovered.",
  },
  {
    type: "turn",
    text: "Next week the family is going on another outing. I have recovered from the cold, but it still feels a bit hot.",
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
  els.pendingState.textContent = state.pendingId ? "Waiting for clarification" : "None";
  els.composerMode.textContent = state.pendingId
    ? "Sending to /clarification"
    : "Sending to /turn";
  els.chatHint.textContent = state.pendingId
    ? "The next user message will answer the clarification question"
    : "Send a user turn or run the full demo";
  if (state.pendingId) {
    els.pendingCard.classList.remove("is-hidden");
    els.pendingCard.textContent = `pending_id: ${state.pendingId}\nquestion: ${pending.question}\noriginal_context: ${pending.original_context}`;
  } else {
    els.pendingCard.classList.add("is-hidden");
    els.pendingCard.textContent = "";
  }
}

function renderPreferences(preferences) {
  els.preferenceCount.textContent = `${preferences.length} item${preferences.length === 1 ? "" : "s"}`;
  els.preferencesList.innerHTML = "";
  els.preferencesEmpty.classList.toggle("is-hidden", preferences.length > 0);

  for (const item of preferences) {
    const fragment = els.preferenceTemplate.content.cloneNode(true);
    fragment.querySelector(".preference-name").textContent = item.preference;
    fragment.querySelector(".preference-status").textContent = item.status;
    fragment.querySelector(".preference-value").textContent = `value: ${item.value}`;
    fragment.querySelector(".preference-condition").textContent = `condition: ${formatCondition(item.condition)}`;
    fragment.querySelector(".preference-meta").textContent = `source: ${item.source}  ·  time: ${item.timestamp}`;
    fragment.querySelector(".preference-evidence").textContent = item.evidence || "No evidence";
    els.preferencesList.appendChild(fragment);
  }
}

function formatCondition(condition) {
  if (!condition) return "-";
  if (condition.type === "default") return "default, no special condition";
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
  const context = trace?.parsed_context || trace?.context || "None";
  const mode = detectConversationMode(result, trace);

  els.currentStatus.textContent = status;
  els.toolName.textContent = toolName;
  els.retrievalCount.textContent = String(retrievalHits.length);
  els.learnedState.textContent = learned ? `${learned.preference} -> ${learned.value}` : "None";
  els.expiredCount.textContent = String(expired.length);
  els.unknownDimensions.textContent = unknownDimensions.length
    ? unknownDimensions.join(" / ")
    : "None";
  els.conversationMode.textContent = mode;
  els.resultBanner.textContent = result?.assistant_text || "Waiting for the backend result for the current turn.";
  els.contextJson.textContent = pretty(context);
  els.candidatesJson.textContent = pretty(candidates.length ? candidates : "None");
  els.retrievedJson.textContent = pretty(retrievedPrefs.length ? retrievedPrefs : "None");
  els.toolResult.textContent = pretty(result?.tool_result || "None");
  els.decisionJson.textContent = pretty(result?.decision || "None");
  els.traceJson.textContent = pretty(trace || "None");

  if (status === "needs_user_input") {
    setDecisionBadge("pending", "Needs Clarification");
  } else if (status === "acted") {
    setDecisionBadge("online", "Acted");
  } else if (status === "replied") {
    setDecisionBadge("neutral", "Replied");
  } else {
    setDecisionBadge("neutral", "Waiting");
  }
}

function detectConversationMode(result, trace) {
  if (!result) return "Free Input";
  if (result.status === "needs_user_input") return "Clarification Mode";
  if (result.decision?.tool_name === "general_chat") return "General Chat";
  if (trace?.parsed_context?.is_clarification) return "Clarification Answer";
  return "Task Execution";
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
    setConnectionBadge("online", "Online");
    addMessage("system", `Health check succeeded: session_id=${payload.session_id}`, "health");
    return payload;
  } catch (error) {
    setConnectionBadge("offline", "Offline");
    addMessage("system", `Health check failed: ${error.message}`, "health");
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

  addMessage("assistant", payload.assistant_text || "(no response)", payload.status);
  setPending(payload.pending);
  updateSummary(payload);
  await refreshPreferences();
  return payload;
}

async function doSummarize() {
  const payload = await apiPost("/summarize", { session_id: "default" });
  addMessage("system", `Offline summarization completed. Added ${payload.count} preference${payload.count === 1 ? "" : "s"}.`, "summarize");
  await refreshPreferences();
  return payload;
}

async function doReset() {
  const payload = await apiPost("/reset", { session_id: "default" });
  state.pendingId = null;
  state.pendingQuestion = "";
  clearChat();
  addMessage("system", "Demo state has been reset.", "reset");
  setPending(null);
  updateSummary(null);
  await refreshPreferences();
  return payload;
}

async function seedFamilyTripDemo() {
  const payload = await apiPost("/demo/family_trip", { session_id: "default" });
  addMessage("system", `Seeded the family-trip demo with ${payload.count} initial preference${payload.count === 1 ? "" : "s"}.`, "seed");
  await refreshPreferences();
  return payload;
}

async function runScenario() {
  clearChat();
  setPending(null);
  updateSummary(null);
  await seedFamilyTripDemo();
  addMessage("system", "Starting the full demo: family-trip long-term memory loop.", "scenario");
  for (const step of scenarioSteps) {
    if (step.type === "system") {
      addMessage("system", step.text, "scenario");
      if (step.action === "summarize") {
        await doSummarize();
      }
    } else if (step.type === "clarification") {
      if (!state.pendingId) {
        addMessage("system", "There is no pending clarification. Skipping the clarification step.", "scenario");
        continue;
      }
      await submitTurn(step.text);
    } else {
      await submitTurn(step.text);
    }
  }
  addMessage("system", "Full demo completed. The system is now in the learned-and-reuse stage.", "scenario");
}

function withBusy(button, fn) {
  return async (...args) => {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Working...";
    try {
      await fn(...args);
    } catch (error) {
      addMessage("system", `Operation failed: ${error.message}`, "error");
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
    els.traceToggleBtn.textContent = state.traceCollapsed ? "Expand Trace" : "Collapse Trace";
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
      addMessage("system", `Send failed: ${error.message}`, "error");
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
  addMessage("system", "Page is ready. Check the API connection before starting the demo.", "init");
  try {
    await checkHealth();
    await refreshPreferences();
  } catch (error) {
    updateSummary(null);
  }
}

bootstrap();
