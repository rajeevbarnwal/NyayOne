import { execFileSync } from 'node:child_process';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { PNG } from 'pngjs';
import { chromium } from 'playwright';
import {
  NYAY18_ASSERTION_INVENTORY,
  NYAY18_CACHE_SEEDS_PER_FAMILY,
  NYAY18_LEGACY_CACHE_PREFIXES,
  NYAY18_LEGACY_LOCAL_EXACT_KEYS,
  NYAY18_LEGACY_LOCAL_PREFIXES,
  NYAY18_LEGACY_SESSION_EXACT_KEYS,
  NYAY18_LEADING_CANDIDATE_KEYS,
  NYAY18_LEADING_UNRELATED_KEYS,
  NYAY18_LEADING_TARGET_KEYS,
  NYAY18_PREFIX_SEEDS_PER_FAMILY,
  NYAY18_RETIRED_CURRENT_CACHE,
  NYAY18_SCREENSHOT_INVENTORY,
  NYAY18_UNRELATED_CANARIES,
  buildNyay18LegacyCacheSeedKeys,
  buildNyay18LeadingCandidateEntries,
  buildNyay18LeadingTargetKeys,
  buildNyay18LegacyLocalSeedKeys,
  inspectNyay18Evidence,
  nyay18EvidenceInventory,
  nyay18Sha256,
  runNyay18ContractSelfTest,
} from './lib/nyay18-browser-contract.mjs';
import {
  NYAY5_ASSERTION_INVENTORY,
  NYAY5_SEEDED_MUTANT_INVENTORY,
  seededNyay5MutantResults,
} from './lib/nyay5-profile-browser-contract.mjs';

const REPOSITORY = path.resolve(import.meta.dirname, '../..');

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function loopbackOrigin(raw) {
  const parsed = new URL(raw);
  const loopback = new Set(['127.0.0.1', 'localhost', '[::1]']);
  if (!['http:', 'https:'].includes(parsed.protocol)
    || !loopback.has(parsed.hostname)
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash) {
    throw new Error('NYAY18_WEB_URL must be an explicit HTTP(S) loopback origin');
  }
  return parsed.origin;
}

const WEB = loopbackOrigin(requiredEnv('NYAY18_WEB_URL'));
const OUTPUT = requiredEnv('NYAY18_EVIDENCE_PATH');
const EXACT_COMMIT = requiredEnv('NYAY18_EXACT_COMMIT');
const EXACT_TREE = requiredEnv('NYAY18_EXACT_TREE');
const EXACT_PARENT = requiredEnv('NYAY18_EXACT_PARENT');
const PREVIEW_SOURCE_SHA256 = requiredEnv('NYAY18_PREVIEW_SOURCE_SHA256');
if (!path.isAbsolute(OUTPUT) || path.extname(OUTPUT).toLowerCase() !== '.json') {
  throw new Error('NYAY18_EVIDENCE_PATH must be an absolute JSON path');
}
if (!/^[0-9a-f]{40}$/u.test(EXACT_COMMIT)) {
  throw new Error('NYAY18_EXACT_COMMIT must be a lowercase 40-character commit SHA');
}
if (!/^[0-9a-f]{40}$/u.test(EXACT_TREE)) {
  throw new Error('NYAY18_EXACT_TREE must be a lowercase 40-character tree SHA');
}
if (EXACT_PARENT !== 'ROOT' && !/^[0-9a-f]{40}$/u.test(EXACT_PARENT)) {
  throw new Error('NYAY18_EXACT_PARENT must be ROOT or a lowercase 40-character commit SHA');
}
if (!/^[0-9a-f]{64}$/u.test(PREVIEW_SOURCE_SHA256)) {
  throw new Error('NYAY18_PREVIEW_SOURCE_SHA256 must be a lowercase SHA-256 digest');
}
const outputRelative = path.relative(REPOSITORY, OUTPUT);
const OUTPUT_OUTSIDE_REPOSITORY = outputRelative.startsWith('..')
  && !path.isAbsolute(outputRelative);
const SCREENSHOT_DIR = path.resolve(path.dirname(OUTPUT), 'screenshots');

const LOCAL_PRIVATE_SEED = 'nyay18-private-local-value';
const SESSION_PRIVATE_SEED = 'nyay18-private-session-value';
const UNRELATED_LOCAL_VALUE = 'nyay18-unrelated-local-canary';
const UNRELATED_SESSION_VALUE = 'nyay18-unrelated-session-canary';
const CURRENT_THEME_KEY = 'nyayone.theme.v1';
const CURRENT_CACHE = 'nyayone-shell-v1';
const PRIVATE_SCREEN = '[data-screen="S-60"]';
const SESSION_UNAVAILABLE = '[data-testid="student-session-unavailable"]';
const PRIVATE_SINK_SEED = 'nyay18-private-sink-sentinel';
const PRIVATE_SHELL_SEED = 'nyay18-private-shell-sentinel';
const HOSTILE_ASSET_PATH = '/assets/nyay18-private-canary.js';
const HOSTILE_ASSET_COOKIE = 'third-party-asset-canary';
const HOSTILE_SHELL_COOKIE = 'third-party-shell-canary';
const UNRELATED_POISON_MARKER = 'nyay18-unrelated-cache-poison';
const STORAGE_PROBE_SYMBOL = 'nyay18.browser.storage-probe.v1';
const S03_SELECTOR = '[data-screen="S-03"]';
const VIEWPORTS = Object.freeze([
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
]);

const legacyLocalSeedKeys = buildNyay18LegacyLocalSeedKeys();
const legacyCacheSeedKeys = buildNyay18LegacyCacheSeedKeys();
const leadingCandidateEntries = buildNyay18LeadingCandidateEntries();
const leadingTargetKeys = buildNyay18LeadingTargetKeys();
const observations = new Map(NYAY18_ASSERTION_INVENTORY.map((id) => [id, {
  id, executed: false, pass: false, metrics: {},
}]));
const screenshots = [];
let failureStage = 'environment';
let failureCode = null;
let failureClass = null;
let freshProfileContexts = 0;

async function createFreshContext(browser, options = {}) {
  freshProfileContexts += 1;
  return browser.newContext({
    serviceWorkers: 'allow',
    viewport: { width: 1440, height: 1024 },
    ...options,
  });
}

function record(id, pass, metrics) {
  if (!observations.has(id)) throw new Error('NYAY18_UNKNOWN_ASSERTION');
  if (observations.get(id).executed) throw new Error('NYAY18_DUPLICATE_ASSERTION');
  observations.set(id, { id, executed: true, pass: pass === true, metrics });
}

