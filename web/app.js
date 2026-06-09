const SIDEBAR_PANEL_COLLAPSED_PREFIX = "vds-lite-sidebar-panel-collapsed";
const PROJECT_VISIBLE_LIMIT = 5;
const PROJECT_CHAT_VISIBLE_LIMIT = 5;
const THINKING_PHASES = [
  {
    key: "context",
    label: "读取数据上下文",
    detail: "读取已上传表、字段 profile、样例值和项目历史。",
    thresholdMs: 0,
  },
  {
    key: "prompt",
    label: "组织分析提示",
    detail: "把用户问题、业务口径、表关系和对话历史整理给 LLM。",
    thresholdMs: 900,
  },
  {
    key: "llm",
    label: "LLM 生成方案",
    detail: "等待 LLM 判断分析意图、表选择、图表和 Pandas 代码。",
    thresholdMs: 2400,
  },
  {
    key: "execute",
    label: "执行 Pandas",
    detail: "后端运行生成代码，得到直接答案、表格和图表数据。",
    thresholdMs: 7600,
  },
  {
    key: "verify",
    label: "语义校验",
    detail: "检查结果是否回答了问题，必要时触发修复重试。",
    thresholdMs: 11200,
  },
  {
    key: "render",
    label: "渲染回答",
    detail: "整理最终回答、表格、图表和执行记录。",
    thresholdMs: 15000,
  },
];

const state = {
  datasetId: "",
  projectId: "",
  conversationId: "",
  profile: null,
  projects: [],
  projectConversations: {},
  projectListExpanded: false,
  projectChatExpanded: {},
  projectExpanded: {},
  conversations: [],
  projectDetail: null,
  projectTab: "chats",
  selectedFiles: [],
  contextStatus: "等待选择文件。",
  pendingTurnId: "",
  sidebarPanelCollapsed: {},
  uploadBannerTimer: 0,
  uploadProgress: 0,
  searchTimer: 0,
  searchRequestId: 0,
  searchResults: [],
  operationsPage: "",
  opsMetrics: {},
  evalRecords: [],
  ragDocuments: [],
  ragQaPairs: [],
  analysisTemplates: [],
  experienceCases: [],
  thinkingTrace: null,
  thinkingTraces: {},
  thinkingTimer: 0,
  thinkingDrawerOpen: false,
};

const el = {
  workspace: document.querySelector(".workspace"),
  fileInput: document.querySelector("#file-input"),
  composerFrame: document.querySelector(".composer-frame"),
  composerFileList: document.querySelector("#composer-file-list"),
  uploadStatus: document.querySelector("#upload-status"),
  uploadBanner: document.querySelector("#upload-banner"),
  uploadBannerTitle: document.querySelector("#upload-banner-title"),
  uploadBannerDetail: document.querySelector("#upload-banner-detail"),
  uploadBannerProgress: document.querySelector("#upload-banner-progress"),
  uploadBannerBarFill: document.querySelector("#upload-banner-bar-fill"),
  uploadBannerClose: document.querySelector("#upload-banner-close"),
  datasetChip: document.querySelector("#dataset-chip"),
  tableCount: document.querySelector("#table-count"),
  drawerTableCount: document.querySelector("#drawer-table-count"),
  profileList: document.querySelector("#profile-list"),
  drawerProfileList: document.querySelector("#drawer-profile-list"),
  questionInput: document.querySelector("#question-input"),
  askButton: document.querySelector("#ask-button"),
  apiStatus: document.querySelector("#api-status"),
  answer: document.querySelector("#answer"),
  errorBox: document.querySelector("#error-box"),
  resultTable: document.querySelector("#result-table"),
  codeView: document.querySelector("#code-view"),
  attemptList: document.querySelector("#attempt-list"),
  runId: document.querySelector("#run-id"),
  rowCount: document.querySelector("#row-count"),
  attemptCount: document.querySelector("#attempt-count"),
  intentLabel: document.querySelector("#intent-label"),
  emptyState: document.querySelector("#empty-state"),
  conversation: document.querySelector("#conversation"),
  questionHistory: document.querySelector("#question-history"),
  scrollBottomButton: document.querySelector("#scroll-bottom-button"),
  assistantCard: document.querySelector("#assistant-card"),
  composerHint: document.querySelector("#composer-hint"),
  profileToggle: document.querySelector("#profile-toggle"),
  profileDrawer: document.querySelector("#profile-drawer"),
  profileDrawerBackdrop: document.querySelector("#profile-drawer-backdrop"),
  drawerClose: document.querySelector("#drawer-close"),
  newProjectButton: document.querySelector("#new-project-button"),
  newChatButton: document.querySelector("#new-chat-button"),
  projectList: document.querySelector("#project-list"),
  conversationList: document.querySelector("#conversation-list"),
  projectHome: document.querySelector("#project-home"),
  projectHomeTitle: document.querySelector("#project-home-title"),
  projectHomeNewChat: document.querySelector("#project-home-new-chat"),
  projectTabChats: document.querySelector("#project-tab-chats"),
  projectTabSources: document.querySelector("#project-tab-sources"),
  projectChatsPanel: document.querySelector("#project-chats-panel"),
  projectSourcesPanel: document.querySelector("#project-sources-panel"),
  projectConversationList: document.querySelector("#project-conversation-list"),
  projectSourceInput: document.querySelector("#project-source-input"),
  projectSourceList: document.querySelector("#project-source-list"),
  contextMenu: document.querySelector("#context-menu"),
  searchOpenButton: document.querySelector("#search-open-button"),
  searchModal: document.querySelector("#search-modal"),
  searchModalBackdrop: document.querySelector("#search-modal-backdrop"),
  searchInput: document.querySelector("#search-input"),
  searchCloseButton: document.querySelector("#search-close-button"),
  searchNewChat: document.querySelector("#search-new-chat"),
  searchStatus: document.querySelector("#search-status"),
  searchResults: document.querySelector("#search-results"),
  opsMenuButton: document.querySelector("#ops-menu-button"),
  opsMenu: document.querySelector("#ops-menu"),
  opsMenuMonitor: document.querySelector("#ops-menu-monitor"),
  opsMenuRag: document.querySelector("#ops-menu-rag"),
  opsMenuTemplate: document.querySelector("#ops-menu-template"),
  operationsPages: document.querySelector("#operations-pages"),
  monitorPage: document.querySelector("#monitor-page"),
  ragPage: document.querySelector("#rag-page"),
  templatePage: document.querySelector("#template-page"),
  opsMetricGrid: document.querySelector("#ops-metric-grid"),
  opsEvalTable: document.querySelector("#ops-eval-table"),
  evalRecordForm: document.querySelector("#eval-record-form"),
  addEvalRecordButton: document.querySelector("#add-eval-record-button"),
  ragDocInput: document.querySelector("#rag-doc-input"),
  ragPipeline: document.querySelector("#rag-pipeline"),
  ragDocumentList: document.querySelector("#rag-document-list"),
  ragEntityLinks: document.querySelector("#rag-entity-links"),
  ragQaForm: document.querySelector("#rag-qa-form"),
  ragRetrievalConfig: document.querySelector("#rag-retrieval-config"),
  templateLibrary: document.querySelector("#template-library"),
  templateForm: document.querySelector("#template-form"),
  addTemplateButton: document.querySelector("#add-template-button"),
  experienceLibrary: document.querySelector("#experience-library"),
  thinkingDrawer: document.querySelector("#thinking-drawer"),
  thinkingDrawerBackdrop: document.querySelector("#thinking-drawer-backdrop"),
  thinkingDrawerClose: document.querySelector("#thinking-drawer-close"),
  thinkingStatus: document.querySelector("#thinking-status"),
  thinkingDrawerBody: document.querySelector("#thinking-drawer-body"),
};

el.fileInput.addEventListener("change", handleFileSelection);
el.composerFileList.addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-upload-action='clear']");
  if (!removeButton) return;
  clearUploadedFileContext();
});
el.uploadBannerClose.addEventListener("click", hideUploadBanner);
el.askButton.addEventListener("click", askQuestion);
el.scrollBottomButton.addEventListener("click", scrollConversationToBottom);
el.workspace.addEventListener("scroll", updateScrollBottomButton);
el.profileToggle.addEventListener("click", toggleDrawer);
el.drawerClose.addEventListener("click", closeDrawer);
el.profileDrawerBackdrop.addEventListener("click", closeDrawer);
el.thinkingDrawerClose.addEventListener("click", closeThinkingDrawer);
el.thinkingDrawerBackdrop.addEventListener("click", closeThinkingDrawer);
el.newProjectButton.addEventListener("click", createProject);
el.newChatButton.addEventListener("click", startUnprojectedConversation);
el.projectHomeNewChat.addEventListener("click", () => createConversation({ projectId: state.projectId }));
el.projectTabChats.addEventListener("click", () => setProjectTab("chats"));
el.projectTabSources.addEventListener("click", () => setProjectTab("sources"));
el.projectSourceInput.addEventListener("change", () => handleProjectSourceSelection());
el.searchOpenButton.addEventListener("click", openSearchModal);
el.opsMenuButton.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleOpsMenu();
});
el.opsMenuMonitor.addEventListener("click", () => showOperationsPage("monitor"));
el.opsMenuRag.addEventListener("click", () => showOperationsPage("rag"));
el.opsMenuTemplate.addEventListener("click", () => showOperationsPage("template"));
el.addEvalRecordButton.addEventListener("click", () => {
  showOperationsPage("monitor");
  el.evalRecordForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
el.evalRecordForm.addEventListener("submit", addEvaluationRecord);
el.ragDocInput.addEventListener("change", addRagDocumentRecord);
el.ragQaForm.addEventListener("submit", addRagQaPair);
el.addTemplateButton.addEventListener("click", () => {
  showOperationsPage("template");
  el.templateForm.scrollIntoView({ behavior: "smooth", block: "nearest" });
});
el.templateForm.addEventListener("submit", addAnalysisTemplateRecord);
el.searchCloseButton.addEventListener("click", closeSearchModal);
el.searchModalBackdrop.addEventListener("click", closeSearchModal);
el.searchNewChat.addEventListener("click", async () => {
  closeSearchModal();
  await startUnprojectedConversation();
});
el.searchInput.addEventListener("input", () => scheduleSearch(el.searchInput.value));
document.addEventListener("click", (event) => {
  const thinkingTrigger = event.target.closest("[data-thinking-action='open']");
  if (thinkingTrigger) {
    event.preventDefault();
    openThinkingDrawer(thinkingTrigger.dataset.thinkingId || "");
    return;
  }
  if (!el.opsMenu.contains(event.target) && !el.opsMenuButton.contains(event.target)) closeOpsMenu();
  if (!el.contextMenu.contains(event.target)) closeContextMenu();
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openSearchModal();
    return;
  }
  if (event.key === "Escape" && !el.searchModal.classList.contains("hidden")) {
    closeSearchModal();
    return;
  }
  if (event.key === "Escape" && !el.thinkingDrawer.classList.contains("hidden")) {
    closeThinkingDrawer();
  }
});
for (const toggle of document.querySelectorAll("[data-collapse-target]")) {
  toggle.addEventListener("click", () => toggleSidebarSection(toggle));
}
document.addEventListener("pointerover", activateChartHit);
document.addEventListener("click", activateChartHit);
document.addEventListener("focusin", activateChartHit);
el.questionInput.addEventListener("input", () => {
  autoResize();
  updateAskState();
});
el.questionInput.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    if (!el.askButton.disabled) askQuestion();
  }
});

initSidebarPanels();
initWorkspace();
updateAskState();
autoResize();

async function initWorkspace() {
  await checkHealth();
  await loadOperationsStateFromApi();
  await loadProjects();
}

function autoResize() {
  el.questionInput.style.height = "auto";
  el.questionInput.style.height = `${Math.min(el.questionInput.scrollHeight, 200)}px`;
}

function updateAskState() {
  el.askButton.disabled = !state.datasetId || !el.questionInput.value.trim();
}

async function handleFileSelection() {
  const files = [...el.fileInput.files];
  state.selectedFiles = files;
  if (!files.length) return;

  el.composerHint.textContent = files.map((file) => file.name).join(" / ");
  state.uploadProgress = 0;
  renderComposerFiles(files, "uploading", "", state.uploadProgress);
  await uploadFiles(files);
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    el.apiStatus.textContent = "准备就绪";
    el.apiStatus.className = "status-chip ok";
  } catch (error) {
    el.apiStatus.textContent = "API 异常";
    el.apiStatus.className = "status-chip error";
  }
}

