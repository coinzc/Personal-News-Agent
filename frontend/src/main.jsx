import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Activity, ArrowUpRight, BookOpen, Check, ChevronRight, CircleAlert, Clock3,
  FileText, LayoutDashboard, LogIn, Newspaper, Radio, RefreshCw, Rss, Send,
  Settings, ShieldCheck, Sparkles, Tag, X,
} from 'lucide-react'
import './styles.css'

const API_KEY_STORAGE = 'personal-news-agent.admin-api-key'
const categories = ['AI', '科技', '编程', '财经', '商业', '国际', '科学', '游戏']

async function api(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) }
  const key = sessionStorage.getItem(API_KEY_STORAGE)
  if (key) headers['X-API-Key'] = key
  const response = await fetch(path, { ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `请求失败（${response.status}）`)
  }
  return response.status === 204 ? null : response.json()
}

function App() {
  const [view, setView] = useState('overview')
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem(API_KEY_STORAGE) || '')
  const [showKey, setShowKey] = useState(!sessionStorage.getItem(API_KEY_STORAGE))
  const [toast, setToast] = useState(null)

  const notify = (message, tone = 'success') => {
    setToast({ message, tone })
    window.setTimeout(() => setToast(null), 3600)
  }

  const saveKey = (value) => {
    const next = value.trim()
    if (next) sessionStorage.setItem(API_KEY_STORAGE, next)
    else sessionStorage.removeItem(API_KEY_STORAGE)
    setApiKey(next)
    setShowKey(false)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><span>PN</span><div><strong>新闻编辑台</strong><small>PERSONAL NEWS AGENT</small></div></div>
        <nav className="main-nav" aria-label="主导航">
          <NavItem icon={<LayoutDashboard size={17} />} label="总览" active={view === 'overview'} onClick={() => setView('overview')} />
          <NavItem icon={<Newspaper size={17} />} label="新闻" active={view === 'news'} onClick={() => setView('news')} />
          <NavItem icon={<Radio size={17} />} label="事件" active={view === 'events'} onClick={() => setView('events')} />
          <NavItem icon={<FileText size={17} />} label="日报" active={view === 'digest'} onClick={() => setView('digest')} />
          <NavItem icon={<Rss size={17} />} label="新闻源" active={view === 'sources'} onClick={() => setView('sources')} />
        </nav>
        <div className="sidebar-footer"><div className="status-dot online" />系统在线<span className="version">v0.1</span></div>
      </aside>
      <main className="content">
        <header className="topbar"><div><p className="kicker">NEWSROOM / {view.toUpperCase()}</p><h1>{viewTitle(view)}</h1></div><div className="top-actions"><button className="icon-button" title="刷新页面" onClick={() => window.location.reload()}><RefreshCw size={17} /></button><button className="key-button" onClick={() => setShowKey(true)}><ShieldCheck size={15} />管理密钥 {apiKey ? <Check size={14} /> : <CircleAlert size={14} />}</button></div></header>
        {view === 'overview' && <Overview notify={notify} onNavigate={setView} />}
        {view === 'news' && <NewsView notify={notify} />}
        {view === 'events' && <EventsView />}
        {view === 'digest' && <DigestView notify={notify} />}
        {view === 'sources' && <SourcesView notify={notify} />}
      </main>
      {showKey && <KeyModal value={apiKey} onSave={saveKey} onClose={() => setShowKey(false)} />}
      {toast && <div className={`toast ${toast.tone}`}><span>{toast.tone === 'success' ? <Check size={15} /> : <CircleAlert size={15} />}</span>{toast.message}</div>}
    </div>
  )
}

function viewTitle(view) { return ({ overview: '今日编辑台', news: '新闻流', events: '事件聚合', digest: '每日日报', sources: '新闻源' })[view] }
function NavItem({ icon, label, active, onClick }) { return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>{icon}<span>{label}</span>{active && <ChevronRight size={14} />}</button> }

