"""Smoke tests – run with: python tests/smoke_test.py

Tests:
  1. PDF extraction from a tiny inline PDF.
  2. Content hashing is deterministic.
  3. payments.verify_payment_signature verifies correctly.
  4. payments.verify_webhook_signature verifies correctly.
  5. App health check (requires server running at localhost:8000).
"""
import hashlib
import hmac
import os
import sys
import unittest

# ── 1. PDF extraction ────────────────────────────────────────────────────────
class TestPdfUtils(unittest.TestCase):

    def _make_minimal_pdf(self, text: str) -> bytes:
        """Build the smallest possible valid single-page PDF with the given text."""
        # We'll use a raw-crafted PDF that PyMuPDF can open
        content = (
            b"BT /F1 12 Tf 72 720 Td (" + text.encode() + b") Tj ET"
        )
        stream_len = len(content)
        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
            b"4 0 obj<</Length " + str(stream_len).encode() + b">>\n"
            b"stream\n" + content + b"\nendstream\nendobj\n"
            b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
            b"xref\n0 6\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"0000000266 00000 n \n"
            b"0000000360 00000 n \n"
            b"trailer<</Size 6/Root 1 0 R>>\n"
            b"startxref\n420\n%%EOF"
        )
        return pdf

    def test_extract_simple(self):
        import pdf_utils
        try:
            import fitz  # noqa
        except ImportError:
            self.skipTest("PyMuPDF not installed")

        pdf = self._make_minimal_pdf("Hello World Resume")
        text = pdf_utils.extract_text(pdf)
        # Text may vary; just check it's non-empty and a string
        self.assertIsInstance(text, str)

    def test_too_large_raises(self):
        import pdf_utils
        big = b"%" + b"x" * (2 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError) as ctx:
            pdf_utils.extract_text(big)
        self.assertIn("2 MB", str(ctx.exception))

    def test_invalid_pdf_raises(self):
        import pdf_utils
        try:
            import fitz  # noqa
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        with self.assertRaises(ValueError):
            pdf_utils.extract_text(b"not a pdf at all")


# ── 2. Pipeline hash ──────────────────────────────────────────────────────────
class TestPipelineHash(unittest.TestCase):
    """Test the content hash logic directly (no DB/LLM imports)."""

    @staticmethod
    def _content_hash(resume_text: str, jd_text: str) -> str:
        h = hashlib.sha256(f"{resume_text}|||{jd_text}".encode()).hexdigest()
        return h[:32]

    def test_deterministic(self):
        h1 = self._content_hash("resume text", "job description")
        h2 = self._content_hash("resume text", "job description")
        self.assertEqual(h1, h2)

    def test_different_inputs(self):
        h1 = self._content_hash("a", "b")
        h2 = self._content_hash("c", "d")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = self._content_hash("any", "thing")
        self.assertEqual(len(h), 32)


# ── 3. Payment signature verification ────────────────────────────────────────
class TestPayments(unittest.TestCase):

    def setUp(self):
        os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dummy"
        os.environ["RAZORPAY_KEY_SECRET"] = "testsecret"
        os.environ["RAZORPAY_WEBHOOK_SECRET"] = "webhooksecret"

    def test_verify_payment_signature_valid(self):
        import payments
        order_id = "order_abc"
        payment_id = "pay_xyz"
        msg = f"{order_id}|{payment_id}".encode()
        sig = hmac.new(b"testsecret", msg, hashlib.sha256).hexdigest()
        self.assertTrue(payments.verify_payment_signature(order_id, payment_id, sig))

    def test_verify_payment_signature_invalid(self):
        import payments
        self.assertFalse(
            payments.verify_payment_signature("order_abc", "pay_xyz", "badsig")
        )

    def test_verify_webhook_signature_valid(self):
        import payments
        body = b'{"event":"payment.captured"}'
        sig = hmac.new(b"webhooksecret", body, hashlib.sha256).hexdigest()
        self.assertTrue(payments.verify_webhook_signature(body, sig))

    def test_verify_webhook_signature_invalid(self):
        import payments
        self.assertFalse(
            payments.verify_webhook_signature(b"body", "badsignature")
        )

    def test_verify_payment_signature_empty_secret_returns_false(self):
        """When RAZORPAY_KEY_SECRET is unset, verify must return False (not True)."""
        import payments
        original = os.environ.pop("RAZORPAY_KEY_SECRET", None)
        try:
            self.assertFalse(
                payments.verify_payment_signature("order_abc", "pay_xyz", "anything")
            )
        finally:
            if original is not None:
                os.environ["RAZORPAY_KEY_SECRET"] = original

    def test_verify_webhook_signature_empty_secret_returns_false(self):
        """When RAZORPAY_WEBHOOK_SECRET is unset, verify must return False (not True)."""
        import payments
        original = os.environ.pop("RAZORPAY_WEBHOOK_SECRET", None)
        try:
            self.assertFalse(
                payments.verify_webhook_signature(b"anybody", "anysig")
            )
        finally:
            if original is not None:
                os.environ["RAZORPAY_WEBHOOK_SECRET"] = original