async function uploadFiles(files) {
  const summary = formatFileUploadSummary(files);
  showUploadBanner({
    status: "uploading",
    title: "正在上传文件",
    detail: `${summary.names} · ${summary.sizeText}`,
    progress: 0,
  });
  setBusy(true, { contextMessage: "正在上传文件..." });
  try {
    const formData = new FormData();
    if (state.projectId) formData.append("project_id", state.projectId);
    let payload;

    if (files.length === 1) {
      formData.append("file", files[0]);
      payload = await postForm("/api/chat/upload", formData, {
        onProgress: (progress) => updateUploadProgress(progress, summary),
      });
    } else {
      for (const file of files) formData.append("files", file);
      payload = await postForm("/api/chat/upload-batch", formData, {
        onProgress: (progress) => updateUploadProgress(progress, summary),
      });
    }

    applyDataset(payload, files);
    state.uploadProgress = 100;
    renderComposerFiles(files, "ready", "", state.uploadProgress);
    showUploadBanner({
      status: "success",
      title: "文件已解析完成",
      detail: describeUploadedDataset(payload.profile),
      progress: 100,
      autoHideMs: 5200,
    });
  } catch (error) {
    state.datasetId = "";
    state.conversationId = "";
    state.profile = null;
    renderComposerFiles(files, "error", error.message);
    el.uploadStatus.textContent = `上传失败：${error.message}`;
    el.composerHint.textContent = `上传失败：${error.message}`;
    el.datasetChip.textContent = "上传失败";
    showUploadBanner({
      status: "error",
      title: "上传失败",
      detail: error.message,
      progress: 100,
    });
    updateAskState();
  } finally {
    setBusy(false);
    el.fileInput.value = "";
  }
}

async function askQuestion() {
  const question = el.questionInput.value.trim();
  if (!state.datasetId || !question) return;

  appendUserQuestion(question);
  startThinkingTrace(question);
  renderPending();
  setBusy(true, { hintMessage: "LLM 正在读取文件、生成 Pandas 并执行..." });

  try {
    const response = await fetch("/api/chat/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: state.datasetId,
        question,
        project_id: state.projectId,
        conversation_id: state.conversationId,
      }),
    });
    if (!response.ok) throw new Error((await readErrorMessage(response)) || `HTTP ${response.status}`);
    renderResult(await response.json());
  } catch (error) {
    removePendingTurn();
    el.errorBox.textContent = `分析失败：${error.message}`;
    el.errorBox.classList.remove("hidden");
    const errorResult = {
      run_id: "",
      direct_answer: "",
      rows: [],
      columns: [],
      attempts: [],
      pandas_code: "",
      execution_error: `分析失败：${error.message}`,
    };
    finishThinkingTrace(errorResult);
    errorResult.thinking_trace = state.thinkingTrace;
    appendAssistantTurn(errorResult);
  } finally {
    setBusy(false);
  }
}

async function postForm(url, formData, { onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", url);
    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const progress = Math.max(0, Math.min(99, Math.round((event.loaded / event.total) * 100)));
      onProgress?.({ phase: "uploading", progress });
    });
    request.upload.addEventListener("load", () => {
      onProgress?.({ phase: "processing", progress: 100 });
    });
    request.addEventListener("load", () => {
      const contentType = request.getResponseHeader("content-type") || "";
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(parseXhrError(request, contentType) || `HTTP ${request.status}`));
        return;
      }
      try {
        resolve(contentType.includes("application/json") ? JSON.parse(request.responseText || "{}") : request.responseText);
      } catch (error) {
        reject(new Error(`响应解析失败：${error.message}`));
      }
    });
    request.addEventListener("error", () => reject(new Error("网络错误，文件没有上传成功。")));
    request.addEventListener("timeout", () => reject(new Error("上传超时，请重试。")));
    request.send(formData);
  });
}

async function readErrorMessage(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = await response.json();
    return payload.detail || payload.message || JSON.stringify(payload);
  }
  return response.text();
}

function applyDataset(payload, files) {
  state.datasetId = payload.dataset_id;
  state.projectId = payload.project_id || state.projectId;
  state.profile = payload.profile;
  state.contextStatus = `已读取 ${files.map((file) => file.name).join(" / ")}`;

  el.datasetChip.textContent = formatDatasetKind(payload.profile.dataset_kind);
  el.uploadStatus.textContent = state.contextStatus;
  el.composerHint.textContent = "文件已读入，现在可以直接提问。";
  renderComposerFiles(files, "ready");
  renderProfile(payload.profile);
  updateAskState();
  loadConversations(state.projectId);
  loadProjectDetail(state.projectId);
}

async function loadOperationsStateFromApi() {
  try {
    applyOperationsState(await getJson("/api/ops/state"));
  } catch (error) {
    state.evalRecords = [];
    state.ragDocuments = [];
    state.ragQaPairs = [];
    state.analysisTemplates = [];
    state.experienceCases = [];
    state.opsMetrics = {};
    updateOpsMetrics();
    el.composerHint.textContent = `管理页加载失败：${error.message}`;
  }
}

function applyOperationsState(payload) {
  const rag = payload.rag || {};
  state.evalRecords = Array.isArray(payload.evaluations) ? payload.evaluations : [];
  state.ragDocuments = Array.isArray(rag.documents) ? rag.documents : [];
  state.ragQaPairs = Array.isArray(rag.qa_pairs) ? rag.qa_pairs : [];
  state.analysisTemplates = Array.isArray(payload.templates) ? payload.templates : [];
  state.experienceCases = Array.isArray(payload.experience_cases) ? payload.experience_cases : [];
  state.opsMetrics = payload.metrics || {};
  updateOpsMetrics();
  if (state.operationsPage) renderOperationsPage();
}

function updateOpsMetrics() {
  const records = state.evalRecords;
  const average = (key) => records.length
    ? records.reduce((sum, record) => sum + Number(record[key] || 0), 0) / records.length
    : 0;
  state.opsMetrics = {
    exactness: Number(state.opsMetrics.exactness ?? average("exactness")),
    faithfulness: Number(state.opsMetrics.faithfulness ?? average("faithfulness")),
    coverage: Number(state.opsMetrics.coverage ?? average("coverage")),
    safety: Number(state.opsMetrics.safety ?? average("safety")),
    totalRuns: Number(state.opsMetrics.total_runs ?? state.opsMetrics.totalRuns ?? records.length),
    riskCount: Number(state.opsMetrics.risk_count ?? state.opsMetrics.riskCount ?? records.filter((record) => Math.min(record.exactness, record.faithfulness, record.coverage, record.safety) < 0.8).length),
  };
}

function toggleOpsMenu() {
  const open = el.opsMenu.classList.contains("hidden");
  el.opsMenu.classList.toggle("hidden", !open);
  el.opsMenuButton.setAttribute("aria-expanded", String(open));
}

function closeOpsMenu() {
  el.opsMenu.classList.add("hidden");
  el.opsMenuButton.setAttribute("aria-expanded", "false");
}

function showOperationsPage(page) {
  state.operationsPage = page;
  closeOpsMenu();
  closeSearchModal();
  closeDrawer();
  closeThinkingDrawer();
  el.emptyState.classList.add("hidden");
  el.projectHome.classList.add("hidden");
  el.conversation.classList.add("hidden");
  el.operationsPages.classList.remove("hidden");
  for (const section of [el.monitorPage, el.ragPage, el.templatePage]) {
    section.classList.toggle("hidden", section.dataset.opsPage !== page);
  }
  el.opsMenuButton.classList.toggle("active", Boolean(page));
  renderOperationsPage();
}

function hideOperationsPage() {
  state.operationsPage = "";
  el.operationsPages.classList.add("hidden");
  el.opsMenuButton.classList.remove("active");
}

function renderOperationsPage() {
  renderMonitorPage();
  renderRagPage();
  renderTemplatePage();
}

