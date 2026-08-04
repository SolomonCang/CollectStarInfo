import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, Bot, ChevronRight, Database, LogOut, Menu, Search,
  ShieldCheck, Sparkles, Star, Telescope, Users, X,
} from "lucide-react";
import { listStars } from "./api";
import LoginPage, { ChangePasswordPage } from "./components/auth/LoginPage";
import TargetPage from "./components/target/TargetPage";
import { useAuth } from "./hooks/useAuth";
import { useLightCurveWorkspace } from "./hooks/useLightCurveWorkspace";
import { useTargetWorkspace } from "./hooks/useTargetWorkspace";

const LightCurvePage = lazy(() => import("./components/lightcurve/LightCurvePage"));
const DataManagerPage = lazy(() => import("./components/datamanager/DataManagerPage"));
const LlmPluginPage = lazy(() => import("./components/plugins/LlmPluginPage"));
const UserAdminPage = lazy(() => import("./components/admin/UserAdminPage"));

const PAGE_META = {
  home: { label: "恒星主页", title: "恒星信息工作台", icon: Star },
  discovery: { label: "数据发现与入库", title: "数据发现与入库", icon: Telescope },
  lightcurves: { label: "光变实验室", title: "光变曲线分析", icon: Activity },
  llm: { label: "大模型接口", title: "大模型接口插件", icon: Bot, plugin: true },
  literature: { label: "文献调研", title: "文献调研插件", icon: Sparkles, plugin: true },
  data: { label: "数据管理", title: "共享数据仓库", icon: Database },
  admin: { label: "用户管理", title: "用户与迁移", icon: Users, admin: true },
};

function pageFromHash() {
  if (typeof window === "undefined") return "home";
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return Object.hasOwn(PAGE_META, candidate) ? candidate : "home";
}

function LoadingScreen({ label = "正在载入工作区…" }) {
  return <main className="boot-screen"><div className="brand-orbit"><span /><span /><span /></div><strong>{label}</strong></main>;
}

function Sidebar({ user, stars, page, onPage, onTarget, open, onClose, onLogout }) {
  const [query, setQuery] = useState("");
  const [pluginsOpen, setPluginsOpen] = useState(() => PAGE_META[page]?.plugin);
  const visibleStars = useMemo(
    () => stars.filter((item) => item.name.toLowerCase().includes(query.toLowerCase())),
    [stars, query],
  );
  useEffect(() => { if (PAGE_META[page]?.plugin) setPluginsOpen(true); }, [page]);
  const go = (next) => { onPage(next); onClose(); };

  return (
    <aside className={open ? "workspace-sidebar open" : "workspace-sidebar"}>
      <div className="workspace-brand">
        <div className="brand-orbit small"><span /><span /><span /></div>
        <div><strong>Target Info</strong><small>Star-centered workspace</small></div>
        <button className="sidebar-close" aria-label="关闭导航" onClick={onClose}><X size={18} /></button>
      </div>
      <nav className="workspace-nav" aria-label="主导航">
        {["home", "discovery", "lightcurves"].map((id) => {
          const Icon = PAGE_META[id].icon;
          return <button key={id} className={page === id ? "active" : ""} onClick={() => go(id)}><Icon size={18} />{PAGE_META[id].label}</button>;
        })}
        <div className="nav-group">
          <button className={PAGE_META[page]?.plugin ? "nav-parent has-active-child" : "nav-parent"} aria-expanded={pluginsOpen} onClick={() => setPluginsOpen((value) => !value)}><Sparkles size={18} /><span>插件中心</span><b>2</b><ChevronRight className="nav-chevron" size={14} /></button>
          {pluginsOpen ? <div className="nav-children">{["llm", "literature"].map((id) => <button key={id} className={page === id ? "active" : ""} onClick={() => go(id)}><span className="nav-marker" /><span><strong>{PAGE_META[id].label}</strong><small>{id === "llm" ? "私有接口与运行历史" : "基于参考文献的 AI 调研"}</small></span></button>)}</div> : null}
        </div>
        <button className={page === "data" ? "active" : ""} onClick={() => go("data")}><Database size={18} />数据管理</button>
        {user.is_admin ? <button className={page === "admin" ? "active" : ""} onClick={() => go("admin")}><ShieldCheck size={18} />用户管理</button> : null}
      </nav>
      <div className="sidebar-target-heading"><span>STELLAR OBJECTS</span><b>{stars.length}</b></div>
      <label className="sidebar-target-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="查找目标…" /></label>
      <div className="sidebar-target-list">
        {visibleStars.map((item) => <button key={item.normalized} onClick={() => { onTarget(item.name); go("home"); }}><span className="target-avatar">{item.name.slice(0, 1).toUpperCase()}</span><span><strong>{item.name}</strong><small>{item.entry_count || 0} 条数据 · {item.has_lc ? "含光变" : "目标信息"}</small></span></button>)}
        {!visibleStars.length ? <small className="sidebar-empty">迁移或查询目标后显示在这里</small> : null}
      </div>
      <div className="sidebar-account"><div className="target-avatar">{user.username.slice(0, 1).toUpperCase()}</div><span><strong>{user.username}</strong><small>{user.is_admin ? "管理员" : "普通用户"}</small></span><button title="退出登录" aria-label="退出登录" onClick={onLogout}><LogOut size={16} /></button></div>
    </aside>
  );
}

