"""Run resumable preview, metadata, poster and semantic passes in order."""

from job_lock import single_job
import subprocess
import sys
from catalog import update_job


@single_job('integration')
def main():
    commands = [
        ['previews.py'],
        ['enrich.py', '--workers', '4'],
        ['posters.py'],
        ['semantic_index.py', '--batch-size', '16'],
    ]
    update_job('integration', 'running', 0, len(commands))
    for n, args in enumerate(commands, 1):
        print('integration stage ' + str(n) + ': ' + args[0], flush=True)
        p = subprocess.run([sys.executable, *args])
        if p.returncode:
            update_job(
                'integration', 'error', n - 1, len(commands), 'Stopped at ' + args[0]
            )
            return p.returncode
        update_job('integration', 'running', n, len(commands))
    update_job('integration', 'ready', len(commands), len(commands))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
