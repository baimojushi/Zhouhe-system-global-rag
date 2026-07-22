#!/usr/bin/env python3
"""V1.1 verification: page/heading/block-type aware chunking."""
import sys, json
sys.path.insert(0, '/opt/global-rag/backend')

from ingest_worker import _chunk_from_content_list, _chunk_markdown

# 1. Test with real academic PDF content_list
raw = open('/home/baimo/services/mineru/output/academic_content_list.json').read()
content_list = json.loads(raw)
if isinstance(content_list, str):
    content_list = json.loads(content_list)

print('Content list length:', len(content_list))

# Collect block types
types = {}
for item in content_list:
    t = item.get('type', '?') if isinstance(item, dict) else '?'
    types[t] = types.get(t, 0) + 1
print('Block types:', dict(sorted(types.items())))

# Chunk using new function
chunks = _chunk_from_content_list(content_list, 'test_academic.pdf')
print(f'Chunks produced: {len(chunks)}')

# Analyze chunk properties
pages = set()
block_types = set()
asset_refs_count = 0
for c in chunks:
    pages.add(c['page'])
    block_types.add(c['block_type'])
    if c['asset_refs']:
        asset_refs_count += 1

print(f'Unique pages: {sorted(pages)[:10]}...' if len(pages) > 10 else f'Unique pages: {sorted(pages)}')
print(f'Unique block types: {sorted(block_types)}')
print(f'Chunks with asset refs: {asset_refs_count}')

# Show first 5 chunks
print('\n=== First 5 chunks ===')
for i, c in enumerate(chunks[:5]):
    print(f'[{i}] page={c["page"]} heading="{c["heading"][:50]}" type={c["block_type"]} len={len(c["content"])} assets={c["asset_refs"]}')
    print(f'    content: {c["content"][:100]}...')

# Show a chunk with assets
asset_chunks = [c for c in chunks if c['asset_refs']]
if asset_chunks:
    print('\n=== Chunk with asset refs ===')
    c = asset_chunks[0]
    print(f'page={c["page"]} heading="{c["heading"][:50]}" type={c["block_type"]}')
    print(f'assets: {c["asset_refs"]}')
    print(f'content: {c["content"][:200]}')

# Show a non-text chunk
non_text = [c for c in chunks if c['block_type'] != 'text']
if non_text:
    print('\n=== Non-text chunk ===')
    c = non_text[0]
    print(f'page={c["page"]} heading="{c["heading"][:50]}" type={c["block_type"]}')
    print(f'content: {c["content"][:200]}')

# 2. Compare with markdown-based chunking
md = open('/home/baimo/services/mineru/output/academic_md.md').read()
md_chunks = _chunk_markdown(md, 'test_academic.pdf')
print(f'\nMarkdown chunks: {len(md_chunks)}')
print(f'Content list chunks: {len(chunks)}')

# 3. Verify chunk properties
for c in chunks:
    assert 'content' in c
    assert 'heading' in c
    assert 'page' in c
    assert 'block_type' in c
    assert 'asset_refs' in c
    assert 'chunk_index' in c
print('\n[PASS] All chunk properties present')

assert len(chunks) > 0
assert len(pages) > 0
assert block_types.issubset({'text', 'table', 'chart', 'image', 'formula'})
print('[PASS] Block types are valid')

print()
print('=== V1.1 ALL TESTS PASSED ===')
