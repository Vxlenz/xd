"""Run the executable from a fresh working directory, with no source tree on sys.path."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='novadeck-build-check-') as temporary:
        report_path = Path(temporary) / 'report.json'
        result = subprocess.run([str(executable), '--self-test', str(report_path)], cwd=temporary, timeout=90)
        if not report_path.is_file():
            raise SystemExit('NovaDeck did not produce its build check report.')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        failed = [name for name, passed in report['checks'].items() if not passed]
        if result.returncode or not report['ok'] or not report['frozen'] or failed:
            raise SystemExit('Build check failed: ' + ', '.join(failed or ['process/frozen status']))
        print(f"Packaged NovaDeck: {len(report['checks'])} checks passed.")


if __name__ == '__main__':
    main()