function gitState() {
  const head = execFileSync('git', ['rev-parse', 'HEAD'], {
    cwd: REPOSITORY, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  const status = execFileSync('git', ['status', '--porcelain=v1', '--untracked-files=all'], {
    cwd: REPOSITORY, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
  });
  const tree = execFileSync('git', ['rev-parse', 'HEAD^{tree}'], {
    cwd: REPOSITORY, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  const parentLine = execFileSync('git', ['rev-list', '--parents', '-n', '1', 'HEAD'], {
    cwd: REPOSITORY, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
  }).trim().split(/\s+/u);
  const parent = parentLine.length === 1 ? 'ROOT' : parentLine[1];
  return { head, tree, parent, clean: status.trim() === '' };
}

function digestLines(values) {
  return nyay18Sha256(`${values.join('\n')}\n`);
}

async function sha256File(filename) {
  return nyay18Sha256(await readFile(filename));
}

async function waitForServiceWorker(page) {
  return page.evaluate(async () => {
    if (!('serviceWorker' in navigator)) {
      return {
        supported: false, registrations: 0, active: false, controller: false,
        scriptPathExact: false,
      };
    }
    const registration = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((resolve) => setTimeout(() => resolve(null), 15_000)),
    ]);
    if (!navigator.serviceWorker.controller) {
      await Promise.race([
        new Promise((resolve) => navigator.serviceWorker.addEventListener(
          'controllerchange', resolve, { once: true },
        )),
        new Promise((resolve) => setTimeout(resolve, 10_000)),
      ]);
    }
    const registrations = await navigator.serviceWorker.getRegistrations();
    const scriptPathnames = registrations.flatMap((item) => {
      const worker = item.active ?? item.waiting ?? item.installing;
      if (!worker) return [];
      try { return [new URL(worker.scriptURL).pathname]; } catch { return []; }
    });
    return {
      supported: true,
      registrations: registrations.length,
      active: registration?.active?.state === 'activated',
      controller: navigator.serviceWorker.controller !== null,
      scriptPathExact: scriptPathnames.length === 1 && scriptPathnames[0] === '/sw.js',
    };
  });
}

async function unregisterServiceWorkers(page) {
  return page.evaluate(async () => {
    const registrations = await navigator.serviceWorker.getRegistrations();
    let unregistered = 0;
    for (const registration of registrations) {
      if (await registration.unregister()) unregistered += 1;
    }
    return { initialRegistrations: registrations.length, unregistered };
  });
}

async function runLeadingUnrelatedMatrix(browser) {
  const context = await createFreshContext(browser);
  const page = await context.newPage();
  const bootstrapPath = '__nyay18-leading-bootstrap';
  try {
    await page.route(`${WEB}/${bootstrapPath}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><title>NYAY-18 leading-key bootstrap</title>',
      });
    });
    await page.goto(`${WEB}/${bootstrapPath}`, { waitUntil: 'domcontentloaded' });
    const before = await page.evaluate((fixture) => {
      for (const [key, value] of fixture.candidates) localStorage.setItem(key, value);
      const candidateNames = new Set(fixture.candidates.map(([key]) => key));
      let chosenTarget = null;
      let selectionAttempts = 0;
      let targetIndexBeforeBootstrap = -1;
      let unrelatedBeforeTarget = -1;
      for (const target of fixture.targets) {
        selectionAttempts += 1;
        localStorage.setItem(target, fixture.privateValue);
        const names = Array.from(
          { length: localStorage.length }, (_, index) => localStorage.key(index),
        ).filter((key) => key !== null);
        const targetIndex = names.indexOf(target);
        const leadingCandidates = names.slice(0, targetIndex)
          .filter((key) => candidateNames.has(key)).length;
        if (targetIndex >= fixture.minimumLeading
          && leadingCandidates >= fixture.minimumLeading) {
          chosenTarget = target;
          targetIndexBeforeBootstrap = targetIndex;
          unrelatedBeforeTarget = leadingCandidates;
          break;
        }
        localStorage.removeItem(target);
      }
      if (chosenTarget === null) throw new Error('NYAY18_LEADING_TARGET_NOT_FOUND');
      const targetSurvivors = fixture.targets.filter((key) => (
        Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
          .includes(key)
      )).length;
      return {
        entries: fixture.candidates.map(([key]) => [key, localStorage.getItem(key)]),
        chosenTarget,
        leadingBeforeOwned: targetIndexBeforeBootstrap >= fixture.minimumLeading
          && unrelatedBeforeTarget >= fixture.minimumLeading,
        selectionAttempts,
        targetIndexBeforeBootstrap,
        targetSurvivorsBeforeBootstrap: targetSurvivors,
        unrelatedBeforeTarget,
      };
    }, {
      candidates: leadingCandidateEntries,
      minimumLeading: NYAY18_LEADING_UNRELATED_KEYS,
      privateValue: LOCAL_PRIVATE_SEED,
      targets: leadingTargetKeys,
    });
    await page.unroute(`${WEB}/${bootstrapPath}`);
    await routeCanonicalSession(page, { actor: null });
    await page.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    const after = await page.evaluate((fixture) => {
      const localNames = Array.from(
        { length: localStorage.length }, (_, index) => localStorage.key(index),
      ).filter((key) => key !== null);
      const entries = fixture.candidates.map(([key]) => [key, localStorage.getItem(key)]);
      return {
        entries,
        preservedCount: entries.filter(([, value]) => value !== null).length,
        targetRemoved: !fixture.targets.some((key) => localNames.includes(key)),
      };
    }, { candidates: leadingCandidateEntries, targets: leadingTargetKeys });
    const candidateLines = leadingCandidateEntries.map(([key, value]) => `${key}\0${value}`);
    const beforeLines = before.entries.map(([key, value]) => `${key}\0${value}`);
    const afterLines = after.entries.map(([key, value]) => `${key}\0${value}`);
    const expectedDigest = digestLines(candidateLines);
    return {
      afterSha256: digestLines(afterLines),
      beforeSha256: digestLines(beforeLines),
      candidateCount: leadingCandidateEntries.length,
      candidateInventorySha256: expectedDigest,
      leadingBeforeOwned: before.leadingBeforeOwned,
      preservedCount: after.preservedCount,
      selectionAttempts: before.selectionAttempts,
      targetCandidates: leadingTargetKeys.length,
      targetIndexBeforeBootstrap: before.targetIndexBeforeBootstrap,
      targetInventorySha256: digestLines(leadingTargetKeys),
      targetRemoved: after.targetRemoved,
      targetSurvivorsBeforeBootstrap: before.targetSurvivorsBeforeBootstrap,
      unrelatedBeforeTarget: before.unrelatedBeforeTarget,
      valuesExact: digestLines(beforeLines) === expectedDigest
        && digestLines(afterLines) === expectedDigest,
    };
  } finally {
    await context.close();
  }
}

async function installStorageInstrumentation(context) {
  await context.addInitScript((inventory) => {
    const probeKey = Symbol.for(inventory.probeSymbol);
    const state = {
      localClearCalls: 0,
      sessionClearCalls: 0,
      localLegacyReads: [],
      sessionLegacyReads: [],
    };
    Object.defineProperty(globalThis, probeKey, {
      configurable: false, enumerable: false, writable: false, value: state,
    });
    const localExact = new Set(inventory.localExact);
    const sessionExact = new Set(inventory.sessionExact);
    const isLegacyLocal = (key) => localExact.has(key)
      || inventory.localPrefixes.some((prefix) => key.startsWith(prefix));
    const nativeGetItem = Storage.prototype.getItem;
    Storage.prototype.getItem = function getItem(key) {
      const normalized = String(key);
      if (this === globalThis.localStorage && isLegacyLocal(normalized)) {
        state.localLegacyReads.push(normalized);
      }
      if (this === globalThis.sessionStorage && sessionExact.has(normalized)) {
        state.sessionLegacyReads.push(normalized);
      }
      return Reflect.apply(nativeGetItem, this, [key]);
    };
    if (typeof Storage.prototype.clear !== 'function') {
      throw new Error('NYAY18_STORAGE_CLEAR_INSTRUMENTATION_UNAVAILABLE');
    }
    Object.defineProperty(Storage.prototype, 'clear', {
      configurable: true,
      value() {
        if (this === globalThis.localStorage) state.localClearCalls += 1;
        if (this === globalThis.sessionStorage) state.sessionClearCalls += 1;
        throw new DOMException('NYAY18_STORAGE_CLEAR_FORBIDDEN', 'SecurityError');
      },
    });
  }, {
    localExact: NYAY18_LEGACY_LOCAL_EXACT_KEYS,
    localPrefixes: NYAY18_LEGACY_LOCAL_PREFIXES,
    sessionExact: NYAY18_LEGACY_SESSION_EXACT_KEYS,
    probeSymbol: STORAGE_PROBE_SYMBOL,
  });
}

async function installPrivacySinkInstrumentation(context) {
  await context.addInitScript(({ detectorCanary, probeName, secrets }) => {
    const state = {
      secretWrites: { cache: 0, cookie: 0, dom: 0, history: 0, storage: 0 },
      detectorCanaryWrites: { cache: 0, cookie: 0, dom: 0, history: 0, storage: 0 },
      indexedDbCanaryWrites: 0,
      databaseDeleteCalls: 0,
      databaseOpenCalls: 0,
      objectStoreCreateCalls: 0,
      writeCalls: 0,
      suspended: false,
    };
    Object.defineProperty(globalThis, probeName, {
      configurable: false, enumerable: false, writable: false, value: state,
    });
    const serialize = (value) => {
      try { return typeof value === 'string' ? value : JSON.stringify(value); } catch { return ''; }
    };
    const classify = (surface, values) => {
      if (state.suspended) return;
      const serialized = values.map(serialize).join('\n');
      if (secrets.some((secret) => serialized.includes(secret))) state.secretWrites[surface] += 1;
      if (serialized.includes(detectorCanary)) state.detectorCanaryWrites[surface] += 1;
    };
    const containsSecret = (values) => values.map(serialize).join('\n');

    const nativeAppendChild = Node.prototype.appendChild;
    Node.prototype.appendChild = function appendChild(node) {
      classify('dom', [node?.textContent, node instanceof Element ? node.outerHTML : '']);
      return Reflect.apply(nativeAppendChild, this, [node]);
    };
    const nativeInsertBefore = Node.prototype.insertBefore;
    Node.prototype.insertBefore = function insertBefore(node, reference) {
      classify('dom', [node?.textContent, node instanceof Element ? node.outerHTML : '']);
      return Reflect.apply(nativeInsertBefore, this, [node, reference]);
    };
    const nativeSetAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function setAttribute(name, value) {
      classify('dom', [name, value]);
      return Reflect.apply(nativeSetAttribute, this, [name, value]);
    };
    const nativeInsertAdjacentHtml = Element.prototype.insertAdjacentHTML;
    Element.prototype.insertAdjacentHTML = function insertAdjacentHTML(position, text) {
      classify('dom', [position, text]);
      return Reflect.apply(nativeInsertAdjacentHtml, this, [position, text]);
    };
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        classify('dom', [
          record.oldValue,
          record.target?.textContent,
          ...[...record.addedNodes].map((node) => node.textContent),
        ]);
      }
    });
    observer.observe(document, {
      attributes: true, attributeOldValue: true, characterData: true,
      characterDataOldValue: true, childList: true, subtree: true,
    });

    const nativePushState = History.prototype.pushState;
    History.prototype.pushState = function pushState(...args) {
      classify('history', args);
      return Reflect.apply(nativePushState, this, args);
    };
    const nativeReplaceState = History.prototype.replaceState;
    History.prototype.replaceState = function replaceState(...args) {
      classify('history', args);
      return Reflect.apply(nativeReplaceState, this, args);
    };
    const nativeOpenWindow = globalThis.open;
    globalThis.open = function open(...args) {
      classify('history', args);
      return Reflect.apply(nativeOpenWindow, this, args);
    };
    addEventListener('hashchange', (event) => {
      classify('history', [event.oldURL, event.newURL]);
    });

    const cookieDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
    if (cookieDescriptor?.get && cookieDescriptor.set) {
      Object.defineProperty(Document.prototype, 'cookie', {
        configurable: cookieDescriptor.configurable,
        enumerable: cookieDescriptor.enumerable,
        get() { return Reflect.apply(cookieDescriptor.get, this, []); },
        set(value) {
          classify('cookie', [value]);
          Reflect.apply(cookieDescriptor.set, this, [value]);
        },
      });
    }

    const nativeStorageSet = Storage.prototype.setItem;
    Storage.prototype.setItem = function setItem(key, value) {
      classify('storage', [key, value]);
      return Reflect.apply(nativeStorageSet, this, [key, value]);
    };

    const nativeCachePut = Cache.prototype.put;
    Cache.prototype.put = async function put(request, response) {
      let body = '';
      try { body = await response.clone().text(); } catch { /* opaque response */ }
      classify('cache', [request instanceof Request ? request.url : request, body]);
      return Reflect.apply(nativeCachePut, this, [request, response]);
    };
    for (const method of ['add', 'addAll']) {
      const nativeCacheWrite = Cache.prototype[method];
      Cache.prototype[method] = function instrumentedCacheWrite(...args) {
        classify('cache', args.flat());
        return Reflect.apply(nativeCacheWrite, this, args);
      };
    }
    for (const method of ['open', 'delete']) {
      const nativeCacheStorageWrite = CacheStorage.prototype[method];
      CacheStorage.prototype[method] = function instrumentedCacheStorageWrite(...args) {
        classify('cache', args);
        return Reflect.apply(nativeCacheStorageWrite, this, args);
      };
    };

    const nativeOpen = IDBFactory.prototype.open;
    IDBFactory.prototype.open = function open(...args) {
      state.databaseOpenCalls += 1;
      if (secrets.some((secret) => containsSecret(args).includes(secret))) {
        state.indexedDbCanaryWrites += 1;
      }
      return Reflect.apply(nativeOpen, this, args);
    };
    const nativeDeleteDatabase = IDBFactory.prototype.deleteDatabase;
    IDBFactory.prototype.deleteDatabase = function deleteDatabase(...args) {
      state.databaseDeleteCalls += 1;
      if (secrets.some((secret) => containsSecret(args).includes(secret))) {
        state.indexedDbCanaryWrites += 1;
      }
      return Reflect.apply(nativeDeleteDatabase, this, args);
    };
    const nativeCreateObjectStore = IDBDatabase.prototype.createObjectStore;
    IDBDatabase.prototype.createObjectStore = function createObjectStore(...args) {
      state.objectStoreCreateCalls += 1;
      if (secrets.some((secret) => containsSecret(args).includes(secret))) {
        state.indexedDbCanaryWrites += 1;
      }
      return Reflect.apply(nativeCreateObjectStore, this, args);
    };
    for (const method of ['add', 'put']) {
      const nativeWrite = IDBObjectStore.prototype[method];
      IDBObjectStore.prototype[method] = function instrumentedWrite(...args) {
        state.writeCalls += 1;
        if (secrets.some((secret) => containsSecret(args).includes(secret))) {
          state.indexedDbCanaryWrites += 1;
        }
        return Reflect.apply(nativeWrite, this, args);
      };
    }
  }, {
    detectorCanary: 'nyay18-instrumentation-canary',
    probeName: '__nyay18IndexedDbProbe',
    secrets: [LOCAL_PRIVATE_SEED, SESSION_PRIVATE_SEED, PRIVATE_SINK_SEED, PRIVATE_SHELL_SEED],
  });
}

async function seedLegacySurfaces(page) {
  return page.evaluate(async (fixture) => {
    const privacyProbe = globalThis.__nyay18IndexedDbProbe;
    if (privacyProbe) privacyProbe.suspended = true;
    localStorage.removeItem(fixture.currentThemeKey);
    for (const key of fixture.localKeys) localStorage.setItem(key, fixture.localValue);
    localStorage.setItem('ls-theme', 'dark');
    localStorage.setItem(fixture.unrelatedLocalKey, fixture.unrelatedLocalValue);
    for (const key of fixture.sessionKeys) sessionStorage.setItem(key, fixture.sessionValue);
    sessionStorage.setItem(fixture.unrelatedSessionKey, fixture.unrelatedSessionValue);
    for (let index = 0; index < fixture.cacheKeys.length; index += 32) {
      await Promise.all(fixture.cacheKeys.slice(index, index + 32).map((name) => caches.open(name)));
    }
    const unrelatedCache = await caches.open(fixture.unrelatedCacheKey);
    await unrelatedCache.put(
      new Request(new URL(fixture.hostileAssetPath, location.origin)),
      new Response(
        `globalThis.__nyay18UnrelatedAssetPoison = true; /* ${fixture.poisonMarker} */`,
        { headers: { 'Content-Type': 'application/javascript' } },
      ),
    );
    await unrelatedCache.put(
      new Request(new URL('/index.html', location.origin)),
      new Response(
        `<script>parent.postMessage('${fixture.poisonMarker}', '*')</script>`,
        { headers: { 'Content-Type': 'text/html' } },
      ),
    );
    if (privacyProbe) privacyProbe.suspended = false;
    const localNames = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index));
    const sessionNames = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
    const cacheNames = await caches.keys();
    return {
      localSeeded: fixture.localKeys.filter((key) => localNames.includes(key)).length,
      sessionSeeded: fixture.sessionKeys.filter((key) => sessionNames.includes(key)).length,
      cacheSeeded: fixture.cacheKeys.filter((key) => cacheNames.includes(key)).length,
      localUnrelated: localNames.includes(fixture.unrelatedLocalKey),
      sessionUnrelated: sessionNames.includes(fixture.unrelatedSessionKey),
      cacheUnrelated: cacheNames.includes(fixture.unrelatedCacheKey),
      unrelatedPoisonEntries: (await unrelatedCache.keys()).length,
      retiredCurrentSeeded: cacheNames.includes(fixture.retiredCurrentCache),
    };
  }, {
    localKeys: legacyLocalSeedKeys,
    sessionKeys: NYAY18_LEGACY_SESSION_EXACT_KEYS,
    cacheKeys: legacyCacheSeedKeys,
    retiredCurrentCache: NYAY18_RETIRED_CURRENT_CACHE,
    localValue: LOCAL_PRIVATE_SEED,
    sessionValue: SESSION_PRIVATE_SEED,
    currentThemeKey: CURRENT_THEME_KEY,
    unrelatedLocalKey: NYAY18_UNRELATED_CANARIES.local,
    unrelatedSessionKey: NYAY18_UNRELATED_CANARIES.session,
    unrelatedCacheKey: NYAY18_UNRELATED_CANARIES.cache,
    hostileAssetPath: HOSTILE_ASSET_PATH,
    poisonMarker: UNRELATED_POISON_MARKER,
    unrelatedLocalValue: UNRELATED_LOCAL_VALUE,
    unrelatedSessionValue: UNRELATED_SESSION_VALUE,
  });
}

async function runPrivacySinkInstrumentationCanaries(page) {
  return page.evaluate(async ({ canary, currentCache }) => {
    const probe = globalThis.__nyay18IndexedDbProbe;
    if (!probe) {
      return {
        continuousCacheWrites: -1,
        continuousCookieWrites: -1,
        continuousDomWrites: -1,
        continuousHistoryWrites: -1,
        continuousStorageWrites: -1,
        indexedDbCanaryWrites: -1,
        indexedDbDeleteCalls: -1,
        indexedDbOpenCalls: -1,
        indexedDbWriteCalls: -1,
        instrumentationCacheCanaryDetected: false,
        instrumentationCookieCanaryDetected: false,
        instrumentationDomCanaryDetected: false,
        instrumentationHistoryCanaryDetected: false,
        instrumentationStorageCanaryDetected: false,
        probeAvailable: false,
      };
    }
    const node = document.createElement('span');
    node.textContent = canary;
    document.body.append(node);
    node.remove();

    const originalState = history.state;
    const originalUrl = `${location.pathname}${location.search}${location.hash}`;
    history.replaceState({ canary }, '', `${location.pathname}${location.search}#${canary}`);
    history.replaceState(originalState, '', originalUrl);

    localStorage.setItem(canary, canary);
    localStorage.removeItem(canary);
    document.cookie = `${canary}=1; Path=/; SameSite=Strict`;
    document.cookie = `${canary}=; Max-Age=0; Path=/; SameSite=Strict`;

    const cache = await caches.open(currentCache);
    const canaryRequest = `/assets/${canary}.txt`;
    await cache.put(canaryRequest, new Response(canary));
    await cache.delete(canaryRequest);
    await new Promise((resolve) => setTimeout(resolve, 0));
    return {
      continuousCacheWrites: probe.secretWrites.cache,
      continuousCookieWrites: probe.secretWrites.cookie,
      continuousDomWrites: probe.secretWrites.dom,
      continuousHistoryWrites: probe.secretWrites.history,
      continuousStorageWrites: probe.secretWrites.storage,
      indexedDbCanaryWrites: probe.indexedDbCanaryWrites,
      indexedDbDeleteCalls: probe.databaseDeleteCalls,
      indexedDbOpenCalls: probe.databaseOpenCalls,
      indexedDbWriteCalls: probe.objectStoreCreateCalls + probe.writeCalls,
      instrumentationCacheCanaryDetected: probe.detectorCanaryWrites.cache > 0,
      instrumentationCookieCanaryDetected: probe.detectorCanaryWrites.cookie > 0,
      instrumentationDomCanaryDetected: probe.detectorCanaryWrites.dom > 0,
      instrumentationHistoryCanaryDetected: probe.detectorCanaryWrites.history > 0,
      instrumentationStorageCanaryDetected: probe.detectorCanaryWrites.storage > 0,
      probeAvailable: true,
    };
  }, { canary: 'nyay18-instrumentation-canary', currentCache: CURRENT_CACHE });
}

async function waitForLegacyRetirement(page) {
  await page.waitForFunction(async (inventory) => {
    const localNames = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index));
    const sessionNames = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index));
    const cacheNames = await caches.keys();
    const localRetired = localNames.every((key) => key !== null
      && !inventory.localExact.includes(key)
      && !inventory.localPrefixes.some((prefix) => key.startsWith(prefix)));
    const sessionRetired = sessionNames.every((key) => key !== null
      && !inventory.sessionExact.includes(key));
    const cacheRetired = cacheNames.every((key) => (
      key !== inventory.retiredCurrentCache
      && !inventory.cachePrefixes.some((prefix) => key.startsWith(prefix))
    ));
    return localRetired && sessionRetired && cacheRetired;
  }, {
    localExact: NYAY18_LEGACY_LOCAL_EXACT_KEYS,
    localPrefixes: NYAY18_LEGACY_LOCAL_PREFIXES,
    sessionExact: NYAY18_LEGACY_SESSION_EXACT_KEYS,
    cachePrefixes: NYAY18_LEGACY_CACHE_PREFIXES,
    retiredCurrentCache: NYAY18_RETIRED_CURRENT_CACHE,
  }, { timeout: 20_000 });
}

