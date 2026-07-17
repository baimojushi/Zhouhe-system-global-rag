"use client";

import { useMemo, useState, useEffect } from "react";

type LibraryId = "ai-work" | "academic" | "production" | "notes" | "association";
type TreeNode = { id: string; label: string; count: number; hint?: string; children?: TreeNode[] };
type LibraryDefinition = {
  id: LibraryId;
  mark: string;
  name: string;
  subtitle: string;
  count: number;
  unclassified: number;
  collection: string;
  policy: string;
  description: string;
};

const libraryMeta: Record<LibraryId, Omit<LibraryDefinition, "count" | "unclassified">> = {
  "ai-work": { id: "ai-work", mark: "AI", name: "AI 工作记录", subtitle: "会话、实验与决策", collection: "kb_ai_work_v1", policy: "private · session-aware", description: "保存模型实验、提示词版本、工作日志与可复用决策；按项目、模型和时间组织。" },
  "academic": { id: "academic", mark: "AC", name: "学术资料", subtitle: "论文、书籍与引用", collection: "kb_academic_v1", policy: "research · citation-first", description: "强调作者、年份、DOI、版本和引用链，目录树按领域与研究问题逐步演化。" },
  "production": { id: "production", mark: "PR", name: "生产文档", subtitle: "SOP、部署与故障", collection: "kb_production_v1", policy: "team · recency-weighted", description: "强调版本有效期、责任人、环境与变更记录，过期内容不参与默认回答。" },
  "notes": { id: "notes", mark: "NT", name: "个人思维笔记", subtitle: "灵感、观察与草稿", collection: "kb_notes_v1", policy: "owner-only · exploratory", description: "允许弱结构、交叉标签和持续生长的主题分支，不强迫每条笔记只有一个位置。" },
  "association": { id: "association", mark: "∿", name: "关联知识库", subtitle: "跨库潜在关系", collection: "kb_association_v1", policy: "edge-only · cross-library", description: "只保存跨库关系、证据指针和置信度，不复制原文；用于发现支持、冲突、类比和反常组合。" },
};

// Predefined tree structures (served from backend /v1/libraries/{id}/tree)
const PREDEFINED_TREES: Record<LibraryId, TreeNode[]> = {
  "ai-work": [
    { id: "ai-unclassified", label: "未归类", count: 0, hint: "新文件入口" },
    { id: "ai-projects", label: "项目", count: 0, children: [
      { id: "ai-rag", label: "Global RAG", count: 0, children: [{ id: "ai-rag-design", label: "设计决策", count: 0 }, { id: "ai-rag-debug", label: "调试记录", count: 0 }, { id: "ai-rag-prompts", label: "提示词版本", count: 0 }] },
      { id: "ai-agents", label: "Agent 实验", count: 0 },
      { id: "ai-automation", label: "自动化工作流", count: 0 },
    ] },
    { id: "ai-models", label: "模型评测", count: 0, children: [{ id: "ai-closed", label: "闭源 API", count: 0 }, { id: "ai-local", label: "本地模型", count: 0 }] },
    { id: "ai-decisions", label: "跨项目决策", count: 0 },
  ],
  academic: [
    { id: "ac-unclassified", label: "未归类", count: 0, hint: "等待路由卡" },
    { id: "ac-cs", label: "计算机科学", count: 0, children: [{ id: "ac-ir", label: "信息检索", count: 0, children: [{ id: "ac-hybrid", label: "混合检索", count: 0 }, { id: "ac-rerank", label: "重排序", count: 0 }] }, { id: "ac-llm", label: "语言模型", count: 0 }, { id: "ac-hci", label: "人机交互", count: 0 }] },
    { id: "ac-cog", label: "认知科学", count: 0 },
    { id: "ac-method", label: "研究方法", count: 0 },
  ],
  production: [
    { id: "pr-unclassified", label: "未归类", count: 0, hint: "需确认环境" },
    { id: "pr-platform", label: "平台与基础设施", count: 0, children: [{ id: "pr-wsl", label: "WSL2", count: 0 }, { id: "pr-llamacpp", label: "llama.cpp / Gemma", count: 0 }, { id: "pr-vector", label: "向量数据库", count: 0 }] },
    { id: "pr-sop", label: "标准作业流程", count: 0 },
    { id: "pr-incidents", label: "故障与复盘", count: 0, children: [{ id: "pr-oom", label: "GPU / OOM", count: 0 }, { id: "pr-index", label: "索引异常", count: 0 }] },
    { id: "pr-archive", label: "历史版本", count: 0 },
  ],
  notes: [
    { id: "nt-unclassified", label: "未归类", count: 0, hint: "允许长期停留" },
    { id: "nt-systems", label: "系统与复杂性", count: 0, children: [{ id: "nt-emergence", label: "涌现", count: 0 }, { id: "nt-feedback", label: "反馈回路", count: 0 }] },
    { id: "nt-making", label: "创造与方法", count: 0 },
    { id: "nt-observation", label: "观察记录", count: 0 },
    { id: "nt-seeds", label: "尚未成形的种子", count: 0 },
  ],
  association: [
    { id: "as-candidate", label: "候选关联", count: 0, hint: "等待人工确认" },
    { id: "as-support", label: "相互支持", count: 0, children: [{ id: "as-support-direct", label: "直接证据", count: 0 }, { id: "as-support-analogy", label: "跨域类比", count: 0 }] },
    { id: "as-conflict", label: "冲突与例外", count: 0, children: [{ id: "as-version", label: "版本冲突", count: 0 }, { id: "as-counter", label: "反例", count: 0 }] },
    { id: "as-causal", label: "因果与条件", count: 0 },
    { id: "as-counterintuitive", label: "反直觉假设", count: 0, hint: "只作为待验证结论" },
  ],
};

