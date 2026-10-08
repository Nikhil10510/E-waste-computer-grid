import ast
import json
import urllib.request
from pathlib import Path

base = 'https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/'
source = urllib.request.urlopen(base + '_registry.py', timeout=20).read().decode()
registry = next(ast.literal_eval(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'registry' for t in n.targets))
specs = [
    ('chelsea.png', 'Domestic cat', ['tabby', 'tiger cat', 'Egyptian cat'], 'CC0'),
    ('coffee.png', 'Coffee cup', ['espresso', 'cup', 'coffee mug'], 'CC0'),
    ('brick.png', 'Brick wall', ['stone wall'], 'CC0'),
    ('camera.png', 'Person with camera', [], 'CC0'),
    ('astronaut.png', 'Astronaut portrait', [], 'Public domain'),
    ('coins.png', 'Coins', [], 'No known copyright restrictions'),
    ('grass.png', 'Grass texture', [], 'CC0'),
    ('gravel.png', 'Gravel texture', [], 'CC0'),
    ('clock_motion.png', 'Wall clock', ['wall clock', 'analog clock'], 'Public domain'),
    ('rocket.jpg', 'Rocket launch', ['missile', 'projectile', 'space shuttle'], 'Public domain'),
]
data = {'dataset_version': 1, 'source_version': 'scikit-image v0.25.2',
        'purpose': 'Ten genuine photographic inputs for integration; not a representative accuracy benchmark.',
        'source_documentation': base + '_fetchers.py',
        'images': [{'filename': f, 'source_url': base + f, 'sha256': registry['data/' + f],
                    'subject': subject, 'expected_labels': labels, 'license_note': lic + ' per upstream documentation'}
                   for f, subject, labels, lic in specs]}
Path('workloads/test-data/demo-manifest.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
print('Created manifest with ten pinned published checksums.')
