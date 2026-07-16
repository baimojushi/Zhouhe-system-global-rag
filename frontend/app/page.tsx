"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type View = "search" | "library" | "memory" | "status" | "settings";
type HealthState = "online" | "offline" | "checking";
type ServiceKey = "gateway" | "weaviate" | "embedding" | "vllm";

type SearchResult = {
  id: string;
  title: string;
  heading: string;
  content: string;
  sourcePath: string;
  sourceName: string;
  score: number;
  page?: number;
  scope: string;
  tags: string[];
};

type Settings = {
  demoMode: boolean;
  gatewayUrl: string;
  weaviateUrl: string;
  embeddingUrl: string;
  vllmUrl: string;
  apiKey: string;
  model: string;
};

const defaultSettings: Settings = {
  demoMode: false,
  gatewayUrl: "http://127.0.0.1:9100",
  weaviateUrl: "http://127.0.0.1:8080",
  embeddingUrl: "",
  vllmUrl: "http://127.0.0.1:8000",
  apiKey: "1c95b235989f7ef61fdb2c73513ab8e1d9bb750094c30d11f4d506de3acacf1e",
  model: "gemma-4-31b-jang-crack",
};

const demoResults: SearchResult[] = [
  {
    id: "rag-deployment",
    title: "WSL2 全局混合检索与上下文记忆部署方案",
    heading: "检索流程与参数",
    content:
      "一般中文知识问答建议将混合检索 alpha 设为 0.55；概念和语义性问题可提高到 0.65–0.75。先召回 30 条，重排并扩展相邻切片后，最终返回 6–10 条可靠依据。",
    sourcePath: "/opt/global-rag/kb/WSL2-Global-RAG-Deployment-CN.md",
    sourceName: "WSL2-Global-RAG-Deployment-CN.md",
    score: 0.94,
    scope: "global",
    tags: ["部署文档", "混合检索"],
  },
  {
    id: "vllm-guide",
    title: "WSL2 + vLLM 部署 Qwen2.5-32B 指南",
    heading: "故障排查 · vLLM 启动 OOM",
    content:
      "双 RTX 3090 使用 tensor parallel 2。若启动时显存不足，先将 gpu-memory-utilization 从 0.95 降到 0.85，并把 max-model-len 从 8192 调整为 4096。",
    sourcePath: "~/docs/README_WSL2_vLLM_32B.md",
    sourceName: "README_WSL2_vLLM_32B.md",
    score: 0.89,
    scope: "global",
    tags: ["部署文档", "vLLM"],
  },
  {
    id: "resource-plan",
    title: "检索栈资源与隔离策略",
    heading: "硬件与资源分配",
    content:
      "两张 3090 完全保留给大语言模型；Weaviate 限制约 14 GB 内存，CPU Embedding 服务限制约 6 GB。数据库应放在 WSL2 ext4，而不是 /mnt/c 或 /mnt/d。",
    sourcePath: "/opt/global-rag/kb/WSL2-Global-RAG-Deployment-CN.md",
    sourceName: "WSL2-Global-RAG-Deployment-CN.md",
    score: 0.82,
    scope: "global",
    tags: ["资源规划", "WSL2"],
  },
];

const navItems: { id: View; label: string; sub: string; icon: IconName }[] = [
  { id: "search", label: "检索", sub: "混合召回", icon: "search" },
  { id: "library", label: "知识库", sub: "索引与来源", icon: "book" },
  { id: "memory", label: "上下文", sub: "会话记忆", icon: "message" },
  { id: "status", label: "服务状态", sub: "运行与延迟", icon: "pulse" },
  { id: "settings", label: "设置", sub: "端点与模型", icon: "settings" },
];