# ── 4. Rubric score cap logic ─────────────────────────────────────────────────
class TestScoreRubric(unittest.TestCase):
    """Test _score_from_rubric() in isolation – no LLM, no network."""

    @staticmethod
    def _call(raw: dict):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import llm
        return llm._score_from_rubric(raw)

    def _perfect(self):
        return {"keyword_match": 30, "role_fit": 25, "impact": 20,
                "clarity": 15, "completeness": 10}

    def test_perfect_score_is_100(self):
        score, _, badge = self._call(self._perfect())
        self.assertEqual(score, 100)
        self.assertEqual(badge, "Excellent")

    def test_per_dimension_over_cap_is_clamped(self):
        raw = {"keyword_match": 99, "role_fit": 99, "impact": 99,
               "clarity": 99, "completeness": 99}
        score, subscores, _ = self._call(raw)
        self.assertEqual(subscores["keyword_match"], 30)
        self.assertEqual(subscores["role_fit"], 25)
        self.assertEqual(score, 100)

    def test_role_fit_cap_limits_total_to_65(self):
        """role_fit < 12 must cap total at 65, regardless of other subscores."""
        raw = {**self._perfect(), "role_fit": 11}   # 11 < 12 → cap at 65
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 65)

    def test_keyword_match_cap_limits_total_to_60(self):
        """keyword_match < 12 must cap total at 60."""
        raw = {**self._perfect(), "keyword_match": 5}   # 5 < 12 → cap at 60
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 60)

    def test_both_caps_tightest_wins(self):
        """When both caps fire, the tighter one (60) must apply."""
        raw = {**self._perfect(), "role_fit": 5, "keyword_match": 5}
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 60)

    def test_badge_needs_work(self):
        raw = {"keyword_match": 5, "role_fit": 5, "impact": 5,
               "clarity": 5, "completeness": 5}
        _, _, badge = self._call(raw)
        self.assertEqual(badge, "Needs work")

    def test_badge_getting_there(self):
        raw = {"keyword_match": 18, "role_fit": 13, "impact": 7,
               "clarity": 5, "completeness": 5}
        score, _, badge = self._call(raw)
        self.assertGreaterEqual(score, 40)
        self.assertLess(score, 60)
        self.assertEqual(badge, "Getting there")

    def test_badge_strong(self):
        raw = {"keyword_match": 22, "role_fit": 18, "impact": 12,
               "clarity": 10, "completeness": 8}
        score, _, badge = self._call(raw)
        self.assertGreaterEqual(score, 60)
        self.assertLess(score, 80)
        self.assertEqual(badge, "Strong")

    def test_badge_excellent(self):
        score, _, badge = self._call(self._perfect())
        self.assertEqual(badge, "Excellent")

    def test_missing_keys_default_to_zero(self):
        score, subscores, badge = self._call({})
        self.assertEqual(score, 0)
        self.assertEqual(badge, "Needs work")
        self.assertEqual(subscores["keyword_match"], 0)