function findNode(nodes: TreeNode[], id: string): TreeNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = node.children ? findNode(node.children, id) : undefined;
    if (child) return child;
  }
}

interface ProposalData {
  change_set_id: string;
  status: string;
  operations: Array<{ op: string; file_id: string; target_node_id: string; confidence: number; reason_code: string }>;
  holds: Array<{ file_id: string; confidence: number; reason_code: string }>;
  taxonomy_version: number;
  model_provider?: string;
  routing_cards_count?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
}

function TreeBranch({ nodes, depth, expanded, selected, onToggle, onSelect }: { nodes: TreeNode[]; depth: number; expanded: Set<string>; selected: string; onToggle: (id: string) => void; onSelect: (id: string) => void }) {
  return <div className="tree-level" role={depth === 0 ? "tree" : "group"}>{nodes.map((node) => {
    const hasChildren = Boolean(node.children?.length);
    const isOpen = expanded.has(node.id);
    return <div className="tree-branch" key={node.id}>
      <button className={`tree-node ${selected === node.id ? "selected" : ""}`} style={{ "--tree-depth": depth } as React.CSSProperties} onClick={() => { onSelect(node.id); if (hasChildren) onToggle(node.id); }} role="treeitem" aria-selected={selected === node.id} aria-expanded={hasChildren ? isOpen : undefined}>
        <span className={`tree-chevron ${hasChildren ? "has-children" : ""}`}>{hasChildren ? (isOpen ? "−" : "+") : "·"}</span>
        <span className="tree-folder">{hasChildren ? "▱" : "◇"}</span>
        <span className="tree-label"><b>{node.label}</b>{node.hint && <small>{node.hint}</small>}</span>
        <span className="tree-count">{node.count}</span>
      </button>
      {hasChildren && isOpen && <TreeBranch nodes={node.children!} depth={depth + 1} expanded={expanded} selected={selected} onToggle={onToggle} onSelect={onSelect}/>}
    </div>;
  })}</div>;
}

function confidenceColor(c: number): string {
  if (c >= 0.88) return "color: var(--green); font-weight: 700;";
  if (c >= 0.65) return "";
  return "color: var(--vermilion);";
}

