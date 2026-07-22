#!/usr/bin/env python3
"""Analyze MinerU content_list structure (double-decoded)."""
import json

raw = open('/home/baimo/services/mineru/output/academic_content_list.json').read()
d = json.loads(raw)
if isinstance(d, str):
    d = json.loads(d)

print('Type:', type(d).__name__)
if isinstance(d, list):
    print('Length:', len(d))
    types = {}
    for item in d[:500]:
        t = item.get('type', '?') if isinstance(item, dict) else str(type(item))
        types[t] = types.get(t, 0) + 1
    print('Block types:', dict(sorted(types.items())))

    # Show samples
    for btype in sorted(types.keys()):
        print(f'\n=== {btype} ===')
        samples = [x for x in d if isinstance(x, dict) and x.get('type') == btype][:2]
        for s in samples:
            print(f'  keys: {list(s.keys())}')
            for k, v in s.items():
                if isinstance(v, str):
                    print(f'    {k}: {v[:120]}')
                elif isinstance(v, (int, float)):
                    print(f'    {k}: {v}')
                elif isinstance(v, list):
                    print(f'    {k}: {v[:6]}')
                else:
                    print(f'    {k}: {v}')

    # Page distribution
    pages = {}
    for item in d:
        if isinstance(item, dict):
            p = item.get('page_idx', -1)
            pages[p] = pages.get(p, 0) + 1
    print('\n=== Pages ===')
    for p in sorted(pages.keys())[:10]:
        print(f'  Page {p}: {pages[p]} blocks')
    print(f'  ... total {len(pages)} pages')
