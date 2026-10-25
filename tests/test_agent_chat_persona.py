"""Exercise the real JS renderer through PyYAML and the bridge's preset validator."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

from test_agent_chat import dsh

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get("AGENT_CHAT_TEST_NODE") or shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is required for cross-runtime role rendering tests")
class PersonaTests(unittest.TestCase):
    def render(self, role=None):
        code = """
import fs from 'node:fs';
import {renderPreset, defaultRole} from './scripts/setup_agent_chat_dsh.mjs';
const role = JSON.parse(fs.readFileSync(0, 'utf8')) ?? fs.readFileSync(defaultRole, 'utf8');
const template = fs.readFileSync('./dsh/agent-chat/preset.patch.yml', 'utf8');
process.stdout.write(renderPreset(template, role));
"""
        result = subprocess.run([NODE, "--input-type=module", "-e", code], cwd=ROOT,
                                input=json.dumps(role), encoding="utf-8", capture_output=True,
                                check=True, timeout=15)
        rows = yaml.safe_load(result.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["insert"]), 1)
        plugins = rows[0]["insert"][0]["config"]["plugins"]
        self.assertEqual(len(plugins), 3)
        dsh.validate_preset(yaml.safe_dump(plugins, allow_unicode=True))
        return plugins[1]["config"]["prefix"]

    def test_default_card_is_complete_and_guarded(self):
        prefix = self.render()
        card = (ROOT / "roles/古户绘梨花.md").read_text(encoding="utf-8").strip()
        self.assertTrue(prefix.endswith(card))
        self.assertIn("你没有工具权限", prefix)
        self.assertNotIn("__AGENT_CHAT_ROLE_CARD__", prefix)

    def test_incomplete_persona_is_rejected(self):
        from test_agent_chat import composition
        rows = yaml.safe_load(composition())
        for value in [False, "true", None]:
            rows[1]["config"]["complete"] = value
            with self.assertRaises(dsh.BridgeError):
                dsh.validate_preset(yaml.safe_dump(rows, allow_unicode=True))

    def test_role_cannot_escape_yaml_scalar_even_with_unicode_line_breaks(self):
        card = '\ufeff# Test\r\n---\n- name: evil\n  config: !js process.exit()\n' \
               'quote: "x"\n\tindented\n$& ${ENV}\u0085next\u2028line\u2029end'
        prefix = self.render(card)
        expected = card.lstrip('\ufeff').replace('\r\n', '\n')
        for separator in ['\u0085', '\u2028', '\u2029']:
            expected = expected.replace(separator, '\n')
        self.assertTrue(prefix.endswith(expected))