async function storageTelemetry(page) {
  return page.evaluate((probeSymbol) => {
    const state = globalThis[Symbol.for(probeSymbol)];
    if (!state) return null;
    return {
      localClearCalls: state.localClearCalls,
      sessionClearCalls: state.sessionClearCalls,
      localLegacyReads: state.localLegacyReads.length,
      themeReads: state.localLegacyReads.filter((key) => key === 'ls-theme').length,
      nonThemeLegacyReads: state.localLegacyReads.filter((key) => key !== 'ls-theme').length,
      sessionLegacyReads: state.sessionLegacyReads.length,
    };
  }, STORAGE_PROBE_SYMBOL);
}

function legacyNamespace(name) {
  return /^(?:ls[-_.:]|legalsaathi|legal[\s._:-]*saathi)/iu.test(name)
    || /^__legalsaathi/iu.test(name);
}

function nyayOneNamespace(name) {
  return /^(?:nyayone[._:-]|__nyayone)/iu.test(name);
}

async function runtimeSurfaceSnapshot(page, context) {
  const browser = await page.evaluate(async (fixture) => {
    const localNames = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
      .filter((key) => key !== null);
    const sessionNames = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
      .filter((key) => key !== null);
    const cacheNames = await caches.keys();
    const globalNames = Reflect.ownKeys(globalThis).map((key) => (
      typeof key === 'string' ? key : Symbol.keyFor(key) ?? key.description ?? ''
    ));
    const aria = Array.from(document.querySelectorAll('[aria-label]'))
      .map((element) => element.getAttribute('aria-label') ?? '');
    const downloads = Array.from(document.querySelectorAll('[download]'))
      .map((element) => element.getAttribute('download') ?? '');
    const legacyBrand = /legal[\s._-]*saathi|legalsaathi|लीगल\s*साथी/iu;
    const title = document.title;
    const body = document.body?.innerText ?? '';
    return {
      localNames,
      sessionNames,
      cacheNames,
      globalNames,
      titleExact: title === 'NyayOne',
      bodyNyayOneVisible: /nyayone/iu.test(body),
      legacyTitleMatches: Number(legacyBrand.test(title)),
      legacyBodyMatches: Number(legacyBrand.test(body)),
      legacyAriaMatches: aria.filter((value) => legacyBrand.test(value)).length,
      legacyDownloadMatches: downloads.filter((value) => legacyBrand.test(value)).length,
      legacyGlobalMatches: globalNames.filter((value) => legacyBrand.test(value)).length,
      oldThemeAbsent: !localNames.includes('ls-theme'),
      newThemePresent: localNames.includes(fixture.currentThemeKey),
      migratedDark: localStorage.getItem(fixture.currentThemeKey) === 'dark',
      unrelatedLocalPreserved: localNames.includes(fixture.unrelatedLocalKey),
      unrelatedSessionPreserved: sessionNames.includes(fixture.unrelatedSessionKey),
      unrelatedCachePreserved: cacheNames.includes(fixture.unrelatedCacheKey),
      unrelatedValuesExact:
        localStorage.getItem(fixture.unrelatedLocalKey) === fixture.unrelatedLocalValue
        && sessionStorage.getItem(fixture.unrelatedSessionKey) === fixture.unrelatedSessionValue,
      currentCachePresent: cacheNames.includes(fixture.currentCache),
      retiredCurrentCachePresent: cacheNames.includes(fixture.retiredCurrentCache),
    };
  }, {
    currentThemeKey: CURRENT_THEME_KEY,
    currentCache: CURRENT_CACHE,
    retiredCurrentCache: NYAY18_RETIRED_CURRENT_CACHE,
    unrelatedLocalKey: NYAY18_UNRELATED_CANARIES.local,
    unrelatedSessionKey: NYAY18_UNRELATED_CANARIES.session,
    unrelatedCacheKey: NYAY18_UNRELATED_CANARIES.cache,
    unrelatedLocalValue: UNRELATED_LOCAL_VALUE,
    unrelatedSessionValue: UNRELATED_SESSION_VALUE,
  });
  const cookieNames = (await context.cookies(WEB)).map((cookie) => cookie.name);
  const allowed = {
    local: new Set([CURRENT_THEME_KEY]),
    session: new Set(),
    cache: new Set([CURRENT_CACHE]),
    cookie: new Set(['nyayone_session']),
    global: new Set(['__nyayoneVideoRoom', '__nyayoneVideoTransport']),
  };
  const surfaces = [
    ['local', browser.localNames],
    ['session', browser.sessionNames],
    ['cache', browser.cacheNames],
    ['cookie', cookieNames],
    ['global', browser.globalNames],
  ];
  let unexpectedOwnedNames = 0;
  let nyayOneOwnedNames = 0;
  for (const [surface, names] of surfaces) {
    for (const name of names) {
      if (nyayOneNamespace(name)) {
        nyayOneOwnedNames += 1;
        if (!allowed[surface].has(name)) unexpectedOwnedNames += 1;
      }
      if (legacyNamespace(name)) unexpectedOwnedNames += 1;
    }
  }
  return {
    ...browser,
    legacyLocalNames: browser.localNames.filter(legacyNamespace).length,
    legacySessionNames: browser.sessionNames.filter(legacyNamespace).length,
    legacyCacheNames: browser.cacheNames.filter(legacyNamespace).length,
    retiredCacheNames: browser.cacheNames.filter((name) => (
      name === NYAY18_RETIRED_CURRENT_CACHE || legacyNamespace(name)
    )).length,
    legacyCookieNames: cookieNames.filter(legacyNamespace).length,
    legacyGlobalNames: browser.globalNames.filter(legacyNamespace).length,
    legacyCookieMatches: cookieNames
      .filter((name) => /legal[\s._-]*saathi|legalsaathi/iu.test(name)).length,
    unexpectedOwnedNames,
    nyayOneOwnedNames,
  };
}

async function runLegacyBrandSeparatorCanary(page, context) {
  const cookieName = 'legal.saathi';
  const originalTitle = await page.title();
  await context.addCookies([{ name: cookieName, value: 'canary', url: WEB }]);
  try {
    await page.evaluate(() => {
      document.title = 'legal-saathi';
      const canary = document.createElement('a');
      canary.id = 'nyay18-legacy-brand-detector-canary';
      canary.setAttribute('aria-label', 'legal_saathi');
      canary.setAttribute('download', 'legal.saathi');
      canary.href = '#';
      canary.textContent = 'legal.saathi';
      document.body.append(canary);
      Object.defineProperty(globalThis, 'legal.saathi', {
        configurable: true, value: true,
      });
    });
    const observed = await runtimeSurfaceSnapshot(page, context);
    return [
      observed.legacyTitleMatches >= 1,
      observed.legacyBodyMatches >= 1,
      observed.legacyAriaMatches >= 1,
      observed.legacyDownloadMatches >= 1,
      observed.legacyGlobalMatches >= 1,
      observed.legacyCookieMatches >= 1,
    ].filter(Boolean).length;
  } finally {
    await page.evaluate((title) => {
      document.title = title;
      document.getElementById('nyay18-legacy-brand-detector-canary')?.remove();
      Reflect.deleteProperty(globalThis, 'legal.saathi');
    }, originalTitle);
    await context.clearCookies({ name: cookieName });
  }
}

async function observeS03Viewport(page, viewport, screenshotPath) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const screen = page.locator(S03_SELECTOR);
  await screen.waitFor({ state: 'visible' });
  const metrics = await page.evaluate(({ selector, width, height }) => {
    const nodes = Array.from(document.querySelectorAll(selector));
    const visible = nodes.filter((node) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
        && style.display !== 'none';
    });
    const legacyBrand = /legal[\s._-]*saathi|legalsaathi|लीगल\s*साथी/iu;
    return {
      width,
      height,
      routeExact: location.pathname === '/s-03' && location.search === '' && location.hash === '',
      screenSelectorCount: nodes.length,
      visible: visible.length === 1,
      noHorizontalOverflow: document.documentElement.scrollWidth <= window.innerWidth + 1,
      legacyVisibleMatches: Number(legacyBrand.test(document.body?.innerText ?? '')),
    };
  }, { selector: S03_SELECTOR, width: viewport.width, height: viewport.height });
  await page.screenshot({ path: screenshotPath, fullPage: false });
  return { ...metrics, screenshotCaptured: true };
}

function canonicalStudentActor(index) {
  const suffix = String(index).padStart(12, '0');
  const profileSuffix = String(index + 100).padStart(12, '0');
  return {
    sub: `00000000-0000-4000-8000-${suffix}`,
    roles: ['student'],
    student_profile_id: `00000000-0000-4000-8000-${profileSuffix}`,
    student_verification: 'verified',
    is_minor: false,
    consent_state: ['registration'],
  };
}

async function routeCanonicalSession(page, state, telemetry = null) {
  await page.route('**/api/v1/auth/student/session', async (route) => {
    if (telemetry) {
      telemetry.requestCount += 1;
      if (route.request().method() === 'GET') telemetry.getRequests += 1;
      else telemetry.otherRequests += 1;
      telemetry.canonicalBodies += 1;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(state.actor === null
        ? { authenticated: false, actor: null }
        : { authenticated: true, actor: state.actor }),
    });
  });
}

async function runThemeMatrix(browser) {
  const currentContext = await createFreshContext(browser);
  await installStorageInstrumentation(currentContext);
  await currentContext.addInitScript(({ currentKey }) => {
    localStorage.setItem(currentKey, 'light');
    localStorage.setItem('ls-theme', 'dark');
  }, { currentKey: CURRENT_THEME_KEY });
  const currentPage = await currentContext.newPage();
  await routeCanonicalSession(currentPage, { actor: null });
  await currentPage.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
  await currentPage.locator(S03_SELECTOR).waitFor({ state: 'visible' });
  const currentTelemetry = await storageTelemetry(currentPage);
  const current = await currentPage.evaluate((currentKey) => ({
    currentLightPreserved: localStorage.getItem(currentKey) === 'light',
    oldThemeAbsent: localStorage.getItem('ls-theme') === null,
    resolved: document.documentElement.getAttribute('data-theme'),
  }), CURRENT_THEME_KEY);
  await currentContext.close();

  const invalidContext = await createFreshContext(browser);
  await installStorageInstrumentation(invalidContext);
  await invalidContext.addInitScript(() => {
    localStorage.setItem('ls-theme', 'system');
    const nativeMatchMedia = globalThis.matchMedia?.bind(globalThis);
    globalThis.matchMedia = (query) => {
      if (query === '(prefers-color-scheme: dark)') {
        return {
          matches: false, media: query, onchange: null,
          addEventListener() {}, removeEventListener() {},
          addListener() {}, removeListener() {}, dispatchEvent: () => false,
        };
      }
      return nativeMatchMedia ? nativeMatchMedia(query) : {
        matches: false, media: query, onchange: null,
        addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {}, dispatchEvent: () => false,
      };
    };
  });
  const invalidPage = await invalidContext.newPage();
  await routeCanonicalSession(invalidPage, { actor: null });
  await invalidPage.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
  await invalidPage.locator(S03_SELECTOR).waitFor({ state: 'visible' });
  const invalidTelemetry = await storageTelemetry(invalidPage);
  const invalid = await invalidPage.evaluate((currentKey) => ({
    oldThemeAbsent: localStorage.getItem('ls-theme') === null,
    resolved: document.documentElement.getAttribute('data-theme'),
    stored: localStorage.getItem(currentKey),
  }), CURRENT_THEME_KEY);
  await invalidContext.close();

  return {
    current: {
      currentLightPreserved: current.currentLightPreserved,
      currentWon: current.resolved === 'light',
      legacyDarkSeeded: true,
      legacyThemeReads: currentTelemetry?.themeReads ?? -1,
      oldThemeAbsent: current.oldThemeAbsent,
    },
    invalid: {
      invalidLegacySeeded: true,
      invalidReadOnce: invalidTelemetry?.themeReads === 1,
      oldThemeAbsent: invalid.oldThemeAbsent,
      resolvedLight: invalid.resolved === 'light' && invalid.stored === 'light',
    },
  };
}

function exactPendingFlowProjection(body, purpose) {
  const keys = [
    'attempts_left', 'destination_masked', 'expires_in_seconds',
    'locked_for_seconds', 'purpose', 'resend_allowed',
    'resend_in_seconds', 'status',
  ];
  return body && typeof body === 'object' && !Array.isArray(body)
    && Object.keys(body).sort().join(',') === keys.join(',')
    && body.status === 'pending'
    && body.purpose === purpose
    && /^••••••\d{4}$/u.test(body.destination_masked ?? '')
    && Number.isSafeInteger(body.attempts_left)
    && body.attempts_left > 0
    && Number.isSafeInteger(body.expires_in_seconds)
    && body.expires_in_seconds > 0
    && Number.isSafeInteger(body.resend_in_seconds)
    && body.resend_in_seconds >= 0
    && Number.isSafeInteger(body.locked_for_seconds)
    && body.locked_for_seconds >= 0
    && typeof body.resend_allowed === 'boolean';
}