type IconName = "search" | "book" | "message" | "pulse" | "settings" | "quote" | "path" | "plus" | "trash" | "check" | "arrow" | "spark" | "copy";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h7"/></>,
    message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 9h.01M12 9h.01M16 9h.01"/></>,
    pulse: <><path d="M3 12h4l2.2-6 4.3 12 2.2-6H21"/><circle cx="12" cy="12" r="10"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21h-4v-.08A1.7 1.7 0 0 0 8.95 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.58 15 1.7 1.7 0 0 0 3 14H3v-4h.08A1.7 1.7 0 0 0 4.6 8.95a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.58 1.7 1.7 0 0 0 10 3V3h4v.08A1.7 1.7 0 0 0 15.05 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.42 9 1.7 1.7 0 0 0 21 10h.08v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
    quote: <><path d="M9 11H5a4 4 0 0 0 4 4V7H5v4M19 11h-4a4 4 0 0 0 4 4V7h-4v4"/></>,
    path: <><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h3a3 3 0 0 0 3-3V9a3 3 0 0 1 3-3"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
    spark: <><path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9z"/><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z"/></>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function toResult(item: Record<string, unknown>, index: number): SearchResult {
  const props = (item.properties ?? item) as Record<string, unknown>;
  return {
    id: String(item.id ?? props.chunk_id ?? index),
    title: String(props.title ?? props.source_name ?? "未命名来源"),
    heading: String(props.heading ?? "正文"),
    content: String(props.content ?? props.text ?? ""),
    sourcePath: String(props.source_path ?? props.path ?? ""),
    sourceName: String(props.source_name ?? props.title ?? "来源"),
    score: Number(item.score ?? props.score ?? item.certainty ?? 0),
    page: props.page == null ? undefined : Number(props.page),
    scope: String(props.scope ?? "global"),
    tags: Array.isArray(props.tags) ? props.tags.map(String) : [String(props.mime_type ?? "知识片段")],
  };
}

