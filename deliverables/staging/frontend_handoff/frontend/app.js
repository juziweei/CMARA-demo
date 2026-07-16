function resolveDefaultApiBase() {
  const hostname = window.location.hostname;
  const protocol = window.location.protocol || "http:";
  if (!hostname || hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]") {
    return "http://127.0.0.1:8010";
  }
  return `${protocol}//${hostname}:8010`;
}

const DEFAULT_API_BASE = resolveDefaultApiBase();
const AUTO_STEP_DELAY_MS = 900;
const STORAGE_KEYS = {
  apiBase: "vehicle-memory-demo-api-base",
  scenarioId: "vehicle-memory-demo-scenario-id",
};

const state = {
  apiBase: DEFAULT_API_BASE,
  apiReachable: null,
  memoryMode: "unknown",
  scenarios: [],
  selectedScenarioId: null,
  activeScenarioId: null,
  activeStep: 0,
  pendingId: null,
  pendingQuestion: "",
  currentResult: null,
  currentStep: null,
  autoRunning: false,
  busy: false,
  local: {
    activeScenarioId: null,
    activeStep: 0,
    pendingId: null,
    pendingQuestion: "",
    preferences: [],
    preferenceSeq: 0,
  },
};

const LOCAL_SCENARIO_CATALOG = "./scenarios.json";
const LOCAL_SCENARIO_RULES = {
  family_coastal_trip: {
    toolName: "set_ac_temperature",
    actionLabel: "cabin temperature",
    askQuestion:
      "Is he still recovering today, or should I keep the cooler family-trip setting from the earlier drive?",
    turnReply:
      "I found the family-trip context and I can keep the cabin calm while the child sleeps.",
    reuseReply:
      "I can reuse the recovered-state temperature rule and keep the family cabin calm.",
    summaryPreference: {
      preference: "cabin_quiet_mode",
      value: "quiet",
      condition: { type: "family_trip", operator: "==", target: "coastal" },
      source: "offline_summary",
      evidence:
        "The family trip wants a quiet cabin, low music, and no unnecessary voice prompts.",
    },
    learnedPreference: {
      preference: "ac_temperature",
      value: 25.5,
      condition: {
        type: "health_state",
        operator: "==",
        target: "recovering",
      },
      source: "learned_from_clarification",
      evidence:
        "The recovery state changed, so the cabin can return to the recovered setting.",
      expire: {
        preference: "ac_temperature",
        condition: { type: "health_state", target: "sick" },
      },
    },
    missingDimension: "health_state",
  },
  morning_commute_time_pressure: {
    toolName: "set_seat_heating",
    actionLabel: "seat heating",
    askQuestion:
      "Is your father still recovering, or should I keep the lighter weekday commute setting?",
    turnReply:
      "I can keep the commute focused and use the lighter seat-heating preference.",
    reuseReply:
      "I can reuse the recovery-aware commute setting and keep seat heating measured.",
    summaryPreference: {
      preference: "commute_focus_mode",
      value: "light",
      condition: { type: "time_pressure", operator: "==", target: "high" },
      source: "offline_summary",
      evidence:
        "The weekday commute stays calm, low-distraction, and focused on getting to work on time.",
    },
    learnedPreference: {
      preference: "seat_heating",
      value: 2,
      condition: {
        type: "passenger_health_state",
        operator: "==",
        target: "recovering",
      },
      source: "learned_from_clarification",
      evidence:
        "The passenger is still recovering, so a slightly warmer seat is better.",
      expire: {
        preference: "seat_heating",
        condition: { type: "default" },
      },
    },
    missingDimension: "passenger_health_state",
  },
  elderly_passenger_comfort: {
    toolName: "set_ac_temperature",
    actionLabel: "cabin temperature",
    askQuestion:
      "Is your mother still sensitive today, or should I keep the gentler clinic setting?",
    turnReply:
      "I can keep the ride smooth and use the gentler clinic-drive preference.",
    reuseReply:
      "I can reuse the gentle comfort rule and keep the cabin soft for the return drive.",
    summaryPreference: {
      preference: "gentle_drive_mode",
      value: "on",
      condition: { type: "clinic_run", operator: "==", target: "active" },
      source: "offline_summary",
      evidence:
        "The clinic run favors a gentle cabin and a conservative ride.",
    },
    learnedPreference: {
      preference: "ac_temperature",
      value: 23.5,
      condition: {
        type: "passenger_health_state",
        operator: "==",
        target: "sensitive",
      },
      source: "learned_from_clarification",
      evidence:
        "The passenger is still sensitive after the rough night.",
      expire: {
        preference: "ac_temperature",
        condition: { type: "passenger_health_state", target: "sick" },
      },
    },
    missingDimension: "passenger_health_state",
  },
  quiet_work_call_mode: {
    toolName: "set_music_mode",
    actionLabel: "audio mode",
    askQuestion:
      "Should I keep the cabin silent until the client call is over, or switch back to the usual light music afterward?",
    turnReply:
      "I can keep the client-call setup quiet and protect voice clarity during the call.",
    reuseReply:
      "I can reuse the silent call mode and keep the cabin quiet until the meeting ends.",
    summaryPreference: {
      preference: "call_privacy_mode",
      value: "quiet",
      condition: { type: "work_call", operator: "==", target: "active" },
      source: "offline_summary",
      evidence:
        "The call scenario needs a quiet cabin and stable voice clarity.",
    },
    learnedPreference: {
      preference: "music_mode",
      value: "silent",
      condition: {
        type: "work_call",
        operator: "==",
        target: "active",
      },
      source: "learned_from_clarification",
      evidence:
        "The client call should stay silent until it ends.",
      expire: {
        preference: "music_mode",
        condition: { type: "default" },
      },
    },
    missingDimension: "work_call",
  },
  rainy_evening_return: {
    toolName: "set_ac_temperature",
    actionLabel: "cabin temperature",
    askQuestion:
      "Should I keep the cabin a little warmer because of the rain, or leave it at the normal evening setting?",
    turnReply:
      "I can keep the rainy return steady and avoid swinging the cabin temperature too far.",
    reuseReply:
      "I can reuse the rainy-evening setting and keep the return drive stable.",
    summaryPreference: {
      preference: "rainy_drive_mode",
      value: "stable",
      condition: { type: "weather_state", operator: "==", target: "rainy" },
      source: "offline_summary",
      evidence:
        "The rainy return wants a steady cabin and less temperature swing.",
    },
    learnedPreference: {
      preference: "ac_temperature",
      value: 23.5,
      condition: {
        type: "weather_state",
        operator: "==",
        target: "rainy",
      },
      source: "learned_from_clarification",
      evidence:
        "Rainy evening drives feel better with a slightly warmer cabin.",
      expire: {
        preference: "ac_temperature",
        condition: { type: "default" },
      },
    },
    missingDimension: "weather_state",
  },
  default: {
    toolName: "general_chat",
    actionLabel: "assistant reply",
    askQuestion: "Could you share the key condition I should use here?",
    turnReply: "I can work with the current context and keep the response concise.",
    reuseReply:
      "I can reuse the latest preference and keep the response aligned with it.",
    summaryPreference: {
      preference: "general_demo_note",
      value: "active",
      condition: { type: "default" },
      source: "offline_summary",
      evidence:
        "The demo conversation produced a reusable note for the current scenario.",
    },
    learnedPreference: {
      preference: "general_demo_rule",
      value: "active",
      condition: { type: "default" },
      source: "learned_from_clarification",
      evidence:
        "The demo conversation produced a reusable clarification result.",
      expire: null,
    },
    missingDimension: "context",
  },
};