async function provisionServerPendingFlow(browser, purpose) {
  const context = await createFreshContext(browser);
  const start = purpose === 'login'
    ? await context.request.post(`${WEB}/api/v1/auth/student/login/otp/start`, {
      data: { mobile: '9000000042' },
    })
    : await context.request.post(`${WEB}/api/v1/auth/student/register`, {
      data: {
        first_name: 'Design',
        middle_name: null,
        last_name: 'Fixture',
        mobile: '9000000042',
        dob: '2000-01-01',
        terms_accepted: true,
        terms_version: 'dpdp-2023.v1',
        privacy_notice_acknowledged: true,
        privacy_notice_version: 'dpdp-2023.v1',
      },
    });
  const stateResponse = await context.request.get(`${WEB}/api/v1/auth/student/otp/state`);
  const stateBody = stateResponse.ok() ? await stateResponse.json() : null;
  const cookies = await context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
  const flowCookies = cookies.filter((cookie) => cookie.name === 'nyayone_otp_flow');
  const sessionCookies = cookies.filter((cookie) => cookie.name === 'nyayone_session');
  if (start.status() !== 202
    || stateResponse.status() !== 200
    || stateBody?.status !== 'pending'
    || stateBody?.purpose !== purpose
    || !exactPendingFlowProjection(stateBody, purpose)
    || flowCookies.length !== 1
    || flowCookies[0].httpOnly !== true
    || flowCookies[0].sameSite !== 'Strict'
    || flowCookies[0].path !== '/api/v1'
    || sessionCookies.length !== 0) {
    await context.close();
    throw new Error('NYAY18_SERVER_PENDING_FLOW_INVALID');
  }
  return { context, startStatus: start.status(), stateStatus: stateResponse.status() };
}

async function runServerPendingFlowMatrix(browser) {
  const rows = [];
  for (const [purpose, route, screenSelector] of [
    ['login', '/s-05', '[data-screen="S-05"]'],
    ['signup', '/s-09', '[data-screen="S-09"]'],
  ]) {
    const fixture = await provisionServerPendingFlow(browser, purpose);
    const page = await fixture.context.newPage();
    let otpStateRequestCount = 0;
    let sessionRequestCount = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (request.method() === 'GET'
        && url.pathname === '/api/v1/auth/student/otp/state') otpStateRequestCount += 1;
      if (request.method() === 'GET'
        && url.pathname === '/api/v1/auth/student/session') sessionRequestCount += 1;
    });
    await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded' });
    await page.getByLabel('Six digit code').waitFor({ state: 'visible' });
    const controls = await page.getByLabel('Six digit code').count();
    const verifyControls = await page.getByRole('button', {
      name: 'Verify and continue', exact: true,
    }).count();
    const screen = await page.locator(screenSelector).count();
    const cookies = await fixture.context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
    rows.push({
      controls,
      flowCookies: cookies.filter((cookie) => cookie.name === 'nyayone_otp_flow').length,
      purpose,
      screen,
      sessionCookies: cookies.filter((cookie) => cookie.name === 'nyayone_session').length,
      sessionRequestCount,
      startStatus: fixture.startStatus,
      stateStatus: fixture.stateStatus,
      otpStateRequestCount,
      verifyControls,
    });
    await fixture.context.close();
  }
  return {
    controls: rows.reduce((total, row) => total + row.controls, 0),
    flowCookies: rows.reduce((total, row) => total + row.flowCookies, 0),
    flows: rows.length,
    purposesExact: rows.map((row) => row.purpose).join(',') === 'login,signup',
    screens: rows.reduce((total, row) => total + row.screen, 0),
    serverStateRequests: rows.reduce((total, row) => total + row.otpStateRequestCount, 0),
    sessionCookies: rows.reduce((total, row) => total + row.sessionCookies, 0),
    sessionRequests: rows.reduce((total, row) => total + row.sessionRequestCount, 0),
    startResponses: rows.filter((row) => row.startStatus === 202).length,
    stateResponses: rows.filter((row) => row.stateStatus === 200).length,
    verifyControls: rows.reduce((total, row) => total + row.verifyControls, 0),
  };
}

async function runUnavailableChallengeDenial(page, context) {
  const before = await context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
  const stateResponse = await context.request.get(`${WEB}/api/v1/auth/student/otp/state`);
  const stateBody = stateResponse.status() === 200 ? await stateResponse.json() : null;
  const unavailableKeys = [
    'attempts_left', 'destination_masked', 'expires_in_seconds',
    'locked_for_seconds', 'purpose', 'resend_allowed',
    'resend_in_seconds', 'status',
  ];
  const flowUnavailableProven = stateBody && typeof stateBody === 'object'
    && !Array.isArray(stateBody)
    && Object.keys(stateBody).sort().join(',') === unavailableKeys.join(',')
    && stateBody.status === 'unavailable'
    && stateBody.purpose === null
    && stateBody.destination_masked === null
    && stateBody.attempts_left === null
    && stateBody.expires_in_seconds === null
    && stateBody.resend_in_seconds === null
    && stateBody.locked_for_seconds === null
    && stateBody.resend_allowed === false;
  let otpControls = 0;
  let retiredInlineErrors = 0;
  let routesDenied = 0;
  for (const route of ['/s-05', '/s-09']) {
    await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(/\/s-03$/u);
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    otpControls += await page.getByLabel('Six digit code').count();
    retiredInlineErrors += await page.getByText(
      'This browser cannot safely change sessions. Check browser privacy support and try again.',
      { exact: true },
    ).count();
    routesDenied += new URL(page.url()).pathname === '/s-03' ? 1 : 0;
  }
  const after = await context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
  const cookieShape = (cookies) => cookies.map((cookie) => ({
    domain: cookie.domain,
    httpOnly: cookie.httpOnly,
    name: cookie.name,
    path: cookie.path,
    sameSite: cookie.sameSite,
    secure: cookie.secure,
    value: cookie.value,
  }));
  return {
    cookieInventoryUnchanged: JSON.stringify(cookieShape(before)) === JSON.stringify(cookieShape(after)),
    flowAuthorityAbsent: before.every((cookie) => cookie.name !== 'nyayone_otp_flow')
      && after.every((cookie) => cookie.name !== 'nyayone_otp_flow'),
    flowUnavailableProven,
    otpControlsAbsent: otpControls === 0,
    retiredInlineErrorAbsent: retiredInlineErrors === 0,
    routesDenied,
  };
}

async function runAnonymousChallengeDenialMatrix(browser) {
  const context = await createFreshContext(browser);
  const page = await context.newPage();
  try {
    return await runUnavailableChallengeDenial(page, context);
  } finally {
    await context.close();
  }
}

async function installRuntimeStorageFailure(page, mode) {
  const applyStorageFailure = (currentMode) => {
    const legacyKey = 'ls-onboarding-seen';
    localStorage.setItem(legacyKey, 'nyay18-private-local-value');
    if (currentMode === 'inaccessible') {
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        get() { throw new DOMException('synthetic storage denial', 'SecurityError'); },
      });
      return;
    }
    const nativeRemove = Storage.prototype.removeItem;
    Storage.prototype.removeItem = function removeItem(key) {
      if (currentMode === 'throw' && String(key) === legacyKey) {
        throw new DOMException('synthetic removal denial', 'SecurityError');
      }
      if (currentMode === 'no_progress' && String(key) === legacyKey) return;
      return Reflect.apply(nativeRemove, this, [key]);
    };
  };
  await page.context().addInitScript(applyStorageFailure, mode);
  await page.evaluate(applyStorageFailure, mode);
}

function internalCookieInventory(cookies) {
  return cookies.map((cookie) => ({
    domain: cookie.domain,
    httpOnly: cookie.httpOnly,
    name: cookie.name,
    path: cookie.path,
    sameSite: cookie.sameSite,
    secure: cookie.secure,
    value: cookie.value,
  })).sort((left, right) => left.name.localeCompare(right.name));
}

function isExactPendingStateResponse(response) {
  const url = new URL(response.url());
  return response.request().method() === 'GET'
    && url.origin === new URL(WEB).origin
    && url.pathname === '/api/v1/auth/student/otp/state'
    && url.search === ''
    && url.hash === '';
}

async function runFailClosedMatrix(browser) {
  const outcomes = {};
  for (const mode of ['inaccessible', 'throw', 'no_progress', 'unsupported_locks']) {
    const fixture = mode === 'unsupported_locks'
      ? { context: await createFreshContext(browser) }
      : await provisionServerPendingFlow(browser, 'login');
    const { context } = fixture;
    if (mode === 'unsupported_locks') {
      await context.addInitScript(() => {
        const probe = { cookieOperations: 0 };
        Object.defineProperty(globalThis, '__nyay18FailClosedProbe', {
          configurable: false, value: probe,
        });
        Object.defineProperty(navigator, 'locks', {
          configurable: true, get: () => undefined,
        });
      });
    }
    const page = await context.newPage();
    let sessionRequests = 0;
    let cookieOperations = 0;
    let actionAttempts = 0;
    let actionRejected;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/v1/auth/student/session') sessionRequests += 1;
      if (request.method() !== 'GET' && url.pathname.startsWith('/api/v1/auth/student/')) {
        cookieOperations += 1;
      }
    });
    if (mode === 'unsupported_locks') {
      await routeCanonicalSession(page, { actor: canonicalStudentActor(700) });
      await page.goto(`${WEB}/s-60`, { waitUntil: 'domcontentloaded' });
      await page.locator(SESSION_UNAVAILABLE).waitFor({ state: 'visible', timeout: 15_000 });
      await page.goto(`${WEB}/s-04`, { waitUntil: 'domcontentloaded' });
      await page.locator('[data-screen="S-04"]').waitFor({ state: 'visible' });
      await page.getByLabel('Mobile Number', { exact: true }).fill('9876543210');
      actionAttempts += 1;
      await page.getByRole('button', { name: 'Send Code', exact: true }).click();
      const rejected = page.getByText(
        'A one time code could not be requested. Please retry.', { exact: true },
      );
      await rejected.waitFor({ state: 'visible' });
      actionRejected = await rejected.count() === 1 && cookieOperations === 0;
    } else {
      const pendingStateResponsePromise = page.waitForResponse(isExactPendingStateResponse);
      await page.goto(`${WEB}/s-05`, { waitUntil: 'domcontentloaded' });
      const pendingStateResponse = await pendingStateResponsePromise;
      const pendingStateFinishedError = await pendingStateResponse.finished();
      if (pendingStateResponse.status() !== 200 || pendingStateFinishedError !== null) {
        throw new Error('NYAY18_PENDING_STATE_READINESS_FAILED');
      }
      await page.locator('[data-screen="S-05"]').waitFor({ state: 'visible' });
      const pendingControl = page.getByLabel('Six digit code');
      await pendingControl.waitFor({ state: 'visible' });
      const pendingControls = await pendingControl.count();
      const beforeCookies = await context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
      const beforeFlowCookies = beforeCookies.filter(
        (cookie) => cookie.name === 'nyayone_otp_flow',
      );
      const pendingAuthorityProven = pendingControls === 1
        && beforeFlowCookies.length === 1
        && beforeFlowCookies[0].httpOnly === true
        && beforeFlowCookies[0].path === '/api/v1'
        && beforeFlowCookies[0].sameSite === 'Strict';

      await routeCanonicalSession(page, { actor: canonicalStudentActor(700) });
      await page.route('**/api/v1/student/profile', async (route) => {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          headers: { 'Cache-Control': 'no-store' },
          body: JSON.stringify(incompleteProfileProjection()),
        });
      });
      await page.goto(`${WEB}/s-07`, { waitUntil: 'domcontentloaded' });
      const signOut = page.getByRole('button', { name: 'Sign out', exact: true });
      await signOut.waitFor({ state: 'visible' });
      await installRuntimeStorageFailure(page, mode);
      actionAttempts += 1;
      await signOut.click();
      await page.waitForURL(/\/s-03$/u);
      await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
      const safeEntryVisible = await page.locator(S03_SELECTOR).count() === 1;
      const afterCookies = await context.cookies(`${WEB}/api/v1/auth/student/otp/state`);
      const afterFlowCookies = afterCookies.filter(
        (cookie) => cookie.name === 'nyayone_otp_flow',
      );
      const cookieInventoryUnchanged = JSON.stringify(internalCookieInventory(beforeCookies))
        === JSON.stringify(internalCookieInventory(afterCookies));
      const flowAuthorityPreserved = beforeFlowCookies.length === 1
        && afterFlowCookies.length === 1
        && beforeFlowCookies[0].value === afterFlowCookies[0].value;
      actionRejected = pendingAuthorityProven
        && safeEntryVisible
        && cookieInventoryUnchanged
        && flowAuthorityPreserved
        && cookieOperations === 0;
      outcomes[mode] = {
        cookieInventoryUnchanged,
        flowAuthorityPreserved,
        pendingAuthorityProven,
        pendingControlsProven: pendingControls === 1,
        safeEntryVisible,
      };
    }
    await page.goto(`${WEB}/s-60`, { waitUntil: 'domcontentloaded' });
    await page.locator(SESSION_UNAVAILABLE).waitFor({ state: 'visible', timeout: 15_000 });
    const unavailableVisible = await page.locator(SESSION_UNAVAILABLE).count() === 1;
    const privateMounted = await page.locator(PRIVATE_SCREEN).count() > 0;
    outcomes[mode] = {
      ...outcomes[mode],
      cookieOperations,
      actionAttempts,
      actionRejected,
      privateMounted,
      sessionRequests,
      unavailableVisible,
    };
    await context.close();
  }
  return outcomes;
}

function incompleteProfileProjection() {
  return {
    access_mode: 'full', completed_sections: [], completion_percent: 0,
    completion_version: 'v1', disabled_capabilities: [],
    missing_requirements: [
      'personal.preferred_language', 'personal.city', 'academic.college',
      'academic.year_of_study', 'academic.enrolment_number',
      'interests.interests', 'interests.goals',
    ],
    guardian: { required: false, status: 'not_required' },
    institutional_email_status: 'not_provided', is_complete: false,
    next_incomplete_section: 'personal',
    profile: {
      academic: {
        bar_enrolment_number: null, college: null, enrolment_number: null,
        institutional_email: null, year_of_study: null,
      },
      interests: { goals: [], interests: [] },
      personal: {
        city: null, date_of_birth: '2000-01-01', first_name: 'Boundary',
        last_name: 'Owner', middle_name: null, preferred_language: null,
        pronouns: null,
      },
    },
    profile_prompt: { dismissed_for_session: false, should_show: true },
    profile_version: 1,
  };
}

function settingsProjection() {
  return {
    language: 'English', notif_email: true, notif_sms: false,
    notif_updates: true,
    privacy: [
      { enabled: true, kind: 'analytics' },
      { enabled: false, kind: 'marketing' },
      { enabled: false, kind: 'share_partners' },
    ],
    theme: 'dark', version: 7,
  };
}

