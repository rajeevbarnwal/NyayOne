#!/usr/bin/env python3
"""Literal contract for the NYAY-18 browser/mobile namespace boundary document."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "docs/architecture/nyay18-frontend-browser-mobile-namespace-boundary.md"


class Nyay18NamespaceBoundaryDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DOCUMENT.read_text(encoding="utf-8")
        cls.prose = " ".join(cls.text.split())

    def test_exact_active_identity_and_runtime_map_is_present(self) -> None:
        for literal in (
            "`nyayone-frontend`",
            "`com.nyayone.app`",
            "`NyayOne`",
            "`nyayone-shell-v1`",
            "`nyayone.theme.v1`",
            "`nyayone.locale.v1`",
            "`nyayone.auth.${role}.v1`",
            "`nyayone.student.reports.v1.`",
            "`nyayone.student.reminder-prefs.v1.`",
            "`nyayone.lawyer.draft-workspace.v1.`",
            "`nyayone.lawyer.review-workspace.v1.`",
            "`nyayone.lawyer.filing-workflow.v1.`",
            "`nyayone:auth-change`",
            "`nyayone:student-auth-changed`",
            "`nyayone:student-auth-transition-started`",
            "`nyayone.student.auth-session.v1`",
            "`nyayone.student.auth-transition.v2`",
            "`__nyayoneVideoTransport`",
            "`__nyayoneVideoRoom`",
            "`nyayone-credential-qr.png`",
            "`nyayone.clinical-export.v1`",
            "`nyayone-clinical-hours-`",
            "`/brand/nyayone-mark.svg`",
            "`NYAY-CASE-`",
            "`NYAY-INV-`",
            "`NYAY-INT-`",
        ):
            self.assertIn(literal, self.text)
        for row in (
            "Case display/reference prefix | `NYAY-CASE-`",
            "Invoice display/reference prefix | `NYAY-INV-`",
            "Internship display/reference prefix | `NYAY-INT-`",
        ):
            self.assertIn(row, self.text)
        self.assertGreaterEqual(
            self.prose.count(
                "Display/reference only; never authentication, payment, or session authority."
            ),
            3,
        )

    def test_delete_only_inventory_and_theme_exception_are_literal(self) -> None:
        for literal in (
            "`legalsaathi.student.profile.v1`",
            "`legalsaathi.student.onboarding.v34`",
            "`legalsaathi.internship.applications.v1`",
            "`legalsaathi.clinical.export-audit.v1`",
            "`legalsaathi.student.cleanup-registry.v1`",
            "`ls-auth-student`",
            "`ls-auth-lawyer`",
            "`ls-locale`",
            "`ls-reviewer`",
            "`ls-onboarding-seen`",
            "`ls-reports-`",
            "`ls-reminder-prefs-`",
            "`ls-draftws-`",
            "`ls-review-`",
            "`ls-filing-`",
            "`legalsaathi.student.registration.v2`",
            "`legalsaathi.student.privacy.export.v1`",
            "`legalsaathi.student.privacy.delete.v1`",
        ):
            self.assertIn(literal, self.text)
        self.assertIn("sole compatible legacy value", self.prose)
        self.assertIn("valid `light` or `dark`", self.prose)
        self.assertIn("read `ls-theme` at most once", self.prose)

    def test_cleanup_and_private_mount_invariants_are_explicit(self) -> None:
        for phrase in (
            "at most 256 matching keys",
            "never calls `storage.clear()`",
            "never reads a delete-only legacy value",
            "preserves every unrelated key",
            "before `ReactDOM.createRoot`",
            "Logout, expiry, revocation, actor change, and accepted deletion",
            "private routes remain `unavailable`",
            "Web Locks",
            "CacheStorage",
        ):
            self.assertIn(phrase, self.prose)

    def test_qa_exact_head_and_rollback_constraints_are_explicit(self) -> None:
        for phrase in (
            "real production Chromium",
            "exact candidate HEAD and tree",
            "planted-mutant",
            "Do not roll back by restoring a legacy writer",
            "server-authoritative NYAY-5 boundary",
            "changing `com.nyayone.app` creates a different mobile application",
            "`inherited_nyay5_contract_integrity`",
            "does not execute or replace the independently required NYAY-5 workflow",
            "bounded static projection, not a proof against arbitrary JavaScript evaluation",
            "`nyay18-preview-server.mjs`",
            "server-observed Cookie-header count must be zero",
        ):
            self.assertIn(phrase, self.prose)


if __name__ == "__main__":
    unittest.main()
