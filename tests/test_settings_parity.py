"""tools/settings.py must agree with normalize() in switchboard_shared.vts."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from settings import SCHEMA, normalize  # noqa: E402

SHARED = ROOT / "src/panorama/scripts/switchboard_shared.vts"
NODE = shutil.which("node")
RUNNER = """
const fs=require('fs'),vm=require('vm');const c={module:{exports:{}}};vm.createContext(c);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);const M=c.module.exports;
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const out=cases.map(v=>{try{return {ok:M.normalize(v)};}catch(e){return {error:e.message};}});
process.stdout.write(JSON.stringify({results:out,defaults:M.defaults,numeric:M.numeric,enums:M.enums}));
"""

CASES = [
    {},
    {"version": 1},
    {"version": 1.0},
    {"version": 2},
    {"version": True},
    {"version": None},
    {"fontSize": 22.5},
    {"fontSize": 12.49},
    {"fontSize": -1e300},
    {"fontSize": 1e300},
    {"fontSize": "22px"},
    {"fontSize": True},
    {"width": 9000, "height": 1, "radius": 2.5, "fadeSeconds": 120.4},
    {"mode": "hidden", "anchor": "center", "nameMode": "both", "fadeMode": "always"},
    {"mode": "loud"},
    {"mode": 1},
    {"preset": "custom"},
    {"bold": True, "showPings": False},
    {"showPings": "false"},
    {"showPings": 0},
    {"textColor": "#ABCDEF"},
    {"textColor": "#abc"},
    {"textColor": "#abcdef\n"},
    {"textColor": "red"},
    {"objectiveWords": "  guardian , walker  "},
    {"objectiveWords": "﻿walker﻿"},
    {"objectiveWords": "\u001fwalker"},
    {"objectiveWords": "守护者,中路首领"},
    {"objectiveWords": "a" * 400},
    {"objectiveWords": "a" * 401},
    {"objectiveWords": "\U0001F600" * 200},
    {"objectiveWords": "\U0001F600" * 201},
    {"calloutWords": "<b>"},
    {"responseWords": "yes\r\nno"},
    {"responseWords": 5},
    {"unknown": 1, "artwork": True, "artworkOpacity": 50},
    {"textOpacity": 0},
]


@unittest.skipUnless(NODE, "node is required for the parity check")
class SettingsParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([NODE, "-e", RUNNER, str(SHARED)], input=json.dumps(CASES),
                              capture_output=True, text=True, encoding="utf-8", check=True)
        cls.js = json.loads(done.stdout)

    def test_schema_matches_shared_model(self):
        self.assertEqual(SCHEMA["defaults"], self.js["defaults"])
        self.assertEqual(SCHEMA["numeric"], self.js["numeric"])
        self.assertEqual(SCHEMA["enums"], self.js["enums"])

    def test_normalize_matches_for_every_case(self):
        for case, js in zip(CASES, self.js["results"]):
            with self.subTest(case=case):
                try:
                    py = {"ok": normalize(case)}
                except ValueError as error:
                    py = {"error": str(error)}
                self.assertEqual(py, js)

    def test_errors_use_british_spelling(self):
        with self.assertRaisesRegex(ValueError, "Unrecognised mode"):
            normalize({"mode": "loud"})

    def test_non_object_rejected(self):
        for value in ([], "x", None, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize(value)


if __name__ == "__main__":
    unittest.main()
