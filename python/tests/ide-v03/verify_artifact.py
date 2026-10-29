"""Pin IDE evidence to the exact final wheel and unchanged installed bytes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    result_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / '.work/ide-v03-results.json'
    result = json.loads(result_path.read_text(encoding='utf-8'))
    assert result['status'] == 'passed', 'IDE phase has not passed'
    wheel = ROOT / 'dist/v0.3/minebridge-0.3.0-py3-none-any.whl'
    package = Path(result['config']['installedPackage']).resolve()
    assert os.path.samefile(sys.executable, result['config']['python'])
    hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if not name.startswith('minebridge/') or name.endswith('/'):
                    continue
                relative = name.removeprefix('minebridge/')
                installed = package / relative
                data = archive.read(name)
                assert installed.read_bytes() == data, f'Installed bytes differ: {name}'
                hashes[name] = hashlib.sha256(data).hexdigest()
        assert hashes and 'minebridge/py.typed' in hashes
        for group in ('catalogs', 'signatures'):
            for item in result[group].values():
                for definition in item['definitions']:
                    relative = Path(definition).resolve().relative_to(package).as_posix()
                    assert 'minebridge/' + relative in hashes, definition
        result['artifactValidation'] = {
            'status': 'passed',
            'wheel': str(wheel),
            'wheelSha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'installedPackageFilesCompared': len(hashes),
            'installedFileSha256': hashes,
            'helperSha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted(Path(__file__).parent.iterdir()) if path.is_file()},
        }
    except BaseException as error:
        result['status'] = 'failed'
        result['artifactValidation'] = {'status': 'failed', 'error': str(error)}
        raise
    finally:
        result_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'IDE artifact verified: {len(hashes)} installed package files match final wheel')


if __name__ == '__main__':
    main()
