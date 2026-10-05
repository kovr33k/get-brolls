// The review layer moves the existing toolbar into the replaceable viewer.
// Replacing a shot detaches that toolbar until the review observer remounts it.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const previous = {};
const next = {};
const position = {};
const select = { addEventListener() {} };
const caption = { replaceChildren() {} };
let toolbarInside = false;
let toolbarAttached = true;
let selectedTemplate;
const templates = Array.from({ length: 3 }, (_, index) => ({
  dataset: { preview: "1" },
  content: { cloneNode: () => ({ index }) },
}));
const viewer = {
  classList: { toggle() {} },
  replaceChildren(template) {
    selectedTemplate = template.index;
    if (toolbarInside) toolbarAttached = false;
  },
  querySelector(selector) {
    return selector === ".presenter" ? {} : null;
  },
  querySelectorAll() { return []; },
};
const document = {
  body: { classList: { contains: () => false } },
  addEventListener() {},
  getElementById(id) {
    const elements = { select, viewer, caption, position };
    if (id === "prev") return toolbarAttached ? previous : null;
    if (id === "next") return toolbarAttached ? next : null;
    return elements[id];
  },
  querySelectorAll(selector) {
    return selector === "template[data-shot]" ? templates : [];
  },
};
const window = { addEventListener() {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {
  document,
  window,
  matchMedia: () => ({ matches: true }),
});
assert.equal(selectedTemplate, 0);
assert.equal(previous.disabled, true);
assert.equal(next.disabled, false);

// Simulate review mounting, then use both keyboard/select navigation and buttons.
toolbarInside = true;
window.getbrollsGo(1);
assert.equal(selectedTemplate, 1);
assert.equal(previous.disabled, false);
assert.equal(next.disabled, false);
assert.equal(position.textContent, "02 / 03");
toolbarAttached = true;
next.onclick();
assert.equal(selectedTemplate, 2);
assert.equal(next.disabled, true);
toolbarAttached = true;
previous.onclick();
assert.equal(selectedTemplate, 1);
assert.equal(next.disabled, false);
toolbarAttached = true;
window.getbrollsGo(0);
assert.equal(previous.disabled, true);
assert.equal(position.textContent, "01 / 03");
