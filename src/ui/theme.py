"""Shared product styling for the Streamlit review workspace."""

APP_CSS = """
<style>
:root {
  --tnt-navy: #123b4b;
  --tnt-navy-soft: #1d5264;
  --tnt-teal: #118b7e;
  --tnt-bg: #f3f6f7;
  --tnt-panel: #ffffff;
  --tnt-border: #dfe7ea;
  --tnt-text: #173743;
  --tnt-muted: #70818a;
  --tnt-success: #147866;
  --tnt-success-bg: #e9f6f2;
  --tnt-missing: #b94e42;
  --tnt-missing-bg: #fff0ee;
}
[data-testid="stAppViewContainer"] { background: var(--tnt-bg); }
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
  padding:12px; border:1px solid var(--tnt-border); border-radius:10px;
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
  border-color:var(--tnt-border) !important; border-radius:10px !important;
  background:#fff; box-shadow:0 3px 14px rgba(29,61,73,.04);
}
.tnt-document-actions__eyebrow {
  margin-bottom:8px; color:#819099; font-size:10px; font-weight:800;
  letter-spacing:.08em; text-transform:uppercase;
}
.tnt-document-actions__title {
  color:var(--tnt-text); font-size:14px; font-weight:800; line-height:1.3;
}
.tnt-document-actions__subtitle {
  min-height:36px; margin-top:4px; color:var(--tnt-muted); font-size:11px; line-height:1.45;
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
  width:100%; min-height:38px; border:1px solid var(--tnt-navy); border-radius:8px;
  background:var(--tnt-navy); color:#fff; font-size:0; font-weight:700;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] button::after {
  content:"Chọn tài liệu"; font-size:14px;
}
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] button::after {
  content:"Đổi tài liệu"; font-size:14px;
}
.st-key-document_actions_idle [data-testid="stFileUploaderDropzone"] button:hover,
.st-key-document_actions_active [data-testid="stFileUploaderDropzone"] button:hover {
  border-color:var(--tnt-navy-soft); background:var(--tnt-navy-soft); color:#fff;
}
.st-key-document_actions_idle [data-testid="stBaseButton-primary"],
.st-key-document_actions_active [data-testid="stBaseButton-primary"] {
  width:100%;
  background: var(--tnt-teal); border-color: var(--tnt-teal);
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
.tnt-appbar {
  display:flex; align-items:center; justify-content:flex-start; gap:10px;
  width:100%; min-height:46px; padding:11px 13px; margin-bottom:12px; color:#fff;
  background:linear-gradient(135deg,var(--tnt-navy),var(--tnt-navy-soft));
  border-radius:10px; box-shadow:0 5px 18px rgba(18,59,75,.13);
}
.tnt-brand { display:flex; align-items:center; gap:10px; }
.tnt-brand__mark {
  display:grid; place-items:center; width:34px; height:34px; border-radius:9px;
  background:#2ac0a7; color:#0e3b46; font-weight:900;
}
.tnt-brand__name { font-size:13px; font-weight:800; line-height:1.2; }
.tnt-brand__subtitle { margin-top:1px; font-size:11px; color:rgba(255,255,255,.67); }
.tnt-context {
  display:flex; align-items:center; justify-content:space-between;
  gap:14px; min-height:46px; margin-bottom:8px;
}
.tnt-context__title {
  overflow:hidden; color:var(--tnt-text); font-size:20px; font-weight:900;
  line-height:1.25; text-overflow:ellipsis; white-space:nowrap;
}
.tnt-context__chips { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; }
.tnt-chip {
  display:inline-flex; align-items:center; min-height:32px; padding:6px 11px;
  border:1px solid var(--tnt-border); border-radius:7px; background:#fff;
  color:#455f69; font-size:13px; font-weight:800;
}
.tnt-chip--success {
  border-color:#cce8df; background:var(--tnt-success-bg);
  color:var(--tnt-success); font-weight:800;
}
.tnt-chip--error {
  border-color:#f1d2ce; background:var(--tnt-missing-bg);
  color:var(--tnt-missing); font-weight:800;
}
.tnt-panel-head {
  display:flex; align-items:center; justify-content:space-between; min-height:42px;
  padding:0 12px; border:1px solid var(--tnt-border); border-bottom:0;
  border-radius:10px 10px 0 0; background:#fff;
}
.tnt-panel-head__title { color:var(--tnt-text); font-size:13px; font-weight:800; }
.tnt-panel-head__meta { color:var(--tnt-muted); font-size:11px; }
.tnt-preview-notice {
  margin:0; padding:7px 10px; border-right:1px solid var(--tnt-border);
  border-left:1px solid var(--tnt-border); background:#fff9e7;
  color:#856e28; font-size:11px;
}
.tnt-results {
  overflow:hidden; border:1px solid var(--tnt-border); border-radius:10px;
  background:var(--tnt-panel); box-shadow:0 3px 14px rgba(29,61,73,.05);
}
.tnt-results--error {
  border-color:#f1d2ce; background:#fffafa;
}
.tnt-results--error .tnt-results__title {
  color:var(--tnt-missing);
}
.tnt-results__head { padding:13px; border-bottom:1px solid var(--tnt-border); }
.tnt-results__title-row {
  display:flex; align-items:center; gap:9px;
}
.tnt-results__title { color:var(--tnt-text); font-size:15px; font-weight:800; }
.tnt-results__summary { margin-top:4px; color:var(--tnt-muted); font-size:13px; }
.tnt-spinner {
  flex:0 0 auto; width:18px; height:18px; border-radius:999px;
  border:3px solid #d7eee8; border-top-color:var(--tnt-teal);
  animation:tnt-spin .8s linear infinite;
}
@keyframes tnt-spin {
  to { transform:rotate(360deg); }
}
.tnt-progress {
  height:5px; margin-top:9px; overflow:hidden; border-radius:999px; background:#edf2f3;
}
.tnt-progress__bar { height:100%; border-radius:999px; background:var(--tnt-teal); }
.tnt-progress__bar--indeterminate {
  width:42%; animation:tnt-progress-sweep 1.35s ease-in-out infinite;
}
@keyframes tnt-progress-sweep {
  0% { transform:translateX(-120%); }
  100% { transform:translateX(260%); }
}
.tnt-result-row {
  display:flex; align-items:center; justify-content:space-between; gap:10px;
  min-height:48px; padding:9px 13px; border-bottom:1px solid #edf1f2;
}
.tnt-result-row:last-child { border-bottom:0; }
.tnt-result-label { color:#37535e; font-size:14px; line-height:1.38; }
.tnt-required { color:var(--tnt-missing); font-weight:900; }
.tnt-status {
  flex:0 0 auto; min-width:50px; padding:5px 9px; border-radius:999px;
  text-align:center; font-size:12px; font-weight:800;
}
.tnt-status--ok { background:var(--tnt-success-bg); color:var(--tnt-success); }
.tnt-status--missing { background:var(--tnt-missing-bg); color:var(--tnt-missing); }
.tnt-status--error { background:var(--tnt-missing-bg); color:var(--tnt-missing); }
.tnt-sidebar-brand { margin-bottom:12px; }
.tnt-sidebar-brand__title { color:var(--tnt-text); font-size:14px; font-weight:800; }
.tnt-sidebar-brand__subtitle { margin-top:2px; color:var(--tnt-muted); font-size:11px; }
.tnt-sidebar-label {
  margin:14px 0 6px; color:#819099; font-size:10px; font-weight:800;
  letter-spacing:.08em; text-transform:uppercase;
}
.tnt-sidebar-summary { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
.tnt-summary-card {
  padding:8px; border-radius:8px; background:#f3f7f8; color:#71828a; font-size:10px;
}
.tnt-summary-card strong {
  display:block; margin-bottom:1px; color:var(--tnt-text); font-size:19px;
}
.tnt-summary-card--found { background:var(--tnt-success-bg); }
.tnt-summary-card--found strong { color:var(--tnt-success); }
.tnt-summary-card--missing { background:var(--tnt-missing-bg); }
.tnt-summary-card--missing strong { color:var(--tnt-missing); }
.tnt-reference-card {
  margin-top:6px; padding:8px; border-radius:8px; background:#f3f7f8;
  color:#71828a; font-size:10px;
}
.tnt-reference-card strong {
  display:block; margin-top:1px; color:var(--tnt-text); font-size:13px;
}
.tnt-empty {
  padding:18px; border:1px dashed #cbd8dd; border-radius:0 0 10px 10px;
  background:rgba(255,255,255,.68); color:var(--tnt-muted); font-size:12px;
}
.tnt-empty strong {
  display:block; margin-bottom:4px; color:var(--tnt-text); font-size:13px;
}
@media (max-width:900px) {
  .tnt-appbar,.tnt-context { align-items:flex-start; }
  .tnt-context { flex-direction:column; }
  .tnt-context__chips { justify-content:flex-start; }
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