const els = {
  apiBase: document.getElementById("api-base"),
  apiChip: document.getElementById("api-chip"),
  memoryChip: document.getElementById("memory-chip"),
  scenarioChip: document.getElementById("scenario-chip"),
  stepChip: document.getElementById("step-chip"),
  pendingChip: document.getElementById("pending-chip"),
  checkHealthBtn: document.getElementById("check-health-btn"),
  reloadBtn: document.getElementById("reload-btn"),
  runBtn: document.getElementById("run-btn"),
  stepBtn: document.getElementById("step-btn"),
  autoBtn: document.getElementById("auto-btn"),
  summarizeBtn: document.getElementById("summarize-btn"),
  resetBtn: document.getElementById("reset-btn"),
  scenarioCount: document.getElementById("scenario-count"),
  scenarioList: document.getElementById("scenario-list"),
  preferenceCount: document.getElementById("preference-count"),
  preferencesEmpty: document.getElementById("preferences-empty"),
  preferencesList: document.getElementById("preferences-list"),
  selectedScenarioTitle: document.getElementById("selected-scenario-title"),
  selectedScenarioSubtitle: document.getElementById("selected-scenario-subtitle"),
  playbackStatus: document.getElementById("playback-status"),
  selectedScenarioGoal: document.getElementById("selected-scenario-goal"),
  scenarioFocus: document.getElementById("scenario-focus"),
  scenarioDimensions: document.getElementById("scenario-dimensions"),
  scenarioStepCount: document.getElementById("scenario-step-count"),
  scenarioSeedCount: document.getElementById("scenario-seed-count"),
  activeStepCount: document.getElementById("active-step-count"),
  scenarioOutlineMeta: document.getElementById("scenario-outline-meta"),
  scenarioOutline: document.getElementById("scenario-outline"),
  conversationMode: document.getElementById("conversation-mode"),
  pendingBanner: document.getElementById("pending-banner"),
  pendingQuestion: document.getElementById("pending-question"),
  conversationLog: document.getElementById("conversation-log"),
  composer: document.getElementById("composer"),
  userInput: document.getElementById("user-input"),
  composerMode: document.getElementById("composer-mode"),
  decisionStatus: document.getElementById("decision-status"),
  flowContextTitle: document.getElementById("flow-context-title"),
  flowContextBody: document.getElementById("flow-context-body"),
  flowRetrievalTitle: document.getElementById("flow-retrieval-title"),
  flowRetrievalList: document.getElementById("flow-retrieval-list"),
  flowPolicyTitle: document.getElementById("flow-policy-title"),
  flowPolicyBody: document.getElementById("flow-policy-body"),
  flowUpdateTitle: document.getElementById("flow-update-title"),
  flowUpdateBody: document.getElementById("flow-update-body"),
  rawTrace: document.getElementById("raw-trace"),
  timelineCount: document.getElementById("timeline-count"),
  timelineList: document.getElementById("timeline-list"),
  scenarioTemplate: document.getElementById("scenario-template"),
  messageTemplate: document.getElementById("message-template"),
  preferenceTemplate: document.getElementById("preference-template"),
  timelineTemplate: document.getElementById("timeline-template"),
};

function readStoredValue(key, fallback = "") {
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch (error) {
    return fallback;
  }
}

