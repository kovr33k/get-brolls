(() => {
  "use strict";
  const data = window.GETBROLLS_REVIEW;
  if (!data) return;
  const items = Array.isArray(data.items) ? data.items : [];
  const graphicsRows = Array.isArray(data.graphics) ? data.graphics : [];
  const alignmentRows = Array.isArray(data.alignment) ? data.alignment : [];
  const aiRows = Array.isArray(data.ai) ? data.ai : [];
  const hasAiBoard = !!document.querySelector(".ai-board");
  if (!items.length && !graphicsRows.length && !alignmentRows.length && !aiRows.length && !hasAiBoard) return;
  const key = "getbrolls-v2:" + data.project;
  const graphicsKey = "getbrolls-v2-graphics:" + data.project;
  const alignmentKey = "getbrolls-v2-alignment:" + data.project;
  const aiKey = "getbrolls-v2-ai:" + data.project;
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
  let savedAi = {};
  if (hasAiBoard || aiRows.length) {
    try {
      savedAi = JSON.parse(localStorage.getItem(aiKey) || "{}");
      if (!savedAi || typeof savedAi !== "object" || Array.isArray(savedAi)) savedAi = {};
    } catch {
      available = false;
      savedAi = {};
    }
  }
  const aiDrafts = {};
  const aiLaunched = new Set();
  const aiSelectTimers = new Map();
  let aiPollTimer = 0;
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
      (!row.activeReferences || old.referenceBase === row.activeReferences.sha256) &&
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
      reference: row.activeReferences ? null : prior?.reference || row.reference || null,
      references: prior !== row && prior?.references != null ? prior.references : row.activeReferences?.references || row.references || null,
      referenceBase: row.activeReferences?.sha256 || null,
      referenceSaved: prior === row ? !!(row.activeReferences || row.reference || row.references) : prior?.referenceSaved === true,
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
    const historical = !!row.activeReferences && row.current === false;
    const saved = historical ? row.frozenReferences || [] : savedReferences(decision);
    const status = panel.querySelector("[data-graphics-status]");
    if (!selected && status?.textContent === referenceSelectionNote) status.textContent = "";
    const shared = panel.querySelector("[data-graphics-shared]");
    if (shared) {
      const localOnly = historical || (!row.activeReferences && (row.initial === true || !!selected || saved.length > 0));
      shared.disabled = localOnly;
      if (shared.parentElement) shared.parentElement.hidden = localOnly;
      if (localOnly) { shared.checked = false; decision.scope = "scene"; }
    }
    const input = panel.querySelector("[data-graphics-reference]");
    if (input) input.disabled = historical || !window.GETBROLLS_SAVE?.referenceUrl;
    let info = panel.querySelector("[data-reference-context]");
    if (!info) { info = document.createElement("div"); info.dataset.referenceContext = "1"; }
    if (row.activeReferences) box.append(info);
    info.textContent = "";
    const caption = document.createElement("p");
    caption.textContent = historical ? "Frozen references in this version. Viewing history does not change the active set." :
      `Active references for future changes · ${row.activeReferences?.instruction_count || 0} earlier instructions retained. Remove or replace individual files; describe any changed instructions in your prompt.`;
    info.append(caption);
    const history = historical ? row.frozenReferenceInstructions : row.activeReferences?.instructions;
    if (history?.length) {
      const details = document.createElement("details");
      const title = document.createElement("summary");
      title.textContent = historical ? "Instructions frozen in this version" : "Earlier instructions";
      details.append(title);
      for (const event of history) {
        const text = document.createElement("p");
        text.textContent = event.prompt + (event.application ? " — " + event.application : "");
        details.append(text);
      }
      info.append(details);
    }
    for (const group of row.referenceScopes || []) {
      const line = document.createElement("p");
      line.textContent = `Shared request: ${group.state}. ` + (group.targets.length ? group.targets.map(t => `${t.title || t.occurrence_id}: ${t.state}${t.reason ? " (" + t.reason + ")" : ""} — ${t.instruction}`).join("; ") : "Targets must be resolved in chat before processing.");
      info.append(line);
    }
    for (const work of row.referenceWork || []) {
      if (work.state === "blocked") {
        const warning = document.createElement("p");
        const missing = work.files.filter(file => file.state !== "available").map(file => file.label);
        warning.textContent = "Saved reference files, inspection evidence or the rendered result need attention" +
          (missing.length ? ": " + missing.join(", ") : "") + ". Preserve the originals and ask in chat to recover this request.";
        info.append(warning);
      }
    }
    const uploaded = referencePreviews.get(row.id);
    const entries = [
      ...saved.filter(ref => !selected?.some(entry => entry.label === ref.label)).map(ref => ({ref, label: ref.label, url: uploaded?.find(item => item.ref === ref.ref)?.url})),
      ...(historical ? [] : selected || []),
    ].sort((a,b) => Number(a.label?.slice(1)) - Number(b.label?.slice(1)));
    entries.forEach(entry => {
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
        (entry.file ? " · selected, not saved" : historical ? " · frozen in version" : decision.referenceSaved ? " · saved in project" : " · save the changed request");
      media.onerror = () => { label.textContent += " · Browser preview unavailable. Ask in chat to inspect the saved reference or recover its original."; };
      item.append(media, label);
      if (!historical) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Remove " + entry.label;
        remove.disabled = referenceSaving;
        remove.onclick = () => {
          if (referenceSaving) return;
          if (entry.url) URL.revokeObjectURL(entry.url);
          if (selected) {
            const at = selected.indexOf(entry);
            if (at >= 0) selected.splice(at, 1);
            if (!selected.length) referenceFiles.delete(row.id);
          }
          decision.reference = null;
          decision.references = savedReferences(decision).filter(ref => ref.label !== entry.label);
          decision.referenceSaved = false;
          const input = panel.querySelector("[data-graphics-reference]");
          if (input) input.value = "";
          persist();
          referencePreview(panel, row);
        };
        item.append(remove);
        const replace = document.createElement("button");
        replace.type = "button";
        replace.textContent = "Replace " + entry.label;
        replace.disabled = referenceSaving || !window.GETBROLLS_SAVE?.referenceUrl;
        replace.onclick = () => {
          if (referenceSaving || !input) return;
          panel.dataset.replaceReference = entry.label;
          input.multiple = false;
          input.value = "";
          input.click();
        };
        item.append(replace);
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
      const metadata = Object.fromEntries(
        ["id", "project", "scene_id", "occurrence_id", "version", "signature", "reviewEpoch", "initial"].map(key => [key, row[key]])
      );
      if (decision.referenceBase) metadata.referenceBase = decision.referenceBase;
      let refs = [...savedReferences(decision)];
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
        refs = refs.filter(ref => ref.label !== entry.label);
        refs.push({...entry.ref, label: entry.label});
      }
      decision.reference = null;
      decision.references = refs.sort((a,b) => Number(a.label.slice(1)) - Number(b.label.slice(1)));
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

  function aiDisplayedStill(card) {
    return !!card
      && aiAttr(card, "data-ai-stale") !== "true"
      && !!aiAttr(card, "data-ai-version")
      && !!aiAttr(card, "data-ai-signature");
  }
  function counts() {
    const all = reviewTargets
      .filter((target) => !target.aiCard || aiDisplayedStill(target.aiCard))
      .map((target) => target.decision);
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
  const AI_IN_FLIGHT = new Set(["queued", "running", "remote_pending", "downloading"]);
  let aiBoardBody = { beats: [], versions: [] };
  function aiCards() {
    return [...document.querySelectorAll(".ai-card")];
  }
  function aiSaveConfig() {
    return window.GETBROLLS_SAVE || null;
  }
  function aiLive() {
    const save = aiSaveConfig();
    return !!(save && save.aiUrl && save.token && save.header);
  }
  function aiAttr(node, name) {
    if (!node) return "";
    if (typeof node.getAttribute === "function") {
      const value = node.getAttribute(name);
      if (value != null && value !== "") return value;
    }
    const key = name.replace(/^data-/, "").replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    return node.dataset && node.dataset[key] ? node.dataset[key] : "";
  }
  function aiMode(card) {
    const control = card.querySelector("[data-ai-mode]");
    const value = control && control.value ? control.value : aiAttr(card, "data-ai-mode");
    return value === "images" ? "images" : "economy";
  }
  function aiSelected(card) {
    const chosen = [...card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.checked);
    if (!chosen) return "";
    return chosen.value || aiAttr(chosen, "value");
  }
  function aiNonce(draft, alternative, comment) {
    const guidance = [draft.referenceId || "", draft.sharedReferences || ""].filter(Boolean);
    const raw = ["still", draft.beat, draft.fingerprint, alternative, comment, "economy", ...guidance].join("\u001f");
    let hash = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      hash ^= raw.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return "still-" + (hash >>> 0).toString(16);
  }
  function aiGroupNonce(card, draft, comment) {
    const ids = [...card.querySelectorAll("[data-ai-alternative]")]
      .map((radio) => radio.value || aiAttr(radio, "value"))
      .filter(Boolean);
    const guidance = [draft.referenceId || "", draft.sharedReferences || ""].filter(Boolean);
    const raw = [draft.beat, draft.fingerprint, ...ids, comment, "3", ...guidance].join("\u001f");
    let hash = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      hash ^= raw.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return "group-" + (hash >>> 0).toString(16);
  }
  function aiSetCurrent(card) {
    aiCards().forEach((other) => {
      if (other === card) other.setAttribute("data-ai-current", "true");
      else if (typeof other.removeAttribute === "function") other.removeAttribute("data-ai-current");
    });
  }
  function aiKnownDecision(value) {
    return value === "approved" || value === "changes" || value === "rejected" ? value : "";
  }
  function aiLockModes(card) {
    const stale = aiAttr(card, "data-ai-stale") === "true";
    const video = card.querySelector("[data-ai-video]");
    if (video) video.disabled = stale || !aiLive() || aiAttr(card, "data-ai-video-ready") !== "true";
    const videoVersion = aiAttr(card.querySelector("[data-ai-video-review]"), "data-ai-video-version");
    card.querySelectorAll("[data-ai-video-decision]").forEach((button) => {
      button.disabled = stale || !videoVersion;
    });
    const generate = card.querySelector("[data-ai-generate]");
    if (generate) {
      generate.disabled = stale || !aiLive();
      generate.textContent = aiMode(card) === "images" ? "Generate three stills" : "Generate still";
    }
    card.querySelectorAll("[data-ai-apply], [data-ai-upload], [data-ai-remove-reference]").forEach((button) => {
      button.disabled = stale || !aiLive();
    });
    const hasStill = !!aiAttr(card, "data-ai-version");
    card.querySelectorAll("[data-ai-decision]").forEach((button) => {
      button.disabled = stale || !hasStill;
    });
  }
  function aiHash(raw) {
    let hash = 2166136261;
    for (let i = 0; i < raw.length; i++) {
      hash ^= raw.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }
  function aiPauseOthers(except) {
    document.querySelectorAll("audio, video").forEach((el) => {
      if (el !== except) pauseMedia(el);
    });
  }
  function aiInsertAfter(node, anchor) {
    if (anchor && typeof anchor.after === "function") {
      anchor.after(node);
      return;
    }
    const parent = anchor && anchor.parentNode;
    if (parent && Array.isArray(parent.children)) {
      const index = parent.children.indexOf(anchor);
      node.parentNode = parent;
      if (index < 0) parent.children.push(node);
      else parent.children.splice(index + 1, 0, node);
      return;
    }
    if (parent && typeof parent.append === "function") parent.append(node);
  }
  function aiInsertBefore(node, anchor) {
    if (anchor && typeof anchor.before === "function") {
      anchor.before(node);
      return;
    }
    const parent = anchor && anchor.parentNode;
    if (parent && Array.isArray(parent.children)) {
      const index = parent.children.indexOf(anchor);
      node.parentNode = parent;
      if (index < 0) parent.children.push(node);
      else parent.children.splice(index, 0, node);
      return;
    }
    if (parent && typeof parent.append === "function") parent.append(node);
  }
  function aiDetach(node) {
    if (!node) return;
    if (typeof node.remove === "function") {
      node.remove();
      return;
    }
    const parent = node.parentNode;
    if (parent && Array.isArray(parent.children)) {
      const index = parent.children.indexOf(node);
      if (index >= 0) parent.children.splice(index, 1);
      node.parentNode = null;
    }
  }
  function aiSafePreview(preview) {
    if (typeof preview !== "string" || !preview.startsWith("previews/")) return false;
    return preview.split("/").every((part) => part && part !== "." && part !== "..");
  }
  function aiField(card, name) {
    const field = card.querySelector("[" + name + "]");
    return field && typeof field.value === "string" ? field.value : "";
  }
  function aiPost(card, body, noteName) {
    if (!aiLive()) return;
    const save = aiSaveConfig();
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify(body),
    })
      .then((response) => Promise.resolve()
        .then(() => response.json())
        .then((payload) => ({ ok: response.ok, body: payload }))
        .catch(() => ({ ok: response.ok, body: {} })))
      .then((result) => {
        if (!result.ok) {
          const message = result.body && (result.body.error || result.body.message);
          aiNote(card, noteName, message || "The request was not saved.");
          return;
        }
        aiNote(card, noteName, "");
        aiPoll();
      })
      .catch(() => aiNote(card, noteName, "The request was not saved."));
  }
  function aiCandidateRows(timing) {
    const raw = timing && Array.isArray(timing.candidates) ? timing.candidates : [];
    return raw.map((row) => {
      if (typeof row === "string") return { id: row, text: "", start_s: null, end_s: null };
      if (!row || typeof row !== "object" || !row.id) return null;
      return {
        id: String(row.id),
        text: typeof row.text === "string" ? row.text : "",
        start_s: row.start_s,
        end_s: row.end_s,
      };
    }).filter(Boolean);
  }
  function aiCandidateLabel(row) {
    const bounds = row.start_s != null && row.end_s != null ? row.start_s + "–" + row.end_s + "s" : "";
    return [row.id, bounds, row.text].filter(Boolean).join(" · ");
  }
  function aiTimingLine(timing) {
    if (!timing) return "";
    if (timing.resolved === true) {
      return "Recorded interval " + timing.start_s + "–" + timing.end_s + "s. Timing does not generate media.";
    }
    const reasons = Array.isArray(timing.reasons) && timing.reasons.length ? timing.reasons.join(", ") : (timing.state || "unresolved");
    const labels = aiCandidateRows(timing).map(aiCandidateLabel).filter(Boolean);
    const extra = labels.length ? " Candidates: " + labels.join("; ") + "." : "";
    return "Timing unresolved: " + reasons + "." + extra + " Timing does not generate media.";
  }
  function aiPaintPreview(card, timing) {
    const blocked = timing && timing.preview_error;
    const preview = timing && !blocked && aiSafePreview(timing.preview) ? timing.preview : "";
    aiNote(card, "data-ai-preview-note", !preview && blocked ? String(timing.preview_error) : "");
    let audio = card.querySelector("[data-ai-vo]");
    if (!preview) {
      aiDetach(audio);
      return;
    }
    if (!audio) {
      audio = document.createElement("audio");
      audio.setAttribute("data-ai-vo", "");
      audio.controls = true;
      audio.autoplay = false;
      audio.preload = "metadata";
      audio.setAttribute("controls", "");
      audio.setAttribute("preload", "metadata");
      audio.addEventListener("play", () => aiPauseOthers(audio));
      const box = card.querySelector("[data-ai-timing-box]");
      if (box) aiInsertAfter(audio, box);
      else card.append(audio);
    }
    if (audio.getAttribute("src") !== preview) {
      audio.setAttribute("src", preview);
      audio.src = preview;
    }
  }
  function aiPaintCandidates(card, timing) {
    const list = card.querySelector("[data-ai-candidates]");
    if (!list) return;
    list.textContent = "";
    aiCandidateRows(timing).forEach((row) => {
      const button = document.createElement("button");
      button.setAttribute("type", "button");
      button.setAttribute("data-ai-candidate-choice", row.id);
      button.textContent = aiCandidateLabel(row);
      button.addEventListener("click", () => {
        const field = card.querySelector("[data-ai-candidate]");
        if (field) field.value = row.id;
      });
      list.append(button);
    });
  }
  function aiApplyBeatTiming(card, draft, beat) {
    const timing = beat && beat.timing && typeof beat.timing === "object" ? beat.timing : null;
    draft.timing = timing;
    if (beat && beat.video_ready === true) card.setAttribute("data-ai-video-ready", "true");
    else card.setAttribute("data-ai-video-ready", "false");
    const videoJob = beat && beat.video_job && typeof beat.video_job === "object" ? beat.video_job : null;
    if (videoJob && videoJob.state) card.setAttribute("data-ai-video-state", videoJob.state);
    else if (typeof card.removeAttribute === "function") card.removeAttribute("data-ai-video-state");
    let progress = card.querySelector("[data-ai-video-progress]");
    if (videoJob && !progress) {
      progress = document.createElement("p");
      progress.setAttribute("data-ai-video-progress", "");
      card.append(progress);
    }
    if (progress) progress.textContent = videoJob ? (videoJob.error || videoJob.state || "") : "";
    let line = card.querySelector("[data-ai-timing]");
    if (!line) {
      line = document.createElement("p");
      line.setAttribute("data-ai-timing", "");
      card.append(line);
    }
    line.textContent = aiTimingLine(timing);
    const analysis = card.querySelector("[data-ai-analysis]");
    if (analysis && !draft.analysisDirty && timing && typeof timing.analysis_id === "string" && !analysis.value) {
      analysis.value = timing.analysis_id;
    }
    aiPaintCandidates(card, timing);
    aiPaintPreview(card, timing);
    aiPaintVideoSetup(card);
    aiPaintVideoReview(card, beat && beat.video);
    aiLockModes(card);
  }
  function aiApprovedStill(card, draft) {
    const timing = draft.timing;
    const wanted = timing && typeof timing.still === "string" ? timing.still : "";
    const rows = [];
    const beatId = draft.beat;
    const beats = Array.isArray(aiBoardBody.beats) ? aiBoardBody.beats : [];
    const beat = beats.find((row) => row && row.id === beatId);
    if (beat && beat.version) rows.push(beat.version);
    if (beat && Array.isArray(beat.slots)) beat.slots.forEach((slot) => { if (slot && slot.version) rows.push(slot.version); });
    if (Array.isArray(aiBoardBody.versions)) rows.push(...aiBoardBody.versions);
    const displayed = aiAttr(card, "data-ai-version");
    if (displayed && aiAttr(card, "data-ai-approval") === "approved") {
      rows.push({ id: displayed, signature: aiAttr(card, "data-ai-signature"), approval: "approved", kind: "image" });
    }
    return rows.find((row) => (
      row && row.kind !== "video" && row.approval === "approved" && row.id && row.signature && (!wanted || row.id === wanted)
    )) || null;
  }
  function aiPostTiming(card, draft) {
    if (aiAttr(card, "data-ai-stale") === "true") return;
    const analysis = aiField(card, "data-ai-analysis").trim();
    if (!analysis) {
      aiNote(card, "data-ai-timing-note", "Name the completed narration analysis. Timing does not transcribe.");
      return;
    }
    const body = { action: "timing", beat: draft.beat, analysis, expected: draft.fingerprint };
    const known = draft.timing && typeof draft.timing.still === "string" ? draft.timing.still : "";
    const approved = aiApprovedStill(card, draft);
    if (known) body.still = known;
    else if (approved) body.still = approved.id;
    aiPost(card, body, "data-ai-timing-note");
  }
  function aiPostResolve(card, draft) {
    if (aiAttr(card, "data-ai-stale") === "true") return;
    const analysis = aiField(card, "data-ai-analysis").trim();
    const statement = aiField(card, "data-ai-statement").trim();
    if (!analysis || !statement) {
      aiNote(card, "data-ai-timing-note", "Name the analysis and the exact correction statement.");
      return;
    }
    const candidate = aiField(card, "data-ai-candidate").trim();
    const startText = aiField(card, "data-ai-start").trim();
    const endText = aiField(card, "data-ai-end").trim();
    const body = {
      action: "resolve",
      beat: draft.beat,
      analysis,
      by: "Storyboard",
      statement,
      expected: draft.fingerprint,
    };
    if (candidate) body.candidate = candidate;
    else if (startText && endText) {
      body.start = Number(startText);
      body.end = Number(endText);
      if (!Number.isFinite(body.start) || !Number.isFinite(body.end)) {
        aiNote(card, "data-ai-timing-note", "Start and end must be finite seconds.");
        return;
      }
    } else {
      aiNote(card, "data-ai-timing-note", "Choose a candidate or enter both start and end. Timing does not pick the first candidate.");
      return;
    }
    aiPost(card, body, "data-ai-timing-note");
  }
  function aiEnsureTimingControls(card, draft) {
    if (card.querySelector("[data-ai-timing-box]")) return;
    const box = document.createElement("div");
    box.setAttribute("data-ai-timing-box", "");
    const analysis = document.createElement("input");
    analysis.setAttribute("data-ai-analysis", "");
    analysis.addEventListener("input", () => { draft.analysisDirty = true; });
    const statement = document.createElement("input");
    statement.setAttribute("data-ai-statement", "");
    const candidate = document.createElement("input");
    candidate.setAttribute("data-ai-candidate", "");
    const start = document.createElement("input");
    start.setAttribute("data-ai-start", "");
    const end = document.createElement("input");
    end.setAttribute("data-ai-end", "");
    const candidates = document.createElement("p");
    candidates.setAttribute("data-ai-candidates", "");
    const match = document.createElement("button");
    match.setAttribute("type", "button");
    match.setAttribute("data-ai-timing-match", "");
    match.textContent = "Match narration";
    match.addEventListener("click", () => aiPostTiming(card, draft));
    const resolve = document.createElement("button");
    resolve.setAttribute("type", "button");
    resolve.setAttribute("data-ai-timing-resolve", "");
    resolve.textContent = "Resolve interval";
    resolve.addEventListener("click", () => aiPostResolve(card, draft));
    [
      ["Analysis", analysis],
      ["Statement", statement],
      ["Candidate", candidate],
      ["Start", start],
      ["End", end],
    ].forEach((pair) => {
      const label = document.createElement("label");
      label.append(pair[0] + " ", pair[1]);
      box.append(label);
    });
    box.append(candidates, match, resolve);
    const line = card.querySelector("[data-ai-timing]");
    if (line) aiInsertAfter(box, line);
    else card.append(box);
  }
  function aiVideoDecisionButton(box, decision, label) {
    let button = [...box.querySelectorAll("[data-ai-video-decision]")].find((item) => aiAttr(item, "data-ai-video-decision") === decision);
    if (!button) {
      button = document.createElement("button");
      button.setAttribute("type", "button");
      button.setAttribute("data-ai-video-decision", decision);
      button.textContent = label;
      box.append(button);
    }
    return button;
  }
  function aiBindVideoDecisions(card) {
    card.querySelectorAll("[data-ai-video-decision]").forEach((button) => {
      if (button.dataset.aiVideoWired === "1") return;
      button.dataset.aiVideoWired = "1";
      button.addEventListener("click", () => aiReviewVideo(card, aiAttr(button, "data-ai-video-decision")));
    });
  }
  function aiNativeSetup() {
    const setup = aiBoardBody && aiBoardBody.native_video;
    return setup && typeof setup === "object" ? setup : {};
  }
  function aiVideoLimits() {
    return "480p and 720p are not native Full HD. A short clip does not cover the recorded interval. Motion follows the selected treatment. The approved still is the first frame. Speech and music stay off unless requested. Narration stays a separate recording.";
  }
  function aiDraftFor(card) {
    return aiDrafts[aiAttr(card, "data-ai-beat")] || null;
  }
  function aiVideoKey(version, signature) {
    return String(version || "") + "\u001f" + String(signature || "");
  }
  function aiPaintVideoSetup(card) {
    let note = card.querySelector("[data-ai-video-setup]");
    if (!note) {
      note = document.createElement("p");
      note.setAttribute("data-ai-video-setup", "");
      const button = card.querySelector("[data-ai-video]");
      if (button) aiInsertBefore(note, button);
      else card.append(note);
    }
    const setup = aiNativeSetup();
    const message = setup.message || "Native Grok video is unverified. Record the model and tool in project setup. No model was guessed.";
    note.textContent = message + " " + aiVideoLimits();
  }
  function aiStoreVideoNote(draft, card) {
    if (!draft) return;
    const box = card.querySelector("[data-ai-video-review]");
    const version = aiAttr(box, "data-ai-video-version");
    const signature = aiAttr(box, "data-ai-video-signature");
    const field = card.querySelector("[data-ai-video-comment]");
    if (!version || !signature || !field) return;
    draft.videoNotes = draft.videoNotes && typeof draft.videoNotes === "object" ? draft.videoNotes : {};
    const comment = typeof field.value === "string" ? field.value : "";
    draft.videoVersion = version;
    draft.videoSignature = signature;
    draft.videoComment = comment;
    draft.videoNotes[aiVideoKey(version, signature)] = {
      comment,
      state: draft.videoState || "pending",
      save: draft.videoSave || "",
      dirty: draft.videoCommentDirty === true,
    };
  }
  function aiEnsureVideoComment(card) {
    const box = card.querySelector("[data-ai-video-review]");
    if (!box) return null;
    let field = box.querySelector("[data-ai-video-comment]");
    if (!field) {
      const label = document.createElement("label");
      field = document.createElement("textarea");
      field.setAttribute("data-ai-video-comment", "");
      label.append("Video note ", field);
      box.append(label);
    }
    if (field.dataset.aiVideoComment !== "1") {
      field.dataset.aiVideoComment = "1";
      field.addEventListener("input", () => {
        const draft = aiDraftFor(card);
        if (!draft) return;
        draft.videoComment = field.value;
        draft.videoCommentDirty = true;
        draft.videoVersion = aiAttr(box, "data-ai-video-version");
        draft.videoSignature = aiAttr(box, "data-ai-video-signature");
        aiStoreVideoNote(draft, card);
        persist();
      });
    }
    if (!box.querySelector("[data-ai-video-decision-label]")) {
      const decision = document.createElement("p");
      decision.className = "ai-decision";
      decision.setAttribute("data-ai-video-decision-label", "");
      box.append(decision);
    }
    return field;
  }
  function aiPaintVideoDecision(card, draft) {
    const box = card.querySelector("[data-ai-video-review]");
    const label = box && box.querySelector("[data-ai-video-decision-label]");
    if (!label || !draft) return;
    const name = LABELS[draft.videoState] || LABELS.pending;
    const unsaved = draft.videoState !== "pending" && (draft.videoSave === "pending" || draft.videoSave === "failed");
    label.textContent = unsaved ? name + " · not saved" : name;
  }
  function aiApplyVideoComment(field, draft, video, sameClip) {
    const note = draft.videoNotes && draft.videoNotes[aiVideoKey(video.id, video.signature)];
    const serverComment = typeof video.comment === "string" ? video.comment : null;
    if (sameClip && draft.videoCommentDirty) return;
    if (note && note.dirty === true && typeof note.comment === "string") {
      field.value = note.comment;
      draft.videoComment = note.comment;
      draft.videoCommentDirty = true;
      return;
    }
    if (sameClip && draft.videoComment && serverComment === null) return;
    field.value = serverComment || "";
    draft.videoComment = field.value;
    draft.videoCommentDirty = false;
  }
  function aiApplyVideoState(draft, video, sameClip) {
    const note = draft.videoNotes && draft.videoNotes[aiVideoKey(video.id, video.signature)];
    const serverState = aiKnownDecision(typeof video.approval === "string" ? video.approval : "");
    if (!sameClip) {
      if (note && note.dirty === true && aiKnownDecision(note.state)) {
        draft.videoState = aiKnownDecision(note.state);
        draft.videoSave = typeof note.save === "string" ? note.save : "";
        return;
      }
      draft.videoState = serverState || "pending";
      draft.videoSave = "";
      return;
    }
    if (!aiKnownDecision(draft.videoState)) draft.videoState = serverState || "pending";
    else if (serverState && serverState === draft.videoState) draft.videoSave = "";
  }
  function aiPaintVideoReview(card, video) {
    let box = card.querySelector("[data-ai-video-review]");
    if (!box) {
      box = document.createElement("div");
      box.className = "ai-video-review";
      box.setAttribute("data-ai-video-review", "");
      card.append(box);
    }
    const draft = aiDraftFor(card);
    const previousVersion = aiAttr(box, "data-ai-video-version");
    const previousSignature = aiAttr(box, "data-ai-video-signature");
    if (!video || !video.id || !video.signature) {
      if (draft && previousVersion && previousSignature) aiStoreVideoNote(draft, card);
      box.hidden = true;
      return;
    }
    const sameClip = previousVersion === video.id && previousSignature === video.signature;
    if (draft && previousVersion && previousSignature && !sameClip) aiStoreVideoNote(draft, card);
    box.hidden = false;
    box.setAttribute("data-ai-video-version", video.id);
    box.setAttribute("data-ai-video-signature", video.signature);
    let meta = box.querySelector("[data-ai-video-meta]");
    if (!meta) {
      meta = document.createElement("p");
      meta.setAttribute("data-ai-video-meta", "");
      box.append(meta);
    }
    const short = video.coverage === "short" ? " Duration is shorter than the recorded interval." : "";
    const native = video.native_full_hd === false ? " Native 480p/720p is not native Full HD." : "";
    meta.textContent = (video.width || "") + "×" + (video.height || "") + " " + (video.resolution || "")
      + " · " + (video.duration_s == null ? "" : video.duration_s) + "s · audio " + video.audio + "." + short + native;
    let media = box.querySelector("video");
    if (!media) {
      media = document.createElement("video");
      media.controls = true;
      media.autoplay = false;
      media.preload = "metadata";
      media.setAttribute("controls", "");
      media.setAttribute("preload", "metadata");
      media.addEventListener("play", () => aiPauseOthers(media));
      box.append(media);
    }
    if (video.path && media.getAttribute("src") !== video.path) {
      media.setAttribute("src", video.path);
      media.src = video.path;
    }
    const field = aiEnsureVideoComment(card);
    if (draft && field) {
      aiApplyVideoComment(field, draft, video, sameClip);
      aiApplyVideoState(draft, video, sameClip);
      draft.videoVersion = video.id;
      draft.videoSignature = video.signature;
      aiPaintVideoDecision(card, draft);
    }
    aiVideoDecisionButton(box, "approved", "Approve this video");
    aiVideoDecisionButton(box, "changes", "Request video changes");
    aiVideoDecisionButton(box, "rejected", "Reject this video");
    aiBindVideoDecisions(card);
  }
  function aiLaunchVideo(card, draft) {
    const button = card.querySelector("[data-ai-video]");
    if (!button || button.disabled || aiAttr(card, "data-ai-video-ready") !== "true") return;
    if (aiAttr(card, "data-ai-stale") === "true") return;
    const timing = draft.timing;
    if (!timing || timing.resolved !== true) {
      aiNote(card, "data-ai-video-note", "Resolve the recorded interval before generating video.");
      return;
    }
    const setup = aiNativeSetup();
    const typedModel = aiField(card, "data-ai-video-model").trim();
    const model = typedModel || (typeof setup.model === "string" ? setup.model.trim() : "");
    const toolField = card.querySelector("[data-ai-video-tool]");
    const chosenTool = toolField && toolField.value ? toolField.value : "";
    const tool = chosenTool || (typeof setup.tool === "string" ? setup.tool : "");
    if (!model || (tool !== "reference_to_video" && tool !== "image_to_video")) {
      aiNote(card, "data-ai-video-note", setup.message || "Native Grok video is unverified. Record the model and tool in project setup. No model was guessed.");
      return;
    }
    const still = aiApprovedStill(card, draft);
    if (!still) {
      aiNote(card, "data-ai-video-note", "Approve the exact still before generating video.");
      return;
    }
    const resolutionField = card.querySelector("[data-ai-video-resolution]");
    const resolution = resolutionField && resolutionField.value ? resolutionField.value : "480p";
    const sound = {
      speech: !!(card.querySelector("[data-ai-speech]") || {}).checked,
      music: !!(card.querySelector("[data-ai-music]") || {}).checked,
      atmosphere: !!(card.querySelector("[data-ai-atmosphere]") || {}).checked,
      effects: !!(card.querySelector("[data-ai-effects]") || {}).checked,
    };
    const requestId = "video-" + aiHash([
      draft.beat,
      draft.fingerprint,
      still.id,
      still.signature,
      String(timing.start_s),
      String(timing.end_s),
      model,
      tool,
      resolution,
      sound.speech ? "1" : "0",
      sound.music ? "1" : "0",
      sound.atmosphere ? "1" : "0",
      sound.effects ? "1" : "0",
    ].join("\u001f"));
    aiPost(card, {
      action: "video",
      beat: draft.beat,
      expected: draft.fingerprint,
      version: still.id,
      signature: still.signature,
      requestId,
      model,
      tool,
      resolution,
      speech: sound.speech,
      music: sound.music,
      atmosphere: sound.atmosphere,
      effects: sound.effects,
    }, "data-ai-video-note");
  }
  function aiReviewVideo(card, decision) {
    const box = card.querySelector("[data-ai-video-review]");
    const version = aiAttr(box, "data-ai-video-version");
    const signature = aiAttr(box, "data-ai-video-signature");
    if (!box || !version || !signature || !LABELS[decision] || decision === "pending") return;
    if (aiAttr(card, "data-ai-stale") === "true") return;
    const draft = aiDraftFor(card);
    if (!draft || !aiLive()) return;
    const comment = aiField(card, "data-ai-video-comment");
    draft.videoState = decision;
    draft.videoVersion = version;
    draft.videoSignature = signature;
    draft.videoComment = comment;
    draft.videoCommentDirty = false;
    draft.videoSave = "pending";
    aiStoreVideoNote(draft, card);
    aiPaintVideoDecision(card, draft);
    persist();
    const save = aiSaveConfig();
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify({
        action: "review",
        beat: draft.beat,
        version,
        signature,
        decision,
        by: "Storyboard",
        comment,
      }),
    })
      .then((response) => Promise.resolve()
        .then(() => response.json())
        .then((payload) => ({ ok: response.ok, body: payload }))
        .catch(() => ({ ok: response.ok, body: {} })))
      .then((result) => {
        if (aiAttr(box, "data-ai-video-version") !== version || aiAttr(box, "data-ai-video-signature") !== signature) return;
        if (!result.ok) {
          draft.videoSave = "failed";
          draft.videoCommentDirty = true;
          aiNote(card, "data-ai-video-note", (result.body && result.body.error) || "The video review was not saved.");
        } else {
          draft.videoSave = "saved";
          aiNote(card, "data-ai-video-note", "");
        }
        aiStoreVideoNote(draft, card);
        aiPaintVideoDecision(card, draft);
        persist();
        if (result.ok) aiPoll();
      })
      .catch(() => {
        if (aiAttr(box, "data-ai-video-version") !== version || aiAttr(box, "data-ai-video-signature") !== signature) return;
        draft.videoSave = "failed";
        draft.videoCommentDirty = true;
        aiStoreVideoNote(draft, card);
        aiPaintVideoDecision(card, draft);
        aiNote(card, "data-ai-video-note", "The video review was not saved.");
        persist();
      });
  }
  function aiEnsureVideoAdvanced(card) {
    const details = card.querySelector(".ai-details");
    if (!details || details.querySelector("[data-ai-video-advanced]")) return;
    const box = document.createElement("div");
    box.setAttribute("data-ai-video-advanced", "");
    const model = document.createElement("input");
    model.setAttribute("data-ai-video-model", "");
    const tool = document.createElement("select");
    tool.setAttribute("data-ai-video-tool", "");
    const project = document.createElement("option");
    project.value = "";
    project.textContent = "Project setup";
    tool.append(project);
    [["reference_to_video", "reference_to_video"], ["image_to_video", "image_to_video"]].forEach((pair) => {
      const option = document.createElement("option");
      option.value = pair[0];
      option.textContent = pair[1];
      tool.append(option);
    });
    [["Model", model], ["Tool", tool]].forEach((pair) => {
      const label = document.createElement("label");
      label.append(pair[0] + " ", pair[1]);
      box.append(label);
    });
    details.append(box);
  }
  function aiEnsureVideoControls(card, draft) {
    if (card.querySelector("[data-ai-video-box]")) {
      aiEnsureVideoAdvanced(card);
      return;
    }
    const box = document.createElement("div");
    box.setAttribute("data-ai-video-box", "");
    const resolution = document.createElement("select");
    resolution.setAttribute("data-ai-video-resolution", "");
    ["480p", "720p"].forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      resolution.append(option);
    });
    resolution.value = "480p";
    const flags = [
      ["speech", "data-ai-speech", "Speech"],
      ["music", "data-ai-music", "Music"],
      ["atmosphere", "data-ai-atmosphere", "Atmosphere"],
      ["effects", "data-ai-effects", "Effects"],
    ].map((item) => {
      const input = document.createElement("input");
      input.setAttribute("type", "checkbox");
      input.setAttribute(item[1], "");
      const label = document.createElement("label");
      label.append(input, " " + item[2]);
      return label;
    });
    const resolutionLabel = document.createElement("label");
    resolutionLabel.append("Resolution ", resolution);
    box.append(resolutionLabel);
    flags.forEach((label) => box.append(label));
    const videoButton = card.querySelector("[data-ai-video]");
    if (videoButton) aiInsertBefore(box, videoButton);
    else card.append(box);
    if (videoButton && videoButton.dataset.aiVideoLaunch !== "1") {
      videoButton.dataset.aiVideoLaunch = "1";
      videoButton.addEventListener("click", () => aiLaunchVideo(card, draft));
    }
    aiEnsureVideoAdvanced(card);
    aiBindVideoDecisions(card);
  }
  function aiNote(card, name, text) {
    let note = card.querySelector("[" + name + "]");
    if (!note) {
      note = document.createElement("p");
      note.setAttribute(name, "");
      card.append(note);
    }
    note.textContent = text;
  }
  function aiPaintDecision(card, draft) {
    let label = card.querySelector("[data-ai-decision-label]");
    if (!label) {
      label = document.createElement("p");
      label.className = "ai-decision";
      label.setAttribute("data-ai-decision-label", "");
      card.append(label);
    }
    const name = LABELS[draft.state] || LABELS.pending;
    const unsaved = draft.state !== "pending" && (draft.save === "pending" || draft.save === "failed");
    label.textContent = unsaved ? name + " · not saved" : name;
  }
  function aiShowStill(card, version) {
    const figure = card.querySelector("[data-ai-result]");
    if (!figure || !version || !version.id || !version.signature) return;
    let image = figure.querySelector("img");
    if (!image) {
      image = document.createElement("img");
      figure.append(image);
    }
    if (version.path) {
      image.setAttribute("src", version.path);
      image.src = version.path;
    }
    image.alt = "Generated illustration";
    image.setAttribute("alt", "Generated illustration");
    let caption = figure.querySelector("figcaption");
    if (!caption) {
      caption = document.createElement("figcaption");
      figure.append(caption);
    }
    caption.textContent = "Generated illustration";
    card.setAttribute("data-ai-version", version.id);
    card.setAttribute("data-ai-signature", version.signature);
    if (version.approval) card.setAttribute("data-ai-approval", version.approval);
    const review = card.querySelector(".ai-review");
    if (review) review.hidden = false;
    aiLockModes(card);
  }
  function aiShowDiagnostics(card, job, version) {
    const details = card.querySelector(".ai-details");
    if (!details) return;
    let node = details.querySelector("[data-ai-diagnostics]");
    if (!node) {
      node = document.createElement("p");
      node.setAttribute("data-ai-diagnostics", "");
      details.append(node);
    }
    const parts = [];
    if (job && typeof job === "object") {
      parts.push("Job " + (job.id || "none") + " · state " + (job.state || "idle"));
      if (job.error) parts.push(String(job.error));
    }
    if (version && version.width && version.height) {
      parts.push(version.width + "×" + version.height + " " + (version.codec || ""));
    }
    const setup = aiNativeSetup();
    parts.push(
      "Native video " + (setup.model || "model not recorded") + " · "
      + (setup.tool || "tool not recorded") + " · capability unverified"
    );
    parts.push("Generated illustration, not documentary evidence. Generation is not approval.");
    node.textContent = parts.join(" · ");
  }
  function aiRemember(draft) {
    return {
      beat: draft.beat,
      fingerprint: draft.fingerprint,
      selected: draft.selected,
      selectedDirty: draft.selectedDirty === true,
      comment: draft.comment,
      commentDirty: draft.commentDirty === true,
      mode: draft.mode,
      modeDirty: draft.modeDirty === true,
      job: draft.job || "",
      version: (draft.pendingExact || draft).version || "",
      signature: (draft.pendingExact || draft).signature || "",
      state: draft.state,
      save: draft.save || "",
      versions: draft.versions || {},
      videoVersion: draft.videoVersion || "",
      videoSignature: draft.videoSignature || "",
      videoComment: typeof draft.videoComment === "string" ? draft.videoComment : "",
      videoCommentDirty: draft.videoCommentDirty === true,
      videoState: draft.videoState || "pending",
      videoSave: draft.videoSave || "",
      videoNotes: draft.videoNotes && typeof draft.videoNotes === "object" ? draft.videoNotes : {},
      instruction: typeof draft.instruction === "string" ? draft.instruction : "",
      instructionDirty: draft.instructionDirty === true,
      fileName: typeof draft.fileName === "string" ? draft.fileName : "",
      fileUnsent: draft.fileUnsent === true,
      uploadEpoch: draft.uploadEpoch || 0,
      referenceId: typeof draft.referenceId === "string" ? draft.referenceId : "",
    };
  }
  function aiContextMatch(stored, fingerprint, version, signature) {
    if (!stored || stored.fingerprint !== fingerprint) return false;
    if (aiKnownDecision(stored.state)) {
      return !!version && !!signature && stored.version === version && stored.signature === signature;
    }
    return (stored.version || "") === (version || "") && (stored.signature || "") === (signature || "");
  }
  function aiLocalExact(stored, fingerprint, version, signature) {
    if (!stored || stored.fingerprint !== fingerprint) return null;
    if (!stored.version || !stored.signature) return null;
    if (stored.version === (version || "") && stored.signature === (signature || "")) return null;
    return stored;
  }
  function aiLoadDraft(card) {
    const beat = aiAttr(card, "data-ai-beat");
    const signature = aiAttr(card, "data-ai-signature");
    const version = aiAttr(card, "data-ai-version");
    const fingerprint = aiAttr(card, "data-ai-fingerprint");
    const commentBox = card.querySelector("[data-ai-comment]");
    const stored = savedAi[beat];
    const row = aiRows.find((item) => (
      item &&
      item.beat === beat &&
      item.fingerprint === fingerprint &&
      (item.version || "") === version &&
      (item.signature || "") === signature
    ));
    const serverDecision = aiKnownDecision(aiAttr(card, "data-ai-approval")) || aiKnownDecision(row && (row.decision || row.state));
    const draft = {
      beat,
      fingerprint,
      selected: aiSelected(card),
      selectedDirty: false,
      comment: commentBox && typeof commentBox.value === "string" ? commentBox.value : "",
      commentDirty: false,
      mode: aiMode(card),
      modeDirty: false,
      sceneComment: commentBox && typeof commentBox.value === "string" ? commentBox.value : "",
      job: aiAttr(card, "data-ai-job"),
      version,
      signature,
      state: serverDecision || "pending",
      save: "",
      versions: stored && stored.fingerprint === fingerprint && stored.versions && typeof stored.versions === "object" ? stored.versions : {},
      videoNotes: stored && stored.fingerprint === fingerprint && stored.videoNotes && typeof stored.videoNotes === "object" && !Array.isArray(stored.videoNotes) ? stored.videoNotes : {},
      videoVersion: "",
      videoSignature: "",
      videoComment: "",
      videoCommentDirty: false,
      videoState: "pending",
      videoSave: "",
      epoch: 0,
      saveEpoch: 0,
      offered: null,
      instruction: "",
      instructionDirty: false,
      fileName: "",
      fileUnsent: false,
      uploadEpoch: 0,
      referenceId: "",
    };
    const videoBox = card.querySelector("[data-ai-video-review]");
    const videoVersion = aiAttr(videoBox, "data-ai-video-version");
    const videoSignature = aiAttr(videoBox, "data-ai-video-signature");
    const videoNote = videoVersion && videoSignature ? draft.videoNotes[videoVersion + "\u001f" + videoSignature] : null;
    const videoField = card.querySelector("[data-ai-video-comment]");
    if (videoNote && videoNote.dirty === true && videoField && typeof videoNote.comment === "string") {
      videoField.value = videoNote.comment;
      draft.videoVersion = videoVersion;
      draft.videoSignature = videoSignature;
      draft.videoComment = videoNote.comment;
      draft.videoCommentDirty = true;
      draft.videoState = aiKnownDecision(videoNote.state) || "pending";
      draft.videoSave = typeof videoNote.save === "string" ? videoNote.save : "";
    }
    if (aiContextMatch(stored, fingerprint, version, signature)) {
      if (typeof stored.comment === "string" && commentBox) {
        commentBox.value = stored.comment;
        draft.comment = stored.comment;
        draft.commentDirty = stored.commentDirty === true;
      }
      if (stored.selectedDirty === true && typeof stored.selected === "string") {
        card.querySelectorAll("[data-ai-alternative]").forEach((radio) => {
          const value = radio.value || aiAttr(radio, "value");
          radio.checked = value === stored.selected;
        });
        draft.selected = stored.selected;
        draft.selectedDirty = true;
      }
      const localDecision = aiKnownDecision(stored.state);
      if (localDecision) {
        draft.state = localDecision;
        draft.version = stored.version;
        draft.signature = stored.signature;
        draft.job = stored.job || draft.job;
        const exactServer = serverDecision === localDecision && stored.version === version && stored.signature === signature && !!version && !!signature;
        if (exactServer || stored.save === "saved" || stored.save === "local" || !stored.save) {
          draft.save = stored.save === "local" && !exactServer ? "local" : "";
        } else if (stored.save === "failed") {
          draft.save = "failed";
        } else {
          draft.save = "pending";
        }
      }
    }
    const held = aiLocalExact(stored, fingerprint, version, signature);
    if (held) {
      draft.pendingExact = {
        version: held.version,
        signature: held.signature,
        selectedDirty: held.selectedDirty === true,
        comment: typeof held.comment === "string" ? held.comment : "",
      };
      if (held.selectedDirty === true && typeof held.selected === "string") {
        card.querySelectorAll("[data-ai-alternative]").forEach((radio) => {
          const value = radio.value || aiAttr(radio, "value");
          radio.checked = value === held.selected;
        });
        draft.selected = held.selected;
        draft.selectedDirty = true;
      }
      if (held.commentDirty === true && typeof held.comment === "string" && commentBox) {
        commentBox.value = held.comment;
        draft.comment = held.comment;
        draft.commentDirty = true;
      }
    }
    if (stored && stored.fingerprint === fingerprint) {
      const instructionBox = card.querySelector("[data-ai-instruction]");
      if (instructionBox && typeof stored.instruction === "string") {
        instructionBox.value = stored.instruction;
        draft.instruction = stored.instruction;
        draft.instructionDirty = stored.instructionDirty === true;
      }
      draft.fileName = typeof stored.fileName === "string" ? stored.fileName : "";
      draft.fileUnsent = stored.fileUnsent === true;
      draft.uploadEpoch = typeof stored.uploadEpoch === "number" ? stored.uploadEpoch : 0;
      draft.referenceId = typeof stored.referenceId === "string" ? stored.referenceId : "";
      if (draft.fileUnsent) aiNote(card, "data-ai-file-note", "Selected, not sent.");
    }
    if (version && signature && aiKnownDecision(draft.state)) {
      const identity = version + "\u001f" + signature;
      if (!draft.versions[identity]) {
        const exactRow = row && aiKnownDecision(row.decision || row.state) === draft.state;
        draft.versions[identity] = {
          version, signature, state: draft.state, job: draft.job, save: draft.save,
          comment: exactRow && typeof row.comment === "string" ? row.comment : draft.comment,
          selected: exactRow && typeof row.selected === "string" ? row.selected : draft.selected,
        };
      }
    }
    return draft;
  }
  function aiScheduleSelect(card) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!draft || !aiLive() || typeof setInterval !== "function" || typeof clearInterval !== "function") return;
    draft.epoch += 1;
    const epoch = draft.epoch;
    const previous = aiSelectTimers.get(draft.beat);
    if (previous) clearInterval(previous);
    // The export path keeps the only setTimeout. Debounce with an interval instead.
    const timer = setInterval(() => {
      clearInterval(timer);
      aiSelectTimers.delete(draft.beat);
      if (draft.epoch !== epoch) return;
      aiPostSelect(card, epoch);
    }, 400);
    aiSelectTimers.set(draft.beat, timer);
  }
  function aiPostSelect(card, epoch) {
    const save = aiSaveConfig();
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!save || !draft || draft.epoch !== epoch || !aiLive()) return;
    const payload = { action: "select", beat: draft.beat, expected: draft.fingerprint };
    if (draft.selectedDirty) payload.alternative = aiSelected(card);
    if (draft.commentDirty) payload.comment = draft.comment;
    if (draft.modeDirty) payload.mode = aiMode(card);
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify(payload),
    })
      .then((response) => Promise.resolve()
        .then(() => response.json())
        .then((body) => ({ ok: response.ok, body }))
        .catch(() => ({ ok: response.ok, body: {} })))
      .then((result) => {
        if (!draft || draft.epoch !== epoch) return;
        if (!result.ok) aiNote(card, "data-ai-save", "The scene choice was not saved.");
        else aiNote(card, "data-ai-save", "");
      })
      .catch(() => {
        if (!draft || draft.epoch !== epoch) return;
        aiNote(card, "data-ai-save", "The scene choice was not saved.");
      });
  }
  function aiGenerate(card) {
    const button = card.querySelector("[data-ai-generate]");
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    const images = aiMode(card) === "images";
    if (!button || button.disabled || !draft || !aiLive()) return;
    if (draft.referenceBusy || draft.fileUnsent) {
      aiNote(card, "data-ai-file-note", "Keep the selected reference before generating.");
      return;
    }
    const alternative = aiSelected(card);
    const commentBox = card.querySelector("[data-ai-comment]");
    const comment = commentBox && typeof commentBox.value === "string" ? commentBox.value : draft.comment;
    if (!images && !alternative) return;
    const nonce = images ? aiGroupNonce(card, draft, comment) : aiNonce(draft, alternative, comment);
    if (aiLaunched.has(nonce)) return;
    aiLaunched.add(nonce);
    draft.comment = comment;
    const save = aiSaveConfig();
    const payload = {
      action: "generate",
      beat: draft.beat,
      expected: draft.fingerprint,
      comment,
      nonce,
      requestId: nonce,
    };
    if (images) payload.outputs = 3;
    else {
      payload.alternative = alternative;
    }
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify(payload),
    })
      .then((response) => Promise.resolve()
        .then(() => response.json())
        .then((body) => ({ ok: response.ok, body }))
        .catch(() => ({ ok: response.ok, body: {} })))
      .then((result) => {
        const jobs = result.ok && result.body && Array.isArray(result.body.jobs) ? result.body.jobs : null;
        if (jobs && jobs.length) {
          const flight = jobs.find((row) => row && AI_IN_FLIGHT.has(row.state));
          const marked = flight || jobs[0];
          if (marked && marked.state) card.setAttribute("data-ai-state", marked.state);
          const progress = card.querySelector("[data-ai-progress]");
          if (progress) {
            progress.textContent = jobs
              .map((row) => (row.alternative || row.id || "slot") + ": " + (row.error || row.state || "waiting"))
              .join(" · ");
          }
          aiPoll();
          aiEnsurePoll();
          return;
        }
        const job = result.ok && result.body ? result.body.job : null;
        const terminal = job && ["failed", "unknown", "quota", "auth"].includes(job.state);
        if (!result.ok || !job || terminal) {
          if (!job || !terminal) aiLaunched.delete(nonce);
          const progress = card.querySelector("[data-ai-progress]");
          if (progress) progress.textContent = (job && (job.error || job.state)) || (result.body && result.body.error) || "Could not start still generation.";
          if (job) aiShowDiagnostics(card, job, null);
          return;
        }
        const displayed = aiAttr(card, "data-ai-version");
        if (!displayed && draft.state === "pending" && job.id) {
          card.setAttribute("data-ai-job", job.id);
          draft.job = job.id;
        }
        if (job.state) card.setAttribute("data-ai-state", job.state);
        const progress = card.querySelector("[data-ai-progress]");
        if (progress) progress.textContent = job.error || job.state || "";
        aiShowDiagnostics(card, job, null);
        if (job.state === "complete") aiPoll();
        aiEnsurePoll();
      })
      .catch(() => {
        aiLaunched.delete(nonce);
        const progress = card.querySelector("[data-ai-progress]");
        if (progress) progress.textContent = "Could not start still generation.";
      });
  }
  function aiSlotVersion(figure) {
    const id = aiAttr(figure, "data-ai-version");
    const signature = aiAttr(figure, "data-ai-signature");
    if (!id || !signature) return null;
    const image = figure.querySelector("img");
    return {
      id,
      signature,
      path: image ? image.getAttribute("src") || "" : "",
      approval: aiAttr(figure, "data-ai-approval"),
    };
  }
  function aiSceneComment(card, draft, value) {
    const box = card.querySelector("[data-ai-comment]");
    const text = typeof value === "string" ? value : "";
    if (box) box.value = text;
    draft.comment = text;
  }
  function aiRestoreChoice(card, draft, beat) {
    if (!draft.modeDirty && (beat.mode === "images" || beat.mode === "economy")) {
      const control = card.querySelector("[data-ai-mode]");
      if (control) control.value = beat.mode;
      card.setAttribute("data-ai-mode", beat.mode);
      draft.mode = beat.mode;
      aiLockModes(card);
    }
    if (!draft.selectedDirty && typeof beat.selected === "string" && beat.selected) {
      card.querySelectorAll("[data-ai-alternative]").forEach((radio) => {
        const value = radio.value || aiAttr(radio, "value");
        radio.checked = value === beat.selected;
      });
      draft.selected = beat.selected;
    }
    if (!draft.commentDirty && typeof beat.comment === "string") {
      aiSceneComment(card, draft, beat.comment);
      draft.sceneComment = beat.comment;
      draft.commentDirty = false;
    }
  }
  function aiSlotDecision(version, prior, current, same) {
    const kept = same ? aiKnownDecision(current) : "";
    const stored = prior && aiKnownDecision(prior.state);
    return kept || stored || aiKnownDecision(version && version.approval) || "pending";
  }
  function aiChooseSlot(card, slot, quiet) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!draft || !slot || aiAttr(card, "data-ai-stale") === "true") return;
    const alternative = slot.alternative || "";
    card.querySelectorAll("[data-ai-alternative]").forEach((radio) => {
      radio.checked = (radio.value || aiAttr(radio, "value")) === alternative;
    });
    draft.selected = alternative;
    if (!quiet) draft.selectedDirty = true;
    const version = slot.version;
    if (version && version.id && version.signature) {
      const same = draft.version === version.id && draft.signature === version.signature;
      if (!same) aiStoreDisplayed(draft, card);
      const prior = (draft.versions || {})[version.id + "\u001f" + version.signature];
      draft.state = aiSlotDecision(version, prior, draft.state, same);
      draft.version = version.id;
      draft.signature = version.signature;
      draft.job = (slot.job && slot.job.id) || version.job || draft.job;
      card.setAttribute("data-ai-approval", draft.state);
      if (!quiet && !same) {
        if (prior && typeof prior.comment === "string") aiSceneComment(card, draft, prior.comment);
        else if (typeof slot.comment === "string") aiSceneComment(card, draft, slot.comment);
        else if (typeof draft.sceneComment === "string") aiSceneComment(card, draft, draft.sceneComment);
        draft.commentDirty = false;
      }
      aiShowStill(card, {
        id: version.id,
        signature: version.signature,
        path: version.path || "",
        approval: draft.state,
      });
      aiPaintDecision(card, draft);
    }
    if (!quiet) aiSetCurrent(card);
    persist();
    if (!quiet) aiScheduleSelect(card);
  }
  function aiRestoreExactSlot(card, draft, held, slot, beat) {
    if (held.selectedDirty === true) draft.selectedDirty = true;
    aiChooseSlot(card, slot, true);
    if (slot.alternative && typeof beat.selected === "string" && slot.alternative !== beat.selected) {
      draft.selectedDirty = true;
    }
    if (!draft.commentDirty) {
      if (typeof slot.comment === "string") aiSceneComment(card, draft, slot.comment);
      else if (typeof held.comment === "string") aiSceneComment(card, draft, held.comment);
    }
    aiNote(card, "data-ai-slot-note", "");
    persist();
    if (draft.selectedDirty || draft.commentDirty || draft.modeDirty) aiScheduleSelect(card);
  }
  function aiHydrateFocus(card, draft, beat) {
    const pendingSlot = draft.pendingExact && Array.isArray(beat.slots) && beat.slots.some((slot) => (
      slot && slot.version && slot.version.id === draft.pendingExact.version && slot.version.signature === draft.pendingExact.signature
    ));
    if (draft.pendingExact && !pendingSlot && beat.fingerprint === draft.fingerprint) {
      const held = draft.pendingExact;
      const latest = beat.version;
      const focus = latest && latest.id === held.version && latest.signature === held.signature ? latest
        : (Array.isArray(aiBoardBody.versions) ? aiBoardBody.versions : []).find((row) => (
          row && row.kind === "image" && row.beat === draft.beat && row.inputs === draft.fingerprint
          && row.id === held.version && row.signature === held.signature
        ));
      if (focus) {
        draft.pendingExact = null;
        draft.hydrated = true;
        draft.offered = focus;
        aiUseOffered(card);
      } else aiNote(card, "data-ai-slot-note", beat.mode === "images" ? "The chosen still is missing from the current comparison." : "The chosen retained still is not available in this context.");
      return;
    }
    if (
      draft.pendingExact &&
      beat.fingerprint === draft.fingerprint &&
      beat.mode === "images" &&
      Array.isArray(beat.slots)
    ) {
      const held = draft.pendingExact;
      draft.pendingExact = null;
      draft.hydrated = true;
      const slot = beat.slots.find((row) => (
        row && row.version && row.version.id === held.version && row.version.signature === held.signature
      ));
      if (slot) {
        aiRestoreExactSlot(card, draft, held, slot, beat);
        return;
      }
      aiNote(card, "data-ai-slot-note", "The chosen still is missing from the current comparison.");
      return;
    }
    if (draft.hydrated) return;
    draft.hydrated = true;
    if (aiAttr(card, "data-ai-version") && aiAttr(card, "data-ai-signature")) return;
    if (beat.mode !== "images" || !Array.isArray(beat.slots) || !beat.slots.length) return;
    const focus = beat.version && typeof beat.version === "object" ? beat.version : null;
    if (!focus || !focus.id || !focus.signature) return;
    const slot = beat.slots.find((row) => (
      row && row.version && row.version.id === focus.id && row.version.signature === focus.signature
    ));
    aiChooseSlot(card, slot || { alternative: beat.selected || "", job: beat.job, version: focus }, true);
  }
  function aiChooseButton(card, button) {
    const figure = button.parentNode;
    aiChooseSlot(card, {
      alternative: aiAttr(button, "data-ai-choose"),
      comment: figure.getAttribute("data-ai-slot-comment"),
      job: { id: aiAttr(figure, "data-ai-job"), state: aiAttr(figure, "data-ai-state") },
      version: aiSlotVersion(figure),
    });
  }
  function aiPaintSlots(card, slots) {
    if (!Array.isArray(slots) || !slots.length) return;
    let box = card.querySelector("[data-ai-slots]");
    if (!box) {
      box = document.createElement("div");
      box.className = "ai-slots";
      box.setAttribute("data-ai-slots", "");
      card.append(box);
    }
    box.textContent = "";
    const selected = aiSelected(card);
    slots.forEach((slot) => {
      const job = slot && slot.job ? slot.job : {};
      const version = slot && slot.version ? slot.version : null;
      const alternative = (slot && slot.alternative) || "";
      const figure = document.createElement("figure");
      figure.className = "ai-slot";
      figure.setAttribute("data-ai-slot", alternative);
      figure.setAttribute("data-ai-selected", alternative && alternative === selected ? "true" : "false");
      if (slot && typeof slot.comment === "string") figure.setAttribute("data-ai-slot-comment", slot.comment);
      if (job.id) figure.setAttribute("data-ai-job", job.id);
      if (job.state) figure.setAttribute("data-ai-state", job.state);
      if (version && version.id) figure.setAttribute("data-ai-version", version.id);
      if (version && version.signature) figure.setAttribute("data-ai-signature", version.signature);
      if (version) figure.setAttribute("data-ai-approval", version.approval || "pending");
      if (version && version.path) {
        const image = document.createElement("img");
        image.setAttribute("src", version.path);
        image.setAttribute("alt", "Generated illustration");
        image.alt = "Generated illustration";
        figure.append(image);
      }
      const caption = document.createElement("figcaption");
      caption.textContent = job.error || job.state || "waiting";
      const button = document.createElement("button");
      button.setAttribute("type", "button");
      button.setAttribute("data-ai-choose", alternative);
      button.textContent = "Review this still";
      button.addEventListener("click", () => aiChooseSlot(card, slot));
      figure.append(caption, button);
      box.append(figure);
    });
  }
  function aiApplyState(body) {
    aiBoardBody = body && typeof body === "object" ? body : { beats: [], versions: [] };
    const beats = Array.isArray(body && body.beats) ? body.beats : [];
    const shared = Array.isArray(body && body.shared_references) ? body.shared_references : [];
    aiCards().forEach((card) => {
      const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
      if (!draft) return;
      draft.sharedReferences = shared.map((row) => row.context_id || row.error || "").sort().join("\u001f");
      let sharedNote = card.querySelector("[data-ai-shared-reference-note]");
      if (!sharedNote && shared.length) {
        sharedNote = document.createElement("p");
        sharedNote.setAttribute("data-ai-shared-reference-note", "");
        card.append(sharedNote);
      }
      if (sharedNote) sharedNote.textContent = shared.map((row) => row.error || "Shared style reference: " + [row.name, row.scope_instruction].filter(Boolean).join(" — ")).join(" · ");
      const beat = beats.find((row) => row && row.id === aiAttr(card, "data-ai-beat"));
      if (!beat || beat.active === false) {
        const inactiveJob = beat && beat.job && typeof beat.job === "object" ? beat.job : null;
        if (inactiveJob) {
          if (inactiveJob.state) card.setAttribute("data-ai-state", inactiveJob.state);
          const inactiveProgress = card.querySelector("[data-ai-progress]");
          if (inactiveProgress) inactiveProgress.textContent = inactiveJob.error || inactiveJob.state || "";
        }
        aiMarkStale(card);
        return;
      }
      const job = beat.job && typeof beat.job === "object" ? beat.job : null;
      if (job) {
        if (job.state) card.setAttribute("data-ai-state", job.state);
        const progress = card.querySelector("[data-ai-progress]");
        if (progress) progress.textContent = job.error || job.state || "";
      }
      if (beat.fingerprint !== draft.fingerprint) {
        aiMarkStale(card);
        return;
      }
      if (aiAttr(card, "data-ai-stale") === "true") {
        card.setAttribute("data-ai-stale", "false");
        aiNote(card, "data-ai-stale-note", "");
        aiLockModes(card);
      }
      aiRestoreChoice(card, draft, beat);
      const slotReview = Array.isArray(beat.slots) && beat.slots.length > 0;
      if (slotReview) {
        const flight = beat.slots.map((slot) => slot && slot.job).find((job) => job && AI_IN_FLIGHT.has(job.state));
        if (flight && flight.state) card.setAttribute("data-ai-state", flight.state);
        if (aiMode(card) === "images") {
          const slotProgress = card.querySelector("[data-ai-progress]");
          if (slotProgress) {
            slotProgress.textContent = beat.slots
              .map((slot) => {
                const slotJob = (slot && slot.job) || {};
                return (slot.alternative || slotJob.id || "slot") + ": " + (slotJob.error || slotJob.state || "waiting");
              })
              .join(" · ");
          }
        }
        aiPaintSlots(card, beat.slots);
      }
      aiHydrateFocus(card, draft, beat);
      const displayed = aiAttr(card, "data-ai-version");
      if (job && !displayed && draft.state === "pending" && job.id) {
        card.setAttribute("data-ai-job", job.id);
        draft.job = job.id;
      }
      const incoming = beat.version && typeof beat.version === "object" ? beat.version : null;
      const displayedSignature = aiAttr(card, "data-ai-signature");
      const sameStill = incoming && displayed && incoming.id === displayed && incoming.signature === displayedSignature;
      const firstStill = incoming && incoming.id && incoming.signature && !displayed && draft.state === "pending";
      if (!slotReview && (firstStill || sameStill)) {
        aiShowStill(card, incoming);
        if (firstStill) {
          draft.version = incoming.id;
          draft.signature = incoming.signature;
          draft.job = incoming.job || (job && job.id) || draft.job;
          const serverDecision = aiKnownDecision(incoming.approval);
          if (serverDecision) draft.state = serverDecision;
        }
        aiHideOffer(card);
      } else if (!slotReview && incoming && incoming.id && incoming.signature && displayed && (incoming.id !== displayed || incoming.signature !== displayedSignature)) {
        draft.offered = {
          id: incoming.id,
          signature: incoming.signature,
          path: incoming.path || "",
          approval: incoming.approval || "",
          job: incoming.job || (job && job.id) || "",
          width: incoming.width,
          height: incoming.height,
          codec: incoming.codec,
        };
        aiShowOffer(card);
      }
      const shown = firstStill || sameStill ? incoming : null;
      aiShowDiagnostics(card, job, shown || (displayed ? { id: displayed, signature: displayedSignature } : null));
      aiPaintDecision(card, draft);
      aiApplyBeatTiming(card, draft, beat);
      aiKeepApplyDraft(card, draft, beat);
    });
    aiEnsurePoll();
    paintGallery();
  }
  function aiMarkStale(card) {
    card.setAttribute("data-ai-stale", "true");
    aiNote(card, "data-ai-stale-note", "This scene changed. The current still and unsent text were kept.");
    aiHideOffer(card);
    aiLockModes(card);
  }
  function aiHideOffer(card) {
    const button = card.querySelector("[data-ai-new-result]");
    if (button) button.hidden = true;
  }
  function aiShowOffer(card) {
    let button = card.querySelector("[data-ai-new-result]");
    if (!button) {
      button = document.createElement("button");
      button.setAttribute("type", "button");
      button.setAttribute("data-ai-new-result", "");
      button.addEventListener("click", () => aiUseOffered(card));
      card.append(button);
    }
    button.hidden = false;
    button.textContent = "Show the new still";
  }
  function aiStoreDisplayed(draft, card, refreshContext) {
    if (!draft.version || !draft.signature) return;
    draft.versions = draft.versions || {};
    const key = draft.version + "\u001f" + draft.signature;
    const prior = draft.versions[key] && typeof draft.versions[key] === "object" ? draft.versions[key] : {};
    const source = card || aiCards().find((item) => aiAttr(item, "data-ai-beat") === draft.beat);
    const commentBox = source && source.querySelector("[data-ai-comment]");
    const liveComment = commentBox && typeof commentBox.value === "string" ? commentBox.value : draft.comment || "";
    const liveSelected = source ? (aiSelected(source) || draft.selected || "") : (draft.selected || "");
    const freeze = !refreshContext && typeof prior.comment === "string" && !!aiKnownDecision(prior.state);
    draft.versions[key] = {
      version: draft.version,
      signature: draft.signature,
      state: draft.state,
      job: draft.job || "",
      save: draft.save || "",
      comment: freeze ? prior.comment : liveComment,
      selected: freeze && typeof prior.selected === "string" ? prior.selected : liveSelected,
    };
  }
  function aiUseOffered(card) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    const offer = draft && draft.offered;
    if (!draft || !offer || !offer.id || !offer.signature || aiAttr(card, "data-ai-stale") === "true") return;
    aiStoreDisplayed(draft, card);
    aiShowStill(card, offer);
    const prior = (draft.versions || {})[offer.id + "\u001f" + offer.signature];
    draft.version = offer.id;
    draft.signature = offer.signature;
    draft.job = offer.job || "";
    draft.state = prior && aiKnownDecision(prior.state) ? prior.state : aiKnownDecision(offer.approval) || "pending";
    if (prior && prior.save === "failed") draft.save = "failed";
    else if (prior && prior.save === "pending") draft.save = "pending";
    else if (prior && prior.save === "local") draft.save = "local";
    else draft.save = "";
    card.setAttribute("data-ai-approval", draft.state);
    draft.offered = null;
    aiHideOffer(card);
    aiPaintDecision(card, draft);
    persist();
  }
  function aiPoll() {
    if (!aiLive()) return;
    const save = aiSaveConfig();
    fetch(String(save.aiUrl).replace(/\/$/, "") + "/state", {
      method: "GET",
      headers: { [save.header]: save.token },
    })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((body) => aiApplyState(body))
      .catch(() => {});
  }
  function aiEnsurePoll() {
    if (typeof setInterval !== "function" || typeof clearInterval !== "function") return;
    const needs = aiLive() && aiCards().some((card) => (
      AI_IN_FLIGHT.has(aiAttr(card, "data-ai-state")) || AI_IN_FLIGHT.has(aiAttr(card, "data-ai-video-state"))
    ));
    if (!needs) {
      if (aiPollTimer) clearInterval(aiPollTimer);
      aiPollTimer = 0;
      return;
    }
    if (aiPollTimer) return;
    aiPollTimer = setInterval(aiPoll, 1000);
  }
  function aiDecide(card, decision) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    const version = aiAttr(card, "data-ai-version");
    const signature = aiAttr(card, "data-ai-signature");
    if (!draft || !version || !signature || !LABELS[decision] || decision === "pending") return;
    if (aiAttr(card, "data-ai-stale") === "true") return;
    draft.state = decision;
    draft.version = version;
    draft.signature = signature;
    card.setAttribute("data-ai-approval", decision);
    draft.save = aiLive() ? "pending" : "local";
    draft.saveEpoch += 1;
    const ticket = draft.saveEpoch;
    aiStoreDisplayed(draft, card, true);
    aiPaintDecision(card, draft);
    persist();
    if (!aiLive()) return;
    const save = aiSaveConfig();
    const commentBox = card.querySelector("[data-ai-comment]");
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify({
        action: "review",
        beat: draft.beat,
        version,
        signature,
        decision,
        by: "Storyboard",
        comment: commentBox && typeof commentBox.value === "string" ? commentBox.value : draft.comment,
      }),
    })
      .then((response) => Promise.resolve()
        .then(() => response.json())
        .then((body) => ({ ok: response.ok, body }))
        .catch(() => ({ ok: response.ok, body: {} })))
      .then((result) => {
        if (draft.saveEpoch !== ticket || draft.version !== version || draft.signature !== signature) return;
        draft.save = result.ok ? "saved" : "failed";
        aiStoreDisplayed(draft, card);
        aiPaintDecision(card, draft);
        persist();
      })
      .catch(() => {
        if (draft.saveEpoch !== ticket || draft.version !== version || draft.signature !== signature) return;
        draft.save = "failed";
        aiStoreDisplayed(draft, card);
        aiPaintDecision(card, draft);
        persist();
      });
  }
  function aiFinite(input) {
    if (!input || typeof input.value !== "string" || !input.value.trim()) return null;
    const number = Number(input.value);
    return Number.isFinite(number) ? number : null;
  }
  function aiChosenFile(card) {
    const input = card.querySelector("[data-ai-file]");
    const files = input && input.files;
    if (!files || !files.length) return null;
    return files[0] || null;
  }
  function aiDeclaredType(file) {
    const type = file && file.type;
    if (type === "image/png" || type === "image/jpeg" || type === "video/mp4") return type;
    const name = String((file && file.name) || "").toLowerCase();
    if (name.endsWith(".png")) return "image/png";
    if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
    if (name.endsWith(".mp4")) return "video/mp4";
    return "";
  }
  function aiVideoFile(file) {
    return aiDeclaredType(file) === "video/mp4";
  }
  function aiApplyInstruction(card) {
    const box = card.querySelector("[data-ai-instruction]");
    return box && typeof box.value === "string" ? box.value.trim() : "";
  }
  function aiReferenceInstruction(card, draft) {
    const typed = aiApplyInstruction(card);
    if (typed) return typed;
    const comment = card.querySelector("[data-ai-comment]");
    if (comment && typeof comment.value === "string" && comment.value.trim()) return comment.value.trim();
    return typeof draft.comment === "string" ? draft.comment.trim() : "";
  }
  function aiScopeChoice(card) {
    const scope = card.querySelector("[data-ai-scope]");
    const value = scope && scope.value === "shared" ? "shared" : "beat";
    const extra = card.querySelector("[data-ai-scope-instruction]");
    const text = (extra && typeof extra.value === "string" ? extra.value.trim() : "") || aiApplyInstruction(card);
    if (value === "shared" && !text) return { ok: false, scope: value, scope_instruction: "" };
    return { ok: true, scope: value, scope_instruction: value === "shared" ? text : "" };
  }
  function aiIntervalChoice(card, file) {
    if (!aiVideoFile(file)) return { ok: true, interval: null };
    const start = aiFinite(card.querySelector("[data-ai-interval-start]"));
    const end = aiFinite(card.querySelector("[data-ai-interval-end]"));
    if (start == null && end == null) return { ok: true, interval: null };
    if (start == null || end == null || !(end > start)) return { ok: false, interval: null };
    return { ok: true, interval: { start_s: start, end_s: end } };
  }
  function aiFileBytes(file) {
    if (file && typeof file.arrayBuffer === "function") return file.arrayBuffer();
    if (file && file.bytes != null) return Promise.resolve(file.bytes);
    return Promise.resolve(null);
  }
  function aiReferenceUrl(save) {
    if (save.aiReferenceUrl) return String(save.aiReferenceUrl).replace(/\/$/, "");
    return String(save.aiUrl).replace(/\/$/, "") + "/reference";
  }
  function aiJsonResult(response) {
    return Promise.resolve()
      .then(() => response.json())
      .then((body) => ({ ok: response.ok, body }))
      .catch(() => ({ ok: response.ok, body: {} }));
  }
  function aiPreviewReference(card, contextId, kind) {
    const save = aiSaveConfig();
    if (!save || !contextId) return;
    card.setAttribute("data-ai-reference-context", contextId);
    const part = kind === "video" ? "sheet" : "pixels";
    const url = aiReferenceUrl(save) + "/" + encodeURIComponent(contextId) + "?part=" + part;
    fetch(url, { method: "GET", headers: { [save.header]: save.token } })
      .then((response) => (response.ok && typeof response.blob === "function" ? response.blob() : null))
      .then((blob) => {
        if (!blob || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
        const image = card.querySelector("[data-ai-reference-preview]");
        if (!image || aiAttr(card, "data-ai-reference-context") !== contextId) return;
        if (image.src && String(image.src).startsWith("blob:")) URL.revokeObjectURL(image.src);
        const preview = URL.createObjectURL(blob);
        if (String(preview).includes("ai-data")) return;
        image.hidden = false;
        image.alt = "Private reference preview";
        image.src = preview;
      })
      .catch(() => {});
  }
  function aiKeepApplyDraft(card, draft, beat) {
    const box = card.querySelector("[data-ai-instruction]");
    if (box && draft.instructionDirty && typeof draft.instruction === "string") box.value = draft.instruction;
    if (draft.fileUnsent) aiNote(card, "data-ai-file-note", "Selected, not sent.");
    if (beat && !draft.referenceBusy) {
      const shown = beat.reference || beat.guidance;
      const still = shown && beat.reference ? (shown.target_still || aiStillTarget(card)) : null;
      if (!still || still.id === aiAttr(card, "data-ai-version")) {
        draft.referenceId = shown ? shown.context_id || "" : "";
        draft.referenceTarget = { still, context: draft.referenceId };
        if (shown && shown.error) {
          aiClearReferencePreview(card);
          aiNote(card, "data-ai-reference-note", shown.error);
        } else if (shown && shown.context_id && aiAttr(card, "data-ai-reference-context") !== shown.context_id) {
          aiPreviewReference(card, shown.context_id, shown.kind);
          aiNote(card, "data-ai-reference-note", [shown.name, shown.instructions].filter(Boolean).join(": "));
        } else if (!shown) aiClearReferencePreview(card);
      }
    }
    aiLockModes(card);
  }
  function aiClearReferencePreview(card) {
    card.removeAttribute("data-ai-reference-context");
    const image = card.querySelector("[data-ai-reference-preview]");
    if (image) {
      if (image.src && String(image.src).startsWith("blob:") && typeof URL !== "undefined") URL.revokeObjectURL(image.src);
      image.removeAttribute("src");
      image.hidden = true;
    }
    aiNote(card, "data-ai-reference-note", "");
  }
  function aiStillTarget(card) {
    const id = aiAttr(card, "data-ai-version");
    const signature = aiAttr(card, "data-ai-signature");
    return id && signature ? { id, signature } : null;
  }
  function aiRememberFile(card, draft) {
    const file = aiChosenFile(card);
    draft.uploadEpoch = (draft.uploadEpoch || 0) + 1;
    draft.fileName = file ? (file.name || "attachment") : "";
    draft.fileUnsent = !!file;
    aiNote(card, "data-ai-file-note", file ? "Selected, not sent." : "");
    persist();
  }
  function aiSendReference(card, draft, file) {
    const save = aiSaveConfig();
    if (!save || !file || draft.referenceBusy) {
      aiNote(card, "data-ai-file-note", "Choose a PNG, JPEG, or MP4. Nothing was sent.");
      return Promise.resolve(false);
    }
    if (draft.referenceTarget && draft.referenceTarget.still && JSON.stringify(draft.referenceTarget.still) !== JSON.stringify(aiStillTarget(card))) {
      aiNote(card, "data-ai-file-note", "The displayed still changed. Refreshing its reference context; the file stays selected.");
      aiPoll();
      return Promise.resolve(false);
    }
    const declared = aiDeclaredType(file);
    const instructions = aiReferenceInstruction(card, draft);
    if (!declared || !instructions) {
      aiNote(card, "data-ai-file-note", "Type what this reference is for. Nothing was sent.");
      return Promise.resolve(false);
    }
    const interval = aiIntervalChoice(card, file);
    if (!interval.ok) {
      aiNote(card, "data-ai-file-note", "Name both ends of the video interval. Nothing was sent.");
      return Promise.resolve(false);
    }
    const scoped = aiScopeChoice(card);
    if (!scoped.ok) {
      aiNote(card, "data-ai-file-note", "Shared style needs an explicit scope instruction. Nothing was sent.");
      return Promise.resolve(false);
    }
    const still = draft.referenceId && draft.referenceTarget ? draft.referenceTarget.still : aiStillTarget(card);
    const displayed = JSON.stringify(aiStillTarget(card));
    const uploadEpoch = draft.uploadEpoch;
    const roleBox = card.querySelector("[data-ai-role]");
    const metadata = {
      beat: draft.beat,
      fingerprint: draft.fingerprint,
      identity: "up-" + aiHash(JSON.stringify([
        draft.beat, draft.fingerprint, still, file.name, uploadEpoch, instructions,
        roleBox && roleBox.value, scoped, interval.interval,
      ])),
      name: file.name || "attachment",
      declared_type: declared,
      instructions,
      role: roleBox && roleBox.value ? roleBox.value : "guidance",
      scope: scoped.scope,
    };
    if (scoped.scope === "shared") metadata.scope_instruction = scoped.scope_instruction;
    if (still) metadata.still = still;
    if (interval.interval) metadata.interval = interval.interval;
    if (draft.referenceId) {
      metadata.replace = true;
      metadata.context = draft.referenceId;
    }
    draft.referenceBusy = true;
    return aiFileBytes(file).then((bytes) => {
      if (!bytes) {
        aiNote(card, "data-ai-file-note", "The selected file had no bytes. Nothing was sent.");
        return false;
      }
      return fetch(aiReferenceUrl(save), {
        method: "POST",
        headers: {
          [save.header]: save.token,
          "X-GetBrolls-Ai-Reference": encodeURIComponent(JSON.stringify(metadata)),
        },
        body: bytes,
      })
        .then(aiJsonResult)
        .then((result) => {
          const reference = result.ok && result.body ? result.body.reference : null;
          if (!reference || !reference.context_id) {
            aiNote(card, "data-ai-file-note", (result.body && result.body.error) || "The reference was not kept.");
            return false;
          }
          if (displayed === JSON.stringify(aiStillTarget(card))) {
            draft.referenceId = reference.context_id;
            draft.referenceTarget = { still, context: reference.context_id };
          }
          if (uploadEpoch === draft.uploadEpoch && displayed === JSON.stringify(aiStillTarget(card))) {
            draft.fileUnsent = false;
            const input = card.querySelector("[data-ai-file]");
            if (input) input.value = "";
            aiNote(card, "data-ai-file-note", "Reference kept. It was not sent for generation.");
            aiNote(card, "data-ai-reference-note", [reference.name || file.name, reference.instructions || instructions].filter(Boolean).join(": "));
            aiPreviewReference(card, reference.context_id, reference.kind);
          }
          persist();
          return reference.context_id;
        })
        .catch(() => {
          aiNote(card, "data-ai-file-note", "The reference was not kept.");
          return false;
        });
    }).catch(() => {
      aiNote(card, "data-ai-file-note", "The reference was not kept. Choose the file again to retry.");
      return false;
    }).finally(() => { draft.referenceBusy = false; aiPoll(); });
  }
  function aiKeepReference(card) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!draft) return;
    if (!aiLive()) {
      draft.fileUnsent = !!draft.fileName || !!aiChosenFile(card);
      aiNote(card, "data-ai-file-note", "Selected, not sent.");
      persist();
      return;
    }
    const button = card.querySelector("[data-ai-upload]");
    if (button && button.disabled) return;
    aiSendReference(card, draft, aiChosenFile(card));
  }
  function aiRemoveReference(card) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!draft) return;
    if (!aiLive()) {
      aiNote(card, "data-ai-apply-note", "Selected, not sent.");
      persist();
      return;
    }
    const button = card.querySelector("[data-ai-remove-reference]");
    if ((button && button.disabled) || draft.referenceBusy) return;
    const save = aiSaveConfig();
    const payload = { action: "reference-remove", beat: draft.beat, expected: draft.fingerprint };
    if (!draft.referenceId || !draft.referenceTarget) return;
    const target = draft.referenceTarget;
    if (target.still && JSON.stringify(target.still) !== JSON.stringify(aiStillTarget(card))) {
      aiNote(card, "data-ai-apply-note", "The displayed still changed. Refreshing its reference context before removal.");
      aiPoll();
      return;
    }
    const displayed = JSON.stringify(aiStillTarget(card));
    if (target.still) payload.still = target.still;
    payload.context = draft.referenceId;
    draft.referenceBusy = true;
    fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify(payload),
    })
      .then(aiJsonResult)
      .then((result) => {
        if (!result.ok) {
          aiNote(card, "data-ai-apply-note", (result.body && result.body.error) || "The reference was not removed.");
          return;
        }
        if (draft.referenceTarget === target && displayed === JSON.stringify(aiStillTarget(card))) {
          draft.referenceId = "";
          draft.referenceTarget = null;
          aiClearReferencePreview(card);
        }
        aiNote(card, "data-ai-file-note", draft.fileUnsent ? "Selected, not sent." : "Reference removed. Earlier media stays.");
        persist();
      })
      .catch(() => aiNote(card, "data-ai-apply-note", "The reference was not removed."))
      .finally(() => { draft.referenceBusy = false; aiPoll(); });
  }
  function aiPostApply(card, draft, instruction, frozen) {
    const save = aiSaveConfig();
    const stillId = frozen.still ? frozen.still.id : "";
    const signature = frozen.still ? frozen.still.signature : "";
    const scoped = frozen.scope;
    if (!scoped.ok) {
      aiNote(card, "data-ai-apply-note", "Shared style needs an explicit scope instruction.");
      return;
    }
    const nonce = "apply-" + aiHash([
      "apply", draft.beat, draft.fingerprint, stillId, signature, frozen.referenceId || "", instruction,
      JSON.stringify(scoped), String(frozen.uploadEpoch || 0),
    ].join("\u001f"));
    if (aiLaunched.has(nonce)) return;
    aiLaunched.add(nonce);
    const payload = {
      action: "apply",
      beat: draft.beat,
      expected: draft.fingerprint,
      instruction,
      nonce,
      requestId: nonce,
    };
    if (stillId && signature) payload.still = { id: stillId, signature };
    if (scoped.scope === "shared") {
      payload.scope = "shared";
      payload.scope_instruction = scoped.scope_instruction;
    }
    if (frozen.referenceId) payload.reference = frozen.referenceId;
    return fetch(save.aiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", [save.header]: save.token },
      body: JSON.stringify(payload),
    })
      .then(aiJsonResult)
      .then((result) => {
        const job = result.ok && result.body ? result.body.job : null;
        if (!result.ok || !job) {
          aiLaunched.delete(nonce);
          aiNote(card, "data-ai-apply-note", (job && job.error) || (result.body && result.body.error) || "Apply was not started.");
          return;
        }
        if (job.state && JSON.stringify(aiStillTarget(card)) === JSON.stringify(frozen.still)) card.setAttribute("data-ai-state", job.state);
        const progress = card.querySelector("[data-ai-progress]");
        if (progress) progress.textContent = job.error || job.state || "";
        aiNote(card, "data-ai-apply-note", "");
        aiPoll();
        aiEnsurePoll();
      })
      .catch(() => {
        aiLaunched.delete(nonce);
        aiNote(card, "data-ai-apply-note", "Apply was not started.");
      });
  }
  function aiApply(card) {
    const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
    if (!draft) return;
    if (!aiLive()) {
      aiNote(card, "data-ai-apply-note", "Selected, not sent.");
      if (draft.fileName || aiChosenFile(card)) {
        draft.fileUnsent = true;
        aiNote(card, "data-ai-file-note", "Selected, not sent.");
      }
      persist();
      return;
    }
    const button = card.querySelector("[data-ai-apply]");
    if ((button && button.disabled) || draft.applyPending || draft.referenceBusy) return;
    const instruction = aiApplyInstruction(card);
    if (!instruction) {
      aiNote(card, "data-ai-apply-note", "Type the Apply instruction.");
      return;
    }
    draft.instruction = instruction;
    draft.instructionDirty = true;
    const file = draft.fileUnsent ? aiChosenFile(card) : null;
    if (draft.fileUnsent && !file) {
      aiNote(card, "data-ai-apply-note", "Choose the unsent file again before Apply.");
      return;
    }
    const frozen = {
      still: aiStillTarget(card), scope: aiScopeChoice(card),
      referenceId: draft.referenceId, uploadEpoch: draft.uploadEpoch,
    };
    draft.applyPending = true;
    const done = () => { draft.applyPending = false; };
    if (file) {
      aiSendReference(card, draft, file).then((context) => {
        if (!context) return;
        frozen.referenceId = context;
        return aiPostApply(card, draft, instruction, frozen);
      }).finally(done);
      return;
    }
    Promise.resolve(aiPostApply(card, draft, instruction, frozen)).finally(done);
  }
  function mountAi() {
    const cards = aiCards();
    if (!cards.length && !aiRows.length) return;
    cards.forEach((card) => {
      if (card.dataset.aiWired === "1") return;
      card.setAttribute("data-ai-wired", "1");
      const beat = aiAttr(card, "data-ai-beat");
      if (!beat) return;
      const draft = aiLoadDraft(card);
      aiDrafts[beat] = draft;
      if (!reviewTargets.some((target) => target.aiCard === card)) reviewTargets.push({ decision: draft, aiCard: card });
      aiLockModes(card);
      aiPaintDecision(card, draft);
      if (draft.version) {
        const review = card.querySelector(".ai-review");
        if (review) review.hidden = false;
      }
      card.addEventListener("click", () => aiSetCurrent(card));
      card.querySelectorAll("[data-ai-alternative]").forEach((radio) => {
        radio.addEventListener("change", () => {
          if (radio.checked) {
            card.querySelectorAll("[data-ai-alternative]").forEach((other) => {
              if (other !== radio) other.checked = false;
            });
          }
          draft.selected = aiSelected(card);
          draft.selectedDirty = true;
          aiSetCurrent(card);
          persist();
          aiScheduleSelect(card);
        });
      });
      const comment = card.querySelector("[data-ai-comment]");
      if (comment) {
        comment.addEventListener("input", () => {
          draft.comment = comment.value;
          draft.commentDirty = true;
          aiSetCurrent(card);
          persist();
          aiScheduleSelect(card);
        });
      }
      const mode = card.querySelector("[data-ai-mode]");
      if (mode) {
        mode.addEventListener("change", () => {
          draft.mode = aiMode(card);
          draft.modeDirty = true;
          aiLockModes(card);
          aiSetCurrent(card);
          persist();
          aiScheduleSelect(card);
        });
      }
      card.querySelectorAll("[data-ai-choose]").forEach((button) => {
        button.addEventListener("click", () => aiChooseButton(card, button));
      });
      const generate = card.querySelector("[data-ai-generate]");
      if (generate) generate.addEventListener("click", () => aiGenerate(card));
      const instruction = card.querySelector("[data-ai-instruction]");
      if (instruction) {
        instruction.addEventListener("input", () => {
          draft.instruction = instruction.value;
          draft.instructionDirty = true;
          persist();
        });
      }
      const referenceFile = card.querySelector("[data-ai-file]");
      if (referenceFile) referenceFile.addEventListener("change", () => aiRememberFile(card, draft));
      const upload = card.querySelector("[data-ai-upload]");
      if (upload) upload.addEventListener("click", () => aiKeepReference(card));
      const removeReference = card.querySelector("[data-ai-remove-reference]");
      if (removeReference) removeReference.addEventListener("click", () => aiRemoveReference(card));
      const apply = card.querySelector("[data-ai-apply]");
      if (apply) apply.addEventListener("click", () => aiApply(card));
      card.querySelectorAll("[data-ai-decision]").forEach((button) => {
        button.addEventListener("click", () => aiDecide(card, aiAttr(button, "data-ai-decision")));
      });
      aiEnsureTimingControls(card, draft);
      aiEnsureVideoControls(card, draft);
    });
    if (aiLive()) aiPoll();
    aiEnsurePoll();
    paintGallery();
  }
  function aiVersionRow(card, draft, entry, historical) {
    const commentBox = card.querySelector("[data-ai-comment]");
    const state = entry.state || "pending";
    const liveComment = commentBox && typeof commentBox.value === "string" ? commentBox.value : draft.comment || "";
    const liveSelected = aiSelected(card) || draft.selected || "";
    return {
      id: "ai:" + draft.beat,
      project: data.project,
      beat: draft.beat,
      fingerprint: draft.fingerprint || aiAttr(card, "data-ai-fingerprint"),
      selected: historical && typeof entry.selected === "string" ? entry.selected : liveSelected,
      comment: historical && typeof entry.comment === "string" ? entry.comment : liveComment,
      mode: draft.mode === "images" ? "images" : "economy",
      job: entry.job || null,
      version: entry.version || "",
      signature: entry.signature || "",
      state,
      decision: state,
    };
  }
  function exportAiRows() {
    const cards = aiCards();
    if (!cards.length) return aiRows.map((row) => ({ ...row }));
    const fromCards = [];
    cards.forEach((card) => {
      const beat = aiAttr(card, "data-ai-beat");
      const draft = aiDrafts[beat] || { beat, versions: {} };
      const decided = draft.state && draft.state !== "pending";
      const bound = decided && (draft.versions || {})[draft.version + "\u001f" + draft.signature];
      const displayed = aiVersionRow(card, draft, {
        version: decided && draft.version ? draft.version : aiAttr(card, "data-ai-version") || draft.version || "",
        signature: decided && draft.signature ? draft.signature : aiAttr(card, "data-ai-signature") || draft.signature || "",
        state: draft.state || "pending",
        job: aiAttr(card, "data-ai-job") || draft.job || "",
        ...(bound ? { comment: bound.comment, selected: bound.selected } : {}),
      }, !!decided);
      fromCards.push(displayed);
      const seen = new Set([displayed.version]);
      Object.values(draft.versions || {}).forEach((entry) => {
        if (!entry || !entry.version || seen.has(entry.version)) return;
        seen.add(entry.version);
        fromCards.push(aiVersionRow(card, draft, entry, true));
      });
    });
    const used = new Set(fromCards.map((row) => row.beat + "\u001f" + row.version));
    const leftovers = aiRows.filter((row) => row && !used.has((row.beat || "") + "\u001f" + (row.version || "")));
    return [...fromCards, ...leftovers.map((row) => ({ ...row }))];
  }
  function persist() {
    try {
      if (items.length) localStorage.setItem(key, JSON.stringify(decisions));
      if (graphicsRows.length) localStorage.setItem(graphicsKey, JSON.stringify(graphicsDecisions));
      if (alignmentRows.length) localStorage.setItem(alignmentKey, JSON.stringify(alignmentDecisions));
      if (aiCards().length || aiRows.length) {
        const stored = {};
        aiCards().forEach((card) => {
          const draft = aiDrafts[aiAttr(card, "data-ai-beat")];
          if (draft) stored[draft.beat] = aiRemember(draft);
        });
        localStorage.setItem(aiKey, JSON.stringify(stored));
      }
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
          if (target.aiCard) {
            if (!aiDisplayedStill(target.aiCard)) continue;
            aiSetCurrent(target.aiCard);
            target.aiCard.scrollIntoView?.({ block: "start" });
          } else if (target.row) {
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
      if (comment) {
        comment.value = d.comment;
        comment.readOnly = !!row.activeReferences && row.current === false;
      }
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
      if (change && row.activeReferences) change.disabled = row.current === false;
      const edit = panel.querySelector("[data-graphics-edit]");
      if (edit) edit.hidden = row.current === false;
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
        const replaceLabel = panel.dataset.replaceReference;
        delete panel.dataset.replaceReference;
        imageInput.multiple = true;
        const retained = savedReferences(graphicsDecisions[boundId]);
        const previous = referenceFiles.get(boundId) || [];
        const used = new Set([...retained, ...previous].map(entry => entry.label));
        if ((replaceLabel && files.length !== 1) || used.size + (replaceLabel ? 0 : files.length) > 8 ||
            files.reduce((sum, file) => sum + file.size, 0) + retained.filter(ref => ref.label !== replaceLabel && !previous.some(e => e.label === ref.label)).reduce((sum, ref) => sum + ref.bytes, 0) + previous.filter(e => e.label !== replaceLabel).reduce((sum, e) => sum + e.file.size, 0) > 134217728) {
          status.textContent = "Choose at most 8 references and 128 MiB in total.";
          return;
        }
        const entries = files.map(file => {
          const label = replaceLabel || Array.from({length: 8}, (_, i) => "R" + (i + 1)).find(label => !used.has(label));
          used.add(label);
          return {file, label, kind: /\.mp4$/i.test(file.name) || file.type === "video/mp4" ? "video" : "image"};
        });
        if (entries.some(entry => entry.file.size > (entry.kind === "video" ? 67108864 : 16777216))) {
          status.textContent = "Each PNG/JPEG may be at most 16 MiB; each MP4/H.264 at most 64 MiB.";
          return;
        }
        releasePreviews(previous.filter(entry => entry.label === replaceLabel));
        referenceFiles.set(boundId, [...previous.filter(entry => entry.label !== replaceLabel), ...entries.map(entry => ({...entry, url: URL.createObjectURL(entry.file)}))]);
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
    const edit = panel.querySelector("[data-graphics-edit]");
    if (edit) edit.onclick = () => {
      pending = "changes";
      panel.dataset.asking = "1";
      reveal(true);
      if (confirm) confirm.hidden = false;
      checkComment();
      comment?.focus();
    };
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
    mountAi();
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
    if (decision.state === "changes" && decision.referenceBase && row.current !== false) {
      const unchanged = row.referenceBase && decision.comment === row.comment && decision.scope === row.scope &&
        JSON.stringify(savedReferences(decision)) === JSON.stringify(row.references || []);
      payload.referenceBase = unchanged ? row.referenceBase : decision.referenceBase;
      payload.references = savedReferences(decision);
      delete payload.reference;
      if (!unchanged) {
        delete payload.reference_change;
        delete payload.reference_application;
        delete payload.shared_request_id;
      }
      const unchangedLegacy = row.state === "changes" && !row.reference_change && decision.comment === row.comment &&
        decision.scope === row.scope && JSON.stringify(savedReferences(decision)) === JSON.stringify(row.activeReferences?.references || []);
      if (unchangedLegacy) {
        delete payload.referenceBase;
        delete payload.references;
        if (row.references) payload.references = row.references;
        if (row.reference) payload.reference = row.reference;
      }
    }
    if (row.activeReferences && row.current === false && decision.state === "changes") {
      payload.state = "pending";
      delete payload.reference;
      delete payload.references;
      delete payload.referenceBase;
      delete payload.reference_change;
      delete payload.reference_application;
      delete payload.shared_request_id;
    }
    if (row.activeReferences && row.state === "approved" && decision.state === row.state && decision.comment === row.comment) {
      payload.state = "pending";
    }
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
    if (aiCards().length || aiRows.length) result.ai = exportAiRows();
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
            note("The reference save was not confirmed; it may already be in the project. Keep this draft and retry the same request; no media package was downloaded.");
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
    document.querySelectorAll("details.graphics-details, details.narration-details, details.graphics-passage, details.ai-details").forEach((detail) => {
      if (!printDisclosureState.has(detail)) printDisclosureState.set(detail, detail.open);
      detail.open = true;
    });
  });
  window.addEventListener("afterprint", () => {
    printDisclosureState.forEach((open, detail) => { detail.open = open; });
    printDisclosureState.clear();
  });
})();