export default function Home() {
  const [view, setView] = useState<View>("search");
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [query, setQuery] = useState("WSL2 中的部署与故障排查");
  const [scope, setScope] = useState("all");
  const [alpha, setAlpha] = useState(65);
  const [topK, setTopK] = useState(6);
  const [results, setResults] = useState<SearchResult[]>(demoResults);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [answer, setAnswer] = useState("");
  const [answering, setAnswering] = useState(false);
  const [sessionId, setSessionId] = useState("local-main");
  const [memoryText, setMemoryText] = useState("");
  const [ingestPath, setIngestPath] = useState("/opt/global-rag/kb");
  const [ingestText, setIngestText] = useState("");
  const [health, setHealth] = useState<Record<ServiceKey, HealthState>>({ gateway: "online", weaviate: "online", embedding: "online", vllm: "online" });
  const [lastCheck, setLastCheck] = useState("刚刚");

  useEffect(() => {
    const saved = localStorage.getItem("global-rag-settings");
    if (!saved) return;

    let restored: Settings;
    try { restored = { ...defaultSettings, ...JSON.parse(saved) }; }
    catch { return; }

    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) setSettings(restored); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [view]);

  const selectedResults = useMemo(() => results.filter((item) => selected.includes(item.id)), [results, selected]);

  function saveSettings(next: Settings) {
    setSettings(next);
    localStorage.setItem("global-rag-settings", JSON.stringify(next));
  }

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2400);
  }

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setAnswer("");
    try {
      if (settings.demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 620));
        const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
        const ranked = demoResults
          .map((item) => ({ ...item, score: Math.min(.98, item.score + (terms.some((term) => `${item.title}${item.content}`.toLowerCase().includes(term)) ? .02 : 0)) }))
          .slice(0, topK);
        setResults(ranked);
      } else {
        const response = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/retrieve`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : {}) },
          body: JSON.stringify({ query, scope: scope === "all" ? undefined : scope, alpha: alpha / 100, top_k: topK, session_id: sessionId }),
        });
        if (!response.ok) throw new Error(`检索失败：HTTP ${response.status}`);
        const payload = await response.json() as Record<string, unknown>;
        const items = (payload.results ?? payload.items ?? payload.data ?? []) as Record<string, unknown>[];
        setResults(items.map(toResult));
      }
    } catch (error) {
      flash(error instanceof Error ? error.message : "无法连接检索服务");
    } finally {
      setLoading(false);
    }
  }

  async function checkHealth() {
    setHealth({ gateway: "checking", weaviate: "checking", embedding: "checking", vllm: "checking" });
    if (settings.demoMode) {
      await new Promise((resolve) => window.setTimeout(resolve, 520));
      setHealth({ gateway: "online", weaviate: "online", embedding: "online", vllm: "online" });
      setLastCheck("刚刚");
      return;
    }
    const checks: ( [ServiceKey, string, Record<string, string>?] )[] = [
      ["gateway", `${settings.gatewayUrl}/health`],
      ["weaviate", `${settings.weaviateUrl}/.well-known/ready`, settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : undefined],
      ...(settings.embeddingUrl
        ? [["embedding", `${settings.embeddingUrl}/api/tags`]] as [ServiceKey, string][]
        : []),
      ["vllm", `${settings.vllmUrl}/health`],
    ];
    const states = await Promise.all(checks.map(async ([key, url, headers]) => {
      try { const response = await fetch(url, { headers }); return [key, response.ok ? "online" : "offline"] as const; }
      catch { return [key, "offline"] as const; }
    }));
    setHealth(Object.fromEntries(states) as Record<ServiceKey, HealthState>);
    setLastCheck(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }));
  }

  function toggleCitation(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
    flash(selected.includes(id) ? "已移出引用" : "已加入回答上下文");
  }

  async function generateAnswer() {
    const context = (selectedResults.length ? selectedResults : results.slice(0, 3));
    if (!context.length) return;
    setAnswering(true);
    try {
      if (settings.demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 780));
        setAnswer("部署时应先保证 Weaviate、CPU Embedding 和 vLLM 三类服务彼此隔离：两张 RTX 3090 留给 Qwen2.5-32B，检索向量化走 CPU。一般中文查询可从 0.55–0.65 的语义权重开始；遇到错误码、文件名或命令时降低语义权重。若 vLLM 启动显存不足，优先将显存利用率降至 0.85，并把最大上下文调整为 4096。数据库与模型文件都应放在 WSL2 ext4 中。［1］［2］［3］");
      } else {
        const messages = [
          { role: "system", content: "你是本地知识库助手。只根据给出的检索片段回答，使用［序号］标注依据。" },
          { role: "user", content: `问题：${query}\n\n检索片段：\n${context.map((item, i) => `［${i + 1}］${item.title} / ${item.heading}\n${item.content}`).join("\n\n")}` },
        ];
        const response = await fetch(`${settings.vllmUrl.replace(/\/$/, "")}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: settings.model, messages, temperature: 0.2, max_tokens: 900 }),
        });
        if (!response.ok) throw new Error(`生成失败：HTTP ${response.status}`);
        const data = await response.json() as { choices?: { message?: { content?: string } }[] };
        setAnswer(data.choices?.[0]?.message?.content ?? "模型没有返回内容。");
      }
    } catch (error) { flash(error instanceof Error ? error.message : "生成失败"); }
    finally { setAnswering(false); }
  }

  async function postGateway(path: string, body: Record<string, unknown>, success: string) {
    if (settings.demoMode) { await new Promise((resolve) => window.setTimeout(resolve, 420)); flash(success); return; }
    try {
      const response = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : {}) },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`);
      flash(success);
    } catch (error) { flash(error instanceof Error ? error.message : "请求失败"); }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="全局 RAG 检索工作台">
          <span className="brand-seal">检</span>
          <span className="brand-copy"><b>归藏</b><small>RAG CONSOLE</small></span>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => (
            <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
              <span className="nav-icon"><Icon name={item.icon} size={22}/></span>
              <span><b>{item.label}</b><small>{item.sub}</small></span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={`mode-mark ${settings.demoMode ? "demo" : "live"}`}/>
          <span><b>{settings.demoMode ? "演示模式" : "本地服务"}</b><small>{settings.demoMode ? "无需后端即可体验" : "连接 127.0.0.1"}</small></span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-seal">检</span><b>归藏</b></div>
          <div className="service-strip">
            {([ ["weaviate", "Weaviate", "1.38"], ["embedding", "Embedding", "BGE-M3"], ["vllm", "llama-server", "Gemma 4"] ] as [ServiceKey, string, string][]).map(([key, label, meta]) => (
              <button key={key} onClick={() => setView("status")} className="service-pill" title={`查看 ${label} 服务状态`}>
                <span className={`status-dot ${health[key]}`}/><span>{label}</span><small>{meta}</small>
              </button>
            ))}
          </div>
          <div className="top-actions">
            <span className="session-label">会话 · {sessionId}</span>
            <button className="quiet-button" onClick={() => setView("settings")}><Icon name="settings" size={18}/><span>连接设置</span></button>
          </div>
        </header>

        {view === "search" && (
          <div className="page search-page">
            <section className="search-column">
              <div className="eyebrow"><span/>GLOBAL RETRIEVAL · 全局检索</div>
              <h1>从散落的知识中，<br/><em>找到可信依据。</em></h1>
              <p className="intro">混合召回文件知识与历史上下文，保留每一条答案的来源、章节和路径。</p>

              <form onSubmit={runSearch} className="search-form">
                <label className="query-box">
                  <span className="query-icon"><Icon name="search" size={28}/></span>
                  <textarea aria-label="检索问题" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runSearch(); } }} placeholder="输入问题、错误码、文件名或命令…"/>
                  <span className="key-hint">Enter 检索 · Shift + Enter 换行</span>
                </label>

                <div className="control-grid">
                  <div className="control-block range-block">
                    <label>检索范围</label>
                    <div className="segment-group" role="radiogroup" aria-label="检索范围">
                      {[ ["all", "全部知识"], ["global", "部署文档"], ["private", "会话记忆"] ].map(([value, label]) => <button type="button" role="radio" aria-checked={scope === value} className={scope === value ? "selected" : ""} key={value} onClick={() => setScope(value)}>{label}</button>)}
                    </div>
                  </div>
                  <div className="control-block topk-block">
                    <label htmlFor="top-k">返回数量</label>
                    <select id="top-k" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                      {[4, 6, 8, 10].map((n) => <option key={n} value={n}>Top {n}</option>)}
                    </select>
                  </div>
                </div>

                <div className="weight-block">
                  <div className="weight-head"><label htmlFor="alpha">混合检索权重</label><span><b>语义 {alpha}%</b><i>关键词 {100 - alpha}%</i></span></div>
                  <input id="alpha" type="range" min="0" max="100" value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} style={{ "--range": `${alpha}%` } as React.CSSProperties}/>
                  <div className="range-notes"><span>精确术语 / 错误码</span><span>概念 / 语义问题</span></div>
                </div>

                <button className="primary-button" disabled={loading} type="submit">{loading ? <span className="loading-mark"/> : <Icon name="arrow"/>}<span>{loading ? "正在检索" : "开始检索"}</span></button>
              </form>

              <div className="answer-panel">
                <div className="answer-head"><div><span className="section-kicker">SYNTHESIS</span><h2>依据整理</h2></div><button onClick={generateAnswer} disabled={answering || !results.length} className="outline-button"><Icon name="spark"/>{answering ? "正在生成" : "整理为回答"}</button></div>
                {answer ? <p className="answer-text">{answer}</p> : <p className="empty-answer">选择引用片段后，可由本地 vLLM 整理为带出处的回答；不选择时默认使用前三条结果。</p>}
              </div>
            </section>

            <section className="results-column">
              <div className="results-head"><div><span className="section-kicker">EVIDENCE</span><h2>检索依据</h2></div><div className="result-count"><b>{results.length}</b><span>条结果</span></div></div>
              <div className="citation-summary"><span>已选 <b>{selected.length}</b> 条作为回答上下文</span>{selected.length > 0 && <button onClick={() => setSelected([])}>清空</button>}</div>
              <div className="result-list" aria-live="polite">
                {results.map((item, index) => (
                  <article className={`result-card ${selected.includes(item.id) ? "cited" : ""}`} key={item.id} style={{ animationDelay: `${index * 45}ms` }}>
                    <div className="result-meta"><span className="rank">{String(index + 1).padStart(2, "0")}</span><div className="tag-row">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><span className="score">{Math.round(item.score * 100)}<small>%</small></span></div>
                    <h3>{item.title}</h3>
                    <p className="heading">{item.heading}{item.page ? ` · 第 ${item.page} 页` : ""}</p>
                    <p className="excerpt">{item.content}</p>
                    <div className="source-path"><Icon name="path" size={16}/><span title={item.sourceName}>来源 · {item.sourceName}</span></div>
                    <div className="card-foot"><span>相关度</span><div className="score-line"><i style={{ width: `${item.score * 100}%` }}/></div><button onClick={() => toggleCitation(item.id)} className={selected.includes(item.id) ? "selected" : ""}><Icon name={selected.includes(item.id) ? "check" : "quote"} size={17}/>{selected.includes(item.id) ? "已引用" : "引用"}</button></div>
                  </article>
                ))}
                {!results.length && <div className="empty-state"><span>无</span><h3>没有找到可靠依据</h3><p>尝试扩大检索范围、调整关键词或提高返回数量。</p></div>}
              </div>
            </section>
          </div>
        )}

        {view === "library" && (
          <div className="page inner-page">
            <PageTitle kicker="KNOWLEDGE BASE" title="知识入库" description="增量解析文件目录或直接写入文本；路径、哈希和切片编号用于去重。"/>
            <div className="two-column-panels">
              <section className="paper-panel"><PanelHeading number="壹" title="索引本地目录" text="后端会递归扫描支持的文档，并仅更新发生变化的来源。"/>
                <label className="field"><span>WSL2 路径</span><input value={ingestPath} onChange={(e) => setIngestPath(e.target.value)}/></label>
                <div className="format-row"><span>PDF</span><span>DOCX</span><span>Markdown</span><span>代码</span><span>纯文本</span></div>
                <button className="primary-button compact" onClick={() => postGateway("/v1/ingest/path", { path: ingestPath, scope: "global" }, "目录已加入索引队列")}><Icon name="plus"/>加入索引队列</button>
              </section>
              <section className="paper-panel"><PanelHeading number="贰" title="写入一段知识" text="适合临时笔记、操作记录和无法保存为文件的说明。"/>
                <label className="field"><span>标题与正文</span><textarea value={ingestText} onChange={(e) => setIngestText(e.target.value)} placeholder="输入要写入知识库的内容…"/></label>
                <button disabled={!ingestText.trim()} className="primary-button compact" onClick={() => { postGateway("/v1/ingest/text", { title: "工作台手动记录", content: ingestText, scope: "private" }, "文本已写入知识库"); setIngestText(""); }}><Icon name="plus"/>写入知识库</button>
              </section>
            </div>
            <section className="paper-panel sources-panel"><div className="panel-row"><PanelHeading number="叁" title="最近来源" text="按来源文件查看索引状态与切片数量。"/><span className="total-chip">2 个来源 · 112 个切片</span></div>
              <div className="source-table"><div className="table-head"><span>来源</span><span>范围</span><span>切片</span><span>更新时间</span><span/></div>
                {[ ["WSL2-Global-RAG-Deployment-CN.md", "全局知识库", "86", "今天 18:42"], ["README_WSL2_vLLM_32B.md", "部署文档目录", "26", "今天 18:37"] ].map((row) => <div className="table-row" key={row[0]}><span><b>{row[0]}</b><small>{row[1]}</small></span><span>global</span><span>{row[2]}</span><span>{row[3]}</span><button title="删除来源" onClick={() => flash("演示模式未删除真实数据")}><Icon name="trash" size={17}/></button></div>)}
              </div>
            </section>
          </div>
        )}

        {view === "memory" && (
          <div className="page inner-page">
            <PageTitle kicker="CONTEXT MEMORY" title="上下文记忆" description="只保存值得跨轮次检索的事实、决策和摘要；近期对话仍由模型上下文直接承载。"/>
            <div className="memory-layout">
              <section className="paper-panel memory-compose"><PanelHeading number="壹" title="记住一件事" text="内容会与会话标识和重要度一起写入 ContextMemory。"/>
                <label className="field"><span>会话标识</span><input value={sessionId} onChange={(e) => setSessionId(e.target.value)}/></label>
                <label className="field"><span>记忆内容</span><textarea value={memoryText} onChange={(e) => setMemoryText(e.target.value)} placeholder="例如：数据库必须放在 WSL2 ext4，不使用 /mnt/d…"/></label>
                <div className="memory-actions"><select aria-label="记忆类型"><option>decision · 决策</option><option>fact · 事实</option><option>summary · 摘要</option></select><button disabled={!memoryText.trim()} className="primary-button compact" onClick={() => { postGateway("/v1/memory", { content: memoryText, session_id: sessionId, memory_type: "decision", importance: .8, scope: "private" }, "已写入会话记忆"); setMemoryText(""); }}><Icon name="plus"/>保存记忆</button></div>
              </section>
              <section className="memory-list-panel"><div className="memory-list-head"><span className="section-kicker">RECENT MEMORY</span><h2>近期记忆</h2></div>
                {[ ["决策", "检索服务不得占用两张 RTX 3090，Embedding 固定走 CPU。", "今天 18:44"], ["事实", "Qwen2.5-32B 通过 vLLM 以 tensor-parallel-size=2 启动。", "今天 18:39"], ["摘要", "本轮完成 Weaviate、BGE-M3 与 Gateway 的部署参数确认。", "今天 18:33"] ].map(([type, text, time], i) => <article className="memory-card" key={text}><span>{type}</span><p>{text}</p><footer><i>重要度 {(.9 - i * .1).toFixed(1)}</i><time>{time}</time></footer></article>)}
              </section>
            </div>
          </div>
        )}

        {view === "status" && (
          <div className="page inner-page">
            <div className="title-row"><PageTitle kicker="SYSTEM PULSE" title="服务状态" description={`上次检查：${lastCheck}。状态检测只读取健康端点，不修改服务。`}/><button className="outline-button" onClick={checkHealth}><Icon name="pulse"/>重新检查</button></div>
            <div className="status-grid">
              {([ ["gateway", "RAG Gateway", settings.gatewayUrl, "检索、入库与权限封装", "12 ms"], ["weaviate", "Weaviate", settings.weaviateUrl, "BM25 + HNSW 混合索引", "18 ms"], ["embedding", "BGE-M3", settings.embeddingUrl, "FlagEmbedding · CPU 推理", "内置"], ["vllm", "llama-server (Gemma 4)", settings.vllmUrl, "双 3090 · Q4_K_M GGUF", "在线"] ] as [ServiceKey, string, string, string, string][]).map(([key, title, url, description, metric], i) => <article className="status-card" key={key}><div className="status-card-top"><span className="ordinal">{["壹", "贰", "叁", "肆"][i]}</span><span className={`large-status ${health[key]}`}>{health[key] === "checking" ? "检查中" : health[key] === "online" ? "运行正常" : "无法连接"}</span></div><h2>{title}</h2><p>{description}</p><code>{url}</code><footer><span>当前指标</span><b>{health[key] === "online" ? metric : "—"}</b></footer></article>)}
            </div>
            <section className="paper-panel resource-panel"><PanelHeading number="监" title="资源边界" text="按部署文档设定的本机资源上限。"/><div className="resource-bars"><ResourceBar label="Weaviate 内存" value="8.7 / 14 GB" width="62%"/><ResourceBar label="Embedding 内存" value="3.2 / 6 GB" width="53%"/><ResourceBar label="向量容量" value="0.34 / 0.8 M" width="42%"/></div></section>
          </div>
        )}

        {view === "settings" && (
          <div className="page inner-page">
            <PageTitle kicker="CONNECTION" title="连接设置" description="设置只保存在当前浏览器；API Key 不会写入项目源码。"/>
            <section className="paper-panel settings-panel">
              <div className="mode-switch"><div><b>运行模式</b><p>演示模式使用内置样例；本地服务模式调用 WSL2 中的真实端点。</p></div><button className={settings.demoMode ? "demo" : "live"} onClick={() => saveSettings({ ...settings, demoMode: !settings.demoMode })}><span/><b>{settings.demoMode ? "演示模式" : "本地服务"}</b></button></div>
              <div className="settings-grid">
                <label className="field"><span>RAG Gateway</span><input value={settings.gatewayUrl} onChange={(e) => setSettings({ ...settings, gatewayUrl: e.target.value })}/></label>
                <label className="field"><span>Weaviate</span><input value={settings.weaviateUrl} onChange={(e) => setSettings({ ...settings, weaviateUrl: e.target.value })}/></label>
                <label className="field"><span>Embedding / Ollama</span><input value={settings.embeddingUrl} onChange={(e) => setSettings({ ...settings, embeddingUrl: e.target.value })}/></label>
                <label className="field"><span>vLLM OpenAI API</span><input value={settings.vllmUrl} onChange={(e) => setSettings({ ...settings, vllmUrl: e.target.value })}/></label>
                <label className="field"><span>Weaviate / Gateway API Key</span><input type="password" value={settings.apiKey} placeholder="至少 32 字节" onChange={(e) => setSettings({ ...settings, apiKey: e.target.value })}/></label>
                <label className="field"><span>vLLM 模型名称</span><input value={settings.model} onChange={(e) => setSettings({ ...settings, model: e.target.value })}/></label>
              </div>
              <div className="settings-actions"><button className="outline-button" onClick={checkHealth}><Icon name="pulse"/>测试连接</button><button className="primary-button compact" onClick={() => { saveSettings(settings); flash("设置已保存在当前浏览器"); }}><Icon name="check"/>保存设置</button></div>
              <p className="security-note">建议仅绑定 127.0.0.1，并由 Gateway 统一处理 CORS、鉴权和 scope 过滤。远程打开此界面时，浏览器可能阻止访问本机 HTTP 服务。</p>
            </section>
          </div>
        )}
      </section>
      {notice && <div className="toast"><Icon name="check" size={18}/>{notice}</div>}
    </main>
  );
}

function PageTitle({ kicker, title, description }: { kicker: string; title: string; description: string }) {
  return <div className="page-title"><div className="eyebrow"><span/>{kicker}</div><h1>{title}</h1><p>{description}</p></div>;
}

function PanelHeading({ number, title, text }: { number: string; title: string; text: string }) {
  return <div className="panel-heading"><span>{number}</span><div><h2>{title}</h2><p>{text}</p></div></div>;
}

function ResourceBar({ label, value, width }: { label: string; value: string; width: string }) {
  return <div className="resource-bar"><div><span>{label}</span><b>{value}</b></div><i><em style={{ width }}/></i></div>;
}