function renderMonitorPage() {
  const metrics = [
    ["Exactness", state.opsMetrics.exactness, "答案数字和对象是否准确"],
    ["Faithfulness", state.opsMetrics.faithfulness, "答案是否忠于数据和证据"],
    ["Coverage", state.opsMetrics.coverage, "是否覆盖用户问题的全部义务"],
    ["Safety", state.opsMetrics.safety, "是否遵守安全边界和口径边界"],
  ];
  el.opsMetricGrid.innerHTML = metrics.map(([label, value, note]) => `
    <div class="ops-metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${formatScore(value)}</strong>
      <p>${escapeHtml(note)}</p>
    </div>
  `).join("") + `
    <div class="ops-metric-card compact">
      <span>记录数</span>
      <strong>${state.opsMetrics.totalRuns}</strong>
      <p>${state.opsMetrics.riskCount} 条低分风险</p>
    </div>
  `;
  el.opsEvalTable.innerHTML = `
    <table>
      <thead>
        <tr><th>Run</th><th>问题</th><th>Exactness</th><th>Faithfulness</th><th>Coverage</th><th>Safety</th><th>备注</th></tr>
      </thead>
      <tbody>
        ${state.evalRecords.map((record) => `
          <tr>
            <td>${escapeHtml(record.run_id || record.runId || "")}</td>
            <td>${escapeHtml(record.question)}</td>
            <td>${formatScore(record.exactness)}</td>
            <td>${formatScore(record.faithfulness)}</td>
            <td>${formatScore(record.coverage)}</td>
            <td>${formatScore(record.safety)}</td>
            <td>${escapeHtml(record.notes)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function addEvaluationRecord(event) {
  event.preventDefault();
  const form = new FormData(el.evalRecordForm);
  await postEvaluationRecord({
    run_id: String(form.get("runId") || "").trim() || `run_manual_${Date.now()}`,
    question: String(form.get("question") || "").trim() || "未命名问题",
    exactness: clampScore(form.get("exactness")),
    faithfulness: clampScore(form.get("faithfulness")),
    coverage: clampScore(form.get("coverage")),
    safety: clampScore(form.get("safety")),
    notes: String(form.get("notes") || "").trim(),
  });
}

async function postEvaluationRecord(payload) {
  const result = await postJson("/api/ops/evaluations", payload);
  applyOperationsState(result.state);
}

function renderRagPage() {
  const pipeline = [
    ["上传", state.ragDocuments.length],
    ["解析", state.ragDocuments.filter((doc) => String(doc.status || "").includes("parsed")).length],
    ["分片", state.ragDocuments.reduce((sum, doc) => sum + Number(doc.chunk_count || 0), 0)],
    ["QA", state.ragQaPairs.length],
    ["实体", "未启用"],
    ["检索", "未启用"],
  ];
  el.ragPipeline.innerHTML = pipeline.map(([label, value], index) => `
    <div class="rag-stage">
      <span>${index + 1}</span>
      <strong>${escapeHtml(label)}</strong>
      <small>${escapeHtml(String(value))}</small>
    </div>
  `).join("");
  el.ragDocumentList.innerHTML = state.ragDocuments.map((doc) => `
    <div class="ops-card">
      <strong>${escapeHtml(doc.name)}</strong>
      <span>${escapeHtml(formatRagStatus(doc.status))} · ${doc.chunk_count || 0} chunks · RAG 未启用</span>
      ${(doc.chunks || []).slice(0, 2).map((chunk) => `<p>${escapeHtml(chunk.text || "").slice(0, 180)}</p>`).join("")}
    </div>
  `).join("");
  el.ragEntityLinks.innerHTML = state.ragDocuments.length ? state.ragDocuments.map((doc) => `
    <div class="ops-card">
      <strong>${escapeHtml(doc.name)}</strong>
      <span>已记录文档证据和 chunk 引用；实体抽取/实体链接暂未启用。</span>
    </div>
  `).join("") : '<div class="ops-card"><strong>暂无文档证据</strong><span>上传文档后会显示真实 chunk 记录。</span></div>';
  el.ragRetrievalConfig.innerHTML = [
    ["RAG 状态", "未启用：当前只建设和记录文档切片，不接入聊天回答。"],
    ["向量检索", "未启用：尚未生成 embedding 或向量索引。"],
    ["混合检索", "未启用：尚未接入 BM25/vector rerank。"],
    ["答案证据", "已记录 chunk 级证据片段，后续启用 RAG 时可引用。"],
  ].map(([title, detail]) => `
    <div class="ops-card">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(detail)}</span>
    </div>
  `).join("");
}

async function addRagDocumentRecord() {
  const files = [...el.ragDocInput.files];
  if (!files.length) return;
  await uploadRagDocuments(files);
  el.ragDocInput.value = "";
}

async function uploadRagDocuments(files) {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  const result = await postForm("/api/ops/rag/documents", formData);
  applyOperationsState(result.state);
}

async function addRagQaPair(event) {
  event.preventDefault();
  const form = new FormData(el.ragQaForm);
  const result = await postJson("/api/ops/rag/qa", {
    question: String(form.get("question") || "").trim(),
    answer: String(form.get("answer") || "").trim(),
    evidence: String(form.get("evidence") || "").trim(),
  });
  applyOperationsState(result.state);
}

function renderTemplatePage() {
  el.templateLibrary.innerHTML = state.analysisTemplates.map((template) => `
    <div class="template-card">
      <div>
        <strong>${escapeHtml(template.name)}</strong>
        <span>${escapeHtml(template.scenario)}</span>
      </div>
      <ol>
        ${(template.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
      </ol>
      <div class="template-tags">
        ${(template.capabilities || []).map((capability) => `<span>${escapeHtml(formatCapability(capability))}</span>`).join("")}
      </div>
    </div>
  `).join("");
  el.experienceLibrary.innerHTML = state.experienceCases.map((item) => `
    <div class="ops-card">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml((item.factors || []).join(" / "))}</span>
      <p>${escapeHtml(item.outcome)}</p>
    </div>
  `).join("");
}

async function addAnalysisTemplateRecord(event) {
  event.preventDefault();
  const form = new FormData(el.templateForm);
  const capabilities = ["database", "webSearch", "nlSql", "nlLf"].filter((key) => form.get(key));
  await postAnalysisTemplateRecord({
    name: String(form.get("name") || "").trim() || "未命名分析模板",
    scenario: String(form.get("scenario") || "").trim(),
    steps: String(form.get("steps") || "").split(/\n+/).map((item) => item.replace(/^\d+[.、]\s*/, "").trim()).filter(Boolean),
    capabilities,
  });
}

async function postAnalysisTemplateRecord(payload) {
  const result = await postJson("/api/ops/templates", payload);
  applyOperationsState(result.state);
}

function formatDatasetKind(kind) {
  const mapping = {
    single_csv: "单表数据",
    multi_csv: "多表数据",
    excel_workbook: "Excel 工作簿",
    document_context: "文档上下文",
    multi_file: "多类文件",
  };
  return mapping[kind] || "已上传数据";
}

function updateUploadProgress({ phase, progress }, summary) {
  state.uploadProgress = phase === "processing" ? 100 : Math.max(0, Math.min(100, Number(progress) || 0));
  if (phase === "processing") {
    renderComposerFiles(state.selectedFiles, "processing", "解析中", state.uploadProgress);
    showUploadBanner({
      status: "processing",
      title: "上传完成，正在解析文件",
      detail: `${summary.names} · 后端正在读取表、字段和样例`,
      progress: 100,
    });
    el.uploadStatus.textContent = "上传完成，正在解析文件...";
    el.composerHint.textContent = "文件已传到后端，正在解析数据上下文。";
    return;
  }
  renderComposerFiles(state.selectedFiles, "uploading", "", state.uploadProgress);
  showUploadBanner({
    status: "uploading",
    title: "正在上传文件",
    detail: `${summary.names} · ${summary.sizeText}`,
    progress,
  });
  el.uploadStatus.textContent = `正在上传文件 ${progress}%`;
  el.composerHint.textContent = `上传中 ${progress}% · ${summary.names}`;
}

function showUploadBanner({ status, title, detail, progress = 0, autoHideMs = 0 }) {
  window.clearTimeout(state.uploadBannerTimer);
  state.uploadBannerTimer = 0;
  el.uploadBanner.className = `upload-banner ${status || "uploading"}`;
  el.uploadBannerTitle.textContent = title;
  el.uploadBannerDetail.textContent = detail;
  const safeProgress = Math.max(0, Math.min(100, Number(progress) || 0));
  el.uploadBannerProgress.textContent = status === "processing" ? "处理中" : `${safeProgress}%`;
  el.uploadBannerBarFill.style.width = status === "processing" ? "" : `${safeProgress}%`;
  if (autoHideMs) {
    state.uploadBannerTimer = window.setTimeout(hideUploadBanner, autoHideMs);
  }
}

function hideUploadBanner() {
  window.clearTimeout(state.uploadBannerTimer);
  state.uploadBannerTimer = 0;
  el.uploadBanner.classList.add("hidden");
}

function formatFileUploadSummary(files) {
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  const names = files.length === 1
    ? files[0].name
    : `${files[0].name} 等 ${files.length} 个文件`;
  return {
    names,
    sizeText: formatBytes(totalBytes),
  };
}

function renderComposerFiles(files, status = "ready", message = "", progress = status === "ready" ? 100 : state.uploadProgress) {
  if (!files.length) {
    clearComposerFiles();
    return;
  }
  el.composerFileList.classList.remove("hidden");
  el.composerFrame.classList.add("has-files");
  el.composerFileList.innerHTML = files.map((file) => renderComposerFileCard({
    name: file.name,
    size: file.size,
    status,
    message,
    progress,
  })).join("");
}

function renderComposerFileCard(file) {
  const typeLabel = fileTypeLabel(file.name);
  const kind = fileKind(file.name);
  const statusText = file.status === "uploading"
    ? `上传中 ${Math.round(Number(file.progress) || 0)}%`
    : file.status === "processing"
      ? "解析中"
    : file.status === "error"
      ? (file.message || "上传失败")
      : typeLabel;
  const progress = Math.max(0, Math.min(100, Number(file.progress) || 0));
  const angle = Math.round(progress * 3.6);
  return `
    <div class="composer-file-card ${escapeHtml(file.status || "ready")} file-kind-${escapeHtml(kind)} ${file.status === "error" ? "error" : ""}" style="--upload-progress:${progress}; --upload-angle:${angle}deg;">
      <div class="composer-file-progress" aria-hidden="true">
        <div class="composer-file-icon">${escapeHtml(fileIconText(file.name))}</div>
      </div>
      <div class="composer-file-meta">
        <strong title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</strong>
        <span>${escapeHtml(statusText)}${file.size ? ` · ${escapeHtml(formatBytes(file.size))}` : ""}</span>
      </div>
      <button type="button" data-upload-action="clear" aria-label="移除上传文件">×</button>
    </div>
  `;
}

function clearComposerFiles() {
  el.composerFileList.innerHTML = "";
  el.composerFileList.classList.add("hidden");
  el.composerFrame.classList.remove("has-files");
}

function clearUploadedFileContext() {
  state.selectedFiles = [];
  state.datasetId = "";
  state.profile = null;
  state.contextStatus = "等待选择文件。";
  el.fileInput.value = "";
  el.datasetChip.textContent = "未上传数据";
  el.uploadStatus.textContent = state.contextStatus;
  el.composerHint.textContent = "支持 CSV、Excel、Markdown、TXT、PDF、Word、Pages 等文件。";
  clearComposerFiles();
  renderEmptyProfile();
  updateAskState();
}

function fileTypeLabel(name) {
  const ext = fileExtension(name);
  const mapping = {
    csv: "CSV",
    xlsx: "Excel",
    xls: "Excel",
    md: "Markdown",
    markdown: "Markdown",
    txt: "TXT",
    pdf: "PDF",
    doc: "Word",
    docx: "Word",
    pages: "Pages",
    rtf: "RTF",
  };
  return mapping[ext] || "文件";
}

function fileIconText(name) {
  const ext = fileExtension(name);
  if (["csv", "xlsx", "xls"].includes(ext)) return "▦";
  if (["md", "markdown", "txt"].includes(ext)) return "T";
  if (["doc", "docx", "pages", "rtf"].includes(ext)) return "W";
  if (ext === "pdf") return "P";
  return "F";
}

function fileKind(name) {
  const ext = fileExtension(name);
  if (["csv", "xlsx", "xls"].includes(ext)) return "data";
  if (["md", "markdown", "txt"].includes(ext)) return "document";
  if (["doc", "docx", "pages", "rtf"].includes(ext)) return "document";
  if (ext === "pdf") return "pdf";
  return "default";
}

function fileExtension(name) {
  return String(name || "").split(".").pop().toLowerCase();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** index;
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

function describeUploadedDataset(profile) {
  const tables = profile?.tables || (profile ? [profile] : []);
  const tableCount = tables.length;
  const rowCount = tables.reduce((sum, table) => sum + Number(table.row_count || 0), 0);
  return `已生成数据上下文：${tableCount} 张表，约 ${formatNumber(rowCount)} 行。现在可以提问。`;
}

function parseXhrError(request, contentType) {
  const text = request.responseText || "";
  if (contentType.includes("application/json")) {
    try {
      const payload = JSON.parse(text);
      return payload.detail || payload.message || JSON.stringify(payload);
    } catch {
      return text;
    }
  }
  return text;
}

function renderProfile(profile) {
  const tables = profile.tables || [profile];
  const sidebarHtml = renderProfileHtml(profile, { compact: true });
  const drawerHtml = renderProfileHtml(profile, { compact: false });

  el.tableCount.textContent = String(tables.length);
  el.drawerTableCount.textContent = String(tables.length);
  el.profileList.classList.remove("empty");
  el.drawerProfileList.classList.remove("empty");
  el.profileList.innerHTML = sidebarHtml;
  el.drawerProfileList.innerHTML = drawerHtml;
}

function renderProfileHtml(profile, { compact }) {
  const tables = profile.tables || [profile];
  return tables
    .map((table) => {
      const tableName = table.table_name || profile.table_name || table.original_filename || "table";
      const columns = table.columns || [];
      const shownColumns = columns;
      const hiddenCount = Math.max(0, columns.length - shownColumns.length);
      return `
        <div class="profile-item">
          <strong>${escapeHtml(tableName)}</strong>
          <small>${escapeHtml(table.original_filename || "")} · ${table.row_count || 0} rows · ${table.column_count || columns.length} columns</small>
          <div class="field-list">
            ${shownColumns.map((column) => `<span title="${escapeHtml(column.dtype || "")}">${escapeHtml(column.name)}</span>`).join("")}
            ${hiddenCount ? `<span class="field-more" title="完整字段可在右上角查看表页展开">+${hiddenCount}</span>` : ""}
          </div>
        </div>
      `;
    })
    .join("");
}

function renderEmptyProfile() {
  el.tableCount.textContent = "0";
  el.drawerTableCount.textContent = "0";
  el.profileList.classList.add("empty");
  el.drawerProfileList.classList.add("empty");
  el.profileList.textContent = "上传后这里显示表、字段和样例。";
  el.drawerProfileList.textContent = "上传后显示表结构。";
}

function toggleSidebarSection(toggle) {
  const section = toggle.closest(".sidebar-panel");
  if (!section) return;
  const collapsed = !section.classList.contains("collapsed");
  const sectionName = toggle.dataset.collapseTarget || section.dataset.section || "";
  setSidebarSectionCollapsed(section, toggle, collapsed);
  if (sectionName) {
    state.sidebarPanelCollapsed[sectionName] = collapsed;
    try {
      window.localStorage.setItem(`${SIDEBAR_PANEL_COLLAPSED_PREFIX}:${sectionName}`, String(collapsed));
    } catch {
      // UI preference only; ignore storage failures.
    }
  }
}

function initSidebarPanels() {
  for (const toggle of document.querySelectorAll("[data-collapse-target]")) {
    const section = toggle.closest(".sidebar-panel");
    const sectionName = toggle.dataset.collapseTarget || section?.dataset.section || "";
    if (!section || !sectionName) continue;
    let collapsed = sectionName === "dataset";
    if (sectionName !== "dataset") {
      try {
        const savedValue = window.localStorage.getItem(`${SIDEBAR_PANEL_COLLAPSED_PREFIX}:${sectionName}`);
        collapsed = savedValue === null ? collapsed : savedValue === "true";
      } catch {
        collapsed = false;
      }
    }
    state.sidebarPanelCollapsed[sectionName] = collapsed;
    setSidebarSectionCollapsed(section, toggle, collapsed);
  }
}

function setSidebarSectionCollapsed(section, toggle, collapsed) {
  const bodyId = toggle.getAttribute("aria-controls");
  const body = bodyId ? document.getElementById(bodyId) : section.querySelector(".nav-section-body");
  section.classList.toggle("collapsed", collapsed);
  body?.classList.toggle("hidden", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
}

function appendUserQuestion(question) {
  el.emptyState.classList.add("hidden");
  el.projectHome.classList.add("hidden");
  hideOperationsPage();
  el.conversation.classList.remove("hidden");
  el.questionHistory.insertAdjacentHTML(
    "beforeend",
    `
      <div class="user-turn">
        <div class="user-bubble">${escapeHtml(question)}</div>
      </div>
    `,
  );
  el.questionInput.value = "";
  state.selectedFiles = [];
  clearComposerFiles();
  autoResize();
  updateAskState();
  requestAnimationFrame(scrollConversationToBottom);
}

function renderPending() {
  removePendingTurn();
  state.pendingTurnId = `pending-${Date.now()}`;
  const thinkingLabel = currentThinkingLabel();
  el.questionHistory.insertAdjacentHTML(
    "beforeend",
    `
      <article id="${state.pendingTurnId}" class="assistant-message pending-message">
        <div class="assistant-avatar">V</div>
        <div class="assistant-content">
          <div class="assistant-message-head">
            <strong>分析结果</strong>
            <button class="thinking-chip running" type="button" data-thinking-action="open" data-thinking-id="${escapeHtml(state.thinkingTrace?.id || "")}">
              <span class="thinking-dot"></span>
              <span data-thinking-label>${escapeHtml(thinkingLabel)}</span>
            </button>
          </div>
          <p class="assistant-text" data-thinking-summary>${escapeHtml(currentThinkingDetail())}</p>
        </div>
      </article>
    `,
  );
  el.assistantCard.classList.add("hidden");
  el.answer.textContent = "正在分析数据...";
  el.resultTable.textContent = "等待执行结果。";
  el.resultTable.className = "table-wrap empty";
  el.codeView.textContent = "LLM 正在生成代码。";
  el.attemptList.innerHTML = "<li>等待 LLM 输出。</li>";
  el.errorBox.classList.add("hidden");
  el.runId.textContent = "-";
  el.rowCount.textContent = "0 rows";
  el.attemptCount.textContent = "0 attempts";
  el.intentLabel.textContent = "-";
  requestAnimationFrame(scrollConversationToBottom);
}

function renderResult(result) {
  finishThinkingTrace(result);
  result.thinking_trace = state.thinkingTrace;
  removePendingTurn();
  state.projectId = result.project_id || state.projectId;
  state.conversationId = result.conversation_id || state.conversationId;
  el.assistantCard.classList.add("hidden");
  el.runId.textContent = result.run_id || "-";
  el.intentLabel.textContent = truncate(result.intent || "-", 24);
  el.answer.textContent = result.direct_answer || "没有直接答案。";
  el.codeView.textContent = result.pandas_code || "未生成代码。";
  el.rowCount.textContent = `${(result.rows || []).length} rows`;
  el.attemptCount.textContent = `${(result.attempts || []).length} attempts`;
  renderTable(result.columns || [], result.rows || []);
  renderAttempts(result.attempts || []);

  if (result.execution_error) {
    el.errorBox.textContent = result.execution_error;
    el.errorBox.classList.remove("hidden");
  } else {
    el.errorBox.classList.add("hidden");
  }

  el.uploadStatus.textContent = state.contextStatus;
  el.composerHint.textContent = "可以继续追问，LLM 会基于当前上传的数据继续分析。";
  appendAssistantTurn(result);
  loadConversations(state.projectId);
}

async function loadProjects() {
  try {
    const payload = await getJson("/api/chat/projects");
    state.projects = payload.projects || [];
    await loadVisibleProjectConversations();
    renderProjectList();
    if (!state.projectId) await loadConversations("");
  } catch (error) {
    el.composerHint.textContent = `项目加载失败：${error.message}`;
  }
}

async function loadVisibleProjectConversations() {
  const visibleProjects = getVisibleProjectsForSidebar();
  await Promise.all(visibleProjects.map(async (project) => {
    try {
      const payload = await getJson(`/api/chat/projects/${encodeURIComponent(project.project_id)}/conversations`);
      state.projectConversations[project.project_id] = payload.conversations || [];
    } catch (error) {
      state.projectConversations[project.project_id] = [];
    }
  }));
}

function getVisibleProjectsForSidebar() {
  const visible = state.projectListExpanded ? [...state.projects] : state.projects.slice(0, PROJECT_VISIBLE_LIMIT);
  if (state.projectId && !visible.some((project) => project.project_id === state.projectId)) {
    const selected = state.projects.find((project) => project.project_id === state.projectId);
    if (selected) visible.push(selected);
  }
  return visible;
}

async function selectProject(projectId) {
  const project = state.projects.find((item) => item.project_id === projectId);
  if (!project) return;
  state.projectId = projectId;
  state.conversationId = "";
  state.projectTab = "chats";
  renderProjectList();
  await loadProjectDataset(project);
  await loadConversations(projectId);
  await loadProjectDetail(projectId);
  renderProjectHome();
  clearConversation({ showProjectHome: true });
}

async function loadProjectDataset(project) {
  if (!project.current_dataset_id) {
    state.datasetId = "";
    state.profile = null;
    state.contextStatus = "当前项目还没有上传数据。";
    el.datasetChip.textContent = "未上传数据";
    el.uploadStatus.textContent = state.contextStatus;
    clearComposerFiles();
    renderEmptyProfile();
    updateAskState();
    return;
  }
  await loadDatasetContext(project.current_dataset_id, "project");
}

async function loadDatasetContext(datasetId, scope = "chat") {
  try {
    const payload = await getJson(`/api/chat/sessions/${encodeURIComponent(datasetId)}`);
    state.datasetId = payload.dataset_id;
    state.profile = payload.profile;
    state.contextStatus = scope === "project"
      ? `项目数据已就绪：${payload.original_filename || payload.dataset_id}`
      : `对话数据已就绪：${payload.original_filename || payload.dataset_id}`;
    el.datasetChip.textContent = formatDatasetKind(payload.profile.dataset_kind);
    el.uploadStatus.textContent = state.contextStatus;
    state.selectedFiles = [];
    clearComposerFiles();
    renderProfile(payload.profile);
    updateAskState();
  } catch (error) {
    el.composerHint.textContent = `数据加载失败：${error.message}`;
  }
}

async function loadConversations(projectId) {
  try {
    const url = projectId
      ? `/api/chat/projects/${encodeURIComponent(projectId)}/conversations`
      : "/api/chat/conversations";
    const payload = await getJson(url);
    state.conversations = payload.conversations || [];
    if (projectId) state.projectConversations[projectId] = payload.conversations || [];
    renderConversationList();
    renderProjectList();
  } catch (error) {
    el.composerHint.textContent = `历史对话加载失败：${error.message}`;
  }
}

async function loadProjectDetail(projectId) {
  if (!projectId) return;
  try {
    const payload = await getJson(`/api/chat/projects/${encodeURIComponent(projectId)}`);
    state.projectDetail = payload.project || null;
    state.conversations = payload.conversations || state.conversations;
    state.projectConversations[projectId] = payload.conversations || [];
    renderProjectHome();
    renderConversationList();
    renderProjectList();
  } catch (error) {
    el.composerHint.textContent = `项目详情加载失败：${error.message}`;
  }
}

function openSearchModal() {
  el.searchModal.classList.remove("hidden");
  el.searchModalBackdrop.classList.remove("hidden");
  el.searchInput.value = "";
  renderSearchResults([]);
  el.searchStatus.textContent = "最近项目和聊天";
  void runSearch("");
  window.setTimeout(() => el.searchInput.focus(), 0);
}

function closeSearchModal() {
  window.clearTimeout(state.searchTimer);
  el.searchModal.classList.add("hidden");
  el.searchModalBackdrop.classList.add("hidden");
}

function scheduleSearch(query) {
  window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(() => runSearch(query), 160);
}

async function runSearch(query) {
  const requestId = ++state.searchRequestId;
  const trimmed = query.trim();
  el.searchStatus.textContent = trimmed ? "搜索中..." : "最近项目和聊天";
  try {
    const payload = await getJson(`/api/chat/search?q=${encodeURIComponent(trimmed)}&limit=60`);
    if (requestId !== state.searchRequestId) return;
    state.searchResults = payload.results || [];
    renderSearchResults(state.searchResults, trimmed);
  } catch (error) {
    if (requestId !== state.searchRequestId) return;
    el.searchStatus.textContent = `搜索失败：${error.message}`;
    el.searchResults.innerHTML = "";
  }
}

function renderSearchResults(results, query = "") {
  if (!results.length) {
    el.searchStatus.textContent = query ? "没有找到匹配内容。" : "没有可搜索的项目或聊天。";
    el.searchResults.innerHTML = "";
    return;
  }
  el.searchStatus.textContent = query ? `找到 ${results.length} 条结果` : "最近项目和聊天";
  const groups = groupSearchResults(results);
  el.searchResults.innerHTML = Object.entries(groups)
    .map(([label, items]) => `
      <section class="search-group">
        <h2>${escapeHtml(label)}</h2>
        ${items.map((item) => renderSearchResultItem(item, query)).join("")}
      </section>
    `)
    .join("");
  for (const item of el.searchResults.querySelectorAll("[data-search-index]")) {
    item.addEventListener("click", () => openSearchResult(results[Number(item.dataset.searchIndex)]));
  }
}

function groupSearchResults(results) {
  const groups = {};
  results.forEach((result, index) => {
    const label = result.result_type === "project" ? "项目" : "聊天记录";
    if (!groups[label]) groups[label] = [];
    groups[label].push({ ...result, __index: index });
  });
  return groups;
}

function renderSearchResultItem(result, query) {
  const icon = result.result_type === "project" ? "▣" : "○";
  const meta = [result.subtitle, formatDate(result.updated_at)].filter(Boolean).join(" · ");
  const snippet = result.snippet || (result.result_type === "project" ? "项目" : "暂无消息。");
  return `
    <button class="search-result-item" type="button" data-search-index="${result.__index}">
      <span class="search-result-icon">${icon}</span>
      <span class="search-result-main">
        <strong>${highlightSearchText(result.title || "未命名", query)}</strong>
        <small>${escapeHtml(meta)}</small>
        <span>${highlightSearchText(snippet, query)}</span>
      </span>
    </button>
  `;
}

async function openSearchResult(result) {
  if (!result) return;
  closeSearchModal();
  if (result.result_type === "project" && result.project_id) {
    await selectProject(result.project_id);
    return;
  }
  if (result.conversation_id) {
    await openConversation(result.conversation_id);
  } else if (result.project_id) {
    await selectProject(result.project_id);
  }
}

async function createProject() {
  const name = window.prompt("项目名称", `项目 ${state.projects.length + 1}`);
  if (name === null) return;
  const payload = await postJson("/api/chat/projects", { name: name.trim() || null });
  state.projects.unshift(payload.project);
  renderProjectList();
  await selectProject(payload.project.project_id);
}

async function startUnprojectedConversation() {
  state.projectId = "";
  state.conversationId = "";
  state.projectDetail = null;
  state.datasetId = "";
  state.profile = null;
  state.contextStatus = "等待选择文件。";
  el.datasetChip.textContent = "未上传数据";
  el.uploadStatus.textContent = state.contextStatus;
  renderProjectList();
  await loadConversations("");
  renderEmptyProfile();
  clearConversation();
}

async function createConversation({ projectId = state.projectId } = {}) {
  if (!projectId) {
    await startUnprojectedConversation();
    return;
  }
  const payload = await postJson("/api/chat/conversations", {
    project_id: projectId,
    title: "新对话",
  });
  state.projectId = projectId;
  state.conversationId = payload.conversation.conversation_id;
  state.conversations.unshift(payload.conversation);
  state.projectConversations[projectId] = [payload.conversation, ...(state.projectConversations[projectId] || [])];
  state.projectExpanded[projectId] = true;
  clearConversation();
  renderConversationList();
  renderProjectList();
  renderProjectHome();
}

async function openConversation(conversationId) {
  const payload = await getJson(`/api/chat/conversations/${encodeURIComponent(conversationId)}`);
  state.conversationId = payload.conversation_id;
  el.projectHome.classList.add("hidden");
  if (payload.project_id && payload.project_id !== state.projectId) {
    state.projectId = payload.project_id;
    renderProjectList();
  } else if (!payload.project_id) {
    state.projectId = "";
    state.projectDetail = null;
    renderProjectList();
  }
  if (payload.dataset_id && payload.dataset_available !== false) {
    state.datasetId = payload.dataset_id;
    await loadDatasetContext(payload.dataset_id, payload.project_id ? "project" : "chat");
  } else if (payload.dataset_id && payload.dataset_available === false) {
    state.datasetId = "";
    state.profile = null;
    state.contextStatus = "这条历史对话的数据文件已不可用，请重新上传。";
    el.datasetChip.textContent = "未上传数据";
    el.uploadStatus.textContent = state.contextStatus;
    renderEmptyProfile();
  } else {
    state.datasetId = "";
    state.profile = null;
    state.contextStatus = payload.project_id ? "当前项目还没有上传数据。" : "等待选择文件。";
    el.datasetChip.textContent = "未上传数据";
    el.uploadStatus.textContent = state.contextStatus;
    renderEmptyProfile();
  }
  clearConversation();
  const turns = payload.turns || [];
  if (turns.length) {
    el.emptyState.classList.add("hidden");
    el.conversation.classList.remove("hidden");
    for (const turn of turns) {
      appendUserQuestionForHistory(turn.question || "");
      appendAssistantTurn(turn);
    }
    requestAnimationFrame(scrollConversationToBottom);
  }
  renderConversationList();
  updateAskState();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error((await readErrorMessage(response)) || `HTTP ${response.status}`);
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error((await readErrorMessage(response)) || `HTTP ${response.status}`);
  return response.json();
}

async function patchJson(url, payload) {
  const response = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error((await readErrorMessage(response)) || `HTTP ${response.status}`);
  return response.json();
}

async function deleteJson(url) {
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) throw new Error((await readErrorMessage(response)) || `HTTP ${response.status}`);
  return response.json();
}

function renderProjectList() {
  const visibleProjects = getVisibleProjectsForSidebar();
  const items = visibleProjects
    .map((project) => renderSidebarProject(project))
    .join("");
  const hasMoreProjects = !state.projectListExpanded && state.projects.length > visibleProjects.length;
  el.projectList.innerHTML = `
    <button id="new-project-button" class="nav-item new-item" type="button">新项目</button>
    ${items}
    ${hasMoreProjects ? '<button class="nav-show-more" type="button" data-project-list-more>查看更多</button>' : ""}
  `;
  el.projectList.querySelector("#new-project-button").addEventListener("click", createProject);
  for (const row of el.projectList.querySelectorAll("[data-project-id]")) {
    row.querySelector(".project-open").addEventListener("click", () => selectProject(row.dataset.projectId));
    row.querySelector(".row-menu").addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectMenu(row.dataset.projectId, event.currentTarget);
    });
  }
  for (const button of el.projectList.querySelectorAll("[data-project-toggle]")) {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const projectId = button.dataset.projectToggle;
      state.projectExpanded[projectId] = !isProjectExpanded(projectId);
      if (state.projectExpanded[projectId]) await loadProjectConversations(projectId);
      renderProjectList();
    });
  }
  for (const row of el.projectList.querySelectorAll("[data-project-conversation-id]")) {
    row.querySelector(".project-child-open").addEventListener("click", () => openConversation(row.dataset.projectConversationId));
    row.querySelector(".row-menu").addEventListener("click", (event) => {
      event.stopPropagation();
      openConversationMenu(row.dataset.projectConversationId, event.currentTarget);
    });
  }
  for (const button of el.projectList.querySelectorAll("[data-project-chat-more]")) {
    button.addEventListener("click", () => {
      state.projectChatExpanded[button.dataset.projectChatMore] = true;
      renderProjectList();
    });
  }
  const projectMore = el.projectList.querySelector("[data-project-list-more]");
  if (projectMore) {
    projectMore.addEventListener("click", async () => {
      state.projectListExpanded = true;
      await loadVisibleProjectConversations();
      renderProjectList();
    });
  }
}

