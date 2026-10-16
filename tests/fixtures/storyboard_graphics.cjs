// Graphics-only and mixed Storyboard review: decisions, version drafts, export, save.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tag = String(tag).toLowerCase();
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.dataset = {};
    this.className = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this._text = "";
    this.onclick = null;
    this.onchange = null;
    this.oninput = null;
    this.listeners = {};
    this.style = {};
  }
  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join("");
    return this._text;
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get innerHTML() {
    return this._text;
  }
  set innerHTML(value) {
    this._text = String(value);
  }
  matches(selector) {
    if (selector.startsWith("#")) return this.attrs.id === selector.slice(1);
    if (selector.startsWith(".")) return this.className.split(/\s+/).includes(selector.slice(1));
    const attr = selector.match(/^\[([^\]]+)\]$/);
    if (attr) {
      const [name, raw] = attr[1].split("=");
      const key = name.replace(/^data-/, "");
      const datasetKey = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      const actual = this.dataset[datasetKey] ?? this.attrs[name];
      if (raw == null) return actual != null;
      return String(actual) === raw.replace(/^["']|["']$/g, "");
    }
    return this.tag === selector;
  }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    if (parts.length > 1) {
      const [first, ...rest] = parts;
      return this.querySelectorAll(first).flatMap((node) => node.querySelectorAll(rest.join(" ")));
    }
    return this.children.flatMap((child) => [
      ...(child.matches(selector) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  closest(selector) {
    let node = this;
    while (node) {
      if (node.matches(selector)) return node;
      node = node.parentNode;
    }
    return null;
  }
  append(...nodes) {
    nodes.forEach((node) => {
      if (typeof node === "string") {
        const text = new Element("#text");
        text.textContent = node;
        node = text;
      }
      node.parentNode = this;
      this.children.push(node);
    });
  }
  prepend(node) {
    node.parentNode = this;
    this.children.unshift(node);
  }
  appendChild(node) {
    this.append(node);
    return node;
  }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  getAttribute(name) {
    if (name === "class") return this.className;
    return this.attrs[name] ?? null;
  }
  addEventListener(name, handler) {
    this.listeners[name] = this.listeners[name] || [];
    this.listeners[name].push(handler);
  }
  dispatchEvent(event) {
    const name = event.type;
    const handler = this["on" + name];
    if (typeof handler === "function") handler(event);
    (this.listeners[name] || []).forEach((fn) => fn(event));
    return true;
  }
  click() {
    if (typeof this.onclick === "function") this.onclick();
    (this.listeners.click || []).forEach((fn) => fn());
  }
  focus() {}
  pause() { this.paused = true; }
  scrollIntoView() {
    this.scrolled = true;
  }
  get classList() {
    const el = this;
    return {
      add(name) {
        const parts = new Set(el.className.split(/\s+/).filter(Boolean));
        parts.add(name);
        el.className = [...parts].join(" ");
      },
      toggle(name, force) {
        const parts = new Set(el.className.split(/\s+/).filter(Boolean));
        const on = force == null ? !parts.has(name) : !!force;
        if (on) parts.add(name);
        else parts.delete(name);
        el.className = [...parts].join(" ");
        return on;
      },
      contains(name) {
        return el.className.split(/\s+/).includes(name);
      },
    };
  }
}

function el(tag, attrs = {}, children = []) {
  const node = new Element(tag);
  Object.entries(attrs).forEach(([name, value]) => {
    if (name === "className") node.className = value;
    else if (name === "dataset") Object.assign(node.dataset, value);
    else if (name === "text") node.textContent = value;
    else node.setAttribute(name, value);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function graphicsRow(overrides) {
  return {
    id: "graphics:stat-01:v1",
    project: "synthetic-graphics",
    scene_id: "numeric-stat",
    occurrence_id: "stat-01",
    version: "v1",
    parent: null,
    current: true,
    signature: "aa".repeat(32),
    reviewEpoch: "epoch-v1",
    state: "pending",
    comment: "",
    scope: "scene",
    requestId: null,
    timing_basis: "estimated",
    artifact: "previews/graphics-stat-01-v1.mp4",
    approval: null,
    readiness: { complete: true, reviewable: true, approved: false, deliverable: false, reasons: ["estimated_timing"] },
    versions: [{ id: "v1", parent: null, status: "complete" }],
    requests: [],
    context: {
      chapter_context: "Original chapter\ncontext",
      narration: "The count stands at twelve units.",
      purpose: "Show the count",
      timing: { basis: "estimated", duration_s: 3, duration_in_frames: 90 },
      anchors: [{ text: "Original & anchor" }],
      questions: [],
      proposed_scenes: [],
      props: { value: "12", unit: "units", label: "Synthetic count", claim_status: "synthetic", claim_note: "Synthetic draft value." },
      style_revision: 1,
    },
    ...overrides,
  };
}

function versionPane(row) {
  const pane = el("div", {
    className: row.current ? "graphics-version is-shown" : "graphics-version",
    "data-version": row.version,
    "data-row-id": row.id,
    "data-current": String(!!row.current),
  });
  pane.dataset.version = row.version;
  pane.dataset.rowId = row.id;
  pane.dataset.current = String(!!row.current);
  const video = el("video", { className: "graphics-preview", src: row.artifact });
  if (row.vo_preview) pane.append(el("audio", { className: "graphics-vo-preview", src: row.vo_preview.ref }));
  const record = el("p", { "data-graphics-decision-record": "", className: "graphics-decision-record" });
  record.dataset.graphicsDecisionRecord = "";
  pane.append(video, el("p", { className: "graphics-original", text: row.context.narration }), record);
  return pane;
}

function graphicsCard(rows) {
  const current = rows.find((row) => row.current) || rows[0];
  const card = el("article", { className: "graphics-card" });
  card.dataset.occurrence = current.occurrence_id;
  const display = el("select", { "data-graphics-display": "" });
  display.dataset.graphicsDisplay = "";
  const compare = el("select", { "data-graphics-compare": "" });
  compare.dataset.graphicsCompare = "";
  compare.append(el("option", { value: "", text: "None" }));
  rows.forEach((row, index) => {
    const label = `v${index + 1}`;
    const option = el("option", { value: row.version, text: label });
    if (row.current) option.attrs.selected = "selected";
    display.append(option);
    compare.append(el("option", { value: row.version, text: label }));
  });
  display.value = current.version;
  compare.value = "";
  const tools = el("div", { className: "graphics-version-tools" }, [display, compare]);
  const versions = el("div", { className: "graphics-versions" }, rows.map(versionPane));
  const currentBasis =
    (current.context && current.context.timing && current.context.timing.basis) ||
    current.timing_basis ||
    "";
  const badge = el("span", {
    className: "timing-basis" + (currentBasis ? " " + currentBasis : ""),
    text: currentBasis === "estimated" ? "Estimated draft timing" : "Explicit narration timing",
  });
  const meta = el("p", { className: "graphics-meta" }, [badge]);
  const comment = el("textarea", { "data-graphics-comment": "" });
  const imageInput = el("input", { type: "file", "data-graphics-reference": "" });
  const referencePreview = el("div", { "data-graphics-reference-preview": "" });
  comment.dataset.graphicsComment = "";
  const shared = el("input", { type: "checkbox", "data-graphics-shared": "" });
  shared.dataset.graphicsShared = "";
  const approve = el("button", { "data-graphics-decision": "approved" });
  approve.dataset.graphicsDecision = "approved";
  const changes = el("button", { "data-graphics-decision": "changes" });
  changes.dataset.graphicsDecision = "changes";
  const toggle = el("button", { className: "comment-toggle", text: "Comment" });
  const confirm = el("button", { className: "confirm-review" });
  confirm.hidden = true;
  const fields = el("div", { className: "review-fields" }, [comment, imageInput, referencePreview, shared, confirm]);
  fields.hidden = true;
  const detailPanes = rows.map((row) => {
    const pane = el("div", {
      className: "graphics-version-details",
      "data-version": row.version,
    });
    pane.dataset.version = row.version;
    return pane;
  });
  const details = el("details", { className: "graphics-details" }, [
    ...detailPanes,
    toggle,
    el("p", { "data-graphics-readiness": "", className: "graphics-readiness" }),
    el("div", { "data-graphics-requests": "", className: "graphics-request-status" }),
  ]);
  const panel = el("section", { className: "graphics-review-panel" }, [
    el("div", { className: "graphics-review-actions review-actions" }, [approve, changes]),
    fields,
    details,
    el("p", { "data-graphics-status": "", className: "feedback" }),
  ]);
  panel.querySelector("[data-graphics-readiness]").dataset.graphicsReadiness = "";
  panel.querySelector("[data-graphics-requests]").dataset.graphicsRequests = "";
  panel.querySelector("[data-graphics-status]").dataset.graphicsStatus = "";
  card.append(meta);
  const voiceStatus = el("span", { className: "graphics-vo-status", text: "Без озвучки" });
  card.append(voiceStatus, tools);
  compare.disabled = rows.length <= 1;
  card.append(versions, panel);
  return card;
}

function candidatePanel() {
  const comment = el("textarea", { "data-comment": "" });
  comment.dataset.comment = "";
  const suggestion = el("input", { "data-suggestion": "" });
  suggestion.dataset.suggestion = "";
  const alternative = el("input", { type: "checkbox", "data-alternative": "" });
  alternative.dataset.alternative = "";
  const approve = el("button", { "data-decision": "approved" });
  approve.dataset.decision = "approved";
  const changes = el("button", { "data-decision": "changes" });
  changes.dataset.decision = "changes";
  const reject = el("button", { "data-decision": "rejected" });
  reject.dataset.decision = "rejected";
  const panel = el("section", { className: "review-panel" }, [
    el("div", { className: "review-actions" }, [approve, changes, reject]),
    el("button", { className: "comment-toggle", text: "Comment" }),
    el("div", { className: "review-fields" }, [
      el("label", { className: "want-other" }, [alternative]),
      comment,
      el("label", { className: "other-url" }, [suggestion]),
      el("button", { className: "confirm-review" }),
    ]),
    el("p", { "data-review-status": "", className: "feedback" }),
  ]);
  panel.querySelector("[data-review-status]").dataset.reviewStatus = "";
  panel.querySelector(".review-fields").hidden = true;
  panel.querySelector(".want-other").hidden = true;
  panel.querySelector(".other-url").hidden = true;
  panel.querySelector(".confirm-review").hidden = true;
  return panel;
}

function run(scenario) {
  const store = { ...(scenario.store || {}) };
  const main = el("main");
  const board = el("section", { className: "graphics-board" });
  const pieceSelect = el("select", { "data-graphics-piece": "" });
  const piecePrevious = el("button", { "data-graphics-prev": "" });
  const pieceNext = el("button", { "data-graphics-next": "" });
  const piecePosition = el("span", { "data-graphics-position": "" });
  const pieceNavigation = el("div", { className: "graphics-navigation" }, [piecePrevious, pieceSelect, pieceNext, piecePosition]);
  pieceNavigation.hidden = true;
  board.append(pieceNavigation);
  const exportButton = el("button", { id: "export-review" });
  exportButton.attrs.id = "export-review";
  const printButton = el("button", { id: "print-review" });
  printButton.attrs.id = "print-review";
  const nextButton = el("button", { id: "next-pending" });
  nextButton.attrs.id = "next-pending";
  const storage = el("span", { "data-storage-status": "" });
  storage.dataset.storageStatus = "";
  const done = el("p", { className: "export-done" });
  const summaryText = el("p", { "data-summary": "" });
  const summaryHost = el("div", { className: "review-summary" }, [summaryText, exportButton, printButton, nextButton, storage, done]);
  const graphics = scenario.graphics || [];
  if (graphics.length) {
    const byOcc = new Map();
    graphics.forEach((row) => {
      const list = byOcc.get(row.occurrence_id) || [];
      list.push(row);
      byOcc.set(row.occurrence_id, list);
    });
    for (const rows of byOcc.values()) board.append(graphicsCard(rows));
  }
  main.append(summaryHost, board);
  const select = el("select", { id: "select" });
  select.attrs.id = "select";
  select.value = "0";
  const viewer = el("div", { id: "viewer" });
  viewer.attrs.id = "viewer";
  const material = el("section", { className: "material" });
  const presenter = el("figure", { className: "presenter" }, [el("div", { className: "image-box" })]);
  if (scenario.items) {
    viewer.append(presenter, material, candidatePanel());
    main.append(select, viewer, ...scenario.items.map(() => el("button", { className: "shot" })));
  }
  const byId = {
    "export-review": exportButton,
    "print-review": printButton,
    "next-pending": nextButton,
    select,
    viewer,
  };
  const document = {
    body: { classList: { contains: () => false } },
    createTextNode(text) { return el("#text", {text}); },
    querySelector(selector) {
      if (selector === "main") return main;
      if (selector.startsWith("#") && byId[selector.slice(1)]) return byId[selector.slice(1)];
      if (selector === ".graphics-board") return board;
      if (selector === ".export-done") return done;
      if (selector === "[data-storage-status]") return storage;
      if (selector === ".print-notes") return main.querySelector(".print-notes");
      if (selector === ".review-toolbar") return null;
      if (selector === "#pending-only") return null;
      return main.querySelector(selector);
    },
    querySelectorAll(selector) {
      if (selector === "[data-storage-status]") return [storage];
      if (selector === "[data-summary]") return [summaryText];
      if (selector === ".export-done") return [done];
      return main.querySelectorAll(selector);
    },
    createElement(tag) {
      return new Element(tag);
    },
    addEventListener() {},
  };
  let downloaded;
  const posted = [];
  const uploads = [];
  class FakeEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
    }
  }
  const window = {
    GETBROLLS_REVIEW: {
      type: "getbrolls-review",
      templateVersion: 2,
      project: "synthetic-graphics",
      items: scenario.items || [],
      graphics,
    },
    GETBROLLS_SAVE: scenario.save || null,
    listeners: {},
    addEventListener(name, handler) { window.listeners[name] = handler; },
    dispatchEvent(event) { window.listeners[event.type]?.(event); },
    print() {},
    Event: FakeEvent,
    getbrollsGo(index) {
      window.wentTo = index;
      select.value = String(index);
      window.dispatchEvent(new FakeEvent("getbrolls:navigate", {detail: {index}}));
    },
  };
  const context = {
    window,
    document,
    Event: FakeEvent,
    localStorage: {
      getItem(name) {
        return Object.prototype.hasOwnProperty.call(store, name) ? store[name] : null;
      },
      setItem(name, value) {
        store[name] = value;
      },
    },
    matchMedia: () => ({ matches: true }),
    MutationObserver: class {
      observe() {}
    },
    IntersectionObserver: undefined,
    URL: {
      createObjectURL(blob) {
        downloaded = blob.parts ? blob.parts.join("") : String(blob);
        return "blob:fixture";
      },
      revokeObjectURL() {},
    },
    Blob: class {
      constructor(parts) {
        this.parts = parts;
      }
    },
    fetch: async (_url, options) => {
      if (_url === scenario.save?.referenceUrl) {
        uploads.push(options.body);
        const failed = scenario.uploadFail || uploads.length === scenario.uploadFailAt;
        return { ok: !failed, json: async () => failed ? {error: "Synthetic upload refusal"} :
          {reference: scenario.references?.[uploads.length - 1] || scenario.reference} };
      }
      posted.push(JSON.parse(options.body));
      if (scenario.saveFail) throw new Error("offline");
      return { ok: true, json: async () => ({ name: "20261010-120000.json", path: "brolls/reviews/20261010-120000.json" }) };
    },
    navigator: {},
    setTimeout,
    console,
  };
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
  return {
    document,
    window,
    store,
    main,
    board,
    nextButton,
    summaryText,
    exportButton,
    printButton,
    downloaded: () => downloaded,
    posted,
    uploads,
    done,
    storage,
    Event: FakeEvent,
  };
}

function exported(harness) {
  harness.exportButton.click();
  return JSON.parse(harness.downloaded());
}

const v1 = graphicsRow();
const v2 = graphicsRow({
  id: "graphics:stat-01:v2",
  version: "v2",
  parent: "v1",
  current: true,
  signature: "bb".repeat(32),
  reviewEpoch: "epoch-v2",
  artifact: "previews/graphics-stat-01-v2.mp4",
  context: {
    ...v1.context,
    narration: "The count now claims twenty units.",
    chapter_context: "Changed chapter context.",
    timing: { basis: "estimated", duration_s: 4, duration_in_frames: 120 },
  },
  versions: [
    { id: "v1", parent: null, status: "complete" },
    { id: "v2", parent: "v1", status: "complete" },
  ],
});
v1.current = false;

const only = run({ graphics: [v1] });
assert.equal(only.window.GETBROLLS_REVIEW.items.length, 0);
const card = only.board.querySelector(".graphics-card");
const approve = card.querySelector('[data-graphics-decision="approved"]');
approve.click();
const first = exported(only);
assert.equal(first.templateVersion, 2);
assert.deepEqual(first.items, []);
assert.equal(first.graphics.length, 1);
assert.equal(first.graphics[0].state, "approved");
assert.equal(first.graphics[0].id, "graphics:stat-01:v1");
assert.equal(first.graphics[0].signature, v1.signature);
assert.equal(first.graphics[0].reviewEpoch, v1.reviewEpoch);
assert.ok(!first.graphics[0].requestId);
assert.equal(only.done.textContent.includes("getbrolls-review.json"), true);

const drafts = run({ graphics: [v1, v2] });
const draftCard = drafts.board.querySelector(".graphics-card");
const display = draftCard.querySelector("[data-graphics-display]");
const compare = draftCard.querySelector("[data-graphics-compare]");
display.value = "v1";
display.dispatchEvent(new drafts.Event("change"));
draftCard.querySelector('[data-graphics-decision="approved"]').click();
const comment = draftCard.querySelector("[data-graphics-comment]");
display.value = "v2";
display.dispatchEvent(new drafts.Event("change"));
draftCard.querySelector('[data-graphics-decision="changes"]').click();
comment.value = "Make the numeral larger.";
comment.oninput();
const shared = draftCard.querySelector("[data-graphics-shared]");
shared.checked = true;
shared.onchange();
draftCard.querySelector(".confirm-review").click();
compare.value = "v1";
compare.dispatchEvent(new drafts.Event("change"));
const compareLine = draftCard.querySelector("[data-graphics-compare-context]").textContent;
assert.match(compareLine, /Displayed v2 narration: The count now claims twenty units/);
assert.match(compareLine, /Compare v1 narration: The count stands at twelve units/);
assert.match(compareLine, /Estimated duration 4 s · 120 frames/);
const draftExport = exported(drafts);
const byVersion = Object.fromEntries(draftExport.graphics.map((row) => [row.version, row]));
assert.equal(byVersion.v1.state, "approved");
assert.equal(byVersion.v1.comment, "");
assert.equal(byVersion.v2.state, "changes");
assert.equal(byVersion.v2.comment, "Make the numeral larger.");
assert.equal(byVersion.v2.scope, "shared");
assert.equal(byVersion.v2.requestId, null);
assert.equal(byVersion.v1.scope, "scene");
const stored = JSON.parse(drafts.store["getbrolls-v2-graphics:synthetic-graphics"]);
assert.equal(stored["graphics:stat-01:v1"].state, "approved");
assert.equal(stored["graphics:stat-01:v2"].state, "changes");

const stale = run({
  graphics: [{ ...v2, state: "pending", comment: "", signature: "cc".repeat(32), reviewEpoch: "epoch-v2-new" }],
  store: {
    "getbrolls-v2-graphics:synthetic-graphics": JSON.stringify({
      "graphics:stat-01:v2": {
        signature: v2.signature,
        reviewEpoch: v2.reviewEpoch,
        state: "approved",
        comment: "stale local copy",
        scope: "scene",
      },
    }),
  },
});
const staleExport = exported(stale);
assert.equal(staleExport.graphics[0].state, "pending");
assert.equal(staleExport.graphics[0].comment, "");
assert.notEqual(staleExport.graphics[0].signature, v2.signature);

const requestRow = graphicsRow({
  state: "changes",
  comment: "Shift the label.",
  scope: "scene",
  requestId: "grq-stable-identity",
});
const stable = run({ graphics: [requestRow] });
const stableExport = exported(stable);
assert.equal(stableExport.graphics[0].requestId, "grq-stable-identity");
assert.equal(stableExport.graphics[0].scope, "scene");
const stableCard = stable.board.querySelector(".graphics-card");
const stableComment = stableCard.querySelector("[data-graphics-comment]");
stableComment.value = "A different request text.";
stableComment.oninput();
stableCard.querySelector('[data-graphics-decision="changes"]').click();
stableCard.querySelector(".confirm-review").click();
const changed = exported(stable);
assert.equal(changed.graphics[0].comment, "A different request text.");
assert.equal(changed.graphics[0].requestId, null);

const blocked = run({
  graphics: [graphicsRow({ readiness: { complete: false, reviewable: false, approved: false, deliverable: false, reasons: ["incomplete_version"] } })],
});
blocked.board.querySelector('[data-graphics-decision="approved"]').click();
const blockedExport = exported(blocked);
assert.equal(blockedExport.graphics[0].state, "pending");
assert.match(blocked.board.querySelector("[data-graphics-status]").textContent, /cannot be approved/);

const candidateItem = {
  id: "local:clip",
  signature: "item-sig",
  reviewEpoch: "item-epoch",
  title: "Synthetic clip",
  segment: { start_s: 0, end_s: 1 },
  source: "https://example.org/fixture",
  narration: "Original narration",
  review: { state: "pending" },
};
const mixed = run({ items: [candidateItem], graphics: [v1] });
mixed.document.querySelector('[data-decision="approved"]').click();
mixed.board.querySelector('[data-graphics-decision="approved"]').click();
const mixedExport = exported(mixed);
assert.equal(mixedExport.items.length, 1);
assert.equal(mixedExport.items[0].id, "local:clip");
assert.equal(mixedExport.items[0].state, "approved");
assert.equal(mixedExport.items[0].title, "Synthetic clip");
assert.equal(mixedExport.graphics[0].state, "approved");
assert.equal(mixedExport.templateVersion, 2);

const during = run({ graphics: [v1, v2] });
const duringCard = during.board.querySelector(".graphics-card");
const duringDisplay = duringCard.querySelector("[data-graphics-display]");
const duringComment = duringCard.querySelector("[data-graphics-comment]");
const duringConfirm = duringCard.querySelector(".confirm-review");
const duringShared = duringCard.querySelector("[data-graphics-shared]");
duringDisplay.value = "v2";
duringDisplay.dispatchEvent(new during.Event("change"));
duringCard.querySelector(".comment-toggle").click();
duringComment.value = "Unconfirmed v2 draft only.";
duringComment.oninput();
duringDisplay.value = "v1";
duringDisplay.dispatchEvent(new during.Event("change"));
duringCard.querySelector('[data-graphics-decision="changes"]').click();
duringComment.value = "Revision specifically for v1.";
duringComment.oninput();
duringShared.checked = true;
duringShared.onchange();
assert.equal(duringConfirm.hidden, false);
assert.equal(duringConfirm.disabled, false);
duringDisplay.value = "v2";
duringDisplay.dispatchEvent(new during.Event("change"));
assert.equal(duringConfirm.hidden, true);
assert.equal(duringComment.value, "Unconfirmed v2 draft only.");
assert.equal(duringShared.checked, false);
duringConfirm.click();
const duringExport = exported(during);
const duringBy = Object.fromEntries(duringExport.graphics.map((row) => [row.version, row]));
assert.equal(duringBy.v2.state, "pending");
assert.equal(duringBy.v2.comment, "Unconfirmed v2 draft only.");
assert.equal(duringBy.v2.scope, "scene");
assert.ok(!duringBy.v2.requestId);
assert.equal(duringBy.v1.state, "pending");
assert.equal(duringBy.v1.comment, "Revision specifically for v1.");
assert.equal(duringBy.v1.scope, "scene");
const duringStored = JSON.parse(during.store["getbrolls-v2-graphics:synthetic-graphics"]);
assert.equal(duringStored["graphics:stat-01:v1"].state, "pending");
assert.equal(duringStored["graphics:stat-01:v1"].comment, "Revision specifically for v1.");
assert.equal(duringStored["graphics:stat-01:v2"].state, "pending");
assert.equal(duringStored["graphics:stat-01:v2"].comment, "Unconfirmed v2 draft only.");

const v2Explicit = graphicsRow({
  id: "graphics:stat-01:v2",
  version: "v2",
  parent: "v1",
  current: true,
  signature: "bb".repeat(32),
  reviewEpoch: "epoch-v2",
  timing_basis: "explicit",
  artifact: "previews/graphics-stat-01-v2.mp4",
  context: {
    ...v1.context,
    narration: "The count now claims twenty units.",
    chapter_context: "Changed chapter context.",
    timing: {
      basis: "explicit",
      start_s: 5,
      end_s: 7,
      start_frame: 150,
      end_frame: 210,
      duration_s: 2,
      duration_in_frames: 60,
    },
  },
  versions: [
    { id: "v1", parent: null, status: "complete" },
    { id: "v2", parent: "v1", status: "complete" },
  ],
});
const v1Estimated = { ...v1, current: false };
const timingSwitch = run({ graphics: [v1Estimated, v2Explicit] });
const timingCard = timingSwitch.board.querySelector(".graphics-card");
const timingBadge = timingCard.querySelector(".timing-basis");
const timingDisplay = timingCard.querySelector("[data-graphics-display]");
const timingCompare = timingCard.querySelector("[data-graphics-compare]");
assert.equal(timingBadge.hidden, true);
assert.match(timingBadge.className, /explicit/);
timingDisplay.value = "v1";
timingDisplay.dispatchEvent(new timingSwitch.Event("change"));
assert.equal(timingBadge.hidden, false);
assert.match(timingBadge.textContent, /Draft · VO timing pending/);
assert.match(timingBadge.className, /estimated/);
timingCompare.value = "v2";
timingCompare.dispatchEvent(new timingSwitch.Event("change"));
assert.match(timingBadge.textContent, /Draft · VO timing pending/);
assert.match(timingBadge.className, /estimated/);
const timingLine = timingCard.querySelector("[data-graphics-compare-context]").textContent;
assert.match(timingLine, /Displayed v1 narration: The count stands at twelve units/);
assert.match(timingLine, /Estimated duration 3 s · 90 frames/);
assert.match(timingLine, /Compare v2 narration: The count now claims twenty units/);
assert.match(timingLine, /Explicit 5–7 s \(frames 150–210\)/);
assert.match(timingLine, /Duration 2 s · 60 frames/);

assert.equal(only.board.querySelectorAll("video").length, 1);
assert.equal(only.board.querySelector(".graphics-preview").className.includes("graphics-preview"), true);
assert.equal(only.board.querySelector(".graphics-version-tools") != null, true);
assert.equal(only.board.querySelector("[data-graphics-compare]").disabled, true);
assert.equal(only.board.querySelector(".graphics-vo-status").hidden, false);
assert.equal(only.board.querySelectorAll(".graphics-details").length, 1);
assert.equal(only.board.querySelector("[data-graphics-compare-context]").parentNode.className, "graphics-details");
const detailVersions = timingCard.querySelectorAll(".graphics-version-details");
assert.equal(detailVersions[0].classList.contains("is-shown"), true);
assert.equal(detailVersions[1].classList.contains("is-compare"), true);
const voiceSwitch = run({graphics: [
  {...v1, current:false, vo_preview:{ref:"previews/vo-v1.wav"}},
  {...v2, current:true},
]});
const voiceCard = voiceSwitch.board.querySelector(".graphics-card");
const voiceDisplay = voiceCard.querySelector("[data-graphics-display]");
const voiceBadge = voiceCard.querySelector(".graphics-vo-status");
assert.equal(voiceBadge.hidden, false);
voiceDisplay.value = "v1";
voiceDisplay.dispatchEvent(new voiceSwitch.Event("change"));
assert.equal(voiceBadge.hidden, true);
voiceDisplay.value = "v2";
voiceDisplay.dispatchEvent(new voiceSwitch.Event("change"));
assert.equal(voiceBadge.hidden, false);

const pieceVersions = [
  {id: "v4", status: "complete"},
  {id: "v7", status: "failed"},
  {id: "v10", status: "complete"},
];
const pieceOld = graphicsRow({
  id: "graphics:later-piece:v4", occurrence_id: "later-piece", version: "v4", current: false,
  versions: pieceVersions,
});
const pieceNew = graphicsRow({
  id: "graphics:later-piece:v10", occurrence_id: "later-piece", version: "v10", parent: "v4",
  versions: pieceVersions, signature: "cc".repeat(32), reviewEpoch: "epoch-v10",
  requests: [{id: "fixture-local-request", reviewed_version: "v4", state: "pending", scope: "scene"}],
});
const separatePiece = graphicsRow({
  id: "graphics:separate-piece:v2", occurrence_id: "separate-piece", version: "v2",
  versions: [{id: "v2", status: "complete"}],
});
const localLabels = run({graphics: [separatePiece, pieceOld, pieceNew]});
const laterCard = localLabels.board.querySelectorAll(".graphics-card").find(card => card.dataset.occurrence === "later-piece");
const laterCompare = laterCard.querySelector("[data-graphics-compare]");
laterCompare.value = "v4";
laterCompare.dispatchEvent(new localLabels.Event("change"));
const laterContext = laterCard.querySelector("[data-graphics-compare-context]").textContent;
assert.match(laterContext, /Displayed v2 narration/);
assert.match(laterContext, /Compare v1 narration/);
assert.doesNotMatch(laterContext, /v10|v4/);
assert.match(laterCard.querySelector("[data-graphics-requests]").textContent, /target v1/);
laterCard.querySelector('[data-graphics-decision="approved"]').click();
const localExport = exported(localLabels);
const exportedPiece = localExport.graphics.find(row => row.id === "graphics:later-piece:v10");
assert.equal(exportedPiece.version, "v10");
assert.equal(exportedPiece.signature, pieceNew.signature);
assert.equal(exportedPiece.reviewEpoch, "epoch-v10");
assert.equal(exportedPiece.state, "approved");
assert.equal(localExport.graphics.find(row => row.id === "graphics:separate-piece:v2").state, "pending");

// Six current pieces, eight retained versions: history does not inflate the queue.
const pendingPieces = Array.from({length: 6}, (_, index) => graphicsRow({
  id: `graphics:piece-${index}:v10`, occurrence_id: `piece-${index}`, version: "v10",
  versions: [{id: "v1", status: "complete"}, {id: "v10", status: "complete"}],
}));
const pendingHistory = [
  {...pendingPieces[0], id: "graphics:piece-0:v1", version: "v1", current: false, state: "approved"},
  {...pendingPieces[3], id: "graphics:piece-3:v1", version: "v1", current: false},
];
const queue = run({graphics: [pendingHistory[0], ...pendingPieces, pendingHistory[1]]});
const queueCards = queue.board.querySelectorAll(".graphics-card");
assert.equal(queueCards.filter(card => card.classList.contains("is-active-piece")).length, 1);
assert.equal(queue.board.querySelector(".graphics-navigation").hidden, false);
const pieceSelect = queue.board.querySelector("[data-graphics-piece]");
assert.equal(pieceSelect.children.length, 6);
assert.equal(queue.board.querySelector("[data-graphics-position]").textContent, "1 / 6");
assert.equal(queue.board.querySelector("[data-graphics-prev]").disabled, true);
pieceSelect.value = "5";
const firstPlayingVideo = queueCards[0].querySelector("video");
firstPlayingVideo.paused = false;
pieceSelect.dispatchEvent(new queue.Event("change"));
assert.equal(firstPlayingVideo.paused, true, "leaving a piece pauses its media");
assert.equal(queueCards[5].classList.contains("is-active-piece"), true);
assert.equal(queue.board.querySelector("[data-graphics-next]").disabled, true);
queue.board.querySelector("[data-graphics-prev]").click();
assert.equal(queueCards[4].classList.contains("is-active-piece"), true);
queue.board.querySelector("[data-graphics-next]").click();
assert.equal(queueCards[5].classList.contains("is-active-piece"), true);
pieceSelect.value = "0";
pieceSelect.dispatchEvent(new queue.Event("change"));
const oldDisplay = queueCards[0].querySelector("[data-graphics-display]");
oldDisplay.value = "v1";
oldDisplay.dispatchEvent(new queue.Event("change"));
assert.equal(queue.summaryText.textContent, "0 approved · 0 reviewed · 6 pending");
for (const expected of [1, 2, 3, 4, 5, 0, 1]) {
  queueCards.forEach(card => { card.scrolled = false; });
  queue.nextButton.click();
  assert.equal(queue.board.scrolled, true, "navigation keeps the summary and piece controls visible");
  assert.deepEqual(queueCards.flatMap((card, index) => card.classList.contains("is-active-piece") ? [index] : []), [expected]);
}
assert.equal(oldDisplay.value, "v10", "navigation selects the current saved version");
const queueExport = exported(queue);
assert.equal(queueExport.graphics.length, 8, "all historical decisions remain exportable");
for (const row of [...pendingPieces, ...pendingHistory]) {
  assert.equal(queueExport.graphics.find(saved => saved.id === row.id).state, row.state);
}
queueCards[1].querySelector('[data-graphics-decision="approved"]').click();
assert.equal(queue.summaryText.textContent, "1 approved · 0 reviewed · 5 pending");
queueCards.forEach(card => { card.scrolled = false; });
queue.nextButton.click();
assert.equal(queueCards[2].classList.contains("is-active-piece"), true, "the next action skips an approved current piece");

const settled = run({graphics: [
  ...pendingPieces.map((row, index) => ({...row, state: index ? "approved" : "changes"})),
  {...pendingHistory[0], state: "pending"}, pendingHistory[1],
]});
assert.equal(settled.summaryText.textContent, "5 approved · 1 reviewed · 0 pending");
assert.equal(settled.nextButton.disabled, true, "old pending versions do not reopen the queue");
const fallbackPiece = run({graphics: [{...v1, state: "pending"}, {...v2, current: false}]});
assert.equal(fallbackPiece.summaryText.textContent, "0 approved · 0 reviewed · 1 pending");

// Mixed boards cycle between candidate clips and current graphics pieces.
const candidate = {
  id: "candidate-queue", signature: "dd".repeat(32), reviewEpoch: "candidate-epoch",
  title: "Synthetic candidate", review: {state: "pending"}, segment: {start_s: 0, end_s: 3},
};
const mixedQueue = run({items: [candidate], graphics: [pendingPieces[0], pendingPieces[1]]});
assert.equal(mixedQueue.summaryText.textContent, "0 approved · 0 reviewed · 3 pending");
const mixedCards = mixedQueue.board.querySelectorAll(".graphics-card");
for (const card of mixedCards) {
  mixedQueue.nextButton.click();
  assert.equal(card.scrolled, true, "pending candidates do not hide graphics from navigation");
  assert.equal(mixedQueue.window.wentTo, undefined);
}
mixedQueue.nextButton.click();
assert.equal(mixedQueue.window.wentTo, 0, "navigation wraps back to the candidate player");

const candidatesOnly = run({items: [candidate, {...candidate, id: "candidate-two"}, {...candidate, id: "candidate-three"}]});
candidatesOnly.nextButton.click();
assert.equal(candidatesOnly.window.wentTo, 1);
candidatesOnly.nextButton.click();
assert.equal(candidatesOnly.window.wentTo, 2);
candidatesOnly.window.getbrollsGo(0);
candidatesOnly.nextButton.click();
assert.equal(candidatesOnly.window.wentTo, 1, "player buttons and gallery navigation reset the pending cursor");
const candidateSelect = candidatesOnly.document.querySelector("#select");
candidateSelect.value = "2";
candidateSelect.dispatchEvent(new candidatesOnly.Event("change"));
candidatesOnly.nextButton.click();
assert.equal(candidatesOnly.window.wentTo, 0, "manual candidate selection resets the navigation cursor");

(async () => {
  const imageReference = {
    ref: "graphics-data/references/" + "ee".repeat(32) + ".png", sha256: "ee".repeat(32),
    name: "example.png", bytes: 100, width: 40, height: 20, kind: "image",
  };
  const withImage = run({
    graphics: [{...v1, state: "pending", comment: ""}], reference: imageReference,
    save: {url: "/__save", header: "X-GetBrolls-Token", token: "fixture-token", referenceUrl: "/__graphics-reference"},
  });
  const imagePanel = withImage.board.querySelector(".graphics-review-panel");
  imagePanel.querySelector('[data-graphics-decision="changes"]').click();
  const imageComment = imagePanel.querySelector("[data-graphics-comment]");
  imageComment.value = "Adopt the image colors; keep our values.";
  imageComment.oninput();
  const imageInput = imagePanel.querySelector("[data-graphics-reference]");
  imageInput.files = [{name: "example.png", size: 100}];
  imageInput.onchange();
  assert.match(imagePanel.querySelector("[data-graphics-reference-preview]").textContent, /selected, not saved/);
  imagePanel.querySelector(".confirm-review").click();
  withImage.exportButton.click();
  for (let i = 0; i < 24; i++) await Promise.resolve();
  assert.equal(withImage.uploads.length, 1);
  assert.equal(withImage.posted.length, 1);
  assert.deepEqual(withImage.posted[0].graphics[0].references, [{...imageReference, label: "R1"}]);
  assert.match(imagePanel.querySelector("[data-graphics-reference-preview]").textContent, /saved in project/);
  assert.doesNotMatch(imagePanel.querySelector("[data-graphics-reference-preview]").textContent, /selected, not saved/);
  assert.doesNotMatch(imagePanel.querySelector("[data-graphics-status]").textContent, /selected, not saved/);
  assert.equal(imagePanel.querySelector("[data-graphics-shared]").disabled, true);

  const videoReference = {...imageReference, ref: imageReference.ref.replace(".png", ".mp4"), kind: "video",
    name: "example.png", duration_s: 6, fps: 10, codec: "h264"};
  const reopenedInitial = {...v1, id: "graphics:stat-01:initial", initial: true, version: null,
    state: "changes", comment: "Imported saved R1 and R3 request.", requestId: "grq-new-import",
    references: [{...imageReference, label: "R1"}, {...videoReference, label: "R3"}]};
  const reopened = run({graphics:[reopenedInitial],
    save:{url:"/__save",header:"X-GetBrolls-Token",token:"fixture-token",referenceUrl:"/__graphics-reference"}, store:{
    "getbrolls-v2-graphics:synthetic-graphics":JSON.stringify({[reopenedInitial.id]:{
      signature:reopenedInitial.signature, reviewEpoch:reopenedInitial.reviewEpoch,
      state:"pending", comment:"Older browser draft.", updatedAt:"before-import", requestId:null
    }})
  }});
  reopened.exportButton.click();
  for (let i = 0; i < 16; i++) await Promise.resolve();
  const reopenedExport = reopened.posted[0];
  assert.equal(reopenedExport.graphics[0].state,"changes");
  assert.equal(reopenedExport.graphics[0].comment,reopenedInitial.comment);
  assert.deepEqual(reopenedExport.graphics[0].references,reopenedInitial.references);
  const mixedScenario = {
    graphics: [{...v1, state: "changes", comment: "Use R1 colors and R2 motion from 3 to 5 seconds."}],
    references: [imageReference, videoReference, videoReference], uploadFailAt: 2,
    save: {url: "/__save", header: "X-GetBrolls-Token", token: "fixture-token", referenceUrl: "/__graphics-reference"},
  };
  const mixedRefs = run(mixedScenario);
  const mixedInput = mixedRefs.board.querySelector("[data-graphics-reference]");
  mixedInput.files = [{name: "example.png", size: 100}, {name: "example.png", type: "video/mp4", size: 200}];
  mixedInput.onchange();
  const mixedPreview = mixedRefs.board.querySelector("[data-graphics-reference-preview]");
  assert.match(mixedPreview.textContent, /R1 · example.png/);
  assert.match(mixedPreview.textContent, /R2 · example.png/);
  assert.equal(mixedPreview.querySelectorAll("video").length, 1);
  mixedPreview.querySelector("video").onerror();
  assert.match(mixedPreview.textContent, /Browser preview unavailable/);
  mixedRefs.exportButton.click();
  for (let i = 0; i < 32; i++) await Promise.resolve();
  assert.equal(mixedRefs.posted.length, 0, "a partial batch cannot become a saved request");
  assert.match(mixedRefs.storage.textContent, /Synthetic upload refusal/);
  mixedRefs.exportButton.click();
  for (let i = 0; i < 40; i++) await Promise.resolve();
  assert.equal(mixedRefs.uploads.length, 3, "retry retains the intact first upload");
  assert.deepEqual(mixedRefs.posted[0].graphics[0].references,
    [{...imageReference, label: "R1"}, {...videoReference, label: "R2"}]);
  assert.match(mixedPreview.textContent, /saved in project/);
  assert.doesNotMatch(mixedPreview.textContent, /selected, not saved/);

  const removedRefs = run({...mixedScenario, uploadFailAt: undefined});
  const removedInput = removedRefs.board.querySelector("[data-graphics-reference]");
  removedInput.files = mixedInput.files;
  removedInput.onchange();
  const removedPreview = removedRefs.board.querySelector("[data-graphics-reference-preview]");
  removedPreview.querySelector("button").click();
  assert.equal(removedPreview.querySelectorAll("video").length, 1);
  assert.match(removedPreview.textContent, /R2 · example.png/);
  assert.doesNotMatch(removedPreview.textContent, /R1 ·/);

  const imageDrafts = run({
    graphics: [v1, v2],
    save: {url: "/__save", header: "X-GetBrolls-Token", token: "fixture-token", referenceUrl: "/__graphics-reference"},
  });
  const boundPanel = imageDrafts.board.querySelector(".graphics-review-panel");
  const boundDisplay = imageDrafts.board.querySelector("[data-graphics-display]");
  const boundInput = boundPanel.querySelector("[data-graphics-reference]");
  boundDisplay.value = "v1";
  boundDisplay.dispatchEvent(new imageDrafts.Event("change"));
  boundPanel.querySelector('[data-graphics-decision="changes"]').click();
  boundInput.files = [{name: "v1-only.png", size: 100}];
  boundInput.onchange();
  boundDisplay.value = "v2";
  boundDisplay.dispatchEvent(new imageDrafts.Event("change"));
  assert.equal(boundInput.value, "");
  assert.equal(boundPanel.querySelector("[data-graphics-reference-preview]").textContent, "");
  assert.equal(boundPanel.querySelector(".confirm-review").hidden, true);
  boundDisplay.value = "v1";
  boundDisplay.dispatchEvent(new imageDrafts.Event("change"));
  assert.match(boundPanel.querySelector("[data-graphics-reference-preview]").textContent, /v1-only.png · selected, not saved/);

  const uploadFailure = run({
    graphics: [{...v1, state: "changes", comment: "Keep this image draft."}], uploadFail: true,
    save: {url: "/__save", header: "X-GetBrolls-Token", token: "fixture-token", referenceUrl: "/__graphics-reference"},
  });
  const failedInput = uploadFailure.board.querySelector("[data-graphics-reference]");
  failedInput.files = [{name: "retry.png", size: 100}];
  failedInput.onchange();
  uploadFailure.exportButton.click();
  for (let i = 0; i < 16; i++) await Promise.resolve();
  assert.match(uploadFailure.storage.textContent, /Synthetic upload refusal/);
  assert.equal(uploadFailure.posted.length, 0);
  assert.match(uploadFailure.board.querySelector("[data-graphics-reference-preview]").textContent, /retry.png · selected, not saved/);

  const referenceFailure = run({
    graphics: [{...v1, state: "changes", comment: "Use this saved image.", reference: imageReference}], saveFail: true,
    save: {url: "/__save", header: "X-GetBrolls-Token", token: "fixture-token", referenceUrl: "/__graphics-reference"},
  });
  referenceFailure.exportButton.click();
  for (let i = 0; i < 16; i++) await Promise.resolve();
  assert.match(referenceFailure.storage.textContent, /not saved to the project/);
  assert.equal(referenceFailure.downloaded(), undefined, "a failed reference save is not disguised as a media-package download");

  const saved = run({
    graphics: [v1],
    save: { url: "/__save", header: "X-Getbrolls-Token", token: "fixture-token" },
  });
  saved.exportButton.click();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(saved.posted.length, 1);
  assert.deepEqual(saved.posted[0].items, []);
  assert.equal(saved.posted[0].graphics[0].id, "graphics:stat-01:v1");
  assert.match(saved.done.textContent, /Decisions saved to the project/);

  const fallback = run({
    graphics: [v1],
    save: { url: "/__save", header: "X-Getbrolls-Token", token: "fixture-token" },
    saveFail: true,
  });
  fallback.exportButton.click();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(JSON.parse(fallback.downloaded()).graphics[0].id, "graphics:stat-01:v1");
  assert.match(fallback.storage.textContent, /downloaded the file instead/);
  console.log("Graphics review decisions, drafts, identity, save and candidate export");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
