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
type JobRecord = { id: string; state: string; source_path: string; progress: number; created_at: string };
type AuditRecord = { id: string; action: string; target_type: string; created_at: string };
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
      setConnectionError(error instanceof Error ? error.message : "V2 控制面连接失败");
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
      const data = await callGateway<{ items: DocumentRecord[] }>(`/v2/documents?${params}`);
      setDocuments(data.items);
      setSelectedDocuments(new Set());
      setFocusedDocument((current) => data.items.find((document) => document.id === current?.id) ?? null);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "文档列表加载失败");
    }
  }, [callGateway, demoMode, tree]);

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
      setConnectionError(error instanceof Error ? error.message : "AI 提案列表加载失败");
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
      onNotice(error instanceof Error ? error.message : "AI 提案详情加载失败");
    } finally {
      setProposalLoading(false);
    }
  }, [callGateway, demoMode, onNotice]);

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
      onNotice("拖拽目标已识别；真实模式会提交可审计的目录移动变更");
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
      onNotice("请选择实体目录作为摄取目标");
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
      onNotice(`摄取任务 ${result.job.id.slice(0, 16)} 已进入持久化队列`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "加入摄取队列失败");
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
      onNotice(`AI 提案已保存：${result.items.length} 项待审核${invalid ? `，${invalid} 项未通过校验` : ""}`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "AI 提案生成失败");
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

  return <div className="page inner-page knowledge-page knowledge-v2">
    <div className="kb-title-row">
      <div className="page-title">
        <div className="eyebrow"><span/>KNOWLEDGE CONTROL PLANE · V2</div>
        <h1>知识资产工作台</h1>
        <p>目录、文档、版本和任务已分离管理。手动操作优先，AI 只生成可审查提案。</p>
      </div>
      <div className="kb-header-actions">
        <span className={`control-plane-badge ${connectionError ? "is-error" : ""}`}><i/>{demoMode ? "演示数据" : connectionError ? "控制面离线" : "SQLite 控制面在线"}</span>
        <button className="outline-button" onClick={() => { setProposalPanelOpen(true); if (!proposal && proposals[0]) void loadProposal(proposals[0].id); }}>提案队列 · {proposals.length}</button>
        <button className="outline-button" onClick={() => void requestClassification()} disabled={proposalLoading}>{proposalLoading ? "生成中…" : "＋ 生成 AI 提案"}</button>
        <button className="primary-button compact" onClick={() => setDialog({ type: "library" })}>＋ 新建知识库</button>
      </div>
    </div>

    {connectionError && <div className="kb-error-banner"><b>V2 控制面不可用</b><span>{connectionError}</span><button onClick={() => void refreshCurrent()}>重试</button></div>}

    <section className="kb-overview-strip" aria-label="知识库概览">
      <div><small>知识库</small><b>{libraries.length}</b><span>独立集合与策略</span></div>
      <div><small>正式文档</small><b>{overview.documents}</b><span>稳定 Document ID</span></div>
      <div><small>未归类</small><b>{overview.unclassified}</b><span>等待人工或提案</span></div>
      <div><small>活动任务</small><b>{overview.queued}</b><span>重启后可恢复</span></div>
    </section>

    <section className="kb-workbench kb-workbench-v2">
      <aside className="library-rail" aria-label="知识库">
        <div className="rail-head"><span>LIBRARIES</span><button onClick={() => setDialog({ type: "library" })} title="新建知识库">＋</button></div>
        <div className="library-list">
          {libraries.map((library) => <button key={library.id} className={`library-item ${activeId === library.id ? "active" : ""}`} onClick={() => chooseLibrary(library.id)}>
            <span className="library-mark">{libraryMark(library)}</span>
            <span className="library-copy"><b>{library.name}</b><small>{library.policy}</small></span>
            <span className="library-stats"><b>{library.document_count}</b>{library.unclassified_count > 0 && <i>{library.unclassified_count}</i>}</span>
          </button>)}
        </div>
        <div className="rail-health">
          <span><i className="ok"/>目录版本</span><b>v{treeVersion}</b>
          <span><i className={jobs.some((job) => job.state === "queued") ? "busy" : "ok"}/>任务队列</span><b>{jobs.length}</b>
        </div>
        <p className="rail-note">跨库移动需要建立新的索引修订；同库目录移动只更新过滤元数据。</p>
      </aside>

      <aside className="taxonomy-pane">
        <header className="taxonomy-head">
          <div><span className="section-kicker">TAXONOMY</span><h2>{activeLibrary.name}</h2></div>
          <button onClick={() => setDialog({ type: "node", parentId: selectedNodeId })} title="在当前目录下新建">＋</button>
        </header>
        <div className="taxonomy-tools">
          <button onClick={() => setExpanded(new Set(allNodes.map((node) => node.id)))}>全部展开</button>
          <button onClick={() => setExpanded(new Set())}>折叠</button>
          <button disabled={!selectedNode} onClick={() => { if (selectedNode) { setNodeDraft({ name: selectedNode.name, description: selectedNode.description, kind: selectedNode.kind }); setDialog({ type: "edit-node", node: selectedNode }); } }}>编辑</button>
        </div>
        <div className="tree-scroll-v2">
          {loading ? <div className="kb-empty">正在读取目录…</div> : tree.length > 0 ? <TreeBranch nodes={tree} depth={0} expanded={expanded} selected={selectedNodeId} onToggle={toggleNode} onSelect={setSelectedNodeId} onMove={(source, target) => void moveNode(source, target)}/> : <div className="kb-empty">这个知识库还没有目录</div>}
        </div>
        <div className="taxonomy-footer">
          <button onClick={() => setDialog({ type: "node", parentId: selectedNodeId })}>＋ 新建子目录</button>
          <button className="danger-text" disabled={!selectedNode || selectedNode.is_unclassified} onClick={() => void archiveSelectedNode()}>归档</button>
        </div>
      </aside>

      <main className="document-workspace">
        <header className="document-toolbar">
          <div>
            <span className="section-kicker">DOCUMENTS</span>
            <h2>{selectedNode?.name ?? activeLibrary.name}<small>{documents.length} 项</small></h2>
          </div>
          <div className="document-tools">
            <label className="document-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索当前目录及子目录"/></label>
            <button onClick={() => void refreshCurrent()} title="刷新">↻</button>
          </div>
        </header>

        {selectedDocuments.size > 0 && <div className="bulk-action-bar">
          <b>已选择 {selectedDocuments.size} 项</b>
          <select value={bulkTarget} onChange={(event) => setBulkTarget(event.target.value)}>
            <option value="">选择目标目录</option>
            {allNodes.filter((node) => node.kind === "physical").map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}
          </select>
          <button onClick={() => void moveSelectedDocuments()} disabled={!bulkTarget}>移动</button>
          <button onClick={() => setSelectedDocuments(new Set())}>取消选择</button>
        </div>}

        {proposal && <div className="proposal-banner proposal-banner-v2">
          <span className="proposal-pulse"/>
          <div><b>AI 提案 · {proposal.status}</b><p>{proposal.items.length} 项建议 · {proposal.approved_count ?? proposal.items.filter((item) => item.status === "approved").length} 项已批准 · {proposal.llm_model || "规则引擎"}</p></div>
          <button onClick={() => setProposalPanelOpen(true)}>逐项审核</button>
          <button onClick={() => setProposal(null)}>关闭</button>
        </div>}

        <div className="document-table-wrap">
          <table className="document-table">
            <thead><tr><th className="check-cell"><input type="checkbox" aria-label="选择全部" checked={documents.length > 0 && selectedDocuments.size === documents.length} onChange={(event) => setSelectedDocuments(event.target.checked ? new Set(documents.map((document) => document.id)) : new Set())}/></th><th>名称</th><th>状态</th><th>主目录</th><th>标签</th><th>索引</th><th>更新时间</th></tr></thead>
            <tbody>
              {documents.map((document) => <tr key={document.id} className={focusedDocument?.id === document.id ? "focused" : ""} onClick={() => setFocusedDocument(document)}>
                <td className="check-cell" onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`选择 ${document.title}`} checked={selectedDocuments.has(document.id)} onChange={(event) => setSelectedDocuments((current) => { const next = new Set(current); if (event.target.checked) next.add(document.id); else next.delete(document.id); return next; })}/></td>
                <td><div className="document-name"><span>{document.mime_type.includes("pdf") ? "PDF" : document.mime_type.includes("json") ? "{}" : "MD"}</span><p><b>{document.title}</b><small>{document.source_name || document.source_path || "手动记录"}</small></p></div></td>
                <td><span className={`status-pill status-${document.status}`}>{document.status === "unclassified" ? "未归类" : document.status === "active" ? "有效" : document.status === "archived" ? "归档" : "回收站"}</span></td>
                <td>{document.primary_node_name ?? "—"}</td>
                <td><div className="tag-stack">{document.tags.slice(0, 2).map((tag) => <span key={tag.id}>{tag.name}</span>)}{document.tags.length > 2 && <i>+{document.tags.length - 2}</i>}</div></td>
                <td><span className={`index-dot index-${document.index_status}`}/>{document.index_status}</td>
                <td>{formatTime(document.updated_at)}</td>
              </tr>)}
              {documents.length === 0 && <tr><td colSpan={7}><div className="document-empty"><span>◇</span><b>当前范围没有文档</b><p>可从下方摄取文件，或选择另一个目录。</p></div></td></tr>}
            </tbody>
          </table>
        </div>
      </main>

      <aside className="detail-drawer detail-drawer-v2">
        {focusedDocument ? <>
          <header><span className="section-kicker">DOCUMENT INSPECTOR</span><h2>{focusedDocument.title}</h2><p>{focusedDocument.source_path || "手动创建的知识记录"}</p></header>
          <div className="inspector-status-row">
            <label><span>生命周期</span><select value={focusedDocument.status} onChange={(event) => void updateFocusedDocument({ status: event.target.value })}><option value="unclassified">未归类</option><option value="active">有效</option><option value="archived">归档</option><option value="trash">回收站</option></select></label>
            <label><span>索引状态</span><b>{focusedDocument.index_status}</b></label>
          </div>
          <dl className="drawer-meta">
            <div><dt>Document ID</dt><dd><code>{focusedDocument.id}</code></dd></div>
            <div><dt>主归属</dt><dd>{focusedDocument.primary_node_name ?? "—"}</dd></div>
            <div><dt>版本</dt><dd>rev {focusedDocument.revision}</dd></div>
            <div><dt>内容哈希</dt><dd><code>{focusedDocument.content_hash || "尚未计算"}</code></dd></div>
          </dl>
          <section className="drawer-section"><h3>标签</h3><div className="inspector-tags">{focusedDocument.tags.map((tag) => <span key={tag.id}>{tag.name}</span>)}{focusedDocument.tags.length === 0 && <small>尚无标签</small>}</div><div className="inline-editor"><input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="输入或复用标签"/><button onClick={() => void createAndAssignTag()}>添加</button></div></section>
          <section className="drawer-section"><h3>目录别名</h3><div className="alias-list">{focusedDocument.aliases.map((alias) => <span key={alias.id}>↗ {alias.name}</span>)}{focusedDocument.aliases.length === 0 && <small>没有跨目录引用</small>}</div><div className="inline-editor"><select value={aliasTarget} onChange={(event) => setAliasTarget(event.target.value)}><option value="">选择目录</option>{allNodes.filter((node) => node.kind === "physical" && node.id !== focusedDocument.primary_node_id).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</select><button onClick={() => void addAlias()} disabled={!aliasTarget}>引用</button></div></section>
        </> : selectedNode ? <>
          <header><span className="section-kicker">NODE INSPECTOR</span><h2>{selectedNode.name}</h2><p>{selectedNode.description || "当前目录没有说明"}</p></header>
          <dl className="drawer-meta"><div><dt>节点 ID</dt><dd><code>{selectedNode.id}</code></dd></div><div><dt>直接文档</dt><dd>{selectedNode.direct_count}</dd></div><div><dt>子树文档</dt><dd>{selectedNode.subtree_count}</dd></div><div><dt>节点类型</dt><dd>{selectedNode.kind}</dd></div><div><dt>目录版本</dt><dd>v{treeVersion}</dd></div></dl>
          <section className="drawer-section"><h3>操作提示</h3><ul><li>拖拽目录到另一个目录即可移动分支</li><li>主归属唯一，别名不会复制向量</li><li>归档分支会把文档移入未归类</li></ul></section>
          <section className="drawer-section relation-preview"><h3>最近审计</h3>{audit.slice(0, 4).map((event) => <p key={event.id}><span>{formatTime(event.created_at)}</span>{event.action} · {event.target_type}</p>)}{audit.length === 0 && <small>暂无审计事件</small>}</section>
        </> : <div className="kb-empty">请选择一个目录或文档</div>}
      </aside>
    </section>

    {activeLibrary.kind !== "association" && <section className="ingest-dock ingest-dock-v2">
      <div><span className="section-kicker">PERSISTENT INGEST QUEUE</span><h2>摄取文件或扫描目录</h2><p>路径必须位于服务端 `RAG_INGEST_ROOTS` 允许范围。任务写入 SQLite，不再制造零向量知识块。</p></div>
      <label><span>WSL 文件或目录路径</span><input value={ingestPath} onChange={(event) => setIngestPath(event.target.value)}/></label>
      <label><span>目标目录</span><select value={selectedNodeId ?? ""} onChange={(event) => setSelectedNodeId(event.target.value)}>{allNodes.filter((node) => node.kind === "physical").map((node) => <option value={node.id} key={node.id}>{node.name}</option>)}</select></label>
      <button className="primary-button compact" onClick={() => void enqueueIngest()}>加入任务队列</button>
    </section>}

    {proposalPanelOpen && <div className="proposal-review-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setProposalPanelOpen(false); }}>
      <section className="proposal-review-panel" role="dialog" aria-modal="true" aria-label="AI 分类提案审核">
        <header className="proposal-review-head">
          <div><span className="section-kicker">VERSION-LOCKED AI PROPOSALS</span><h2>AI 分类提案审核</h2><p>每项单独批准或拒绝；应用前会再次检查文档版本、修订号和目录位置。</p></div>
          <button onClick={() => setProposalPanelOpen(false)} aria-label="关闭提案审核">×</button>
        </header>
        <div className="proposal-review-layout">
          <aside className="proposal-history">
            <div className="proposal-history-head"><b>提案历史</b><button onClick={() => void requestClassification()} disabled={proposalLoading}>＋ 新建</button></div>
            {proposals.map((entry) => <button key={entry.id} className={proposal?.id === entry.id ? "active" : ""} onClick={() => void loadProposal(entry.id)}>
              <span><b>{entry.llm_model || "classifier"}</b><i className={`proposal-status status-${entry.status}`}>{entry.status}</i></span>
              <small>{formatTime(entry.created_at)} · {entry.item_count} 项 · {entry.approved_count} 已批准</small>
            </button>)}
            {proposals.length === 0 && <div className="proposal-history-empty">尚无持久化提案。<br/>点击“新建”扫描未归类文件。</div>}
          </aside>
          <main className="proposal-review-main">
            {proposalLoading && !proposal ? <div className="kb-empty">正在读取提案…</div> : proposal ? <>
              <div className="proposal-summary">
                <div><small>提案状态</small><b>{proposal.status}</b></div>
                <div><small>分类器</small><b>{proposal.llm_model || "unknown"}</b></div>
                <div><small>待审核</small><b>{proposal.items.filter((item) => item.status === "pending").length}</b></div>
                <div><small>Token</small><b>{(proposal.prompt_tokens ?? 0) + (proposal.completion_tokens ?? 0)}</b></div>
              </div>
              <div className="proposal-item-list">
                {proposal.items.map((item, index) => {
                  const versionConflict = item.live_version_id !== undefined && item.live_version_id !== item.version_id;
                  const busy = proposalAction.endsWith(item.id);
                  return <article className={`proposal-item-card item-${item.status} ${versionConflict ? "has-conflict" : ""}`} key={item.id}>
                    <div className="proposal-item-index">{String(index + 1).padStart(2, "0")}</div>
                    <div className="proposal-item-copy">
                      <header><b>{item.document_title || item.document_source_name || item.document_id}</b><span>{Math.round(item.confidence * 100)}%</span></header>
                      <p><span>{item.source_node_name || item.source_node_id}</span><i>→</i><strong>{item.target_node_name || item.target_node_id}</strong></p>
                      <small>{item.llm_reasoning || item.reason_code || "分类器未提供额外说明"}</small>
                      {versionConflict && <em>版本冲突：文档已在提案生成后更新，必须重新生成提案。</em>}
                    </div>
                    <div className="proposal-item-actions">
                      <i className={`proposal-status status-${item.status}`}>{item.status}</i>
                      {item.status === "pending" && <>
                        <button className="approve" disabled={busy || versionConflict} onClick={() => void reviewProposalItem(item.id, "approve")}>{busy ? "处理中" : "批准"}</button>
                        <button className="reject" disabled={busy} onClick={() => void reviewProposalItem(item.id, "reject")}>拒绝</button>
                      </>}
                    </div>
                  </article>;
                })}
                {proposal.items.length === 0 && <div className="kb-empty">分类器没有生成可审核项；请检查校验日志或调整目录说明。</div>}
              </div>
              <footer className="proposal-review-footer">
                <p>应用操作是单个 SQLite 事务；任意一项过期，整个批次都不会移动。</p>
                {proposal.status === "applied" ? <button className="outline-button" disabled={proposalAction === "revert"} onClick={() => void transitionProposal("revert")}>{proposalAction === "revert" ? "撤销校验中…" : "安全撤销"}</button> : <button className="primary-button compact" disabled={proposalAction === "apply" || !proposal.items.some((item) => item.status === "approved")} onClick={() => void transitionProposal("apply")}>{proposalAction === "apply" ? "冲突校验与应用中…" : "应用所有已批准项"}</button>}
              </footer>
            </> : <div className="kb-empty">从左侧选择一个提案，或新建分类提案。</div>}
          </main>
        </div>
      </section>
    </div>}

    {dialog && <div className="kb-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(null); }}>
      {dialog.type === "library" ? <form className="kb-modal" onSubmit={createLibrary}>
        <header><div><span className="section-kicker">NEW LIBRARY</span><h2>创建独立知识库</h2></div><button type="button" onClick={() => setDialog(null)}>×</button></header>
        <label><span>名称</span><input required value={libraryDraft.name} onChange={(event) => setLibraryDraft({ ...libraryDraft, name: event.target.value })} placeholder="例如：工程资料"/></label>
        <label><span>稳定 ID（可留空）</span><input value={libraryDraft.id} onChange={(event) => setLibraryDraft({ ...libraryDraft, id: event.target.value.toLowerCase() })} placeholder="engineering" pattern="[a-z0-9][a-z0-9-]{1,62}"/></label>
        <label><span>类型</span><select value={libraryDraft.kind} onChange={(event) => setLibraryDraft({ ...libraryDraft, kind: event.target.value })}><option value="document">文档库</option><option value="association">关联库</option></select></label>
        <label><span>用途说明</span><textarea value={libraryDraft.description} onChange={(event) => setLibraryDraft({ ...libraryDraft, description: event.target.value })}/></label>
        <footer><button type="button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" type="submit">创建知识库</button></footer>
      </form> : <form className="kb-modal" onSubmit={submitNode}>
        <header><div><span className="section-kicker">{dialog.type === "node" ? "NEW NODE" : "EDIT NODE"}</span><h2>{dialog.type === "node" ? "创建目录" : `编辑 ${dialog.node.name}`}</h2></div><button type="button" onClick={() => setDialog(null)}>×</button></header>
        <label><span>目录名称</span><input required value={nodeDraft.name} onChange={(event) => setNodeDraft({ ...nodeDraft, name: event.target.value })}/></label>
        <label><span>节点类型</span><select value={nodeDraft.kind} onChange={(event) => setNodeDraft({ ...nodeDraft, kind: event.target.value })}><option value="physical">实体目录</option><option value="smart">智能目录</option><option value="alias">目录快捷入口</option></select></label>
        <label><span>用途与分类边界</span><textarea value={nodeDraft.description} onChange={(event) => setNodeDraft({ ...nodeDraft, description: event.target.value })} placeholder="说明哪些内容应该进入这里"/></label>
        <footer><button type="button" onClick={() => setDialog(null)}>取消</button><button className="primary-button" type="submit">保存目录</button></footer>
      </form>}
    </div>}
  </div>;
}
