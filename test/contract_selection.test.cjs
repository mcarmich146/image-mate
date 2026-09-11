const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Exercise the real loader without starting the map or making network requests.
const app = fs.readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8");
const start = app.indexOf("async function loadContracts() {");
const end = app.indexOf("async function loadSatellogicCollections() {", start);
assert.ok(start >= 0 && end > start);
const loader = app.slice(start, end);
const showcase = "cont.eac744cc-2afe-4012-9621-35623feeb7a7";

async function load(data, { enabled = true, ok = true } = {}) {
  const messages = [];
  const select = {
    value: "", options: [],
    appendChild(option) { this.options.push(option); },
  };
  const context = vm.createContext({
    state: { satellogicContractMemory: "cont.old-selection" },
    contractSelectEl: select,
    document: { createElement: () => ({}) },
    URLSearchParams, apiBase: "",
    fetch: async () => ({ ok, json: async () => data }),
    isSourceEnabled: () => enabled,
    toast: message => messages.push(message),
  });
  await vm.runInContext(`${loader}\nloadContracts()`, context);
  return { context, select, messages };
}

test("backend default wins over a remembered selection and provider order", async () => {
  const { context, select } = await load({
    default_contract_id: showcase, count: 2,
    contracts: [
      { id: "cont.old-selection", name: "Other" },
      { id: showcase, name: "Sales -  Showcase" },
    ],
  });
  assert.equal(select.value, showcase);
  assert.equal(context.state.satellogicContractMemory, showcase);
  assert.match(select.options[2].textContent, /Sales -  Showcase/);
});

test("default is remembered even when the Satellogic source is disabled", async () => {
  const { context, select } = await load({
    default_contract_id: showcase, count: 1, contracts: [{ id: showcase }],
  }, { enabled: false });
  assert.equal(context.state.satellogicContractMemory, showcase);
  assert.equal(select.disabled, true);
});

test("unavailable default reports an error without retaining an old contract", async () => {
  const { context, messages } = await load({
    default_contract_id: showcase, count: 1, contracts: [{ id: "cont.old-selection" }],
  });
  assert.equal(context.state.satellogicContractMemory, null);
  assert.match(messages[0], /Configured default contract .* is not available/);
});

test("discovery errors do not retain a stale contract", async () => {
  const { context, messages } = await load({ detail: "Unavailable" }, { ok: false });
  assert.equal(context.state.satellogicContractMemory, null);
  assert.match(messages[0], /Contracts unavailable: Unavailable/);
});
