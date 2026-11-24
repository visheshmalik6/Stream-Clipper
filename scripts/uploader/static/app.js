/* Stream Clips Dashboard Client-Side Logic (Phase 2 YouTube Data API v3 Integration) */

let currentStreams = [];
let selectedClip = null;
let currentHashtags = [];
let ytStatus = { connected: false, client_configured: false, channel: null };
let igStatus = { connected: false, configured: false, account: null, masked_token: null, public_base_url: null };
let duplicateTargetPlatform = "youtube";

// DOM Elements
const streamsContainer = document.getElementById("streams-container");
const clipCountBadge = document.getElementById("clip-count-badge");
const emptyState = document.getElementById("empty-state");
const editorContainer = document.getElementById("editor-container");
const videoPlayer = document.getElementById("video-player");

const editTitle = document.getElementById("edit-title");
const titleCounter = document.getElementById("title-counter");
const editCaption = document.getElementById("edit-caption");
const captionCounter = document.getElementById("caption-counter");
const tagPills = document.getElementById("tag-pills");
const newTagInput = document.getElementById("new-tag-input");
const tagCounter = document.getElementById("tag-counter");
const editPrivacy = document.getElementById("edit-privacy");

const saveMetadataBtn = document.getElementById("save-metadata-btn");
const saveStatusIndicator = document.getElementById("save-status-indicator");
const refreshBtn = document.getElementById("refresh-btn");

const clipFilenameDisplay = document.getElementById("clip-filename-display");
const streamNameDisplay = document.getElementById("stream-name-display");
const whyText = document.getElementById("why-text");
const whyBox = document.getElementById("why-box");

const statScore = document.getElementById("stat-score");
const statDuration = document.getElementById("stat-duration");
const statType = document.getElementById("stat-type");
const statLook = document.getElementById("stat-look");

const ytStatusBadge = document.getElementById("yt-status-badge");
const igStatusBadge = document.getElementById("ig-status-badge");

const ytPublishedBanner = document.getElementById("yt-published-banner");
const ytPublishedTime = document.getElementById("yt-published-time");
const ytWatchLink = document.getElementById("yt-watch-link");

const igPublishedBanner = document.getElementById("ig-published-banner");
const igPublishedTime = document.getElementById("ig-published-time");
const igWatchLink = document.getElementById("ig-watch-link");

const uploadProgressContainer = document.getElementById("upload-progress-container");
const progressStatusText = document.getElementById("progress-status-text");
const progressPercentText = document.getElementById("progress-percent-text");
const progressBarFill = document.getElementById("progress-bar-fill");

const publishYtBtn = document.getElementById("publish-yt-btn");
const publishYtTitle = document.getElementById("publish-yt-title");
const publishYtSub = document.getElementById("publish-yt-sub");
const scheduleYtBtn = document.getElementById("schedule-yt-btn");
const scheduleYtTitle = document.getElementById("schedule-yt-title");
const scheduleYtSub = document.getElementById("schedule-yt-sub");
const ytScheduleTime = document.getElementById("yt-schedule-time");
const ytScheduledBanner = document.getElementById("yt-scheduled-banner");
const ytScheduledTime = document.getElementById("yt-scheduled-time");
const ytScheduledWatchLink = document.getElementById("yt-scheduled-watch-link");
const publishIgBtn = document.getElementById("publish-ig-btn");
const publishIgTitle = document.getElementById("publish-ig-title");
const publishIgSub = document.getElementById("publish-ig-sub");
const publishBothBtn = document.getElementById("publish-both-btn");

// YouTube Auth Header Elements
const ytConnectBtn = document.getElementById("yt-connect-btn");
const ytConnectBtnText = document.getElementById("yt-connect-btn-text");
const ytSettingsBtn = document.getElementById("yt-settings-btn");
const ytConnectedInfo = document.getElementById("yt-connected-info");
const ytChannelName = document.getElementById("yt-channel-name");
const ytDisconnectBtn = document.getElementById("yt-disconnect-btn");

// Instagram Auth Header Elements
const igConnectBtn = document.getElementById("ig-connect-btn");
const igConnectBtnText = document.getElementById("ig-connect-btn-text");
const igSettingsBtn = document.getElementById("ig-settings-btn");
const igConnectedInfo = document.getElementById("ig-connected-info");
const igAccountName = document.getElementById("ig-account-name");
const igDisconnectBtn = document.getElementById("ig-disconnect-btn");

// Instagram Modal Elements
const igConfigModal = document.getElementById("ig-config-modal");
const igConfigClose = document.getElementById("ig-config-close");
const igCfgStatusText = document.getElementById("ig-cfg-status-text");
const igCfgClearBtn = document.getElementById("ig-cfg-clear-btn");
const cfgIgToken = document.getElementById("cfg-ig-token");
const cfgIgPublicUrl = document.getElementById("cfg-ig-public-url");
const saveIgCfgBtn = document.getElementById("save-ig-cfg-btn");

// Modals
const ytConfigModal = document.getElementById("yt-config-modal");
const ytConfigClose = document.getElementById("yt-config-close");
const cfgStatusText = document.getElementById("cfg-status-text");
const cfgClearBtn = document.getElementById("cfg-clear-btn");
const tabPasteBtn = document.getElementById("tab-paste-btn");
const tabFileBtn = document.getElementById("tab-file-btn");
const configPasteView = document.getElementById("config-paste-view");
const configFileView = document.getElementById("config-file-view");
const cfgClientId = document.getElementById("cfg-client-id");
const cfgClientSecret = document.getElementById("cfg-client-secret");
const cfgSecretsJson = document.getElementById("cfg-secrets-json");
const saveCfgOnlyBtn = document.getElementById("save-cfg-only-btn");
const saveCfgBtn = document.getElementById("save-cfg-btn");

