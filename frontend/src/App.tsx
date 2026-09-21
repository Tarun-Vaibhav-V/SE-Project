import { useEffect, useMemo, useState } from "react";
import MapView from "./components/MapView";
import RiskCard from "./components/RiskCard";
import DriverPanel from "./components/DriverPanel";
import AddSiteModal from "./components/AddSiteModal";
import NewsPanel from "./components/NewsPanel";
import PortfolioView from "./components/PortfolioView";
import PwiView from "./components/PwiView";
import CopilotView from "./components/CopilotView";
import EvidenceView from "./components/EvidenceView";
import TwinView from "./components/TwinView";
import { TopNav, LayerSelector, Legend, BasemapToggle, FuturePanel, WeightsPanel } from "./components/Panels";
import { loadBasins, loadSites, loadFutures, getRiskCache, fetchSubbasins, supa } from "./lib/data";
import type { BasinFeature, Site } from "./lib/data";
import { LAYERS } from "./lib/risk";
import LandingView from "./components/LandingView";
import LoginView from "./components/LoginView";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/auth.css";

export default function App() {
  // survive refresh: once inside, stay inside for the browser session
  const [appState, setAppState] = useState<"landing" | "login" | "app">(
    () => (sessionStorage.getItem("hydris_entered") === "1" ? "app" : "landing"));
  const [basins, setBasins] = useState<BasinFeature[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [futures, setFutures] = useState<Record<number, any>>({});
  const [view, setView] = useState<"map" | "portfolio" | "pwi" | "copilot" | "evidence" | "twin">("map");
  const [layerId, setLayerId] = useState("overall");
  const [basemap, setBasemap] = useState<"dark" | "light" | "sat">("dark");
  const [selected, setSelected] = useState<Site | null>(null);
  const [cache, setCache] = useState<any | null>(null);
  const [explainRisk, setExplainRisk] = useState<string | null>(null);
  const [showFuture, setShowFuture] = useState(false);
  const [showWeights, setShowWeights] = useState(false);
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number } | null>(null);
  // custom-weights override for the selected site (Gate 5: live recolor)
  const [customOverall, setCustomOverall] = useState<number | null>(null);
  // factory input flow
  const [addOpen, setAddOpen] = useState(false);
  const [pickMode, setPickMode] = useState(false);
  const [picked, setPicked] = useState<{ lat: number; lng: number } | null>(null);
  // local news + finer sub-basins
  const [showNews, setShowNews] = useState(false);
  const [subbasins, setSubbasins] = useState<any | null>(null);
  const [subsLoading, setSubsLoading] = useState(false);
  // first-run guidance (dismiss persists across sessions)
  const [showHint, setShowHint] = useState(() => localStorage.getItem("hydris_hint_done") !== "1");
  const dismissHint = () => { setShowHint(false); localStorage.setItem("hydris_hint_done", "1"); };

  useEffect(() => {
    loadBasins().then(setBasins);
    loadSites().then(setSites);
    loadFutures().then(setFutures);
  }, []);

  const reload = () => {
    loadBasins().then(setBasins);
    loadSites().then(setSites);
    loadFutures().then(setFutures);
  };

  // portfolio row click -> open the site on the map
  const drillTo = (s: Site) => {
    setView("map");
    setSelected(s);
    setFlyTo({ lat: s.lat, lng: s.lng });
  };

  useEffect(() => {
    setCache(null); setExplainRisk(null); setShowFuture(false); setShowWeights(false);
    setCustomOverall(null); setShowNews(false); setSubbasins(null);
    if (selected && showHint) dismissHint(); // they've found their way — stop guiding
    if (selected) {
      getRiskCache(selected.pfaf_id).then(setCache);
      setSubsLoading(true);
      fetchSubbasins(selected.lat, selected.lng)
        .then(setSubbasins)
        .finally(() => setSubsLoading(false));
    }
  }, [selected]);

  const layer = LAYERS.find((l) => l.id === layerId)!;

  const basinByPfaf = useMemo(() => {
    const m: Record<string, Record<string, any>> = {};
    basins.forEach((b) => { if (b.properties.pfaf_id != null) m[String(b.properties.pfaf_id)] = b.properties; });
    return m;
  }, [basins]);

  const siteOverall = useMemo(() => {
    const m: Record<string, number | null> = {};
    sites.forEach((s) => { m[s.id] = s.pfaf_id != null ? basinByPfaf[String(s.pfaf_id)]?.overall ?? null : null; });
    if (selected && customOverall !== null) m[selected.id] = customOverall; // live reweight recolor
    return m;
  }, [sites, basinByPfaf, selected, customOverall]);

  // custom weights recolor the selected basin's Overall layer too
  const basinsForMap = useMemo(() => {
    if (!selected || customOverall === null || selected.pfaf_id == null) return basins;
    return basins.map((b) =>
      String(b.properties.pfaf_id) === String(selected.pfaf_id)
        ? { ...b, properties: { ...b.properties, overall: customOverall } }
        : b
    );
  }, [basins, selected, customOverall]);

  const selectedProps = selected && selected.pfaf_id != null ? basinByPfaf[String(selected.pfaf_id)] ?? {} : {};

  // only one bottom popup at a time
  const openBottomPopup = (which: "future" | "weights" | "news") => {
    if (which === "future") {
      setShowFuture(!showFuture); setShowWeights(false); setShowNews(false);
    } else if (which === "weights") {
      setShowWeights(!showWeights); setShowFuture(false); setShowNews(false);
    } else {
      setShowNews(!showNews); setShowFuture(false); setShowWeights(false);
    }
  };

  const hasRightSidebar = view === "map" && !!selected;

  if (appState === "landing") {
    return <LandingView onLoginClick={() => setAppState("login")} />;
  }

  if (appState === "login") {
    return <LoginView onBack={() => setAppState("landing")} onLogin={() => {
      sessionStorage.setItem("hydris_entered", "1");
      setAppState("app");
    }} />;
  }

  return (
    <div style={{ position: "relative", height: "100%", overflow: "hidden" }}>
      {/* ── Full-bleed map ── */}
      <MapView
        basins={basinsForMap} sites={sites} siteOverall={siteOverall}
        layerProp={layer.prop} basemap={basemap} flyTo={flyTo}
        subbasins={subbasins} pickMode={pickMode}
        onPick={(lat, lng) => setPicked({ lat, lng })}
        onSelect={(s) => setSelected(s)}
      />

      {/* ── Full-screen views (portfolio, pwi, copilot) ── */}
      {view === "portfolio" && (
        <PortfolioView
          sites={sites} basinByPfaf={basinByPfaf} futures={futures}
          onDrill={drillTo} onReload={reload}
        />
      )}
      {view === "pwi" && <PwiView selectedSite={selected ? { name: selected.name, lat: selected.lat, lng: selected.lng } : null} />}
      {view === "evidence" && <EvidenceView />}
      {view === "twin" && <TwinView sites={sites} selectedSite={selected} />}
      {view === "copilot" && <CopilotView />}

      {/* ── Header bar (fixed, full-width) ── */}
      <TopNav view={view} onView={setView}
        onGo={(p) => setFlyTo({ lat: p.lat, lng: p.lng })}
        onSignOut={() => {
          supa?.auth.signOut().catch(() => { /* guest session — nothing to revoke */ });
          sessionStorage.removeItem("hydris_entered");
          setSelected(null);
          setView("map");
          setAppState("landing");
        }} />

      {/* ── Map-view overlays ── */}
      {view === "map" && <>
        {/* Left sidebar: layer selector + legend + basemap */}
        <div className="left-sidebar glass">
          <LayerSelector layerId={layerId} onChange={setLayerId} />
          <Legend layerLabel={layer.label} />
          <BasemapToggle value={basemap} onChange={setBasemap} />
        </div>

        {/* Right sidebar: selected plant info + driver explanations */}
        {selected && (
          <div className="right-sidebar glass">
            <RiskCard
              site={selected} cache={cache} basinProps={selectedProps}
              onExplain={(r) => setExplainRisk(r)} onClose={() => setSelected(null)}
            />
            {/* Action buttons for bottom popups */}
            <div className="right-actions">
              <button onClick={() => openBottomPopup("future")} className={showFuture ? "primary" : ""}>
                {showFuture ? "Hide" : "Show"} 2030/2050
              </button>
              <button onClick={() => openBottomPopup("weights")} className={showWeights ? "primary" : ""}>
                {showWeights ? "Hide" : "Custom"} weights
              </button>
              <button onClick={() => openBottomPopup("news")} className={showNews ? "primary" : ""}>
                Local news
              </button>
            </div>
            {subsLoading && (
              <div className="subs-loading">loading level-9 sub-basins…</div>
            )}
            {/* Driver explanation panel — renders inline, scrolls with sidebar */}
            {explainRisk && (
              <div className="driver-inline">
                <DriverPanel site={selected} risk={explainRisk} onClose={() => setExplainRisk(null)} />
              </div>
            )}
          </div>
        )}

        {/* Bottom popups: FuturePanel, WeightsPanel, NewsPanel */}
        {selected && showFuture && (
          <div className={`bottom-popup glass${hasRightSidebar ? " with-right" : ""}`}>
            <FuturePanel site={selected}
              baselineScarcity={cache?.profile?.bws?.score ?? selectedProps.bws ?? null}
              onClose={() => setShowFuture(false)} />
          </div>
        )}
        {selected && showWeights && (
          <div className={`bottom-popup glass${hasRightSidebar ? " with-right" : ""}`}>
            <WeightsPanel site={selected} onResult={setCustomOverall}
              onClose={() => { setShowWeights(false); setCustomOverall(null); }} />
          </div>
        )}
        {selected && showNews && (
          <div className={`bottom-popup glass${hasRightSidebar ? " with-right" : ""}`}>
            <NewsPanel site={selected} onClose={() => setShowNews(false)} />
          </div>
        )}

        {/* factory input */}
        <button className={`primary fab${hasRightSidebar ? " with-sidebar" : ""}`} title="Add factory site" onClick={() => setAddOpen(true)}>+</button>
        {addOpen && (
          <AddSiteModal
            pick={picked}
            onPickMode={(on) => { setPickMode(on); if (!on) setPicked(null); }}
            onDone={reload}
            onClose={() => { setAddOpen(false); setPickMode(false); setPicked(null); }}
          />
        )}

        {showHint && !selected && (
          <div className="map-hint glass">
            <span>Click a colored pin to inspect a factory's water risk — or press <b>+</b> to assess a new site</span>
            <button onClick={dismissHint} aria-label="dismiss hint">Got it</button>
          </div>
        )}

        <div className="attribution">
          WRI Aqueduct 4.0 · Google Earth Engine · CHIRPS · GLDAS · GRACE · SMAP · HydroSHEDS · GHSL — free with attribution
        </div>
      </>}
    </div>
  );
}
