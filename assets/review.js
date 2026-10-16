(() => {
  "use strict";
  const data = window.GETBROLLS_REVIEW;
  if (!data) return;
  const items = Array.isArray(data.items) ? data.items : [];
  const graphicsRows = Array.isArray(data.graphics) ? data.graphics : [];
  const alignmentRows = Array.isArray(data.alignment) ? data.alignment : [];
  if (!items.length && !graphicsRows.length && !alignmentRows.length) return;
  const key = "getbrolls-v2:" + data.project;
  const graphicsKey = "getbrolls-v2-graphics:" + data.project;
  const alignmentKey = "getbrolls-v2-alignment:" + data.project;
  const STATES = ["pending", "approved", "changes", "rejected", "alternative"];
  const GRAPHICS_STATES = ["pending", "approved", "changes"];
  const GRAPHICS_MAX_COMMENT = 8000;
  const LABELS = {
    pending: "Awaiting decision",
    approved: "Approved",
    changes: "Changes requested",
    rejected: "Rejected",
    alternative: "Different video requested",
  };
  let saved = {};
  let savedGraphics = {};
  let savedAlignment = {};
  let available = true;
  try {
    saved = JSON.parse(localStorage.getItem(key) || "{}");
    if (!saved || typeof saved !== "object") saved = {};
  } catch {
    available = false;
  }
  try {
    savedGraphics = JSON.parse(localStorage.getItem(graphicsKey) || "{}");
    if (!savedGraphics || typeof savedGraphics !== "object") savedGraphics = {};
  } catch {
    available = false;
  }
  try {
    savedAlignment = JSON.parse(localStorage.getItem(alignmentKey) || "{}");
    if (!savedAlignment || typeof savedAlignment !== "object") savedAlignment = {};
  } catch {
    available = false;
  }
  const decisions = {};
  for (const item of items) {
    const old = saved[item.id];
    const prior =
      old &&
      old.signature === item.signature &&
      old.reviewEpoch === item.reviewEpoch &&
      !(old.state === "pending" && !old.updatedAt && item.review?.state !== "pending")
        ? old
        : item.review;
    decisions[item.id] = {
      signature: item.signature,
      reviewEpoch: item.reviewEpoch,
      state: STATES.includes(prior?.state) ? prior.state : "pending",
      comment: typeof prior?.comment === "string" ? prior.comment : "",
      suggestion: typeof prior?.suggestion === "string" ? prior.suggestion : "",
      updatedAt: typeof prior?.updatedAt === "string" ? prior.updatedAt : undefined,
    };
  }
  function graphicsScope(value, fallback) {
    if (value === "shared") return "shared";
    if (value === "scene") return "scene";
    return fallback === "shared" ? "shared" : "scene";
  }
  function matchingRequest(row) {
    return (Array.isArray(row.requests) ? row.requests : []).find(
      (req) => req && req.reviewed_version === row.version,
    );
  }
  const graphicsDecisions = {};
  for (const row of graphicsRows) {
    const old = savedGraphics[row.id];
    const prior =
      old &&
      old.signature === row.signature &&
      old.reviewEpoch === row.reviewEpoch &&
      (!row.requestId || old.requestId === row.requestId) &&
      !(old.state === "pending" && !old.updatedAt && row.state !== "pending")
        ? old
        : row;
    const req = matchingRequest(row);
    graphicsDecisions[row.id] = {
      signature: row.signature,
      reviewEpoch: row.reviewEpoch,
      requestId: row.requestId || null,
      state: GRAPHICS_STATES.includes(prior?.state) ? prior.state : "pending",
      comment: typeof prior?.comment === "string" ? prior.comment : "",
      scope: graphicsScope(prior?.scope, req?.scope || row.scope),
      reference: prior?.reference || row.reference || null,
      references: prior?.references || row.references || null,
      referenceSaved: prior === row ? !!(row.reference || row.references) : prior?.referenceSaved === true,
      updatedAt: typeof prior?.updatedAt === "string" ? prior.updatedAt : undefined,
    };
  }
  const alignmentDecisions = {};
  const referenceFiles = new Map();
  const referencePreviews = new Map();
  const referenceSelectionNote = "References selected, not saved. Describe their use, confirm the request, then Save decisions.";
  let referenceSaving = false;
  function savedReferences(decision) {
    return decision.references || (decision.reference ? [decision.reference] : []);
  }
  function releasePreviews(entries) {
    for (const entry of entries || []) URL.revokeObjectURL(entry.url);
  }
  function referencePreview(panel, row) {
    const box = panel?.querySelector("[data-graphics-reference-preview]");
    if (!box) return;
    box.textContent = "";
    const selected = referenceFiles.get(row.id);
    if (!selected) {
      const input = panel.querySelector("[data-graphics-reference]");
      if (input) input.value = "";
    }
    const decision = graphicsDecisions[row.id];
    const saved = savedReferences(decision);
    const status = panel.querySelector("[data-graphics-status]");
    if (!selected && status?.textContent === referenceSelectionNote) status.textContent = "";
    const shared = panel.querySelector("[data-graphics-shared]");
    if (shared) {
      const localOnly = row.initial === true || !!selected || saved.length > 0;
      shared.disabled = localOnly;
      if (shared.parentElement) shared.parentElement.hidden = localOnly;
      if (localOnly) { shared.checked = false; decision.scope = "scene"; }
    }
    const uploaded = referencePreviews.get(row.id);
    const entries = selected || saved.map(ref => ({ref, url: uploaded?.find(item => item.ref === ref.ref)?.url}));
    entries.forEach((entry, index) => {
      const ref = entry.ref;
      const kind = ref?.kind || entry.kind;
      const item = document.createElement("div");
      const media = document.createElement(kind === "video" ? "video" : "img");
      media.src = entry.url || "/__graphics-reference/" + ref.ref.split("/").pop();
      if (kind === "video") {
        media.controls = true;
        media.preload = "metadata";
        media.onloadedmetadata = () => { media.dataset.previewReady = "true"; };
      } else media.alt = "Image reference " + (ref?.label || entry.label);
      const label = document.createElement("span");
      label.textContent = (ref?.label || entry.label) + " · " + (entry.file?.name || ref.name) +
        (selected ? " · selected, not saved" : decision.referenceSaved ? " · saved in project" : " · uploaded; save the request");
      media.onerror = () => { label.textContent += " · Browser preview unavailable; the original remains available for inspection."; };
      item.append(media, label);
      if (selected) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Remove " + entry.label;
        remove.disabled = referenceSaving;
        remove.onclick = () => {
          if (referenceSaving) return;
          URL.revokeObjectURL(entry.url);
          selected.splice(index, 1);
          const input = panel.querySelector("[data-graphics-reference]");
          if (input) input.value = "";
          if (!selected.length) referenceFiles.delete(row.id);
          referencePreview(panel, row);
        };
        item.append(remove);
      }
      box.append(item);
    });
  }
  async function uploadReferences() {
    const save = window.GETBROLLS_SAVE;
    if (!save?.referenceUrl || !save.token) throw new Error("Open Storyboard through the local server to save references.");
    for (const [id, selected] of referenceFiles) {
      const row = graphicsRows.find(item => item.id === id);
      const decision = graphicsDecisions[id];
      if (!row || decision.state !== "changes" || !decision.comment.trim()) {
        throw new Error("Describe the references' intended use and confirm the request before saving.");
      }
      if (decision.scope !== "scene") throw new Error("Reference requests currently target one scene.");
      const metadata = Object.fromEntries(
        ["id", "project", "scene_id", "occurrence_id", "version", "signature", "reviewEpoch", "initial"].map(key => [key, row[key]])
      );
      const refs = [];
      for (const entry of selected) {
        if (!entry.ref) {
          metadata.name = entry.file.name;
          metadata.kind = entry.kind;
          const response = await fetch(save.referenceUrl, {
            method: "POST",
            headers: { [save.header]: save.token, "X-GetBrolls-Reference": encodeURIComponent(JSON.stringify(metadata)), "Content-Type": "application/octet-stream" },
            body: entry.file,
          });
          const answer = await response.json();
          if (!response.ok) throw new Error(answer.error || "Media upload failed; the draft was preserved.");
          entry.ref = answer.reference;
        }
        if (referenceFiles.get(id) !== selected) throw new Error("The selected references changed during transfer. Save the current draft again.");
        refs.push({...entry.ref, label: entry.label});
      }
      decision.reference = null;
      decision.references = refs;
      decision.referenceSaved = false;
      referencePreviews.set(id, selected.map(entry => ({ref: entry.ref.ref, url: entry.url})));
      referenceFiles.delete(id);
      persist();
    }
    paintGraphics();
  }
  for (const row of alignmentRows) {
    const old = savedAlignment[row.id];
    const prior =
      old && old.signature === row.signature && old.reviewEpoch === row.reviewEpoch ? old : null;
    alignmentDecisions[row.id] = {
      signature: row.signature,
      reviewEpoch: row.reviewEpoch,
      occurrence_id: row.occurrence_id,
      analysis_id: row.analysis_id,
      recording_id: row.recording_id,
      recording_sha256: row.recording_sha256,
      transcript_sha256: row.transcript_sha256,
      scenario_sha256: row.scenario_sha256,
      input_fingerprint: row.input_fingerprint,
      candidate_id: typeof prior?.candidate_id === "string" ? prior.candidate_id : "",
      start_s: prior && prior.start_s != null ? prior.start_s : "",
      end_s: prior && prior.end_s != null ? prior.end_s : "",
      statement: typeof prior?.statement === "string" ? prior.statement : "",
      updatedAt: typeof prior?.updatedAt === "string" ? prior.updatedAt : undefined,
    };
  }
  const select = items.length ? document.querySelector("#select") : null,
    viewer = document.querySelector("#viewer"),
    tools = document.querySelector("#tools"),
    cards = [...document.querySelectorAll(".shot")];
  const current = () => (select ? items[Number(select.value)] : items[0]);
  // Count one saved preview per piece, retaining every version's decision separately.
  const currentGraphics = new Map();
  for (const row of graphicsRows) {
    if (row.current || !currentGraphics.has(row.occurrence_id)) currentGraphics.set(row.occurrence_id, row);
  }
  const reviewTargets = [
    ...items.map((item, index) => ({ decision: decisions[item.id], index })),
    ...[...currentGraphics.values()].map(row => ({ decision: graphicsDecisions[row.id], row })),
  ];
  let pendingIndex = null;
  const graphicsCards = [...document.querySelectorAll(".graphics-card")];
  let graphicsPieceIndex = 0;
  select?.addEventListener("change", () => { pendingIndex = Number(select.value); });
  window.addEventListener("getbrolls:navigate", event => {
    const index = event.detail?.index;
    if (Number.isInteger(index) && index >= 0 && index < items.length) pendingIndex = index;
  });

  // Summary bar: counters, export, print, storage status.
  const summary = document.createElement("div");
  summary.className = "review-summary";
  summary.innerHTML =
    '<p data-summary></p><div class="summary-actions"><button type="button" id="next-pending">Next pending →</button><button type="button" id="export-review" title="Save your decisions to return them to the agent.">Save decisions</button><button type="button" id="print-review">Print / PDF</button></div><span data-storage-status role="status"></span><p class="export-done" role="status" aria-live="polite"></p>';
  document.querySelector(".review-toolbar")?.remove();

  // Gallery: status tag per card, pending filter.
  cards.forEach((card) => {
    const tag = document.createElement("span");
    tag.className = "status-tag";
    card.append(tag);
  });
  const pendingOnly = document.querySelector("#pending-only");

  // Storyboard animation modes: static / hover / on.
  const thumbs = [...document.querySelectorAll("[data-animated-thumb]")];
  const visible = new Set();
  let storyboardMode = "static";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function paintThumb(img) {
    const shot = img.closest(".shot");
    const playing =
      !reduced &&
      (storyboardMode === "on"
        ? visible.has(img)
        : storyboardMode === "hover" && (shot.matches(":hover") || shot === document.activeElement));
    const src = playing ? img.dataset.animatedThumb : img.dataset.still;
    if (img.getAttribute("src") !== src) img.setAttribute("src", src);
  }
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(({ target, isIntersecting }) => {
          if (isIntersecting) visible.add(target);
          else visible.delete(target);
          paintThumb(target);
        });
      },
      { threshold: 0.01 },
    );
    thumbs.forEach((img) => observer.observe(img));
  }
  thumbs.forEach((img) => {
    const shot = img.closest(".shot");
    ["pointerenter", "pointerleave", "focus", "blur"].forEach((event) =>
      shot.addEventListener(event, () => paintThumb(img)),
    );
    paintThumb(img);
  });
  document.querySelectorAll("[data-storyboard-mode]").forEach((button) => {
    button.onclick = () => {
      storyboardMode = button.dataset.storyboardMode;
      document
        .querySelectorAll("[data-storyboard-mode]")
        .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      thumbs.forEach(paintThumb);
    };
  });

  function counts() {
    const all = reviewTargets.map(target => target.decision);
    const n = (s) => all.filter((d) => d.state === s).length;
    return { approved: n("approved"), pending: n("pending"), other: all.length - n("approved") - n("pending") };
  }
  function paintGallery() {
    cards.forEach((card, i) => {
      const d = decisions[items[i].id];
      const tag = card.querySelector(".status-tag");
      if (!tag || !d) return;
      tag.textContent = LABELS[d.state];
      tag.dataset.state = d.state;
      card.hidden = !!pendingOnly?.checked && d.state !== "pending";
    });
    const c = counts();
    const text = `${c.approved} approved · ${c.other} reviewed · ${c.pending} pending`;
    document.querySelectorAll("[data-summary]").forEach((el) => (el.textContent = text));
    const next = document.querySelector("#next-pending");
    if (next) next.disabled = c.pending === 0;
  }
  function persist() {
    try {
      if (items.length) localStorage.setItem(key, JSON.stringify(decisions));
      if (graphicsRows.length) localStorage.setItem(graphicsKey, JSON.stringify(graphicsDecisions));
      if (alignmentRows.length) localStorage.setItem(alignmentKey, JSON.stringify(alignmentDecisions));
    } catch {
      available = false;
    }
    document.querySelectorAll("[data-storage-status]").forEach(
      (el) =>
        (el.textContent = available
          ? "Your choices are stored in this browser. Click “Save decisions” when finished."
          : "This browser cannot store your choices. Click “Save decisions” when finished."),
    );
    paintGallery();
    paintPlayer();
    paintGraphics();
  }
  function paintPlayer() {
    if (!items.length || !viewer) return;
    const box = viewer.querySelector(".presenter .image-box");
    if (!box) return;
    let badge = box.querySelector(".player-status");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "player-status";
      box.append(badge);
    }
    const item = current();
    if (!item) return;
    const d = decisions[item.id];
    badge.textContent = LABELS[d.state];
    badge.dataset.state = d.state;
  }
  function mountPlayer() {
    if (!items.length || !viewer) return;
    const presenter = viewer.querySelector(".presenter");
    if (!presenter) return;
    if (tools && !presenter.contains(tools)) presenter.append(tools);
    const gif = presenter.querySelector("[data-gif]");
    if (gif && !presenter.querySelector(".gif-control")) {
      const control = document.createElement("button");
      control.type = "button";
      control.className = "gif-control";
      const sync = () => {
        const playing = gif.getAttribute("aria-pressed") === "true";
        control.innerHTML = playing
          ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3v14H7zm7 0h3v14h-3z"/></svg>'
          : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7z"/></svg>';
        const label = playing ? "Pause GIF" : "Play GIF";
        control.title = label;
        control.setAttribute("aria-label", label);
      };
      control.onclick = () => {
        gif.click();
        sync();
      };
      gif.addEventListener("click", sync);
      presenter.querySelector(".image-box").append(control);
      sync();
    }
    paintPlayer();
  }
  function mountPanel() {
    if (!items.length || !viewer) return;
    const panel = viewer.querySelector(".review-panel");
    if (!panel || panel.dataset.mounted) return;
    panel.dataset.mounted = "1";
    const material = viewer.querySelector(".material");
    if (material && !material.contains(summary)) material.prepend(summary);
    const item = current(),
      d = decisions[item.id];
    const comment = panel.querySelector("[data-comment]"),
      suggestion = panel.querySelector("[data-suggestion]"),
      status = panel.querySelector("[data-review-status]"),
      fields = panel.querySelector(".review-fields"),
      toggle = panel.querySelector(".comment-toggle"),
      wantOther = panel.querySelector(".want-other"),
      alternative = panel.querySelector("[data-alternative]"),
      other = panel.querySelector(".other-url"),
      confirm = panel.querySelector(".confirm-review");
    let pending = null;
    comment.value = d.comment;
    suggestion.value = d.suggestion;
    alternative.checked = d.state === "alternative";
    // "Outra fonte" virou esta caixinha: mesmo valor exportado, um botão a menos.
    const wanted = () => (alternative.checked ? "alternative" : "changes");
    function reveal(open, asking = false) {
      fields.hidden = !open;
      wantOther.hidden = !asking;
      other.hidden = !(asking && alternative.checked);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Close comment" : comment.value ? "View comment" : "Comment";
    }
    function checkComment() {
      // Validação na hora: o bloqueio aparece onde a pessoa escreve, não no fim —
      // inclusive quando ela apaga o comentário de um pedido de ajuste já confirmado.
      if (!pending && !["changes", "alternative"].includes(d.state)) return;
      const empty = !comment.value.trim();
      confirm.disabled = empty;
      confirm.textContent =
        wanted() === "changes" ? "Confirm change request" : "Confirm: find a different video";
      if (empty) status.textContent = "Describe what you want in one line.";
      else if (pending) status.textContent = "";
      else paint();
    }
    function paint() {
      panel.querySelectorAll("[data-decision]").forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(
            b.dataset.decision === d.state ||
              (b.dataset.decision === "changes" && d.state === "alternative"),
          ),
        ),
      );
      status.textContent = d.state === "pending" ? "" : LABELS[d.state] + (d.updatedAt ? " · saved in this browser" : "");
    }
    toggle.onclick = () => {
      pending = null;
      confirm.hidden = true;
      reveal(fields.hidden, ["changes", "alternative"].includes(d.state));
      if (!fields.hidden) comment.focus();
    };
    alternative.onchange = () => {
      other.hidden = !alternative.checked;
      checkComment();
    };
    panel.querySelectorAll("[data-decision]").forEach((b) => {
      b.onclick = () => {
        const state = b.dataset.decision;
        if (state === d.state || (state === "changes" && d.state === "alternative")) {
          // Clicking the active decision undoes it.
          d.state = "pending";
          d.updatedAt = new Date().toISOString();
          pending = null;
          confirm.hidden = true;
          reveal(false);
          paint();
          persist();
          return;
        }
        if (state === "changes") {
          pending = state;
          reveal(true, true);
          confirm.hidden = false;
          checkComment();
          comment.focus();
          return;
        }
        pending = null;
        confirm.hidden = true;
        reveal(false);
        d.state = state;
        d.updatedAt = new Date().toISOString();
        paint();
        persist();
      };
    });
    confirm.onclick = () => {
      if (!comment.value.trim()) {
        status.textContent = "Describe what you want in one line.";
        comment.focus();
        return;
      }
      d.state = wanted();
      d.updatedAt = new Date().toISOString();
      pending = null;
      confirm.hidden = true;
      reveal(false);
      paint();
      persist();
    };
    comment.oninput = () => {
      d.comment = comment.value;
      checkComment();
      persist();
    };
    suggestion.oninput = () => {
      d.suggestion = suggestion.value;
      persist();
    };
    reveal(false, ["changes", "alternative"].includes(d.state));
    paint();
    wireSummary();
  }
  function placeSummary() {
    const material = viewer && viewer.querySelector(".material");
    if (material && !material.contains(summary)) material.prepend(summary);
    if (material || items.length) return;
    const host = document.querySelector(".graphics-board") || document.querySelector("main");
    if (host && !host.contains(summary)) host.prepend(summary);
  }
  function goToPendingGraphics(pendingRow) {
    const pieceIndex = graphicsCards.findIndex(card => card.dataset.occurrence === pendingRow.occurrence_id);
    const card = graphicsCards[pieceIndex];
    if (!card) return false;
    showGraphicsPiece(pieceIndex);
    const display = card.querySelector("[data-graphics-display]");
    if (display && display.value !== pendingRow.version) {
      display.value = pendingRow.version;
      display.dispatchEvent(new Event("change"));
    }
    const destination = items.length ? card : document.querySelector(".graphics-board") || card;
    destination.scrollIntoView?.({ block: "start" });
    return true;
  }
  function showGraphicsPiece(index, track = true) {
    graphicsPieceIndex = Math.max(0, Math.min(index, graphicsCards.length - 1));
    graphicsCards.forEach((card, i) => {
      card.classList.toggle("is-active-piece", i === graphicsPieceIndex);
      if (i !== graphicsPieceIndex) {
        [...card.querySelectorAll("video"), ...card.querySelectorAll("audio")].forEach(pauseMedia);
      }
    });
    const piece = document.querySelector("[data-graphics-piece]");
    if (piece) piece.value = String(graphicsPieceIndex);
    const previous = document.querySelector("[data-graphics-prev]");
    const next = document.querySelector("[data-graphics-next]");
    const position = document.querySelector("[data-graphics-position]");
    if (previous) previous.disabled = graphicsPieceIndex === 0;
    if (next) next.disabled = graphicsPieceIndex === graphicsCards.length - 1;
    if (position) position.textContent = `${graphicsPieceIndex + 1} / ${graphicsCards.length}`;
    if (track) {
      const occurrence = graphicsCards[graphicsPieceIndex]?.dataset.occurrence;
      const target = reviewTargets.findIndex(target => target.row?.occurrence_id === occurrence);
      if (target >= 0) pendingIndex = target;
    }
  }
  function bindGraphicsNavigation() {
    const navigation = document.querySelector(".graphics-navigation");
    if (!navigation || navigation.dataset.wired || !graphicsCards.length) return;
    const piece = navigation.querySelector("[data-graphics-piece]");
    if (!piece) return;
    graphicsCards.forEach((card, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${index + 1}. ${card.querySelector("h3")?.firstChild?.textContent.trim() || "Graphics piece"}`;
      piece.append(option);
    });
    piece.onchange = () => showGraphicsPiece(Number(piece.value));
    navigation.querySelector("[data-graphics-prev]").onclick = () => showGraphicsPiece(graphicsPieceIndex - 1);
    navigation.querySelector("[data-graphics-next]").onclick = () => showGraphicsPiece(graphicsPieceIndex + 1);
    navigation.dataset.wired = "1";
    navigation.hidden = graphicsCards.length <= 1;
    document.querySelector(".graphics-board")?.classList.add("is-paged");
    showGraphicsPiece(0, !items.length);
  }
  function wireSummary() {
    const next = document.querySelector("#next-pending");
    if (next && !next.dataset.wired) {
      next.dataset.wired = "1";
      next.onclick = () => {
        const n = reviewTargets.length;
        const start = pendingIndex ?? (select ? Number(select.value) : -1);
        for (let step = 1; step <= n; step++) {
          const i = (start + step) % n;
          const target = reviewTargets[i];
          if (target.decision.state !== "pending") continue;
          if (target.row) {
            if (!goToPendingGraphics(target.row)) continue;
          } else {
            window.getbrollsGo?.(target.index);
          }
          pendingIndex = i;
          return;
        }
      };
    }
    const exportButton = document.querySelector("#export-review");
    if (exportButton && !exportButton.dataset.wired) {
      exportButton.dataset.wired = "1";
      exportButton.onclick = exportReview;
    }
    const printButton = document.querySelector("#print-review");
    if (printButton && !printButton.dataset.wired) {
      printButton.dataset.wired = "1";
      printButton.onclick = async () => {
        printButton.disabled = true;
        try {
          const section = buildPrintNotes();
          await Promise.all([...section.querySelectorAll("img")].map((img) => img.decode().catch(() => {})));
          window.print();
        } finally {
          printButton.disabled = false;
        }
      };
    }
  }
  function graphicsRowByVersion(occurrence, versionId) {
    return graphicsRows.find((row) => row.occurrence_id === occurrence && row.version === versionId);
  }
  function graphicsVersionLabel(row, versionId) {
    const saved = Array.isArray(row.versions) ? row.versions.filter(version => version.status === "complete") : [];
    const index = saved.findIndex(version => version.id === versionId);
    return index >= 0 ? `v${index + 1}` : (versionId || "unknown");
  }
  function canApprove(row) {
    return !!(row && row.readiness && row.readiness.reviewable);
  }
  function readinessText(row) {
    const r = row.readiness || {};
    const parts = [
      r.reviewable ? "reviewable" : "not reviewable",
      r.approved ? "currently approved for this version" : "not currently approved",
      r.deliverable ? "deliverable" : "not deliverable",
    ];
    const reasons = Array.isArray(r.reasons) && r.reasons.length ? " (" + r.reasons.join(", ") + ")" : "";
    const hist =
      row.approval === "approved"
        ? " Historical approval is recorded for this version and is not current delivery readiness."
        : "";
    return "Readiness: " + parts.join(" · ") + reasons + hist;
  }
  function requestText(row) {
    const reqs = Array.isArray(row.requests) ? row.requests : [];
    if (!reqs.length) return "No saved revision request for this occurrence.";
    return reqs
      .map((req) => {
        const stale =
          req.state === "stale" || req.reason
            ? " · " + (req.reason || "stale or ambiguous older target")
            : "";
        const outcome =
          req.processing && req.processing.outcome ? " · outcome " + req.processing.outcome : "";
        return (
          "Request " +
          (req.id || "") +
          " target " +
          graphicsVersionLabel(row, req.reviewed_version) +
          " · " +
          (req.state || "") +
          " · scope " +
          (req.scope || "scene") +
          stale +
          outcome
        );
      })
      .join("\n");
  }
  function frozenContextText(row) {
    const ctx = row.context || {};
    const timing = ctx.timing || {};
    const anchors = Array.isArray(ctx.anchors) ? ctx.anchors : [];
    const timingLine =
      timing.basis === "explicit"
        ? `Explicit ${timing.start_s}–${timing.end_s} s (frames ${timing.start_frame}–${timing.end_frame}) · Duration ${timing.duration_s} s · ${timing.duration_in_frames} frames`
        : timing.basis === "estimated"
          ? `Estimated duration ${timing.duration_s} s · ${timing.duration_in_frames} frames`
          : "";
    return {
      chapter: ctx.chapter_context || "",
      narration: ctx.narration || "",
      purpose: ctx.purpose || "",
      timing: timingLine,
      anchors: anchors
        .map((item) => (item && typeof item === "object" ? (item.t_s == null ? item.text : item.t_s + " s " + item.text) : item))
        .filter(Boolean)
        .join("\n"),
    };
  }
  function mediaFps(el) {
    const raw = el && (el.dataset?.fps || (typeof el.getAttribute === "function" && el.getAttribute("data-fps")));
    const fps = Number(raw || 30);
    return fps > 0 ? fps : 30;
  }
  function syncAudioToVideo(video, audio) {
    if (!video || !audio) return;
    const slop = 1 / mediaFps(audio) || 1 / mediaFps(video);
    const videoTime = Number(video.currentTime || 0);
    const audioTime = Number(audio.currentTime || 0);
    if (Math.abs(audioTime - videoTime) > slop) audio.currentTime = videoTime;
  }
  function pauseMedia(el) {
    if (!el) return;
    if (typeof el.pause === "function") el.pause();
  }
  function playMedia(el) {
    if (!el || typeof el.play !== "function") return;
    const result = el.play();
    if (result && typeof result.catch === "function") result.catch(() => {});
  }
  function pauseAlignmentPreviews(except) {
    document.querySelectorAll(".graphics-alignment-preview").forEach((el) => {
      if (el !== except) pauseMedia(el);
    });
  }
  function pauseGraphicsAndAlignment(except) {
    document.querySelectorAll(".graphics-preview, .graphics-vo-preview, .graphics-alignment-preview").forEach((el) => {
      if (el !== except) pauseMedia(el);
    });
  }
  function bindAlignmentPreviews(root) {
    root.querySelectorAll(".graphics-alignment-preview").forEach((audio) => {
      if (audio.dataset.alignmentWired) return;
      audio.dataset.alignmentWired = "1";
      audio.addEventListener("play", () => pauseGraphicsAndAlignment(audio));
    });
  }
  function alignmentRowFor(occurrence) {
    return alignmentRows.find((row) => row.occurrence_id === occurrence) || null;
  }
  function disableAlignmentForm(box, message) {
    box.querySelectorAll("input, textarea, button").forEach((el) => {
      el.disabled = true;
    });
    const status = box.querySelector("[data-alignment-status]");
    if (status) status.textContent = message;
  }
  function bindAlignmentForm(box) {
    if (!box || box.dataset.alignmentMounted) return;
    box.dataset.alignmentMounted = "1";
    const rowId = box.dataset.alignmentId;
    const signature = box.dataset.alignmentSignature;
    const epoch = box.dataset.alignmentEpoch;
    const editable = box.dataset.alignmentEditable !== "0";
    const row = alignmentRows.find((item) => item.id === rowId) || null;
    const live = !!(row && row.signature === signature && row.reviewEpoch === epoch);
    if (!editable || !row || !live) {
      disableAlignmentForm(
        box,
        live
          ? "This saved version keeps its original alignment context. Record a correction on the current assignment."
          : "Stale alignment context; this form will not retarget the current occurrence.",
      );
      return;
    }
    const decision = alignmentDecisions[row.id];
    const candidate = box.querySelector("[data-alignment-candidate]");
    const start = box.querySelector("[data-alignment-start]");
    const end = box.querySelector("[data-alignment-end]");
    const statement = box.querySelector("[data-alignment-statement]");
    const status = box.querySelector("[data-alignment-status]");
    const recordBtn = box.querySelector("[data-alignment-record]");
    if (candidate) candidate.value = decision.candidate_id || "";
    if (start) start.value = decision.start_s === "" || decision.start_s == null ? "" : String(decision.start_s);
    if (end) end.value = decision.end_s === "" || decision.end_s == null ? "" : String(decision.end_s);
    if (statement) statement.value = decision.statement || "";
    function note(text) {
      if (status) status.textContent = text;
    }
    recordBtn &&
      (recordBtn.onclick = () => {
        if (box.dataset.alignmentSignature !== row.signature || box.dataset.alignmentEpoch !== row.reviewEpoch) {
          note("Stale alignment context; this form will not retarget the current occurrence.");
          return;
        }
        const cand = (candidate?.value || "").trim();
        const startRaw = (start?.value || "").trim();
        const endRaw = (end?.value || "").trim();
        const text = statement?.value || "";
        if (text.length > GRAPHICS_MAX_COMMENT) {
          note("Keep the correction statement within 8000 characters.");
          return;
        }
        if (!text.trim()) {
          note("A correction needs the exact human statement already received.");
          return;
        }
        if (cand && (startRaw || endRaw)) {
          note("Use a candidate id or start/end seconds, not both.");
          return;
        }
        if (!cand && (!startRaw || !endRaw)) {
          note("Choose a candidate id or both start and end seconds.");
          return;
        }
        if (!cand) {
          const startN = Number(startRaw);
          const endN = Number(endRaw);
          if (!Number.isFinite(startN) || !Number.isFinite(endN) || endN <= startN || startN < 0) {
            note("Start and end must be finite seconds with end after start.");
            return;
          }
          decision.start_s = startN;
          decision.end_s = endN;
          decision.candidate_id = "";
        } else {
          decision.candidate_id = cand;
          decision.start_s = "";
          decision.end_s = "";
        }
        decision.statement = text;
        decision.signature = row.signature;
        decision.reviewEpoch = row.reviewEpoch;
        decision.updatedAt = new Date().toISOString();
        note("Correction stored for Save decisions. It does not transcribe or rewrite a frozen version.");
        persist();
      });
  }
  function bindAlignmentCard(card) {
    bindAlignmentPreviews(card);
    card.querySelectorAll(".graphics-alignment-correct").forEach((box) => bindAlignmentForm(box));
  }
  function bindGraphicsMedia(pane) {
    const video = pane.querySelector(".graphics-preview");
    const audio = pane.querySelector(".graphics-vo-preview");
    if (!video || video.dataset.graphicsMediaWired) return;
    video.dataset.graphicsMediaWired = "1";
    let syncing = false;
    function pair() {
      return pane.querySelector(".graphics-vo-preview");
    }
    function withSync(fn) {
      if (syncing) return;
      syncing = true;
      try {
        fn();
      } finally {
        syncing = false;
      }
    }
    function onPlay() {
      withSync(() => {
        pauseAlignmentPreviews();
        const other = pair();
        syncAudioToVideo(video, other);
        playMedia(other);
      });
    }
    function onPause() {
      withSync(() => {
        const other = pair();
        syncAudioToVideo(video, other);
        pauseMedia(other);
      });
    }
    function onSeek() {
      withSync(() => syncAudioToVideo(video, pair()));
    }
    function onEnded() {
      withSync(() => {
        const other = pair();
        pauseMedia(other);
        syncAudioToVideo(video, other);
      });
    }
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("seeking", onSeek);
    video.addEventListener("seeked", onSeek);
    video.addEventListener("ended", onEnded);
    if (audio) {
      audio.addEventListener("play", () =>
        withSync(() => {
          pauseAlignmentPreviews();
          syncAudioToVideo(video, audio);
          playMedia(video);
        }),
      );
      audio.addEventListener("pause", () =>
        withSync(() => {
          syncAudioToVideo(video, audio);
          pauseMedia(video);
        }),
      );
      audio.addEventListener("seeking", () => withSync(() => syncAudioToVideo(video, audio)));
      audio.addEventListener("seeked", () => withSync(() => syncAudioToVideo(video, audio)));
      audio.addEventListener("ended", () =>
        withSync(() => {
          pauseMedia(video);
          syncAudioToVideo(video, audio);
        }),
      );
    }
    if (audio && !pane.querySelector("[data-graphics-media-toggles]")) {
      const box = document.createElement("p");
      box.className = "graphics-media-toggles";
      box.setAttribute("data-graphics-media-toggles", "");
      const label = document.createElement("label");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.setAttribute("data-graphics-mute-vo", "");
      label.append(check, document.createTextNode(" Mute VO preview"));
      box.append(label);
      check.onchange = () => {
        audio.muted = check.checked;
      };
      video.insertAdjacentElement?.("afterend", box) || pane.append(box);
    }
  }
  function syncShownGraphicsMedia(card, displayId) {
    card.querySelectorAll(".graphics-version").forEach((pane) => {
      bindGraphicsMedia(pane);
      const video = pane.querySelector(".graphics-preview");
      const audio = pane.querySelector(".graphics-vo-preview");
      const shown = pane.dataset.version === displayId;
      if (!shown) {
        pauseMedia(video);
        pauseMedia(audio);
        pane.querySelectorAll(".graphics-alignment-preview").forEach((el) => pauseMedia(el));
        return;
      }
      syncAudioToVideo(video, audio);
    });
  }
  function paintVersionPanes(card, displayId, compareId) {
    card.querySelectorAll(".graphics-version").forEach((pane) => {
      const id = pane.dataset.version;
      pane.classList.toggle("is-shown", id === displayId);
      pane.classList.toggle("is-compare", Boolean(compareId) && id === compareId && id !== displayId);
      const decision = graphicsDecisions[pane.dataset.rowId];
      const record = pane.querySelector("[data-graphics-decision-record]");
      if (record && decision) {
        record.textContent =
          LABELS[decision.state] +
          (decision.state === "changes" && decision.scope === "shared" ? " · scope shared" : "") +
          (decision.comment ? " · " + decision.comment : "");
        record.hidden = decision.state === "pending";
      }
    });
    card.querySelectorAll(".graphics-version-details").forEach((pane) => {
      const id = pane.dataset.version;
      pane.classList.toggle("is-shown", id === displayId);
      pane.classList.toggle("is-compare", Boolean(compareId) && id === compareId && id !== displayId);
      if (id !== displayId && id !== compareId) {
        pane.querySelectorAll(".graphics-alignment-preview").forEach((el) => pauseMedia(el));
      }
    });
    syncShownGraphicsMedia(card, displayId);
  }
  function bindGraphicsCard(card) {
    card.classList.add("is-wired");
    const display = card.querySelector("[data-graphics-display]");
    const compare = card.querySelector("[data-graphics-compare]");
    const panel = card.querySelector(".graphics-review-panel");
    const occurrence = card.dataset.occurrence;
    const rows = graphicsRows.filter((row) => row.occurrence_id === occurrence);
    if (!rows.length) return;
    let boundId = (rows.find((row) => row.version === display?.value) || rows.find((row) => row.current) || rows[0]).id;
    let pending = null;
    function selectedRow() {
      return graphicsRows.find((row) => row.id === boundId) || rows[0];
    }
    function resetTransientAction() {
      pending = null;
      if (!panel) return;
      panel.dataset.asking = "";
      const confirmBtn = panel.querySelector(".confirm-review");
      if (confirmBtn) {
        confirmBtn.hidden = true;
        confirmBtn.disabled = true;
      }
      const fields = panel.querySelector(".review-fields");
      const toggle = panel.querySelector(".comment-toggle");
      const comment = panel.querySelector("[data-graphics-comment]");
      if (fields) fields.hidden = true;
      toggle?.setAttribute("aria-expanded", "false");
      if (toggle) toggle.textContent = comment?.value ? "View comment" : "Comment";
    }
    function showSelected() {
      const row = selectedRow();
      paintVersionPanes(card, row.version, compare?.value);
      const voiceStatus = card.querySelector(".graphics-vo-status");
      if (voiceStatus) {
        const shownPane = [...card.querySelectorAll(".graphics-version")].find(pane => pane.dataset.version === row.version);
        voiceStatus.hidden = !!shownPane?.querySelector(".graphics-vo-preview");
      }
      const badge = card.querySelector(".timing-basis");
      if (badge) {
        const basis =
          (row.context && row.context.timing && row.context.timing.basis) || row.timing_basis || "";
        badge.className = "timing-basis" + (basis ? " " + basis : "");
        badge.hidden = basis !== "estimated";
        badge.textContent = basis === "estimated" ? "Draft · VO timing pending" : "";
      }
      const compareRow = graphicsRowByVersion(occurrence, compare?.value);
      let box = card.querySelector("[data-graphics-compare-context]");
      if (!box) {
        box = document.createElement("p");
        box.className = "graphics-compare-context";
        box.setAttribute("data-graphics-compare-context", "");
        (card.querySelector(".graphics-details") || card).append(box);
      }
      const shown = frozenContextText(row);
      const other = compareRow ? frozenContextText(compareRow) : null;
      box.hidden = !other;
      box.textContent = other
        ? `Displayed ${graphicsVersionLabel(row, row.version)} narration: ${shown.narration} · timing: ${shown.timing} · Compare ${graphicsVersionLabel(compareRow, compareRow.version)} narration: ${other.narration} · timing: ${other.timing}`
        : `Displayed ${graphicsVersionLabel(row, row.version)} narration: ${shown.narration} · timing: ${shown.timing}`;
      if (!panel) return;
      const d = graphicsDecisions[boundId];
      const comment = panel.querySelector("[data-graphics-comment]");
      const shared = panel.querySelector("[data-graphics-shared]");
      const status = panel.querySelector("[data-graphics-status]");
      const readiness = panel.querySelector("[data-graphics-readiness]");
      const requests = panel.querySelector("[data-graphics-requests]");
      if (comment) comment.value = d.comment;
      if (shared) shared.checked = d.scope === "shared";
      if (readiness) readiness.textContent = readinessText(row);
      if (requests) requests.textContent = requestText(row);
      panel.querySelectorAll("[data-graphics-decision]").forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.graphicsDecision === d.state)),
      );
      const approve = panel.querySelector('[data-graphics-decision="approved"]');
      if (approve) approve.disabled = !canApprove(row);
      if (approve) approve.hidden = row.initial === true;
      const change = panel.querySelector('[data-graphics-decision="changes"]');
      if (change) change.textContent = row.initial ? "Prepare first version" : "Needs changes";
      referencePreview(panel, row);
      if (status && !panel.dataset.asking) status.textContent = "";
    }
    function rebind() {
      const next = graphicsRowByVersion(occurrence, display?.value) || rows.find((row) => row.current) || rows[0];
      boundId = next.id;
      const imageInput = panel?.querySelector("[data-graphics-reference]");
      if (imageInput) imageInput.value = "";
      if (compare && compare.value === display?.value) compare.value = "";
      resetTransientAction();
      showSelected();
      resetTransientAction();
    }
    if (display && !display.dataset.wired) {
      display.dataset.wired = "1";
      display.onchange = rebind;
    }
    if (compare && !compare.dataset.wired) {
      compare.dataset.wired = "1";
      compare.onchange = () => showSelected();
    }
    if (!panel || panel.dataset.mounted) {
      showSelected();
      return;
    }
    panel.dataset.mounted = "1";
    const comment = panel.querySelector("[data-graphics-comment]");
    const shared = panel.querySelector("[data-graphics-shared]");
    const status = panel.querySelector("[data-graphics-status]");
    const fields = panel.querySelector(".review-fields");
    const toggle = panel.querySelector(".comment-toggle");
    const confirm = panel.querySelector(".confirm-review");
    const imageInput = panel.querySelector("[data-graphics-reference]");
    if (imageInput) {
      imageInput.disabled = !window.GETBROLLS_SAVE?.referenceUrl;
      imageInput.title = "Up to 8 PNG/JPEG or MP4/H.264 references; 128 MiB total; local server required.";
      imageInput.onchange = () => {
        if (referenceSaving) return;
        const files = Array.from(imageInput.files || []);
        if (!files.length) return;
        if (files.length > 8 || files.reduce((sum, file) => sum + file.size, 0) > 134217728) {
          status.textContent = "Choose at most 8 references and 128 MiB in total.";
          return;
        }
        const entries = files.map((file, index) => ({file, label: "R" + (index + 1), kind: /\.mp4$/i.test(file.name) || file.type === "video/mp4" ? "video" : "image"}));
        if (entries.some(entry => entry.file.size > (entry.kind === "video" ? 67108864 : 16777216))) {
          status.textContent = "Each PNG/JPEG may be at most 16 MiB; each MP4/H.264 at most 64 MiB.";
          return;
        }
        releasePreviews(referenceFiles.get(boundId));
        releasePreviews(referencePreviews.get(boundId));
        referencePreviews.delete(boundId);
        referenceFiles.set(boundId, entries.map(entry => ({...entry, url: URL.createObjectURL(entry.file)})));
        graphicsDecisions[boundId].referenceSaved = false;
        referencePreview(panel, selectedRow());
        status.textContent = referenceSelectionNote;
      };
    }
    function reveal(open) {
      if (fields) fields.hidden = !open;
      toggle?.setAttribute("aria-expanded", String(open));
      if (toggle) toggle.textContent = open ? "Close comment" : comment?.value ? "View comment" : "Comment";
    }
    function checkComment() {
      const d = graphicsDecisions[boundId];
      if (!pending && d.state !== "changes") return;
      const text = (comment?.value || "").trim();
      const tooLong = (comment?.value || "").length > GRAPHICS_MAX_COMMENT;
      if (confirm) {
        confirm.disabled = !text || tooLong;
        confirm.textContent = "Confirm change request";
      }
      if (!text) status.textContent = "Describe what you want in one line.";
      else if (tooLong) status.textContent = "Keep the comment within 8000 characters.";
      else if (pending) status.textContent = "";
    }
    toggle &&
      (toggle.onclick = () => {
        pending = null;
        panel.dataset.asking = "";
        if (confirm) confirm.hidden = true;
        reveal(fields?.hidden);
        if (!fields?.hidden) comment?.focus();
      });
    panel.querySelectorAll("[data-graphics-decision]").forEach((b) => {
      b.onclick = () => {
        const d = graphicsDecisions[boundId];
        const row = selectedRow();
        const state = b.dataset.graphicsDecision;
        if (state === d.state) {
          d.state = "pending";
          d.updatedAt = new Date().toISOString();
          pending = null;
          panel.dataset.asking = "";
          if (confirm) confirm.hidden = true;
          reveal(false);
          persist();
          showSelected();
          return;
        }
        if (state === "changes") {
          pending = state;
          panel.dataset.asking = "1";
          reveal(true);
          if (confirm) confirm.hidden = false;
          checkComment();
          comment?.focus();
          return;
        }
        if (state === "approved" && !canApprove(row)) {
          status.textContent =
            "This version cannot be approved. Pending or failed assignments and incomplete results stay unapproved.";
          return;
        }
        pending = null;
        panel.dataset.asking = "";
        if (confirm) confirm.hidden = true;
        reveal(false);
        d.state = state;
        d.updatedAt = new Date().toISOString();
        persist();
        showSelected();
      };
    });
    confirm &&
      (confirm.onclick = () => {
        if (!pending) return;
        const d = graphicsDecisions[boundId];
        const text = (comment?.value || "").trim();
        if (!text) {
          status.textContent = "Describe what you want in one line.";
          comment?.focus();
          return;
        }
        if ((comment?.value || "").length > GRAPHICS_MAX_COMMENT) {
          status.textContent = "Keep the comment within 8000 characters.";
          comment?.focus();
          return;
        }
        d.comment = comment.value;
        d.scope = shared?.checked ? "shared" : "scene";
        d.state = "changes";
        d.updatedAt = new Date().toISOString();
        pending = null;
        panel.dataset.asking = "";
        confirm.hidden = true;
        reveal(false);
        persist();
        showSelected();
      });
    comment &&
      (comment.oninput = () => {
        graphicsDecisions[boundId].comment = comment.value;
        checkComment();
        persist();
      });
    shared &&
      (shared.onchange = () => {
        graphicsDecisions[boundId].scope = shared.checked ? "shared" : "scene";
        persist();
      });
    reveal(false);
    showSelected();
  }
  function paintGraphics() {
    document.querySelectorAll(".graphics-card").forEach((card) => {
      const display = card.querySelector("[data-graphics-display]");
      const compare = card.querySelector("[data-graphics-compare]");
      if (display) paintVersionPanes(card, display.value, compare?.value);
      const row = graphicsRowByVersion(card.dataset.occurrence, display?.value) ||
        graphicsRows.find(item => item.occurrence_id === card.dataset.occurrence && item.current);
      if (row) referencePreview(card.querySelector(".graphics-review-panel"), row);
    });
  }
  function mountGraphics() {
    document.querySelectorAll(".graphics-card").forEach((card) => {
      bindGraphicsCard(card);
      bindAlignmentCard(card);
    });
  }
  function mount() {
    placeSummary();
    mountPlayer();
    mountPanel();
    mountGraphics();
    bindGraphicsNavigation();
    wireSummary();
  }
  if (viewer) new MutationObserver(mount).observe(viewer, { childList: true });
  if (pendingOnly) pendingOnly.onchange = paintGallery;
  mount();
  persist();

  function exportRequestId(row, decision) {
    if (decision.state !== "changes" || !(decision.comment || "").trim()) return null;
    const scope = decision.scope === "shared" ? "shared" : "scene";
    const same =
      (row.comment || "") === decision.comment &&
      graphicsScope(row.scope, "scene") === scope &&
      row.state === "changes" &&
      typeof row.requestId === "string" &&
      row.requestId;
    return same ? row.requestId : null;
  }
  function exportAlignmentRow(row) {
    const decision = alignmentDecisions[row.id];
    const payload = {
      ...row,
      signature: row.signature,
      reviewEpoch: row.reviewEpoch,
      occurrence_id: row.occurrence_id,
      analysis_id: row.analysis_id,
      recording_id: row.recording_id,
      recording_sha256: row.recording_sha256,
      recording_duration_s: row.recording_duration_s,
      transcript_sha256: row.transcript_sha256,
      scenario_sha256: row.scenario_sha256,
      input_fingerprint: row.input_fingerprint,
      order: row.order,
      fps: row.fps,
      statement: decision?.statement || row.statement || "",
      by: decision?.by || row.by || "",
    };
    if (decision?.candidate_id) payload.candidate_id = decision.candidate_id;
    if (decision && decision.start_s !== "" && decision.start_s != null) payload.start_s = decision.start_s;
    if (decision && decision.end_s !== "" && decision.end_s != null) payload.end_s = decision.end_s;
    return payload;
  }
  function exportGraphicsRow(row) {
    const decision = graphicsDecisions[row.id];
    const scope = decision.scope === "shared" ? "shared" : "scene";
    const payload = {
      ...row,
      signature: row.signature,
      reviewEpoch: row.reviewEpoch,
      state: decision.state,
      comment: decision.comment,
      scope: decision.state === "changes" && scope === "shared" ? "shared" : "scene",
      requestId: exportRequestId(row, decision),
    };
    delete payload.reference;
    delete payload.references;
    if (decision.state === "changes" && decision.reference) payload.reference = decision.reference;
    if (decision.state === "changes" && decision.references) payload.references = decision.references;
    return payload;
  }
  function exportReview() {
    const note = (text) =>
      document.querySelectorAll("[data-storage-status]").forEach((el) => (el.textContent = text));
    if (referenceSaving) return;
    if (referenceFiles.size) {
      referenceSaving = true;
      note("Uploading references to the project…");
      uploadReferences().then(() => {
        referenceSaving = false;
        exportReview();
      }).catch(error => {
        referenceSaving = false;
        note(error.message || "Reference transfer failed; the draft is preserved.");
      });
      return;
    }
    for (const d of Object.values(decisions)) {
      if (["changes", "alternative"].includes(d.state) && !d.comment.trim()) {
        note("A change request needs a comment. Open that clip and describe the changes.");
        return;
      }
      if (d.suggestion) {
        let valid = false;
        try {
          const u = new URL(d.suggestion);
          valid =
            u.protocol === "https:" &&
            !u.username &&
            !u.password &&
            ![...u.searchParams.keys()].some((k) =>
              /^(key|api_key|apikey|token|access_token|authorization|signature|sig)$|^x-amz-|^x-goog-/i.test(k),
            ) &&
            u.hostname.includes(".") &&
            u.hostname !== "localhost" &&
            !u.hostname.endsWith(".local") &&
            !/^\d+\.\d+\.\d+\.\d+$/.test(u.hostname);
        } catch {}
        if (!valid) {
          note("Use a public HTTPS link without credentials or access tokens. Correct or remove the link.");
          return;
        }
      }
    }
    for (const row of graphicsRows) {
      const d = graphicsDecisions[row.id];
      if (d.state === "changes" && !(d.comment || "").trim()) {
        note("A graphics change request needs a comment. Open that version and describe the changes.");
        return;
      }
      if ((d.comment || "").length > GRAPHICS_MAX_COMMENT) {
        note("A graphics comment must stay within 8000 characters.");
        return;
      }
    }
    const result = {
      ...data,
      exportedAt: new Date().toISOString(),
      items: items.map((i) => ({ ...i, ...decisions[i.id] })),
    };
    if (Array.isArray(data.graphics) || graphicsRows.length) {
      result.graphics = graphicsRows.map(exportGraphicsRow);
    }
    if (Array.isArray(data.alignment) || alignmentRows.length) {
      for (const row of alignmentRows) {
        const d = alignmentDecisions[row.id];
        if (d && (d.candidate_id || (d.start_s !== "" && d.end_s !== "")) && !(d.statement || "").trim()) {
          note("An alignment correction needs the exact human statement already received.");
          return;
        }
        if ((d?.statement || "").length > GRAPHICS_MAX_COMMENT) {
          note("An alignment statement must stay within 8000 characters.");
          return;
        }
      }
      result.alignment = alignmentRows.map(exportAlignmentRow);
    }
    const save = window.GETBROLLS_SAVE;
    if (save && save.url && save.token) {
      // Servido por `gb.py serve`: as decisões vão direto para dentro do projeto,
      // sem passar pela pasta de Downloads nem depender de a pessoa achar o arquivo.
      note("Saving to the project…");
      fetch(save.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", [save.header]: save.token },
        body: JSON.stringify(result),
      })
        .then((response) => {
          if (!response.ok) throw new Error(String(response.status));
          return response.json();
        })
        .then((answer) => {
          for (const row of graphicsRows) {
            const decision = graphicsDecisions[row.id];
            const sent = result.graphics.find(item => item.id === row.id);
            if ((sent?.reference || sent?.references) && (decision.reference || null) === (sent.reference || null) &&
              (decision.references || null) === (sent.references || null) && !referenceFiles.has(row.id)) {
              decision.referenceSaved = true;
              releasePreviews(referencePreviews.get(row.id));
              referencePreviews.delete(row.id);
            }
          }
          persist();
          paintGraphics();
          note("");
          announce(
            "Decisions saved to the project (" +
              answer.name +
              "). Return to the chat and say “saved”.",
            answer.path,
          );
        })
        .catch(() => {
          if (result.graphics?.some(row => row.reference || row.references)) {
            note("The reference request was not saved to the project. Keep this draft and retry; no media package was downloaded.");
            return;
          }
          // Servidor fora do ar ou recusa: cai no download, que nunca depende dele.
          note("Could not save to the project; downloaded the file instead.");
          download(result);
        });
      return;
    }
    if (result.graphics?.some(row => row.reference || row.references)) {
      note("References require the local Storyboard server. Open the project there and save again.");
      return;
    }
    download(result);
  }
  function download(result) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "getbrolls-review.json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    // O maior buraco da jornada era aqui: a página acabava e ninguém dizia pra voltar.
    announce(
      "Decisions saved in getbrolls-review.json (in your Downloads folder). " +
        "Return to the chat and say where you saved the file.",
      "getbrolls-review.json",
    );
  }
  function announce(text, path) {
    // A região viva já nasce montada e vazia junto da barra de resumo, no load: um
    // `role="status"` inserido no DOM já preenchido costuma não ser anunciado pelo
    // leitor de tela. Aqui só trocamos o texto, sem `setTimeout` — o anúncio vira
    // parte do mesmo passo do export, e o teste consegue observar o resultado.
    const done = document.querySelector(".export-done");
    if (!done) return;
    done.textContent = text;
    if (!path || !navigator.clipboard) return;
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "copy-path";
    copy.textContent = "Copy path";
    copy.title = "Copy the decision file path to paste into the chat.";
    copy.onclick = () =>
      navigator.clipboard.writeText(path).then(
        () => (copy.textContent = "Path copied"),
        () => (copy.textContent = path),
      );
    done.append(" ", copy);
  }
  function buildPrintNotes() {
    const section = document.querySelector(".print-notes") || document.createElement("section");
    section.className = "print-notes";
    items.forEach((item, index) => {
      let article = section.children[index];
      if (!article) {
        article = document.createElement("article");
        const h = document.createElement("h2");
        h.textContent = item.title;
        article.append(h);
        for (const source of [item.poster, item.context_poster].filter(Boolean)) {
          const poster = document.createElement("img");
          poster.src = source;
          poster.alt = item.title;
          poster.loading = "eager";
          article.append(poster);
        }
        section.append(article);
      }
      article.querySelectorAll("p").forEach((p) => p.remove());
      const d = decisions[item.id];
      for (const text of [
        item.asset_type && item.asset_type !== "video"
          ? `Still image${item.captured_at ? " · Captured on " + item.captured_at : ""}`
          : item.segment.start_s === null
            ? "Interval to be defined"
            : `Clip: ${item.segment.start_s}–${item.segment.end_s} s`,
        item.source ? "Source: " + item.source : "Local file",
        item.creator ? "Creator: " + item.creator : "",
        item.published_at ? "Published on: " + item.published_at : "",
        item.narration ? "Narration: “" + item.narration + "”" : "",
        item.collection_reason ? "Selection reason: " + item.collection_reason : "",
        "Review: " + LABELS[d.state],
        d.comment ? "Comment: " + d.comment : "",
        d.suggestion ? "Suggestion: " + d.suggestion : "",
      ].filter(Boolean)) {
        const p = document.createElement("p");
        p.textContent = text;
        article.append(p);
      }
    });
    if (!section.parentNode) document.querySelector("main").append(section);
    return section;
  }
  // Load print images while reviewing; beforeprint must preserve the decoded nodes.
  buildPrintNotes();
  const printDisclosureState = new Map();
  window.addEventListener("beforeprint", () => {
    buildPrintNotes();
    document.querySelectorAll("details.graphics-details, details.narration-details, details.graphics-passage").forEach((detail) => {
      if (!printDisclosureState.has(detail)) printDisclosureState.set(detail, detail.open);
      detail.open = true;
    });
  });
  window.addEventListener("afterprint", () => {
    printDisclosureState.forEach((open, detail) => { detail.open = open; });
    printDisclosureState.clear();
  });
})();