export function KnowledgeWorkbench({ demoMode, gatewayUrl, apiKey, onNotice }: { demoMode: boolean; gatewayUrl: string; apiKey: string; onNotice: (message: string) => void }) {
  const [activeId, setActiveId] = useState<LibraryId>("ai-work");
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["ai-projects", "ai-rag"]));
  const [selectedNode, setSelectedNode] = useState("ai-unclassified");
  const [ingestPath, setIngestPath] = useState("/opt/global-rag/kb/inbox");
  const [proposalState, setProposalState] = useState<"idle" | "running" | "preview">("idle");
  const [proposalData, setProposalData] = useState<ProposalData | null>(null);
  const [libraries, setLibraries] = useState<LibraryDefinition[]>([]);
  const [treeVersion, setTreeVersion] = useState<number>(1);

  useEffect(() => {
    if (demoMode) return;
    let cancelled = false;
    async function loadLibraries() {
      try {
        const resp = await fetch(`${gatewayUrl.replace(/\/$/, "")}/v1/libraries`, {
          headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
        });
        if (!resp.ok) return;
        const data = await resp.json() as { libraries: Array<{ library_id: string; document_count: number; taxonomy_version: number }> };
        if (cancelled) return;
        const merged = data.libraries.map((lib) => ({
          ...libraryMeta[lib.library_id as LibraryId],
          count: lib.document_count,
          unclassified: 0, // TODO: count unscoped chunks
        }));
        setLibraries(merged);
        const activeLib = data.libraries.find((l) => l.library_id === activeId);
        if (activeLib) setTreeVersion(activeLib.taxonomy_version);
      } catch { /* silently ignore */ }
    }
    loadLibraries();
    return () => { cancelled = true; };
  }, [demoMode, gatewayUrl, apiKey, activeId]);

  // Count unclassified files per library for the overview strip
  const overviewStats = useMemo(() => {
    const totalLibraries = libraries.length;
    const totalUnclassified = libraries.reduce((sum, lib) => sum + lib.unclassified, 0);
    return { totalLibraries, totalUnclassified };
  }, [libraries]);

  const activeLibrary = useMemo<LibraryDefinition>(() => {
    const found = libraries.find((item) => item.id === activeId);
    if (found) return found;
    // Fallback: static meta with defaults
    const meta = Object.values(libraryMeta).find((m) => m.id === activeId);
    return meta ? ({ ...meta, count: 0, unclassified: 0 } as LibraryDefinition) : ({ ...Object.values(libraryMeta)[0]!, count: 0, unclassified: 0 } as LibraryDefinition);
  }, [libraries, activeId]);
  const activeTree = PREDEFINED_TREES[activeId];
  const node = useMemo(() => findNode(activeTree, selectedNode) ?? activeTree[0], [activeTree, selectedNode]);
  const isAssociation = activeId === "association";

  function chooseLibrary(id: LibraryId) {
    setActiveId(id);
    setSelectedNode(PREDEFINED_TREES[id][0].id);
    setExpanded(new Set(PREDEFINED_TREES[id].filter((item) => item.children).slice(0, 1).map((item) => item.id)));
    setProposalState("idle");
    setProposalData(null);
  }

  function toggleNode(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function callGateway(path: string, body: Record<string, unknown>) {
    if (demoMode) {
      await new Promise((resolve) => window.setTimeout(resolve, 650));
      return null;
    }
    const response = await fetch(`${gatewayUrl.replace(/\/$/, "")}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`);
    return await response.json();
  }

  async function requestClassification() {
    if (isAssociation) {
      setProposalState("running");
      try {
        await callGateway("/v1/associations/discover", { source_scope: "all_document_libraries", mode: "candidate_only", max_hops: 1, edge_budget: 12 });
        onNotice("候选关联发现任务已提交；不会移动或复制原始文档");
      } catch (error) {
        onNotice(error instanceof Error ? error.message : "候选关联任务提交失败");
      } finally {
        setProposalState("idle");
      }
      return;
    }
    setProposalState("running");
    try {
      const result = await callGateway("/v1/taxonomy/proposals", {
        library_id: activeId,
        source_node: `${activeId}-unclassified`,
        mode: "preview",
        payload_mode: "routing_cards",
        taxonomy_scope: "affected_subtree",
        max_routing_cards: 20,
      }) as unknown as ProposalData;
      if (result) {
        setProposalData(result);
        setProposalState("preview");
        onNotice(`AI 归类提案已生成：${result.operations.length} 项移动 · ${result.holds.length} 项保留`);
      }
    } catch (error) {
      setProposalState("idle");
      onNotice(error instanceof Error ? error.message : "归类提案生成失败");
    }
  }

  async function applyProposal() {
    if (!proposalData) return;
    setProposalState("running");
    try {
      const resp = await fetch(`${gatewayUrl.replace(/\/$/, "")}/v1/taxonomy/proposals/${proposalData.change_set_id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
        body: JSON.stringify({ expected_taxonomy_version: treeVersion }),
      });
      if (!resp.ok) {
        const err = await resp.json() as { detail?: string };
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const result = await resp.json() as { applied_count: number; new_version: number };
      setTreeVersion(result.new_version);
      setProposalState("idle");
      setProposalData(null);
      onNotice(`已应用 ${result.applied_count} 项变更 · 目录版本 v${result.new_version}`);
    } catch (error) {
      setProposalState("idle");
      onNotice(error instanceof Error ? error.message : "应用提案失败");
    }
  }

  async function enqueueIngest() {
    try {
      await callGateway("/v1/ingest/path", { path: ingestPath, library_id: activeId, target_node: `${activeId}-unclassified`, classification: "manual-major-category" });
      onNotice(`目录已进入"${activeLibrary.name} / 未归类"`);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "加入队列失败");
    }
  }

  const opCount = proposalData?.operations.length ?? 0;
  const holdCount = proposalData?.holds.length ?? 0;

  return <div className="page inner-page knowledge-page">
    <div className="kb-title-row">
      <div className="page-title"><div className="eyebrow"><span/>KNOWLEDGE WORKBENCH</div><h1>知识库工作台</h1><p>大类由人决定；闭源 AI 只在点击后生成目录变更提案，确认前不移动任何文件。</p></div>
      <div className="kb-header-actions">
        <span className="isolation-badge"><i/>独立集合隔离</span>
        <button className="outline-button" onClick={requestClassification} disabled={proposalState === "running"}>{proposalState === "running" ? (isAssociation ? "正在发现关联" : "正在生成提案") : isAssociation ? "发现候选关联" : "AI 自动归类"}</button>
        <button className="primary-button compact" onClick={() => onNotice("新建知识库向导已预留后端接口")}>＋ 新建知识库</button>
      </div>
    </div>

    <section className="kb-overview-strip" aria-label="知识库概览">
      <div><small>独立知识库</small><b>{overviewStats.totalLibraries || 5}</b><span>4 文档库 · 1 关联库</span></div>
      <div><small>未归类</small><b>{overviewStats.totalUnclassified || 99}</b><span>仅存在预制大类中</span></div>
      <div><small>待复核提案</small><b>{opCount + holdCount}</b><span>{proposalState === "preview" ? "未应用" : "不会自动应用"}</span></div>
      <div><small>潜在关联</small><b>4,382</b><span>跨库边 · 不复制原文</span></div>
    </section>

    <section className="kb-workbench">
      <aside className="library-rail" aria-label="知识库分类">
        <div className="rail-head"><span>LIBRARIES</span><button title="新建知识库">＋</button></div>
        <div className="library-list">{libraries.map((library) => <button key={library.id} className={`library-item ${activeId === library.id ? "active" : ""}`} onClick={() => chooseLibrary(library.id)}>
          <span className="library-mark">{library.mark}</span><span className="library-copy"><b>{library.name}</b><small>{library.subtitle}</small></span><span className="library-stats"><b>{library.count.toLocaleString()}</b>{library.unclassified > 0 && <i>{library.unclassified}</i>}</span>
        </button>)}{libraries.length === 0 && Object.values(libraryMeta).map((library) => <button key={library.id} className={`library-item ${activeId === library.id ? "active" : ""}`} onClick={() => chooseLibrary(library.id as LibraryId)}>
          <span className="library-mark">{library.mark}</span><span className="library-copy"><b>{library.name}</b><small>{library.subtitle}</small></span><span className="library-stats"><b>—</b></span>
        </button>)}</div>
        <p className="rail-note">每个库使用独立 collection、权限策略与索引参数。跨库只通过关联库的证据指针连接。</p>
      </aside>

      <section className="tree-workspace">
        <header className="tree-toolbar">
          <div><span className="section-kicker">MULTI-LEVEL TAXONOMY</span><h2>{activeLibrary.name}</h2><p>{activeLibrary.description}</p></div>
          <div className="tree-tools"><button onClick={() => setExpanded(new Set(activeTree.map((item) => item.id)))}>展开一级</button><button onClick={() => setExpanded(new Set())}>折叠</button><button onClick={() => onNotice("目录编辑将以可撤销变更集提交")}>编辑树</button></div>
        </header>
        {proposalState === "preview" && proposalData && <div className="proposal-banner"><span className="proposal-pulse"/><div><b>归类提案 #{proposalData.change_set_id.slice(0, 20)}</b><p>{opCount} 项可直接归类 · {holdCount} 项低置信度保留 · {proposalData.model_provider || "规则引擎"}</p></div><button onClick={() => { setProposalState("idle"); setProposalData(null); }}>关闭预审</button></div>}
        <div className="tree-scroll"><TreeBranch nodes={activeTree} depth={0} expanded={expanded} selected={node.id} onToggle={toggleNode} onSelect={setSelectedNode}/></div>
        {!isAssociation && <div className="unclassified-queue"><div><span className="queue-mark">INBOX</span><p><b>{activeLibrary.unclassified} 个未归类文件</b><small>只发送路由卡和相关子树给远程 AI</small></p></div><div className="queue-files"><span>research-notes-0715.md</span><span>debug-session-42.json</span><span>paper-draft-v3.pdf</span></div></div>}
        {isAssociation && <div className="association-sample"><span className="queue-mark">EDGE SAMPLE</span><div><b>部署文档 / GPU 隔离</b><i>条件冲突 · 0.84</i><b>个人笔记 / 资源越多越慢</b></div><p>证据来自两个独立库；关系库只保存两端 ID、关系类型、置信度和证据切片 ID。</p></div>}
      </section>

      <aside className="detail-drawer">
        <div className="drawer-grip"/>
        <header><span className="section-kicker">DETAIL DRAWER</span><h2>{proposalState === "preview" ? "归类变更预审" : node.label}</h2><p>{proposalState === "preview" ? "远程模型返回结构化 JSON Patch；所有变更均可撤销。" : node.hint ?? activeLibrary.subtitle}</p></header>
        {proposalState === "preview" && proposalData ? <>
          <div className="proposal-list">
            {proposalData.operations.map((op, i) => <div key={`op-${i}`}>
              <span>{op.op.toUpperCase()}</span>
              <p><b>{op.file_id.replace("file-", "")}</b><small> → {op.target_node_id}</small></p>
              <em style={{ color: op.confidence >= 0.88 ? "var(--green)" : op.confidence >= 0.65 ? "inherit" : "var(--vermilion)", fontWeight: op.confidence >= 0.88 ? 700 : 400 }}>{op.confidence.toFixed(2)}</em>
            </div>)}
            {proposalData.holds.map((h, i) => <div className="needs-review" key={`hold-${i}`}>
              <span>HOLD</span>
              <p><b>{h.file_id.replace("file-", "")}</b><small>{h.reason_code}</small></p>
              <em style={{ color: "var(--vermilion)" }}>{h.confidence.toFixed(2)}</em>
            </div>)}
            {opCount === 0 && holdCount === 0 && <div style={{ color: "var(--ink-faint)", padding: "12px 0" }}>当前库没有未归类文件。</div>}
          </div>
          <div className="token-budget">
            <span>Token 消耗</span>
            <b>{proposalData.prompt_tokens ? `≈ ${Math.round((proposalData.prompt_tokens + (proposalData.completion_tokens ?? 0)) / 1000) * 1000} tokens` : "—"} tokens</b>
            <small>{proposalData.routing_cards_count || 0} 张路由卡 · {proposalData.model_provider || "—"}</small>
          </div>
          <div className="drawer-actions">
            <button onClick={() => { setProposalState("idle"); setProposalData(null); }}>取消</button>
            <button onClick={applyProposal}>应用高置信度变更</button>
          </div>
        </> : <>
          <dl className="drawer-meta"><div><dt>对象数量</dt><dd>{node.count}</dd></div><div><dt>向量集合</dt><dd><code>{activeLibrary.collection}</code></dd></div><div><dt>隔离策略</dt><dd>{activeLibrary.policy}</dd></div><div><dt>目录版本</dt><dd>v{treeVersion} · 可回滚</dd></div></dl>
          <section className="drawer-section"><h3>{isAssociation ? "关联约束" : "AI 管理边界"}</h3><ul>{isAssociation ? <><li>只保存跨库边和证据指针</li><li>默认检索只扩展一跳、最多 12 条边</li><li>反直觉结果必须标为"待验证假设"</li></> : <><li>首次大类由用户手动指定</li><li>仅点击后生成分类提案</li><li>低置信度文件继续留在未归类</li><li>目录移动保留审计日志和撤销点</li></>}</ul></section>
          <section className="drawer-section relation-preview"><h3>最近活动</h3><p><span>18:42</span> taxonomy v{treeVersion} 已发布</p><p><span>18:31</span> 6 个文件完成索引</p><p><span>17:58</span> 1 项变更已撤销</p></section>
        </>}
      </aside>
    </section>

    {!isAssociation && <section className="ingest-dock">
      <div><span className="section-kicker">MANUAL MAJOR CATEGORY</span><h2>先进入预制大类的"未归类"</h2><p>这里不触发远程 AI。解析、摘要和实体抽取先在本地完成，之后由你手动启动自动归类。</p></div>
      <label><span>本地目录</span><input value={ingestPath} onChange={(event) => setIngestPath(event.target.value)}/></label>
      <label><span>预制大类</span><select value={activeId} onChange={(event) => chooseLibrary(event.target.value as LibraryId)}>{libraries.length > 0 ? libraries.filter((item) => item.id !== "association").map((item) => <option value={item.id} key={item.id}>{item.name}</option>) : Object.values(libraryMeta).filter((item) => item.id !== "association").map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      <button className="primary-button compact" onClick={enqueueIngest}>加入未归类队列</button>
    </section>}
  </div>;
}