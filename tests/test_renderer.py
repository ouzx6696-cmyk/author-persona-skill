# -*- coding: utf-8 -*-
"""Renderer: JSON block extraction, single-source composition, public sanitization."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from author_persona_skill.report.renderer import (
    _PUBLIC_EVIDENCE_PLACEHOLDER,
    _compose_single_source,
    extract_json_block,
    render_report_outputs,
    REPORT_SCHEMA_VERSION,
)

from tests import _fixtures as fx


class JsonBlockTest(unittest.TestCase):

    def test_takes_the_last_fenced_block(self):
        text = '正文\n\n```json\n{"a": 1}\n```\n\n中间\n\n```json\n{"b": 2}\n```\n'
        prose, data = extract_json_block(text)
        self.assertEqual(data, {"b": 2})
        self.assertIn("中间", prose)
        # The selected machine block is removed from the prose; any earlier
        # example block is the author's own content and stays.
        self.assertNotIn('{"b": 2}', prose)
        self.assertIn('{"a": 1}', prose)

    def test_naked_json_with_technique_cards_is_recovered(self):
        text = '正文\n\n{"technique_cards": [], "thinking_layer": {}}'
        _, data = extract_json_block(text)
        self.assertEqual(data["technique_cards"], [])

    def test_non_object_payload_is_treated_as_missing(self):
        _, data = extract_json_block('正文\n\n```json\n[1, 2, 3]\n```\n')
        self.assertIsNone(data)

    def test_invalid_json_returns_prose_only(self):
        prose, data = extract_json_block("正文\n\n```json\n{不是合法 JSON\n```\n")
        self.assertIsNone(data)
        self.assertIn("正文", prose)


class SingleSourceTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()
        cls.prose, cls.data = extract_json_block(fx.valid_response(cls.prep))

    def test_parts_0_2_3_are_rendered_from_json(self):
        composed = _compose_single_source(self.prose, self.data)
        self.assertIn("〇.1 定位", composed)
        self.assertIn(self.data["technique_cards"][0]["name"], composed)
        self.assertIn(self.data["thinking_layer"]["closure"], composed)
        # LLM-written part 0 body must not survive.
        self.assertNotIn("本部分正文由", composed)

    def test_missing_heading_fails_closed(self):
        broken = self.prose.replace("## 第三部分", "第三部分（不是标题行）")
        with self.assertRaises(ValueError):
            _compose_single_source(broken, self.data)

    def test_missing_json_fails_closed(self):
        with self.assertRaises(ValueError):
            _compose_single_source(self.prose, None)


class PublicArtifactTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.prep = fx.prepared()
        cls.prose, cls.data = extract_json_block(fx.valid_response(cls.prep))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rendered = render_report_outputs(
            prose_markdown=cls.prose, parsed_json=cls.data, prepare_result=cls.prep,
            output_dir=Path(cls.tmp.name), base_name="渲染报告",
            validation={"schema": "passed", "desensitization": "passed",
                        "numeric_audit": {"status": "passed"}, "warnings": []},
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_evidence_bodies_are_hidden(self):
        markdown = self.rendered["full_markdown"]
        self.assertIn(_PUBLIC_EVIDENCE_PLACEHOLDER, markdown)
        for unit in self.prep["evidence_store_ids"].values():
            self.assertNotIn(unit["text"], markdown)

    def test_headers_use_work_id_not_real_identity(self):
        markdown = self.rendered["full_markdown"]
        self.assertNotIn("测试书", markdown)
        self.assertNotIn("测试作者", markdown)
        self.assertIn(self.rendered["report_json"]["meta"]["work_id"], markdown)

    def test_public_json_drops_speakers_and_raw_quotes(self):
        blob = json.dumps(self.rendered["report_json"], ensure_ascii=False)
        for speaker in self.prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)
        self.assertIn(_PUBLIC_EVIDENCE_PLACEHOLDER, blob)

    def test_public_mapping_has_neutral_keys_only(self):
        for key in self.rendered["report_json"]["desensitization_map"]:
            self.assertTrue(key.startswith("候选原型_"), key)

    def test_files_are_written_and_manifest_is_public(self):
        saved = self.rendered["files_saved"]
        for key in ("report_md_path", "report_json_path", "manifest_path"):
            self.assertTrue(Path(saved[key]).is_file(), key)
        manifest = json.loads(Path(saved["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], REPORT_SCHEMA_VERSION)
        self.assertNotIn("测试书", json.dumps(manifest, ensure_ascii=False))

    def test_malformed_placeholder_is_rejected(self):
        broken = self.prose.replace("### 1.1 小节标题", f"### 1.1 小节标题\n[{_PUBLIC_EVIDENCE_PLACEHOLDER} 裸文本。")
        with self.assertRaises(ValueError):
            render_report_outputs(
                prose_markdown=broken, parsed_json=self.data, prepare_result=self.prep,
                output_dir=Path(self.tmp.name), base_name="坏渲染",
            )

    def test_claims_are_sanitized_like_every_other_public_field(self):
        data = json.loads(json.dumps(self.data))
        data["claims"] = [{"claim_id": "CL1", "statement": "苏疏的短句推进。",
                           "evidence_refs": ["E0001"], "confidence": 0.9}]
        rendered = render_report_outputs(
            prose_markdown=self.prose, parsed_json=data, prepare_result=self.prep,
            base_name="claims 渲染",
        )
        self.assertNotIn("苏疏", json.dumps(rendered["report_json"], ensure_ascii=False))


class RawModeTest(unittest.TestCase):

    def test_desensitize_off_keeps_identity_and_keeps_evidence_visible(self):
        """`raw` is the explicit private mode: no noun mapping, quotes intact.

        Structural trimming (speaker lists, sample quotes) still applies to the
        machine sidecar even here, so the raw artifact is not a corpus dump.
        """
        prep = fx.prepared(key="raw-mode", options={"desensitize": False})
        prose, data = extract_json_block(fx.valid_response(prep))
        rendered = render_report_outputs(
            prose_markdown=prose, parsed_json=data, prepare_result=prep, base_name="原始报告")
        markdown = rendered["full_markdown"]
        self.assertEqual(rendered["report_json"]["artifact_policy"], "raw")
        self.assertIn("测试书", markdown)
        self.assertNotIn(_PUBLIC_EVIDENCE_PLACEHOLDER, markdown)
        blob = json.dumps(rendered["report_json"], ensure_ascii=False)
        for speaker in prep["quantitative_features"]["dialogue_features"]["high_confidence_speakers"]:
            self.assertNotIn(speaker["name"], blob)


if __name__ == "__main__":
    unittest.main()