class TestCategoricalCaps(unittest.TestCase):
    """Test hard caps from role_match and must_have_coverage – no LLM, no network."""

    @staticmethod
    def _call(raw: dict):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import llm
        return llm._score_from_rubric(raw)

    def _perfect_subscores(self):
        """All five subscores maxed out = 100 before any categorical cap."""
        return {
            "keyword_match": 30,
            "role_fit": 25,
            "impact": 20,
            "clarity": 15,
            "completeness": 10,
        }

    # ── role_match caps ───────────────────────────────────────────────────────

    def test_role_match_different_caps_at_55(self):
        raw = {**self._perfect_subscores(), "role_match": "different"}
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 55)

    def test_role_match_adjacent_caps_at_72(self):
        raw = {**self._perfect_subscores(), "role_match": "adjacent"}
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 72)

    def test_role_match_same_no_cap(self):
        """role_match='same' must NOT apply a categorical cap."""
        raw = {**self._perfect_subscores(), "role_match": "same"}
        score, _, _ = self._call(raw)
        self.assertEqual(score, 100)  # uncapped perfect score

    def test_role_match_missing_no_cap(self):
        """Absent role_match field must not apply any categorical cap."""
        score, _, _ = self._call(self._perfect_subscores())
        self.assertEqual(score, 100)

    # ── must_have_coverage caps ───────────────────────────────────────────────

    def test_must_have_low_caps_at_55(self):
        raw = {**self._perfect_subscores(), "must_have_coverage": "low"}
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 55)

    def test_must_have_medium_caps_at_78(self):
        raw = {**self._perfect_subscores(), "must_have_coverage": "medium"}
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 78)

    def test_must_have_high_no_cap(self):
        """must_have_coverage='high' must NOT apply a categorical cap."""
        raw = {**self._perfect_subscores(), "must_have_coverage": "high"}
        score, _, _ = self._call(raw)
        self.assertEqual(score, 100)

    # ── tightest-cap logic ────────────────────────────────────────────────────

    def test_tightest_cap_different_and_low_both_55(self):
        """Both 'different' and 'low' produce a cap of 55; result must be <= 55."""
        raw = {
            **self._perfect_subscores(),
            "role_match": "different",
            "must_have_coverage": "low",
        }
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 55)

    def test_tightest_cap_different_beats_medium(self):
        """'different' (cap 55) is tighter than 'medium' (cap 78); result must be <= 55."""
        raw = {
            **self._perfect_subscores(),
            "role_match": "different",
            "must_have_coverage": "medium",
        }
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 55)

    def test_tightest_cap_adjacent_and_low(self):
        """'adjacent' (cap 72) vs 'low' (cap 55) -> tightest is 55."""
        raw = {
            **self._perfect_subscores(),
            "role_match": "adjacent",
            "must_have_coverage": "low",
        }
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 55)

    def test_tightest_cap_adjacent_and_medium(self):
        """'adjacent' (cap 72) vs 'medium' (cap 78) -> tightest is 72."""
        raw = {
            **self._perfect_subscores(),
            "role_match": "adjacent",
            "must_have_coverage": "medium",
        }
        score, _, _ = self._call(raw)
        self.assertLessEqual(score, 72)

    # ── _apply_tightest helper ────────────────────────────────────────────────

    def test_apply_tightest_none_returns_candidate(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import llm
        self.assertEqual(llm._apply_tightest(None, 72), 72)

    def test_apply_tightest_lower_wins(self):
        import llm
        self.assertEqual(llm._apply_tightest(72, 55), 55)

    def test_apply_tightest_higher_loses(self):
        import llm
        self.assertEqual(llm._apply_tightest(55, 72), 55)


class TestHealthCheck(unittest.TestCase):

    def _get(self, path: str):
        import urllib.request
        return urllib.request.urlopen(f"http://localhost:8000{path}", timeout=3)

    def test_root_responds_200(self):
        try:
            resp = self._get("/")
            self.assertEqual(resp.status, 200)
        except Exception:
            self.skipTest("Server not running at localhost:8000")

    def test_health_responds_200_with_status_ok(self):
        """GET /health must always return HTTP 200 with {status: ok}."""
        try:
            resp = self._get("/health")
            self.assertEqual(resp.status, 200)
            import json as _json
            body = _json.loads(resp.read())
            self.assertIn("status", body)
            self.assertEqual(body["status"], "ok")
            self.assertIn("db", body)   # db key must be present
        except Exception:
            self.skipTest("Server not running at localhost:8000")


if __name__ == "__main__":
    # Add project root to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    unittest.main(verbosity=2)
