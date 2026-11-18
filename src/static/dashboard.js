const state = {
  claims: [],
  patients: [],
  selectedPatient: null,
  selectedClaim: null,
};

const money = (value) => new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
}).format(value);

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
}[character]));

const statusClass = (status) => `status-${status.toLowerCase().replaceAll(" ", "-")}`;

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json();
}

function showView(view) {
  const validViews = ["dashboard", "patients", "review"];
  const current = validViews.includes(view) ? view : "dashboard";
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === `view-${current}`);
  });
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === current);
  });
  const titles = { dashboard: "Overview", patients: "Patients", review: "Review queue" };
  document.getElementById("breadcrumb-current").textContent = titles[current];
  if (current === "patients" && !state.selectedPatient && state.patients.length) {
    selectPatient(state.patients[0].id);
  }
  if (current === "review" && !state.selectedClaim) {
    const first = state.claims.find((claim) => claim.status !== "Reviewed");
    if (first) selectClaim(first.id);
  }
}

function drawActivityChart(values, labels) {
  const canvas = document.getElementById("activity-chart");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * ratio);
  canvas.height = Math.max(1, rect.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const pad = { top: 8, right: 7, bottom: 9, left: 27 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const max = Math.ceil(Math.max(...values) / 100) * 100;
  context.font = "8px Segoe UI, sans-serif";
  context.textBaseline = "middle";
  for (let tick = 0; tick <= 3; tick += 1) {
    const y = pad.top + (chartHeight * tick) / 3;
    context.strokeStyle = "#edf0f5";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(pad.left, y);
    context.lineTo(width - pad.right, y);
    context.stroke();
    context.fillStyle = "#a0a9b7";
    context.fillText(String(Math.round(max * (1 - tick / 3))), 1, y);
  }
  const points = values.map((value, index) => ({
    x: pad.left + (chartWidth * index) / Math.max(1, values.length - 1),
    y: pad.top + chartHeight * (1 - value / max),
  }));
  const gradient = context.createLinearGradient(0, pad.top, 0, height);
  gradient.addColorStop(0, "rgba(82, 111, 229, .18)");
  gradient.addColorStop(1, "rgba(82, 111, 229, 0)");
  context.beginPath();
  context.moveTo(points[0].x, height - pad.bottom);
  points.forEach((point) => context.lineTo(point.x, point.y));
  context.lineTo(points[points.length - 1].x, height - pad.bottom);
  context.closePath();
  context.fillStyle = gradient;
  context.fill();
  context.beginPath();
  points.forEach((point, index) => {
    if (index === 0) context.moveTo(point.x, point.y);
    else context.lineTo(point.x, point.y);
  });
  context.strokeStyle = "#5975e4";
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.stroke();
  points.forEach((point, index) => {
    if (index !== points.length - 1 && index % 3 !== 0) return;
    context.beginPath();
    context.arc(point.x, point.y, 3, 0, Math.PI * 2);
    context.fillStyle = "#fff";
    context.fill();
    context.strokeStyle = "#5975e4";
    context.lineWidth = 1.5;
    context.stroke();
  });
  document.getElementById("chart-axis").innerHTML = labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("");
}

function drawCategoryChart(categories) {
  const canvas = document.getElementById("category-chart");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * ratio);
  canvas.height = Math.max(1, rect.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const total = categories.reduce((sum, item) => sum + item.count, 0);
  const centerX = rect.width / 2;
  const centerY = rect.height / 2;
  const radius = Math.min(rect.width, rect.height) * 0.39;
  let start = -Math.PI / 2;
  categories.forEach((item) => {
    const end = start + (item.count / total) * Math.PI * 2;
    context.beginPath();
    context.arc(centerX, centerY, radius, start, end - 0.025);
    context.strokeStyle = item.color;
    context.lineWidth = 16;
    context.lineCap = "round";
    context.stroke();
    start = end;
  });
  document.getElementById("category-legend").innerHTML = categories.map((item) => (
    `<div class="legend-item"><i class="legend-dot" style="background:${escapeHtml(item.color)}"></i>${escapeHtml(item.name)}<strong>${item.count}</strong></div>`
  )).join("");
  document.querySelector(".donut-center strong").textContent = total;
}

function memberMarkup(patient) {
  const review = patient.review_count
    ? `<span class="member-indicator">${patient.review_count} review</span>`
    : "";
  return `<button class="member-item ${state.selectedPatient === patient.id ? "selected" : ""}" type="button" data-patient="${escapeHtml(patient.id)}">
    <span class="member-avatar">${escapeHtml(patient.initials)}</span>
    <span class="member-item-copy"><strong>${escapeHtml(patient.name)}</strong><small>${escapeHtml(patient.plan)}</small></span>${review}
  </button>`;
}

async function selectPatient(patientId) {
  state.selectedPatient = patientId;
  document.getElementById("member-list").innerHTML = state.patients
    .filter((patient) => patient.name.toLowerCase().includes(document.getElementById("patient-search").value.toLowerCase()))
    .map(memberMarkup).join("") || '<p class="empty-row">No members match that search.</p>';
  try {
    const patient = await getJson(`/api/patients/${encodeURIComponent(patientId)}`);
    const claims = patient.claims.map((claim) => `<tr data-claim="${escapeHtml(claim.id)}" data-clickable="true">
      <td><span class="claim-id">${escapeHtml(claim.id)}</span></td><td>${escapeHtml(claim.date)}</td><td>${escapeHtml(claim.service)}</td>
      <td>${money(claim.charged)}</td><td><span class="status-pill ${statusClass(claim.status)}">${escapeHtml(claim.status)}</span></td>
    </tr>`).join("");
    document.getElementById("profile-panel").innerHTML = `<div class="profile-header">
      <span class="profile-big-avatar">${escapeHtml(patient.initials)}</span>
      <div class="profile-title"><h2>${escapeHtml(patient.name)}</h2><p>Member ID ${escapeHtml(patient.id)} · Age ${patient.age}</p></div>
      <span class="member-active">${escapeHtml(patient.status)}</span>
    </div>
    <div class="profile-meta">
      <div><span class="meta-label">COVERAGE</span><span class="meta-value">${escapeHtml(patient.plan)}</span></div>
      <div><span class="meta-label">MEMBER SINCE</span><span class="meta-value">${escapeHtml(patient.member_since)}</span></div>
      <div><span class="meta-label">LOCATION</span><span class="meta-value">${escapeHtml(patient.location)}</span></div>
      <div><span class="meta-label">CARE TEAM</span><span class="meta-value">${escapeHtml(patient.care_team)}</span></div>
      <div><span class="meta-label">CLAIMS</span><span class="meta-value">${patient.claims.length} demo records</span></div>
      <div><span class="meta-label">REVIEW SIGNALS</span><span class="meta-value">${patient.claims.filter((claim) => claim.status !== "Reviewed").length} open</span></div>
    </div>
    <div class="profile-section-title"><h3>Conditions</h3></div>
    <div class="condition-list">${patient.conditions.map((condition) => `<span class="condition-tag">${escapeHtml(condition)}</span>`).join("")}</div>
    <div class="profile-section-title"><h3>Recent claims</h3></div>
    <div class="profile-claims table-scroll"><table><thead><tr><th>CLAIM</th><th>DATE</th><th>SERVICE</th><th>SUBMITTED</th><th>STATUS</th></tr></thead><tbody>${claims}</tbody></table></div>`;
  } catch (error) {
    document.getElementById("profile-panel").innerHTML = `<p class="empty-row">${escapeHtml(error.message)}</p>`;
  }
}

function renderClaimTable(claims, target, includeSignal) {
  if (!claims.length) {
    target.innerHTML = '<tr><td class="empty-row" colspan="6">No claims match these filters.</td></tr>';
    return;
  }
  target.innerHTML = claims.map((claim) => `<tr data-claim="${escapeHtml(claim.id)}" data-clickable="true">
    <td><span class="claim-id">${escapeHtml(claim.id)}</span></td>
    <td><span class="member-cell"><span class="mini-avatar">${escapeHtml(state.patients.find((patient) => patient.id === claim.patient_id)?.initials || "")}</span><span class="member-name">${escapeHtml(claim.patient)}</span></span></td>
    ${includeSignal ? `<td>${escapeHtml(claim.service)}</td><td>${money(claim.charged)}</td><td class="signal-cell">${escapeHtml(claim.signal)}</td>` : `<td>${money(claim.charged)}</td><td><span class="priority-cell"><span class="priority-meter"><i style="width:${claim.priority}%"></i></span>${claim.priority}</span></td>`}
    <td><span class="status-pill ${statusClass(claim.status)}">${escapeHtml(claim.status)}</span></td>
  </tr>`).join("");
}

function renderPriorityClaims() {
  const target = document.getElementById("priority-claims");
  renderClaimTable(state.claims.filter((claim) => claim.status !== "Reviewed").slice(0, 4), target, true);
}

function renderReviewQueue() {
  const query = document.getElementById("claim-search").value.trim().toLowerCase();
  const status = document.getElementById("status-filter").value;
  const filtered = state.claims.filter((claim) => {
    const matchesText = !query || [claim.id, claim.patient, claim.provider, claim.service].join(" ").toLowerCase().includes(query);
    return matchesText && (!status || claim.status === status);
  });
  renderClaimTable(filtered, document.getElementById("review-claims"), false);
  document.getElementById("queue-count").textContent = state.claims.filter((claim) => claim.status !== "Reviewed").length;
  document.getElementById("nav-review-count").textContent = String(state.claims.filter((claim) => claim.status !== "Reviewed").length).padStart(2, "0");
}

function selectClaim(claimId) {
  const claim = state.claims.find((item) => item.id === claimId);
  if (!claim) return;
  state.selectedClaim = claimId;
  const detail = document.getElementById("claim-detail");
  detail.innerHTML = `<div class="detail-header"><div><h2>${escapeHtml(claim.id)}</h2><p>${escapeHtml(claim.date)} · ${escapeHtml(claim.category)}</p></div><span class="priority-badge">Priority ${claim.priority}</span></div>
    <div class="detail-meta">
      <div><span class="meta-label">MEMBER</span><span class="meta-value">${escapeHtml(claim.patient)}</span></div>
      <div><span class="meta-label">STATUS</span><span class="status-pill ${statusClass(claim.status)}">${escapeHtml(claim.status)}</span></div>
      <div><span class="meta-label">PROVIDER</span><span class="meta-value">${escapeHtml(claim.provider)}</span></div>
      <div><span class="meta-label">SERVICE</span><span class="meta-value">${escapeHtml(claim.service)}</span></div>
      <div><span class="meta-label">SUBMITTED</span><span class="meta-value">${money(claim.charged)}</span></div>
      <div><span class="meta-label">ALLOWED</span><span class="meta-value">${money(claim.allowed)}</span></div>
    </div>
    <div class="detail-signal"><h3>Illustrative review signal</h3><p>${escapeHtml(claim.signal)}</p></div>
    <p class="detail-disclaimer">This demo signal is provided for review workflow illustration only. It is not a verified anomaly, finding, or determination of fraud. Human review and supporting evidence are required.</p>`;
}

async function loadDashboard() {
  try {
    const [overview, claims, patients] = await Promise.all([
      getJson("/api/overview"),
      getJson("/api/claims"),
      getJson("/api/patients"),
    ]);
    state.claims = claims;
    state.patients = patients;
    document.getElementById("metric-processed").textContent = overview.claims_processed.toLocaleString("en-US");
    document.getElementById("metric-members").textContent = overview.members_monitored.toLocaleString("en-US");
    document.getElementById("metric-review").textContent = overview.needs_review.toLocaleString("en-US");
    document.getElementById("metric-exposure").textContent = money(overview.potential_exposure);
    document.querySelector(".chart-summary strong").textContent = overview.monthly_claims
      .reduce((total, count) => total + count, 0).toLocaleString("en-US");
    document.getElementById("patient-count-label").textContent = `${patients.length} demo members`;
    drawActivityChart(overview.monthly_claims, overview.monthly_labels);
    drawCategoryChart(overview.categories);
    renderPriorityClaims();
    renderReviewQueue();
    document.getElementById("member-list").innerHTML = patients.map(memberMarkup).join("");
  } catch (error) {
    document.querySelector(".demo-notice p").textContent = `Unable to load demo data: ${error.message}`;
  }
}

document.querySelectorAll("[data-view]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const view = link.dataset.view;
    history.replaceState(null, "", `#${view}`);
    showView(view);
  });
});
document.getElementById("refresh-button").addEventListener("click", loadDashboard);
document.getElementById("patient-search").addEventListener("input", (event) => {
  const query = event.target.value.toLowerCase();
  document.getElementById("member-list").innerHTML = state.patients
    .filter((patient) => patient.name.toLowerCase().includes(query))
    .map(memberMarkup).join("") || '<p class="empty-row">No members match that search.</p>';
});
document.getElementById("claim-search").addEventListener("input", renderReviewQueue);
document.getElementById("status-filter").addEventListener("change", renderReviewQueue);
document.addEventListener("click", (event) => {
  const member = event.target.closest("[data-patient]");
  if (member) selectPatient(member.dataset.patient);
  const claim = event.target.closest("[data-claim]");
  if (claim) {
    if (document.getElementById("view-review").classList.contains("active")) {
      selectClaim(claim.dataset.claim);
    } else {
      history.replaceState(null, "", "#review");
      showView("review");
      selectClaim(claim.dataset.claim);
    }
  }
});
window.addEventListener("resize", () => {
  if (state.claims.length) loadDashboard();
});
loadDashboard().then(() => showView(window.location.hash.slice(1)));
