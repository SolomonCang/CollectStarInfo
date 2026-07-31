import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import TargetPage from "./components/target/TargetPage";
import { useLightCurveWorkspace } from "./hooks/useLightCurveWorkspace";
import { useTargetWorkspace } from "./hooks/useTargetWorkspace";

const LightCurvePage = lazy(() => import("./components/lightcurve/LightCurvePage"));
const DataManagerPage = lazy(() => import("./components/datamanager/DataManagerPage"));

const PAGE_TITLES = {
  target: "Target Info Search",
  lightcurves: "Light Curve Lab",
  data: "Data Manager",
};

function pageFromHash() {
  if (typeof window === "undefined") return "target";
  const candidate = window.location.hash.replace(/^#\/?/, "");
  return Object.hasOwn(PAGE_TITLES, candidate) ? candidate : "target";
}

export default function App() {
  const [page, setPage] = useState(pageFromHash);
  const targetWorkspace = useTargetWorkspace();
  const lightCurveWorkspace = useLightCurveWorkspace({
    active: page === "lightcurves",
  });

  useEffect(() => {
    const syncPage = () => setPage(pageFromHash());
    window.addEventListener("hashchange", syncPage);
    return () => window.removeEventListener("hashchange", syncPage);
  }, []);

  useEffect(() => {
    document.title = PAGE_TITLES[page];
  }, [page]);

  const navigateTo = useCallback((nextPage) => {
    const nextHash = `#/${nextPage}`;
    if (window.location.hash === nextHash) {
      setPage(nextPage);
    } else {
      window.location.hash = nextHash;
    }
  }, []);

  return (
    <main className="app-shell">
      <section className={page === "lightcurves" ? "workspace-header compact-header" : "workspace-header"}>
        <div>
          <p className="eyebrow">Interactive astronomy workspace</p>
          <h1>{PAGE_TITLES[page]}</h1>
        </div>
        <nav className="page-switcher" aria-label="工作区导航">
          {[
            ["target", "目标信息"],
            ["lightcurves", "光变曲线"],
            ["data", "数据管理"],
          ].map(([pageId, label]) => (
            <button
              key={pageId}
              type="button"
              className={page === pageId ? "nav-button active" : "nav-button"}
              aria-current={page === pageId ? "page" : undefined}
              onClick={() => navigateTo(pageId)}
            >
              {label}
            </button>
          ))}
        </nav>
      </section>

      {page === "target" && <TargetPage {...targetWorkspace} />}

      {page === "lightcurves" && (
        <Suspense fallback={<div className="page-loading" role="status">正在加载光变工作区…</div>}>
          <LightCurvePage workspace={lightCurveWorkspace} />
        </Suspense>
      )}

      {page === "data" && (
        <Suspense fallback={<div className="page-loading" role="status">正在加载数据管理…</div>}>
          <DataManagerPage />
        </Suspense>
      )}
    </main>
  );
}