async function runLifecycleScenario(browser, name, index) {
  const context = await createFreshContext(browser);
  const actorA = canonicalStudentActor(index * 2 + 1);
  const actorB = canonicalStudentActor(index * 2 + 2);
  const state = { actor: actorA };
  await context.addInitScript(({
    actorIdentifiers, currentThemeKey, reminderKey, reportKey, unrelatedKey,
  }) => {
    localStorage.setItem(currentThemeKey, 'dark');
    localStorage.setItem(unrelatedKey, 'lifecycle-unrelated-canary');
    for (const actorIdentifier of actorIdentifiers) {
      localStorage.setItem(`${reportKey}${actorIdentifier}`, 'nyay18-private-local-value');
      localStorage.setItem(`${reminderKey}${actorIdentifier}`, 'nyay18-private-local-value');
    }
    localStorage.setItem('ls-onboarding-seen', 'nyay18-private-local-value');
    sessionStorage.setItem(
      'legalsaathi.student.registration.v2',
      'nyay18-private-session-value',
    );
    const probe = { starts: 0, ends: 0 };
    Object.defineProperty(globalThis, '__nyay18LifecycleProbe', { value: probe });
    addEventListener('nyayone:student-auth-transition-started', () => { probe.starts += 1; });
    addEventListener('nyayone:student-auth-changed', () => { probe.ends += 1; });
  }, {
    actorIdentifiers: [actorA.sub, actorA.student_profile_id],
    currentThemeKey: CURRENT_THEME_KEY,
    reminderKey: 'nyayone.student.reminder-prefs.v1.',
    reportKey: 'nyayone.student.reports.v1.',
    unrelatedKey: NYAY18_UNRELATED_CANARIES.local,
  });
  const page = await context.newPage();
  const requests = {
    deletion: 0, logout: 0, private401: 0, session: 0,
  };
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/v1/auth/student/session' && request.method() === 'GET') {
      requests.session += 1;
    }
    if (pathname === '/api/v1/auth/student/logout' && request.method() === 'POST') {
      requests.logout += 1;
    }
    if (pathname === '/api/v1/student/privacy/delete' && request.method() === 'POST') {
      requests.deletion += 1;
    }
    if (pathname === '/api/v1/student/settings'
      && request.method() === 'GET'
      && (name === 'revocation' || name === 'canonical_loss')) requests.private401 += 1;
  });
  await routeCanonicalSession(page, state);
  await page.route('**/api/v1/student/profile', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(incompleteProfileProjection()),
    });
  });

  let releasePrivate401 = () => undefined;
  const private401Gate = new Promise((resolve) => { releasePrivate401 = resolve; });
  if (name === 'revocation' || name === 'canonical_loss') {
    const code = name === 'revocation'
      ? 'session_authority_required' : 'authentication_required';
    await page.route('**/api/v1/student/settings', async (route) => {
      await private401Gate;
      state.actor = null;
      await route.fulfill({
        status: 401, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' },
        body: JSON.stringify({ detail: { code } }),
      });
    });
  } else if (name === 'deletion') {
    await page.route('**/api/v1/student/settings', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' },
        body: JSON.stringify(settingsProjection()),
      });
    });
    await page.route('**/api/v1/auth/student/otp/state', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' },
        body: JSON.stringify({
          attempts_left: null, destination_masked: null, expires_in_seconds: null,
          locked_for_seconds: null, purpose: 'recovery', resend_allowed: false,
          resend_in_seconds: null, status: 'verified',
        }),
      });
    });
    await page.route('**/api/v1/student/privacy/delete', async (route) => {
      state.actor = null;
      await route.fulfill({
        status: 202, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' },
        body: JSON.stringify({ request_id: 'd'.repeat(32), status: 'pending' }),
      });
    });
  }
  if (name === 'logout') {
    await page.route('**/api/v1/auth/student/logout', async (route) => {
      state.actor = null;
      await route.fulfill({
        status: 200, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' }, body: JSON.stringify({}),
      });
    });
  }

  const initialRoute = name === 'logout' ? '/s-07'
    : name === 'deletion' ? '/s-19'
      : (name === 'revocation' || name === 'canonical_loss') ? '/s-18' : '/s-60';
  const initialScreen = name === 'logout' ? '[data-screen="S-07"]'
    : name === 'deletion' ? '[data-screen="S-19"]'
      : (name === 'revocation' || name === 'canonical_loss')
        ? '[data-screen="S-18"]' : PRIVATE_SCREEN;
  await page.goto(`${WEB}${initialRoute}`, { waitUntil: 'domcontentloaded' });
  await page.locator(initialScreen).waitFor({ state: 'visible' });
  const actorAIdentifiers = [actorA.sub, actorA.student_profile_id];
  const actorKeysPerScenario = actorAIdentifiers.length * 2;
  const coldActorKeysPurged = await page.evaluate((actorIdentifiers) => actorIdentifiers
    .flatMap((actorIdentifier) => [
      `nyayone.student.reports.v1.${actorIdentifier}`,
      `nyayone.student.reminder-prefs.v1.${actorIdentifier}`,
    ])
    .filter((key) => localStorage.getItem(key) === null).length, actorAIdentifiers);
  await page.evaluate(({ actorIdentifiers, reportKey, reminderKey }) => {
    for (const actorIdentifier of actorIdentifiers) {
      localStorage.setItem(`${reportKey}${actorIdentifier}`, 'nyay18-private-local-value');
      localStorage.setItem(`${reminderKey}${actorIdentifier}`, 'nyay18-private-local-value');
    }
    localStorage.setItem('ls-reports-lifecycle', 'nyay18-private-local-value');
    sessionStorage.setItem(
      'legalsaathi.student.privacy.delete.v1',
      'nyay18-private-session-value',
    );
  }, {
    actorIdentifiers: actorAIdentifiers,
    reportKey: 'nyayone.student.reports.v1.',
    reminderKey: 'nyayone.student.reminder-prefs.v1.',
  });

  let actorRotationRediscoveryResponses = 0;
  const actorRotationResponse = name === 'actor_rotation'
    ? page.waitForResponse(async (response) => {
      const request = response.request();
      if (request.method() !== 'GET'
        || new URL(response.url()).pathname !== '/api/v1/auth/student/session'
        || response.status() !== 200) return false;
      try {
        const projection = await response.json();
        return projection?.authenticated === true && projection.actor?.sub === actorB.sub;
      } catch {
        return false;
      }
    }, { timeout: 15_000 })
    : null;
  if (name === 'logout') {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  } else if (name === 'deletion') {
    failureStage = 'normative_lifecycle_matrix_deletion_open_confirmation';
    await page.getByRole('button', { name: 'Delete…', exact: true }).click();
    failureStage = 'normative_lifecycle_matrix_deletion_type_confirmation';
    await page.getByLabel('Type DELETE to confirm').fill('DELETE');
    failureStage = 'normative_lifecycle_matrix_deletion_submit';
    await page.getByRole('button', { name: 'Delete my account', exact: true }).click();
  } else if (name === 'revocation' || name === 'canonical_loss') {
    releasePrivate401();
  } else {
    state.actor = name === 'actor_rotation' ? actorB : null;
    await page.evaluate(() => dispatchEvent(new StorageEvent('storage', { key: null })));
  }

  if (name === 'actor_rotation') {
    await actorRotationResponse;
    actorRotationRediscoveryResponses = 1;
    await page.waitForFunction((actorIdentifiers) => actorIdentifiers.every((actorIdentifier) => (
      localStorage.getItem(`nyayone.student.reports.v1.${actorIdentifier}`) === null
      && localStorage.getItem(`nyayone.student.reminder-prefs.v1.${actorIdentifier}`) === null
    )), actorAIdentifiers);
    await page.locator(PRIVATE_SCREEN).waitFor({ state: 'visible' });
  } else {
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
  }
  const surface = await page.evaluate(({ actorIdentifiers, currentThemeKey, unrelatedKey }) => {
    const localNames = Array.from(
      { length: localStorage.length }, (_, current) => localStorage.key(current),
    ).filter((key) => key !== null);
    const sessionNames = Array.from(
      { length: sessionStorage.length }, (_, current) => sessionStorage.key(current),
    ).filter((key) => key !== null);
    const retiredLocal = localNames.filter((key) => (
      key.startsWith('ls-') || key.startsWith('legalsaathi.')
    ));
    const retiredSession = sessionNames.filter((key) => key.startsWith('legalsaathi.'));
    const actorKeys = actorIdentifiers.flatMap((actorIdentifier) => [
      `nyayone.student.reports.v1.${actorIdentifier}`,
      `nyayone.student.reminder-prefs.v1.${actorIdentifier}`,
    ]);
    const transition = globalThis.__nyay18LifecycleProbe ?? { starts: -1, ends: -1 };
    return {
      teardownActorKeysPurged: actorKeys.filter((key) => !localNames.includes(key)).length,
      currentThemePreserved: localStorage.getItem(currentThemeKey) === 'dark',
      unrelatedPreserved:
        localStorage.getItem(unrelatedKey) === 'lifecycle-unrelated-canary',
      retiredAbsent: retiredLocal.length === 0 && retiredSession.length === 0,
      transitionEnds: transition.ends,
      transitionStarts: transition.starts,
    };
  }, {
    currentThemeKey: CURRENT_THEME_KEY,
    unrelatedKey: NYAY18_UNRELATED_CANARIES.local,
    actorIdentifiers: actorAIdentifiers,
  });
  const privateMounted = await page.locator(initialScreen).count() > 0;
  const publicMounted = await page.locator(S03_SELECTOR).count() > 0;
  const transitionExpected = [
    'logout', 'expiry', 'deletion', 'revocation', 'canonical_loss',
  ].includes(name);
  const endpointExact = (name !== 'logout' || requests.logout === 1)
    && (name !== 'deletion' || requests.deletion === 1)
    && (!['revocation', 'canonical_loss'].includes(name) || requests.private401 === 1);
  const transitionExact = transitionExpected
    ? surface.transitionStarts === 1 && surface.transitionEnds === 1
    : surface.transitionStarts === 0 && surface.transitionEnds === 0;
  const authoritativeRediscovery = requests.session >= 2;
  await context.close();
  return {
    name,
    pass: coldActorKeysPurged === actorKeysPerScenario
      && surface.teardownActorKeysPurged === actorKeysPerScenario
      && surface.currentThemePreserved
      && surface.unrelatedPreserved && surface.retiredAbsent
      && endpointExact && transitionExact && authoritativeRediscovery
      && (name !== 'actor_rotation' || actorRotationRediscoveryResponses === 1)
      && (name === 'actor_rotation' ? privateMounted : publicMounted && !privateMounted),
    ...surface,
    authoritativeRediscovery,
    actorIdentifiers: actorAIdentifiers.length,
    actorKeysExpected: actorKeysPerScenario,
    actorRotationRediscoveryResponses,
    coldActorKeysPurged,
    deletionRequests: requests.deletion,
    endpointExact,
    logoutRequests: requests.logout,
    private401Requests: requests.private401,
    privateUnmounted: name === 'actor_rotation' ? false : publicMounted && !privateMounted,
  };
}

async function runLifecycleMatrix(browser) {
  const names = ['logout', 'expiry', 'revocation', 'actor_rotation', 'canonical_loss', 'deletion'];
  const rows = [];
  for (const [index, name] of names.entries()) {
    failureStage = `normative_lifecycle_matrix_${name}`;
    rows.push(await runLifecycleScenario(browser, name, index + 1));
  }
  const byName = new Map(rows.map((row) => [row.name, row]));
  return {
    actionEndpointsExact: rows.every((row) => row.endpointExact),
    actorRotation: byName.get('actor_rotation')?.pass === true,
    actorRotationRediscoveryResponses:
      byName.get('actor_rotation')?.actorRotationRediscoveryResponses ?? 0,
    authoritativeRediscovery: rows.filter((row) => row.authoritativeRediscovery).length,
    canonical401Requests: rows.reduce((total, row) => total + row.private401Requests, 0),
    canonicalLoss: byName.get('canonical_loss')?.pass === true,
    actorIdentifiersPerScenario: Math.min(...rows.map((row) => row.actorIdentifiers)),
    actorKeyFamilies: 2,
    coldActorKeysExpected: rows.reduce((total, row) => total + row.actorKeysExpected, 0),
    coldActorKeysPurged: rows.reduce((total, row) => total + row.coldActorKeysPurged, 0),
    completed: rows.filter((row) => row.pass).length,
    currentThemePreserved: rows.filter((row) => row.currentThemePreserved).length,
    deletion: byName.get('deletion')?.pass === true,
    deletionEndpointRequests: rows.reduce((total, row) => total + row.deletionRequests, 0),
    expiry: byName.get('expiry')?.pass === true,
    logout: byName.get('logout')?.pass === true,
    logoutEndpointRequests: rows.reduce((total, row) => total + row.logoutRequests, 0),
    privateUnmountedLosses: rows.filter((row) => row.privateUnmounted).length,
    productionActions: Number(byName.get('logout')?.endpointExact)
      + Number(byName.get('deletion')?.endpointExact),
    retiredAbsent: rows.filter((row) => row.retiredAbsent).length,
    revocation: byName.get('revocation')?.pass === true,
    scenarios: rows.length,
    transitionEnds: rows.reduce((total, row) => total + row.transitionEnds, 0),
    transitionStarts: rows.reduce((total, row) => total + row.transitionStarts, 0),
    teardownActorKeysExpected: rows.reduce((total, row) => total + row.actorKeysExpected, 0),
    teardownActorKeysPurged: rows.reduce(
      (total, row) => total + row.teardownActorKeysPurged, 0,
    ),
    unrelatedPreserved: rows.filter((row) => row.unrelatedPreserved).length,
  };
}

async function runInstallShellOfflineProbe(page, context) {
  const installed = await page.evaluate(async (currentCache) => {
    const response = await (await caches.open(currentCache)).match('/index.html');
    if (!response) return false;
    const body = await response.clone().text();
    return body.includes('<title>NyayOne</title>') && body.includes('id="root"');
  }, CURRENT_CACHE);
  await context.setOffline(true);
  let offlineServed;
  try {
    offlineServed = await page.evaluate(async () => {
      const frame = document.createElement('iframe');
      frame.hidden = true;
      const loaded = new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), 5_000);
        frame.addEventListener('load', () => {
          clearTimeout(timer);
          try {
            resolve(frame.contentDocument?.title === 'NyayOne'
              && frame.contentDocument?.querySelector('#root') !== null);
          } catch {
            resolve(false);
          }
        }, { once: true });
        frame.addEventListener('error', () => {
          clearTimeout(timer);
          resolve(false);
        }, { once: true });
      });
      frame.src = '/nyay18-installed-shell-offline-probe';
      document.body.append(frame);
      const result = await loaded;
      frame.remove();
      return result;
    });
  } finally {
    await context.setOffline(false);
  }
  return { installShellEntryPresent: installed, installShellOfflineServed: offlineServed };
}