const ytConfirmModal = document.getElementById("yt-confirm-modal");
const ytConfirmClose = document.getElementById("yt-confirm-close");
const confirmClientId = document.getElementById("confirm-client-id");
const confirmChangeCfgBtn = document.getElementById("confirm-change-cfg-btn");
const confirmProceedBtn = document.getElementById("confirm-proceed-btn");

const duplicateModal = document.getElementById("duplicate-modal");
const duplicateClose = document.getElementById("duplicate-close");
const dupCancelBtn = document.getElementById("dup-cancel-btn");
const dupForceBtn = document.getElementById("dup-force-btn");
const dupUploadedTime = document.getElementById("dup-uploaded-time");
const dupVideoLink = document.getElementById("dup-video-link");
const dupPlatformName = document.getElementById("dup-platform-name");

const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalCloseBtn = document.getElementById("modal-close-btn");
const modalOkBtn = document.getElementById("modal-ok-btn");
const toast = document.getElementById("toast");

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  checkUrlParamsForAuth();
  loadYouTubeStatus();
  loadInstagramStatus();
  loadStreams();
  setupEventListeners();
});

function checkUrlParamsForAuth() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("auth") === "youtube_success") {
    showToast("✓ YouTube account connected successfully!");
    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (params.get("auth_error")) {
    showModal("YouTube Connection Error", `Failed to authorize with Google: ${escapeHtml(params.get("auth_error"))}`);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

async function loadYouTubeStatus() {
  try {
    const res = await fetch("/api/youtube/status");
    ytStatus = await res.json();
    renderYouTubeHeaderStatus();
  } catch (err) {
    console.error("Failed to load YouTube status:", err);
  }
}

function renderYouTubeHeaderStatus() {
  if (ytStatus.connected) {
    ytConnectBtn.classList.add("hidden");
    ytConnectedInfo.classList.remove("hidden");
    const name = (ytStatus.channel && ytStatus.channel.title) || "Connected Channel";
    ytChannelName.textContent = name;
  } else {
    ytConnectBtn.classList.remove("hidden");
    ytConnectedInfo.classList.add("hidden");
    ytConnectBtnText.textContent = ytStatus.client_configured ? "Connect YouTube" : "Setup YouTube API";
  }
}

async function loadInstagramStatus() {
  try {
    const res = await fetch("/api/instagram/status");
    igStatus = await res.json();
    renderInstagramHeaderStatus();
  } catch (err) {
    console.error("Failed to load Instagram status:", err);
  }
}

function renderInstagramHeaderStatus() {
  if (igStatus.connected && igStatus.account) {
    igConnectBtn.classList.add("hidden");
    igConnectedInfo.classList.remove("hidden");
    const name = igStatus.account.username ? `@${igStatus.account.username}` : (igStatus.account.name || "Instagram");
    igAccountName.textContent = name;
  } else {
    igConnectBtn.classList.remove("hidden");
    igConnectedInfo.classList.add("hidden");
    igConnectBtnText.textContent = igStatus.configured ? "Connect Instagram" : "Setup Instagram API";
  }
}

function setupEventListeners() {
  refreshBtn.addEventListener("click", () => {
    loadStreams();
    loadYouTubeStatus();
    loadInstagramStatus();
    showToast("Clips refreshed from disk");
  });

  // Counters
  editTitle.addEventListener("input", updateCounters);
  editCaption.addEventListener("input", updateCounters);

  // Hashtag input
  newTagInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === "," || e.key === " ") {
      e.preventDefault();
      addTagFromInput();
    }
  });

  newTagInput.addEventListener("blur", () => {
    if (newTagInput.value.trim()) addTagFromInput();
  });

  // Save metadata
  saveMetadataBtn.addEventListener("click", saveMetadata);

  // YouTube OAuth buttons
  ytConnectBtn.addEventListener("click", handleConnectYouTubeClick);
  ytSettingsBtn.addEventListener("click", () => openConfigModal());
  ytDisconnectBtn.addEventListener("click", handleDisconnectYouTube);

  // YouTube Config Modal
  ytConfigClose.addEventListener("click", () => ytConfigModal.classList.add("hidden"));
  tabPasteBtn.addEventListener("click", () => switchConfigTab("paste"));
  tabFileBtn.addEventListener("click", () => switchConfigTab("file"));
  cfgClearBtn.addEventListener("click", handleClearGoogleConfig);
  saveCfgBtn.addEventListener("click", () => handleSaveGoogleConfig(true));
  saveCfgOnlyBtn.addEventListener("click", () => handleSaveGoogleConfig(false));

  // YouTube Confirm Modal
  ytConfirmClose.addEventListener("click", () => ytConfirmModal.classList.add("hidden"));
  confirmChangeCfgBtn.addEventListener("click", () => {
    ytConfirmModal.classList.add("hidden");
    openConfigModal();
  });
  confirmProceedBtn.addEventListener("click", proceedToGoogleOAuth);

  // Instagram Credentials buttons & modal
  igConnectBtn.addEventListener("click", () => openInstagramConfigModal());
  igSettingsBtn.addEventListener("click", () => openInstagramConfigModal());
  igDisconnectBtn.addEventListener("click", handleClearInstagramConfig);
  igConfigClose.addEventListener("click", () => igConfigModal.classList.add("hidden"));
  igCfgClearBtn.addEventListener("click", handleClearInstagramConfig);
  saveIgCfgBtn.addEventListener("click", handleSaveInstagramConfig);

  // Publishing actions
  publishYtBtn.addEventListener("click", handlePublishYouTube);
  scheduleYtBtn.addEventListener("click", handleScheduleYouTube);
  publishIgBtn.addEventListener("click", handlePublishInstagram);
  publishBothBtn.addEventListener("click", () => triggerPublishPlaceholder("both"));

  // Duplicate Warning Modal
  duplicateClose.addEventListener("click", () => duplicateModal.classList.add("hidden"));
  dupCancelBtn.addEventListener("click", () => duplicateModal.classList.add("hidden"));
  dupForceBtn.addEventListener("click", () => {
    duplicateModal.classList.add("hidden");
    if (duplicateTargetPlatform === "instagram") {
      executeInstagramUpload(true);
    } else if (duplicateTargetPlatform === "youtube_schedule") {
      executeYouTubeSchedule(true);
    } else {
      executeYouTubeUpload(true);
    }
  });

  // Generic modal
  modalCloseBtn.addEventListener("click", closeModal);
  modalOkBtn.addEventListener("click", closeModal);
}

