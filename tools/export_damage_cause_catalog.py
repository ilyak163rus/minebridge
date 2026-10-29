"""Export enum names from the pinned Paper API class file using the pinned javap."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    toolchain = json.loads((ROOT / '.tools/t02-toolchain.json').read_text(encoding='utf-8'))
    candidates = list((ROOT / '.tools/gradle-cache/caches/modules-2/files-2.1/io.papermc.paper/paper-api/26.2.build.133-stable').rglob('*.jar'))
    candidates = [path for path in candidates if not path.name.endswith(('-sources.jar', '-javadoc.jar'))]
    if len(candidates) != 1:
        raise SystemExit('Expected exactly one pinned API133 JAR')
    jar = candidates[0]
    enum_class = 'org.bukkit.event.entity.EntityDamageEvent$DamageCause'
    result = subprocess.run([str(Path(toolchain['javaHome']) / 'bin/javap.exe'), '-classpath', str(jar), enum_class],
                            check=True, capture_output=True, text=True, encoding='utf-8')
    names = re.findall(r'public static final org\.bukkit\.event\.entity\.EntityDamageEvent\$DamageCause ([A-Z_]+);', result.stdout)
    if not names or len(names) != len(set(names)):
        raise SystemExit('Invalid native DamageCause export')
    doc = {'schemaVersion': 1, 'minecraft': '26.2', 'paperBuild': 133, 'sourceClass': enum_class,
           'apiSha256': hashlib.sha256(jar.read_bytes()).hexdigest(), 'values': names}
    encoded = json.dumps(doc, ensure_ascii=True, indent=2) + '\n'
    target = ROOT / 'catalogs/paper-26.2-build133-damage-causes.json'
    if args.check:
        if target.read_text(encoding='utf-8') != encoded:
            raise SystemExit('DamageCause catalog differs from pinned API133')
    else:
        target.write_text(encoded, encoding='utf-8')
    print(f'{len(names)} native DamageCause values; API {doc["apiSha256"]}')


if __name__ == '__main__':
    main()
