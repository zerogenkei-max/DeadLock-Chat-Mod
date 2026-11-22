"""Install or update the chat mod from the command line, with the same checks as the Windows customiser."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher import App, friendly_error, resolve_game

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--game-root', type=Path)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    data = args.data_dir or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Switchboard'
    app = App(data, resolve_game(data, args.game_root))
    try:
        app.install()
    except (ValueError, OSError) as exc:
        raise SystemExit(friendly_error(exc))
    print('Installed and connected:')
    for path in app.installed:
        print(path)
    print('Backups are in:', data / 'backups')
