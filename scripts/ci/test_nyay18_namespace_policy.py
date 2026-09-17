#!/usr/bin/env python3
"""Seeded negative tests for the NYAY-18 shipped namespace policy."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_policy():
    path = HERE / "check_nyay18_frontend_namespaces.py"
    spec = importlib.util.spec_from_file_location("check_nyay18_frontend_namespaces", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load NYAY-18 namespace policy")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


policy = load_policy()


def load_workflow_policy():
    path = HERE / "verify_nyayone_ci.py"
    spec = importlib.util.spec_from_file_location("verify_nyayone_ci_nyay18", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load workflow policy")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NamespacePolicyTests(unittest.TestCase):
    def _fixture(self, directory: str) -> tuple[Path, dict[str, object]]:
        root = Path(directory)
        files = {
            "frontend/index.html": (
                "<!doctype html><title>NyayOne</title>"
                "<script type=\"module\" src=\"/src/main.tsx\"></script>\n"
            ),
            "frontend/package.json": json.dumps({"name": "nyayone-frontend"}) + "\n",
            "frontend/package-lock.json": json.dumps(
                {
                    "name": "nyayone-frontend",
                    "packages": {"": {"name": "nyayone-frontend"}},
                }
            ) + "\n",
            "frontend/capacitor.config.ts": (
                "export default { appId: 'com.nyayone.app', "
                "appName: 'NyayOne', webDir: 'dist', "
                "server: { androidScheme: 'https' } };\n"
            ),
            "frontend/vite.config.ts": "export default {};\n",
            "frontend/public/sw.js": "const CACHE = 'nyayone-shell-v1';\n",
            "frontend/src/main.tsx": (
                "const EVENT = 'nyayone:student-auth-changed';\n"
                "const THEME = 'nyayone.theme.v1';\n"
                "document.title = 'NyayOne';\n"
            ),
            "frontend/src/i18n/locales/en.json": '{"app.name":"NyayOne"}\n',
            "frontend/src/i18n/locales/hi.json": '{"app.name":"NyayOne"}\n',
            "frontend/src/features/student/lib/studentBrowserContext.ts": (
                "export const RETIRED = ['legalsaathi.student.profile.v1'];\n"
                "export function purge(storage: Storage) {\n"
                "  storage.removeItem(RETIRED[0]);\n"
                "}\n"
            ),
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        compatibility_path = (
            root / "frontend/src/features/student/lib/studentBrowserContext.ts"
        )
        contract = {
            "schema_version": 1,
            "source_inventory_sha256": policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            ),
            "metadata": {
                "package_name": "nyayone-frontend",
                "capacitor_app_id": "com.nyayone.app",
                "capacitor_android_scheme": "https",
                "capacitor_web_dir": "dist",
                "app_name": "NyayOne",
                "service_worker_cache": "nyayone-shell-v1",
            },
            "required_runtime_namespaces": {
                "nyayone-frontend": 3,
                "nyayone-shell-": 1,
                "nyayone-shell-v1": 1,
                "nyayone.app": 1,
                "nyayone.theme.v1": 1,
                "nyayone:student-auth-changed": 1,
            },
            "compatibility_sources": {
                "frontend/src/features/student/lib/studentBrowserContext.ts": {
                    "sha256": policy.sha256_file(compatibility_path),
                    "allowed_literals": {
                        "legalsaathi.student.profile.v1": 1,
                    },
                }
            },
        }
        return root, contract

    def test_clean_fixture_passes_exact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            report = policy.audit(root, contract)
        self.assertEqual(report.failures, ())
        self.assertGreater(report.scanned_files, 0)
        self.assertTrue(report.self_test_passed)

    def test_repository_shipped_surface_passes_sealed_contract(self) -> None:
        report = policy.audit(policy.ROOT, policy.load_contract())
        self.assertEqual(report.failures, ())
        self.assertEqual(report.source_inventory_count, 164)
        self.assertEqual(
            report.source_inventory_sha256,
            "eecb0b6cc29d3f32a6fcf92402607c7afefb5bbbdd6b118ea08f8b93e097a9dd",
        )
        self.assertTrue(report.self_test_passed)

    def test_closed_active_runtime_map_is_explicit_and_drift_fails_closed(self) -> None:
        required = policy.load_contract()["required_runtime_namespaces"]
        self.assertIsInstance(required, dict)
        expected = {
            "NYAY-CASE-": 3,
            "NYAY-INT-": 1,
            "NYAY-INV-": 1,
            "nyayone-frontend": 3,
            "nyayone-mark.svg": 3,
            "nyayone.r2.onboarding-seen": 2,
            "nyayone-shell-": 2,
            "nyayone-shell-v1": 1,
            "nyayone.app": 1,
            "nyayone.student.auth-session.v1": 1,
            "nyayone.student.auth-transition.v2": 1,
            "nyayone:student-auth-transition-started": 1,
            "nyayone-credential-qr.png": 1,
            "nyayone.clinical-export.v1": 1,
            "nyayone-clinical-hours-": 1,
        }
        for namespace, count in expected.items():
            self.assertEqual(required.get(namespace), count, namespace)

        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            source = root / "frontend/src/main.tsx"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "nyayone.theme.v1", "nyayone.theme.v2"
                ),
                encoding="utf-8",
            )
            report = policy.audit(root, contract)
        self.assertTrue(
            any(item.code == "required-runtime-namespace" for item in report.failures),
            report.failures,
        )

    def test_planted_visible_brand_and_runtime_namespace_fail_closed(self) -> None:
        canaries = {
            "visible copy": "export const title = 'LegalSaathi';\n",
            "lowercase namespace": "export const schema = 'legalsaathi.new.v1';\n",
            "spaced brand": "export const title = 'Legal Saathi';\n",
            "hyphenated brand": "export const title = 'legal-saathi';\n",
            "underscored brand": "export const title = 'legal_saathi';\n",
            "unicode escaped brand": (
                r"export const title = 'Legal\u0053aathi';" + "\n"
            ),
            "HTML entity brand": "export const title = <p>Legal&#83;aathi</p>;\n",
            "concatenated brand": "export const title = 'Legal' + 'Saathi';\n",
            "split-markup brand": "export const title = <p>Legal<span>Saathi</span></p>;\n",
            "legacy storage key": (
                "const STORAGE_KEY = 'ls-planted-private-v1';\n"
                "localStorage.setItem(STORAGE_KEY, 'x');\n"
            ),
        }
        for label, canary in canaries.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                source = root / "frontend/src/main.tsx"
                source.write_text(source.read_text(encoding="utf-8") + canary, encoding="utf-8")
                contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                    policy.shipped_source_inventory(root)
                )
                report = policy.audit(root, contract)
                self.assertTrue(report.failures, label)
                self.assertTrue(
                    any(
                        failure.code in {"legacy-brand", "legacy-browser-namespace"}
                        for failure in report.failures
                    ),
                    report.failures,
                )

    def test_constructed_legacy_brand_expressions_fail_closed(self) -> None:
        canaries = {
            "array join": "export const title = ['Legal', 'Saathi'].join('');\n",
            "const propagation": (
                "const first = 'Legal';\n"
                "const second = 'Saathi';\n"
                "export const title = first + second;\n"
            ),
            "template interpolation": (
                "export const title = `Legal${''}Saathi`;\n"
            ),
            "multi-fragment concatenation": (
                "export const title = 'Leg' + 'al' + 'Saa' + 'thi';\n"
            ),
            "literal concat method": (
                "export const title = 'Legal'.concat('Saathi');\n"
            ),
            "literal character codes": (
                "export const title = String.fromCharCode("
                "76, 101, 103, 97, 108, 83, 97, 97, 116, 104, 105);\n"
            ),
            "literal code points": (
                "document.title = String.fromCodePoint("
                "76, 101, 103, 97, 108, 83, 97, 97, 116, 104, 105);\n"
            ),
            "risky dynamic suffix": (
                "const suffix = window.name;\n"
                "export const title = 'Legal' + suffix;\n"
            ),
        }
        for label, canary in canaries.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                source = root / "frontend/src/main.tsx"
                source.write_text(
                    source.read_text(encoding="utf-8") + canary,
                    encoding="utf-8",
                )
                report = policy.audit(root, contract)
                self.assertTrue(
                    any(item.code == "legacy-brand" for item in report.failures),
                    report.failures,
                )

    def test_uncontracted_current_runtime_namespace_fails_closed(self) -> None:
        canaries = {
            "direct": (
                "localStorage.setItem('nyayone.planted.private.v1', 'secret');\n"
            ),
            "mixed case": (
                "localStorage.setItem('NyayOne.planted.private.v1', 'secret');\n"
            ),
            "concatenated": (
                "localStorage.setItem('nyay' + 'one.planted.private.v1', 'secret');\n"
            ),
            "const propagation": (
                "const owner = 'nyay'; const key = 'one.planted.private.v1';\n"
                "localStorage.setItem(owner + key, 'secret');\n"
            ),
            "literal concat method": (
                "localStorage.setItem("
                "'nyayone.'.concat('planted.private.v1'), 'secret');\n"
            ),
            "literal array join": (
                "localStorage.setItem("
                "['nyayone', 'planted', 'private', 'v1'].join('.'), 'secret');\n"
            ),
            "literal code points": (
                "localStorage.setItem(String.fromCodePoint("
                "110, 121, 97, 121, 111, 110, 101, 46, 112, 108, 97, 110, "
                "116, 101, 100, 46, 118, 49), 'secret');\n"
            ),
            "dynamic template": (
                "const family = window.name;\n"
                "localStorage.setItem(`nyayone.${family}.v1`, 'secret');\n"
            ),
            "uncontracted display reference": (
                "export const reference = 'NYAY-OTHER-001';\n"
            ),
        }
        for label, canary in canaries.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                source = root / "frontend/src/main.tsx"
                source.write_text(
                    source.read_text(encoding="utf-8") + canary,
                    encoding="utf-8",
                )
                report = policy.audit(root, contract)
                self.assertTrue(
                    any(
                        item.code == "uncontracted-runtime-namespace"
                        for item in report.failures
                    ),
                    report.failures,
                )

    def test_legacy_literal_is_allowed_only_in_exact_hash_sealed_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            other = root / "frontend/src/other.ts"
            other.write_text(
                "export const RETIRED = 'legalsaathi.student.profile.v1';\n",
                encoding="utf-8",
            )
            contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            )
            report = policy.audit(root, contract)
            self.assertTrue(any(item.code == "legacy-brand" for item in report.failures))

            other.unlink()
            compatibility = (
                root / "frontend/src/features/student/lib/studentBrowserContext.ts"
            )
            compatibility.write_text(
                compatibility.read_text(encoding="utf-8").replace(
                    "removeItem", "setItem"
                ),
                encoding="utf-8",
            )
            contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            )
            report = policy.audit(root, contract)
            self.assertTrue(
                any(item.code == "compatibility-source-hash" for item in report.failures),
                report.failures,
            )

    def test_inventory_drift_missing_inputs_and_unsafe_nodes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            (root / "frontend/src/new-runtime.ts").write_text(
                "export const brand = 'NyayOne';\n", encoding="utf-8"
            )
            report = policy.audit(root, contract)
            self.assertTrue(any(item.code == "source-inventory" for item in report.failures))

        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            (root / "frontend/index.html").unlink()
            report = policy.audit(root, contract)
            self.assertTrue(any(item.code == "required-source" for item in report.failures))

        if hasattr(Path, "symlink_to"):
            with tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                target = root / "outside.ts"
                target.write_text("export const brand = 'NyayOne';\n", encoding="utf-8")
                link = root / "frontend/src/link.ts"
                link.symlink_to(target)
                contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                    policy.shipped_source_inventory(root)
                )
                report = policy.audit(root, contract)
                self.assertTrue(any(item.code == "unsafe-source" for item in report.failures))

            with tempfile.TemporaryDirectory() as directory:
                container = Path(directory)
                real_root, contract = self._fixture(str(container / "real"))
                linked_root = container / "linked-root"
                linked_root.symlink_to(real_root, target_is_directory=True)
                report = policy.audit(linked_root, contract)
                self.assertTrue(
                    any(item.code == "unsafe-root" for item in report.failures),
                    report.failures,
                )

        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            unsupported = root / "frontend/src/planted.vue"
            unsupported.write_text("<template>LegalSaathi</template>\n", encoding="utf-8")
            contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            )
            report = policy.audit(root, contract)
            self.assertTrue(
                any(item.code == "unsupported-source-format" for item in report.failures),
                report.failures,
            )

    def test_metadata_contract_is_exact_not_merely_nonlegacy(self) -> None:
        mutations = {
            "package": ("frontend/package.json", '{"name":"another-app"}\n'),
            "lock": (
                "frontend/package-lock.json",
                '{"name":"another-app","packages":{"":{"name":"another-app"}}}\n',
            ),
            "capacitor": (
                "frontend/capacitor.config.ts",
                "export default { appId: 'org.example.app', appName: 'Other' };\n",
            ),
            "capacitor webDir": (
                "frontend/capacitor.config.ts",
                "export default { appId: 'com.nyayone.app', appName: 'NyayOne', "
                "webDir: 'build', server: { androidScheme: 'https' } };\n",
            ),
            "capacitor Android scheme": (
                "frontend/capacitor.config.ts",
                "export default { appId: 'com.nyayone.app', appName: 'NyayOne', "
                "webDir: 'dist', server: { androidScheme: 'http' } };\n",
            ),
            "title": ("frontend/index.html", "<!doctype html><title>Other</title>\n"),
            "entrypoint": (
                "frontend/index.html",
                "<!doctype html><title>NyayOne</title>"
                "<script type=\"module\" src=\"/outside.ts\"></script>\n",
            ),
            "cache": ("frontend/public/sw.js", "const CACHE = 'other-shell-v1';\n"),
        }
        for label, (relative, replacement) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                (root / relative).write_text(replacement, encoding="utf-8")
                report = policy.audit(root, contract)
                self.assertTrue(
                    any(item.code == "metadata-identity" for item in report.failures),
                    report.failures,
                )

    def test_locale_app_identity_is_exact_in_english_and_hindi(self) -> None:
        for relative in (
            "frontend/src/i18n/locales/en.json",
            "frontend/src/i18n/locales/hi.json",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                (root / relative).write_text('{"app.name":"Other"}\n', encoding="utf-8")
                report = policy.audit(root, contract)
                self.assertTrue(
                    any(item.code == "metadata-identity" for item in report.failures),
                    report.failures,
                )

    def test_historical_traceability_comments_are_not_shipped_brand_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            source = root / "frontend/src/main.tsx"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "// docs/design/LegalSaathi historical traceability matrix.md\n"
                + "/* Legal Saathi historical provenance only. */\n",
                encoding="utf-8",
            )
            report = policy.audit(root, contract)
        self.assertEqual(report.failures, ())

    def test_bounded_dynamic_analysis_preserves_nonbrand_legal_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            source = root / "frontend/src/main.tsx"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "const state = window.name;\n"
                + "const session = `This session is ${state}`;\n"
                + "const transition = `illegal transition ${state}`;\n"
                + "const review = `Requires Legal Counsel review for ${state}`;\n",
                encoding="utf-8",
            )
            report = policy.audit(root, contract)
        self.assertEqual(report.failures, ())

    def test_ls_styling_tokens_are_not_misclassified_as_browser_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            source = root / "frontend/src/main.tsx"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "export const shell = <div className=\"ls-shell ls-card\" "
                + "id=\"ls-card\" data-testid=\"ls-shell\" />;\n",
                encoding="utf-8",
            )
            styles = root / "frontend/src/styles.css"
            styles.write_text(
                ".ls-shell .ls-card::before { content: 'ls-styling-token'; }\n",
                encoding="utf-8",
            )
            contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            )
            report = policy.audit(root, contract)
        self.assertEqual(report.failures, ())

    def test_nyayone_presentation_identifiers_are_not_runtime_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            source = root / "frontend/src/main.tsx"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "import './styles/nyayone-tokens.css';\n"
                + "const trigger = document.querySelector(\n"
                + "  '[data-nyayone-persona-trigger] .nyayone-selector',\n"
                + ");\n"
                + "const hooks = { 'data-nyayone-value': 'student' };\n"
                + "export const shell = (\n"
                + "  <div className={`nyayone-selector${trigger ? ' is-open' : ''}`}\n"
                + "    data-nyayone-selector=\"persona\" {...hooks} />\n"
                + ");\n",
                encoding="utf-8",
            )
            styles = root / "frontend/src/styles/nyayone-tokens.css"
            styles.parent.mkdir(parents=True, exist_ok=True)
            styles.write_text(
                ":root { --nyayone-color-focus: #2e3a8c; }\n"
                ".nyayone-selector { color: var(--nyayone-color-focus); }\n",
                encoding="utf-8",
            )
            contract["source_inventory_sha256"] = policy.source_inventory_sha256(
                policy.shipped_source_inventory(root)
            )
            report = policy.audit(root, contract)
        self.assertEqual(report.failures, ())

    def test_browser_authority_contexts_remain_fail_closed(self) -> None:
        canaries = {
            "local storage": (
                "localStorage.setItem('nyayone.planted.local.v1', 'secret');\n"
            ),
            "session storage dynamic template": (
                "const family = window.name;\n"
                "sessionStorage.setItem(`nyayone.${family}.v1`, 'secret');\n"
            ),
            "storage side effect nested in presentation expression": (
                "export const planted = <div className={"
                "localStorage.setItem('nyayone.planted.nested.v1', 'secret')"
                " as never} />;\n"
            ),
            "bracket storage side effect nested in presentation expression": (
                "export const planted = <div className={"
                "localStorage['setItem']('nyayone.planted.bracket.v1', 'secret')"
                " as never} />;\n"
            ),
            "optional storage side effect nested in presentation expression": (
                "export const planted = <div className={"
                "localStorage?.setItem('nyayone.planted.optional.v1', 'secret')"
                " as never} />;\n"
            ),
            "aliased dynamic storage side effect nested in presentation expression": (
                "const plantedStore = localStorage;\n"
                "export const planted = <div className={"
                "plantedStore.setItem(`nyayone.${window.name}.alias.v1`, 'secret')"
                " as never} />;\n"
            ),
            "named storage property nested in presentation expression": (
                "export const planted = <div className={"
                "localStorage['nyayone.planted.named-property.v1']"
                " as never} />;\n"
            ),
            "browser authority nested in presentation template": (
                "export const planted = <div className={`plain-${"
                "localStorage.setItem('nyayone.planted.template.v1', 'secret')"
                "}`} />;\n"
            ),
            "cache storage": "caches.open('nyayone-planted-cache');\n",
            "cache storage dynamic template": (
                "const family = window.name;\n"
                "caches.open(`nyayone-${family}-cache`);\n"
            ),
            "bracket cache side effect nested in presentation expression": (
                "export const planted = <div className={"
                "caches['open']('nyayone-planted-bracket-cache') as never} />;\n"
            ),
            "document cookie": "document.cookie = 'nyayone.planted.cookie=1';\n",
            "bracket cookie side effect nested in presentation expression": (
                "export const planted = <div className={"
                "(document['cookie'] = 'nyayone.planted.bracket.cookie=1')"
                " as never} />;\n"
            ),
            "cookie store dynamic template": (
                "const family = window.name;\n"
                "cookieStore.set(`nyayone.${family}.cookie`, '1');\n"
            ),
            "indexeddb side effect nested in presentation expression": (
                "export const planted = <div className={"
                "indexedDB.open('nyayone.planted.indexeddb.v1') as never} />;\n"
            ),
            "custom event": "new CustomEvent('nyayone:planted-event');\n",
            "qualified custom event nested in presentation expression": (
                "export const planted = <div className={"
                "new window.CustomEvent('nyayone:planted-qualified-event')"
                " as never} />;\n"
            ),
            "event listener dynamic template": (
                "const family = window.name;\n"
                "window.addEventListener(`nyayone:${family}`, () => {});\n"
            ),
            "broadcast channel": (
                "new BroadcastChannel('nyayone:planted-channel');\n"
            ),
            "broadcast channel dynamic template": (
                "const family = window.name;\n"
                "new BroadcastChannel(`nyayone:${family}`);\n"
            ),
            "qualified broadcast channel nested in presentation expression": (
                "export const planted = <div className={"
                "new window.BroadcastChannel('nyayone:planted-qualified-channel')"
                " as never} />;\n"
            ),
            "data hook object reused as storage authority": (
                "const plantedHooks = { 'data-nyayone-storage-authority': 'x' };\n"
                "export const planted = <div {...plantedHooks} />;\n"
                "localStorage.setItem(Object.keys(plantedHooks)[0], 'secret');\n"
            ),
            "DOM-derived presentation value reused as storage authority": (
                "export const planted = <button "
                "className='nyayone.planted.dom-key.v1' "
                "onClick={(event) => localStorage.setItem("
                "event.currentTarget.className, 'secret')} />;\n"
            ),
            "aliased DOM-derived presentation value reused as storage authority": (
                "export function persist(event) {\n"
                "  const plantedKey = event.currentTarget.className;\n"
                "  localStorage.setItem(plantedKey, 'secret');\n"
                "}\n"
                "export const planted = <button "
                "className='nyayone.planted.aliased-dom-key.v1' "
                "onClick={persist} />;\n"
            ),
            "bracket DOM-derived presentation value reused as storage authority": (
                "export const planted = <button "
                "className='nyayone.planted.bracket-dom-key.v1' "
                "onClick={(event) => localStorage['setItem']("
                "event.currentTarget['className'], 'secret')} />;\n"
            ),
            "optional DOM-derived presentation value reused as storage authority": (
                "export const planted = <button "
                "className='nyayone.planted.optional-dom-key.v1' "
                "onClick={(event) => localStorage?.setItem("
                "event.currentTarget?.className, 'secret')} />;\n"
            ),
            "storage alias consumes DOM-derived presentation value": (
                "const plantedStore = localStorage;\n"
                "export const planted = <button "
                "className='nyayone.planted.store-alias-dom-key.v1' "
                "onClick={(event) => plantedStore.setItem("
                "event.currentTarget.className, 'secret')} />;\n"
            ),
            "destructured DOM presentation value reused as storage authority": (
                "export function persist(event) {\n"
                "  const { className: plantedKey } = event.currentTarget;\n"
                "  localStorage.setItem(plantedKey, 'secret');\n"
                "}\n"
                "export const planted = <button "
                "className='nyayone.planted.destructured-dom-key.v1' "
                "onClick={persist} />;\n"
            ),
            "destructured storage method consumes DOM presentation value": (
                "const { setItem: persist } = localStorage;\n"
                "export const planted = <button "
                "className='nyayone.planted.destructured-storage.v1' "
                "onClick={(event) => persist("
                "event.currentTarget.className, 'secret')} />;\n"
            ),
            "qualified destructured storage method consumes DOM presentation value": (
                "const { setItem: persist } = window.localStorage;\n"
                "export const planted = <button "
                "className='nyayone.planted.qualified-destructured-storage.v1' "
                "onClick={(event) => persist("
                "event.currentTarget.className, 'secret')} />;\n"
            ),
            "storage authority passed through helper with DOM presentation value": (
                "function persist(store, event) {\n"
                "  store.setItem(event.currentTarget.className, 'secret');\n"
                "}\n"
                "export const planted = <button "
                "className='nyayone.planted.helper-storage.v1' "
                "onClick={(event) => persist(localStorage, event)} />;\n"
            ),
            "DOM class-list value reused as storage authority": (
                "export const planted = <button "
                "className='nyayone.planted.class-list.v1' "
                "onClick={(event) => localStorage.setItem("
                "event.currentTarget.classList.value, 'secret')} />;\n"
            ),
            "attribute lookalike inside JSX expression": (
                "export const planted = <div title={(className = "
                "'nyayone.planted.attribute-lookalike.v1') as never} />;\n"
            ),
            "data hook lookalike inside another attribute": (
                "export const planted = <div "
                "title='data-nyayone-planted-lookalike' />;\n"
            ),
            "regex brace cannot truncate presentation projection": (
                "export const shell = <div className={"
                "/{/.test(window.name) ? 'plain' : ''} />;\n"
                "const plantedAfterJsx = 'nyayone.planted.after-jsx.v1';\n"
            ),
        }
        for label, canary in canaries.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root, contract = self._fixture(directory)
                source = root / "frontend/src/main.tsx"
                source.write_text(
                    source.read_text(encoding="utf-8") + canary,
                    encoding="utf-8",
                )
                report = policy.audit(root, contract)
            self.assertTrue(
                any(
                    item.code == "uncontracted-runtime-namespace"
                    for item in report.failures
                ),
                report.failures,
            )

    def test_self_test_and_evidence_projection_do_not_disclose_canary(self) -> None:
        result = policy.run_self_test()
        self.assertTrue(result.passed)
        self.assertEqual(result.mutants, 17)
        self.assertEqual(result.mutants_killed, result.mutants)
        serialized = json.dumps(result.evidence(), sort_keys=True)
        self.assertNotIn(policy.PLANTED_BRAND_CANARY, serialized)
        self.assertNotIn("ls-planted", serialized)

    def test_static_evidence_binds_source_and_namespace_contract_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, contract = self._fixture(directory)
            report = policy.audit(root, contract)
        evidence = report.evidence()
        self.assertRegex(
            evidence["sourceInventory"]["sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            evidence["namespaceContract"]["sha256"], r"^[0-9a-f]{64}$"
        )

    def test_workflow_and_executable_chain_are_hash_sealed(self) -> None:
        workflow_policy = load_workflow_policy()
        workflow = (
            workflow_policy.ROOT
            / ".github/workflows/nyay18-frontend-namespace-gate.yml"
        )
        self.assertEqual(workflow_policy.check_workflow(workflow), [])
        self.assertEqual(workflow_policy.check_nyay18_static_gate_contract(), [])

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "detector.py"
            planted.write_bytes(
                workflow_policy.NYAY18_NAMESPACE_GATE.read_bytes()
                + b"\n# planted detector bypass\n"
            )
            failures = workflow_policy.check_nyay18_static_gate_contract(
                detector_path=planted
            )
        self.assertTrue(
            any("detector SHA-256" in item for item in failures), failures
        )

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "tests.py"
            planted.write_bytes(
                workflow_policy.NYAY18_NAMESPACE_GATE_TEST.read_bytes()
                + b"\n# planted test deletion\n"
            )
            failures = workflow_policy.check_nyay18_static_gate_contract(
                test_path=planted
            )
        self.assertTrue(
            any("detector tests SHA-256" in item for item in failures), failures
        )

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "contract.json"
            planted.write_bytes(
                workflow_policy.NYAY18_NAMESPACE_CONTRACT.read_bytes() + b" \n"
            )
            failures = workflow_policy.check_nyay18_static_gate_contract(
                contract_path=planted
            )
        self.assertTrue(
            any("namespace contract SHA-256" in item for item in failures), failures
        )

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "boundary.md"
            planted.write_bytes(
                workflow_policy.NYAY18_NAMESPACE_BOUNDARY_DOCUMENT.read_bytes()
                + b"\nPlanted rollback permission.\n"
            )
            failures = workflow_policy.check_nyay18_static_gate_contract(
                document_path=planted
            )
        self.assertTrue(
            any("boundary document SHA-256" in item for item in failures), failures
        )

        original = workflow.read_text(encoding="utf-8")
        mutated = original.replace(
            "python scripts/ci/check_nyay18_frontend_namespaces.py",
            "python -c 'print(\"bypassed\")'",
            1,
        )
        self.assertNotEqual(mutated, original)
        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / workflow.name
            planted.write_text(mutated, encoding="utf-8")
            failures = workflow_policy.check_workflow(planted)
        self.assertTrue(failures)

    def test_production_browser_executable_chain_is_exact_and_sealed(self) -> None:
        workflow_policy = load_workflow_policy()
        self.assertEqual(workflow_policy.check_nyay18_browser_gate_contract(), [])

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "nyay18_browser_namespace_gate.sh"
            planted.write_bytes(
                workflow_policy.NYAY18_BROWSER_ORCHESTRATOR.read_bytes()
            )
            os.chmod(planted, 0o644)
            failures = workflow_policy.check_nyay18_browser_gate_contract(
                orchestrator_path=planted
            )
        self.assertTrue(
            any("orchestrator" in item and "executable" in item for item in failures),
            failures,
        )

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "nyay18-browser-namespace.mjs"
            planted.write_bytes(
                workflow_policy.NYAY18_BROWSER_GATE.read_bytes()
                + b"\n// planted browser bypass\n"
            )
            failures = workflow_policy.check_nyay18_browser_gate_contract(
                browser_path=planted
            )
        self.assertTrue(
            any("browser gate SHA-256" in item for item in failures), failures
        )

        planted_files = (
            (
                workflow_policy.NYAY18_BROWSER_ORCHESTRATOR,
                "orchestrator_path",
                "browser orchestrator",
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "browser assertion contract",
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT_TEST,
                "contract_test_path",
                "browser assertion contract tests",
            ),
            (
                workflow_policy.NYAY18_BROWSER_PREVIEW_SERVER,
                "preview_path",
                "browser preview canary server",
            ),
        )
        for original, argument, label in planted_files:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                planted = Path(directory) / original.name
                planted.write_bytes(original.read_bytes() + b"\n# planted bypass\n")
                if argument == "orchestrator_path":
                    os.chmod(planted, 0o755)
                failures = workflow_policy.check_nyay18_browser_gate_contract(
                    **{argument: planted}
                )
                self.assertTrue(
                    any(label in item and "SHA-256" in item for item in failures),
                    failures,
                )

        with tempfile.TemporaryDirectory() as directory:
            planted = Path(directory) / "package.json"
            package = json.loads(workflow_policy.FRONTEND_PACKAGE.read_text())
            package["scripts"]["qa:nyay18:browser-namespace"] = (
                "node -e 'process.exit(0)'"
            )
            planted.write_text(json.dumps(package), encoding="utf-8")
            failures = workflow_policy.check_nyay18_browser_gate_contract(
                package_path=planted
            )
        self.assertTrue(
            any("package command" in item for item in failures), failures
        )

    def test_browser_exact_head_and_nyay5_separation_semantics_are_explicit(self) -> None:
        workflow_policy = load_workflow_policy()
        mutations = (
            (
                workflow_policy.NYAY18_BROWSER_ORCHESTRATOR,
                "orchestrator_path",
                'NYAY18_EXACT_TREE="$EXACT_TREE"',
                'NYAY18_EXACT_TREE="$EXACT_COMMIT"',
                "exact-head environment plumbing",
                True,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "exactTree: EXACT_TREE,",
                "exactTree: EXACT_COMMIT,",
                "exact-head evidence semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "if (!COMMIT.test(report?.exactTree ?? ''))",
                "if (!SHA256.test(report?.exactTree ?? ''))",
                "exact-head evidence contract semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "inherited_nyay5_contract_integrity",
                "inherited_nyay5_oracles_green",
                "NYAY-5 contract-integrity separation",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_PREVIEW_SERVER,
                "preview_path",
                "if (request.headers.cookie) metrics.hostileAssetCookieHeaders += 1;",
                "if (false) metrics.hostileAssetCookieHeaders += 1;",
                "preview credential-canary semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "previewServerSourceSha256: PREVIEW_SOURCE_SHA256,",
                "previewServerSourceSha256: EXACT_TREE,",
                "preview-source digest semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                r"legal[\s._-]*saathi",
                r"legal\s*saathi",
                "legacy-brand separator runtime semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "hostileShellServerRequests === 1",
                "hostileShellServerRequests >= 0",
                "install-shell credential-canary semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "const detectedInBothDocuments = (key) => migration[key] === true && final[key] === true;",
                "const detectedInBothDocuments = (key) => migration[key] === true;",
                "two-realm privacy-instrumentation semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "metrics.instrumentationDocumentCount === 2",
                "metrics.instrumentationDocumentCount >= 1",
                "two-realm privacy-instrumentation contract semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT_TEST,
                "contract_test_path",
                "metrics.instrumentationDocumentCount = 1;",
                "metrics.instrumentationDocumentCount = 2;",
                "two-realm privacy-instrumentation contract-test semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "&& leading.leadingBeforeOwned && leading.targetRemoved && leading.valuesExact",
                "&& leading.leadingBeforeOwned && leading.valuesExact",
                "finite leading-key purge semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "&& metrics.targetRemoved === true",
                "&& metrics.targetRemoved !== null",
                "finite leading-key purge contract semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT_TEST,
                "contract_test_path",
                "metrics.targetRemoved = false;",
                "metrics.targetRemoved = true;",
                "finite leading-key purge contract-test semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "&& lifecycle.actorRotationRediscoveryResponses === 1",
                "&& lifecycle.actorRotationRediscoveryResponses >= 0",
                "actor-rotation rediscovery semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "&& metrics.actorRotationRediscoveryResponses === 1",
                "&& metrics.actorRotationRediscoveryResponses >= 0",
                "actor-rotation rediscovery contract semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT_TEST,
                "contract_test_path",
                "metrics.actorRotationRediscoveryResponses = 0;",
                "metrics.actorRotationRediscoveryResponses = 1;",
                "actor-rotation rediscovery contract-test semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_GATE,
                "browser_path",
                "lifecycle.transitionStarts === 5 && lifecycle.transitionEnds === 5",
                "lifecycle.transitionStarts === 4 && lifecycle.transitionEnds === 4",
                "authority-loss transition semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT,
                "contract_path",
                "&& metrics.transitionStarts === 5",
                "&& metrics.transitionStarts === 4",
                "authority-loss transition contract semantics",
                False,
            ),
            (
                workflow_policy.NYAY18_BROWSER_CONTRACT_TEST,
                "contract_test_path",
                "'lifecycle-missing-transition'",
                "'lifecycle-transition-not-bound'",
                "authority-loss transition contract-test semantics",
                False,
            ),
        )
        for original, argument, old, new, expected, executable in mutations:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                planted = Path(directory) / original.name
                text = original.read_text(encoding="utf-8")
                mutated = text.replace(old, new)
                self.assertNotEqual(mutated, text)
                planted.write_text(mutated, encoding="utf-8")
                if executable:
                    os.chmod(planted, 0o755)
                failures = workflow_policy.check_nyay18_browser_gate_contract(
                    **{argument: planted}
                )
            self.assertTrue(
                any(expected in item for item in failures),
                failures,
            )

    def test_browser_evidence_chain_binds_raw_and_uploadable_attestations(self) -> None:
        workflow_policy = load_workflow_policy()
        workflow = (
            workflow_policy.ROOT
            / ".github/workflows/nyay18-frontend-namespace-gate.yml"
        )
        original = workflow.read_text(encoding="utf-8")
        mutations = (
            (
                'evidence_manifest.py --seal "$RUNNER_TEMP/nyay18-browser-raw"',
                'evidence_manifest.py --seal "$RUNNER_TEMP/nyay18-browser-wrong"',
            ),
            (
                'evidence_manifest.py --verify "$RUNNER_TEMP/nyay18-browser-raw"',
                'evidence_manifest.py --verify "$RUNNER_TEMP/nyay18-browser-wrong"',
            ),
            (
                'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/results.json" '
                '"$RUNNER_TEMP/nyay18-browser-uploadable/results.json"',
                'install -m 0600 "$RUNNER_TEMP/nyay18-browser-raw/results.json" '
                '"$RUNNER_TEMP/nyay18-browser-uploadable/wrong.json"',
            ),
            (
                "path: ${{ runner.temp }}/nyay18-browser-uploadable",
                "path: ${{ runner.temp }}/nyay18-browser-raw",
            ),
            (
                "steps.browser_raw_integrity.outcome == 'success'",
                "steps.browser_raw_integrity.outcome == 'skipped'",
            ),
        )
        for before, after in mutations:
            with self.subTest(before=before), tempfile.TemporaryDirectory() as directory:
                self.assertIn(before, original)
                planted = Path(directory) / workflow.name
                planted.write_text(original.replace(before, after, 1), encoding="utf-8")
                failures = workflow_policy.check_workflow(planted)
                self.assertTrue(
                    any(
                        "NYAY-18 browser evidence chain differs" in item
                        for item in failures
                    ),
                    failures,
                )


if __name__ == "__main__":
    unittest.main()