async function runUnrelatedCachePoisonProbe(page, context) {
  const prepared = await page.evaluate(async ({ currentCache, unrelatedCache }) => {
    const current = await caches.open(currentCache);
    const unrelated = await caches.open(unrelatedCache);
    const unrelatedEntries = await unrelated.keys();
    const currentIndexRemoved = await current.delete('/index.html');
    return { currentIndexRemoved, unrelatedEntries: unrelatedEntries.length };
  }, {
    currentCache: CURRENT_CACHE,
    unrelatedCache: NYAY18_UNRELATED_CANARIES.cache,
  });
  await context.setOffline(true);
  const unrelatedShellPoisonServed = await page.evaluate(async (poisonMarker) => {
    const result = new Promise((resolve) => {
      const listener = (event) => {
        if (event.data !== poisonMarker) return;
        clearTimeout(timeout);
        removeEventListener('message', listener);
        resolve(true);
      };
      const timeout = setTimeout(() => {
        removeEventListener('message', listener);
        resolve(false);
      }, 1_500);
      addEventListener('message', listener);
    });
    const frame = document.createElement('iframe');
    frame.hidden = true;
    frame.src = '/nyay18-offline-shell-probe';
    document.body.append(frame);
    const served = await result;
    frame.remove();
    return served;
  }, UNRELATED_POISON_MARKER);
  await context.setOffline(false);
  const restored = await page.evaluate(async ({ currentCache, hostileAssetPath, poisonMarker, unrelatedCache }) => {
    const response = await fetch('/index.html', { cache: 'reload', credentials: 'omit' });
    const current = await caches.open(currentCache);
    await current.put('/index.html', response.clone());
    const unrelated = await caches.open(unrelatedCache);
    const assetPoison = await unrelated.match(hostileAssetPath);
    const shellPoison = await unrelated.match('/index.html');
    return {
      currentIndexRestored: response.ok && (await current.match('/index.html')) !== undefined,
      unrelatedEntries: (await unrelated.keys()).length,
      unrelatedValuesExact: Boolean(assetPoison && shellPoison)
        && (await assetPoison.text()).includes(poisonMarker)
        && (await shellPoison.text()).includes(poisonMarker),
    };
  }, {
    currentCache: CURRENT_CACHE,
    hostileAssetPath: HOSTILE_ASSET_PATH,
    poisonMarker: UNRELATED_POISON_MARKER,
    unrelatedCache: NYAY18_UNRELATED_CANARIES.cache,
  });
  return {
    currentScopedMissExercised: prepared.currentIndexRemoved,
    unrelatedPoisonEntriesPreserved: prepared.unrelatedEntries === 2
      && restored.unrelatedEntries === 2 && restored.unrelatedValuesExact,
    unrelatedShellPoisonServed,
    currentIndexRestored: restored.currentIndexRestored,
  };
}

async function inspectPrivateCacheBoundary(page) {
  return page.evaluate(async ({
    currentCache, hostileAssetPath, privateShellSeed, retiredCurrentCache, secrets,
  }) => {
    const cacheNames = await caches.keys();
    const cache = await caches.open(currentCache);
    const requests = await cache.keys();
    const inspected = [];
    for (const request of requests) {
      const response = await cache.match(request);
      inspected.push({
        url: request.url,
        body: response ? await response.clone().text() : '',
      });
    }
    const paths = inspected.map((entry) => new URL(entry.url).pathname);
    return {
      apiEntries: paths.filter((value) => value.startsWith('/api/')).length,
      currentCacheEntries: inspected.length,
      inspectedEntries: inspected.length,
      hostileAssetEntries: paths.filter((value) => value === hostileAssetPath).length,
      hostileShellEntries: inspected.filter((entry) => entry.body.includes(privateShellSeed)).length,
      privateEntries: paths.filter((value) => /^\/s-(?:0?7|1\d|2[234]|3[0-5]|[56]\d|8[2-7]|9[0-3])(?:\/|$)/u.test(value)).length,
      publicEntriesExact: paths.every((value) => (
        value === '/index.html' || value.startsWith('/assets/')
      )),
      responseBodiesClean: inspected.every((entry) => (
        secrets.every((secret) => !entry.body.includes(secret))
      )),
      retiredCurrentAbsent: !cacheNames.includes(retiredCurrentCache),
    };
  }, {
    currentCache: CURRENT_CACHE,
    hostileAssetPath: HOSTILE_ASSET_PATH,
    privateShellSeed: PRIVATE_SHELL_SEED,
    retiredCurrentCache: NYAY18_RETIRED_CURRENT_CACHE,
    secrets: [LOCAL_PRIVATE_SEED, SESSION_PRIVATE_SEED, PRIVATE_SINK_SEED, PRIVATE_SHELL_SEED],
  });
}

async function inspectDeleteOnlyPrivacySinks(page, context, trace, instrumentationCanaries) {
  const browser = await page.evaluate(async (fixture) => {
    const contains = (value) => fixture.secrets
      .some((secret) => String(value ?? '').includes(secret));
    const localNames = Array.from(
      { length: localStorage.length }, (_, index) => localStorage.key(index),
    ).filter((key) => key !== null);
    const sessionNames = Array.from(
      { length: sessionStorage.length }, (_, index) => sessionStorage.key(index),
    ).filter((key) => key !== null);
    const isRetiredLocal = (key) => fixture.localExact.includes(key)
      || fixture.localPrefixes.some((prefix) => key.startsWith(prefix));
    const localValues = localNames.filter((key) => !isRetiredLocal(key))
      .map((key) => localStorage.getItem(key));
    const sessionValues = sessionNames.filter((key) => !fixture.sessionExact.includes(key))
      .map((key) => sessionStorage.getItem(key));
    const cacheValues = [];
    for (const cacheName of await caches.keys()) {
      const cache = await caches.open(cacheName);
      for (const request of await cache.keys()) {
        const response = await cache.match(request);
        cacheValues.push(cacheName, request.url, response ? await response.clone().text() : '');
      }
    }
    const indexedDbNames = typeof indexedDB.databases === 'function'
      ? (await indexedDB.databases()).map((entry) => entry.name ?? '') : [];
    const indexedDbProbe = globalThis.__nyay18IndexedDbProbe ?? {};
    return {
      cacheFindings: cacheValues.filter(contains).length,
      continuousCacheWrites: indexedDbProbe.secretWrites?.cache ?? -1,
      continuousCookieWrites: indexedDbProbe.secretWrites?.cookie ?? -1,
      continuousDomWrites: indexedDbProbe.secretWrites?.dom ?? -1,
      continuousHistoryWrites: indexedDbProbe.secretWrites?.history ?? -1,
      continuousStorageWrites: indexedDbProbe.secretWrites?.storage ?? -1,
      cookieFindings: contains(document.cookie) ? 1 : 0,
      domFindings: contains(document.documentElement.outerHTML) ? 1 : 0,
      historyFindings: contains(JSON.stringify(history.state)) ? 1 : 0,
      indexedDbFindings: indexedDbNames.filter(contains).length,
      indexedDbCanaryWrites: indexedDbProbe.indexedDbCanaryWrites ?? -1,
      indexedDbDeleteCalls: indexedDbProbe.databaseDeleteCalls ?? -1,
      indexedDbOpenCalls: indexedDbProbe.databaseOpenCalls ?? -1,
      indexedDbWriteCalls: (indexedDbProbe.objectStoreCreateCalls ?? -1)
        + (indexedDbProbe.writeCalls ?? -1),
      newIndexedDbNames: indexedDbNames.length,
      storageFindings: [...localValues, ...sessionValues].filter(contains).length,
      urlFindings: contains(location.href) ? 1 : 0,
    };
  }, {
    secrets: [LOCAL_PRIVATE_SEED, SESSION_PRIVATE_SEED, PRIVATE_SINK_SEED, PRIVATE_SHELL_SEED],
    localExact: NYAY18_LEGACY_LOCAL_EXACT_KEYS,
    localPrefixes: NYAY18_LEGACY_LOCAL_PREFIXES,
    sessionExact: NYAY18_LEGACY_SESSION_EXACT_KEYS,
  });
  const cookies = await context.cookies(WEB);
  const containsSecret = (value) => [
    LOCAL_PRIVATE_SEED, SESSION_PRIVATE_SEED, PRIVATE_SINK_SEED, PRIVATE_SHELL_SEED,
  ]
    .some((secret) => String(value ?? '').includes(secret));
  const migration = instrumentationCanaries.migration;
  const final = instrumentationCanaries.final;
  const sumAcrossDocuments = (key) => migration[key] + browser[key];
  const detectedInBothDocuments = (key) => migration[key] === true && final[key] === true;
  return {
    ...browser,
    continuousCacheWrites: sumAcrossDocuments('continuousCacheWrites'),
    continuousCookieWrites: sumAcrossDocuments('continuousCookieWrites'),
    continuousDomWrites: sumAcrossDocuments('continuousDomWrites'),
    continuousHistoryWrites: sumAcrossDocuments('continuousHistoryWrites'),
    continuousStorageWrites: sumAcrossDocuments('continuousStorageWrites'),
    consoleFindings: trace.console.filter(containsSecret).length,
    cookieFindings: browser.cookieFindings
      + cookies.filter((cookie) => containsSecret(cookie.name) || containsSecret(cookie.value)).length,
    indexedDbCanaryWrites: sumAcrossDocuments('indexedDbCanaryWrites'),
    indexedDbDeleteCalls: sumAcrossDocuments('indexedDbDeleteCalls'),
    indexedDbOpenCalls: sumAcrossDocuments('indexedDbOpenCalls'),
    indexedDbWriteCalls: sumAcrossDocuments('indexedDbWriteCalls'),
    instrumentationCacheCanaryDetected:
      detectedInBothDocuments('instrumentationCacheCanaryDetected'),
    instrumentationCookieCanaryDetected:
      detectedInBothDocuments('instrumentationCookieCanaryDetected'),
    instrumentationDocumentCount:
      Number(migration.probeAvailable === true) + Number(final.probeAvailable === true),
    instrumentationDomCanaryDetected:
      detectedInBothDocuments('instrumentationDomCanaryDetected'),
    instrumentationHistoryCanaryDetected:
      detectedInBothDocuments('instrumentationHistoryCanaryDetected'),
    instrumentationStorageCanaryDetected:
      detectedInBothDocuments('instrumentationStorageCanaryDetected'),
    networkFindings: trace.network.filter(containsSecret).length,
  };
}

async function runInheritedNyay5ContractIntegrity() {
  const mutants = seededNyay5MutantResults();
  const assertionInventoryExact = NYAY5_ASSERTION_INVENTORY.length === 22
    && new Set(NYAY5_ASSERTION_INVENTORY).size === NYAY5_ASSERTION_INVENTORY.length;
  const mutantInventoryExact = NYAY5_SEEDED_MUTANT_INVENTORY.length === 46
    && new Set(NYAY5_SEEDED_MUTANT_INVENTORY).size === NYAY5_SEEDED_MUTANT_INVENTORY.length
    && mutants.exact;
  const failed = Number(!assertionInventoryExact)
    + Number(!mutantInventoryExact) + Number(!mutants.allKilled);
  return {
    assertionInventoryExact,
    assertions: NYAY5_ASSERTION_INVENTORY.length,
    contractMutantsAllKilled: mutants.allKilled,
    failed,
    mutantInventoryExact,
    mutants: NYAY5_SEEDED_MUTANT_INVENTORY.length,
    mutantsKilled: mutants.killed,
  };
}

