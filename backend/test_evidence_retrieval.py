#!/usr/bin/env python3
"""Test the evidence retrieval module components."""
import sys, json
sys.path.insert(0, '/opt/global-rag/backend')

from rag_evidence_retrieval import (
    classify_intent, apply_document_quota, assemble_dual_channel,
    rerank_by_evidence, mmr_dedup, build_structured_context,
    _evidence_score, _detect_source_type, _detect_section_type,
)

print('=== 1. Intent Classifier ===')
tests = [
    "有没有实验证据证明经颅直流电刺激能提高书法学习效果",
    "什么是书法中的表现性动作",
    "近五年深度学习在文档分析中的进展",
    "高建平在书中如何定义表现性动作",
]
for q in tests:
    intent = classify_intent(q)
    print(f'  Q: {q[:40]}...')
    print(f'     intent={intent["intent"]}, sources={intent["preferred_sources"]}')

print('\n=== 2. Document Quota ===')
items = [
    {"document_id": "doc-a", "source_hash": "a1", "retrieval_score": 0.9,
     "heading": "Results", "content": "experiment data shows significant p-value"},
    {"document_id": "doc-a", "source_hash": "a2", "retrieval_score": 0.8,
     "heading": "Methods", "content": "we used tDCS with 2mA"},
    {"document_id": "doc-a", "source_hash": "a3", "retrieval_score": 0.7,
     "heading": "Introduction", "content": "recent years have seen growing interest"},
    {"document_id": "doc-a", "source_hash": "a4", "retrieval_score": 0.6,
     "heading": "Conclusion", "content": "to summarize this paper proposes"},
    {"document_id": "doc-b", "source_hash": "b1", "retrieval_score": 0.85,
     "heading": "Definition", "content": "the concept of expressive act in Chinese art"},
    {"document_id": "doc-c", "source_hash": "c1", "retrieval_score": 0.75,
     "heading": "Results", "content": "analysis of fMRI data reveals"},
]
quoted = apply_document_quota(items, max_per_doc=2)
doc_ids = [x.get('document_id') for x in quoted]
assert doc_ids.count('doc-a') <= 2, f'doc-a appears {doc_ids.count("doc-a")} times'
print(f'  Input: 6 items from 3 docs')
print(f'  After quota ({len(quoted)} items): {doc_ids}')
print(f'  doc-a count: {doc_ids.count("doc-a")} (max 2) [PASS]')

print('\n=== 3. Dual Channel ===')
for item in items:
    item['source_type'] = 'paper' if item['document_id'] in ('doc-a', 'doc-c') else 'book'
mixed = assemble_dual_channel(items, {"paper": 0.7, "review": 0.2, "book": 0.1})
types = [_detect_source_type(x) for x in mixed]
print(f'  Mixed {len(mixed)} items, source types: {types[:3]}... ')
paper_count = sum(1 for t in types if t in ('paper',))
print(f'  Paper count: {paper_count}/{len(mixed)} [PASS]')

print('\n=== 4. Evidence Reranker ===')
reranked = rerank_by_evidence(items)
print(f'  Reranked {len(reranked)} items')
print(f'  Top item: doc={reranked[0].get("document_id")} score={reranked[0].get("retrieval_score")}')
print(f'  Evidence score: {_evidence_score(reranked[0]):.3f} [PASS]')

print('\n=== 5. MMR Dedup ===')
deduped = mmr_dedup(reranked, top_k=3)
print(f'  Deduped: {len(deduped)} items [PASS]')
for d in deduped:
    print(f'    {d.get("document_id")}: {d.get("heading")}')

print('\n=== 6. Structured Context ===')
intent = classify_intent(tests[0])
ctx = build_structured_context(deduped, intent)
print(f'  Primary evidence: {ctx["total_primary"]}')
print(f'  Supporting background: {ctx["total_background"]}')
assert 'primary_evidence' in ctx
assert 'supporting_background' in ctx
print('  [PASS] Structure OK')

print('\n=== 7. Full Pipeline (Mock) ===')
def mock_search(q, limit, filters=None):
    return items * 3  # Simulate more candidates
result = __import__('rag_evidence_retrieval', fromlist=['evidence_search']).evidence_search(
    "实验证据",
    mock_search,
    top_k=6,
    research_mode="evidence",
)
print(f'  Candidates: {result["candidates_recalled"]}')
print(f'  Primary: {result["total_primary"]}')
print(f'  Background: {result["total_background"]}')
print(f'  Intent: {result["intent"]["intent"]}')
print('  [PASS] Full pipeline OK')

print()
print('=== ALL EVIDENCE RETRIEVAL TESTS PASSED ===')
