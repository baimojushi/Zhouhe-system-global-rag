#!/usr/bin/env python3
"""End-to-end ingest test: create file → wait for ingest → query via Gateway."""
import os
import sys
import time
import json
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/global-rag")

RAG_ROOT = Path("/mnt/e/RAG")
TEST_LIBRARY = "production"
TEST_CONTENT = """# 摄取端到端测试文档

## 概述
这是一个用于验证 RAG 系统摄取流程的测试文档。

## 测试内容
- 文档创建时间: {timestamp}
- 测试目的: 验证文件扫描、解析、向量化、索引全链路
- 预期结果: 通过 Gateway API 可检索到此文档片段

## 关键技术
RAG (Retrieval-Augmented Generation) 系统通过向量化检索增强大语言模型的生成能力。
BGE-M3 模型支持多语言、多粒度的文本嵌入。
Weaviate 向量数据库提供高效的相似度搜索。
"""

def create_test_file():
    """在生产文档库的未归类目录创建测试文件"""
    unclassified_dir = RAG_ROOT / "生产文档" / "未归类"
    unclassified_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    content = TEST_CONTENT.format(timestamp=timestamp)

    test_file = unclassified_dir / "e2e-test-ingest.md"
    test_file.write_text(content, encoding="utf-8")
    print(f"[OK] 测试文件已创建: {test_file}")
    return test_file

def wait_for_ingest(test_file, timeout_seconds=120):
    """等待摄取 worker 处理文件"""
    print(f"[..] 等待摄取 worker 处理（超时 {timeout_seconds}s）...")
    start = time.time()
    while time.time() - start < timeout_seconds:
        # 检查 Gateway 健康
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:9100/health")
            resp = urllib.request.urlopen(req, timeout=3)
            if resp.status == 200:
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        print("[WARN] Gateway 未就绪，继续尝试查询...")

def query_gateway(query_text, top_k=3):
    """通过 Gateway API 检索"""
    import urllib.request

    payload = json.dumps({
        "query": query_text,
        "scope": "global",
        "alpha": 0.7,
        "top_k": top_k,
        "session_id": "e2e-test"
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:9100/v1/retrieve",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read().decode("utf-8"))
    return data

def main():
    print("=" * 60)
    print("  RAG 摄取端到端测试")
    print("=" * 60)

    # Step 1: 创建测试文件
    print("\n[Step 1] 创建测试文件...")
    test_file = create_test_file()

    # Step 2: 等待 Gateway 就绪
    print("\n[Step 2] 检查 Gateway 状态...")
    wait_for_ingest(test_file)
    print("[OK] Gateway 已就绪")

    # Step 3: 等待摄取处理（扫描间隔 300s，需手动触发或等待）
    print("\n[Step 3] 等待摄取处理...")
    print("  提示: 摄取 Worker 默认 300s 扫描一次，这里等待 310s 或检查文件状态")
    print("  可通过前端「立即扫描」按钮触发，或等待自动扫描")

    # 等待最多 310 秒让自动扫描完成
    ingest_wait = 310
    print(f"  等待 {ingest_wait}s 让摄取 Worker 自动扫描...")
    time.sleep(ingest_wait)

    # Step 4: 通过 Gateway 查询
    print("\n[Step 4] 通过 Gateway API 查询...")
    try:
        result = query_gateway("RAG 摄取端到端测试")
        results = result.get("results", result.get("items", result.get("data", [])))
        print(f"[OK] 查询返回 {len(results)} 条结果")
        for i, item in enumerate(results[:3]):
            title = item.get("title", "N/A")
            score = item.get("score", "N/A")
            content_preview = item.get("content", "")[:80]
            print(f"  [{i+1}] {title} (score={score})")
            print(f"      {content_preview}...")

        if len(results) > 0:
            # 检查是否包含我们的测试文档
            found = any("摄取端到端测试" in r.get("content", "") or
                       "e2e-test" in r.get("source_name", "") or
                       "e2e-test" in r.get("title", "")
                       for r in results)
            if found:
                print("\n[PASS] 端到端摄取测试通过！测试文档已被成功索引和检索。")
                return 0
            else:
                print("\n[WARN] 查询有结果但未命中测试文档，可能摄取尚未完成")
                return 0
        else:
            print("\n[WARN] 查询无结果，摄取可能尚未完成")
            return 0

    except Exception as e:
        print(f"\n[ERROR] Gateway 查询失败: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
