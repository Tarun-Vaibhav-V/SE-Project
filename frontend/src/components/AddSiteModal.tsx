import { useEffect, useState } from "react";
import { addSite } from "../lib/data";
import { riskColor } from "../lib/risk";

/** Factory input: name, optional id, lat/lng (typed or picked from the map).
 * Submit runs the full pipeline server-side; the pin is live when this closes. */
export default function AddSiteModal({ pick, onPickMode, onDone, onClose }: {
  pick: { lat: number; lng: number } | null;   // filled by map click while in pick mode
  onPickMode: (on: boolean) => void;
  onDone: () => void;                          // reload sites+basins
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (pick && picking) {
      setLat(pick.lat.toFixed(5)); setLng(pick.lng.toFixed(5));
      setPicking(false); onPickMode(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pick]);

  const submit = async () => {
    const la = parseFloat(lat), ln = parseFloat(lng);
    if (!name.trim() || Number.isNaN(la) || Number.isNaN(ln)) { setError("name + valid lat/lng required"); return; }
    if (la < -90 || la > 90 || ln < -180 || ln > 180) { setError("lat must be -90..90, lng -180..180"); return; }
    setBusy(true); setError(null);
    try {
      const res = await addSite({ name: name.trim(), id: id.trim() || undefined, lat: la, lng: ln });
      setResult(res);
      onDone();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally { setBusy(false); }
  };

  return (
    <div className="glass addsite">
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <b style={{ fontSize: 14 }}>Add factory site</b>
        <button onClick={() => { onPickMode(false); onClose(); }} style={{ padding: "2px 9px" }}>×</button>
      </div>

      {!result ? (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input type="text" placeholder="Factory name *" value={name} onChange={(e) => setName(e.target.value)} />
            <input type="text" placeholder="Site ID (optional, e.g. MFG-021)" value={id} onChange={(e) => setId(e.target.value)} />
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" placeholder="Latitude *" value={lat} onChange={(e) => setLat(e.target.value)} />
              <input type="text" placeholder="Longitude *" value={lng} onChange={(e) => setLng(e.target.value)} />
            </div>
            <button onClick={() => { const on = !picking; setPicking(on); onPickMode(on); }}
              style={picking ? { borderColor: "var(--accent)", color: "var(--accent)" } : {}}>
              {picking ? "…click the map to set coordinates" : "📍 Pick on map"}
            </button>
            <button className="primary" onClick={submit} disabled={busy}>
              {busy ? "Resolving basin + computing risk…" : "Assess site"}
            </button>
            {error && <div style={{ color: "var(--risk-3)", fontSize: 11 }}>{error}</div>}
            <div style={{ fontSize: 10, color: "var(--faint)" }}>
              On submit: watershed resolve → 13-indicator profile → PWI dims → 2030/2050 futures,
              all cached to Supabase. Driver "why" computes on first click (~1–2 min).
            </div>
          </div>
        </>
      ) : (
        <div style={{ fontSize: 12, lineHeight: 1.7 }}>
          <div><b>{result.site.name}</b> · basin {result.site.pfaf_id}</div>
          <div>
            overall <b className="num" style={{ color: riskColor(result.overall), fontSize: 18 }}>
              {result.overall?.toFixed(2)}
            </b>{" "}
            <span className="pill" style={{ background: riskColor(result.overall), color: "#fff", fontSize: 10 }}>
              {result.level}
            </span>
          </div>
          <div style={{ color: "var(--muted)" }}>
            PWI — Avail {result.pwi?.Availability ?? "n/d"} · Qual {result.pwi?.Quality ?? "n/d"} · Access {result.pwi?.Accessibility ?? "n/d"}
          </div>
          <button className="primary" style={{ marginTop: 8, width: "100%" }} onClick={onClose}>
            Done — site is on the map
          </button>
        </div>
      )}
    </div>
  );
}
