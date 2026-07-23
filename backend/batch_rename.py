#!/usr/bin/env python3
"""Batch rename PDFs using Gemma (standalone, no DB dependency)."""
import sys, os, json, time, hashlib, re, subprocess, urllib.request
sys.path.insert(0, '/opt/global-rag/backend')

from post_parse_filename import (
    rename_after_mineru, enabled, read_mineru_evidence,
    request_gemma_filename, collision_safe_target, canonical_filename,
    RenameOutcome, CANONICAL_RE,
)

PDF_DIR = '/mnt/e/RAG/学术资料'
ARTIFACT_ROOT = '/opt/global-rag/derived/mineru'
log_file = '/home/baimo/services/mineru/logs/batch_rename.log'

def log(msg):
    with open(log_file, 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    print(msg)

def list_pdfs(directory):
    try:
        r = subprocess.run(['ls', directory], capture_output=True, text=True, timeout=15)
        return sorted([f for f in r.stdout.splitlines() if f.lower().endswith('.pdf')])
    except Exception:
        return sorted([f for f in os.listdir(directory) if f.lower().endswith('.pdf')])

def get_artifact_dir(pdf_path, pdf_name):
    """Find or create MinerU artifacts for a PDF."""
    source_hash = hashlib.sha256(pdf_name.encode()).hexdigest()[:16]
    candidate = f'{ARTIFACT_ROOT}/{source_hash}/v1'
    md = f'{candidate}/document.md'
    if os.path.isfile(md) and os.path.getsize(md) > 100:
        return candidate
    return None

# --- Main ---
log('=== BATCH RENAME (STANDALONE) ===')
log(f'RAG_PDF_RENAME_ENABLED={enabled()}')

# Check Gemma
try:
    resp = urllib.request.urlopen('http://127.0.0.1:8000/v1/models', timeout=5)
    assert resp.status == 200
    log('Gemma: OK')
except Exception as e:
    log(f'Gemma NOT available: {e}')
    log('Start Gemma first via F:\\scripts\\Gemma\\start_q4_server_persistent_v4.bat')
    sys.exit(1)

pdfs = list_pdfs(PDF_DIR)
log(f'Found {len(pdfs)} PDFs')

# Build a mock store that does nothing
class MockStore:
    def create_file_rename_event(self, *a, **kw): return {'id': 'mock', 'reason': '', 'old_path': a[3] if len(a)>3 else '', 'new_path': a[4] if len(a)>4 else '', 'old_name': a[5] if len(a)>5 else '', 'new_name': a[6] if len(a)>6 else '', 'confidence': 0.0, 'model': '', 'state': 'mock'}
    def find_file_rename_event(self, *a, **kw): return None
    def apply_pdf_file_rename(self, *a, **kw): return {}
    def update_parse_job(self, *a, **kw): return {}
    def get_library(self, *a, **kw): return {'collection_name': 'kb_test'}
    
store = MockStore()
store._connect = lambda: None  # dummy

results = []
for idx, pdf_name in enumerate(pdfs, 1):
    pdf_path = f'{PDF_DIR}/{pdf_name}'
    log(f'\n[{idx}/{len(pdfs)}] {pdf_name}')
    
    if CANONICAL_RE.match(pdf_name):
        log(f'  Already canonical, skipping')
        results.append((pdf_name, 'skipped'))
        continue
    
    artifact_dir = get_artifact_dir(pdf_path, pdf_name)
    
    # If no artifacts, call Gemma with just filename as evidence
    if not artifact_dir:
        log(f'  No MinerU artifacts. Using filename-only evidence.')
        evidence = {'markdown_excerpt': '', 'content_blocks': []}
        try:
            proposal, model = request_gemma_filename(pdf_name, evidence)
            proposed_name, confidence, reason = canonical_filename(proposal)
            log(f'  Proposal: {proposed_name} (confidence={confidence})')
        except Exception as e:
            log(f'  Gemma error: {e}')
            results.append((pdf_name, f'gemma_error: {str(e)[:80]}'))
            continue
    else:
        log(f'  Using existing artifacts: {artifact_dir}')
        mock_job = {'id': f'batch-{idx}', 'source_path': pdf_path, 'document_id': '', 'version_id': ''}
        try:
            _, outcome = rename_after_mineru(store, mock_job, artifact_dir)
            log(f'  Outcome: {outcome.state}, new_name={outcome.new_name}')
            if outcome.state == 'renamed':
                results.append((pdf_name, outcome.new_name))
            else:
                results.append((pdf_name, outcome.state))
            continue
        except Exception as e:
            log(f'  rename_after_mineru failed: {e}')
            # Fall back to Gemma with evidence
            evidence = read_mineru_evidence(artifact_dir)
            proposal, model = request_gemma_filename(pdf_name, evidence)
            proposed_name, confidence, reason = canonical_filename(proposal)
    
    if not artifact_dir:
        # Standalone rename without MinerU artifacts
        try:
            target = collision_safe_target(pdf_path, proposed_name, pdf_name[:8])
            if target != pdf_path:
                os.rename(pdf_path, target)
                log(f'  ✅ Renamed -> {os.path.basename(target)}')
                results.append((pdf_name, os.path.basename(target)))
            else:
                log(f'  Unchanged (proposal matches current)')
                results.append((pdf_name, 'unchanged'))
        except Exception as e:
            log(f'  Rename failed: {e}')
            results.append((pdf_name, f'rename_error: {str(e)[:80]}'))

log('\n=== SUMMARY ===')
for old, new in results:
    if new.startswith('['):
        log(f'✅ {old[:50]} -> {new}')
    elif new == 'skipped':
        log(f'⏭️ {old[:50]}')
    else:
        log(f'⚠️  {old[:50]} ({new})')

log('\n=== DONE ===')
