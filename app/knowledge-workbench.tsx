"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type LibraryDefinition = {
  id: string;
  name: string;
  collection_name: string;
  kind: "document" | "association";
  policy: string;
  description: string;
  status: "active" | "archived";
  taxonomy_version: number;
  document_count: number;
  unclassified_count: number;
};

type TreeNode = {
  id: string;
  node_id: string;
  library_id: string;
  parent_id: string | null;
  name: string;
  label: string;
  description: string;
  hint: string;
  count: number;
  direct_count: number;
  subtree_count: number;
  position: number;
  kind: "physical" | "smart" | "alias";
  is_unclassified: boolean;
  locked: boolean;
  status: "active" | "archived";
  revision: number;
  children: TreeNode[];
};

type DocumentRecord = {
  id: string;
  library_id: string;
  title: string;
  mime_type: string;
  source_path: string;
  source_name: string;
  content_hash: string;
  status: "unclassified" | "active" | "archived" | "trash";
  index_status: string;
  owner: string;
  current_version_id?:string|null;
  revision: number;
  primary_node_id: string | null;
  primary_node_name: string | null;
  updated_at: string;
  metadata: Record<string, unknown>;
  tags: Array<{ id: string; name: string; color: string }>;
  aliases: Array<{ id: string; name: string }>;
  versions?: Array<{ id: string; version_number: number; created_at: string }>;
};

type TagRecord = { id: string; name: string; color: string; document_count: number };
type DocumentVersion={id:string;version_number:number;index_status:string;chunk_count:number;created_at:string};
type JobRecord={id:string;state:string;source_path:string;progress:number;error?:string;retry_count?:number;max_retries?:number;worker_id?:string;chunks_indexed?:number;created_at:string};
type AuditRecord={id:string;action:string;target_type:string;target_id?:string;actor?:string;created_at:string};
type KnowledgeEdge={id:string;source_title:string;target_title:string;relation_type:string;confidence:number;status:"candidate"|"confirmed"|"rejected";revision:number};
type ProposalStatus = "draft" | "reviewing" | "reviewed" | "applied" | "reverted";
type ProposalItemStatus = "pending" | "approved" | "rejected" | "applied" | "reverted";
type ProposalItem = {
  id: string;
  proposal_id: string;
  document_id: string;
  document_title?: string;
  document_source_name?: string;
  version_id: string;
  live_version_id?: string;
  source_node_id: string;
  source_node_name?: string;
  target_node_id: string;
  target_node_name?: string;
  status: ProposalItemStatus;
  confidence: number;
  reason_code: string;
  llm_reasoning: string;
  conflict_reason?: string;
};
type ProposalSummary = {
  id: string;
  library_id: string;
  status: ProposalStatus;
  llm_model: string;
  item_count: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  applied_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  created_at: string;
};
type ProposalDetail = ProposalSummary & {
  items: ProposalItem[];
  applied_at?: string;
  reverted_at?: string;
};
type ProposalCreateResult = {
  proposal_id: string | null;
  items: ProposalItem[];
  routing_cards_count: number;
  llm_model?: string;
  message?: string;
  validation_errors?: Array<{ document_id: string; target_node_id: string; message: string }>;
};

type DialogState =
  | { type: "library" }
  | { type:"library-settings" }
  | { type: "node"; parentId: string | null }
  | { type: "edit-node"; node: TreeNode }
  | null;

const demoLibraries: LibraryDefinition[] = [
  { id: "ai-work", name: "AI 工作记录", collection_name: "kb_ai_work_v1", kind: "document", policy: "private · session-aware", description: "会话、实验、提示词版本和可复用决策。", status: "active", taxonomy_version: 4, document_count: 36, unclassified_count: 3 },
  { id: "academic", name: "学术资料", collection_name: "kb_academic_v1", kind: "document", policy: "research · citation-first", description: "论文、书籍、研究问题和引用关系。", status: "active", taxonomy_version: 7, document_count: 24, unclassified_count: 2 },
  { id: "production", name: "生产文档", collection_name: "kb_production_v1", kind: "document", policy: "team · recency-weighted", description: "部署、SOP、故障复盘和有效版本。", status: "active", taxonomy_version: 5, document_count: 27, unclassified_count: 1 },
  { id: "notes", name: "个人思维笔记", collection_name: "kb_notes_v1", kind: "document", policy: "owner-only · exploratory", description: "灵感、观察、草稿和持续生长的主题。", status: "active", taxonomy_version: 3, document_count: 11, unclassified_count: 2 },
  { id: "association", name: "关联知识库", collection_name: "kb_association_v1", kind: "association", policy: "edge-only · cross-library", description: "跨库关系、证据和待验证结论。", status: "active", taxonomy_version: 2, document_count: 8, unclassified_count: 4 },
];

function demoNode(id: string, libraryId: string, name: string, count: number, children: TreeNode[] = [], options: Partial<TreeNode> = {}): TreeNode {
  return {
    id,
    node_id: id,
    library_id: libraryId,
    parent_id: null,
    name,
    label: name,
    description: options.description ?? "",
    hint: options.description ?? "",
    count,
    direct_count: count - children.reduce((sum, child) => sum + child.count, 0),
    subtree_count: count,
    position: 0,
    kind: options.kind ?? "physical",
    is_unclassified: options.is_unclassified ?? false,
    locked: options.locked ?? false,
    status: "active",
    revision: 1,
    children,
  };
}

const demoTrees: Record<string, TreeNode[]> = {
  "ai-work": [
    demoNode("ai-unclassified", "ai-work", "未归类", 3, [], { is_unclassified: true, locked: true, description: "新文件入口" }),
    demoNode("ai-projects", "ai-work", "项目", 25, [
      demoNode("ai-rag", "ai-work", "Global RAG", 18, [
        demoNode("ai-rag-design", "ai-work", "设计决策", 6),
        demoNode("ai-rag-debug", "ai-work", "调试记录", 9),
        demoNode("ai-rag-prompts", "ai-work", "提示词版本", 3),
      ]),
      demoNode("ai-agents", "ai-work", "Agent 实验", 7),
    ]),
    demoNode("ai-models", "ai-work", "模型评测", 8),
  ],
  academic: [
    demoNode("ac-unclassified", "academic", "未归类", 2, [], { is_unclassified: true, locked: true }),
    demoNode("ac-cs", "academic", "计算机科学", 18, [
      demoNode("ac-ir", "academic", "信息检索", 12, [
        demoNode("ac-hybrid", "academic", "混合检索", 7),
        demoNode("ac-rerank", "academic", "重排序", 5),
      ]),
      demoNode("ac-llm", "academic", "语言模型", 6),
    ]),
    demoNode("ac-method", "academic", "研究方法", 4),
  ],
  production: [
    demoNode("pr-unclassified", "production", "未归类", 1, [], { is_unclassified: true, locked: true }),
    demoNode("pr-platform", "production", "平台与基础设施", 19, [
      demoNode("pr-wsl", "production", "WSL2", 7),
      demoNode("pr-llamacpp", "production", "llama.cpp / Gemma", 8),
      demoNode("pr-vector", "production", "向量数据库", 4),
    ]),
    demoNode("pr-sop", "production", "标准作业流程", 4),
    demoNode("pr-incidents", "production", "故障与复盘", 3),
  ],
  notes: [
    demoNode("nt-unclassified", "notes", "未归类", 2, [], { is_unclassified: true, locked: true }),
    demoNode("nt-systems", "notes", "系统与复杂性", 5, [
      demoNode("nt-emergence", "notes", "涌现", 3),
      demoNode("nt-feedback", "notes", "反馈回路", 2),
    ]),
    demoNode("nt-seeds", "notes", "尚未成形的种子", 4),
  ],
  association: [
    demoNode("as-candidate", "association", "候选关联", 4, [], { is_unclassified: true, locked: true }),
    demoNode("as-support", "association", "相互支持", 2),
    demoNode("as-conflict", "association", "冲突与例外", 1),
    demoNode("as-counterintuitive", "association", "反直觉假设", 1),
  ],
};

