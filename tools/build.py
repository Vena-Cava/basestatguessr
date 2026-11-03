#!/usr/bin/env python3
"""
BaseStatGuessr data builder.

Builds data/game-data.js and data/sprites.js from:
  * your fangame PBS files   (the list of Pokémon/forms, sprites, categories, flags)
  * PokéAPI's data           (official base stats and types; these win when they exist)

Anything PokéAPI doesn't have (e.g. brand-new Megas it hasn't added yet) keeps the
stats from your PBS files. A report of every difference is written to tools/stat-report.md.

Usage (from the repo root):
    pip install pillow
    python tools/build.py
Options:
    --pbs DIR        folder with your PBS files    (default: tools/fangame/PBS)
    --sprites DIR    folder with Front sprites      (default: tools/fangame/Front)
    --offline        skip PokéAPI and use your PBS stats only
    --refresh        re-download PokéAPI data even if cached
"""
import argparse, base64, csv, glob, io, json, os, re, secrets, sys, unicodedata, urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'tools', '.cache')
POKEAPI_CSV = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
CSV_FILES = ['pokemon.csv', 'pokemon_stats.csv', 'pokemon_types.csv', 'types.csv', 'pokemon_species_names.csv']
ENGLISH = '9'
STAT_IDS = {'1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5}  # hp atk def spa spd spe
# Known errors in the fangame files, used only when PokéAPI has no entry (or with --offline).
OVERRIDES = {'METAGROSS_1': [80, 145, 150, 105, 110, 110]}  # Mega Metagross had Mega Salamence's stats
# Forms taken from PokéAPI even though your PBS files don't have them.
# PokéAPI entry -> (name shown in the game, base species ID in your PBS, sprite ID to use, evolution stage)
EXTRAS = {
    'pikachu-starter': ('Partner Pikachu', 'PIKACHU', 'PIKACHU', 'single'),
    'eevee-starter':   ('Partner Eevee',   'EEVEE',   'EEVEE',   'single'),
}
REGION = {'alola': 'alolan', 'galar': 'galarian', 'hisui': 'hisuian', 'paldea': 'paldean'}

def norm(s):
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower().replace('♀', 'f').replace('♂', 'm')
    return re.sub(r'[^a-z0-9]', '', s)

# ---------------------------------------------------------------- fangame PBS
def pbs_blocks(path):
    cur = None
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.rstrip('\n')
            m = re.match(r'^\[(.+)\]\s*$', line)
            if m:
                if cur: yield cur
                cur = {'_id': m.group(1).strip()}
            elif cur is not None and '=' in line and not line.lstrip().startswith('#'):
                k, v = line.split('=', 1); cur[k.strip()] = v.strip()
    if cur: yield cur

def load_pbs(folder):
    species, forms = {}, []
    files = sorted(glob.glob(os.path.join(folder, 'pokemon*.txt')))
    if not files: sys.exit(f'No pokemon*.txt PBS files found in {folder}')
    for p in files:
        name = os.path.basename(p).lower()
        if 'metrics' in name: continue
        for b in pbs_blocks(p):
            if 'forms' in name: forms.append(b)
            elif 'BaseStats' in b and 'Name' in b: species[b['_id']] = b
    print(f'PBS: {len(species)} species, {len(forms)} form entries from {len(files)} files')
    return species, forms

def std(bs):  # PBS order HP,Atk,Def,Spe,SpA,SpD -> HP,Atk,Def,SpA,SpD,Spe
    e = [int(x) for x in bs.split(',')]
    return [e[0], e[1], e[2], e[4], e[5], e[3]]

def evos(s):
    p = [x.strip() for x in s.split(',')] if s else []
    return [(p[i], p[i + 1]) for i in range(0, len(p) - 2, 3)]

def build_entries(species, forms):
    prevo = {t for b in list(species.values()) + forms for t, _ in evos(b.get('Evolutions', ''))}
    def stage(sp, evostr, mega):
        he = (not mega) and any(m != 'None' for _, m in evos(evostr))
        hp = sp in prevo
        return 'middle' if hp and he else 'final' if hp else 'base' if he else 'single'
    def flags(b): return {x.strip() for x in b.get('Flags', '').split(',')}
    out = []
    def add(id_, name, b, f, bs, formcat, mega, rawform):
        fl = flags(b)
        out.append(dict(
            n=name, s=b['Name'], g=int(b.get('Generation', 0) or 0),
            t=(f or b).get('Types', b['Types']).split(','), st=std(bs), form=formcat,
            stage=stage(id_.split('_')[0], (f or {}).get('Evolutions', b.get('Evolutions', '')), mega),
            leg=1 if fl & {'Legendary', 'Mythical'} else 0, ubp=1 if fl & {'UltraBeast', 'Paradox'} else 0,
            cat=(f or {}).get('Category', b.get('Category', '')), id=id_, rawform=rawform, src='fangame'))
        out[-1]['fan_st'] = list(out[-1]['st']); out[-1]['fan_t'] = list(out[-1]['t'])
    for k, b in species.items():
        add(k, b['Name'], b, None, b['BaseStats'], 'base', False, '')
    seen = set()
    for f in forms:
        if ',' not in f['_id']: continue
        sp, idx = [x.strip() for x in f['_id'].split(',', 1)]
        base = species.get(sp); fn = f.get('FormName')
        if not base or 'BaseStats' not in f or not fn: continue
        bs = f['BaseStats']
        if bs == base['BaseStats'] or (sp, bs) in seen: continue
        seen.add((sp, bs)); name = base['Name']
        m = re.match(r'^(Alolan|Galarian|Hisuian|Paldean)(?: \((.+)\))?$', fn)
        if m:
            disp = f"{m.group(1)} {name}" + (f" ({m.group(2)})" if m.group(2) else ''); cat = 'regional'
        else:
            disp = fn if name in fn else f'{name} ({fn})'
            cat = 'mega' if fn.startswith(('Mega ', 'Primal ')) else 'alt'
        disp = re.sub(r' \((Original Color|Curly Form)\)$', '', disp).replace('Minior (Red Core)', 'Minior (Core Form)')
        add(f'{sp}_{idx}', disp, base, f, bs, cat, cat == 'mega', fn)
    return out

# ---------------------------------------------------------------- PokéAPI
def fetch_csvs(refresh):
    os.makedirs(CACHE, exist_ok=True)
    tables = {}
    for fn in CSV_FILES:
        path = os.path.join(CACHE, fn)
        if refresh or not os.path.exists(path):
            print(f'Downloading {fn} from PokéAPI…')
            req = urllib.request.Request(POKEAPI_CSV + fn, headers={'User-Agent': 'BaseStatGuessr-builder'})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, 'wb') as out: out.write(r.read())
        with open(path, encoding='utf-8') as f: tables[fn] = list(csv.DictReader(f))
    need = {'pokemon.csv': {'id', 'identifier', 'species_id', 'is_default'},
            'pokemon_stats.csv': {'pokemon_id', 'stat_id', 'base_stat'},
            'pokemon_types.csv': {'pokemon_id', 'type_id', 'slot'},
            'types.csv': {'id', 'identifier'},
            'pokemon_species_names.csv': {'pokemon_species_id', 'local_language_id', 'name'}}
    for fn, cols in need.items():
        have = set(tables[fn][0].keys()) if tables[fn] else set()
        if not cols <= have:
            sys.exit(f'PokéAPI {fn} is missing columns {cols - have}. Their format may have changed; try --offline.')
    return tables