function renderSidebarProject(project) {
  const projectId = String(project.project_id || "");
  const conversations = state.projectConversations[projectId] || [];
  const expanded = isProjectExpanded(projectId);
  const chatLimit = state.projectChatExpanded[projectId] ? conversations.length : PROJECT_CHAT_VISIBLE_LIMIT;
  const visibleConversations = conversations.slice(0, chatLimit);
  const moreCount = Math.max(0, conversations.length - visibleConversations.length);
  return `
    <div class="project-block ${project.project_id === state.projectId ? "active" : ""} ${expanded ? "expanded" : "collapsed"}">
      <div class="nav-row ${project.project_id === state.projectId ? "active" : ""} ${project.pinned ? "pinned" : ""}" data-project-id="${escapeHtml(projectId)}">
        <button class="project-toggle" type="button" data-project-toggle="${escapeHtml(projectId)}" aria-label="${expanded ? "折叠项目" : "展开项目"}" aria-expanded="${expanded}">
          <span aria-hidden="true"></span>
        </button>
        <button class="nav-item project-open" type="button">
          <span class="project-folder" aria-hidden="true"></span>
          <span>${escapeHtml(project.name || "未命名项目")}</span>
        </button>
        <button class="row-menu" type="button" title="项目选项" aria-label="项目选项">•••</button>
      </div>
      <div class="project-child-list ${expanded ? "" : "hidden"}">
        ${visibleConversations.map((conversation) => renderSidebarProjectConversation(conversation)).join("")}
        ${moreCount ? `<button class="nav-show-more project-chat-more" type="button" data-project-chat-more="${escapeHtml(projectId)}">显示更多</button>` : ""}
      </div>
    </div>
  `;
}