const demoDocuments: DocumentRecord[] = [
  { id: "demo-1", library_id: "ai-work", title: "Global RAG V2 设计决策.md", mime_type: "text/markdown", source_path: "/opt/global-rag/kb/Global-RAG-V2.md", source_name: "Global-RAG-V2.md", content_hash: "b93f...", status: "active", index_status: "indexed", owner: "local-owner", revision: 3, primary_node_id: "ai-rag-design", primary_node_name: "设计决策", updated_at: "2026-07-17T18:42:00Z", metadata: {}, tags: [{ id: "tag-1", name: "架构", color: "#ff3153" }], aliases: [] },
  { id: "demo-2", library_id: "ai-work", title: "Gateway 调试记录 0717.md", mime_type: "text/markdown", source_path: "/opt/global-rag/kb/debug-0717.md", source_name: "debug-0717.md", content_hash: "2aa1...", status: "active", index_status: "indexed", owner: "local-owner", revision: 2, primary_node_id: "ai-rag-debug", primary_node_name: "调试记录", updated_at: "2026-07-17T18:31:00Z", metadata: {}, tags: [{ id: "tag-2", name: "故障", color: "#ff8b5f" }], aliases: [{ id: "ai-rag", name: "Global RAG" }] },
  { id: "demo-3", library_id: "ai-work", title: "待整理的模型实验.json", mime_type: "application/json", source_path: "/opt/global-rag/kb/inbox/model-exp.json", source_name: "model-exp.json", content_hash: "cc41...", status: "unclassified", index_status: "queued", owner: "local-owner", revision: 1, primary_node_id: "ai-unclassified", primary_node_name: "未归类", updated_at: "2026-07-17T17:58:00Z", metadata: {}, tags: [], aliases: [] },
];

function libraryMark(library: LibraryDefinition): string {
  if (library.kind === "association") return "∿";
  const known: Record<string, string> = { "ai-work": "AI", academic: "AC", production: "PR", notes: "NT" };
  return known[library.id] ?? library.name.slice(0, 2).toUpperCase();
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const result: TreeNode[] = [];
  for (const node of nodes) {
    result.push(node);
    result.push(...flattenTree(node.children));
  }
  return result;
}

function findNode(nodes: TreeNode[], id: string | null): TreeNode | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findNode(node.children, id);
    if (child) return child;
  }
  return null;
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(parsed);
}

function documentStatusLabel(status: string): string {
  return ({
    unclassified: "待整理",
    active: "正常使用",
    archived: "已归档",
    trash: "回收站",
  } as Record<string, string>)[status] ?? "状态未知";
}

function indexStatusLabel(status: string): string {
  return ({
    queued: "等待处理",
    running: "正在处理",
    processing: "正在处理",
    ready: "可以搜索",
    indexed: "可以搜索",
    stale: "等待更新",
    failed: "处理失败",
  } as Record<string, string>)[status] ?? "尚未处理";
}

function proposalStatusLabel(status: string): string {
  return ({
    draft: "准备中",
    reviewing: "等待确认",
    reviewed: "已确认",
    applied: "已执行",
    reverted: "已撤销",
    pending: "待确认",
    approved: "同意采用",
    rejected: "不采用",
  } as Record<string, string>)[status] ?? "状态未知";
}

function jobStatusLabel(status: string): string {
  return ({
    queued: "等待导入",
    running: "正在导入",
    completed: "导入完成",
    succeeded: "导入完成",
    failed: "导入失败",
    cancelled: "已取消",
  } as Record<string, string>)[status] ?? "状态未知";
}

function nodeKindLabel(kind: string): string {
  return ({ physical: "普通分类", smart: "自动筛选分类", alias: "分类快捷方式" } as Record<string, string>)[kind] ?? "普通分类";
}

function auditActionLabel(action: string): string {
  return ({
    create: "新建",
    update: "修改",
    delete: "删除",
    archive: "归档",
    move: "移动",
    ingest: "导入资料",
    apply_proposal: "采用整理建议",
    revert_proposal: "撤销整理建议",
  } as Record<string, string>)[action] ?? action.replaceAll("_", " ");
}

function TreeBranch({
  nodes,
  depth,
  expanded,
  selected,
  onToggle,
  onSelect,
  onMove,
}: {
  nodes: TreeNode[];
  depth: number;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  onMove: (sourceId: string, targetParentId: string) => void;
}) {
  return <div className="tree-level" role={depth === 0 ? "tree" : "group"}>
    {nodes.map((node) => {
      const hasChildren = node.children.length > 0;
      const isOpen = expanded.has(node.id);
      return <div className="tree-branch" key={node.id}>
        <button
          className={`tree-node ${selected === node.id ? "selected" : ""} ${node.is_unclassified ? "is-inbox" : ""}`}
          style={{ "--tree-depth": depth } as React.CSSProperties}
          onClick={() => onSelect(node.id)}
          onDoubleClick={() => hasChildren && onToggle(node.id)}
          draggable={!node.is_unclassified && !node.locked}
          onDragStart={(event) => event.dataTransfer.setData("application/x-kb-node", node.id)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const sourceId = event.dataTransfer.getData("application/x-kb-node");
            if (sourceId && sourceId !== node.id) onMove(sourceId, node.id);
          }}
          role="treeitem"
          aria-selected={selected === node.id}
          aria-expanded={hasChildren ? isOpen : undefined}
        >
          <span className={`tree-chevron ${hasChildren ? "has-children" : ""}`} onClick={(event) => { event.stopPropagation(); if (hasChildren) onToggle(node.id); }}>{hasChildren ? (isOpen ? "−" : "+") : "·"}</span>
          <span className="tree-folder">{node.kind === "smart" ? "⌁" : node.is_unclassified ? "⌂" : "▱"}</span>
          <span className="tree-label"><b>{node.name}</b>{node.description && <small>{node.description}</small>}</span>
          <span className="tree-count">{node.count}</span>
        </button>
        {hasChildren && isOpen && <TreeBranch nodes={node.children} depth={depth + 1} expanded={expanded} selected={selected} onToggle={onToggle} onSelect={onSelect} onMove={onMove}/>} 
      </div>;
    })}
  </div>;
}

