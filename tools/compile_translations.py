"""Generate PO/MO from the active JSON catalogue; requires GNU msgfmt."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1] / 'nanza'
catalogue = json.loads((root / 'translations.json').read_text(encoding='utf-8'))
for language in ('en', 'ar'):
    path = root / 'locale' / language / 'LC_MESSAGES' / 'django.po'
    path.parent.mkdir(parents=True, exist_ok=True)
    plural = ('nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5;'
              if language == 'ar' else 'nplurals=2; plural=(n != 1);')
    header = (f'Project-Id-Version: Nanza\nLanguage: {language}\nMIME-Version: 1.0\n'
              'Content-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n'
              f'Plural-Forms: {plural}\n')
    output = 'msgid ""\nmsgstr ' + json.dumps(header, ensure_ascii=False) + '\n\n'
    for source, translated in sorted(catalogue[language].items()):
        if source:
            output += 'msgid ' + json.dumps(source, ensure_ascii=False) + '\nmsgstr ' + json.dumps(translated, ensure_ascii=False) + '\n\n'
    path.write_text(output, encoding='utf-8')
    subprocess.run(['msgfmt', '--check-format', '-o', str(path.with_suffix('.mo')), str(path)], check=True)