function isProjectExpanded(projectId) {
  return state.projectExpanded[projectId] !== false;
}

async function loadProjectConversations(projectId) {
  if (!projectId) return;
  try {
    const payload = await getJson(`/api/chat/projects/${encodeURIComponent(projectId)}/conversations`);
    state.projectConversations[projectId] = payload.conversations || [];
  } catch (error) {
    state.projectConversations[projectId] = [];
  }
}

function renderSidebarProjectConversation(conversation) {
  return `
    <div class="project-child-row ${conversation.conversation_id === state.conversationId ? "active" : ""} ${conversation.pinned ? "pinned" : ""}" data-project-conversation-id="${escapeHtml(conversation.conversation_id)}">
      <button class="nav-item project-child-open" type="button">
        <span>${escapeHtml(conversation.title || "新对话")}</span>
      </button>
      <button class="row-menu" type="button" title="对话选项" aria-label="对话选项">•••</button>
    </div>
  `;
}

function sortPinnedItems(a, b) {
  const pinnedDelta = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
  if (pinnedDelta) return pinnedDelta;
  const bTime = String(b.pinned_at || b.updated_at || "");
  const aTime = String(a.pinned_at || a.updated_at || "");
  return bTime.localeCompare(aTime);
}

function renderConversationList() {
  if (!state.conversations.length) {
    el.conversationList.innerHTML = '<div class="nav-empty">暂无历史对话</div>';
    return;
  }
  el.conversationList.innerHTML = state.conversations
    .map((conversation) => `
      <div class="nav-row ${conversation.conversation_id === state.conversationId ? "active" : ""} ${conversation.pinned ? "pinned" : ""}" data-conversation-id="${escapeHtml(conversation.conversation_id)}">
        <button class="nav-item conversation-open" type="button">
          ${conversation.pinned ? '<span class="pin-dot">◆</span>' : ""}
          <span>${escapeHtml(conversation.title || "新对话")}</span>
        </button>
        <button class="row-menu" type="button" title="对话选项" aria-label="对话选项">•••</button>
      </div>
    `)
    .join("");
  for (const row of el.conversationList.querySelectorAll("[data-conversation-id]")) {
    row.querySelector(".conversation-open").addEventListener("click", () => openConversation(row.dataset.conversationId));
    row.querySelector(".row-menu").addEventListener("click", (event) => {
      event.stopPropagation();
      openConversationMenu(row.dataset.conversationId, event.currentTarget);
    });
  }
}

function renderProjectHome() {
  const project = state.projectDetail || state.projects.find((item) => item.project_id === state.projectId) || null;
  if (state.operationsPage) {
    el.projectHome.classList.add("hidden");
    return;
  }
  hideOperationsPage();
  if (!project || state.conversationId) {
    el.projectHome.classList.add("hidden");
    return;
  }
  el.projectHome.classList.remove("hidden");
  el.emptyState.classList.add("hidden");
  el.projectHomeTitle.textContent = project.name || "未命名项目";
  setProjectTab(state.projectTab, { renderOnly: true });
  renderProjectConversationList();
  renderProjectSourceList();
}

function setProjectTab(tab, { renderOnly = false } = {}) {
  state.projectTab = tab === "sources" ? "sources" : "chats";
  const showSources = state.projectTab === "sources";
  el.projectTabChats.classList.toggle("active", !showSources);
  el.projectTabSources.classList.toggle("active", showSources);
  el.projectTabChats.setAttribute("aria-selected", String(!showSources));
  el.projectTabSources.setAttribute("aria-selected", String(showSources));
  el.projectChatsPanel.classList.toggle("hidden", showSources);
  el.projectSourcesPanel.classList.toggle("hidden", !showSources);
  if (!renderOnly) renderProjectHome();
}

function renderProjectConversationList() {
  if (!state.conversations.length) {
    el.projectConversationList.innerHTML = '<div class="project-empty">这个项目还没有对话。</div>';
    return;
  }
  el.projectConversationList.innerHTML = state.conversations
    .map((conversation) => `
      <article class="project-card ${conversation.pinned ? "pinned" : ""}" data-conversation-id="${escapeHtml(conversation.conversation_id)}">
        <button class="project-card-main" type="button">
          <strong>${conversation.pinned ? "◆ " : ""}${escapeHtml(conversation.title || "新对话")}</strong>
          <span>${escapeHtml(formatDate(conversation.updated_at))} · ${(conversation.turns || []).length} 轮</span>
        </button>
        <button class="row-menu" type="button" title="对话选项" aria-label="对话选项">•••</button>
      </article>
    `)
    .join("");
  for (const card of el.projectConversationList.querySelectorAll("[data-conversation-id]")) {
    card.querySelector(".project-card-main").addEventListener("click", () => openConversation(card.dataset.conversationId));
    card.querySelector(".row-menu").addEventListener("click", (event) => {
      event.stopPropagation();
      openConversationMenu(card.dataset.conversationId, event.currentTarget);
    });
  }
}

