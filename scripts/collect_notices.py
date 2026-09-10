"""Collect the licenses of the frozen runtime from installed wheel metadata."""
from importlib import metadata
from pathlib import Path
import sys


def collect(engine: Path, output: Path) -> None:
    bundled = []
    for path in sorted((engine / '_internal').glob('*.dist-info/METADATA')):
        from email.parser import Parser
        info = Parser().parsestr(path.read_text())
        bundled.append(info['Name'])
    bundled.append('pyinstaller')  # Bootloader distribution exception.
    parts = ['PhotoDesk — Third-party notices\n\n'
             'PhotoDesk includes the following third-party components. Their licenses\n'
             'apply to those components. PhotoDesk application source is not distributed.\n']
    for name in sorted(set(bundled), key=str.casefold):
        dist = metadata.distribution(name)
        parts.append(f'\n{"=" * 72}\n{name} {dist.version}\n')
        for key in ('License-Expression', 'Home-page', 'Project-URL'):
            for value in dist.metadata.get_all(key, []):
                parts.append(f'{key}: {value}\n')
        found = False
        for path in dist.files or []:
            if any(token in path.name.upper() for token in ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')):
                actual = dist.locate_file(path)
                if actual.is_file():
                    parts.append(f'\n{path.name}\n{actual.read_text(errors="replace")}\n')
                    found = True
        if not found:
            parts.append('\n' + (dist.metadata.get('License') or '\n'.join(
                v for v in dist.metadata.get_all('Classifier', []) if v.startswith('License ::')) or
                'See the component project for its license.') + '\n')
    candidates = [Path(sys.base_prefix) / 'lib/python3.12/LICENSE.txt', Path(sys.base_prefix) / 'LICENSE.txt']
    python_license = next((p for p in candidates if p.is_file()), None)
    if python_license is None:
        raise SystemExit('The embedded Python license was not found; refusing to omit it.')
    parts.append(f'\n{"=" * 72}\nCPython {sys.version.split()[0]}\n{python_license.read_text()}\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(''.join(parts))
    print(f'Collected notices for {len(set(bundled))} components and CPython.')


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    collect(root / 'build/engine/photo-engine', root / 'build/THIRD_PARTY_NOTICES.txt')
