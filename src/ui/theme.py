"""Shared product styling for the Streamlit review workspace."""

APP_CSS = """
<style>
:root {
  --app-navy: #123b4b;
  --app-navy-soft: #1d5264;
  --app-teal: #118b7e;
  --app-bg: #f3f6f7;
  --app-panel: #ffffff;
  --app-border: #dfe7ea;
  --app-text: #173743;
  --app-muted: #70818a;
  --app-success: #147866;
  --app-success-bg: #e9f6f2;
  --app-missing: #b94e42;
  --app-missing-bg: #fff0ee;
}
[data-testid="stAppViewContainer"] { background: var(--app-bg); }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], footer, #MainMenu { visibility: hidden; }
[data-testid="stApp"][data-test-script-state="running"] [data-testid="stAppViewContainer"],
[data-testid="stApp"][data-test-script-state="running"] [data-testid="stAppViewBlockContainer"],
[data-testid="stApp"][data-test-script-state="running"] [data-testid="stVerticalBlock"],
[data-testid="stApp"][data-test-script-state="running"] [data-testid="stElementContainer"],
[data-testid="stApp"][data-test-script-state="running"] .st-key-review_workspace {
  opacity:1 !important; filter:none !important;
}
.block-container {
  max-width:1920px; padding:.55rem 1rem 2rem;
}
.st-key-review_workspace .st-key-document_page_preview {
  overflow-x:hidden; overflow-y:auto; scrollbar-gutter:stable;
  padding:12px; border:1px solid var(--app-border); border-radius:10px;
  background:#dce4e7; box-shadow:inset 0 1px 4px rgba(18,59,75,.08);
}
.st-key-review_workspace .st-key-document_page_preview [data-testid="stImage"] {
  width:100%; margin-bottom:12px; overflow:hidden; background:#fff;
  box-shadow:0 2px 9px rgba(18,59,75,.18);
}
.st-key-review_workspace .st-key-document_page_preview [data-testid="stImage"]:last-child {
  margin-bottom:0;
}
.st-key-review_workspace .st-key-document_page_preview img {
  display:block; width:100% !important; height:auto !important;
}
.st-key-review_workspace .st-key-document_page_preview button {
  display:none !important;
}
.st-key-document_actions_idle,
.st-key-document_actions_active {
  padding:13px;
  border-color:var(--app-border) !important; border-radius:10px !important;
  background:#fff; box-shadow:0 3px 14px rgba(29,61,73,.04);
}
.app-document-actions__eyebrow {
  margin-bottom:8px; color:#819099; font-size:10px; font-weight:800;
  letter-spacing:.08em; text-transform:uppercase;
}
.app-document-actions__title {
  color:var(--app-text); font-size:14px; font-weight:800; line-height:1.3;
}
.app-document-actions__subtitle {
  min-height:36px; margin-top:4px; color:var(--app-muted); font-size:11px; line-height:1.45;
}
.st-key-document_actions_idle [data-testid="stFileUploader"],
.st-key-document_actions_active [data-testid="stFileUploader"] {
  margin-top:12px;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"],
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] {
  min-height:38px; padding:0; border:0; border-radius:8px; background:transparent;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] > div,
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] > div,
.st-key-document_actions_idle [data-testid="stFileUploaderDropzoneInstructions"],
.st-key-document_actions_active [data-testid="stFileUploaderDropzoneInstructions"],
.st-key-document_actions_idle [data-testid="stFileUploaderFile"],
.st-key-document_actions_active [data-testid="stFileUploaderFile"] {
  display:none;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] > span,
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] > span {
  width:100%;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] button,
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] button {
  width:100%; min-height:38px; border:1px solid var(--app-navy); border-radius:8px;
  background:var(--app-navy); color:#fff; font-size:0; font-weight:700;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] button::after {
  content:"Chọn tài liệu"; font-size:14px;
}
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] button::after {
  content:"Đổi tài liệu"; font-size:14px;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] button:hover,
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] button:hover {
  border-color:var(--app-navy-soft); background:var(--app-navy-soft); color:#fff;
}
.st-key-document_actions_idle [data-testid="stBaseButton-primary"],
.st-key-document_actions_active [data-testid="stBaseButton-primary"] {
  width:100%;
  background: var(--app-teal); border-color: var(--app-teal);
  min-height:42px; border-radius: 8px;
  font-size:15px; font-weight:800; line-height:1.2;
}
.st-key-document_actions_idle [data-testid="stBaseButton-primary"]:disabled,
.st-key-document_actions_active [data-testid="stBaseButton-primary"]:disabled {
  color:#fff; opacity:.48;
}
.st-key-document_actions_idle [data-testid="stBaseButton-primary"]:hover,
.st-key-document_actions_active [data-testid="stBaseButton-primary"]:hover {
  background: #0d796e; border-color: #0d796e;
}
.app-appbar {
  display:flex; align-items:center; justify-content:flex-start; gap:10px;
  width:100%; min-height:46px; padding:11px 13px; margin-bottom:12px; color:#fff;
  background:linear-gradient(135deg,var(--app-navy),var(--app-navy-soft));
  border-radius:10px; box-shadow:0 5px 18px rgba(18,59,75,.13);
}
.app-brand { display:flex; align-items:center; gap:10px; }
.app-brand__mark {
  display:grid; place-items:center; width:34px; height:34px; border-radius:9px;
  background:#2ac0a7; color:#0e3b46; font-weight:900;
}
.app-brand__name { font-size:13px; font-weight:800; line-height:1.2; }
.app-brand__subtitle { margin-top:1px; font-size:11px; color:rgba(255,255,255,.67); }
.app-context {
  display:flex; align-items:center; justify-content:space-between;
  gap:14px; min-height:46px; margin-bottom:8px;
}
.app-context__title {
  overflow:hidden; color:var(--app-text); font-size:20px; font-weight:900;
  line-height:1.25; text-overflow:ellipsis; white-space:nowrap;
}
.app-context__chips { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
.app-chip {
  display:inline-flex; align-items:center; min-height:32px; padding:6px 11px;
  border:1px solid var(--app-border); border-radius:7px; background:#fff;
  color:#455f69; font-size:13px; font-weight:800;
}
.app-chip--success {
  border-color:#cce8df; background:var(--app-success-bg);
  color:var(--app-success); font-weight:800;
}
.app-chip--error {
  border-color:#f1d2ce; background:var(--app-missing-bg);
  color:var(--app-missing); font-weight:800;
}
.app-panel-head {
  display:flex; align-items:center; justify-content:space-between; min-height:42px;
  padding:0 12px; border:1px solid var(--app-border); border-bottom:0;
  border-radius:10px 10px 0 0; background:#fff;
}
.app-panel-head__title { color:var(--app-text); font-size:13px; font-weight:800; }
.app-panel-head__meta { color:var(--app-muted); font-size:11px; }
.app-preview-notice {
  margin:0; padding:7px 10px; border-right:1px solid var(--app-border);
  border-left:1px solid var(--app-border); background:#fff9e7;
  color:#856e28; font-size:11px;
}
.app-results {
  overflow:hidden; border:1px solid var(--app-border); border-radius:10px;
  background:var(--app-panel); box-shadow:0 3px 14px rgba(29,61,73,.05);
}
.app-results--error {
  border-color:#f1d2ce; background:#fffafa;
}
.app-results--error .app-results__title {
  color:var(--app-missing);
}
.app-results__head { padding:13px; border-bottom:1px solid var(--app-border); }
.app-results__title-row {
  display:flex; align-items:center; gap:9px;
}
.app-results__title { color:var(--app-text); font-size:15px; font-weight:800; }
.app-results__summary { margin-top:4px; color:var(--app-muted); font-size:13px; }
.app-spinner {
  flex:0 0 auto; width:18px; height:18px; border-radius:999px;
  border:3px solid #d7eee8; border-top-color:var(--app-teal);
  animation:app-spin .8s linear infinite;
}
@keyframes app-spin {
  to { transform:rotate(360deg); }
}
.app-progress {
  height:5px; margin-top:9px; overflow:hidden; border-radius:999px; background:#edf2f3;
}
.app-progress__bar { height:100%; border-radius:999px; background:var(--app-teal); }
.app-progress__bar--indeterminate {
  width:42%; animation:app-progress-sweep 1.35s ease-in-out infinite;
}
@keyframes app-progress-sweep {
  0% { transform:translateX(-120%); }
  100% { transform:translateX(260%); }
}
.app-result-row {
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  min-height:48px; padding:9px 13px; border-bottom:1px solid #edf1f2;
}
.app-result-row:last-child { border-bottom:0; }
.app-result-label { color:#37535e; font-size:14px; line-height:1.38; }
.app-required { color:var(--app-missing); font-weight:900; }
.app-status {
  flex:0 0 auto; min-width:50px; padding:5px 9px; border-radius:999px;
  text-align:center; font-size:12px; font-weight:800;
}
.app-status--ok { background:var(--app-success-bg); color:var(--app-success); }
.app-status--missing { background:var(--app-missing-bg); color:var(--app-missing); }
.app-sidebar-brand { margin-bottom:12px; }
.app-sidebar-brand__title { color:var(--app-text); font-size:14px; font-weight:800; }
.app-sidebar-brand__subtitle { margin-top:2px; color:var(--app-muted); font-size:11px; }
.app-sidebar-label {
  margin:14px 0 6px; color:#819099; font-size:10px; font-weight:800;
  letter-spacing:.08em; text-transform:uppercase;
}
.app-sidebar-summary { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
.app-summary-card {
  padding:8px; border-radius:8px; background:#f3f7f8; color:#71828a; font-size:10px;
}
.app-summary-card strong {
  display:block; margin-bottom:1px; color:var(--app-text); font-size:19px;
}
.app-summary-card--found { background:var(--app-success-bg); }
.app-summary-card--found strong { color:var(--app-success); }
.app-summary-card--missing { background:var(--app-missing-bg); }
.app-summary-card--missing strong { color:var(--app-missing); }
.app-reference-card {
  margin-top:6px; padding:8px; border-radius:8px; background:#f3f7f8;
  color:#71828a; font-size:10px;
}
.app-reference-card strong {
  display:block; margin-top:1px; color:var(--app-text); font-size:13px;
}
.app-empty {
  padding:18px; border:1px dashed #cbd8dd; border-radius:0 0 10px 10px;
  background:rgba(255,255,255,.68); color:var(--app-muted); font-size:12px;
}
.app-empty strong {
  display:block; margin-bottom:4px; color:var(--app-text); font-size:13px;
}
@media (max-width:900px) {
  .app-appbar,.app-context { align-items:flex-start; }
  .app-context { flex-direction:column; }
  .app-context__chips { justify-content:flex-start; }
}
@media (max-width:1150px) {
  .st-key-review_workspace [data-testid="stHorizontalBlock"] {
    flex-direction:column;
  }
  .st-key-review_workspace [data-testid="stColumn"] {
    width:100%; flex:1 1 100%;
  }
}
</style>
"""