function Overview({ notify, onNavigate }) {
  const [data, setData] = useState({ news: [], events: [], sources: [], digest: null })
  const [loading, setLoading] = useState(true)
  const load = async () => {
    setLoading(true)
    try {
      const [news, events, sources, digest] = await Promise.all([
        api('/api/news?limit=100'), api('/api/events?limit=100'), api('/api/sources'), api('/api/digest/today').catch(() => null),
      ])
      setData({ news, events, sources, digest })
    } catch (error) { notify(error.message, 'error') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  const enabledSources = data.sources.filter((source) => source.enabled).length
  return <div className="page-grid">
    <section className="welcome-panel"><div><p className="eyebrow">{todayLabel()}</p><h2>把重要的事，<em>先看清楚。</em></h2><p className="lede">聚合全球信源，追踪事件脉络，把每天的噪音整理成可以行动的信息。</p></div><div className="signal-orbit"><div className="orbit-core"><Sparkles size={25} /><span>LIVE</span></div><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /></div></section>
    <section className="metric-grid"><Metric icon={<Newspaper />} label="今日新闻" value={loading ? '—' : data.news.length} note="已归档报道" /><Metric icon={<Radio />} label="活跃事件" value={loading ? '—' : data.events.length} note="跨源聚合" /><Metric icon={<Rss />} label="启用信源" value={loading ? '—' : enabledSources} note={`共 ${data.sources.length} 个来源`} /><Metric icon={<FileText />} label="日报状态" value={data.digest?.status === 'sent' ? '已发送' : data.digest ? '已生成' : '待生成'} note={data.digest?.digest_date || '今天'} tone={data.digest?.status === 'sent' ? 'green' : 'amber'} /> </section>
    <section className="content-panel lead-panel"><PanelHeading icon={<BookOpen size={16} />} title="最新报道" action="查看全部" onAction={() => onNavigate('news')} /><div className="headline-list">{loading ? <Loading /> : data.news.slice(0, 5).map((item, index) => <Headline key={item.id || index} item={item} index={index} />)}</div></section>
    <section className="content-panel side-panel"><PanelHeading icon={<Activity size={16} />} title="运行状态" /><div className="status-list"><StatusRow label="新闻采集" value="每 30 分钟" state="正常" /><StatusRow label="日报生成" value="09:00 Asia/Shanghai" state={data.digest ? '已完成' : '待执行'} tone={data.digest ? 'green' : 'amber'} /><StatusRow label="企业微信" value="日报推送" state="已配置" /><StatusRow label="DeepSeek" value="智能摘要" state="已连接" /></div><button className="text-action" onClick={load}><RefreshCw size={14} />刷新状态</button></section>
  </div>
}

function NewsView({ notify }) {
  const [items, setItems] = useState([]); const [q, setQ] = useState(''); const [category, setCategory] = useState(''); const [loading, setLoading] = useState(true)
  const load = async () => { setLoading(true); try { setItems(await api(`/api/news?limit=100${q ? `&q=${encodeURIComponent(q)}` : ''}${category ? `&category=${encodeURIComponent(category)}` : ''}`)) } catch (error) { notify(error.message, 'error') } finally { setLoading(false) } }
  useEffect(() => { load() }, [category])
  return <div className="page-stack"><section className="toolbar"><div className="search-box"><span>⌕</span><input value={q} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && load()} placeholder="搜索标题或关键词" /></div><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="">全部领域</option>{categories.map((item) => <option key={item}>{item}</option>)}</select><button className="primary-button" onClick={load}><RefreshCw size={15} />刷新</button></section><section className="content-panel table-panel"><div className="table-caption"><span>{loading ? '正在读取…' : `共 ${items.length} 条报道`}</span><span className="caption-note">按发布时间倒序</span></div>{loading ? <Loading /> : <div className="news-table">{items.map((item) => <article className="news-row" key={item.id}><div className="news-rank">{item.importance_score ? Math.round(item.importance_score) : '—'}</div><div className="news-main"><h3>{item.title}</h3><p>{item.summary || '暂无摘要'}</p><div className="row-meta"><span><Tag size={12} />{item.category || '未分类'}</span><span><Clock3 size={12} />{formatDate(item.published_at)}</span><span>{item.source_name || item.source || '未知来源'}</span></div></div><a href={item.url} target="_blank" rel="noreferrer" className="external-link" title="打开原文"><ArrowUpRight size={17} /></a></article>)}</div>}</section></div>
}

function EventsView() { return <ResourceList path="/api/events" title="事件聚合" empty="暂无事件聚合数据" render={(item) => <><div className="event-score">{Math.round(item.importance_score || 0)}<small>分</small></div><div><h3>{item.canonical_title || item.title}</h3><p>{item.summary || '跨来源报道已归并为同一事件。'}</p><div className="row-meta"><span><Tag size={12} />{item.category || '未分类'}</span><span>{item.sources?.length || item.news_count || 0} 个来源</span></div></div></>} /> }
function ResourceList({ path, title, empty, render }) { const [items, setItems] = useState([]); const [loading, setLoading] = useState(true); useEffect(() => { api(`${path}?limit=100`).then(setItems).catch(() => {}).finally(() => setLoading(false)) }, [path]); return <div className="page-stack"><section className="content-panel table-panel"><div className="table-caption"><span>{loading ? '正在读取…' : `${items.length} 个${title}`}</span><span className="caption-note">事件按重要性排序</span></div>{loading ? <Loading /> : items.length ? <div className="event-list">{items.map((item, index) => <article className="event-row" key={item.id || index}>{render(item)}</article>)}</div> : <Empty label={empty} />}</section></div> }

function DigestView({ notify }) { const [digest, setDigest] = useState(null); const [loading, setLoading] = useState(true); const load = () => { setLoading(true); api('/api/digest/today').then(setDigest).catch((error) => setDigest({ error: error.message })).finally(() => setLoading(false)) }; useEffect(load, []); const action = async (path, label) => { try { await api(path, { method: 'POST' }); notify(`${label}成功`) ; load() } catch (error) { notify(error.message, 'error') } }; return <div className="page-stack"><section className="digest-hero"><div><p className="eyebrow">DAILY BRIEF / {todayLabel()}</p><h2>今天的世界，<em>已经整理好。</em></h2><p>一份基于事件聚合、可信来源和智能摘要的编辑版新闻早报。</p></div><div className="digest-actions"><button className="primary-button" onClick={() => action('/api/digest/generate', '日报生成')}><Sparkles size={15} />生成日报</button><button className="secondary-button" onClick={() => action('/api/digest/send', '日报发送')}><Send size={15} />发送到企业微信</button></div></section><section className="content-panel digest-panel">{loading ? <Loading /> : digest?.error ? <Empty label="今天还没有日报，先生成一份吧。" /> : <><div className="digest-meta"><span className={`status-pill ${digest.status}`}>{digest.status}</span><span>{digest.digest_date}</span><span>{digest.timezone}</span></div><pre className="digest-content">{digest.content || '日报内容为空。'}</pre></>}</section></div> }

function SourcesView({ notify }) { const [sources, setSources] = useState([]); const [loading, setLoading] = useState(true); const [form, setForm] = useState({ name: '', url: '', category: 'AI' }); const load = () => { setLoading(true); api('/api/sources').then(setSources).catch((error) => notify(error.message, 'error')).finally(() => setLoading(false)) }; useEffect(load, []); const create = async (event) => { event.preventDefault(); try { await api('/api/sources', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...form, source_type: 'rss', language: 'zh' }) }); setForm({ name: '', url: '', category: 'AI' }); notify('新闻源已添加'); load() } catch (error) { notify(error.message, 'error') } }; const toggle = async (source) => { try { await api(`/api/sources/${source.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !source.enabled }) }); load() } catch (error) { notify(error.message, 'error') } }; return <div className="source-layout"><section className="content-panel table-panel"><div className="table-caption"><span>{loading ? '正在读取…' : `${sources.length} 个新闻源`}</span><span className="caption-note">优先级越高越先采集</span></div>{sources.map((source) => <div className="source-row" key={source.id}><div className={`source-icon ${source.enabled ? 'enabled' : ''}`}><Rss size={16} /></div><div className="source-copy"><strong>{source.name}</strong><span>{source.url}</span></div><span className="source-category">{source.category}</span><button className={`switch ${source.enabled ? 'on' : ''}`} onClick={() => toggle(source)} aria-label={`切换 ${source.name}`}><span /></button></div>)}</section><section className="content-panel add-source"><div className="panel-title"><Rss size={16} />添加新闻源</div><form onSubmit={create}><label>名称<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：MIT Technology Review" /></label><label>RSS 地址<input required type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></label><label>领域<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{categories.map((item) => <option key={item}>{item}</option>)}</select></label><button className="primary-button" type="submit"><Rss size={15} />保存新闻源</button></form></section></div> }

function KeyModal({ value, onSave, onClose }) { const [draft, setDraft] = useState(value); return <div className="modal-backdrop"><div className="modal"><button className="modal-close" onClick={onClose} title="关闭"><X size={17} /></button><div className="modal-icon"><ShieldCheck size={20} /></div><p className="eyebrow">ADMIN ACCESS</p><h2>输入管理密钥</h2><p>密钥只保存在当前浏览器标签页，关闭标签页后会自动清除。</p><input autoFocus type="password" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && onSave(draft)} placeholder="X-API-Key" /><button className="primary-button full" onClick={() => onSave(draft)}><LogIn size={15} />进入编辑台</button></div></div> }
function Metric({ icon, label, value, note, tone = 'blue' }) { return <div className={`metric-card ${tone}`}><div className="metric-icon">{icon}</div><div><span>{label}</span><strong>{value}</strong><small>{note}</small></div></div> }
function PanelHeading({ icon, title, action, onAction }) { return <div className="panel-heading"><div>{icon}<h2>{title}</h2></div>{action && <button className="link-button" onClick={onAction}>{action}<ArrowUpRight size={14} /></button>}</div> }
function Headline({ item, index }) { return <article className="headline"><span className="headline-index">0{index + 1}</span><div><h3>{item.title}</h3><p>{item.summary || '暂无摘要'}</p><div className="row-meta"><span>{item.category || '未分类'}</span><span>{formatDate(item.published_at)}</span></div></div></article> }
function StatusRow({ label, value, state, tone = 'green' }) { return <div className="status-row"><div><strong>{label}</strong><span>{value}</span></div><span className={`status-text ${tone}`}><i />{state}</span></div> }
function Loading() { return <div className="loading"><RefreshCw size={16} className="spin" />正在读取数据…</div> }
function Empty({ label }) { return <div className="empty"><BookOpen size={20} /><span>{label}</span></div> }
function todayLabel() { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'full' }).format(new Date()) }
function formatDate(value) { if (!value) return '时间未知'; return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) }

createRoot(document.getElementById('root')).render(<App />)