function writeStoredValue(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (error) {
    return;
  }
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function setApiBase(value) {
  state.apiBase = normalizeBaseUrl(value) || DEFAULT_API_BASE;
  els.apiBase.value = state.apiBase;
  writeStoredValue(STORAGE_KEYS.apiBase, state.apiBase);
  setChip(els.apiChip, "API: configured", "neutral");
}

function setChip(element, text, tone = "neutral") {
  element.className = `chip chip-${tone}`;
  element.textContent = text;
}

function setBadge(element, text, tone = "neutral") {
  element.className = `badge badge-${tone}`;
  element.textContent = text;
}

function setBusy(busy) {
  state.busy = busy;
  for (const button of [
    els.checkHealthBtn,
    els.reloadBtn,
    els.runBtn,
    els.stepBtn,
    els.summarizeBtn,
    els.resetBtn,
    els.composer.querySelector('button[type="submit"]'),
  ]) {
    button.disabled = busy;
  }
  els.autoBtn.disabled = busy && !state.autoRunning;
}

function toggleAutoLabel() {
  els.autoBtn.textContent = state.autoRunning ? "Stop Auto" : "Auto Play";
}

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function truncate(text, maxLength = 140) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function stringifyValue(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function pretty(value) {
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function cloneData(value) {
  if (value === undefined) {
    return undefined;
  }
  return JSON.parse(JSON.stringify(value));
}

function capitalize(text) {
  const value = String(text || "").trim();
  if (!value) {
    return "";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatCondition(condition) {
  if (!condition) {
    return "Condition: -";
  }
  if (condition.type === "default") {
    return "Condition: default";
  }
  const operator = condition.operator ? ` ${condition.operator} ` : " ";
  const target = condition.target !== undefined ? condition.target : "";
  const unit = condition.unit ? ` ${condition.unit}` : "";
  return `Condition: ${condition.type}${operator}${target}${unit}`.trim();
}

function formatPreferenceSource(source) {
  switch (source) {
    case "user_stated":
      return "User stated";
    case "offline_summary":
      return "Offline summary";
    case "learned_from_clarification":
      return "Clarification learning";
    default:
      return capitalize(source);
  }
}

function formatPreferenceStatus(status) {
  return capitalize(status);
}

function formatScenarioState(scenario) {
  if (scenario.id === state.activeScenarioId) {
    if (scenario.script.length > 0 && state.activeStep >= scenario.script.length) {
      return "Completed";
    }
    if (state.activeStep > 0) {
      return `Active ${state.activeStep}/${scenario.script.length}`;
    }
    return "Active";
  }
  if (scenario.id === state.selectedScenarioId) {
    return "Selected";
  }
  return "Ready";
}

function formatPlaybackState(scenario) {
  if (state.autoRunning) {
    return "Auto playing";
  }
  if (!scenario) {
    return "Idle";
  }
  if (scenario.id === state.activeScenarioId && scenario.script.length > 0) {
    if (state.activeStep >= scenario.script.length) {
      return "Completed";
    }
    if (state.activeStep > 0) {
      return `Running ${state.activeStep}/${scenario.script.length}`;
    }
    return "Running";
  }
  return "Idle";
}

function formatDecisionBadge(result) {
  if (!result) {
    return { text: "No turn yet", tone: "neutral" };
  }
  if (result.status === "needs_user_input") {
    return { text: "Needs input", tone: "warn" };
  }
  if (result.status === "acted") {
    return { text: "Acted", tone: "good" };
  }
  if (result.status === "replied") {
    return { text: "Replied", tone: "brand" };
  }
  if (result.status === "skipped") {
    return { text: "Skipped", tone: "neutral" };
  }
  return { text: capitalize(result.status), tone: "neutral" };
}

function formatConversationMode(step, result) {
  if (!step) {
    return "Idle";
  }
  if (step.kind === "summary") {
    return "Offline summary";
  }
  if (result?.status === "needs_user_input") {
    return "Clarification requested";
  }
  if (result?.status === "acted") {
    return "Action executed";
  }
  if (result?.status === "replied") {
    return "Assistant reply";
  }
  if (result?.status === "skipped") {
    return "Skipped";
  }
  return capitalize(step.kind);
}

function makeChip(text, tone = "neutral") {
  const chip = document.createElement("span");
  chip.className = `chip chip-${tone}`;
  chip.textContent = text;
  return chip;
}

function makeTag(text, tone = "source") {
  const tag = document.createElement("span");
  tag.className = `tag tag-${tone}`;
  tag.textContent = text;
  return tag;
}

function resetPlaybackViews() {
  clearNode(els.conversationLog);
  clearNode(els.timelineList);
  clearNode(els.flowRetrievalList);
  els.rawTrace.textContent = "No turn yet.";
  els.flowContextTitle.textContent = "Awaiting input";
  els.flowContextBody.textContent = "The latest request will appear here.";
  els.flowRetrievalTitle.textContent = "0 matches";
  els.flowPolicyTitle.textContent = "Idle";
  els.flowPolicyBody.textContent = "The policy decision will explain why the assistant asked or acted.";
  els.flowUpdateTitle.textContent = "No update yet";
  els.flowUpdateBody.textContent = "Learned preferences, expired rules, and summary writes appear here.";
  state.pendingId = null;
  state.pendingQuestion = "";
  state.currentResult = null;
  state.currentStep = null;
  setPendingBanner(null);
  setBadge(els.decisionStatus, "No turn yet", "neutral");
  setBadge(els.playbackStatus, "Idle", "neutral");
  setBadge(els.conversationMode, "Waiting", "neutral");
}

function setPendingBanner(pending) {
  state.pendingId = pending?.pending_id || null;
  state.pendingQuestion = pending?.question || "";
  if (state.pendingId) {
    els.pendingBanner.classList.remove("is-hidden");
    els.pendingQuestion.textContent = pending.question;
    els.pendingChip.textContent = "Pending: yes";
    els.pendingChip.className = "chip chip-warn";
    els.composerMode.textContent = "Sends to /clarification";
  } else {
    els.pendingBanner.classList.add("is-hidden");
    els.pendingQuestion.textContent = "";
    els.pendingChip.textContent = "Pending: none";
    els.pendingChip.className = "chip chip-neutral";
    els.composerMode.textContent = "Sends to /turn";
  }
}

function appendMessage({ role, tag, title = "", body = "", variant = "system" }) {
  const fragment = els.messageTemplate.content.cloneNode(true);
  const root = fragment.querySelector(".message");
  root.classList.add(`message--${variant}`);
  fragment.querySelector(".message-role").textContent = role;
  fragment.querySelector(".message-tag").textContent = tag;
  const titleNode = fragment.querySelector(".message-title");
  if (title) {
    titleNode.textContent = title;
    titleNode.classList.remove("is-hidden");
  }
  fragment.querySelector(".message-body").textContent = body;
  els.conversationLog.appendChild(fragment);
  els.conversationLog.scrollTop = els.conversationLog.scrollHeight;
}

function appendTimeline({ kind, title, body, time }) {
  const fragment = els.timelineTemplate.content.cloneNode(true);
  const root = fragment.querySelector(".timeline-item");
  fragment.querySelector(".timeline-kind").textContent = kind;
  fragment.querySelector(".timeline-time").textContent = time;
  fragment.querySelector(".timeline-title").textContent = title;
  fragment.querySelector(".timeline-body").textContent = body;
  els.timelineList.appendChild(fragment);
  els.timelineList.scrollTop = els.timelineList.scrollHeight;
  els.timelineCount.textContent = `${els.timelineList.children.length} events`;
}

function renderScenarioChips(container, values, tone = "neutral") {
  clearNode(container);
  for (const value of values || []) {
    container.appendChild(makeChip(value, tone));
  }
}

function renderScenarioList() {
  clearNode(els.scenarioList);
  els.scenarioCount.textContent = `${state.scenarios.length} scenario${state.scenarios.length === 1 ? "" : "s"}`;
  if (!state.scenarios.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No scenarios loaded.";
    els.scenarioList.appendChild(empty);
    return;
  }

  for (const scenario of state.scenarios) {
    const fragment = els.scenarioTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".scenario-item");
    const isSelected = scenario.id === state.selectedScenarioId;
    const isActive = scenario.id === state.activeScenarioId;
    root.classList.toggle("is-selected", isSelected);
    root.classList.toggle("is-active", isActive);
    root.addEventListener("click", () => selectScenario(scenario.id));

    fragment.querySelector(".scenario-item-kicker").textContent = scenario.id;
    fragment.querySelector(".scenario-item-title").textContent = scenario.title;
    fragment.querySelector(".scenario-item-state").textContent = formatScenarioState(scenario);
    fragment.querySelector(".scenario-item-subtitle").textContent = scenario.subtitle || "";
    fragment.querySelector(".scenario-item-goal").textContent = scenario.demo_goal || "";
    fragment.querySelector(".scenario-item-count").textContent = `${scenario.script?.length || 0} steps`;
    fragment.querySelector(".scenario-item-mode").textContent = `Seeds: ${scenario.seed_preferences?.length || 0}`;
    renderScenarioChips(fragment.querySelector(".scenario-item-focus"), scenario.visual_focus || [], "good");
    renderScenarioChips(fragment.querySelector(".scenario-item-dimensions"), scenario.memory_dimensions || [], "brand");

    els.scenarioList.appendChild(fragment);
  }
}

function renderSelectedScenario() {
  const scenario = getSelectedScenario();
  if (!scenario) {
    els.selectedScenarioTitle.textContent = "Select a scenario";
    els.selectedScenarioSubtitle.textContent = "Choose a scenario from the library to inspect its playback script.";
    els.selectedScenarioGoal.textContent = "The selected scenario will appear here with its demo goal and memory dimensions.";
    clearNode(els.scenarioFocus);
    clearNode(els.scenarioDimensions);
    clearNode(els.scenarioOutline);
    els.scenarioOutlineMeta.textContent = "No scenario selected";
    els.scenarioStepCount.textContent = "0";
    els.scenarioSeedCount.textContent = "0";
    els.activeStepCount.textContent = "0";
    setBadge(els.playbackStatus, "Idle", "neutral");
    updateTopChips();
    return;
  }

  els.selectedScenarioTitle.textContent = scenario.title;
  els.selectedScenarioSubtitle.textContent = scenario.subtitle || "";
  els.selectedScenarioGoal.textContent = scenario.demo_goal || "";
  renderScenarioChips(els.scenarioFocus, scenario.visual_focus || [], "good");
  renderScenarioChips(els.scenarioDimensions, scenario.memory_dimensions || [], "brand");
  els.scenarioStepCount.textContent = String(scenario.script?.length || 0);
  els.scenarioSeedCount.textContent = String(scenario.seed_preferences?.length || 0);
  els.activeStepCount.textContent = String(
    scenario.id === state.activeScenarioId ? state.activeStep : 0,
  );
  els.scenarioOutlineMeta.textContent = formatPlaybackState(scenario);
  renderScenarioOutline(scenario);
  updateTopChips();
}

function renderScenarioOutline(scenario) {
  clearNode(els.scenarioOutline);
  const script = scenario.script || [];
  if (!script.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No scripted steps available for this scenario.";
    els.scenarioOutline.appendChild(empty);
    return;
  }

  const currentIndex = state.activeScenarioId === scenario.id && state.activeStep > 0
    ? Math.min(state.activeStep - 1, script.length - 1)
    : -1;

  script.forEach((step, index) => {
    const item = document.createElement("article");
    item.className = "outline-item";
    if (index < currentIndex) {
      item.classList.add("is-done");
    }
    if (index === currentIndex) {
      item.classList.add("is-current");
    }

    const head = document.createElement("div");
    head.className = "outline-meta";
    const left = document.createElement("span");
    left.textContent = `Step ${index + 1}`;
    const right = document.createElement("span");
    right.textContent = step.kind;
    head.append(left, right);

    const title = document.createElement("strong");
    title.className = "outline-title";
    title.textContent = step.label || step.kind;

    const body = document.createElement("p");
    body.className = "outline-preview";
    body.textContent = truncate(step.text, 170);

    item.append(head, title, body);
    els.scenarioOutline.appendChild(item);
  });
}

function renderPreferences(preferences) {
  state.preferences = Array.isArray(preferences) ? preferences : [];
  els.preferenceCount.textContent = `${state.preferences.length} item${state.preferences.length === 1 ? "" : "s"}`;
  els.preferencesEmpty.classList.toggle("is-hidden", state.preferences.length > 0);
  clearNode(els.preferencesList);

  for (const record of state.preferences) {
    const fragment = els.preferenceTemplate.content.cloneNode(true);
    const root = fragment.querySelector(".preference-item");
    const sourceLabel = formatPreferenceSource(record.source);
    const statusLabel = formatPreferenceStatus(record.status);
    root.classList.toggle("is-expired", record.status === "expired");

    fragment.querySelector(".preference-name").textContent = record.preference;
    fragment.querySelector(".preference-meta").textContent = `#${record.id} · ${record.timestamp || "-"}`;
    fragment.querySelector(".preference-value").textContent = `Value: ${stringifyValue(record.value)}`;
    fragment.querySelector(".preference-condition").textContent = formatCondition(record.condition);
    fragment.querySelector(".preference-evidence").textContent = record.evidence || "No evidence provided.";

    const tags = fragment.querySelector(".preference-tags");
    tags.append(makeTag(sourceLabel, "source"));
    tags.append(makeTag(statusLabel, record.status === "expired" ? "expired" : "status"));

    els.preferencesList.appendChild(fragment);
  }
}

function renderTimelineEvent(kind, title, body, time) {
  appendTimeline({ kind, title, body, time });
}

function renderFlowFromTurn(response, step) {
  const trace = response.decision_trace || {};
  const retrievalHits = response.retrieval_hits || [];
  const retrievedPrefs = response.retrieved_preferences || trace.retrieved_preferences || [];
  const contextText = trace.parsed_context?.full_text || trace.context || step.text || "";
  const decision = response.decision || {};
  const updateSummary = buildUpdateSummary(response);

  els.flowContextTitle.textContent = step.label || "Current request";
  els.flowContextBody.textContent = truncate(contextText, 260);

  els.flowRetrievalTitle.textContent = `${retrievalHits.length} match${retrievalHits.length === 1 ? "" : "es"}`;
  clearNode(els.flowRetrievalList);
  const retrievalSource = retrievedPrefs.length ? retrievedPrefs : retrievalHits;
  if (!retrievalSource.length) {
    const item = document.createElement("li");
    item.textContent = "No relevant memory hit was used.";
    els.flowRetrievalList.appendChild(item);
  } else {
    for (const itemData of retrievalSource.slice(0, 4)) {
      const item = document.createElement("li");
      const summary = itemData.preference
        ? `${itemData.preference} = ${stringifyValue(itemData.value)}`
        : itemData.memory || itemData.render?.() || "";
      item.textContent = truncate(summary, 150);
      els.flowRetrievalList.appendChild(item);
    }
  }

  const policyLabel = decision.action ? `${decision.action} / ${decision.tool_name || "-"}` : "Idle";
  els.flowPolicyTitle.textContent = policyLabel;
  const rationale = decision.rationale ? `Rationale: ${truncate(decision.rationale, 160)}` : "No rationale provided.";
  const question = decision.question ? `Question: ${decision.question}` : "";
  els.flowPolicyBody.textContent = [rationale, question].filter(Boolean).join("\n");

  els.flowUpdateTitle.textContent = updateSummary.title;
  els.flowUpdateBody.textContent = updateSummary.body;
  els.rawTrace.textContent = pretty({
    step,
    result: response,
    decision_trace: trace,
  });

  const statusBadge = formatDecisionBadge(response);
  setBadge(els.decisionStatus, statusBadge.text, statusBadge.tone);
  setBadge(els.playbackStatus, formatPlaybackState(getSelectedScenario()), response.status === "needs_user_input" ? "warn" : "neutral");
  setBadge(els.conversationMode, formatConversationMode(step, response), response.status === "acted" ? "good" : response.status === "needs_user_input" ? "warn" : "brand");
  setPendingBanner(response.pending);
}

function renderFlowFromSummary(response, step) {
  els.flowContextTitle.textContent = step.label || "Offline summary";
  els.flowContextBody.textContent = truncate(step.text || "Offline summarization step", 260);
  els.flowRetrievalTitle.textContent = "0 matches";
  clearNode(els.flowRetrievalList);
  const item = document.createElement("li");
  item.textContent = "Summarization uses the current session transcript, not live retrieval.";
  els.flowRetrievalList.appendChild(item);
  els.flowPolicyTitle.textContent = "Summarize";
  els.flowPolicyBody.textContent = `Added ${response.count || 0} preference${response.count === 1 ? "" : "s"}.`;
  const addedSummary = Array.isArray(response.added_preferences) ? response.added_preferences : [];
  if (addedSummary.length) {
    els.flowUpdateTitle.textContent = `${addedSummary.length} preference${addedSummary.length === 1 ? "" : "s"} added`;
    els.flowUpdateBody.textContent = addedSummary
      .map((itemData) => `${itemData.preference} = ${stringifyValue(itemData.value)}`)
      .join("\n");
  } else {
    els.flowUpdateTitle.textContent = "No new preference added";
    els.flowUpdateBody.textContent = "The summarizer did not write a new preference on this turn.";
  }
  els.rawTrace.textContent = pretty({ step, result: response });
  setBadge(els.decisionStatus, "Summary", "brand");
  setBadge(els.playbackStatus, formatPlaybackState(getSelectedScenario()), "neutral");
  setBadge(els.conversationMode, "Offline summary", "brand");
  setPendingBanner(null);
}

function buildUpdateSummary(response) {
  if (response.learned_preference) {
    const learned = response.learned_preference;
    const conditionText = formatCondition(learned.condition).replace(/^Condition:\s*/, "");
    const expiredCount = Array.isArray(response.expired_preferences) ? response.expired_preferences.length : 0;
    return {
      title: "Learned new preference",
      body: [
        `${learned.preference} = ${stringifyValue(learned.value)}`,
        `Condition: ${conditionText}`,
        expiredCount ? `Expired: ${expiredCount} preference${expiredCount === 1 ? "" : "s"}` : "No preference expired.",
      ].join("\n"),
    };
  }
  const expired = Array.isArray(response.expired_preferences) ? response.expired_preferences : [];
  if (expired.length) {
    return {
      title: `${expired.length} expired preference${expired.length === 1 ? "" : "s"}`,
      body: expired
        .map((item) => `${item.preference} = ${stringifyValue(item.value)} @ ${formatCondition(item.condition).replace(/^Condition:\s*/, "")}`)
        .join("\n"),
    };
  }
  return {
    title: "No durable update",
    body: "This step did not write a new long-term preference.",
  };
}

function appendPlaybackMessages(step, response) {
  if (step.kind === "summary") {
    appendMessage({
      role: "System",
      tag: "summary",
      title: step.label || "Offline summary",
      body: `Added ${response.count || 0} preference${response.count === 1 ? "" : "s"}.\n\n${step.text || ""}`,
      variant: "system",
    });
    renderTimelineEvent(
      "SUMMARY",
      step.label || "Offline summary",
      `${response.count || 0} new preference${response.count === 1 ? "" : "s"} added.`,
      `Step ${state.activeStep}`,
    );
    return;
  }

  if (step.kind === "clarification") {
    appendMessage({
      role: "User",
      tag: "clarification answer",
      title: step.label || "Clarification answer",
      body: step.text || "",
      variant: "user",
    });
    appendMessage({
      role: "Assistant",
      tag: response.status === "needs_user_input" ? "ASK" : response.status || "acted",
      title: response.decision?.tool_name || "Result",
      body: response.assistant_text || "(no assistant text)",
      variant: "assistant",
    });
  } else {
    appendMessage({
      role: "User",
      tag: "turn",
      title: step.label || "User turn",
      body: step.text || "",
      variant: "user",
    });
    appendMessage({
      role: "Assistant",
      tag: response.status === "needs_user_input" ? "ASK" : response.status || "acted",
      title: response.decision?.tool_name || "Result",
      body: response.assistant_text || "(no assistant text)",
      variant: "assistant",
    });
  }
}

function appendPlaybackTimeline(step, response) {
  const summaryParts = [];
  if (response.decision?.action) {
    summaryParts.push(`${response.decision.action} via ${response.decision.tool_name}`);
  }
  if (response.pending) {
    summaryParts.push("clarification pending");
  }
  if (response.learned_preference) {
    const learned = response.learned_preference;
    summaryParts.push(`learned ${learned.preference} = ${stringifyValue(learned.value)}`);
  }
  if (Array.isArray(response.expired_preferences) && response.expired_preferences.length) {
    summaryParts.push(`${response.expired_preferences.length} expired`);
  }
  if (!summaryParts.length) {
    summaryParts.push(response.status || "completed");
  }
  renderTimelineEvent(
    step.kind.toUpperCase(),
    step.label || step.kind,
    summaryParts.join(" · "),
    `Step ${state.activeStep}`,
  );
}

function updateTopChips() {
  const scenario = getSelectedScenario();
  setChip(els.memoryChip, `Memory: ${state.memoryMode || "unknown"}`, state.memoryMode === "lightmem" ? "good" : "neutral");
  setChip(els.scenarioChip, scenario ? `Scenario: ${scenario.title}` : "Scenario: none", scenario ? "brand" : "neutral");
  const totalSteps = scenario?.script?.length || 0;
  setChip(els.stepChip, `Step: ${state.activeStep}/${totalSteps}`, totalSteps ? "good" : "neutral");
  if (state.pendingId) {
    setChip(els.pendingChip, "Pending: yes", "warn");
  } else {
    setChip(els.pendingChip, "Pending: none", "neutral");
  }
}

function setRuntimeFromHealth(payload) {
  state.memoryMode = payload.memory_mode || "unknown";
  state.activeScenarioId = payload.active_scenario_id || state.activeScenarioId || null;
  setChip(els.apiChip, "API: online", "good");
  updateTopChips();
}

function syncScenarioSelection() {
  const storedId = readStoredValue(STORAGE_KEYS.scenarioId, "");
  if (storedId && state.scenarios.some((scenario) => scenario.id === storedId)) {
    state.selectedScenarioId = storedId;
  }
  if (!state.selectedScenarioId || !state.scenarios.some((scenario) => scenario.id === state.selectedScenarioId)) {
    state.selectedScenarioId = state.activeScenarioId || state.scenarios[0]?.id || null;
  }
  writeStoredValue(STORAGE_KEYS.scenarioId, state.selectedScenarioId || "");
}

function getSelectedScenario() {
  return state.scenarios.find((scenario) => scenario.id === state.selectedScenarioId) || null;
}

async function apiGet(path) {
  const response = await fetch(`${state.apiBase}${path}`);
  return parseJsonResponse(response);
}

async function apiPost(path, payload) {
  const response = await fetch(`${state.apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload || {}),
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

async function loadHealth({ silent = true } = {}) {
  try {
    const payload = await apiGet("/health");
    setRuntimeFromHealth(payload);
    if (!silent) {
      appendMessage({
        role: "System",
        tag: "health",
        title: "Health check",
        body: `API online. Memory mode: ${payload.memory_mode || "unknown"}.`,
        variant: "system",
      });
    }
    return payload;
  } catch (error) {
    setChip(els.apiChip, "API: offline", "danger");
    setChip(els.memoryChip, "Memory: unavailable", "danger");
    if (!silent) {
      appendMessage({
        role: "System",
        tag: "health",
        title: "Health check failed",
        body: error.message,
        variant: "system",
      });
    }
    throw error;
  }
}

async function loadScenarios() {
  const payload = await apiGet("/scenarios");
  state.scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  state.activeScenarioId = payload.active_scenario_id || state.activeScenarioId || null;
  state.activeStep = Number(payload.active_step || 0);
  syncScenarioSelection();
  renderScenarioList();
  renderSelectedScenario();
  return payload;
}

async function loadPreferences() {
  const payload = await apiGet("/preferences");
  renderPreferences(payload.preferences || []);
  return payload;
}

async function refreshWorkspace() {
  setBusy(true);
  try {
    await Promise.allSettled([loadHealth(), loadScenarios(), loadPreferences()]);
    if (!state.scenarios.length) {
      renderSelectedScenario();
    }
    updateTopChips();
  } finally {
    setBusy(false);
    toggleAutoLabel();
  }
}

function selectScenario(scenarioId) {
  state.selectedScenarioId = scenarioId;
  writeStoredValue(STORAGE_KEYS.scenarioId, scenarioId || "");
  renderScenarioList();
  renderSelectedScenario();
}

async function runSelectedScenario({ auto = false } = {}) {
  const scenario = getSelectedScenario();
  if (!scenario) {
    appendMessage({
      role: "System",
      tag: "scenario",
      title: "No scenario selected",
      body: "Choose a scenario before running playback.",
      variant: "system",
    });
    return null;
  }
  if (!auto) {
    stopAutoPlay();
  }
  resetPlaybackViews();
  appendMessage({
    role: "System",
    tag: "scenario",
    title: "Playback started",
    body: `${scenario.title}\n\n${scenario.demo_goal || ""}`,
    variant: "system",
  });
  setBadge(els.playbackStatus, auto ? "Auto playing" : "Running", "brand");
  setBusy(true);
  try {
    const response = await apiPost("/demo/run", {
      session_id: "default",
      scenario_id: scenario.id,
    });
    applyPlaybackResponse(response);
    await loadPreferences();
    return response;
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Playback failed",
      body: error.message,
      variant: "system",
    });
    setBadge(els.playbackStatus, "Error", "danger");
    throw error;
  } finally {
    setBusy(false);
    updateTopChips();
  }
}

async function advanceSelectedScenario() {
  const scenario = getSelectedScenario();
  if (!scenario) {
    return runSelectedScenario();
  }
  if (state.activeScenarioId !== scenario.id) {
    return runSelectedScenario();
  }
  setBusy(true);
  try {
    const response = await apiPost("/demo/advance", {
      session_id: "default",
    });
    applyPlaybackResponse(response);
    await loadPreferences();
    return response;
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Advance failed",
      body: error.message,
      variant: "system",
    });
    setBadge(els.playbackStatus, "Error", "danger");
    throw error;
  } finally {
    setBusy(false);
    updateTopChips();
  }
}

function applyPlaybackResponse(response) {
  if (!response) {
    return;
  }
  state.currentResult = response.result || null;
  state.currentStep = response.step || null;
  state.activeScenarioId = response.scenario_id || state.activeScenarioId;
  state.activeStep = Number(response.step_index || 0);
  const scenario = getSelectedScenario();

  if (response.status === "completed") {
    setBadge(els.playbackStatus, "Completed", "good");
    setBadge(els.conversationMode, "Completed", "good");
    setBadge(els.decisionStatus, "Completed", "good");
    appendMessage({
      role: "System",
      tag: "scenario",
      title: "Playback completed",
      body: "The scripted scenario finished all of its steps.",
      variant: "system",
    });
    renderTimelineEvent(
      "DONE",
      scenario?.title || response.scenario_name || "Scenario",
      "Playback completed.",
      `Step ${state.activeStep}`,
    );
    renderScenarioList();
    renderSelectedScenario();
    updateTopChips();
    return;
  }

  const step = response.step || { kind: "turn", label: "Step", text: "" };
  const result = response.result || {};
  appendPlaybackMessages(step, result);
  appendPlaybackTimeline(step, result);

  if (step.kind === "summary") {
    renderFlowFromSummary(result, step);
  } else {
    renderFlowFromTurn(result, step);
  }

  if (result.status !== "needs_user_input") {
    setPendingBanner(null);
  }

  renderScenarioList();
  renderSelectedScenario();
  updateTopChips();
}

function appendPlaybackMessages(step, response) {
  appendPlaybackMessagesInternal(step, response);
}

function appendPlaybackMessagesInternal(step, response) {
  if (step.kind === "summary") {
    appendMessage({
      role: "System",
      tag: "summary",
      title: step.label || "Offline summary",
      body: `${step.text || ""}\n\nAdded ${response.count || 0} preference${response.count === 1 ? "" : "s"}.`,
      variant: "system",
    });
    return;
  }

  if (step.kind === "clarification") {
    appendMessage({
      role: "User",
      tag: "clarification answer",
      title: step.label || "Clarification answer",
      body: step.text || "",
      variant: "user",
    });
    appendMessage({
      role: "Assistant",
      tag: response.status === "needs_user_input" ? "ASK" : response.status || "acted",
      title: response.decision?.tool_name || "Result",
      body: response.assistant_text || "(no assistant text)",
      variant: "assistant",
    });
    return;
  }

  appendMessage({
    role: "User",
    tag: "turn",
    title: step.label || "User turn",
    body: step.text || "",
    variant: "user",
  });
  appendMessage({
    role: "Assistant",
    tag: response.status === "needs_user_input" ? "ASK" : response.status || "acted",
    title: response.decision?.tool_name || "Result",
    body: response.assistant_text || "(no assistant text)",
    variant: "assistant",
  });
}

async function summarizeSession() {
  setBusy(true);
  try {
    const response = await apiPost("/summarize", { session_id: "default" });
    appendMessage({
      role: "System",
      tag: "summary",
      title: "Manual summary",
      body: `Added ${response.count || 0} preference${response.count === 1 ? "" : "s"}.`,
      variant: "system",
    });
    renderTimelineEvent(
      "SUMMARY",
      "Manual summary",
      `Added ${response.count || 0} preference${response.count === 1 ? "" : "s"}.`,
      "Manual",
    );
    await loadPreferences();
    return response;
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Summary failed",
      body: error.message,
      variant: "system",
    });
    throw error;
  } finally {
    setBusy(false);
  }
}

async function resetWorkspace() {
  stopAutoPlay();
  setBusy(true);
  try {
    await apiPost("/reset", { session_id: "default" });
    state.activeScenarioId = null;
    state.activeStep = 0;
    state.currentResult = null;
    state.currentStep = null;
    state.pendingId = null;
    state.pendingQuestion = "";
    resetPlaybackViews();
    appendMessage({
      role: "System",
      tag: "reset",
      title: "Workspace reset",
      body: "The demo state has been cleared.",
      variant: "system",
    });
    await refreshWorkspace();
    return true;
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Reset failed",
      body: error.message,
      variant: "system",
    });
    throw error;
  } finally {
    setBusy(false);
  }
}

async function checkApi() {
  setBusy(true);
  try {
    await loadHealth({ silent: false });
  } finally {
    setBusy(false);
    updateTopChips();
  }
}

function stopAutoPlay() {
  state.autoRunning = false;
  if (state.autoTimer) {
    clearTimeout(state.autoTimer);
    state.autoTimer = null;
  }
  toggleAutoLabel();
}

async function startAutoPlay() {
  if (state.autoRunning) {
    stopAutoPlay();
    return;
  }
  const scenario = getSelectedScenario();
  if (!scenario) {
    appendMessage({
      role: "System",
      tag: "scenario",
      title: "Select a scenario first",
      body: "Choose a scenario before starting auto play.",
      variant: "system",
    });
    return;
  }

  state.autoRunning = true;
  toggleAutoLabel();
  try {
    await runSelectedScenario({ auto: true });
    while (state.autoRunning) {
      const current = getSelectedScenario();
      if (!current || state.activeScenarioId !== current.id) {
        break;
      }
      if (state.activeStep >= (current.script?.length || 0)) {
        break;
      }
      await sleep(AUTO_STEP_DELAY_MS);
      if (!state.autoRunning) {
        break;
      }
      const response = await advanceSelectedScenario();
      if (response?.status === "completed") {
        break;
      }
    }
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Auto play failed",
      body: error.message,
      variant: "system",
    });
  } finally {
    stopAutoPlay();
  }
}

function sleep(ms) {
  return new Promise((resolve) => {
    state.autoTimer = window.setTimeout(resolve, ms);
  });
}

async function submitUserInput(event) {
  event.preventDefault();
  const text = els.userInput.value.trim();
  if (!text) {
    return;
  }
  stopAutoPlay();
  els.userInput.value = "";
  setBusy(true);
  try {
    let response;
    if (state.pendingId) {
      response = await apiPost("/clarification", {
        session_id: "default",
        pending_id: state.pendingId,
        answer: text,
      });
    } else {
      response = await apiPost("/turn", {
        session_id: "default",
        text,
      });
    }
    const step = state.pendingId
      ? { kind: "clarification", label: "Manual clarification", text }
      : { kind: "turn", label: "Manual turn", text };
    appendPlaybackMessages(step, response);
    if (step.kind === "summary") {
      renderFlowFromSummary(response, step);
    } else {
      renderFlowFromTurn(response, step);
    }
    appendPlaybackTimeline(step, response);
    await loadPreferences();
    updateTopChips();
  } catch (error) {
    appendMessage({
      role: "System",
      tag: "error",
      title: "Send failed",
      body: error.message,
      variant: "system",
    });
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  els.apiBase.addEventListener("change", () => {
    setApiBase(els.apiBase.value);
  });
  els.checkHealthBtn.addEventListener("click", () => {
    checkApi().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Health check failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.reloadBtn.addEventListener("click", () => {
    refreshWorkspace().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Reload failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.runBtn.addEventListener("click", () => {
    stopAutoPlay();
    runSelectedScenario().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Run failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.stepBtn.addEventListener("click", () => {
    stopAutoPlay();
    advanceSelectedScenario().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Step failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.autoBtn.addEventListener("click", () => {
    startAutoPlay().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Auto play failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.summarizeBtn.addEventListener("click", () => {
    stopAutoPlay();
    summarizeSession().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Summary failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.resetBtn.addEventListener("click", () => {
    resetWorkspace().catch((error) => {
      appendMessage({
        role: "System",
        tag: "error",
        title: "Reset failed",
        body: error.message,
        variant: "system",
      });
    });
  });
  els.composer.addEventListener("submit", (event) => {
    submitUserInput(event);
  });
}

async function bootstrap() {
  setApiBase(readStoredValue(STORAGE_KEYS.apiBase, DEFAULT_API_BASE));
  const storedScenarioId = readStoredValue(STORAGE_KEYS.scenarioId, "");
  if (storedScenarioId) {
    state.selectedScenarioId = storedScenarioId;
  }
  bindEvents();
  toggleAutoLabel();
  setBadge(els.playbackStatus, "Idle", "neutral");
  setBadge(els.decisionStatus, "No turn yet", "neutral");
  setBadge(els.conversationMode, "Waiting", "neutral");
  setChip(els.apiChip, "API: checking", "neutral");
  setChip(els.memoryChip, "Memory: unknown", "neutral");
  setChip(els.scenarioChip, "Scenario: none", "neutral");
  setChip(els.stepChip, "Step: 0/0", "neutral");
  setChip(els.pendingChip, "Pending: none", "neutral");
  await refreshWorkspace();
  appendMessage({
    role: "System",
    tag: "init",
    title: "Demo ready",
    body: "Choose a scenario, run the scripted playback, or send a manual English turn.",
    variant: "system",
  });
}

bootstrap().catch((error) => {
  appendMessage({
    role: "System",
    tag: "fatal",
    title: "Bootstrap failed",
    body: error.message,
    variant: "system",
  });
  setChip(els.apiChip, "API: offline", "danger");
});