function switchConfigTab(tab) {
  if (tab === "paste") {
    tabPasteBtn.classList.add("active");
    tabFileBtn.classList.remove("active");
    configPasteView.classList.remove("hidden");
    configFileView.classList.add("hidden");
  } else {
    tabPasteBtn.classList.remove("active");
    tabFileBtn.classList.add("active");
    configPasteView.classList.add("hidden");
    configFileView.classList.remove("hidden");
  }
}

function openConfigModal() {
  if (ytStatus.client_configured) {
    cfgStatusText.innerHTML = `Active Client: <code class="code-pill">${escapeHtml(ytStatus.masked_client_id || "Configured")}</code>`;
    cfgClearBtn.classList.remove("hidden");
  } else {
    cfgStatusText.innerHTML = `<span>No Google Client configured yet. Enter credentials below.</span>`;
    cfgClearBtn.classList.add("hidden");
  }
  ytConfigModal.classList.remove("hidden");
}

async function handleConnectYouTubeClick() {
  if (!ytStatus.client_configured) {
    openConfigModal();
    return;
  }
  // Client is configured: show confirmation dialog with masked Client ID before redirecting
  confirmClientId.textContent = ytStatus.masked_client_id || "Configured Client ID";
  ytConfirmModal.classList.remove("hidden");
}

async function proceedToGoogleOAuth() {
  ytConfirmModal.classList.add("hidden");
  try {
    const res = await fetch("/api/youtube/auth-url");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to generate Google auth URL");
    window.location.href = data.auth_url;
  } catch (err) {
    showModal("Google Auth Error", err.message);
  }
}

async function handleClearGoogleConfig() {
  if (!confirm("Are you sure you want to clear your saved Google OAuth credentials?")) return;
  try {
    const res = await fetch("/api/youtube/config/clear", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      cfgClientId.value = "";
      cfgClientSecret.value = "";
      cfgSecretsJson.value = "";
      showToast("Google credentials cleared.");
      await loadYouTubeStatus();
      openConfigModal();
    } else {
      throw new Error(data.error || "Failed to clear");
    }
  } catch (err) {
    showModal("Error", err.message);
  }
}

async function handleSaveGoogleConfig(andConnect = true) {
  const isPaste = tabPasteBtn.classList.contains("active");
  let payload = {};

  if (isPaste) {
    const clientId = cfgClientId.value.trim();
    const clientSecret = cfgClientSecret.value.trim();
    if (!clientId || !clientSecret) {
      alert("Please enter both Client ID and Client Secret.");
      return;
    }
    payload = { client_id: clientId, client_secret: clientSecret };
  } else {
    const rawJson = cfgSecretsJson.value.trim();
    if (!rawJson) {
      alert("Please paste the client_secrets.json content.");
      return;
    }
    payload = { client_secrets_json: rawJson };
  }

  saveCfgBtn.disabled = true;
  saveCfgOnlyBtn.disabled = true;

  try {
    const res = await fetch("/api/youtube/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to save configuration");

    ytConfigModal.classList.add("hidden");
    showToast("Google credentials saved securely!");
    await loadYouTubeStatus();

    if (andConnect) {
      await proceedToGoogleOAuth();
    }
  } catch (err) {
    showModal("Configuration Error", err.message);
  } finally {
    saveCfgBtn.disabled = false;
    saveCfgOnlyBtn.disabled = false;
  }
}

async function handleDisconnectYouTube() {
  if (!confirm("Are you sure you want to disconnect your YouTube account?")) return;
  try {
    const res = await fetch("/api/youtube/disconnect", { method: "POST" });
    if (res.ok) {
      showToast("YouTube account disconnected.");
      await loadYouTubeStatus();
    }
  } catch (err) {
    showModal("Error", err.message);
  }
}