def pokeapi_index(t):
    types = {r['id']: r['identifier'].upper() for r in t['types.csv']}
    stats = defaultdict(lambda: [None] * 6)
    for r in t['pokemon_stats.csv']:
        if r['stat_id'] in STAT_IDS: stats[r['pokemon_id']][STAT_IDS[r['stat_id']]] = int(r['base_stat'])
    ptypes = defaultdict(list)
    for r in sorted(t['pokemon_types.csv'], key=lambda r: int(r['slot'])): ptypes[r['pokemon_id']].append(types.get(r['type_id'], '?'))
    sp_name = {r['pokemon_species_id']: r['name'] for r in t['pokemon_species_names.csv'] if r['local_language_id'] == ENGLISH}
    by_species = defaultdict(list)  # normalized English species name -> list of varieties
    for r in t['pokemon.csv']:
        st = stats.get(r['id'])
        if not st or None in st: continue
        by_species[norm(sp_name.get(r['species_id'], r['identifier']))].append(dict(
            ident=r['identifier'], default=r['is_default'] == '1', st=st, t=ptypes[r['id']]))
    for v in by_species.values():  # species identifier = the default variety's identifier minus any suffix
        parts = [x['ident'].split('-') for x in v]
        n = 0
        while all(len(p) > n for p in parts) and len({p[n] for p in parts}) == 1: n += 1
        base = '-'.join(parts[0][:n]) if len(v) > 1 else v[0]['ident']
        for x in v:
            suf = x['ident'][len(base):].strip('-') if x['ident'].startswith(base) else x['ident']
            x['tok'] = {REGION.get(w, w) for w in suf.split('-') if w}
    return by_species