async function executeBrowserGate() {
  const initialGit = gitState();
  const previewSourceActual = nyay18Sha256(await readFile(
    path.resolve(REPOSITORY, 'frontend/scripts/nyay18-preview-server.mjs'),
  ));
  const environmentInitial = {
    commitMatchesHead: initialGit.head === EXACT_COMMIT,
    commitRequired: true,
    outputAbsolute: path.isAbsolute(OUTPUT),
    outputOutsideRepository: OUTPUT_OUTSIDE_REPOSITORY,
    parentMatchesHead: initialGit.parent === EXACT_PARENT,
    parentRequired: true,
    previewSourceMatches: previewSourceActual === PREVIEW_SOURCE_SHA256,
    treeMatchesHead: initialGit.tree === EXACT_TREE,
    treeRequired: true,
    webOriginLoopback: true,
    webRequired: true,
    worktreeClean: initialGit.clean,
  };
  if (!Object.values(environmentInitial).every(Boolean)) {
    record('required_environment_exact', false, environmentInitial);
    throw new Error('NYAY18_EXACT_CLEAN_HEAD_REQUIRED');
  }

  failureStage = 'runtime_chromium';
  const browser = await chromium.launch({ headless: true });
  record('runtime_chromium', true, {
    engine: 'chromium', headless: true, launches: 1,
    versionSha256: nyay18Sha256(browser.version()),
  });

  try {
    failureStage = 'leading_unrelated_matrix';
    const leading = await runLeadingUnrelatedMatrix(browser);
    record('leading_unrelated_keys_preserved',
      leading.candidateCount === NYAY18_LEADING_CANDIDATE_KEYS
        && leading.preservedCount === NYAY18_LEADING_CANDIDATE_KEYS
        && leading.targetCandidates === NYAY18_LEADING_TARGET_KEYS
        && leading.targetIndexBeforeBootstrap >= NYAY18_LEADING_UNRELATED_KEYS
        && leading.unrelatedBeforeTarget >= NYAY18_LEADING_UNRELATED_KEYS
        && leading.targetSurvivorsBeforeBootstrap === 1
        && leading.leadingBeforeOwned && leading.targetRemoved && leading.valuesExact
        && leading.beforeSha256 === leading.afterSha256,
      leading);

    const context = await createFreshContext(browser);
    await installPrivacySinkInstrumentation(context);
    const page = await context.newPage();
    const trace = { console: [], network: [] };
    page.on('console', (message) => { trace.console.push(message.text()); });
    page.on('request', (request) => {
      trace.network.push(`${request.method()} ${request.url()} ${request.postData() ?? ''}`);
    });
    const anonymous = { requestCount: 0, getRequests: 0, otherRequests: 0, canonicalBodies: 0 };
    await routeCanonicalSession(page, { actor: null }, anonymous);
    let privateApiProbeRequests = 0;
    await page.route('**/api/v1/student/nyay18-cache-probe', async (route) => {
      privateApiProbeRequests += 1;
      await route.fulfill({
        status: 200, contentType: 'application/json',
        headers: { 'Cache-Control': 'no-store' }, body: JSON.stringify({ ok: true }),
      });
    });

    failureStage = 'initial_production_load';
    await page.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    const initialWorker = await waitForServiceWorker(page);
    const unregistration = await unregisterServiceWorkers(page);

    failureStage = 'legacy_seed';
    const seeded = await seedLegacySurfaces(page);
    const localSeedInventoryExact = legacyLocalSeedKeys.length
      === NYAY18_LEGACY_LOCAL_EXACT_KEYS.length
        + NYAY18_LEGACY_LOCAL_PREFIXES.length * NYAY18_PREFIX_SEEDS_PER_FAMILY;
    const cacheSeedInventoryExact = legacyCacheSeedKeys.length
      === 1 + NYAY18_LEGACY_CACHE_PREFIXES.length * NYAY18_CACHE_SEEDS_PER_FAMILY;
    record('legacy_local_seed_complete',
      seeded.localSeeded === legacyLocalSeedKeys.length
        && seeded.localUnrelated
        && localSeedInventoryExact
        && new Set(legacyLocalSeedKeys).size === legacyLocalSeedKeys.length,
      {
        exactFamilies: NYAY18_LEGACY_LOCAL_EXACT_KEYS.length,
        inventorySha256: digestLines(legacyLocalSeedKeys),
        prefixFamilies: NYAY18_LEGACY_LOCAL_PREFIXES.length,
        seededCount: seeded.localSeeded,
        themeSeeded: legacyLocalSeedKeys.includes('ls-theme'),
        unique: new Set(legacyLocalSeedKeys).size === legacyLocalSeedKeys.length,
      });
    record('legacy_session_seed_complete',
      seeded.sessionSeeded === NYAY18_LEGACY_SESSION_EXACT_KEYS.length
        && seeded.sessionUnrelated,
      {
        exactFamilies: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
        inventorySha256: digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS),
        seededCount: seeded.sessionSeeded,
        unique: new Set(NYAY18_LEGACY_SESSION_EXACT_KEYS).size
          === NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
      });
    record('legacy_cache_seed_complete',
      seeded.cacheSeeded === legacyCacheSeedKeys.length
        && seeded.cacheUnrelated
        && seeded.retiredCurrentSeeded
        && cacheSeedInventoryExact
        && new Set(legacyCacheSeedKeys).size === legacyCacheSeedKeys.length,
      {
        inventorySha256: digestLines(legacyCacheSeedKeys),
        prefixFamilies: NYAY18_LEGACY_CACHE_PREFIXES.length,
        retiredCurrentSeeded: seeded.retiredCurrentSeeded,
        seededCount: seeded.cacheSeeded,
        unique: new Set(legacyCacheSeedKeys).size === legacyCacheSeedKeys.length,
      });
    failureStage = 'migration_reload';
    const hostileShellArmed = await page.evaluate(async () => {
      const response = await fetch('/__nyay18-gate/arm-shell', {
        cache: 'no-store', credentials: 'omit', method: 'GET',
      });
      return response.status === 204;
    });
    if (!hostileShellArmed) throw new Error('NYAY18_HOSTILE_SHELL_ARM_FAILED');
    await context.addCookies([{
      name: HOSTILE_SHELL_COOKIE,
      value: 'opaque-private-shell-cookie-canary',
      url: WEB,
    }]);
    await installStorageInstrumentation(context);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    const reinstalledWorker = await waitForServiceWorker(page);
    await waitForLegacyRetirement(page);
    const firstTelemetry = await storageTelemetry(page);
    if (!firstTelemetry) throw new Error('NYAY18_STORAGE_INSTRUMENTATION_MISSING');
    const migrationPrivacyInstrumentation = await runPrivacySinkInstrumentationCanaries(page);
    const hostileShellServer = await page.evaluate(async () => {
      const response = await fetch('/__nyay18-gate/metrics', {
        cache: 'no-store', credentials: 'omit', method: 'GET',
      });
      if (!response.ok) throw new Error('NYAY18_HOSTILE_SHELL_METRICS_FAILED');
      return response.json();
    });
    await context.clearCookies({ name: HOSTILE_SHELL_COOKIE });

    failureStage = 'one_shot_reload';
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    await waitForLegacyRetirement(page);
    const secondTelemetry = await storageTelemetry(page);
    if (!secondTelemetry) throw new Error('NYAY18_STORAGE_INSTRUMENTATION_MISSING');
    const activeWorker = await waitForServiceWorker(page);
    const finalPrivacyInstrumentation = await runPrivacySinkInstrumentationCanaries(page);
    const brandSeparatorCanariesDetected = await runLegacyBrandSeparatorCanary(page, context);
    const surface = await runtimeSurfaceSnapshot(page, context);

    const localLegacyReads = firstTelemetry.localLegacyReads + secondTelemetry.localLegacyReads;
    const themeReads = firstTelemetry.themeReads + secondTelemetry.themeReads;
    const nonThemeLegacyReads = firstTelemetry.nonThemeLegacyReads
      + secondTelemetry.nonThemeLegacyReads;
    const sessionLegacyReads = firstTelemetry.sessionLegacyReads
      + secondTelemetry.sessionLegacyReads;
    const localClearCalls = firstTelemetry.localClearCalls + secondTelemetry.localClearCalls;
    const sessionClearCalls = firstTelemetry.sessionClearCalls + secondTelemetry.sessionClearCalls;
    record('storage_clear_never_called', localClearCalls === 0 && sessionClearCalls === 0, {
      localCalls: localClearCalls, sessionCalls: sessionClearCalls,
    });
    record('legacy_value_reads_theme_only',
      localLegacyReads === 1 && themeReads === 1
        && nonThemeLegacyReads === 0 && sessionLegacyReads === 0,
      { localLegacyReads, nonThemeLegacyReads, sessionLegacyReads, themeReads });
    record('legacy_local_purge_complete', surface.legacyLocalNames === 0, {
      inventorySha256: digestLines(legacyLocalSeedKeys),
      remaining: surface.legacyLocalNames,
      seededCount: legacyLocalSeedKeys.length,
    });
    record('legacy_session_purge_complete', surface.legacySessionNames === 0, {
      inventorySha256: digestLines(NYAY18_LEGACY_SESSION_EXACT_KEYS),
      remaining: surface.legacySessionNames,
      seededCount: NYAY18_LEGACY_SESSION_EXACT_KEYS.length,
    });
    record('legacy_cache_purge_complete', surface.retiredCacheNames === 0, {
      inventorySha256: digestLines(legacyCacheSeedKeys),
      remaining: surface.retiredCacheNames,
      seededCount: legacyCacheSeedKeys.length,
    });
    record('theme_one_shot_migrated',
      surface.migratedDark && surface.newThemePresent && surface.oldThemeAbsent
        && firstTelemetry.themeReads === 1 && secondTelemetry.themeReads === 0,
      {
        migratedDark: surface.migratedDark,
        newThemePresent: surface.newThemePresent,
        oldThemeAbsent: surface.oldThemeAbsent,
        oneShotRead: firstTelemetry.themeReads === 1 && secondTelemetry.themeReads === 0,
      });
    record('unrelated_surfaces_preserved',
      surface.unrelatedLocalPreserved && surface.unrelatedSessionPreserved
        && surface.unrelatedCachePreserved && surface.unrelatedValuesExact,
      {
        cachePreserved: surface.unrelatedCachePreserved,
        localPreserved: surface.unrelatedLocalPreserved,
        sessionPreserved: surface.unrelatedSessionPreserved,
        surfaceCount: 3,
        valuesExact: surface.unrelatedValuesExact,
      });
    record('active_namespaces_nyayone_only',
      surface.legacyCacheNames === 0 && surface.legacyCookieNames === 0
        && surface.legacyGlobalNames === 0 && surface.legacyLocalNames === 0
        && surface.legacySessionNames === 0 && surface.unexpectedOwnedNames === 0
        && surface.nyayOneOwnedNames >= 2,
      {
        legacyCacheNames: surface.legacyCacheNames,
        legacyCookieNames: surface.legacyCookieNames,
        legacyGlobalNames: surface.legacyGlobalNames,
        legacyLocalNames: surface.legacyLocalNames,
        legacySessionNames: surface.legacySessionNames,
        nyayOneOwnedNames: surface.nyayOneOwnedNames,
        unexpectedOwnedNames: surface.unexpectedOwnedNames,
      });
    const workerMetrics = {
      active: activeWorker.active,
      controller: activeWorker.controller,
      initialRegistrations: unregistration.initialRegistrations,
      registrations: activeWorker.registrations,
      reinstalled: unregistration.unregistered >= 1
        && reinstalledWorker.registrations === 1,
      scriptPathExact: activeWorker.scriptPathExact,
      supported: initialWorker.supported && activeWorker.supported,
      unregistered: unregistration.unregistered,
    };
    record('service_worker_reinstalled_active', Object.values({
      active: workerMetrics.active,
      controller: workerMetrics.controller,
      reinstalled: workerMetrics.reinstalled,
      scriptPathExact: workerMetrics.scriptPathExact,
      supported: workerMetrics.supported,
    }).every(Boolean)
      && workerMetrics.initialRegistrations >= 1
      && workerMetrics.registrations === 1
      && workerMetrics.unregistered >= 1
      && surface.currentCachePresent, workerMetrics);
    record('runtime_identity_clean',
      brandSeparatorCanariesDetected === 6
        && surface.titleExact && surface.bodyNyayOneVisible
        && surface.legacyTitleMatches === 0 && surface.legacyBodyMatches === 0
        && surface.legacyAriaMatches === 0 && surface.legacyDownloadMatches === 0
        && surface.legacyGlobalMatches === 0 && surface.legacyCookieMatches === 0,
      {
        bodyNyayOneVisible: surface.bodyNyayOneVisible,
        brandSeparatorCanariesDetected,
        legacyAriaMatches: surface.legacyAriaMatches,
        legacyBodyMatches: surface.legacyBodyMatches,
        legacyCookieMatches: surface.legacyCookieMatches,
        legacyDownloadMatches: surface.legacyDownloadMatches,
        legacyGlobalMatches: surface.legacyGlobalMatches,
        legacyTitleMatches: surface.legacyTitleMatches,
        titleExact: surface.titleExact,
      });

    failureStage = 'normative_theme_matrix';
    const themeMatrix = await runThemeMatrix(browser);
    record('theme_current_precedence',
      themeMatrix.current.currentLightPreserved
        && themeMatrix.current.currentWon
        && themeMatrix.current.legacyDarkSeeded
        && themeMatrix.current.legacyThemeReads === 0
        && themeMatrix.current.oldThemeAbsent,
      themeMatrix.current);
    record('invalid_theme_retired',
      Object.values(themeMatrix.invalid).every((value) => value === true),
      themeMatrix.invalid);

    failureStage = 'server_pending_flow_matrix';
    const serverPending = await runServerPendingFlowMatrix(browser);
    if (serverPending.flows !== 2
      || serverPending.startResponses !== 2
      || serverPending.stateResponses !== 2
      || serverPending.serverStateRequests < 2
      || serverPending.sessionRequests < 2
      || serverPending.controls !== 2
      || serverPending.screens !== 2
      || serverPending.flowCookies !== 2
      || serverPending.sessionCookies !== 0
      || serverPending.verifyControls !== 2
      || !serverPending.purposesExact) {
      throw new Error('NYAY18_SERVER_PENDING_FLOW_MATRIX_FAILED');
    }

    failureStage = 'anonymous_challenge_denial_matrix';
    const anonymousDenied = await runAnonymousChallengeDenialMatrix(browser);
    if (!anonymousDenied.cookieInventoryUnchanged
      || !anonymousDenied.flowAuthorityAbsent
      || !anonymousDenied.flowUnavailableProven
      || !anonymousDenied.otpControlsAbsent
      || !anonymousDenied.retiredInlineErrorAbsent
      || anonymousDenied.routesDenied !== 2) {
      throw new Error('NYAY18_ANONYMOUS_CHALLENGE_DENIAL_FAILED');
    }

    failureStage = 'normative_fail_closed_matrix';
    const failClosed = await runFailClosedMatrix(browser);
    const cleanupRows = [
      ['inaccessible_storage_fail_closed', 'inaccessible'],
      ['failed_removal_fail_closed', 'throw'],
      ['no_progress_fail_closed', 'no_progress'],
    ];
    for (const [rowId, mode] of cleanupRows) {
      const outcome = failClosed[mode];
      const metrics = {
        actionAttempts: outcome.actionAttempts,
        actionRejected: outcome.actionRejected,
        cookieInventoryUnchanged: outcome.cookieInventoryUnchanged,
        cookieOperations: outcome.cookieOperations,
        flowAuthorityPreserved: outcome.flowAuthorityPreserved,
        mode,
        pendingAuthorityProven: outcome.pendingAuthorityProven,
        pendingControlsProven: outcome.pendingControlsProven,
        privateMounted: outcome.privateMounted,
        safeEntryVisible: outcome.safeEntryVisible,
        unavailableVisible: outcome.unavailableVisible,
      };
      record(rowId,
        metrics.actionAttempts === 1 && metrics.actionRejected
          && metrics.cookieInventoryUnchanged
          && metrics.flowAuthorityPreserved
          && metrics.pendingAuthorityProven
          && metrics.pendingControlsProven
          && metrics.safeEntryVisible
          && metrics.cookieOperations === 0
          && !metrics.privateMounted && metrics.unavailableVisible,
        metrics);
    }
    const unsupportedMetrics = {
      actionAttempts: failClosed.unsupported_locks.actionAttempts,
      actionRejected: failClosed.unsupported_locks.actionRejected,
      cookieOperations: failClosed.unsupported_locks.cookieOperations,
      locksUnavailable: true,
      privateMounted: failClosed.unsupported_locks.privateMounted,
      sessionRequests: failClosed.unsupported_locks.sessionRequests,
      unavailableVisible: failClosed.unsupported_locks.unavailableVisible,
    };
    record('unsupported_locks_fail_closed',
      unsupportedMetrics.cookieOperations === 0
        && unsupportedMetrics.actionAttempts === 1
        && unsupportedMetrics.actionRejected
        && unsupportedMetrics.sessionRequests === 0
        && !unsupportedMetrics.privateMounted
        && unsupportedMetrics.unavailableVisible,
      unsupportedMetrics);

    failureStage = 'normative_lifecycle_matrix';
    const lifecycle = await runLifecycleMatrix(browser);
    record('lifecycle_boundaries_complete',
      lifecycle.scenarios === 6 && lifecycle.completed === 6
        && lifecycle.actorIdentifiersPerScenario === 2
        && lifecycle.actorKeyFamilies === 2
        && lifecycle.coldActorKeysExpected === 24
        && lifecycle.coldActorKeysPurged === 24
        && lifecycle.teardownActorKeysExpected === 24
        && lifecycle.teardownActorKeysPurged === 24
        && lifecycle.currentThemePreserved === 6
        && lifecycle.unrelatedPreserved === 6
        && lifecycle.retiredAbsent === 6
        && lifecycle.privateUnmountedLosses === 5
        && lifecycle.actionEndpointsExact
        && lifecycle.actorRotationRediscoveryResponses === 1
        && lifecycle.authoritativeRediscovery === 6
        && lifecycle.productionActions === 2
        && lifecycle.logoutEndpointRequests === 1
        && lifecycle.deletionEndpointRequests === 1
        && lifecycle.canonical401Requests === 2
        && lifecycle.transitionStarts === 5 && lifecycle.transitionEnds === 5,
      lifecycle);

    failureStage = 'private_cache_exclusion';
    let privateRouteProbeRequests = 0;
    const observePrivateRouteProbe = (request) => {
      if (new URL(request.url()).pathname === '/s-60') privateRouteProbeRequests += 1;
    };
    page.on('request', observePrivateRouteProbe);
    await page.goto(`${WEB}/s-60`, { waitUntil: 'domcontentloaded' });
    await page.locator(S03_SELECTOR).waitFor({ state: 'visible' });
    page.off('request', observePrivateRouteProbe);
    await page.evaluate(async () => {
      await fetch('/api/v1/student/nyay18-cache-probe', {
        method: 'GET', headers: { 'Cache-Control': 'no-store' },
      });
    });
    const installedShell = await runInstallShellOfflineProbe(page, context);
    const unrelatedPoison = await runUnrelatedCachePoisonProbe(page, context);
    await context.addCookies([{
      name: HOSTILE_ASSET_COOKIE,
      value: 'opaque-private-cookie-canary',
      url: WEB,
    }]);
    const hostileAssetExecuted = await page.evaluate(async (assetPath) => {
      globalThis.__nyay18HostileAssetExecuted = false;
      globalThis.__nyay18UnrelatedAssetPoison = false;
      const script = document.createElement('script');
      script.src = assetPath;
      const loaded = new Promise((resolve, reject) => {
        script.addEventListener('load', () => resolve(true), { once: true });
        script.addEventListener('error', () => reject(new Error('NYAY18_HOSTILE_ASSET_FAILED')), {
          once: true,
        });
      });
      document.head.append(script);
      await loaded;
      script.remove();
      return {
        hostile: globalThis.__nyay18HostileAssetExecuted === true,
        unrelatedPoison: globalThis.__nyay18UnrelatedAssetPoison === true,
      };
    }, HOSTILE_ASSET_PATH);
    const hostileAssetServer = await page.evaluate(async () => {
      const response = await fetch('/__nyay18-gate/metrics', {
        cache: 'no-store', credentials: 'omit', method: 'GET',
      });
      if (!response.ok) throw new Error('NYAY18_HOSTILE_ASSET_METRICS_FAILED');
      return response.json();
    });
    await context.clearCookies({ name: HOSTILE_ASSET_COOKIE });
    const privateCache = {
      ...(await inspectPrivateCacheBoundary(page)),
      apiProbeRequests: privateApiProbeRequests,
      hostileAssetCookieHeaders: hostileAssetServer.hostileAssetCookieHeaders,
      hostileAssetExecuted: hostileAssetExecuted.hostile,
      hostileAssetServerRequests: hostileAssetServer.hostileAssetServerRequests,
      hostileShellCookieHeaders: hostileShellServer.hostileShellCookieHeaders,
      hostileShellServerRequests: hostileShellServer.hostileShellServerRequests,
      installShellEntryPresent: installedShell.installShellEntryPresent,
      installShellOfflineServed: installedShell.installShellOfflineServed,
      privateRouteProbeRequests,
      currentIndexRestored: unrelatedPoison.currentIndexRestored,
      currentScopedMissExercised: unrelatedPoison.currentScopedMissExercised,
      unrelatedAssetPoisonServed: hostileAssetExecuted.unrelatedPoison,
      unrelatedPoisonEntriesPreserved: unrelatedPoison.unrelatedPoisonEntriesPreserved,
      unrelatedShellPoisonServed: unrelatedPoison.unrelatedShellPoisonServed,
    };
    record('private_api_cache_excluded',
      privateApiProbeRequests === 1
        && privateRouteProbeRequests === 1
        && hostileAssetServer.hostileAssetServerRequests === 1
        && hostileAssetServer.hostileAssetCookieHeaders === 0
        && hostileShellServer.hostileShellServerRequests === 1
        && hostileShellServer.hostileShellCookieHeaders === 0
        && installedShell.installShellEntryPresent
        && installedShell.installShellOfflineServed
        && hostileAssetExecuted.hostile
        && privateCache.hostileAssetEntries === 0
        && privateCache.hostileShellEntries === 0
        && unrelatedPoison.currentScopedMissExercised
        && unrelatedPoison.currentIndexRestored
        && unrelatedPoison.unrelatedPoisonEntriesPreserved
        && !unrelatedPoison.unrelatedShellPoisonServed
        && !hostileAssetExecuted.unrelatedPoison
        && privateCache.apiEntries === 0 && privateCache.privateEntries === 0
        && privateCache.currentCacheEntries >= 1
        && privateCache.publicEntriesExact && privateCache.responseBodiesClean
        && privateCache.retiredCurrentAbsent,
      privateCache);

    failureStage = 'delete_only_privacy_sinks';
    const privacy = await inspectDeleteOnlyPrivacySinks(
      page, context, trace, {
        final: finalPrivacyInstrumentation,
        migration: migrationPrivacyInstrumentation,
      },
    );
    record('delete_only_privacy_sinks_clean',
      Object.entries(privacy).every(([key, value]) => (
        key === 'instrumentationDocumentCount'
          ? value === 2
          : key.startsWith('instrumentation') ? value === true : value === 0
      )), privacy);

    // The production entry point is wrapped in React.StrictMode. Runtime
    // evidence additionally proves that two full reloads settled authority and
    // rendered exactly one root without leaking a pending private mount.
    const strictModeRuntime = await page.evaluate(() => ({
      root: document.querySelectorAll('#root').length === 1,
      pending: document.querySelectorAll('[data-testid="student-session-pending"]').length,
    }));
    record('fresh_profiles_reload_strictmode',
      freshProfileContexts >= 10 && strictModeRuntime.root
        && strictModeRuntime.pending === 0,
      {
        contexts: freshProfileContexts,
        freshProfiles: freshProfileContexts,
        reloads: 2,
        strictModeRoot: strictModeRuntime.root,
        strictModeSessionSettled: strictModeRuntime.pending === 0,
      });

    failureStage = 'inherited_nyay5_contract_integrity';
    const inheritedNyay5 = await runInheritedNyay5ContractIntegrity();
    record('inherited_nyay5_contract_integrity', inheritedNyay5.failed === 0, inheritedNyay5);

    failureStage = 's03_visuals';
    await mkdir(SCREENSHOT_DIR, { recursive: true, mode: 0o700 });
    for (const viewport of VIEWPORTS) {
      const expected = NYAY18_SCREENSHOT_INVENTORY.find((entry) => (
        entry.width === viewport.width && entry.height === viewport.height
      ));
      if (!expected) throw new Error('NYAY18_SCREENSHOT_INVENTORY_MISSING');
      const filename = path.resolve(SCREENSHOT_DIR, expected.name);
      const metrics = await observeS03Viewport(page, viewport, filename);
      record(`s03_${viewport.name}_observed`,
        metrics.routeExact && metrics.screenSelectorCount === 1 && metrics.visible
          && metrics.noHorizontalOverflow && metrics.legacyVisibleMatches === 0,
         metrics);
      const fileStat = await stat(filename);
      const observedPng = PNG.sync.read(await readFile(filename));
      screenshots.push({
        name: expected.name,
        width: observedPng.width,
        height: observedPng.height,
        bytes: fileStat.size,
        sha256: await sha256File(filename),
      });
    }
    record('screenshots_exact', screenshots.length === 2
      && screenshots.every((entry) => /^[0-9a-f]{64}$/u.test(entry.sha256) && entry.bytes > 0), {
      checksumsExact: screenshots.every((entry) => /^[0-9a-f]{64}$/u.test(entry.sha256)),
      count: screenshots.length,
      dimensionsExact: screenshots.every((entry, index) => (
        entry.width === NYAY18_SCREENSHOT_INVENTORY[index].width
        && entry.height === NYAY18_SCREENSHOT_INVENTORY[index].height
      )),
      inventorySha256: nyay18EvidenceInventory().screenshots.sha256,
    });
    record('anonymous_session_canonical',
      anonymous.requestCount >= 1 && anonymous.getRequests === anonymous.requestCount
        && anonymous.canonicalBodies === anonymous.requestCount && anonymous.otherRequests === 0
        && serverPending.flows === 2
        && serverPending.startResponses === 2
        && serverPending.stateResponses === 2
        && serverPending.serverStateRequests >= 2
        && serverPending.sessionRequests >= 2
        && serverPending.controls === 2
        && serverPending.screens === 2
        && serverPending.flowCookies === 2
        && serverPending.sessionCookies === 0
        && serverPending.verifyControls === 2
        && serverPending.purposesExact
        && anonymousDenied.cookieInventoryUnchanged
        && anonymousDenied.flowAuthorityAbsent
        && anonymousDenied.flowUnavailableProven
        && anonymousDenied.otpControlsAbsent
        && anonymousDenied.retiredInlineErrorAbsent
        && anonymousDenied.routesDenied === 2,
      {
        ...anonymous,
        ...serverPending,
        denialCookieInventoryUnchanged: anonymousDenied.cookieInventoryUnchanged,
        denialFlowAuthorityAbsent: anonymousDenied.flowAuthorityAbsent,
        denialFlowUnavailableProven: anonymousDenied.flowUnavailableProven,
        denialOtpControlsAbsent: anonymousDenied.otpControlsAbsent,
        denialRetiredInlineErrorAbsent: anonymousDenied.retiredInlineErrorAbsent,
        denialRoutesDenied: anonymousDenied.routesDenied,
      });

    const finalGit = gitState();
    const environmentFinal = {
      ...environmentInitial,
      commitMatchesHead: environmentInitial.commitMatchesHead
        && finalGit.head === EXACT_COMMIT,
      parentMatchesHead: environmentInitial.parentMatchesHead
        && finalGit.parent === EXACT_PARENT,
      treeMatchesHead: environmentInitial.treeMatchesHead
        && finalGit.tree === EXACT_TREE,
      worktreeClean: environmentInitial.worktreeClean && finalGit.clean,
    };
    record('required_environment_exact', Object.values(environmentFinal).every(Boolean), environmentFinal);
    await context.close();
  } finally {
    await browser.close();
  }
}