function renderProjectSourceList() {
  const sources = state.projectDetail?.sources || [];
  if (!sources.length) {
    el.projectSourceList.innerHTML = '<div class="project-empty">上传共享文件后会显示在这里。</div>';
    return;
  }
  el.projectSourceList.innerHTML = sources
    .map((source) => {
      const tables = source.metadata?.tables || [];
      return `
        <article class="project-card source-card">
          <div class="source-icon">${sourceIcon(source.title || "")}</div>
          <div class="project-card-main passive">
            <strong>${escapeHtml(source.title || "上传的数据源")}</strong>
            <span>${escapeHtml(formatDatasetKind(source.metadata?.dataset_kind || ""))} · ${tables.length || source.metadata?.table_count || 0} 张表 · ${escapeHtml(formatDate(source.created_at))}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

async function handleProjectSourceSelection() {
  const files = [...el.projectSourceInput.files];
  if (!files.length) return;
  await uploadFiles(files);
  await loadProjectDetail(state.projectId);
  setProjectTab("sources");
  el.projectSourceInput.value = "";
}

function openProjectMenu(projectId, anchor) {
  const project = state.projects.find((item) => item.project_id === projectId) || {};
  showContextMenu(anchor, [
    { label: project.pinned ? "取消置顶" : "置顶项目", action: () => toggleProjectPinned(projectId, !project.pinned) },
    { label: "重命名项目", action: () => renameProject(projectId) },
    { label: "删除项目", danger: true, action: () => deleteProject(projectId) },
  ]);
}

function openConversationMenu(conversationId, anchor) {
  const conversation = findConversationById(conversationId) || {};
  const moveItems = state.projects
    .filter((project) => project.project_id && project.project_id !== conversation.project_id)
    .slice(0, 8)
    .map((project) => ({
      label: `移至：${project.name || "未命名项目"}`,
      action: () => moveConversationToProject(conversationId, project.project_id),
    }));
  showContextMenu(anchor, [
    { label: conversation.pinned ? "取消置顶" : "置顶聊天", action: () => toggleConversationPinned(conversationId, !conversation.pinned) },
    { label: "重命名", action: () => renameConversation(conversationId) },
    ...moveItems,
    { label: "删除", danger: true, action: () => deleteConversation(conversationId) },
  ]);
}

function findConversationById(conversationId) {
  const fromOrdinaryChats = state.conversations.find((item) => item.conversation_id === conversationId);
  if (fromOrdinaryChats) return fromOrdinaryChats;
  for (const conversations of Object.values(state.projectConversations)) {
    const match = conversations.find((item) => item.conversation_id === conversationId);
    if (match) return match;
  }
  return null;
}

function showContextMenu(anchor, items) {
  const rect = anchor.getBoundingClientRect();
  el.contextMenu.innerHTML = items
    .map((item, index) => `<button class="${item.danger ? "danger" : ""}" type="button" data-menu-index="${index}">${escapeHtml(item.label)}</button>`)
    .join("");
  el.contextMenu.style.left = `${Math.min(rect.left, window.innerWidth - 190)}px`;
  el.contextMenu.style.top = `${rect.bottom + 6}px`;
  el.contextMenu.classList.remove("hidden");
  for (const button of el.contextMenu.querySelectorAll("[data-menu-index]")) {
    button.addEventListener("click", async () => {
      const item = items[Number(button.dataset.menuIndex)];
      closeContextMenu();
      await item.action();
    });
  }
}

function closeContextMenu() {
  el.contextMenu.classList.add("hidden");
  el.contextMenu.innerHTML = "";
}

async function renameProject(projectId) {
  const project = state.projects.find((item) => item.project_id === projectId);
  const name = window.prompt("项目名称", project?.name || "未命名项目");
  if (name === null || !name.trim()) return;
  const payload = await patchJson(`/api/chat/projects/${encodeURIComponent(projectId)}`, { name: name.trim() });
  state.projects = state.projects.map((item) => item.project_id === projectId ? payload.project : item);
  state.projects.sort(sortPinnedItems);
  state.projectDetail = payload.project;
  renderProjectList();
  renderProjectHome();
}

async function toggleProjectPinned(projectId, pinned) {
  const payload = await patchJson(`/api/chat/projects/${encodeURIComponent(projectId)}`, { pinned });
  state.projects = state.projects.map((item) => item.project_id === projectId ? payload.project : item);
  state.projects.sort(sortPinnedItems);
  if (state.projectId === projectId) state.projectDetail = payload.project;
  renderProjectList();
  renderProjectHome();
}

async function deleteProject(projectId) {
  if (!window.confirm("删除这个项目及其对话？")) return;
  await deleteJson(`/api/chat/projects/${encodeURIComponent(projectId)}`);
  state.projects = state.projects.filter((item) => item.project_id !== projectId);
  if (state.projectId === projectId) {
    state.projectId = "";
    state.conversationId = "";
    state.projectDetail = null;
    clearConversation();
    await loadProjects();
  } else {
    renderProjectList();
  }
}

async function renameConversation(conversationId) {
  const conversation = findConversationById(conversationId);
  const title = window.prompt("对话名称", conversation?.title || "新对话");
  if (title === null || !title.trim()) return;
  await patchJson(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, { title: title.trim() });
  await loadConversations(state.projectId);
  await loadProjectDetail(state.projectId);
  await loadVisibleProjectConversations();
  renderProjectList();
}

async function toggleConversationPinned(conversationId, pinned) {
  await patchJson(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, { pinned });
  await loadConversations(state.projectId);
  await loadProjectDetail(state.projectId);
  await loadVisibleProjectConversations();
  renderProjectList();
}

async function moveConversationToProject(conversationId, projectId) {
  const payload = await patchJson(`/api/chat/conversations/${encodeURIComponent(conversationId)}`, { project_id: projectId });
  state.projectId = projectId;
  state.projectDetail = null;
  state.conversationId = payload.conversation?.conversation_id || conversationId;
  renderProjectList();
  await loadConversations(projectId);
  await loadProjectDetail(projectId);
  await openConversation(state.conversationId);
}

async function deleteConversation(conversationId) {
  if (!window.confirm("删除这条对话？")) return;
  await deleteJson(`/api/chat/conversations/${encodeURIComponent(conversationId)}`);
  if (state.conversationId === conversationId) {
    state.conversationId = "";
    clearConversation({ showProjectHome: true });
  }
  await loadConversations(state.projectId);
  await loadProjectDetail(state.projectId);
  await loadVisibleProjectConversations();
  renderProjectList();
}

function clearConversation(options = {}) {
  return clearConversationState(options);
}

function clearConversationState({ showProjectHome = false } = {}) {
  removePendingTurn();
  el.questionHistory.innerHTML = "";
  hideOperationsPage();
  el.emptyState.classList.toggle("hidden", showProjectHome);
  el.conversation.classList.add("hidden");
  el.projectHome.classList.toggle("hidden", !showProjectHome);
  el.errorBox.classList.add("hidden");
  el.questionInput.value = "";
  state.selectedFiles = [];
  clearComposerFiles();
  autoResize();
  updateAskState();
  updateScrollBottomButton();
}

function appendUserQuestionForHistory(question) {
  if (!question) return;
  el.emptyState.classList.add("hidden");
  hideOperationsPage();
  el.conversation.classList.remove("hidden");
  el.questionHistory.insertAdjacentHTML(
    "beforeend",
    `
      <div class="user-turn">
        <div class="user-bubble">${escapeHtml(question)}</div>
      </div>
    `,
  );
  bindChartInteractions(el.questionHistory.lastElementChild);
  requestAnimationFrame(updateScrollBottomButton);
}

function appendAssistantTurn(result) {
  const rows = result.rows || [];
  const columns = result.columns || [];
  const attempts = result.attempts || [];
  const trace = ensureThinkingTraceForResult(result);
  const table = rows.length ? renderInlineTable(columns, rows.slice(0, 12)) : '<div class="history-empty">没有结果表。</div>';
  const chart = renderChart(result.chart, rows, columns);
  const sections = renderResponseSections(result.response_sections, result.direct_answer);
  const error = result.execution_error ? `<div class="history-error">${escapeHtml(result.execution_error)}</div>` : "";
  const attemptsHtml = attempts.length
    ? `<ol class="attempt-list compact">${attempts.map((attempt) => {
        const cls = attempt.ok ? "attempt-ok" : "attempt-fail";
        const status = attempt.ok ? "成功" : `失败：${attempt.error || ""}`;
        return `<li class="${cls}">第 ${attempt.attempt} 次：${escapeHtml(status)}</li>`;
      }).join("")}</ol>`
    : '<div class="history-empty">暂无执行记录。</div>';
  const semantic = result.semantic_interpretation
    ? `<pre>${escapeHtml(JSON.stringify(result.semantic_interpretation, null, 2))}</pre>`
    : '<div class="history-empty">暂无语义理解。</div>';
  const code = result.pandas_code
    ? `<pre>${escapeHtml(result.pandas_code)}</pre>`
    : '<div class="history-empty">暂无代码。</div>';
  el.questionHistory.insertAdjacentHTML(
    "beforeend",
    `
      <article class="assistant-message">
        <div class="assistant-avatar">V</div>
        <div class="assistant-content">
          <div class="assistant-message-head">
            <strong>分析结果</strong>
            <span>${result.execution_error ? "失败" : "已完成"} ${escapeHtml(result.run_id || "")}</span>
            <button class="thinking-chip ${result.execution_error ? "failed" : "completed"}" type="button" data-thinking-action="open" data-thinking-id="${escapeHtml(trace.id)}">
              <span class="thinking-dot"></span>
              <span>${escapeHtml(trace?.status === "failed" ? "查看失败过程" : "查看思考")}</span>
            </button>
          </div>
          <div class="history-answer">${escapeHtml(result.direct_answer || "没有直接答案。")}</div>
          ${error}
          ${sections}
          ${chart}
          ${table}
          <details class="debug-details">
            <summary>执行细节</summary>
            <section>
              <h3>执行记录</h3>
              ${attemptsHtml}
            </section>
            <section>
              <h3>语义理解</h3>
              ${semantic}
            </section>
            <section>
              <h3>LLM 生成的 Pandas</h3>
              ${code}
            </section>
          </details>
        </div>
      </article>
    `,
  );
  requestAnimationFrame(scrollConversationToBottom);
}

function scrollConversationToBottom() {
  el.workspace.scrollTo({ top: el.workspace.scrollHeight, behavior: "smooth" });
  updateScrollBottomButton();
}

function updateScrollBottomButton() {
  const conversationVisible = !el.conversation.classList.contains("hidden");
  const canScroll = el.workspace.scrollHeight - el.workspace.clientHeight > 80;
  const distanceToBottom = el.workspace.scrollHeight - el.workspace.scrollTop - el.workspace.clientHeight;
  el.scrollBottomButton.classList.toggle("hidden", !conversationVisible || !canScroll || distanceToBottom < 120);
}

function renderResponseSections(sections, directAnswer = "") {
  const normalized = sections && typeof sections === "object" ? sections : {};
  const summary = cleanDisplayText(normalized.result_summary || "");
  const blocks = [];
  if (summary && summary !== cleanDisplayText(directAnswer || "")) {
    blocks.push(`
      <section class="response-section result-section">
        <h2>简要结论</h2>
        <p>${escapeHtml(summary)}</p>
      </section>
    `);
  }
  blocks.push(renderSectionBlock("分析", normalized.analysis));
  blocks.push(renderSectionBlock("洞察", normalized.insights));
  blocks.push(renderSectionBlock("下一步建议", normalized.next_steps, true));
  const html = blocks.filter(Boolean).join("");
  return html ? `<div class="response-sections">${html}</div>` : "";
}

function renderSectionBlock(title, value, ordered = false) {
  const items = normalizeSectionItems(value);
  if (!items.length) return "";
  const tag = ordered ? "ol" : "ul";
  return `
    <section class="response-section">
      <h2>${escapeHtml(title)}</h2>
      <${tag}>
        ${items.map((item) => renderSectionItem(item)).join("")}
      </${tag}>
    </section>
  `;
}

function renderSectionItem(item) {
  if (item && typeof item === "object") {
    const title = cleanDisplayText(item.title || item.heading || "");
    const children = Array.isArray(item.children) ? item.children.map(cleanDisplayText).filter(Boolean) : [];
    const body = cleanDisplayText(item.body || item.text || item.summary || (children.length ? "" : JSON.stringify(item)));
    return `
      <li class="${children.length ? "section-group" : ""}">
        ${title ? `<strong>${escapeHtml(title)}</strong>` : ""}
        ${body ? `<span>${escapeHtml(body)}</span>` : ""}
        ${children.length ? `
          <ul class="section-sublist">
            ${children.map((child) => `<li>${escapeHtml(child)}</li>`).join("")}
          </ul>
        ` : ""}
      </li>
    `;
  }
  return `<li><span>${escapeHtml(cleanDisplayText(item))}</span></li>`;
}

function normalizeSectionItems(value) {
  if (Array.isArray(value)) {
    return value.flatMap((item) => normalizeSectionItem(item));
  }
  if (typeof value === "string" && value.trim()) return normalizeSectionText(value);
  return [];
}

function normalizeSectionItem(item) {
  if (typeof item === "string") return normalizeSectionText(item);
  if (item === null || item === undefined || String(item).trim() === "") return [];
  return [item];
}

function normalizeSectionText(value) {
  const prepared = cleanDisplayText(value)
    .replace(/\r\n/g, "\n")
    .replace(/([：:])\s+-\s+/g, "$1\n- ")
    .replace(/\s+-\s+(?=[\u4e00-\u9fa5A-Za-z0-9_])/g, "\n- ")
    .trim();
  if (!prepared) return [];

  const lines = prepared.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const items = [];
  let currentGroup = null;

  for (const line of lines) {
    const bullet = line.match(/^[-•]\s*(.+)$/);
    if (bullet) {
      const child = cleanDisplayText(bullet[1]);
      if (!child) continue;
      if (!currentGroup) {
        currentGroup = { title: "", children: [] };
        items.push(currentGroup);
      }
      currentGroup.children.push(child);
      continue;
    }

    const heading = splitSectionHeading(line);
    if (heading) {
      const children = splitInlineNumberedItems(heading.body);
      if (!heading.body || children.length > 1) {
        currentGroup = { title: heading.title, children };
        items.push(currentGroup);
      } else {
        currentGroup = null;
        items.push({ title: heading.title, body: heading.body });
      }
      continue;
    }

    currentGroup = null;
    items.push(line);
  }

  return items.length ? items : [prepared];
}

function splitSectionHeading(line) {
  const match = line.match(/^(.{2,28}?)[：:]\s*(.*)$/);
  if (!match) return null;
  const title = cleanDisplayText(match[1]);
  const body = cleanDisplayText(match[2]);
  if (!title) return null;
  return { title, body };
}

function splitInlineNumberedItems(text) {
  const body = cleanDisplayText(text);
  if (!body) return [];
  if (!/\b\d+[.、]\s*/.test(body)) return body ? [body] : [];
  return body
    .split(/[；;]\s*(?=\d+[.、]\s*)/)
    .map((part) => cleanDisplayText(part.replace(/^\d+[.、]\s*/, "")))
    .filter(Boolean);
}

function renderChart(chart, rows = [], columns = []) {
  if (!chart || typeof chart !== "object" || !chart.chart_type) return "";
  const title = cleanDisplayText(chart.title || "图表");
  const reason = cleanDisplayText(chart.reason || "");
  const interactive = renderInteractiveChart(chart, rows, columns);
  if (interactive) {
    return `
      <figure class="chart-panel interactive-chart">
        ${interactive}
        ${reason ? `<figcaption>${escapeHtml(reason)}</figcaption>` : ""}
      </figure>
    `;
  }
  if (typeof chart.image_data_uri === "string" && chart.image_data_uri.startsWith("data:image/svg+xml;base64,")) {
    return `
      <figure class="chart-panel">
        <img src="${escapeHtml(chart.image_data_uri)}" alt="${escapeHtml(title)}" loading="lazy">
        ${reason ? `<figcaption>${escapeHtml(reason)}</figcaption>` : ""}
      </figure>
    `;
  }
  if (chart.chart_type === "kpi") {
    const row = Array.isArray(chart.data) && chart.data.length ? chart.data[0] : {};
    const value = row && typeof row === "object" ? Object.values(row).find((item) => typeof item === "number" || /^[+-]?\\d+(\\.\\d+)?$/.test(String(item))) : "";
    return `
      <figure class="chart-panel kpi-panel">
        <div class="kpi-label">${escapeHtml(title)}</div>
        <div class="kpi-number">${escapeHtml(formatValue(value || ""))}</div>
      </figure>
    `;
  }
  return "";
}

function renderInteractiveChart(chart, rows, columns) {
  if (!Array.isArray(rows) || !rows.length) return "";
  const type = String(chart.chart_type || "").toLowerCase();
  const xColumn = resolveChartX(chart, rows, columns);
  const yColumn = resolveChartY(chart, rows, columns, xColumn);
  if (!xColumn || !yColumn) return "";
  if (type === "line") return renderLineSvg(chart, rows, xColumn, yColumn, columns);
  if (type === "bar") return renderBarSvg(chart, rows, xColumn, yColumn, false);
  if (type === "horizontal_bar") return renderBarSvg(chart, rows, xColumn, yColumn, true);
  if (type === "pie" || type === "donut") return renderBarSvg(chart, rows, xColumn, yColumn, true);
  return "";
}

function resolveChartX(chart, rows, columns) {
  const requested = String(chart.x || "");
  if (requested && rows.some((row) => Object.prototype.hasOwnProperty.call(row, requested))) return requested;
  return columns.find((column) => rows.some((row) => !isNumericValue(row[column]))) || columns[0] || "";
}

function resolveChartY(chart, rows, columns, xColumn) {
  const requested = String(chart.y || "");
  if (requested && rows.some((row) => Number.isFinite(Number(row[requested])))) return requested;
  return columns.find((column) => column !== xColumn && rows.some((row) => Number.isFinite(Number(row[column])))) || "";
}

function renderBarSvg(chart, rows, xColumn, yColumn, horizontal) {
  const data = rows
    .map((row) => ({ label: String(row[xColumn] ?? ""), value: Number(row[yColumn]) }))
    .filter((item) => item.label && Number.isFinite(item.value))
    .sort((a, b) => horizontal ? b.value - a.value : 0)
    .slice(0, horizontal ? 16 : 14);
  if (!data.length) return "";
  const width = 760;
  const left = horizontal ? 170 : 78;
  const right = 42;
  const top = 48;
  const bottom = 72;
  const rowHeight = horizontal ? 32 : 0;
  const height = horizontal ? Math.max(330, top + bottom + data.length * rowHeight) : 380;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const domain = numberDomain(data.map((item) => item.value));
  const ticks = chartTicks(domain.min, domain.max, 5);
  const colors = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b"];
  const grid = ticks.map((tick) => {
    if (horizontal) {
      const x = scaleValue(tick, domain.min, domain.max, left, left + plotWidth);
      return `<line x1="${x}" y1="${top - 6}" x2="${x}" y2="${top + plotHeight}" class="grid-line"></line><text x="${x}" y="${top + plotHeight + 22}" text-anchor="middle" class="axis-label">${formatNumber(tick)}</text>`;
    }
    const y = scaleValue(tick, domain.min, domain.max, top + plotHeight, top);
    return `<line x1="${left}" y1="${y}" x2="${left + plotWidth}" y2="${y}" class="grid-line"></line><text x="${left - 10}" y="${y + 4}" text-anchor="end" class="axis-label">${formatNumber(tick)}</text>`;
  }).join("");
  const zero = horizontal
    ? scaleValue(0, domain.min, domain.max, left, left + plotWidth)
    : scaleValue(0, domain.min, domain.max, top + plotHeight, top);
  const marks = data.map((item, index) => {
    const color = colors[index % colors.length];
    if (horizontal) {
      const y = top + index * rowHeight + 6;
      const xValue = scaleValue(item.value, domain.min, domain.max, left, left + plotWidth);
      const x = Math.min(zero, xValue);
      const w = Math.max(2, Math.abs(xValue - zero));
      return `
        <g class="chart-hit" tabindex="0">
          <text x="${left - 12}" y="${y + 15}" text-anchor="end" class="axis-label">${escapeHtml(truncate(item.label, 22))}</text>
          <rect x="${x}" y="${y}" width="${w}" height="20" rx="5" fill="${color}"></rect>
          ${chartTooltip(`${xColumn}: ${item.label}`, [`${yColumn}: ${formatNumber(item.value)}`], x + w + 8, y - 24, width)}
        </g>
      `;
    }
    const gap = 10;
    const barWidth = Math.max(16, (plotWidth - gap * (data.length - 1)) / data.length);
    const x = left + index * (barWidth + gap);
    const valueY = scaleValue(item.value, domain.min, domain.max, top + plotHeight, top);
    const y = Math.min(zero, valueY);
    const h = Math.max(2, Math.abs(zero - valueY));
    return `
      <g class="chart-hit" tabindex="0">
        <rect x="${x}" y="${y}" width="${barWidth}" height="${h}" rx="5" fill="${color}"></rect>
        <text x="${x + barWidth / 2}" y="${top + plotHeight + 24}" text-anchor="middle" class="axis-label">${escapeHtml(truncate(item.label, 9))}</text>
        ${chartTooltip(`${xColumn}: ${item.label}`, [`${yColumn}: ${formatNumber(item.value)}`], x - 20, y - 64, width)}
      </g>
    `;
  }).join("");
  return `
    <div class="chart-title">${escapeHtml(chart.title || "自动图表")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chart.title || "分析图表")}">
      ${grid}
      <line x1="${horizontal ? zero : left}" y1="${horizontal ? top - 6 : top}" x2="${horizontal ? zero : left}" y2="${horizontal ? top + plotHeight : top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${horizontal ? top + plotHeight : zero}" x2="${left + plotWidth}" y2="${horizontal ? top + plotHeight : zero}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 18}" text-anchor="middle" class="axis-title">${escapeHtml(horizontal ? yColumn : xColumn)}</text>
      <text transform="translate(20 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(horizontal ? xColumn : yColumn)}</text>
      ${marks}
    </svg>
  `;
}

function renderLineSvg(chart, rows, xColumn, yColumn, columns) {
  const seriesColumn = resolveLineSeriesColumn(chart, rows, xColumn, yColumn, columns);
  const tooltipColumns = columns.filter((column) => column !== xColumn && column !== yColumn && column !== seriesColumn).slice(0, 3);
  const groups = new Map();
  for (const row of rows) {
    const key = seriesColumn ? String(row[seriesColumn] ?? "series") : yColumn;
    const value = Number(row[yColumn]);
    const label = String(row[xColumn] ?? "");
    if (!label || !Number.isFinite(value)) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ label, value, row });
  }
  const series = [...groups.entries()].slice(0, 8).map(([name, points]) => ({ name, points: points.slice(0, 40) }));
  const allValues = series.flatMap((item) => item.points.map((point) => point.value));
  if (!series.length || !allValues.length) return "";
  const width = 820;
  const height = 430;
  const left = 84;
  const right = series.length > 1 ? 150 : 42;
  const top = 54;
  const bottom = 78;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const domain = numberDomain(allValues);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const colors = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b", "#22c55e", "#ef4444"];
  const firstPoints = series[0].points;
  const grid = ticks.map((tick) => {
    const y = scaleValue(tick, domain.min, domain.max, top + plotHeight, top);
    return `<line x1="${left}" y1="${y}" x2="${left + plotWidth}" y2="${y}" class="grid-line"></line><text x="${left - 12}" y="${y + 4}" text-anchor="end" class="axis-label">${formatNumber(tick)}</text>`;
  }).join("");
  const xLabels = firstPoints.map((point, index) => {
    const step = Math.max(1, Math.ceil(firstPoints.length / 6));
    if (index % step !== 0 && index !== firstPoints.length - 1) return "";
    const x = left + (index / Math.max(firstPoints.length - 1, 1)) * plotWidth;
    return `<text x="${x}" y="${top + plotHeight + 28}" text-anchor="middle" class="axis-label">${escapeHtml(truncate(point.label, 9))}</text>`;
  }).join("");
  const lines = series.map((item, seriesIndex) => {
    const color = colors[seriesIndex % colors.length];
    const points = item.points.map((point, index) => ({
      ...point,
      x: left + (index / Math.max(item.points.length - 1, 1)) * plotWidth,
      y: scaleValue(point.value, domain.min, domain.max, top + plotHeight, top),
    }));
    return `
      <polyline points="${points.map((point) => `${point.x},${point.y}`).join(" ")}" class="line-path" style="stroke:${color}"></polyline>
      ${points.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="4" class="line-dot" style="stroke:${color}"></circle>`).join("")}
    `;
  }).join("");
  const hits = firstPoints.map((point, index) => {
    const x = left + (index / Math.max(firstPoints.length - 1, 1)) * plotWidth;
    const prevX = index === 0 ? left : left + ((index - 0.5) / Math.max(firstPoints.length - 1, 1)) * plotWidth;
    const nextX = index === firstPoints.length - 1 ? left + plotWidth : left + ((index + 0.5) / Math.max(firstPoints.length - 1, 1)) * plotWidth;
    const lines = series.map((item) => {
      const matched = item.points[index];
      return matched ? `${item.name}: ${formatNumber(matched.value)}` : "";
    }).filter(Boolean);
    if (series.length === 1 && point.row) {
      for (const column of tooltipColumns) {
        const value = point.row[column];
        if (value !== undefined && value !== null && String(value) !== "") {
          lines.push(`${column}: ${formatValue(value)}`);
        }
      }
    }
    return `
      <g class="chart-hit" tabindex="0">
        <rect x="${prevX}" y="${top}" width="${Math.max(12, nextX - prevX)}" height="${plotHeight}" fill="transparent"></rect>
        <line x1="${x}" y1="${top}" x2="${x}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
        ${chartTooltip(`${xColumn}: ${point.label}`, lines, x - 92, top + 10, width)}
      </g>
    `;
  }).join("");
  const legend = series.length > 1 ? series.map((item, index) => {
    const y = top + index * 24;
    const color = colors[index % colors.length];
    return `<g><line x1="${left + plotWidth + 22}" y1="${y}" x2="${left + plotWidth + 38}" y2="${y}" style="stroke:${color};stroke-width:2"></line><text x="${left + plotWidth + 46}" y="${y + 4}" class="axis-label">${escapeHtml(truncate(item.name, 12))}</text></g>`;
  }).join("") : "";
  return `
    <div class="chart-title">${escapeHtml(chart.title || "趋势图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chart.title || "趋势图")}">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 20}" text-anchor="middle" class="axis-title">${escapeHtml(xColumn)}</text>
      <text x="${left}" y="${top - 28}" text-anchor="start" class="axis-title">${escapeHtml(yColumn)}</text>
      ${xLabels}
      ${lines}
      ${hits}
      ${legend}
    </svg>
  `;
}

