#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_from_dashboard.py — apply a dashboard export JSON to the live site files.

Usage:
    python3 sync_from_dashboard.py <dashboard-export.json> [options]

Options:
    --dry-run        preview what would change without writing anything
    --write-uploads  write uploaded images (data URLs) from the JSON into assets/

The JSON is the file produced by the dashboard's Data tab → Download JSON
(contains: works, schedule, photos, uploads).

Updates in place:
    work.html        WORKS array + COUNT            (all works)
    all-works.html   grid cards                     (all works)
    index.html       works grid cards (first 8) + schedule teaser link + portraits array
    schedule.html    exhibitions/events list + ex-count (dedicated Schedule page)
    about.html       portraits array
    assets/i18n.js   German 'work.title.N' entries for works beyond No. 12

Every touched file is copied to .sync-backups/<timestamp>/ first.

Smart merge: for works whose title/description are unchanged, the site's
existing hand-written alt text and data-od-id are preserved; only new or
changed works get the generated "title — description" alt and a slug id
(leading article stripped, matching the site's convention).
"""

import argparse
import base64
import datetime
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------------
# helpers — equivalent of the dashboard's JS helpers
# ----------------------------------------------------------------------------


def esc(s):
    """HTML-escape (same as dashboard esc())."""
    return (str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def q1(s):
    """JS single-quoted string (same as dashboard q1())."""
    return (str(s) if s is not None else '').replace("'", "\\'").replace('\r', ' ').replace('\n', ' ')


def pad2(n):
    return '%02d' % int(n)


def slug(file):
    """Same as dashboard slug()."""
    base = os.path.basename(str(file or ''))
    base = re.sub(r'\.(svg|png|jpe?g|webp)$', '', base, flags=re.I)
    s = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')
    return s


def slug_id(file, n):
    """Dashboard slugId, then strip the leading article to match the site's
    data-od-id convention (work-card-door-for-winter, not work-card-a-door-...)."""
    s = slug(file) or ('work-' + pad2(n))
    s = re.sub(r'^work-\d+-', '', s) or ('work-' + pad2(n))
    s = re.sub(r'^(a|an|the)-', '', s)
    return s or ('work-' + pad2(n))


def alt_for(w):
    """Same as dashboard altFor()."""
    t = w.get('title') or 'Untitled'
    return t + (' — ' + w['desc'] if w.get('desc') else '')


def reindent(block, indent):
    """Prepend the given leading whitespace to every non-empty line."""
    if not indent:
        return block
    return '\n'.join((indent + ln) if ln.strip() else ln for ln in block.split('\n'))


def detect_indent(inner):
    """Leading whitespace of the first non-empty line (default 10 spaces)."""
    for ln in inner.split('\n'):
        if ln.strip():
            return ln[:len(ln) - len(ln.lstrip())]
    return '          '


# ----------------------------------------------------------------------------
# existing-content parsing (smart merge)
# ----------------------------------------------------------------------------

# work.html entry:  { n: 1, file: '...', title: '...', year: '...', alt: '...', desc: '...', ...
ENTRY_RE = re.compile(
    r"\{ n: (\d+), file: '[^']*',\s*title: '([^']*)',\s*year: '[^']*',\s*alt: '([^']*)',\s*desc: '([^']*)',")

# grid card:  n, data-od-id, aria-label="TITLE, YEAR" ... <img ... alt="ALT"
CARD_RE = re.compile(
    r'<a class="work-card" href="work\.html\?n=(\d+)" data-od-id="([^"]*)" aria-label="([^"]*), ([^"]*)"[\s\S]*?<img src="[^"]*" alt="([^"]*)"')


def existing_alt_map(text, source):
    """Map work n -> existing (alt[, id]) for unchanged works."""
    if source == 'works-js':
        m = {}
        for match in ENTRY_RE.finditer(text):
            m[int(match.group(1))] = (match.group(2), match.group(3), match.group(4))
        return m
    m = {}
    for match in CARD_RE.finditer(text):
        m[int(match.group(1))] = (match.group(2), match.group(3), match.group(4), match.group(5))
    return m


def merged_alt(w, alt_map, source):
    n = int(w.get('n', 0))
    ex = alt_map.get(n)
    if ex:
        if source == 'works-js':
            title, alt, desc = ex
            if title == (w.get('title') or '') and desc == (w.get('desc') or ''):
                return alt, None
        else:
            od_id, title, year, alt = ex
            if title == esc(w.get('title', '')) and year == esc(norm_year(w.get('year', ''))):
                return alt, od_id
    return alt_for(w), None


def work_line(w, alt):
    parts = [
        "n: %d" % int(w['n']),
        "file: '%s'" % q1(w.get('file', '')),
        "title: '%s'" % q1(w.get('title', '')),
        "year: '%s'" % q1(norm_year(w.get('year', ''))),
        "alt: '%s'" % q1(alt),
        "desc: '%s'" % q1(w.get('desc', '')),
        "titleDe: '%s'" % q1(w.get('titleDe', '')),
        "descDe: '%s'" % q1(w.get('descDe', '')),
    ]
    if w.get('video'):
        parts.append("video: '%s'" % q1(w['video']))
    return '    { ' + ', '.join(parts) + ' }'


# ----------------------------------------------------------------------------
# generators — column-0 lines; callers re-indent to the target block
# ----------------------------------------------------------------------------


def gen_works_js(works, alt_map):
    lines = []
    for w in works:
        alt, _ = merged_alt(w, alt_map, 'works-js')
        lines.append(work_line(w, alt))
    return '  const WORKS = [\n' + ',\n'.join(lines) + '\n  ];\n  const COUNT = WORKS.length;'


def gen_cards_html(works, prefix, alt_map):
    out = []
    for w in works:
        n = int(w['n'])
        alt, od_id = merged_alt(w, alt_map, 'cards')
        sid = od_id or (prefix + '-' + slug_id(w.get('file', ''), n))
        title = esc(w.get('title', ''))
        year = esc(norm_year(w.get('year', '')))
        file_ = esc(w.get('file', ''))
        out.append(
            '<li>\n'
            '  <a class="work-card" href="work.html?n=%d" data-od-id="%s" aria-label="%s, %s">\n'
            '    <figure class="work-figure">\n'
            '      <img src="%s" alt="%s" width="800" height="800">\n'
            '      <figcaption class="work-reveal">\n'
            '        <span class="work-reveal__index">No. %s</span>\n'
            '        <span class="work-reveal__title" data-i18n="work.title.%d">%s</span>\n'
            '        <span class="work-reveal__year">%s</span>\n'
            '      </figcaption>\n'
            '    </figure>\n'
            '    <p class="work-caption"><span class="wc-title" data-i18n="work.title.%d">%s</span><span class="wc-meta">%s</span></p>\n'
            '  </a>\n'
            '</li>'
            % (n, sid, title, year, file_, esc(alt), pad2(n), n, title, year, n, title, year)
        )
    return '\n'.join(out)


def norm_year(v):
    m = re.search(r'\d{4}', str(v or ''))
    return m.group(0) if m else str(v or '').strip()


def gen_schedule_html(schedule):
    # page order = dashboard drag & drop order (array order); year is display only
    s = list(schedule)
    if not s:
        return '<!-- no schedule entries -->'
    out = []
    for i, it in enumerate(s):
        period = ('<span class="ex-period">%s</span>' % esc(it.get('period', ''))) if (it.get('period') or '').strip() else ''
        out.append(
            '<li><span class="ex-year">%s</span>%s<span class="ex-name" data-i18n="ex.%d">%s</span><span class="ex-place">%s</span></li>'
            % (esc(norm_year(it.get('year', ''))), period, i + 1, esc(it.get('title', '')), esc(it.get('place', '')))
        )
    return '\n'.join(out)


def gen_photos_js(photos):
    arr = ["'%s'" % q1(p.get('file', '')) for p in photos]
    return 'const portraits = [' + ', '.join(arr) + '];'


def gen_i18n_entries(works):
    rows = []
    for w in works:
        n = int(w.get('n', 0))
        de = (w.get('titleDe') or '').strip()
        if n > 12 and de:
            rows.append("    'work.title.%d': '%s'," % (n, q1(de)))
    return rows


# ----------------------------------------------------------------------------
# block replacers — each returns (new_text, changed)
# ----------------------------------------------------------------------------


def update_works_js(text, works):
    alt_map = existing_alt_map(text, 'works-js')
    new = gen_works_js(works, alt_map)
    pat = re.compile(r'  const WORKS = \[.*?\n  \];\n  const COUNT = WORKS\.length;', re.S)
    m = pat.search(text)
    if not m:
        raise RuntimeError('WORKS array block not found')
    return text[:m.start()] + new + text[m.end():]


def update_grid(text, works, prefix):
    alt_map = existing_alt_map(text, 'cards')
    new = gen_cards_html(works, prefix, alt_map)
    pat = re.compile(r'(<ul class="works-grid" data-od-id="works-grid">\n)(.*?)(\n\s*</ul>)', re.S)
    m = pat.search(text)
    if not m:
        raise RuntimeError('works-grid block not found')
    indent = detect_indent(m.group(2))
    return text[:m.start()] + m.group(1) + reindent(new, indent) + m.group(3) + text[m.end():]


def update_exhibitions(text, schedule, od_id):
    new = gen_schedule_html(schedule)
    pat = re.compile(
        r'(<ul class="exhibitions reveal" data-od-id="%s">\n)(.*?)(\n\s*</ul>)' % re.escape(od_id), re.S)
    m = pat.search(text)
    if not m:
        raise RuntimeError('exhibitions block (%s) not found' % od_id)
    indent = detect_indent(m.group(2))
    return text[:m.start()] + m.group(1) + reindent(new, indent) + m.group(3) + text[m.end():]


def update_ex_count(text, count):
    pat = re.compile(r'(<span class="ex-count" data-od-id="ex-count">)\d+(</span>)')
    m = pat.search(text)
    if not m:
        return text, False
    new = m.group(1) + pad2(count) + m.group(2)
    return (text[:m.start()] + new + text[m.end():], m.group(0) != new)


def update_aw_count(text, count):
    """Update the '12 paintings' counter in all-works.html."""
    pat = re.compile(
        r'(<p class="aw-count" data-od-id="aw-count" data-i18n="aw\.count">)\d+(\s+paintings</p>)')
    m = pat.search(text)
    if not m:
        return text, False
    new = m.group(1) + str(count) + m.group(2)
    return (text[:m.start()] + new + text[m.end():], m.group(0) != new)


def update_index_works_meta(text, count):
    """Update the '8 selected' counter in index.html's works-meta."""
    pat = re.compile(
        r'(<p class="sec-meta" data-od-id="works-meta" data-i18n="works\.meta">'
        r'\d{4} — \d{4} · )\d+(\s+selected</p>)')
    m = pat.search(text)
    if not m:
        return text, False
    new = m.group(1) + str(count) + m.group(2)
    return (text[:m.start()] + new + text[m.end():], m.group(0) != new)


def update_portraits(text, photos):
    arr = ["'%s'" % q1(p.get('file', '')) for p in photos]
    body = ', '.join(arr)
    pat = re.compile(r'(const portraits = \[)[^\]]*(\])')
    m = pat.search(text)
    if not m:
        raise RuntimeError('portraits array not found')
    return text[:m.start()] + m.group(1) + body + m.group(2) + text[m.end():]


def update_i18n(text, works):
    """Update i18n dictionary for works beyond No. 12.
    Replaces existing entries with updated values, adds new ones,
    and removes entries for deleted works."""
    entries = {}  # n -> full line string
    for r in gen_i18n_entries(works):
        m = re.search(r"'work\.title\.(\d+)':", r)
        if m:
            entries[m.group(1)] = r
    if not entries:
        # No works beyond 12 — remove any leftover dashboard entries
        if 'added via dashboard' not in text:
            return text, False
        return _remove_i18n_dashboard_entries(text), True

    lines = text.split('\n')
    existing_keys = set()
    changed = False

    # Pass 1: update existing matching lines
    for i, ln in enumerate(lines):
        m = re.match(r"(\s*)('work\.title\.(\d+)':\s*)'.*',?", ln)
        if m and m.group(3) in entries:
            new_ln = m.group(1) + m.group(2) + "'%s'," % q1(
                [w for w in works if str(w.get('n','')) == m.group(3)][0].get('titleDe', ''))
            if lines[i] != new_ln:
                lines[i] = new_ln
                changed = True
            existing_keys.add(m.group(3))

    # Pass 2: remove entries for deleted works
    for i, ln in enumerate(lines):
        m = re.match(r"\s*'work\.title\.(\d+)':", ln)
        if m and int(m.group(1)) > 12 and m.group(1) not in entries:
            # Remove this line and any surrounding comment
            del lines[i]
            # Also remove preceding comment line if present
            if i > 0 and 'added via dashboard' in lines[i-1]:
                del lines[i-1]
            changed = True
            break  # reprocess after deletion

    # Pass 3: add new entries after the last existing work.title.N line
    new_entries = [(n, r) for n, r in entries.items() if n not in existing_keys]
    if new_entries:
        idx = None
        for i, ln in enumerate(lines):
            if re.match(r"\s*'work\.title\.\d+':", ln):
                idx = i
        if idx is None:
            raise RuntimeError('i18n.js: no work.title.N lines found')
        first_n = min(int(n) for n, _ in new_entries)
        parts = []
        if 'added via dashboard' not in text:
            parts.append("    // work titles %s+ (added via dashboard)" % first_n)
        rows = [r for _, r in sorted(new_entries)]
        insert = '\n' + '\n'.join(parts + rows)
        lines.insert(idx + 1, insert)
        changed = True

    if not changed:
        return text, False
    return '\n'.join(lines), True


def update_i18n_exhibitions(text, schedule):
    """Rebuild the 'ex.N' German dictionary lines from schedule order
    (page order = dashboard drag & drop order)."""
    de_by_pos = {}
    for i, it in enumerate(schedule):
        de = (it.get('titleDe') or '').strip()
        if de:
            de_by_pos[str(i + 1)] = q1(de)
    lines = text.split('\n')
    changed = False
    i = 0
    while i < len(lines):
        m = re.match(r"(\s*)('ex\.(\d+)':\s*)'.*',?", lines[i])
        if m:
            key = m.group(3)
            if key in de_by_pos:
                new_ln = m.group(1) + m.group(2) + "'%s'," % de_by_pos.pop(key)
                if lines[i] != new_ln:
                    lines[i] = new_ln
                    changed = True
            else:
                del lines[i]
                changed = True
                continue
        i += 1
    if de_by_pos:
        idx = None
        for j, ln in enumerate(lines):
            if re.match(r"\s*'ex\.\d+':", ln):
                idx = j
        if idx is None:
            raise RuntimeError('i18n.js: no ex.N lines found')
        rows = ["    'ex.%s': '%s'," % (k, de_by_pos[k]) for k in sorted(de_by_pos, key=lambda k: int(k))]
        lines.insert(idx + 1, '\n' + '\n'.join(rows))
        changed = True
    if not changed:
        return text, False
    return '\n'.join(lines), True


def _remove_i18n_dashboard_entries(text):
    """Remove all dashboard-added i18n entries when works <= 12."""
    lines = text.split('\n')
    out = []
    skip = False
    for ln in lines:
        if 'added via dashboard' in ln:
            skip = True
            continue
        if skip:
            m = re.match(r"\s*'work\.title\.\d+':", ln)
            if m and int(re.search(r'\d+', ln).group()) > 12:
                continue
            skip = False
        out.append(ln)
    return '\n'.join(out)


# ----------------------------------------------------------------------------
# uploads
# ----------------------------------------------------------------------------


def write_uploads(uploads, dry_run, root=None):
    rdir = os.path.abspath(root) if root else ROOT
    written = []
    for key, data in (uploads or {}).items():
        if not isinstance(data, str) or not data.startswith('data:'):
            continue
        m = re.match(r'data:[^;,]*;base64,(.*)$', data, re.S)
        if not m:
            continue
        rel = key.lstrip('/')
        dst = os.path.normpath(os.path.join(rdir, rel))
        if not dst.startswith(rdir):
            print('  !! upload path escapes project root, skipped:', key)
            continue
        try:
            raw = base64.b64decode(m.group(1))
        except Exception:
            print('  !! could not decode upload:', key)
            continue
        if not dry_run:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(raw)
        written.append((rel, len(raw)))
    return written


# ----------------------------------------------------------------------------
# reusable API — returns a JSON-serializable summary (used by serve.py too)
# ----------------------------------------------------------------------------


def apply_data(data, dry_run=False, write_upload_files=True, output_dir=None):
    """Apply dashboard state (works/schedule/photos/uploads) to the site files.

    Returns a JSON-serializable dict; never raises for content issues —
    per-file failures are reported in `files` and `missing`.
    """
    works = data.get('works') or []
    schedule = data.get('schedule') or []
    photos = data.get('photos') or []
    uploads = data.get('uploads') or {}
    # prefix all output paths (used for staging)
    root = ROOT if not output_dir else os.path.join(ROOT, output_dir)
    if output_dir:
        os.makedirs(root, exist_ok=True)

    if not isinstance(works, list) or not works:
        return {'ok': False, 'error': 'JSON has no usable works array'}
    if not isinstance(schedule, list):
        schedule = []
    if not isinstance(photos, list):
        photos = []
    if not isinstance(uploads, dict):
        uploads = {}

    # Re-number works by array position (dashboard order is the source of truth)
    for i, w in enumerate(works):
        w['n'] = i + 1

    files = []
    pending = {}  # rel -> text (batched operations for same file)

    def apply(rel, fn, *fn_args):
        path = os.path.join(root, rel)
        source_path = os.path.join(ROOT, rel) if output_dir else path
        if not os.path.exists(path):
            if not os.path.exists(source_path):
                files.append({'file': rel, 'status': 'not found'})
                return
            # boostrap from source (first staging sync)
            text = open(source_path, encoding='utf-8').read()
            if not dry_run:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, 'w', encoding='utf-8').write(text)
            files.append({'file': rel, 'status': 'bootstrapped'})
        else:
            text = pending.get(rel) or open(path, encoding='utf-8').read()
        try:
            result = fn(text, *fn_args)
            if isinstance(result, tuple):
                new_text, changed = result
            else:
                new_text, changed = result, result != text
        except RuntimeError as e:
            files.append({'file': rel, 'status': 'skipped: %s' % e})
            return
        pending[rel] = new_text

    def flush_pending():
        for rel, text in pending.items():
            path = os.path.join(root, rel)
            orig = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
            if text == orig:
                files.append({'file': rel, 'status': 'no change'})
                continue
            files.append({'file': rel, 'status': 'updated'})
            if not dry_run:
                open(path, 'w', encoding='utf-8').write(text)

    apply('work.html', update_works_js, works)
    apply('all-works.html', update_grid, works, 'aw-card')
    apply('all-works.html', update_aw_count, len(works))
    top8 = [{**w, 'n': i + 1} for i, w in enumerate(works[:8])]
    apply('index.html', update_grid, top8, 'work-card')
    apply('index.html', update_index_works_meta, min(8, len(works)))
    apply('index.html', update_portraits, photos)
    apply('schedule.html', update_exhibitions, schedule, 'schedule-exhibitions')
    apply('schedule.html', update_ex_count, len(schedule))
    apply('index.html', update_exhibitions, schedule, 'home-exhibitions')
    apply('about.html', update_portraits, photos)
    apply('assets/i18n.js', update_i18n, works)
    apply('assets/i18n.js', update_i18n_exhibitions, schedule)
    apply('contact.html', lambda text: (text, False))  # copy as-is (static page)

    flush_pending()

    touched = [f['file'] for f in files if f['status'] == 'updated']
    backup = None
    if touched and not dry_run:
        bakdir = os.path.join(
            root, '.sync-backups', datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        os.makedirs(bakdir, exist_ok=True)
        for rel in touched:
            shutil.copy2(os.path.join(root, rel), os.path.join(bakdir, os.path.basename(rel)))
        backup = bakdir

    uploads_written = write_uploads(uploads, dry_run, root) if write_upload_files else []

    new_works = [w for w in works if int(w.get('n', 0)) > 12]
    missing = []
    for f in [w.get('file') for w in works] + [p.get('file') for p in photos]:
        if not f or f in uploads:
            continue
        p = os.path.normpath(os.path.join(root, f))
        if not os.path.exists(p):
            missing.append(f)

    return {
        'ok': True,
        'dryRun': bool(dry_run),
        'works': len(works),
        'schedule': len(schedule),
        'photos': len(photos),
        'files': files,
        'uploads': [{'path': rel, 'bytes': sz} for rel, sz in uploads_written],
        'newWorks': [
            {'n': w.get('n'), 'title': w.get('title', ''), 'file': w.get('file', '')}
            for w in new_works
        ],
        'missing': missing,
        'backup': backup,
    }


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description='Sync dashboard export JSON into the site files.')
    ap.add_argument('json', help='dashboard export JSON (Data tab → Download JSON)')
    ap.add_argument('--dry-run', action='store_true', help='preview only, write nothing')
    ap.add_argument('--write-uploads', action='store_true', help='also write uploaded images into assets/')
    ap.add_argument('--output-dir', help='write all output files under this subdirectory (for staging)')
    args = ap.parse_args()

    with open(args.json, encoding='utf-8') as f:
        data = json.load(f)

    res = apply_data(data, dry_run=args.dry_run, write_upload_files=args.write_uploads, output_dir=args.output_dir)
    if not res.get('ok'):
        sys.exit('error: %s' % res.get('error', 'unknown'))

    print(('DRY RUN — nothing will be written\n' if args.dry_run else '') +
          'Syncing %d works, %d schedule entries, %d photos' %
          (res['works'], res['schedule'], res['photos']))
    print('-' * 64)
    for f in res['files']:
        print('  %-14s %s' % (f['status'], f['file']))

    if res['backup']:
        print('\nbackups: %s' % res['backup'])
    else:
        print('\nno files changed' if not [f for f in res['files'] if f['status'] == 'updated'] else '(dry run — backups skipped)')

    if res['uploads']:
        print('\nuploads %s assets/ (%d):' % ('would be written to' if args.dry_run else 'written to', len(res['uploads'])))
        for u in res['uploads']:
            print('  %s  (%d bytes)' % (u['path'], u['bytes']))

    if res['newWorks']:
        print('\nNOTE: works beyond No. 12 present (%d):' % len(res['newWorks']))
        for w in res['newWorks']:
            print('  No.%s %s -> %s' % (w['n'], w['title'], w['file']))
        print('  — painting SVG/PNG files for these must exist in assets/ (use the dashboard image upload)')
        print('  — German dictionary entries were added to assets/i18n.js automatically')

    if res['missing']:
        print('\nWARNING: referenced files missing on disk:')
        for f in res['missing']:
            print('  ' + f)


if __name__ == '__main__':
    main()