function openInstagramConfigModal() {
  if (igStatus.configured && igStatus.account) {
    const handle = igStatus.account.username ? `@${igStatus.account.username}` : (igStatus.account.id || "Connected");
    igCfgStatusText.innerHTML = `Active Account: <code class="code-pill">${escapeHtml(handle)}</code> &bull; Token: <code class="code-pill">${escapeHtml(igStatus.masked_token || "Configured")}</code>`;
    igCfgClearBtn.classList.remove("hidden");
  } else {
    igCfgStatusText.innerHTML = `<span>No Instagram Token configured. Enter System-User Access Token below.</span>`;
    igCfgClearBtn.classList.add("hidden");
  }
  cfgIgPublicUrl.value = igStatus.public_base_url || "";
  cfgIgToken.value = "";
  igConfigModal.classList.remove("hidden");
}

async function handleSaveInstagramConfig() {
  const token = cfgIgToken.value.trim();
  const publicUrl = cfgIgPublicUrl.value.trim();

  if (!token && !igStatus.configured) {
    alert("Please enter your Meta System-User Access Token.");
    return;
  }

  saveIgCfgBtn.disabled = true;
  saveIgCfgBtn.textContent = "Verifying with Meta Graph API...";

  try {
    const res = await fetch("/api/instagram/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: token, public_base_url: publicUrl }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to validate token with Meta.");

    igConfigModal.classList.add("hidden");
    const acc = data.account ? `@${data.account.username}` : "account";
    showToast(`✓ Instagram connected (${acc})!`);
    await loadInstagramStatus();
  } catch (err) {
    showModal("Instagram Validation Error", escapeHtml(err.message));
  } finally {
    saveIgCfgBtn.disabled = false;
    saveIgCfgBtn.textContent = "Save & Validate Instagram Token";
  }
}

async function handleClearInstagramConfig() {
  if (!confirm("Are you sure you want to disconnect your Instagram account and clear the saved token?")) return;
  try {
    const res = await fetch("/api/instagram/disconnect", { method: "POST" });
    if (res.ok) {
      cfgIgToken.value = "";
      showToast("Instagram account disconnected.");
      await loadInstagramStatus();
      openInstagramConfigModal();
    }
  } catch (err) {
    showModal("Error", err.message);
  }
}

async function loadStreams() {
  try {
    const res = await fetch("/api/streams");
    const data = await res.json();
    currentStreams = data.streams || [];
    renderStreamsSidebar();
  } catch (err) {
    streamsContainer.innerHTML = `<div class="error-state">Failed to load clips: ${err.message}</div>`;
  }
}

function renderStreamsSidebar() {
  streamsContainer.innerHTML = "";
  let totalClips = 0;

  if (currentStreams.length === 0) {
    streamsContainer.innerHTML = `<div class="empty-state-small">No clips found in configured DATA directory.</div>`;
    clipCountBadge.textContent = "0 clips";
    return;
  }

  currentStreams.forEach((stream) => {
    const groupEl = document.createElement("div");
    groupEl.className = "stream-group";

    const titleEl = document.createElement("div");
    titleEl.className = "stream-group-title";
    titleEl.innerHTML = `
      <span>${escapeHtml(stream.name)}</span>
      ${stream.topic ? `<span class="stream-topic-tag">${escapeHtml(stream.topic)}</span>` : ""}
    `;
    groupEl.appendChild(titleEl);

    (stream.clips || []).forEach((clip) => {
      totalClips++;
      const card = document.createElement("div");
      card.className = `clip-card ${selectedClip && selectedClip.id === clip.id ? "active" : ""}`;
      card.dataset.clipId = clip.id;

      const thumbImg = clip.check_image_exists
        ? `<img src="/media/image/${clip.id}" alt="preview">`
        : `<div class="clip-thumb-placeholder">🎬</div>`;

      card.innerHTML = `
        <div class="clip-thumb">${thumbImg}</div>
        <div class="clip-meta-preview">
          <div class="clip-card-title">${escapeHtml(clip.title || clip.file)}</div>
          <div class="clip-card-sub">
            <span class="badge badge-score">${clip.score}</span>
            <span>${clip.seconds ? Math.round(clip.seconds) + "s" : ""}</span>
            <span>${clip.type || ""}</span>
          </div>
        </div>
      `;

      card.addEventListener("click", () => selectClip(clip, stream));
      groupEl.appendChild(card);
    });

    streamsContainer.appendChild(groupEl);
  });

  clipCountBadge.textContent = `${totalClips} clip${totalClips === 1 ? "" : "s"}`;

  if (selectedClip) {
    const found = findClipById(selectedClip.id);
    if (found) {
      selectClip(found.clip, found.stream);
      return;
    }
  }

  if (currentStreams[0] && currentStreams[0].clips[0]) {
    selectClip(currentStreams[0].clips[0], currentStreams[0]);
  }
}