function resolveLineSeriesColumn(chart, rows, xColumn, yColumn, columns) {
  const explicitCandidates = [
    chart.series_column,
    chart.seriesColumn,
    chart.series_by,
    chart.seriesBy,
    chart.category,
    chart.color,
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  for (const candidate of explicitCandidates) {
    if (candidate !== xColumn && candidate !== yColumn && columns.includes(candidate)) return candidate;
  }

  const candidates = columns.filter((column) => column !== xColumn && column !== yColumn && rows.some((row) => !isNumericValue(row[column])));
  for (const column of candidates) {
    const groups = new Map();
    for (const row of rows) {
      const label = String(row[xColumn] ?? "");
      const value = Number(row[yColumn]);
      const key = String(row[column] ?? "");
      if (!label || !key || !Number.isFinite(value)) continue;
      if (!groups.has(key)) groups.set(key, new Set());
      groups.get(key).add(label);
    }
    const usableGroups = [...groups.values()].filter((labels) => labels.size >= 2);
    if (usableGroups.length >= 2) return column;
  }
  return "";
}

function chartTooltip(title, lines, x, y, width) {
  const safeX = Math.max(8, Math.min(width - 188, x));
  const textLines = [title, ...lines].slice(0, 8);
  const height = 28 + (textLines.length - 1) * 18;
  return `
    <g class="chart-tooltip" transform="translate(${safeX} ${Math.max(8, y)})">
      <rect width="180" height="${height}" rx="8"></rect>
      ${textLines.map((line, index) => `<text x="10" y="${18 + index * 18}" class="${index === 0 ? "tooltip-title" : ""}">${escapeHtml(line)}</text>`).join("")}
    </g>
  `;
}

function numberDomain(values) {
  const finite = values.map(Number).filter(Number.isFinite);
  let min = Math.min(0, ...finite);
  let max = Math.max(0, ...finite);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  return { min: min - pad, max: max + pad };
}

function scaleValue(value, min, max, outMin, outMax) {
  return outMin + ((Number(value) - min) / (max - min || 1)) * (outMax - outMin);
}

function chartTicks(min, max, count) {
  const step = (max - min) / Math.max(1, count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: Math.abs(number) < 10 ? 2 : 0 }).format(number);
}

function formatScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "0%";
  return `${Math.round(number * 100)}%`;
}

function clampScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number));
}

function formatCapability(value) {
  const mapping = {
    database: "数据库查询",
    webSearch: "web search",
    nlSql: "NL-SQL",
    nlLf: "NL-LF",
  };
  return mapping[value] || value;
}

function formatRagStatus(value) {
  const mapping = {
    parsed_not_enabled: "已解析切片，未启用",
  };
  return mapping[value] || value || "未处理";
}

function isNumericValue(value) {
  return value !== null && value !== "" && Number.isFinite(Number(value));
}

function bindChartInteractions(root) {
  if (!root) return;
  const hits = [...root.querySelectorAll(".chart-hit")];
  const clear = (active = null) => {
    hits.forEach((hit) => {
      if (hit !== active) hit.classList.remove("is-active");
    });
  };
  hits.forEach((hit) => {
    hit.addEventListener("pointerenter", () => {
      clear(hit);
      hit.classList.add("is-active");
    });
    hit.addEventListener("click", () => {
      clear(hit);
      hit.classList.add("is-active");
    });
    hit.addEventListener("focus", () => {
      clear(hit);
      hit.classList.add("is-active");
    });
  });
  root.addEventListener("pointerleave", () => clear());
}

function activateChartHit(event) {
  const hit = event.target?.closest?.(".chart-hit");
  if (!hit) return;
  const svg = hit.closest(".chart-svg");
  if (!svg) return;
  svg.querySelectorAll(".chart-hit.is-active").forEach((item) => {
    if (item !== hit) item.classList.remove("is-active");
  });
  hit.classList.add("is-active");
}