function WorkspaceApp({ user, onLogout }) {
  const [page, setPage] = useState(pageFromHash);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [stars, setStars] = useState([]);
  const targetWorkspace = useTargetWorkspace();
  const lightCurveWorkspace = useLightCurveWorkspace({ active: page === "lightcurves" });

  useEffect(() => {
    const sync = () => setPage(pageFromHash());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  useEffect(() => {
    document.title = `${PAGE_META[page].title} · Target Info`;
  }, [page]);
  useEffect(() => {
    listStars({ limit: 500 }).then((result) => setStars(result.stars || [])).catch(() => {});
  }, [targetWorkspace.targetResult, page]);

  const navigate = useCallback((next) => {
    const hash = `#/${next}`;
    if (window.location.hash === hash) setPage(next);
    else window.location.hash = hash;
  }, []);
  const selectTarget = useCallback((name) => {
    targetWorkspace.setTargetName(name);
    lightCurveWorkspace.setTargetName(name);
  }, [targetWorkspace.setTargetName, lightCurveWorkspace.setTargetName]);
  const meta = PAGE_META[page];

  return (
    <main className="workspace-shell">
      <Sidebar user={user} stars={stars} page={page} onPage={navigate} onTarget={selectTarget} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onLogout={onLogout} />
      {sidebarOpen ? <button className="sidebar-scrim" aria-label="关闭导航" onClick={() => setSidebarOpen(false)} /> : null}
      <section className="workspace-main">
        <header className="workspace-topbar"><button className="menu-button" aria-label="打开导航" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div className="breadcrumb"><Database size={16} /><span>Stellar Data Hub</span><b>/</b><strong>{meta.title}</strong></div><div className="topbar-status"><span className="live-dot" />Shared warehouse <b>v2</b></div></header>

        {(page === "home" || page === "discovery" || page === "literature") ? (
          <section className="workspace-page target-workspace-page">
            <header className="page-intro"><div><span className="kicker">{page === "discovery" ? "DATA DISCOVERY & INGEST" : page === "literature" ? "PRIVATE PLUGIN · LITERATURE" : "STELLAR DATA WORKSPACE"}</span><h1>{page === "literature" ? "文献调研" : targetWorkspace.targetResult?.target?.resolved_target || targetWorkspace.targetName || meta.title}</h1><p>{page === "discovery" ? "检索 SIMBAD、Gaia 与 MAST，并把可追溯结果写入共享仓库。" : page === "literature" ? "使用当前账号的模型接口，对目标参考文献开展可追溯调研。" : "聚合恒星身份、测光任务覆盖、参考文献与当前用户的 AI 总结。"}</p></div><div className="coverage"><span>CURRENT TARGET</span><strong>{targetWorkspace.targetResult?.target?.resolved_target || targetWorkspace.targetName}</strong><small>{targetWorkspace.targetResult?.source || "等待载入"}</small></div></header>
            <TargetPage {...targetWorkspace} />
          </section>
        ) : null}
        {page === "lightcurves" ? <Suspense fallback={<LoadingScreen />}><section className="workspace-page"><LightCurvePage workspace={lightCurveWorkspace} canManage={user.is_admin} /></section></Suspense> : null}
        {page === "data" ? <Suspense fallback={<LoadingScreen />}><DataManagerPage isAdmin={user.is_admin} /></Suspense> : null}
        {page === "llm" ? <Suspense fallback={<LoadingScreen />}><LlmPluginPage /></Suspense> : null}
        {page === "admin" && user.is_admin ? <Suspense fallback={<LoadingScreen />}><UserAdminPage currentUser={user} /></Suspense> : null}
      </section>
    </main>
  );
}

export default function App() {
  const auth = useAuth();
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  if (auth.loading && !auth.user) return <LoadingScreen label="正在验证会话…" />;
  if (!auth.user) return <LoginPage busy={auth.loading} error={auth.error} onLogin={auth.login} />;
  if (auth.user.must_change_password) return <ChangePasswordPage busy={passwordBusy} error={passwordError || auth.error} onLogout={auth.logout} onChange={async (payload) => { setPasswordBusy(true); setPasswordError(""); try { await auth.changePassword(payload); } catch (caught) { setPasswordError(caught.message); } finally { setPasswordBusy(false); } }} />;
  return <WorkspaceApp user={auth.user} onLogout={auth.logout} />;
}
