# -*- coding: utf-8 -*-
"""Evidence store: chunking, anchor pool, quote verification, era derivation."""
from __future__ import annotations

import unittest

from author_persona_skill.distill.evidence import (
    MIN_QUOTE_CHARS,
    build_chunk_offsets,
    build_evidence_store,
    create_chunks,
    derive_evidence_era,
    enforce_evidence_reinforcement,
    extract_candidate_evidence_pool,
    normalize_quote,
    verify_all_cards_evidence,
    verify_evidence_item,
)

from tests import _fixtures as fx


class ChunkingTest(unittest.TestCase):

    def test_chunks_are_contiguous_and_lossless(self):
        text = fx.synthetic_corpus(chapters=3)
        chunks = create_chunks(text, chunk_size=500)
        self.assertEqual("".join(chunks[cid] for cid in sorted(chunks)), text)
        offsets = build_chunk_offsets(chunks)
        cursor = 0
        for cid in sorted(chunks):
            self.assertEqual(offsets[cid], cursor)
            cursor += len(chunks[cid])


class AnchorPoolTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()

    def test_pool_anchors_are_citable(self):
        for item in self.prep["evidence_pool"]:
            self.assertGreaterEqual(len(item["quote"].strip()), MIN_QUOTE_CHARS)
            self.assertIn(item["chunk_id"], self.prep["evidence_store"])
            self.assertTrue(item["evidence_id"].startswith("E"))

    def test_pool_spans_multiple_eras(self):
        eras = {item.get("era") for item in self.prep["evidence_pool"]}
        self.assertGreaterEqual(len(eras), 2, eras)

    def test_store_ids_snap_to_corpus(self):
        store = self.prep["evidence_store_ids"]
        self.assertTrue(store)
        for unit in store.values():
            self.assertIn(unit["text"], self.prep["evidence_store"][unit["chunk_id"]])

    def test_empty_chunks_produce_empty_pool(self):
        self.assertEqual(extract_candidate_evidence_pool({}), [])


class QuoteVerificationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.chunks = create_chunks(fx.synthetic_corpus(chapters=3), chunk_size=500)
        cls.sample_cid, cls.sample_text = next(iter(cls.chunks.items()))

    def test_exact_quote_is_valid(self):
        quote = self.sample_text.strip()[:20]
        status, cid = verify_evidence_item(quote, self.sample_cid, self.chunks)
        self.assertEqual((status, cid), ("valid", self.sample_cid))

    def test_wrong_chunk_id_is_fixed(self):
        quote = list(self.chunks.values())[-1].strip()[:20]
        status, cid = verify_evidence_item(quote, self.sample_cid, self.chunks)
        self.assertEqual(status, "fixed")
        self.assertNotEqual(cid, self.sample_cid)

    def test_short_quote_is_downgraded(self):
        status, _ = verify_evidence_item("短", self.sample_cid, self.chunks)
        self.assertEqual(status, "downgraded")

    def test_fabricated_quote_is_downgraded(self):
        status, _ = verify_evidence_item("此句绝不可能出现在语料之中。", self.sample_cid, self.chunks)
        self.assertEqual(status, "downgraded")

    def test_normalization_tolerates_punctuation_variants(self):
        raw = "“这是一句测试对话，”他说，“用来验证归一化匹配。”"
        chunks = {"c001": raw}
        self.assertEqual(verify_evidence_item(raw.replace("“", "\"").replace("”", "\""), "c001", chunks)[0], "valid")
        self.assertIn('"', normalize_quote(raw))

    def test_downgrade_lowers_card_confidence(self):
        cards = [{"id": "T01", "confidence": "high", "evidence": [
            {"chunk_id": self.sample_cid, "quote": "不存在的引文内容，用于验证降级。"}]}]
        verified, stats = verify_all_cards_evidence(cards, self.chunks)
        self.assertEqual(stats["downgraded"], 1)
        self.assertEqual(verified[0]["confidence"], "mid")
        self.assertEqual(verified[0]["evidence"][0]["verification_status"], "downgraded")


class EraDerivationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()

    def test_era_is_derived_from_corpus_not_declared(self):
        unit = next(iter(self.prep["evidence_store_ids"].values()))
        derived = derive_evidence_era(
            unit["text"], unit["chunk_id"], self.prep["evidence_store"],
            self.prep["era_map"], self.prep["era_spans"], self.prep["chunk_offsets"],
        )
        self.assertEqual(derived, unit["era"])

    def test_unknown_chunk_falls_back_to_era_map(self):
        cid = next(iter(self.prep["era_map"]))
        self.assertEqual(
            derive_evidence_era("", cid, self.prep["evidence_store"], self.prep["era_map"], [], {}),
            self.prep["era_map"][cid],
        )


class ReinforcementTest(unittest.TestCase):

    def test_definition_promising_punctuation_needs_it_in_quotes(self):
        cards = [{
            "id": "T01", "confidence": "high",
            "name": "破折号揭底", "definition": "以破折号插入补充说明。",
            "evidence": [{"quote": "一句不含该标点的引文内容。", "verification_status": "valid"}],
        }]
        issues = enforce_evidence_reinforcement(cards)
        self.assertTrue(issues)
        self.assertEqual(cards[0]["confidence"], "mid")


if __name__ == "__main__":
    unittest.main()