function removePendingTurn() {
  if (!state.pendingTurnId) return;
  const pending = document.getElementById(state.pendingTurnId);
  if (pending) pending.remove();
  state.pendingTurnId = "";
}

function renderInlineTable(columns, rows) {
  const safeColumns = columns.length ? columns : Object.keys(rows[0] || {});
  return `
    <div class="history-table">
      <table>
        <thead>
          <tr>${safeColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${rows.map((row) => `
            <tr>${safeColumns.map((column) => `<td>${escapeHtml(formatValue(row[column]))}</td>`).join("")}</tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderTable(columns, rows) {
  if (!rows.length) {
    el.resultTable.textContent = "没有结果表。";
    el.resultTable.className = "table-wrap empty";
    return;
  }

  const safeColumns = columns.length ? columns : Object.keys(rows[0]);
  el.resultTable.className = "table-wrap";
  el.resultTable.innerHTML = `
    <table>
      <thead>
        <tr>${safeColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>${safeColumns.map((column) => `<td>${escapeHtml(formatValue(row[column]))}</td>`).join("")}</tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderAttempts(attempts) {
  if (!attempts.length) {
    el.attemptList.innerHTML = "<li>暂无执行记录。</li>";
    return;
  }

  el.attemptList.innerHTML = attempts
    .map((attempt) => {
      const cls = attempt.ok ? "attempt-ok" : "attempt-fail";
      const status = attempt.ok ? "成功" : `失败：${attempt.error || ""}`;
      return `<li class="${cls}">第 ${attempt.attempt} 次：${escapeHtml(status)}</li>`;
    })
    .join("");
}

function startThinkingTrace(question) {
  window.clearInterval(state.thinkingTimer);
  const now = Date.now();
  const trace = {
    id: `thinking-${now}`,
    question,
    status: "running",
    startedAt: now,
    completedAt: 0,
    runId: "",
    currentIndex: 0,
    phases: THINKING_PHASES.map((phase, index) => ({
      ...phase,
      status: index === 0 ? "running" : "pending",
      startedAt: index === 0 ? now : 0,
      completedAt: 0,
    })),
    attempts: [],
    pandasCode: "",
    directAnswer: "",
    executionError: "",
    rowCount: 0,
  };
  state.thinkingTrace = trace;
  state.thinkingTraces[trace.id] = trace;
  renderThinkingDrawer();
  state.thinkingTimer = window.setInterval(updateThinkingProgress, 700);
}

function updateThinkingProgress() {
  const trace = state.thinkingTrace;
  if (!trace || trace.status !== "running") return;
  const elapsed = Date.now() - trace.startedAt;
  let nextIndex = 0;
  THINKING_PHASES.forEach((phase, index) => {
    if (elapsed >= phase.thresholdMs) nextIndex = index;
  });
  setThinkingPhase(nextIndex);
  renderPendingThinking();
  if (state.thinkingDrawerOpen) renderThinkingDrawer();
}

function setThinkingPhase(index) {
  const trace = state.thinkingTrace;
  if (!trace) return;
  const safeIndex = Math.max(0, Math.min(index, trace.phases.length - 1));
  if (safeIndex === trace.currentIndex) return;
  const now = Date.now();
  trace.phases.forEach((phase, phaseIndex) => {
    if (phaseIndex < safeIndex && phase.status !== "done") {
      phase.status = "done";
      phase.completedAt = phase.completedAt || now;
    } else if (phaseIndex === safeIndex) {
      phase.status = "running";
      phase.startedAt = phase.startedAt || now;
    } else if (phase.status === "running") {
      phase.status = "pending";
    }
  });
  trace.currentIndex = safeIndex;
}

function finishThinkingTrace(result) {
  const trace = state.thinkingTrace || buildThinkingTraceFromResult(result);
  if (!trace) return;
  window.clearInterval(state.thinkingTimer);
  state.thinkingTimer = 0;
  const now = Date.now();
  trace.status = result.execution_error ? "failed" : "completed";
  trace.completedAt = now;
  trace.runId = result.run_id || trace.runId || "";
  trace.attempts = result.attempts || [];
  trace.pandasCode = result.pandas_code || "";
  trace.directAnswer = result.direct_answer || "";
  trace.executionError = result.execution_error || "";
  trace.rowCount = (result.rows || []).length;
  trace.phases.forEach((phase, index) => {
    if (trace.status === "failed" && index >= trace.currentIndex) {
      phase.status = index === trace.currentIndex ? "failed" : "pending";
      return;
    }
    phase.status = "done";
    phase.startedAt = phase.startedAt || trace.startedAt;
    phase.completedAt = phase.completedAt || now;
  });
  trace.currentIndex = trace.status === "failed" ? trace.currentIndex : trace.phases.length - 1;
  state.thinkingTrace = trace;
  state.thinkingTraces[trace.id] = trace;
  renderPendingThinking();
  renderThinkingDrawer();
}

function buildThinkingTraceFromResult(result) {
  const now = Date.now();
  const failed = Boolean(result.execution_error);
  const trace = {
    id: result.run_id ? `thinking-${result.run_id}` : `thinking-result-${now}`,
    question: result.question || "",
    status: failed ? "failed" : "completed",
    startedAt: now,
    completedAt: now,
    runId: result.run_id || "",
    currentIndex: failed ? 2 : THINKING_PHASES.length - 1,
    phases: THINKING_PHASES.map((phase, index) => ({
      ...phase,
      status: failed && index >= 2 ? (index === 2 ? "failed" : "pending") : "done",
      startedAt: now,
      completedAt: failed && index >= 2 ? 0 : now,
    })),
    attempts: result.attempts || [],
    pandasCode: result.pandas_code || "",
    directAnswer: result.direct_answer || "",
    executionError: result.execution_error || "",
    rowCount: (result.rows || []).length,
  };
  return trace;
}

function ensureThinkingTraceForResult(result) {
  const existing = result.thinking_trace;
  if (existing?.id) {
    state.thinkingTraces[existing.id] = existing;
    return existing;
  }
  const trace = buildThinkingTraceFromResult(result);
  state.thinkingTraces[trace.id] = trace;
  return trace;
}

function currentThinkingLabel(trace = state.thinkingTrace) {
  if (!trace) return "正在思考";
  if (trace.status === "completed") return "查看思考";
  if (trace.status === "failed") return "查看失败过程";
  const phase = trace.phases[trace.currentIndex];
  return `正在思考：${phase?.label || "分析中"}`;
}

function currentThinkingDetail(trace = state.thinkingTrace) {
  if (!trace) return "正在准备分析。";
  if (trace.status === "completed") return `已完成分析，返回 ${trace.rowCount} 行结果。`;
  if (trace.status === "failed") return trace.executionError || "分析失败。";
  return trace.phases[trace.currentIndex]?.detail || "正在分析。";
}

function renderPendingThinking() {
  if (!state.pendingTurnId) return;
  const pending = document.getElementById(state.pendingTurnId);
  if (!pending) return;
  const label = pending.querySelector("[data-thinking-label]");
  const summary = pending.querySelector("[data-thinking-summary]");
  if (label) label.textContent = currentThinkingLabel();
  if (summary) summary.textContent = currentThinkingDetail();
}

function openThinkingDrawer(traceId = "") {
  closeDrawer();
  if (traceId && state.thinkingTraces[traceId]) {
    state.thinkingTrace = state.thinkingTraces[traceId];
  }
  state.thinkingDrawerOpen = true;
  el.thinkingDrawer.classList.remove("hidden");
  el.thinkingDrawerBackdrop.classList.remove("hidden");
  renderThinkingDrawer();
}

function closeThinkingDrawer() {
  state.thinkingDrawerOpen = false;
  el.thinkingDrawer.classList.add("hidden");
  el.thinkingDrawerBackdrop.classList.add("hidden");
}

function renderThinkingDrawer() {
  const trace = state.thinkingTrace;
  if (!trace) {
    el.thinkingStatus.textContent = "等待分析。";
    el.thinkingDrawerBody.innerHTML = '<div class="history-empty">提交问题后显示当前分析进度。</div>';
    return;
  }
  el.thinkingStatus.textContent = thinkingStatusText(trace);
  el.thinkingDrawerBody.innerHTML = `
    <div class="thinking-summary-card">
      <span>${escapeHtml(trace.runId || "未生成 run_id")}</span>
      <strong>${escapeHtml(currentThinkingLabel(trace))}</strong>
      <p>${escapeHtml(currentThinkingDetail(trace))}</p>
      ${trace.question ? `<small>${escapeHtml(trace.question)}</small>` : ""}
    </div>
    <ol class="thinking-step-list">
      ${trace.phases.map((phase) => renderThinkingPhase(trace, phase)).join("")}
    </ol>
    ${renderThinkingResult(trace)}
  `;
}

function renderThinkingPhase(trace, phase) {
  return `
    <li class="thinking-step ${escapeHtml(phase.status)}">
      <span class="thinking-step-mark">${thinkingPhaseMark(phase.status)}</span>
      <div>
        <strong>${escapeHtml(phase.label)}</strong>
        <p>${escapeHtml(phase.detail)}</p>
      </div>
    </li>
  `;
}

function renderThinkingResult(trace) {
  if (trace.status === "running") {
    return `<div class="thinking-footnote">已用时 ${escapeHtml(formatElapsed(Date.now() - trace.startedAt))}</div>`;
  }
  const attempts = trace.attempts.length
    ? `<ol class="attempt-list compact">${trace.attempts.map((attempt) => {
        const cls = attempt.ok ? "attempt-ok" : "attempt-fail";
        const status = attempt.ok ? "成功" : `失败：${attempt.error || ""}`;
        return `<li class="${cls}">第 ${attempt.attempt} 次：${escapeHtml(status)}</li>`;
      }).join("")}</ol>`
    : '<div class="history-empty">暂无执行记录。</div>';
  return `
    <section class="thinking-result">
      <h3>结果摘要</h3>
      <p>${escapeHtml(trace.executionError || trace.directAnswer || "没有直接答案。")}</p>
      <div class="thinking-meta-grid">
        <span>耗时 ${escapeHtml(formatElapsed((trace.completedAt || Date.now()) - trace.startedAt))}</span>
        <span>${escapeHtml(String(trace.rowCount))} rows</span>
        <span>${escapeHtml(String(trace.attempts.length))} attempts</span>
      </div>
      <h3>执行记录</h3>
      ${attempts}
      ${trace.pandasCode ? `<h3>LLM 生成的 Pandas</h3><pre>${escapeHtml(trace.pandasCode)}</pre>` : ""}
    </section>
  `;
}

function thinkingPhaseMark(status) {
  if (status === "done") return "✓";
  if (status === "running") return "…";
  if (status === "failed") return "!";
  return "";
}

function thinkingStatusText(trace) {
  if (trace.status === "completed") return "已完成。";
  if (trace.status === "failed") return "分析失败。";
  return currentThinkingLabel(trace);
}

function formatElapsed(ms) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

function toggleDrawer() {
  const shouldOpen = el.profileDrawer.classList.contains("hidden");
  setDrawerOpen(shouldOpen);
}

function closeDrawer() {
  setDrawerOpen(false);
}

function setDrawerOpen(open) {
  if (open) closeThinkingDrawer();
  el.profileDrawer.classList.toggle("hidden", !open);
  el.profileDrawerBackdrop.classList.toggle("hidden", !open);
}

function setBusy(isBusy, { contextMessage = "", hintMessage = "" } = {}) {
  el.askButton.disabled = isBusy || !state.datasetId || !el.questionInput.value.trim();
  if (contextMessage) el.uploadStatus.textContent = contextMessage;
  if (hintMessage) el.composerHint.textContent = hintMessage;
  if (!isBusy && state.datasetId) el.uploadStatus.textContent = state.contextStatus;
}

function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function sourceIcon(name) {
  const ext = fileExtension(name);
  if (["csv", "xlsx", "xls"].includes(ext)) return "▦";
  if (["md", "markdown", "txt"].includes(ext)) return "T";
  if (["doc", "docx", "pages", "rtf"].includes(ext)) return "W";
  if (ext === "pdf") return "P";
  return "◇";
}

function truncate(value, max) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function cleanDisplayText(value) {
  return String(value || "")
    .replace(/^#{1,6}\s*/gm, "")
    .replaceAll("**", "")
    .trim();
}

function highlightSearchText(value, query) {
  const text = String(value || "");
  const trimmed = String(query || "").trim();
  if (!trimmed) return escapeHtml(text);
  const normalizedText = text.casefold ? text.casefold() : text.toLowerCase();
  const normalizedQuery = trimmed.casefold ? trimmed.casefold() : trimmed.toLowerCase();
  const index = normalizedText.indexOf(normalizedQuery);
  if (index < 0) return escapeHtml(text);
  const before = text.slice(0, index);
  const match = text.slice(index, index + trimmed.length);
  const after = text.slice(index + trimmed.length);
  return `${escapeHtml(before)}<mark>${escapeHtml(match)}</mark>${escapeHtml(after)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