def form_tokens(entry):
    words = re.findall(r'[a-z0-9]+', entry['rawform'].lower())
    sp = set(re.findall(r'[a-z0-9]+', entry['s'].lower()))
    return {w for w in words if w not in sp and w not in {'form', 'forme', 'mode', 'size', 'cloak'}} or set(words)

def match(entries, by_species):
    groups = defaultdict(list)
    for e in entries: groups[norm(e['s'])].append(e)
    unmatched_api = []
    for key, es in groups.items():
        vars_ = by_species.get(key)
        if not vars_: continue
        used = set()
        base = next((e for e in es if e['form'] == 'base'), None)
        if base:
            # normally PokéAPI's default variety; a few species (e.g. Pumpkaboo) default to a different form than Essentials
            pick = next((v for v in vars_ if v['default']), vars_[0])
            if pick['st'] != base['st']:
                pick = next((v for v in vars_ if v['st'] == base['st']), pick)
            base['api'] = pick; used.add(pick['ident'])
        pairs = []
        for e in es:
            if e['form'] == 'base': continue
            ft = form_tokens(e)
            for v in vars_:
                if v['ident'] in used or not v['tok']: continue
                j = len(ft & v['tok']) / len(ft | v['tok']) + (0.01 if v['st'] == e['st'] else 0)
                if j >= 0.34: pairs.append((j, id(e), e, v))
        done = set()
        for j, _, e, v in sorted(pairs, key=lambda p: -p[0]):
            if id(e) in done or v['ident'] in used: continue
            e['api'] = v; used.add(v['ident']); done.add(id(e))
        known = {tuple(e['st']) for e in es} | {tuple(e['fan_st']) for e in es}  # same stats as something already in the game = a duplicate form, not missing
        unmatched_api += [v['ident'] for v in vars_ if v['ident'] not in used and tuple(v['st']) not in known and v['ident'] not in EXTRAS]
    return unmatched_api