export function KnowledgeWorkbench({
  demoMode,
  gatewayUrl,
  apiKey,
  llmApiUrl,
  llmApiKey,
  llmModel,
  onNotice,
}: {
  demoMode: boolean;
  gatewayUrl: string;
  apiKey: string;
  llmApiUrl: string;
  llmApiKey: string;
  llmModel: string;
  onNotice: (message: string) => void;
}) {
  // V2 never sends provider secrets from the browser.  These props remain in
  // the signature until the settings screen is migrated to server-side aliases.
  void llmApiUrl;
  void llmApiKey;
  void llmModel;

  const [libraries, setLibraries] = useState<LibraryDefinition[]>(demoMode ? demoLibraries : []);
  const [activeId, setActiveId] = useState<string>("ai-work");
  const [tree, setTree] = useState<TreeNode[]>(demoTrees["ai-work"]);
  const [treeVersion, setTreeVersion] = useState(1);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>("ai-unclassified");
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["ai-projects", "ai-rag"]));
  const [documents, setDocuments] = useState<DocumentRecord[]>(demoDocuments);
  const [selectedDocuments, setSelectedDocuments] = useState<Set<string>>(new Set());
  const [focusedDocument, setFocusedDocument] = useState<DocumentRecord | null>(null);
  const [documentVersions,setDocumentVersions]=useState<DocumentVersion[]>([]);const [documentDraft,setDocumentDraft]=useState({title:"",owner:"",metadata:"{}"});
  const [tags, setTags] = useState<TagRecord[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [dialog, setDialog] = useState<DialogState>(null);
  const [libraryDraft, setLibraryDraft] = useState({ name: "", id: "", description: "", kind: "document" });
  const [nodeDraft, setNodeDraft] = useState({ name: "", description: "", kind: "physical" });
  const [bulkTarget, setBulkTarget] = useState("");
  const [aliasTarget, setAliasTarget] = useState("");
  const [tagDraft, setTagDraft] = useState("");
  const [ingestPath, setIngestPath] = useState("/opt/global-rag/kb/inbox");
  const [proposals, setProposals] = useState<ProposalSummary[]>([]);
  const [proposal, setProposal] = useState<ProposalDetail | null>(null);
  const [proposalPanelOpen, setProposalPanelOpen] = useState(false);
  const [proposalLoading, setProposalLoading] = useState(false);
  const [proposalAction, setProposalAction] = useState("");
  const [managementView,setManagementView]=useState<"browse"|"jobs"|"audit"|"associations">("browse");const [librarySettings,setLibrarySettings]=useState({name:"",description:"",policy:"",status:"active"});const [statusFilter,setStatusFilter]=useState("");const [edges,setEdges]=useState<KnowledgeEdge[]>([]);const [edgeDocuments,setEdgeDocuments]=useState<DocumentRecord[]>([]);const [edgeDraft,setEdgeDraft]=useState({source:"",target:"",relation:"related",confidence:"0.7"});

  const gatewayBase = gatewayUrl.replace(/\/$/, "");

  const callGateway = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`);
    const response = await fetch(`${gatewayBase}${path}`, { ...init, headers });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({})) as { message?: string; detail?: string };
      throw new Error(payload.message || payload.detail || `Gateway HTTP ${response.status}`);
    }
    return await response.json() as T;
  }, [apiKey, gatewayBase]);

  const loadLibraries = useCallback(async () => {
    if (demoMode) {
      setLibraries(demoLibraries);
      return;
    }
    try {
      const data = await callGateway<{ libraries: LibraryDefinition[] }>("/v2/libraries");
      setLibraries(data.libraries);
      setConnectionError("");
      if (!data.libraries.some((library) => library.id === activeId) && data.libraries[0]) {
        setActiveId(data.libraries[0].id);
      }
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "资料管理服务连接失败");
    }
  }, [activeId, callGateway, demoMode]);

  const loadTree = useCallback(async (libraryId: string) => {
    if (demoMode) {
      const nextTree = demoTrees[libraryId] ?? [];
      setTree(nextTree);
      const first = nextTree.find((node) => node.is_unclassified) ?? nextTree[0];
      setSelectedNodeId(first?.id ?? null);
      setExpanded(new Set(nextTree.filter((node) => node.children.length).map((node) => node.id)));
      setTreeVersion(demoLibraries.find((library) => library.id === libraryId)?.taxonomy_version ?? 1);
      return;
    }
    setLoading(true);
    try {
      const data = await callGateway<{ version: number; tree: TreeNode[] }>(`/v2/libraries/${encodeURIComponent(libraryId)}/tree`);
      setTree(data.tree);
      setTreeVersion(data.version);
      setExpanded(new Set(data.tree.filter((node) => node.children.length).map((node) => node.id)));
      setSelectedNodeId((current) => findNode(data.tree, current)?.id ?? data.tree.find((node) => node.is_unclassified)?.id ?? data.tree[0]?.id ?? null);
      setConnectionError("");
    } catch (error) {
      setTree([]);
      setConnectionError(error instanceof Error ? error.message : "目录树加载失败");
    } finally {
      setLoading(false);
    }
  }, [callGateway, demoMode]);

  const loadDocuments = useCallback(async (libraryId: string, nodeId: string | null, query: string) => {
    if (demoMode) {
      const all = demoDocuments.filter((document) => document.library_id === libraryId);
      const filtered = all.filter((document) => {
        const nodeMatches = !nodeId || document.primary_node_id === nodeId || findNode(tree, nodeId)?.count === all.length;
        const queryMatches = !query || document.title.toLowerCase().includes(query.toLowerCase());
        return nodeMatches && queryMatches;
      });
      setDocuments(filtered);
      return;
    }
    try {
      const params = new URLSearchParams({ library_id: libraryId, limit: "100" });
      if (nodeId) params.set("node_id", nodeId);
      if (query.trim()) params.set("q", query.trim());
      if(statusFilter)params.set("status",statusFilter);
      const data = await callGateway<{ items: DocumentRecord[] }>(`/v2/documents?${params}`);
      setDocuments(data.items);
      setSelectedDocuments(new Set());
      setFocusedDocument((current) => data.items.find((document) => document.id === current?.id) ?? null);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "文档列表加载失败");
    }
  }, [callGateway,demoMode,statusFilter,tree]);

  const loadSideData = useCallback(async (libraryId: string) => {
    if (demoMode) {
      setTags([{ id: "tag-1", name: "架构", color: "#ff3153", document_count: 1 }, { id: "tag-2", name: "故障", color: "#ff8b5f", document_count: 1 }]);
      setJobs([]);
      setAudit([]);
      return;
    }
    try {
      const [tagData, jobData, auditData] = await Promise.all([
        callGateway<{ tags: TagRecord[] }>(`/v2/tags?library_id=${encodeURIComponent(libraryId)}`),
        callGateway<{ jobs: JobRecord[] }>(`/v2/jobs?library_id=${encodeURIComponent(libraryId)}&limit=8`),
        callGateway<{ events: AuditRecord[] }>(`/v2/libraries/${encodeURIComponent(libraryId)}/audit?limit=8`),
      ]);
      setTags(tagData.tags);
      setJobs(jobData.jobs);
      setAudit(auditData.events);
    } catch {
      // Secondary panels must not make the primary library view unusable.
    }
  }, [callGateway, demoMode]);

  const loadProposals = useCallback(async (libraryId: string) => {
    if (demoMode) {
      setProposals([]);
      return;
    }
    try {
      const data = await callGateway<{ proposals: ProposalSummary[] }>(
        `/v2/ai-proposals?library_id=${encodeURIComponent(libraryId)}&limit=30`,
      );
      setProposals(data.proposals);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "分类建议列表加载失败");
    }
  }, [callGateway, demoMode]);

  const loadProposal = useCallback(async (proposalId: string) => {
    if (demoMode) return;
    setProposalLoading(true);
    try {
      const detail = await callGateway<ProposalDetail>(
        `/v2/ai-proposals/${encodeURIComponent(proposalId)}`,
      );
      setProposal(detail);
      setProposalPanelOpen(true);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "分类建议详情加载失败");
    } finally {
      setProposalLoading(false);
    }
  }, [callGateway, demoMode, onNotice]);
  const focusDocument=useCallback(async(d:DocumentRecord)=>{setFocusedDocument(d);setDocumentDraft({title:d.title,owner:d.owner,metadata:JSON.stringify(d.metadata??{},null,2)});if(!demoMode){const [detail,v]=await Promise.all([callGateway<DocumentRecord>(`/v2/documents/${d.id}`),callGateway<{versions:DocumentVersion[]}>(`/v2/documents/${d.id}/versions`)]);setFocusedDocument(detail);setDocumentVersions(v.versions)}},[callGateway,demoMode]);
  const loadEdges=useCallback(async(id:string)=>{if(!demoMode)setEdges((await callGateway<{edges:KnowledgeEdge[]}>(`/v2/knowledge-edges?association_library_id=${id}`)).edges)},[callGateway,demoMode]);
  const loadEdgeDocuments=useCallback(async()=>{if(!demoMode){const groups=await Promise.all(libraries.filter(l=>l.kind!=="association").map(l=>callGateway<{items:DocumentRecord[]}>(`/v2/documents?library_id=${l.id}&limit=100`)));setEdgeDocuments(groups.flatMap(g=>g.items))}},[callGateway,demoMode,libraries]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadLibraries(), 0);
    return () => window.clearTimeout(timer);
  }, [loadLibraries]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadTree(activeId);
      void loadSideData(activeId);
      void loadProposals(activeId);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeId, loadProposals, loadSideData, loadTree]);
  useEffect(() => {
    const timer = window.setTimeout(() => void loadDocuments(activeId, selectedNodeId, search), 220);
    return () => window.clearTimeout(timer);
  }, [activeId, loadDocuments, search, selectedNodeId]);

  const activeLibrary = useMemo(() => libraries.find((library) => library.id === activeId) ?? libraries[0] ?? demoLibraries[0], [activeId, libraries]);
  const selectedNode = useMemo(() => findNode(tree, selectedNodeId), [selectedNodeId, tree]);
  const allNodes = useMemo(() => flattenTree(tree), [tree]);
  const overview = useMemo(() => ({
    documents: libraries.reduce((sum, library) => sum + library.document_count, 0),
    unclassified: libraries.reduce((sum, library) => sum + library.unclassified_count, 0),
    queued: jobs.filter((job) => job.state === "queued" || job.state === "running").length,
  }), [jobs, libraries]);
  useEffect(()=>{if(activeLibrary.kind!=="association")return;const timer=window.setTimeout(()=>{void loadEdges(activeId);void loadEdgeDocuments()},0);return()=>window.clearTimeout(timer)},[activeId,activeLibrary.kind,loadEdges,loadEdgeDocuments]);

  function chooseLibrary(libraryId: string) {
    setActiveId(libraryId);
    setFocusedDocument(null);
    setSelectedDocuments(new Set());
    setSearch("");
    setProposal(null);
    setProposalPanelOpen(false);
  }

  function toggleNode(nodeId: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  }

  async function refreshCurrent() {
    await Promise.all([loadLibraries(), loadTree(activeId), loadDocuments(activeId, selectedNodeId, search), loadSideData(activeId), loadProposals(activeId)]);
  }

  async function createLibrary(event: FormEvent) {
    event.preventDefault();
    if (demoMode) {
      onNotice("演示模式不会写入知识库；关闭演示模式后可创建真实库");
      return;
    }
    try {
      const created = await callGateway<LibraryDefinition>("/v2/libraries", {
        method: "POST",
        body: JSON.stringify({
          name: libraryDraft.name,
          library_id: libraryDraft.id || undefined,
          kind: libraryDraft.kind,
          description: libraryDraft.description,
        }),
      });
      setDialog(null);
      setLibraryDraft({ name: "", id: "", description: "", kind: "document" });
      await loadLibraries();
      chooseLibrary(created.id);
      onNotice(`知识库“${created.name}”已创建`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "创建知识库失败");
    }
  }

  async function submitNode(event: FormEvent) {
    event.preventDefault();
    if (!dialog || (dialog.type !== "node" && dialog.type !== "edit-node")) return;
    if (demoMode) {
      onNotice("演示模式不会写入目录；关闭演示模式后可保存变更");
      return;
    }
    try {
      if (dialog.type === "node") {
        await callGateway(`/v2/libraries/${encodeURIComponent(activeId)}/nodes`, {
          method: "POST",
          body: JSON.stringify({
            name: nodeDraft.name,
            description: nodeDraft.description,
            kind: nodeDraft.kind,
            parent_id: dialog.parentId,
            expected_taxonomy_version: treeVersion,
          }),
        });
        onNotice(`目录“${nodeDraft.name}”已创建`);
      } else {
        await callGateway(`/v2/nodes/${encodeURIComponent(dialog.node.id)}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: nodeDraft.name,
            description: nodeDraft.description,
            kind: nodeDraft.kind,
            expected_taxonomy_version: treeVersion,
          }),
        });
        onNotice(`目录“${nodeDraft.name}”已更新`);
      }
      setDialog(null);
      setNodeDraft({ name: "", description: "", kind: "physical" });
      await refreshCurrent();
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "保存目录失败");
    }
  }

  async function moveNode(sourceId: string, targetParentId: string) {
    if (demoMode) {
      onNotice("已识别新的分类位置；切换到本地模式后会保存这次移动");
      return;
    }
    try {
      await callGateway(`/v2/nodes/${encodeURIComponent(sourceId)}:move`, {
        method: "POST",
        body: JSON.stringify({ new_parent_id: targetParentId, expected_taxonomy_version: treeVersion }),
      });
      await refreshCurrent();
      onNotice("目录已移动；内容与向量未重新生成");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "目录移动失败");
    }
  }

  async function archiveSelectedNode() {
    if (!selectedNode || selectedNode.is_unclassified) return;
    if (!window.confirm(`归档“${selectedNode.name}”及其子目录？其中的文档会移入未归类。`)) return;
    if (demoMode) {
      onNotice("演示模式未执行归档");
      return;
    }
    try {
      const result = await callGateway<{ moved_documents: number }>(`/v2/nodes/${encodeURIComponent(selectedNode.id)}:archive`, {
        method: "POST",
        body: JSON.stringify({ expected_taxonomy_version: treeVersion }),
      });
      await refreshCurrent();
      onNotice(`目录已归档，${result.moved_documents} 个文档已安全移入未归类`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "目录归档失败");
    }
  }

  async function moveSelectedDocuments() {
    if (!bulkTarget || selectedDocuments.size === 0) return;
    if (demoMode) {
      onNotice(`演示：已选择 ${selectedDocuments.size} 个文档，目标目录 ${bulkTarget}`);
      return;
    }
    try {
      const result = await callGateway<{ moved_count: number }>("/v2/document-actions/move", {
        method: "POST",
        body: JSON.stringify({ document_ids: [...selectedDocuments], target_node_id: bulkTarget }),
      });
      setSelectedDocuments(new Set());
      await refreshCurrent();
      onNotice(`已移动 ${result.moved_count} 个文档；无需重新嵌入`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "批量移动失败");
    }
  }

  async function updateFocusedDocument(fields: Record<string, unknown>) {
    if (!focusedDocument) return;
    if (demoMode) {
      setFocusedDocument({ ...focusedDocument, ...fields } as DocumentRecord);
      onNotice("演示模式：文档变更仅保留在当前页面");
      return;
    }
    try {
      const updated = await callGateway<DocumentRecord>(`/v2/documents/${encodeURIComponent(focusedDocument.id)}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      });
      setFocusedDocument(updated);
      await refreshCurrent();
      onNotice("文档属性已保存");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "文档保存失败");
    }
  }
  async function saveDocumentDetails(){await updateFocusedDocument({title:documentDraft.title,owner:documentDraft.owner})}
  async function saveDocumentMetadata(){
    try {
      await updateFocusedDocument({metadata:JSON.parse(documentDraft.metadata)});
      onNotice("自定义信息已保存");
    } catch (error) {
      onNotice(error instanceof SyntaxError ? "自定义信息格式有误，请检查括号、引号和逗号" : error instanceof Error ? error.message : "保存自定义信息失败");
    }
  }
  async function saveLibrarySettings(e:FormEvent){e.preventDefault();await callGateway(`/v2/libraries/${activeId}`,{method:"PATCH",body:JSON.stringify(librarySettings)});setDialog(null);await loadLibraries()}
  async function removeAlias(id:string){if(focusedDocument)setFocusedDocument(await callGateway<DocumentRecord>(`/v2/documents/${focusedDocument.id}/aliases/${id}`,{method:"DELETE"}))}
  async function toggleTag(id:string){if(!focusedDocument)return;const ids=new Set(focusedDocument.tags.map(t=>t.id));if(ids.has(id))ids.delete(id);else ids.add(id);setFocusedDocument(await callGateway<DocumentRecord>(`/v2/documents/${focusedDocument.id}/tags`,{method:"PUT",body:JSON.stringify({tag_ids:[...ids]})}))}
  async function activateDocumentVersion(id:string){if(focusedDocument){await callGateway(`/v2/documents/${focusedDocument.id}/versions/${id}:activate`,{method:"POST"});await focusDocument(focusedDocument)}}

  async function addAlias() {
    if (!focusedDocument || !aliasTarget) return;
    if (demoMode) {
      onNotice("演示模式未写入别名");
      return;
    }
    try {
      const updated = await callGateway<DocumentRecord>(`/v2/documents/${encodeURIComponent(focusedDocument.id)}/aliases`, {
        method: "POST",
        body: JSON.stringify({ node_id: aliasTarget }),
      });
      setFocusedDocument(updated);
      setAliasTarget("");
      onNotice("已添加目录别名；没有复制文档或向量");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "添加别名失败");
    }
  }

  async function createAndAssignTag() {
    if (!focusedDocument || !tagDraft.trim()) return;
    if (demoMode) {
      onNotice("演示模式未写入标签");
      return;
    }
    try {
      let tag = tags.find((item) => item.name.toLowerCase() === tagDraft.trim().toLowerCase());
      if (!tag) {
        tag = await callGateway<TagRecord>("/v2/tags", {
          method: "POST",
          body: JSON.stringify({ library_id: activeId, name: tagDraft.trim(), color: "#ff3153" }),
        });
      }
      const tagIds = [...new Set([...focusedDocument.tags.map((item) => item.id), tag.id])];
      const updated = await callGateway<DocumentRecord>(`/v2/documents/${encodeURIComponent(focusedDocument.id)}/tags`, {
        method: "PUT",
        body: JSON.stringify({ tag_ids: tagIds }),
      });
      setFocusedDocument(updated);
      setTagDraft("");
      await loadSideData(activeId);
      onNotice(`标签“${tag.name}”已添加`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "标签保存失败");
    }
  }

  async function enqueueIngest() {
    if (!selectedNode || selectedNode.kind === "smart") {
      onNotice("请选择一个普通分类作为导入位置");
      return;
    }
    if (demoMode) {
      onNotice("演示模式未读取本地路径；真实模式会进行允许根目录校验");
      return;
    }
    try {
      const result = await callGateway<{ job: JobRecord }>("/v2/ingest/path", {
        method: "POST",
        body: JSON.stringify({ path: ingestPath, library_id: activeId, target_node_id: selectedNode.id }),
      });
      await refreshCurrent();
      onNotice(`导入任务 ${result.job.id.slice(0, 16)} 已加入后台处理`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "开始导入失败");
    }
  }

  async function requestClassification() {
    if (demoMode) {
      setProposal({
        id: "demo-proposal", library_id: activeId, status: "draft",
        llm_model: "local-rules", item_count: 1, pending_count: 1,
        approved_count: 0, rejected_count: 0, applied_count: 0,
        prompt_tokens: 0, completion_tokens: 0, created_at: new Date().toISOString(),
        items: [{
          id: "demo-item", proposal_id: "demo-proposal", document_id: "demo-3",
          document_title: "待整理的模型实验.json", version_id: "demo-version",
          source_node_id: "ai-unclassified", source_node_name: "未归类",
          target_node_id: "ai-models", target_node_name: "模型评测",
          status: "pending", confidence: 0.91, reason_code: "SIGNAL_MATCH",
          llm_reasoning: "标题和内容信号与模型评测目录一致。",
        }],
      });
      setProposalPanelOpen(true);
      return;
    }
    setProposalLoading(true);
    try {
      const result = await callGateway<ProposalCreateResult>("/v2/ai-proposals", {
        method: "POST",
        body: JSON.stringify({ library_id: activeId, source_node: selectedNode?.id ?? "unclassified", mode: "preview", payload_mode: "routing_cards", taxonomy_scope: "affected_subtree", max_routing_cards: 20 }),
      });
      if (!result.proposal_id) {
        onNotice(result.message ?? "当前知识库没有未归类文档");
        return;
      }
      await Promise.all([loadProposal(result.proposal_id), loadProposals(activeId)]);
      const invalid = result.validation_errors?.length ?? 0;
      onNotice(`分类建议已保存：${result.items.length} 项待确认${invalid ? `，${invalid} 项无法采用` : ""}`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "生成分类建议失败");
    } finally {
      setProposalLoading(false);
    }
  }

  async function reviewProposalItem(itemId: string, action: "approve" | "reject") {
    if (!proposal) return;
    if (demoMode) {
      setProposal({
        ...proposal,
        status: "reviewed",
        pending_count: 0,
        approved_count: action === "approve" ? 1 : 0,
        rejected_count: action === "reject" ? 1 : 0,
        items: proposal.items.map((item) => item.id === itemId ? { ...item, status: action === "approve" ? "approved" : "rejected" } : item),
      });
      return;
    }
    setProposalAction(`${action}:${itemId}`);
    try {
      await callGateway(
        `/v2/ai-proposals/${encodeURIComponent(proposal.id)}/items/${encodeURIComponent(itemId)}/${action}`,
        { method: "POST", body: action === "reject" ? JSON.stringify({ reason: "人工审核拒绝" }) : undefined },
      );
      await Promise.all([loadProposal(proposal.id), loadProposals(activeId)]);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "提案项审核失败");
    } finally {
      setProposalAction("");
    }
  }

  async function transitionProposal(action: "apply" | "revert") {
    if (!proposal) return;
    if (demoMode) {
      onNotice("演示模式只展示审核流程，不会移动真实文档");
      return;
    }
    setProposalAction(action);
    try {
      await callGateway(`/v2/ai-proposals/${encodeURIComponent(proposal.id)}/${action}`, { method: "POST" });
      await Promise.all([
        loadProposal(proposal.id), loadProposals(activeId), loadLibraries(),
        loadTree(activeId), loadDocuments(activeId, selectedNodeId, search),
      ]);
      onNotice(action === "apply" ? "已原子应用所有批准项" : "提案已安全撤销");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : action === "apply" ? "提案应用失败" : "提案撤销失败");
    } finally {
      setProposalAction("");
    }
  }
  async function retargetProposalItem(id:string,target:string){if(proposal){await callGateway(`/v2/ai-proposals/${proposal.id}/items/${id}`,{method:"PATCH",body:JSON.stringify({target_node_id:target})});await loadProposal(proposal.id)}}
  async function actOnJob(id:string,action:"retry"|"cancel"){await callGateway(`/v2/jobs/${id}:${action}`,{method:"POST"});await loadSideData(activeId)}
  async function createKnowledgeEdge(e:FormEvent){e.preventDefault();await callGateway("/v2/knowledge-edges",{method:"POST",body:JSON.stringify({association_library_id:activeId,source_document_id:edgeDraft.source,target_document_id:edgeDraft.target,relation_type:edgeDraft.relation,confidence:Number(edgeDraft.confidence)})});await loadEdges(activeId)}
  async function updateKnowledgeEdge(e:KnowledgeEdge,status:"confirmed"|"rejected"){await callGateway(`/v2/knowledge-edges/${e.id}`,{method:"PATCH",body:JSON.stringify({status,expected_revision:e.revision})});await loadEdges(activeId)}

  return <div className="page inner-page knowledge-page knowledge-v2">
    <div className="kb-title-row">
      <div className="page-title">
        <div className="eyebrow"><span/>整理和维护你的资料</div>
        <h1>知识库管理</h1>
        <p>先选择知识库，再选择分类，最后管理其中的资料。智能助手只提出建议，是否采用由你决定。</p>
      </div>
      <div className="kb-header-actions">
        <span className={`control-plane-badge ${connectionError ? "is-error" : ""}`}>
          <i/>{demoMode ? "正在使用演示数据" : connectionError ? "资料管理服务暂时不可用" : "资料管理服务正常"}
        </span>
        <button className="outline-button" onClick={() => { setProposalPanelOpen(true); if (!proposal && proposals[0]) void loadProposal(proposals[0].id); }}>
          查看分类建议 <b>{proposals.length}</b>
        </button>
        <button className="outline-button" onClick={() => void requestClassification()} disabled={proposalLoading || activeLibrary.kind === "association"} title={activeLibrary.kind === "association" ? "关联知识库不需要分类资料" : undefined}>
          {proposalLoading ? "正在分析…" : "让助手整理待分类资料"}
        </button>
        <button className="outline-button" onClick={() => { setLibrarySettings({ name: activeLibrary.name, description: activeLibrary.description, policy: activeLibrary.policy, status: activeLibrary.status }); setDialog({ type: "library-settings" }); }}>
          当前知识库设置
        </button>
        <button className="primary-button compact" onClick={() => setDialog({ type: "library" })}>新建知识库</button>
      </div>
    </div>

    {connectionError && <div className="kb-error-banner">
      <div><b>暂时无法读取真实资料</b><span>{connectionError}</span></div>
      <button onClick={() => void refreshCurrent()}>重新连接</button>
    </div>}

    <section className="kb-overview-strip" aria-label="知识库概览">
      <div><small>知识库数量</small><b>{libraries.length}</b><span>不同用途分开管理</span></div>
      <div><small>已收录资料</small><b>{overview.documents}</b><span>所有知识库合计</span></div>
      <div><small>待整理资料</small><b>{overview.unclassified}</b><span>还没有放入合适分类</span></div>
      <div><small>正在处理</small><b>{overview.queued}</b><span>导入完成后可搜索</span></div>
    </section>

    <nav className="deep-management-tabs knowledge-sections" aria-label="知识库功能">
      <button className={managementView === "browse" ? "active" : ""} onClick={() => setManagementView("browse")}><b>资料与分类</b><small>日常整理和查看</small></button>
      <button className={managementView === "jobs" ? "active" : ""} onClick={() => setManagementView("jobs")}><b>导入进度</b><small>查看处理结果</small></button>
      <button className={managementView === "audit" ? "active" : ""} onClick={() => setManagementView("audit")}><b>操作记录</b><small>追溯重要改动</small></button>
      <button className={managementView === "associations" ? "active" : ""} disabled={activeLibrary.kind !== "association"} onClick={() => setManagementView("associations")}><b>跨库关联</b><small>发现资料间联系</small></button>
    </nav>

    {managementView === "browse" && <section className="kb-workbench kb-workbench-v2">
      <aside className="library-rail" aria-label="选择知识库">
        <div className="rail-head">
          <div><span className="step-chip">第 1 步</span><b>选择知识库</b><small>不同知识库互相隔离</small></div>
          <button onClick={() => setDialog({ type: "library" })} title="新建知识库">＋</button>
        </div>
        <div className="library-list">
          {libraries.map((library) => <button key={library.id} className={`library-item ${activeId === library.id ? "active" : ""}`} onClick={() => chooseLibrary(library.id)}>
            <span className="library-mark">{libraryMark(library)}</span>
            <span className="library-copy"><b>{library.name}</b><small>{library.description || (library.kind === "association" ? "维护不同知识库之间的联系" : "独立保存和管理资料")}</small></span>
            <span className="library-stats"><b>{library.document_count}<small>份</small></b>{library.unclassified_count > 0 && <i>{library.unclassified_count} 待整理</i>}</span>
          </button>)}
        </div>
        <details className="advanced-section rail-health">
          <summary>知识库运行信息</summary>
          <div><span>分类结构版本</span><b>v{treeVersion}</b></div>
          <div><span>导入任务数量</span><b>{jobs.length}</b></div>
        </details>
      </aside>

      <aside className="taxonomy-pane">
        <header className="taxonomy-head">
          <div><span className="step-chip">第 2 步</span><h2>选择分类</h2><p>当前知识库：{activeLibrary.name}</p></div>
          <button onClick={() => setDialog({ type: "node", parentId: selectedNodeId })}>新建分类</button>
        </header>
        <div className="taxonomy-tools">
          <button onClick={() => setExpanded(new Set(allNodes.map((node) => node.id)))}>展开全部</button>
          <button onClick={() => setExpanded(new Set())}>全部收起</button>
          <button disabled={!selectedNode} onClick={() => { if (selectedNode) { setNodeDraft({ name: selectedNode.name, description: selectedNode.description, kind: selectedNode.kind }); setDialog({ type: "edit-node", node: selectedNode }); } }}>修改当前分类</button>
        </div>
        <div className="tree-scroll-v2">
          {loading ? <div className="kb-empty">正在读取分类…</div> : tree.length > 0 ? <TreeBranch nodes={tree} depth={0} expanded={expanded} selected={selectedNodeId} onToggle={toggleNode} onSelect={setSelectedNodeId} onMove={(source, target) => void moveNode(source, target)}/> : <div className="kb-empty">这个知识库还没有分类</div>}
        </div>
        <div className="taxonomy-footer">
          <button onClick={() => setDialog({ type: "node", parentId: selectedNodeId })}>在这里新建下级分类</button>
          <button className="danger-text" disabled={!selectedNode || selectedNode.is_unclassified} onClick={() => void archiveSelectedNode()}>停用当前分类</button>
        </div>
      </aside>

      <main className="document-workspace">
        <header className="document-toolbar">
          <div><span className="step-chip">第 3 步</span><h2>管理资料 <small>{documents.length} 份</small></h2><p>正在查看：{selectedNode?.name ?? activeLibrary.name}</p></div>
          <div className="document-tools">
            <select aria-label="按资料状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">全部资料</option><option value="unclassified">待整理</option><option value="active">正常使用</option><option value="archived">已归档</option>
            </select>
            <label className="document-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称或内容"/></label>
            <button onClick={() => void refreshCurrent()}>刷新</button>
          </div>
        </header>

        {selectedDocuments.size > 0 && <div className="bulk-action-bar">
          <b>已选择 {selectedDocuments.size} 份资料</b>
          <select value={bulkTarget} onChange={(event) => setBulkTarget(event.target.value)}>
            <option value="">要移动到哪个分类？</option>
            {allNodes.filter((node) => node.kind === "physical").map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
          </select>
          <button onClick={() => void moveSelectedDocuments()} disabled={!bulkTarget}>确认移动</button>
          <button onClick={() => setSelectedDocuments(new Set())}>取消</button>
        </div>}

        {proposal && <div className="proposal-banner proposal-banner-v2">
          <span className="proposal-pulse"/>
          <div><b>有一组分类建议等待处理</b><p>{proposal.items.length} 条建议，其中 {proposal.approved_count ?? proposal.items.filter((item) => item.status === "approved").length} 条已同意</p></div>
          <button onClick={() => setProposalPanelOpen(true)}>逐条检查</button>
          <button onClick={() => setProposal(null)}>稍后处理</button>
        </div>}

        <div className="document-table-wrap">
          <table className="document-table">
            <thead><tr><th className="check-cell"><input type="checkbox" aria-label="选择全部资料" checked={documents.length > 0 && selectedDocuments.size === documents.length} onChange={(event) => setSelectedDocuments(event.target.checked ? new Set(documents.map((document) => document.id)) : new Set())}/></th><th>资料名称</th><th>使用状态</th><th>所在分类</th><th>是否可搜索</th><th>最近更新</th></tr></thead>
            <tbody>
              {documents.map((document) => <tr key={document.id} className={focusedDocument?.id === document.id ? "focused" : ""} onClick={() => void focusDocument(document)}>
                <td className="check-cell" onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`选择 ${document.title}`} checked={selectedDocuments.has(document.id)} onChange={(event) => setSelectedDocuments((current) => { const next = new Set(current); if (event.target.checked) next.add(document.id); else next.delete(document.id); return next; })}/></td>
                <td><div className="document-name"><span>{document.mime_type.includes("pdf") ? "PDF" : document.mime_type.includes("json") ? "数据" : "文档"}</span><p><b>{document.title}</b><small>{document.source_name || "手动创建"}</small></p></div></td>
                <td><span className={`status-pill status-${document.status}`}>{documentStatusLabel(document.status)}</span></td>
                <td>{document.primary_node_name ?? "尚未分类"}</td>
                <td><span className={`index-dot index-${document.index_status}`}/>{indexStatusLabel(document.index_status)}</td>
                <td>{formatTime(document.updated_at)}</td>
              </tr>)}
              {documents.length === 0 && <tr><td colSpan={6}><div className="document-empty"><span>◇</span><b>这里还没有资料</b><p>可以在页面下方导入文件，或换一个分类查看。</p></div></td></tr>}
            </tbody>
          </table>
        </div>
      </main>

      <aside className="detail-drawer detail-drawer-v2">
        {focusedDocument ? <>
          <header><span className="step-chip">资料详情</span><h2>{focusedDocument.title}</h2><p>在这里修改名称、状态、标签和历史版本。</p></header>
          <div className="inspector-status-row">
            <label><span>资料状态</span><select value={focusedDocument.status} onChange={(event) => void updateFocusedDocument({ status: event.target.value })}><option value="unclassified">待整理</option><option value="active">正常使用</option><option value="archived">已归档</option><option value="trash">移到回收站</option></select></label>
            <label><span>是否可搜索</span><b>{indexStatusLabel(focusedDocument.index_status)}</b></label>
          </div>
          <dl className="drawer-meta simple-meta">
            <div><dt>所在分类</dt><dd>{focusedDocument.primary_node_name ?? "尚未分类"}</dd></div>
            <div><dt>负责人</dt><dd>{focusedDocument.owner || "未填写"}</dd></div>
            <div><dt>最近更新</dt><dd>{formatTime(focusedDocument.updated_at)}</dd></div>
          </dl>
          <section className="drawer-section document-editor">
            <h3>基本信息</h3>
            <label><span>资料名称</span><input value={documentDraft.title} onChange={(event) => setDocumentDraft({ ...documentDraft, title: event.target.value })}/></label>
            <label><span>负责人</span><input value={documentDraft.owner} onChange={(event) => setDocumentDraft({ ...documentDraft, owner: event.target.value })} placeholder="可留空"/></label>
            <button onClick={() => void saveDocumentDetails()}>保存修改</button>
          </section>
          <section className="drawer-section">
            <h3>标签</h3>
            <div className="tag-choice-list">{tags.map((tag) => <label key={tag.id}><input type="checkbox" checked={focusedDocument.tags.some((current) => current.id === tag.id)} onChange={() => void toggleTag(tag.id)}/><span>{tag.name}</span></label>)}{tags.length === 0 && <p>还没有标签</p>}</div>
            <div className="inline-editor"><input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="输入新标签名称"/><button onClick={() => void createAndAssignTag()}>新增</button></div>
          </section>
          <section className="drawer-section">
            <h3>同时显示在其他分类</h3>
            <p className="section-help">资料不会被复制，只会增加一个方便查找的入口。</p>
            <div className="alias-list">{focusedDocument.aliases.map((alias) => <span key={alias.id}>{alias.name}<button aria-label={`移除 ${alias.name}`} onClick={() => void removeAlias(alias.id)}>×</button></span>)}</div>
            <div className="inline-editor"><select value={aliasTarget} onChange={(event) => setAliasTarget(event.target.value)}><option value="">选择另一个分类</option>{allNodes.filter((node) => node.kind === "physical").map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select><button onClick={() => void addAlias()}>添加入口</button></div>
          </section>
          <section className="drawer-section">
            <h3>历史版本</h3>
            <div className="version-list">{documentVersions.map((version) => <article key={version.id}><div><b>第 {version.version_number} 版</b><small>{formatTime(version.created_at)} · {indexStatusLabel(version.index_status)}</small></div>{focusedDocument.current_version_id === version.id ? <strong>当前使用</strong> : version.index_status === "ready" && <button onClick={() => void activateDocumentVersion(version.id)}>改用此版本</button>}</article>)}{documentVersions.length === 0 && <p>暂无历史版本</p>}</div>
          </section>
          <details className="advanced-section">
            <summary>高级信息</summary>
            <dl className="drawer-meta"><div><dt>资料标识</dt><dd><code>{focusedDocument.id}</code></dd></div><div><dt>编辑版本</dt><dd>{focusedDocument.revision}</dd></div><div><dt>内容校验值</dt><dd><code>{focusedDocument.content_hash || "尚未生成"}</code></dd></div><div><dt>原始位置</dt><dd><code>{focusedDocument.source_path || "手动创建"}</code></dd></div></dl>
            <label className="metadata-editor"><span>自定义信息（JSON）</span><textarea value={documentDraft.metadata} onChange={(event) => setDocumentDraft({ ...documentDraft, metadata: event.target.value })}/><button onClick={() => void saveDocumentMetadata()}>保存自定义信息</button></label>
          </details>
        </> : selectedNode ? <>
          <header><span className="step-chip">分类详情</span><h2>{selectedNode.name}</h2><p>{selectedNode.description || "还没有填写这个分类的用途说明。"}</p></header>
          <dl className="drawer-meta simple-meta"><div><dt>本层资料</dt><dd>{selectedNode.direct_count} 份</dd></div><div><dt>包含下级分类</dt><dd>{selectedNode.subtree_count} 份</dd></div><div><dt>分类方式</dt><dd>{nodeKindLabel(selectedNode.kind)}</dd></div></dl>
          <section className="drawer-section"><h3>你可以这样操作</h3><ul className="plain-guidance"><li>拖动一个分类到另一个分类，可调整层级。</li><li>同一份资料可在其他分类增加查找入口。</li><li>停用分类后，其中资料会回到“待整理”。</li></ul></section>
          <section className="drawer-section relation-preview"><h3>最近操作</h3>{audit.slice(0, 4).map((event) => <p key={event.id}><span>{formatTime(event.created_at)}</span>{auditActionLabel(event.action)}</p>)}{audit.length === 0 && <small>还没有操作记录</small>}</section>
          <details className="advanced-section"><summary>高级信息</summary><dl className="drawer-meta"><div><dt>分类标识</dt><dd><code>{selectedNode.id}</code></dd></div><div><dt>分类结构版本</dt><dd>v{treeVersion}</dd></div></dl></details>
        </> : <div className="kb-empty">请选择一个分类或一份资料</div>}
      </aside>
    </section>}

    {managementView === "browse" && activeLibrary.kind !== "association" && <section className="ingest-dock ingest-dock-v2">
      <div><span className="step-chip">导入新资料</span><h2>添加文件或文件夹</h2><p>提交后会在后台处理。你可以离开此页，再到“导入进度”查看结果。</p></div>
      <label><span>文件或文件夹位置</span><input value={ingestPath} onChange={(event) => setIngestPath(event.target.value)}/><small>位置必须在资料服务允许读取的范围内。</small></label>
      <label><span>放入哪个分类</span><select value={selectedNodeId ?? ""} onChange={(event) => setSelectedNodeId(event.target.value)}>{allNodes.filter((node) => node.kind === "physical").map((node) => <option value={node.id} key={node.id}>{node.name}</option>)}</select></label>
      <button className="primary-button compact" onClick={() => void enqueueIngest()}>开始导入</button>
    </section>}

    {managementView === "jobs" && <section className="governance-panel">
      <header><div><span className="section-kicker">处理过程</span><h2>导入进度</h2><p>查看每批资料是否已成功加入知识库。</p></div><button className="outline-button" onClick={() => void loadSideData(activeId)}>刷新</button></header>
      <div className="governance-list">{jobs.map((job) => { const canCancel = job.state === "queued" || job.state === "running"; return <article className="job-card" key={job.id}><div className="job-main"><b>{job.source_path.split(/[\\/]/).filter(Boolean).pop() || job.source_path}</b><p>{job.source_path}</p><div className="job-progress"><i style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}/></div></div><div className="job-state"><strong>{jobStatusLabel(job.state)}</strong><span>{job.progress}%</span></div><button onClick={() => void actOnJob(job.id, canCancel ? "cancel" : "retry")}>{canCancel ? "取消导入" : "重新尝试"}</button>{job.error && <p className="job-error">失败原因：{job.error}</p>}<details className="advanced-section"><summary>任务信息</summary><code>{job.id}</code></details></article>; })}{jobs.length === 0 && <div className="kb-empty">目前没有导入任务</div>}</div>
    </section>}

    {managementView === "audit" && <section className="governance-panel">
      <header><div><span className="section-kicker">可以追溯和检查</span><h2>操作记录</h2><p>重要的新增、移动、修改和撤销都会留在这里。</p></div></header>
      <div className="audit-list">{audit.map((event) => <article key={event.id}><time>{formatTime(event.created_at)}</time><div><b>{auditActionLabel(event.action)}</b><p>{event.actor ? `操作人：${event.actor}` : "由系统记录"}</p></div><details className="advanced-section"><summary>详细信息</summary><code>{event.target_type} · {event.target_id || "—"}</code></details></article>)}{audit.length === 0 && <div className="kb-empty">目前没有操作记录</div>}</div>
    </section>}

    {managementView === "associations" && <section className="governance-panel association-panel">
      <header><div><span className="section-kicker">连接不同知识库</span><h2>跨库关联</h2><p>记录两份资料之间的支持、冲突或其他潜在联系，供后续推理使用。</p></div></header>
      <form className="edge-composer" onSubmit={createKnowledgeEdge}>
        <label><span>第一份资料</span><select required value={edgeDraft.source} onChange={(event) => setEdgeDraft({ ...edgeDraft, source: event.target.value })}><option value="">请选择</option>{edgeDocuments.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}</select></label>
        <label><span>它与第二份资料</span><select value={edgeDraft.relation} onChange={(event) => setEdgeDraft({ ...edgeDraft, relation: event.target.value })}><option value="related">存在联系</option><option value="supports">相互支持</option><option value="contradicts">存在冲突</option><option value="extends">可以互相补充</option></select></label>
        <label><span>第二份资料</span><select required value={edgeDraft.target} onChange={(event) => setEdgeDraft({ ...edgeDraft, target: event.target.value })}><option value="">请选择</option>{edgeDocuments.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}</select></label>
        <label><span>把握程度</span><select value={edgeDraft.confidence} onChange={(event) => setEdgeDraft({ ...edgeDraft, confidence: event.target.value })}><option value="0.5">可能有关</option><option value="0.7">较有把握</option><option value="0.9">非常确定</option></select></label>
        <button className="primary-button">保存关联</button>
      </form>
      <div className="edge-list">{edges.map((edge) => <article key={edge.id}><div><b>{edge.source_title}</b><span>↔</span><b>{edge.target_title}</b><p>把握程度 {Math.round(edge.confidence * 100)}%</p></div><span className={`status-pill status-${edge.status}`}>{edge.status === "candidate" ? "等待确认" : edge.status === "confirmed" ? "已经确认" : "不采用"}</span>{edge.status === "candidate" && <div><button onClick={() => void updateKnowledgeEdge(edge, "confirmed")}>确认保留</button><button onClick={() => void updateKnowledgeEdge(edge, "rejected")}>不采用</button></div>}</article>)}{edges.length === 0 && <div className="kb-empty">还没有建立跨库关联</div>}</div>
    </section>}

    {proposalPanelOpen && <div className="proposal-review-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setProposalPanelOpen(false); }}>
      <section className="proposal-review-panel" role="dialog" aria-modal="true" aria-label="检查智能分类建议">
        <header className="proposal-review-head">
          <div><span className="section-kicker">由你作最后决定</span><h2>检查智能分类建议</h2><p>可以逐条修改、同意或拒绝。真正执行前，系统还会检查资料是否已被别人改动。</p></div>
          <button onClick={() => setProposalPanelOpen(false)} aria-label="关闭分类建议">×</button>
        </header>
        <div className="proposal-review-layout">
          <aside className="proposal-history">
            <div className="proposal-history-head"><b>建议记录</b><button onClick={() => void requestClassification()} disabled={proposalLoading}>新建一组</button></div>
            {proposals.map((entry) => <button key={entry.id} className={proposal?.id === entry.id ? "active" : ""} onClick={() => void loadProposal(entry.id)}><span><b>{formatTime(entry.created_at)}</b><i className={`proposal-status status-${entry.status}`}>{proposalStatusLabel(entry.status)}</i></span><small>{entry.item_count} 条建议 · {entry.approved_count} 条已同意</small></button>)}
            {proposals.length === 0 && <div className="proposal-history-empty">还没有分类建议。<br/>点击“新建一组”分析待整理资料。</div>}
          </aside>
          <main className="proposal-review-main">
            {proposalLoading && !proposal ? <div className="kb-empty">正在读取建议…</div> : proposal ? <>
              <div className="proposal-summary"><div><small>当前状态</small><b>{proposalStatusLabel(proposal.status)}</b></div><div><small>建议总数</small><b>{proposal.items.length}</b></div><div><small>等待确认</small><b>{proposal.items.filter((item) => item.status === "pending").length}</b></div><div><small>已经同意</small><b>{proposal.items.filter((item) => item.status === "approved").length}</b></div></div>
              <div className="proposal-item-list">
                {proposal.items.map((item, index) => {
                  const versionConflict = item.live_version_id !== undefined && item.live_version_id !== item.version_id;
                  const busy = proposalAction.endsWith(item.id);
                  return <article className={`proposal-item-card item-${item.status} ${versionConflict ? "has-conflict" : ""}`} key={item.id}>
                    <div className="proposal-item-index">{index + 1}</div>
                    <div className="proposal-item-copy"><header><b>{item.document_title || item.document_source_name || "未命名资料"}</b><span>把握度 {Math.round(item.confidence * 100)}%</span></header><p><span>{item.source_node_name || "待整理"}</span><i>移到</i><strong>{item.target_node_name || "建议分类"}</strong></p><small>{item.llm_reasoning || "助手未提供额外说明"}</small>{versionConflict && <em>这份资料后来被修改过，需要重新生成建议。</em>}{item.status === "pending" && <label className="proposal-target"><span>改放到</span><select value={item.target_node_id} onChange={(event) => void retargetProposalItem(item.id, event.target.value)}>{allNodes.filter((node) => node.kind === "physical" && !node.is_unclassified).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select></label>}</div>
                    <div className="proposal-item-actions"><i className={`proposal-status status-${item.status}`}>{proposalStatusLabel(item.status)}</i>{item.status === "pending" && <><button className="approve" disabled={busy || versionConflict} onClick={() => void reviewProposalItem(item.id, "approve")}>{busy ? "处理中…" : "同意这样分类"}</button><button className="reject" disabled={busy} onClick={() => void reviewProposalItem(item.id, "reject")}>不采用</button></>}</div>
                  </article>;
                })}
                {proposal.items.length === 0 && <div className="kb-empty">没有生成可确认的建议。可以补充分类用途说明后再试。</div>}
              </div>
              <footer className="proposal-review-footer"><p>执行时会整组检查；只要有一份资料发生变化，就不会移动任何资料。</p>{proposal.status === "applied" ? <button className="outline-button" disabled={proposalAction === "revert"} onClick={() => void transitionProposal("revert")}>{proposalAction === "revert" ? "正在撤销…" : "撤销这组操作"}</button> : <button className="primary-button compact" disabled={proposalAction === "apply" || !proposal.items.some((item) => item.status === "approved")} onClick={() => void transitionProposal("apply")}>{proposalAction === "apply" ? "正在执行…" : "执行已同意的建议"}</button>}<details className="advanced-section proposal-technical"><summary>本次分析信息</summary><p>使用模型：{proposal.llm_model || "未记录"} · 用量：{(proposal.prompt_tokens ?? 0) + (proposal.completion_tokens ?? 0)} tokens</p></details></footer>
            </> : <div className="kb-empty">从左侧选择一组建议，或新建一组。</div>}
          </main>
        </div>
      </section>
    </div>}

    {dialog && <div className="kb-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(null); }}>
      {dialog.type === "library" ? <form className="kb-modal" onSubmit={createLibrary}>
        <header><div><span className="section-kicker">按用途分开管理</span><h2>新建知识库</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="关闭">×</button></header>
        <label><span>知识库名称</span><input required value={libraryDraft.name} onChange={(event) => setLibraryDraft({ ...libraryDraft, name: event.target.value })} placeholder="例如：工程资料"/></label>
        <label><span>用途</span><select value={libraryDraft.kind} onChange={(event) => setLibraryDraft({ ...libraryDraft, kind: event.target.value })}><option value="document">保存和搜索资料</option><option value="association">维护不同知识库之间的联系</option></select></label>
        <label><span>用途说明</span><textarea value={libraryDraft.description} onChange={(event) => setLibraryDraft({ ...libraryDraft, description: event.target.value })} placeholder="这里主要保存哪些资料？谁会使用？"/></label>
        <details className="advanced-section"><summary>高级设置</summary><label><span>技术标识（可留空自动生成）</span><input value={libraryDraft.id} onChange={(event) => setLibraryDraft({ ...libraryDraft, id: event.target.value.toLowerCase() })} placeholder="engineering" pattern="[a-z0-9][a-z0-9-]{1,62}"/></label></details>
        <footer><button type="button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" type="submit">创建知识库</button></footer>
      </form> : dialog.type === "library-settings" ? <form className="kb-modal" onSubmit={saveLibrarySettings}>
        <header><div><span className="section-kicker">当前知识库</span><h2>知识库设置</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="关闭">×</button></header>
        <label><span>名称</span><input value={librarySettings.name} onChange={(event) => setLibrarySettings({ ...librarySettings, name: event.target.value })}/></label>
        <label><span>用途说明</span><textarea value={librarySettings.description} onChange={(event) => setLibrarySettings({ ...librarySettings, description: event.target.value })}/></label>
        <label><span>使用状态</span><select value={librarySettings.status} onChange={(event) => setLibrarySettings({ ...librarySettings, status: event.target.value })}><option value="active">正常使用</option><option value="archived">停止使用</option></select></label>
        <details className="advanced-section"><summary>高级设置</summary><label><span>整理规则</span><input value={librarySettings.policy} onChange={(event) => setLibrarySettings({ ...librarySettings, policy: event.target.value })}/></label></details>
        <footer><button type="button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" type="submit">保存设置</button></footer>
      </form> : <form className="kb-modal" onSubmit={submitNode}>
        <header><div><span className="section-kicker">建立清晰的层级</span><h2>{dialog.type === "node" ? "新建分类" : `修改“${dialog.node.name}”`}</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="关闭">×</button></header>
        <label><span>分类名称</span><input required value={nodeDraft.name} onChange={(event) => setNodeDraft({ ...nodeDraft, name: event.target.value })}/></label>
        <label><span>分类方式</span><select value={nodeDraft.kind} onChange={(event) => setNodeDraft({ ...nodeDraft, kind: event.target.value })}><option value="physical">普通分类</option><option value="smart">按条件自动筛选</option><option value="alias">其他分类的快捷入口</option></select></label>
        <label><span>用途说明</span><textarea value={nodeDraft.description} onChange={(event) => setNodeDraft({ ...nodeDraft, description: event.target.value })} placeholder="说明哪些资料应该放在这里，哪些不应该。"/></label>
        <footer><button type="button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" type="submit">保存分类</button></footer>
      </form>}
    </div>}
  </div>;
}