function selectClip(clip, stream) {
  selectedClip = clip;

  document.querySelectorAll(".clip-card").forEach((card) => {
    card.classList.toggle("active", card.dataset.clipId === clip.id);
  });

  emptyState.classList.add("hidden");
  editorContainer.classList.remove("hidden");

  // Video preview
  videoPlayer.src = `/media/video/${clip.id}`;
  if (clip.check_image_exists) {
    videoPlayer.poster = `/media/image/${clip.id}`;
  } else {
    videoPlayer.removeAttribute("poster");
  }
  videoPlayer.load();

  // Populate metadata
  streamNameDisplay.textContent = `${stream.name} • ${stream.title}`;
  clipFilenameDisplay.textContent = clip.file;

  editTitle.value = clip.title || "";
  editCaption.value = clip.caption || "";
  currentHashtags = [...(clip.hashtags || [])];
  renderTags();

  // Privacy selection
  const ytUpload = (clip.uploads && clip.uploads.youtube) || {};
  const igUpload = (clip.uploads && clip.uploads.instagram) || {};
  editPrivacy.value = ytUpload.privacy || "public";

  // Pre-populate scheduled time if available
  const schedUtc = ytUpload.scheduled_at || ytUpload.publish_at;
  if (schedUtc) {
    const d = new Date(schedUtc);
    if (!isNaN(d.getTime())) {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      const hours = String(d.getHours()).padStart(2, "0");
      const minutes = String(d.getMinutes()).padStart(2, "0");
      ytScheduleTime.value = `${year}-${month}-${day}T${hours}:${minutes}`;
    } else {
      ytScheduleTime.value = "";
    }
  } else {
    ytScheduleTime.value = "";
  }

  // Prevent picking past dates in browser picker
  const now = new Date();
  const nowStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}T${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  ytScheduleTime.min = nowStr;

  // Stats
  statScore.textContent = `Score: ${clip.score}`;
  statDuration.textContent = `${clip.seconds ? Math.round(clip.seconds) : 0}s`;
  statType.textContent = clip.type || "clip";
  statLook.textContent = clip.look || "stack";

  if (clip.why) {
    whyBox.style.display = "block";
    whyText.textContent = clip.why;
  } else {
    whyBox.style.display = "none";
  }

  // Upload badges & published banner
  updateUploadBadges(clip.uploads || {});
  updateYouTubeBannerAndButtons(ytUpload);
  updateInstagramBannerAndButtons(igUpload);

  updateCounters();
  saveStatusIndicator.textContent = "";
}

function updateInstagramBannerAndButtons(igUpload) {
  const status = igUpload.status || "not_uploaded";

  if (status === "published") {
    igPublishedBanner.classList.remove("hidden");
    igPublishedTime.textContent = igUpload.uploaded_at
      ? `Uploaded on ${new Date(igUpload.uploaded_at).toLocaleString()}`
      : "";
    igWatchLink.href = igUpload.url || "#";
    igWatchLink.textContent = `Open Reel in Instagram (${igUpload.media_id || ""}) ↗`;

    publishIgTitle.textContent = "Re-publish to Instagram";
    publishIgSub.textContent = "Already published (creates new Reel)";
    publishIgBtn.classList.add("published-state");
  } else if (status === "failed") {
    igPublishedBanner.classList.add("hidden");
    publishIgTitle.textContent = "Retry Instagram Reel";
    publishIgSub.textContent = igUpload.error ? `Failed: ${igUpload.error.slice(0, 30)}...` : "Click to retry";
    publishIgBtn.classList.remove("published-state");
  } else {
    igPublishedBanner.classList.add("hidden");
    publishIgTitle.textContent = "Publish to Instagram";
    publishIgSub.textContent = "Reels (Meta Graph API)";
    publishIgBtn.classList.remove("published-state");
  }
}

function updateYouTubeBannerAndButtons(ytUpload) {
  const status = ytUpload.status || "not_uploaded";

  if (status === "published") {
    ytScheduledBanner.classList.add("hidden");
    ytPublishedBanner.classList.remove("hidden");
    ytPublishedTime.textContent = ytUpload.uploaded_at
      ? `Uploaded on ${new Date(ytUpload.uploaded_at).toLocaleString()} (${ytUpload.privacy || "public"})`
      : "";
    ytWatchLink.href = ytUpload.url || "#";
    ytWatchLink.textContent = `Open YouTube Shorts (${ytUpload.video_id || ""}) ↗`;

    publishYtTitle.textContent = "Re-upload Now";
    publishYtSub.textContent = "Already published (creates new Short)";
    publishYtBtn.classList.add("published-state");
    scheduleYtBtn.classList.remove("scheduled-state");
  } else if (status === "scheduled") {
    ytPublishedBanner.classList.add("hidden");
    ytScheduledBanner.classList.remove("hidden");
    const schedTime = ytUpload.scheduled_at || ytUpload.publish_at;
    const schedLocal = schedTime ? new Date(schedTime).toLocaleString() : "scheduled time";
    ytScheduledTime.textContent = `Scheduled to publish on ${schedLocal} (UTC: ${schedTime || "pending"})`;
    ytScheduledWatchLink.href = ytUpload.url || "#";
    ytScheduledWatchLink.textContent = `Open YouTube Shorts (${ytUpload.video_id || ""}) ↗`;

    scheduleYtTitle.textContent = "Re-schedule YouTube";
    scheduleYtSub.textContent = `Scheduled for ${schedLocal}`;
    scheduleYtBtn.classList.add("scheduled-state");
    publishYtTitle.textContent = "Upload Now";
    publishYtSub.textContent = "YouTube Shorts (Immediate)";
    publishYtBtn.classList.remove("published-state");
  } else if (status === "failed") {
    ytPublishedBanner.classList.add("hidden");
    ytScheduledBanner.classList.add("hidden");
    publishYtTitle.textContent = "Retry YouTube Upload";
    publishYtSub.textContent = ytUpload.error ? `Failed: ${ytUpload.error.slice(0, 30)}...` : "Click to retry";
    publishYtBtn.classList.remove("published-state");
    scheduleYtBtn.classList.remove("scheduled-state");
  } else {
    ytPublishedBanner.classList.add("hidden");
    ytScheduledBanner.classList.add("hidden");
    publishYtTitle.textContent = "Upload Now";
    publishYtSub.textContent = "YouTube Shorts (Immediate)";
    publishYtBtn.classList.remove("published-state");
    scheduleYtTitle.textContent = "Schedule YouTube";
    scheduleYtSub.textContent = "Publish at selected date/time";
    scheduleYtBtn.classList.remove("scheduled-state");
  }
}

