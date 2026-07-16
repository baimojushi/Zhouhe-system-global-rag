# Python 函数示例

## 向量检索接口

以下是一个简化版的向量检索接口实现：

```python
import weaviate
from weaviate.auth import AuthApiKey

def search_documents(query: str, top_k: int = 5, api_key: str = None) -> list:
    """
    搜索知识库文档
    
    Args:
        query: 搜索查询文本
        top_k: 返回结果数量
        api_key: Weaviate API Key
        
    Returns:
        搜索结果列表
    """
    client = weaviate.connect_to_local(
        host="localhost",
        port=8080,
        auth_credentials=AuthApiKey(api_key)
    )
    
    collection = client.collections.get("KnowledgeChunk")
    
    # BM25 搜索
    result = collection.query.bm25(
        query=query,
        limit=top_k
    )
    
    return [
        {
            "title": r.properties["title"],
            "heading": r.properties["heading"],
            "content": r.properties["content"],
            "score": r.metadata.score,
        }
        for r in result.objects
    ]
```

## 批量索引主函数

```python
import hashlib
from pathlib import Path
from typing import List, Tuple

def index_files(file_paths: List[str]) -> None:
    """
    批量索引文件到 Weaviate
    
    Args:
        file_paths: 文件路径列表
    """
    for fp in file_paths:
        file_path = Path(fp)
        
        # 计算文件哈希
        file_hash = compute_file_hash(file_path)
        
        # 检查是否需要重新索引
        if is_unchanged(file_path, file_hash):
            print(f"跳过: {file_path} (未变更)")
            continue
        
        # 解析文件
        chunks = parse_document(file_path)
        
        # 批量插入
        for chunk in chunks:
            insert_chunk(chunk, file_hash)
```

## 增量索引状态管理

```python
import json

class IndexState:
    def __init__(self, state_file: str = ".index_state.json"):
        self.state_file = state_file
        self._load()
    
    def _load(self):
        if Path(self.state_file).exists():
            with open(self.state_file) as f:
                self.states = json.load(f)
        else:
            self.states = {}
    
    def is_unchanged(self, path: str, file_hash: str) -> bool:
        return self.states.get(path) == file_hash
    
    def update(self, path: str, file_hash: str):
        self.states[path] = file_hash
        with open(self.state_file, "w") as f:
            json.dump(self.states, f, indent=2)
```