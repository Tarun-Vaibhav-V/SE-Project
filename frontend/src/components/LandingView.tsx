import React, { useEffect, useRef, useState } from 'react';

declare global {
  interface Window { WE: any; }
}

interface LandingViewProps {
  onLoginClick: () => void;
}

export default function LandingView({ onLoginClick }: LandingViewProps) {
  const earthRef = useRef<any>(null);
  const animFrameRef = useRef<number>(0);
  const [zooming, setZooming] = useState(false);

  useEffect(() => {
    const initEarth = () => {
      const WE = window.WE;
      const container = document.getElementById('earth_div');
      if (!container || !WE || earthRef.current) return;

      const earth = new WE.map('earth_div', {
        zoom: 2.8,
        dragging: true,
        scrollWheelZoom: false,
        sky: true,
        atmosphere: true,
        center: [20, 0],
      });
      earthRef.current = earth;

      WE.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: '© Esri', maxZoom: 18 }
      ).addTo(earth);

      // Fix popup text styling after WE injects its own leaflet CSS
      injectPopupStyle();

      // Add risk markers
      WE.marker([39.5, -105.35])
        .addTo(earth)
        .bindPopup('<b style="color:#1e293b">Colorado River</b><br><span style="color:#475569">High Scarcity Risk</span>');
      WE.marker([13.08, 80.27])
        .addTo(earth)
        .bindPopup('<b style="color:#1e293b">Chennai</b><br><span style="color:#475569">Drought Risk</span>');
      WE.marker([-33.86, 151.2])
        .addTo(earth)
        .bindPopup('<b style="color:#1e293b">Sydney</b><br><span style="color:#475569">Flood Exposure</span>');

      earth.setView([20, 0], 2.8);

      // Slow auto-rotation
      let last: number | null = null;
      const rotate = (now: number) => {
        const c = earth.getPosition();
        if (c) {
          const dt = last ? now - last : 16;
          last = now;
          earth.setView([c[0], c[1] + 0.018 * (dt / 16)]);
        }
        animFrameRef.current = requestAnimationFrame(rotate);
      };
      animFrameRef.current = requestAnimationFrame(rotate);
    };

    if (!window.WE) {
      const script = document.createElement('script');
      // https, not http — a plain-http script is blocked as mixed content the
      // moment this page is served over https (Vercel/any deploy)
      script.src = 'https://www.webglearth.com/v2/api.js';
      script.async = true;
      script.onload = initEarth;
      document.head.appendChild(script);
    } else {
      initEarth();
    }

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      earthRef.current = null;
      const c = document.getElementById('earth_div');
      if (c) c.innerHTML = '';
    };
  }, []);

  const handleSignIn = () => {
    if (zooming) return;
    // globe failed to load (offline / script blocked)? never lock the user out —
    // skip the zoom flourish and go straight to login
    if (!earthRef.current) { onLoginClick(); return; }
    setZooming(true);

    // Stop auto-rotation
    cancelAnimationFrame(animFrameRef.current);

    const earth = earthRef.current;
    const startZoom = earth.getZoom?.() ?? 2.8;
    const targetZoom = 9;
    const duration = 1800; // ms
    const start = performance.now();

    const zoomIn = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      // Ease-in cubic
      const ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      const z = startZoom + (targetZoom - startZoom) * ease;
      const c = earth.getPosition();
      if (c) earth.setView([c[0], c[1]], z);
      if (t < 1) {
        requestAnimationFrame(zoomIn);
      } else {
        // Transition to login after zoom completes
        setTimeout(() => onLoginClick(), 100);
      }
    };
    requestAnimationFrame(zoomIn);
  };

  return (
    <div style={{ position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden', background: '#020617' }}>
      {/* Full-screen 3D Earth */}
      <div
        id="earth_div"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', zIndex: 0 }}
      />

      {/* Gradient overlay so text is readable over the earth */}
      <div style={{
        position: 'absolute', inset: 0, zIndex: 1,
        background: 'linear-gradient(to right, rgba(2,6,23,0.85) 40%, rgba(2,6,23,0.1) 100%)',
        pointerEvents: 'none',
      }} />

      {/* Nav */}
      <nav style={{
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '1.5rem 3rem',
        background: 'rgba(2,6,23,0.4)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        fontFamily: "'Inter', system-ui, sans-serif",
      }}>
        <div style={{ fontSize: '1.5rem', fontWeight: 600, color: '#fff', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          💧 Hydris <b style={{ color: '#38bdf8' }}>AI</b>
        </div>
        <div style={{ display: 'flex', gap: '2rem', color: '#94a3b8', fontSize: '0.95rem', cursor: 'pointer' }}>
          <span>Platform</span><span>Solutions</span><span>Data &amp; Tech</span><span>Pricing</span>
        </div>
        <button
          className="primary"
          onClick={handleSignIn}
          disabled={zooming}
          style={{ opacity: zooming ? 0.5 : 1 }}
        >
          {zooming ? 'Entering...' : 'Sign In'}
        </button>
      </nav>

      {/* Hero text — left side */}
      <div style={{
        position: 'absolute', top: '50%', left: '3rem', zIndex: 10,
        transform: 'translateY(-50%)', maxWidth: '560px',
        fontFamily: "'Inter', system-ui, sans-serif",
        transition: 'opacity 0.5s',
        opacity: zooming ? 0 : 1,
      }}>
        <h1 style={{
          fontSize: '3.8rem', fontWeight: 700, lineHeight: 1.1, color: '#fff',
          background: 'linear-gradient(to right, #fff, #94a3b8)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          marginBottom: '1.25rem',
        }}>
          Master Water Risk<br />with Basin Intelligence.
        </h1>
        <p style={{ fontSize: '1.1rem', color: '#94a3b8', lineHeight: 1.7, marginBottom: '2.5rem' }}>
          Predict, mitigate, and adapt to global water challenges using satellite-driven truth.
          Understand droughts, floods, and groundwater depletion — explained, not invented.
        </p>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="primary" style={{ padding: '0.9rem 2rem', fontSize: '1rem', borderRadius: '8px' }} onClick={handleSignIn}>
            Explore Platform
          </button>
          <button className="secondary" style={{ padding: '0.9rem 2rem', fontSize: '1rem', borderRadius: '8px', background: 'transparent', border: '1px solid rgba(255,255,255,0.2)', color: '#94a3b8', cursor: 'pointer' }}>
            Watch Video
          </button>
        </div>
      </div>

      {/* Stat chips — bottom left */}
      <div style={{
        position: 'absolute', bottom: '2rem', left: '3rem', zIndex: 10,
        display: 'flex', gap: '1rem',
        fontFamily: "'Inter', system-ui, sans-serif",
        transition: 'opacity 0.5s', opacity: zooming ? 0 : 1,
      }}>
        {[
          { label: 'Basins Monitored', value: '1,482' },
          { label: 'Risk Indicators', value: '13' },
          { label: 'Satellite Sources', value: '9+' },
        ].map(({ label, value }) => (
          <div key={label} style={{
            background: 'rgba(15,23,42,0.7)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px',
            padding: '0.75rem 1.25rem', color: '#fff',
          }}>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#38bdf8' }}>{value}</div>
            <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Inject popup text style to fix invisible text inside WebGLEarth popups */
function injectPopupStyle() {
  if (document.getElementById('we-popup-fix')) return;
  const style = document.createElement('style');
  style.id = 'we-popup-fix';
  style.textContent = `
    .leaflet-popup-content-wrapper {
      background: #fff !important;
      color: #1e293b !important;
      border-radius: 10px !important;
      box-shadow: 0 8px 24px rgba(0,0,0,0.3) !important;
      padding: 0 !important;
    }
    .leaflet-popup-content {
      margin: 10px 14px !important;
      color: #1e293b !important;
      font-family: 'Inter', system-ui, sans-serif !important;
      font-size: 13px !important;
      line-height: 1.5 !important;
    }
    .leaflet-popup-tip {
      background: #fff !important;
    }
  `;
  document.head.appendChild(style);
}