async function main() {
  try {
    await executeBrowserGate();
  } catch (error) {
    failureClass = error instanceof Error ? error.constructor.name : 'NonError';
    failureCode = error instanceof Error && /^NYAY18_[A-Z0-9_]+$/u.test(error.message)
      ? error.message : 'NYAY18_RUNTIME_ASSERTION_FAILED';
  }

  const selfTest = runNyay18ContractSelfTest();
  record('planted_mutants_killed', selfTest.allKilled, {
    allKilled: selfTest.allKilled, killed: selfTest.killed, named: selfTest.named,
  });
  const serializedObservations = JSON.stringify([...observations.values()]);
  const rawPrivateValuesIncluded = [LOCAL_PRIVATE_SEED, SESSION_PRIVATE_SEED]
    .some((value) => serializedObservations.includes(value));
  record('evidence_sanitized', !rawPrivateValuesIncluded, {
    privacyFindings: Number(rawPrivateValuesIncluded),
    rawPrivateValuesIncluded,
  });

  const rows = NYAY18_ASSERTION_INVENTORY.map((id) => observations.get(id));
  const passed = rows.filter((row) => row.executed && row.pass).length;
  const failed = rows.length - passed;
  const report = {
    schemaVersion: 1,
    gate: 'nyay18_browser_namespace',
    target: 'production-build-real-chromium',
    exactCommit: EXACT_COMMIT,
    exactTree: EXACT_TREE,
    exactParent: EXACT_PARENT,
    previewServerSourceSha256: PREVIEW_SOURCE_SHA256,
    executed: observations.get('runtime_chromium').executed,
    status: failed === 0 && failureCode === null ? 'PASS' : 'FAIL',
    total: rows.length,
    passed,
    failed,
    inventory: nyay18EvidenceInventory(),
    rows,
    screenshots,
    failure: failureCode === null ? null : {
      stage: failureStage,
      code: failureCode,
      class: failureClass,
    },
  };
  const inspection = inspectNyay18Evidence(report);
  if (!inspection.pass) {
    report.status = 'FAIL';
    if (report.failed === 0) {
      report.failed = 1;
      report.passed = Math.max(0, report.total - 1);
    }
  }
  await mkdir(path.dirname(OUTPUT), { recursive: true, mode: 0o700 });
  await writeFile(OUTPUT, `${JSON.stringify(report, null, 2)}\n`, {
    encoding: 'utf8', mode: 0o600,
  });
  process.stdout.write(`${JSON.stringify({
    gate: report.gate,
    status: report.status,
    total: report.total,
    passed: report.passed,
    failed: report.failed,
  })}\n`);
  if (report.status !== 'PASS') process.exitCode = 1;
}

await main();