# ---------------------------------------------------------------- sprites
def build_sprites(entries, folder, scramble):
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        sys.exit('Pillow is needed for sprites: pip install pillow')
    if not os.path.isdir(folder):
        print(f'No sprite folder at {folder}; building without sprites'); return {}
    files = {os.path.splitext(f)[0].upper(): os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.png')}
    def webp(im, **kw):
        b = io.BytesIO(); im.save(b, 'WEBP', method=4, **kw); return b.getvalue()
    out, missing = {}, []
    for e in entries:
        cands = [e['id']] + ([e['id'].split('_')[0] + '_FEMALE'] if '(Female)' in e['n'] else []) + ([e['sprite']] if e.get('sprite') else [])
        p = next((files[c.upper()] for c in cands if c.upper() in files), None)
        if not p: missing.append(e['n']); continue
        im = Image.open(p).convert('RGBA')
        if im.width >= im.height * 2: im = im.crop((0, 0, im.height, im.height))  # sprite strips: first frame
        bb = im.getbbox()
        if bb: im = im.crop(bb)
        s = max(im.size); c = Image.new('RGBA', (s, s)); c.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
        full = c.resize((112, 112), Image.NEAREST)
        blur = c.resize((8, 8), Image.BOX).resize((32, 32), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
        out[e['id']] = ['data:image/webp;base64,' + base64.b64encode(webp(blur, quality=80)).decode(),
                        scramble(webp(full, lossless=True))]
    print(f'Sprites: {len(out)} matched' + (f', missing: {", ".join(missing[:15])}' if missing else ''))
    return out

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pbs', default=os.path.join(ROOT, 'tools', 'fangame', 'PBS'))
    ap.add_argument('--sprites', default=os.path.join(ROOT, 'tools', 'fangame', 'Front'))
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    a = ap.parse_args()

    species, forms = load_pbs(a.pbs)
    entries = build_entries(species, forms)

    report = ['# Stat report', '', 'Generated by `tools/build.py`. Stats are HP/Atk/Def/SpA/SpD/Spe.', '']
    if a.offline:
        print('Offline: using fangame stats only'); report.append('Built offline: PokéAPI was not used.')
    else:
        by_species = pokeapi_index(fetch_csvs(a.refresh))
        unmatched_api = match(entries, by_species)
        diffs, gaps = [], []
        for e in entries:
            v = e.get('api')
            if not v: gaps.append(e); continue
            if v['st'] != e['st'] or (v['t'] and v['t'] != e['t']):
                diffs.append((e, v))
            e['st'] = v['st']
            if v['t']: e['t'] = v['t']
            e['src'] = 'pokeapi'
        api_by_ident = {v['ident']: v for vs in by_species.values() for v in vs}
        for ident, (name, sp, sprite, stg) in EXTRAS.items():
            v = api_by_ident.get(ident); b = species.get(sp)
            if not v or not b: print(f'Extra form {ident}: not found, skipped'); continue
            base = next(e for e in entries if e['id'] == sp)
            entries.append(dict(base, n=name, st=v['st'], t=v['t'] or base['t'], form='alt', stage=stg,
                                id=f'{sp}_{ident.split("-")[-1].upper()}', sprite=sprite, src='pokeapi-extra',
                                fan_st=v['st'], fan_t=v['t'] or base['t'], api=v))
        print(f'PokéAPI: {len(entries) - len(gaps)} matched, {len(diffs)} differ from your files, {len(gaps)} kept from your files')
        report += [f'## Your files differ from PokéAPI ({len(diffs)})', '',
                   'The game uses the PokéAPI values. If these are deliberate fangame changes, ignore them.', '',
                   '| Pokémon | Your files | PokéAPI | PokéAPI entry |', '|---|---|---|---|']
        for e, v in diffs:
            report.append(f"| {e['n']} | {'/'.join(map(str, e['fan_st']))} {' '.join(e['fan_t'])} | "
                          f"{'/'.join(map(str, v['st']))} {' '.join(v['t'])} | `{v['ident']}` |")
        report += ['', f'## Not found in PokéAPI, kept from your files ({len(gaps)})', '']
        report += [f"- {e['n']} ({'/'.join(map(str, e['st']))})" for e in gaps] or ['- none']
        report += ['', f'## In PokéAPI with different stats, but not in your files ({len(unmatched_api)})', '',
                   'Forms whose stats match one already in the game (e.g. Wash Rotom = Heat Rotom) are left out of this list.', '']
        report += [f'- `{x}`' for x in unmatched_api] or ['- none']

    for e in entries:
        if not e.get('api') and e['id'] in OVERRIDES: e['st'] = OVERRIDES[e['id']]
    key = secrets.token_hex(8)
    def scramble(b):
        k = key.encode(); return base64.b64encode(bytes(x ^ k[i % len(k)] for i, x in enumerate(b))).decode()
    sprites = build_sprites(entries, a.sprites, scramble)

    rows = [[e['n'], e['s'], e['g'], e['t'], e['st'], e['form'], e['stage'], e['leg'], e['ubp'], e['cat'], e['id']] for e in entries]
    os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
    with open(os.path.join(ROOT, 'data', 'game-data.js'), 'w', encoding='utf-8') as f:
        f.write('// Generated by tools/build.py; do not edit by hand.\n')
        f.write('window.BSG_DATA=' + json.dumps({'k': key, 'd': scramble(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode())}) + ';\n')
    with open(os.path.join(ROOT, 'data', 'sprites.js'), 'w', encoding='utf-8') as f:
        f.write('// Generated by tools/build.py; do not edit by hand.\n')
        f.write('window.BSG_SPRITES=' + json.dumps(sprites, separators=(',', ':')) + ';\n')
    # Data for the ranked-run server (worker/). Not scrambled: it never reaches players' browsers.
    wdir = os.path.join(ROOT, 'worker', 'src')
    if os.path.isdir(wdir):
        wdata = {'mons': [[e['id'], e['n'], e['s'], e['g'], e['t'], e['st'], e['form']] for e in entries],
                 'blur': {k: v[0] for k, v in sprites.items()}}
        with open(os.path.join(wdir, 'data.js'), 'w', encoding='utf-8') as f:
            f.write('// Generated by tools/build.py; do not edit by hand.\nexport default ' + json.dumps(wdata, ensure_ascii=False, separators=(',', ':')) + ';\n')
        print('Wrote worker/src/data.js (redeploy the worker to use it)')
    with open(os.path.join(ROOT, 'tools', 'stat-report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')
    print(f'Wrote data/game-data.js ({len(rows)} entries), data/sprites.js, tools/stat-report.md')

if __name__ == '__main__':
    main()
