# Publishing

Update the existing listing only: https://gamebanana.com/mods/733556. Never
create a new listing or ticket. Check https://gamebanana.com/wikis/2175 first.

1. Bump `VERSION` in `tools/switchboard_version.py`.
2. If Deadlock updated, run `python tools/check_compat.py --game-dir <Deadlock folder> --game <build> --steam <id>`.
   It only reads the game files and refreshes `research/compatibility.json`.
3. Run the tests:
   `python -m unittest discover -s tests -p "test_*.py"` and
   `node --test tests/runtime.test.js`.
4. If `launcher.py`, `web/` or the build tools changed, rebuild the Windows
   customiser: `.venv\Scripts\python tools/package_exe.py` (set up the venv from
   `requirements-dev.txt`).
5. Run `python tools/release.py`. The Mod ZIP holds only the VPK, README,
   LICENSE, THIRD_PARTY, CHANGELOG and mod.json.
6. Set `SWITCHBOARD_PRIVATE_WORDS` to your Windows username, then run
   `.venv\Scripts\python tools/audit_release.py --token-file <your token file>`.
   It has to pass with the token file given.
7. Upload only the Mod ZIP to GameBanana. Source and Windows ZIPs stay local;
   the editable source is published in this project's public GitHub repository.
   The Windows customiser goes out on request through Discord (genkei_).
8. Update the version, description and credits. Credit OpenAI Codex / ChatGPT
   and Anthropic Claude for the code, and say the screenshots are real captures
   (see `gallery/ASSETS.md`).
9. Post an update with patch notes in my own voice, thanking the people who
   gave feedback. Don't claim a fix I haven't tested.
10. Open the page signed out and check the version, the single download and the
   description.