function updateCounters() {
  const titleLen = editTitle.value.length;
  titleCounter.textContent = `${titleLen} / 100`;
  titleCounter.classList.toggle("warning", titleLen > 70 && titleLen <= 90);
  titleCounter.classList.toggle("danger", titleLen > 90);

  const captionLen = editCaption.value.length;
  captionCounter.textContent = `${captionLen} / 2200`;
  captionCounter.classList.toggle("warning", captionLen > 2000 && captionLen <= 2150);
  captionCounter.classList.toggle("danger", captionLen > 2150);
}

function renderTags() {
  tagPills.innerHTML = "";
  currentHashtags.forEach((tag, index) => {
    const pill = document.createElement("span");
    pill.className = "tag-pill";
    pill.innerHTML = `
      ${escapeHtml(tag)}
      <button type="button" class="tag-remove-btn" data-index="${index}">&times;</button>
    `;
    tagPills.appendChild(pill);
  });
  tagCounter.textContent = `${currentHashtags.length} tag${currentHashtags.length === 1 ? "" : "s"}`;

  tagPills.querySelectorAll(".tag-remove-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const idx = parseInt(e.target.dataset.index, 10);
      currentHashtags.splice(idx, 1);
      renderTags();
    });
  });
}

function addTagFromInput() {
  const raw = newTagInput.value.trim().replace(/^#+/, "");
  if (!raw) return;

  const tag = `#${raw}`;
  if (!currentHashtags.includes(tag)) {
    currentHashtags.push(tag);
    renderTags();
  }
  newTagInput.value = "";
}

async function saveMetadata() {
  if (!selectedClip) return;

  saveMetadataBtn.disabled = true;
  saveStatusIndicator.textContent = "Saving...";

  const payload = {
    title: editTitle.value.trim(),
    caption: editCaption.value.trim(),
    hashtags: currentHashtags,
  };

  try {
    const res = await fetch(`/api/clips/${selectedClip.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to save");

    saveStatusIndicator.textContent = "✓ Saved & backed up";
    showToast("Metadata saved to clips.json (backup created)");

    selectedClip.title = payload.title;
    selectedClip.caption = payload.caption;
    selectedClip.hashtags = payload.hashtags;

    const activeCardTitle = document.querySelector(`.clip-card[data-clip-id="${selectedClip.id}"] .clip-card-title`);
    if (activeCardTitle) {
      activeCardTitle.textContent = payload.title || selectedClip.file;
    }
  } catch (err) {
    saveStatusIndicator.textContent = `❌ ${err.message}`;
    showToast(`Error: ${err.message}`);
  } finally {
    saveMetadataBtn.disabled = false;
    setTimeout(() => {
      if (saveStatusIndicator.textContent.includes("✓")) {
        saveStatusIndicator.textContent = "";
      }
    }, 4000);
  }
}

async function handlePublishYouTube() {
  if (!selectedClip) return;

  if (!ytStatus.connected) {
    handleConnectYouTubeClick();
    return;
  }

  // Check duplicate prevention
  const ytUpload = (selectedClip.uploads && selectedClip.uploads.youtube) || {};
  if (ytUpload.status === "published" || ytUpload.status === "scheduled") {
    duplicateTargetPlatform = "youtube";
    if (dupPlatformName) dupPlatformName.textContent = "YouTube Shorts";
    const existingTime = ytUpload.uploaded_at || ytUpload.scheduled_at;
    dupUploadedTime.textContent = existingTime ? new Date(existingTime).toLocaleString() : "previously";
    dupVideoLink.href = ytUpload.url || "#";
    duplicateModal.classList.remove("hidden");
    return;
  }

  executeYouTubeUpload(false, null);
}

async function handleScheduleYouTube() {
  if (!selectedClip) return;

  if (!ytStatus.connected) {
    handleConnectYouTubeClick();
    return;
  }

  const val = ytScheduleTime.value;
  if (!val) {
    showModal(
      "Schedule Time Required",
      "<p>Please select a date and time in the <strong>Schedule Publication Time</strong> field before scheduling.</p>"
    );
    return;
  }

  const localDate = new Date(val);
  if (isNaN(localDate.getTime())) {
    showModal("Invalid Date", "<p>Please select a valid date and time.</p>");
    return;
  }

  if (localDate.getTime() <= Date.now()) {
    showModal("Past Time Not Allowed", "<p>Scheduled time must be in the future. Please select an upcoming date and time.</p>");
    return;
  }

  // Interpret local time and convert to UTC ISO-8601
  const utcIso = localDate.toISOString();

  // Check duplicate prevention
  const ytUpload = (selectedClip.uploads && selectedClip.uploads.youtube) || {};
  if (ytUpload.status === "scheduled" || ytUpload.status === "published") {
    duplicateTargetPlatform = "youtube_schedule";
    if (dupPlatformName) dupPlatformName.textContent = "YouTube Shorts (Schedule)";
    const existingTime = ytUpload.scheduled_at || ytUpload.uploaded_at;
    dupUploadedTime.textContent = existingTime ? new Date(existingTime).toLocaleString() : "previously";
    dupVideoLink.href = ytUpload.url || "#";
    duplicateModal.classList.remove("hidden");
    return;
  }

  executeYouTubeUpload(false, utcIso);
}

function executeYouTubeSchedule(force = false) {
  const val = ytScheduleTime.value;
  if (!val) return;
  const localDate = new Date(val);
  if (isNaN(localDate.getTime()) || localDate.getTime() <= Date.now()) return;
  executeYouTubeUpload(force, localDate.toISOString());
}

async function executeYouTubeUpload(force = false, publishAt = null) {
  if (!selectedClip) return;

  publishYtBtn.disabled = true;
  if (scheduleYtBtn) scheduleYtBtn.disabled = true;
  uploadProgressContainer.classList.remove("hidden");
  progressStatusText.textContent = publishAt ? "Initiating scheduled upload session..." : "Initiating resumable upload session...";
  progressBarFill.style.width = "20%";
  progressBarFill.style.background = "#4f8cff";

  const payload = {
    clip_id: selectedClip.id,
    title: editTitle.value.trim(),
    caption: editCaption.value.trim(),
    hashtags: currentHashtags,
    privacy: editPrivacy.value,
    force: force,
  };
  if (publishAt) {
    payload.publish_at = publishAt;
  }

  try {
    progressBarFill.style.width = "40%";
    progressStatusText.textContent = publishAt
      ? `Streaming vertical MP4 to YouTube (Scheduled for ${new Date(publishAt).toLocaleString()})...`
      : "Streaming vertical MP4 to YouTube...";

    const res = await fetch("/api/publish/youtube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();

    if (res.status === 409) {
      // Duplicate conflict returned from backend
      uploadProgressContainer.classList.add("hidden");
      duplicateTargetPlatform = publishAt ? "youtube_schedule" : "youtube";
      if (dupPlatformName) dupPlatformName.textContent = publishAt ? "YouTube Shorts (Schedule)" : "YouTube Shorts";
      const existingTime = data.scheduled_at || data.uploaded_at;
      dupUploadedTime.textContent = existingTime ? new Date(existingTime).toLocaleString() : "previously";
      dupVideoLink.href = data.url || "#";
      duplicateModal.classList.remove("hidden");
      return;
    }

    if (!res.ok) {
      throw new Error(data.error || data.message || "Upload failed");
    }

    progressBarFill.style.width = "100%";
    progressStatusText.textContent = publishAt ? "Scheduled successfully!" : "Published successfully!";

    // Update in-memory models
    if (!selectedClip.uploads) selectedClip.uploads = {};
    selectedClip.uploads.youtube = data.upload;

    updateUploadBadges(selectedClip.uploads);
    updateYouTubeBannerAndButtons(data.upload);

    if (publishAt) {
      showToast("🕒 Scheduled on YouTube Shorts successfully!");
      showModal(
        "Scheduled on YouTube Shorts!",
        `<p>Your vertical clip has been uploaded to YouTube and scheduled for release!</p>
         <br>
         <p><strong>Video ID:</strong> ${escapeHtml(data.upload.video_id)}</p>
         <p><strong>Scheduled Release:</strong> ${escapeHtml(new Date(publishAt).toLocaleString())} (UTC: ${escapeHtml(publishAt)})</p>
         <p><strong>Initial Visibility:</strong> Private (will become Public at scheduled time)</p>
         <br>
         <p><a href="${escapeHtml(data.upload.url)}" target="_blank" rel="noopener" style="color:#4f8cff; font-weight:600;">Open Short in YouTube ↗</a></p>
         <br>
         <p style="font-size:12px; color:#9ca3af;">Upload is complete. YouTube will publish this video automatically even if your computer is turned off.</p>`
      );
    } else {
      showToast("🎉 Published to YouTube Shorts successfully!");
      showModal(
        "Published to YouTube Shorts!",
        `<p>Your vertical clip has been uploaded to YouTube Data API v3!</p>
         <br>
         <p><strong>Video ID:</strong> ${escapeHtml(data.upload.video_id)}</p>
         <p><strong>Visibility:</strong> ${escapeHtml(data.upload.privacy)}</p>
         <br>
         <p><a href="${escapeHtml(data.upload.url)}" target="_blank" rel="noopener" style="color:#4f8cff; font-weight:600;">Open Short in YouTube ↗</a></p>`
      );
    }
  } catch (err) {
    progressStatusText.textContent = `Upload failed: ${err.message}`;
    progressBarFill.style.background = "#e5534b";
    showModal("YouTube Upload Error", `Failed to upload: ${escapeHtml(err.message)}<br><br><small>You can check the error and retry anytime.</small>`);

    // Update failed status
    if (selectedClip.uploads && selectedClip.uploads.youtube) {
      selectedClip.uploads.youtube.status = "failed";
      selectedClip.uploads.youtube.error = err.message;
      updateUploadBadges(selectedClip.uploads);
      updateYouTubeBannerAndButtons(selectedClip.uploads.youtube);
    }
  } finally {
    publishYtBtn.disabled = false;
    if (scheduleYtBtn) scheduleYtBtn.disabled = false;
    setTimeout(() => {
      uploadProgressContainer.classList.add("hidden");
      progressBarFill.style.width = "10%";
      progressBarFill.style.background = "#4f8cff";
    }, 4000);
  }
}

async function handlePublishInstagram() {
  if (!selectedClip) return;

  if (!igStatus.connected) {
    openInstagramConfigModal();
    return;
  }

  // Check duplicate prevention
  const igUpload = (selectedClip.uploads && selectedClip.uploads.instagram) || {};
  if (igUpload.status === "published") {
    duplicateTargetPlatform = "instagram";
    if (dupPlatformName) dupPlatformName.textContent = "Instagram Reels";
    dupUploadedTime.textContent = igUpload.uploaded_at ? new Date(igUpload.uploaded_at).toLocaleString() : "previously";
    dupVideoLink.href = igUpload.url || "#";
    duplicateModal.classList.remove("hidden");
    return;
  }

  executeInstagramUpload(false);
}

async function executeInstagramUpload(force = false) {
  if (!selectedClip) return;

  publishIgBtn.disabled = true;
  uploadProgressContainer.classList.remove("hidden");
  progressStatusText.textContent = "Setting up secure tunnel & media container...";
  progressBarFill.style.width = "20%";
  progressBarFill.style.background = "#d6558f";

  const payload = {
    clip_id: selectedClip.id,
    title: editTitle.value.trim(),
    caption: editCaption.value.trim(),
    hashtags: currentHashtags,
    force: force,
  };

  try {
    progressBarFill.style.width = "40%";
    progressStatusText.textContent = "Processing Reel on Meta servers...";

    const res = await fetch("/api/publish/instagram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();

    if (res.status === 409) {
      uploadProgressContainer.classList.add("hidden");
      duplicateTargetPlatform = "instagram";
      if (dupPlatformName) dupPlatformName.textContent = "Instagram Reels";
      dupUploadedTime.textContent = data.uploaded_at ? new Date(data.uploaded_at).toLocaleString() : "previously";
      dupVideoLink.href = data.url || "#";
      duplicateModal.classList.remove("hidden");
      return;
    }

    if (!res.ok) {
      throw new Error(data.error || data.message || "Instagram Reels publish failed");
    }

    progressBarFill.style.width = "100%";
    progressStatusText.textContent = "Published to Instagram Reels!";

    if (!selectedClip.uploads) selectedClip.uploads = {};
    selectedClip.uploads.instagram = data.upload;

    updateUploadBadges(selectedClip.uploads);
    updateInstagramBannerAndButtons(data.upload);

    showToast("🎉 Published to Instagram Reels successfully!");
    showModal(
      "Published to Instagram Reels!",
      `<p>Your vertical clip has been uploaded and published to Instagram Reels!</p>
       <br>
       <p><strong>Media ID:</strong> ${escapeHtml(data.upload.media_id)}</p>
       <br>
       <p><a href="${escapeHtml(data.upload.url)}" target="_blank" rel="noopener" style="color:#d6558f; font-weight:600;">Open Reel on Instagram ↗</a></p>`
    );
  } catch (err) {
    progressStatusText.textContent = `Instagram publish failed: ${err.message}`;
    progressBarFill.style.background = "#e5534b";
    showModal("Instagram Publishing Error", `Failed to publish to Instagram Reels: ${escapeHtml(err.message)}<br><br><small>You can check the error and retry anytime.</small>`);

    if (selectedClip.uploads && selectedClip.uploads.instagram) {
      selectedClip.uploads.instagram.status = "failed";
      selectedClip.uploads.instagram.error = err.message;
      updateUploadBadges(selectedClip.uploads);
      updateInstagramBannerAndButtons(selectedClip.uploads.instagram);
    }
  } finally {
    publishIgBtn.disabled = false;
    setTimeout(() => {
      uploadProgressContainer.classList.add("hidden");
      progressBarFill.style.width = "10%";
      progressBarFill.style.background = "#4f8cff";
    }, 4000);
  }
}

function triggerPublishPlaceholder(platform) {
  showModal(
    `${platform === "instagram" ? "Instagram Reels" : "Publish to Both"} Placeholder`,
    `<p>${platform === "instagram" ? "Instagram Reels integration with Meta Graph API" : "Multi-platform publishing"} is scheduled for upcoming phases.</p>
     <br>
     <p style="font-size:12px; color:#9ca3af;">Phase 2 focused strictly on YouTube Data API v3 integration with OAuth and Resumable uploads per your instructions.</p>`
  );
}

function updateUploadBadges(uploads) {
  const yt = uploads.youtube || { status: "not_uploaded" };
  const ig = uploads.instagram || { status: "not_uploaded" };

  ytStatusBadge.textContent = `YouTube: ${formatStatus(yt.status)}`;
  ytStatusBadge.className = `badge badge-status ${yt.status}`;

  igStatusBadge.textContent = `Instagram: ${formatStatus(ig.status)}`;
  igStatusBadge.className = `badge badge-status ${ig.status}`;
}

function formatStatus(status) {
  if (status === "published") return "Published ✓";
  if (status === "scheduled") return "Scheduled 🕒";
  if (status === "in_progress") return "Uploading...";
  if (status === "failed") return "Failed ✕";
  return "Ready to publish";
}

function findClipById(id) {
  for (const s of currentStreams) {
    for (const c of s.clips) {
      if (c.id === id) return { clip: c, stream: s };
    }
  }
  return null;
}

function showModal(title, htmlBody) {
  modalTitle.textContent = title;
  modalBody.innerHTML = htmlBody;
  modalOverlay.classList.remove("hidden");
}

function closeModal() {
  modalOverlay.classList.add("hidden");
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[m]));
}
