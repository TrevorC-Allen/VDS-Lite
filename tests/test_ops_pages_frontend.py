from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "web" / "index.html"
APP_JS = ROOT / "web" / "app.js"
STYLES_CSS = ROOT / "web" / "styles.css"


def test_operations_pages_are_registered_in_html() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    for element_id in [
        "ops-menu-button",
        "ops-menu",
        "ops-menu-monitor",
        "ops-menu-rag",
        "ops-menu-template",
        "operations-pages",
        "monitor-page",
        "rag-page",
        "template-page",
        "scroll-bottom-button",
    ]:
        assert f'id="{element_id}"' in html

    assert 'id="monitor-page-button"' not in html
    assert 'id="rag-page-button"' not in html
    assert 'id="template-page-button"' not in html
    assert "Exactness" in html
    assert "Faithfulness" in html
    assert "RAG 建设" in html
    assert "分析模板" in html
    assert ".md,.markdown,.txt,.pdf,.doc,.docx,.pages,.rtf" in html


def test_operations_pages_have_frontend_state_and_renderers() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")

    for symbol in [
        "operationsPage",
        "opsMetrics",
        "ragDocuments",
        "analysisTemplates",
        "showOperationsPage",
        "renderMonitorPage",
        "renderRagPage",
        "renderTemplatePage",
        "addEvaluationRecord",
        "addRagDocumentRecord",
        "addAnalysisTemplateRecord",
        "loadOperationsStateFromApi",
        "postEvaluationRecord",
        "uploadRagDocuments",
        "postAnalysisTemplateRecord",
        "renderComposerFiles",
        "clearUploadedFileContext",
        "fileTypeLabel",
        "fileKind",
        "uploadProgress",
        "toggleProjectPinned",
        "sortPinnedItems",
        "scrollConversationToBottom",
        "updateScrollBottomButton",
        "startUnprojectedConversation",
        "moveConversationToProject",
        "loadVisibleProjectConversations",
        "renderSidebarProject",
        "projectListExpanded",
        "projectChatExpanded",
        "/api/chat/conversations",
    ]:
        assert symbol in app_js

    append_user_question = app_js.split("function appendUserQuestion(question)", 1)[1].split("function renderPending()", 1)[0]
    assert "clearComposerFiles();" in append_user_question
    assert "clearUploadedFileContext();" not in append_user_question

    load_project_dataset = app_js.split("async function loadProjectDataset(project)", 1)[1].split("async function loadConversations", 1)[0]
    assert "renderComposerFilesFromProfile" not in app_js
    assert "clearComposerFiles();" in load_project_dataset
    assert "state.datasetId = payload.dataset_id;" in load_project_dataset
    assert "置顶项目" in app_js
    assert "取消置顶" in app_js
    assert "{ pinned }" in app_js
    assert "el.workspace.scrollTo" in app_js
    assert 'el.workspace.addEventListener("scroll", updateScrollBottomButton)' in app_js
    assert "await selectProject(state.projects[0].project_id)" not in app_js
    assert 'el.newChatButton.addEventListener("click", startUnprojectedConversation)' in app_js
    assert "project_id: state.projectId" in app_js
    assert "PROJECT_VISIBLE_LIMIT" in app_js
    assert "PROJECT_CHAT_VISIBLE_LIMIT" in app_js
    assert "data-project-list-more" in app_js
    assert "data-project-chat-more" in app_js


def test_operations_pages_have_dedicated_styles() -> None:
    css = STYLES_CSS.read_text(encoding="utf-8")

    for selector in [
        ".operations-pages",
        ".ops-page",
        ".ops-metric-grid",
        ".ops-record-table",
        ".rag-pipeline",
        ".template-library",
        ".ops-form",
        ".ops-menu",
        ".ops-menu-button",
        ".composer-file-card",
        ".composer-file-icon",
        ".composer-file-progress",
        ".scroll-bottom-button",
        ".project-list-expanded",
        ".project-child-list",
        ".project-child-row",
        ".nav-show-more",
        ".workspace::-webkit-scrollbar",
        "@keyframes fileUploadSpinner",
    ]:
        assert selector in css

    assert "background: var(--green)" in css
    assert ".composer-file-card.uploading .composer-file-icon::after" in css
    assert "border-top-color: rgba(255, 255, 255, 0.28)" in css
    assert "fileUploadHalo" not in css
    assert ".composer-file-card.ready .composer-file-icon::before" not in css
    assert ".composer-file-card.ready .composer-file-icon::after" not in css
    assert "ui-sans-serif, -apple-system, BlinkMacSystemFont" in css
    assert "font-size: 14px;" in css
    assert "font-weight: 500;" in css
    assert "grid-template-columns: 260px minmax(0, 1fr);" in css
    assert "height: 304px;" not in css
    assert "max-height: 226px;" not in css
    assert "min-height: 34px;" in css
    composer_css = css.split(".composer-shell {", 1)[1].split("}", 1)[0]
    assert "position: fixed;" in composer_css
    assert "left: 260px;" in composer_css
    assert "bottom: 18px;" in composer_css
    conversation_css = css.split(".conversation {", 1)[1].split("}", 1)[0]
    assert "overflow: visible;" in conversation_css
    assert "max-height: none;" in conversation_css
