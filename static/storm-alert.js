/**
 * v13.1 — Alerte orage proximité (page d'accueil)
 * Bandeau fixe rouge/orange + bip sonore au déclenchement d'un nouvel impact
 * < 30km. Sécurité opérateur : l'utilisateur concentré sur l'écran doit être
 * alerté sans avoir à consulter la page /weather.
 */

(function stormAlertInit() {
  const API_URL = '/api/weather/storm_proximity.json';
  const POLL_INTERVAL_MS = 60000; // 60s — la foudre évolue vite mais pas assez pour justifier moins
  let lastAlertedStrikeTs = null; // réapparaît seulement sur un NOUVEL impact, pas à chaque poll
  let audioCtx = null;

  function playBeep() {
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.4);
      // Double bip
      setTimeout(() => {
        const osc2 = audioCtx.createOscillator();
        const gain2 = audioCtx.createGain();
        osc2.connect(gain2);
        gain2.connect(audioCtx.destination);
        osc2.frequency.value = 880;
        gain2.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gain2.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
        osc2.start();
        osc2.stop(audioCtx.currentTime + 0.4);
      }, 500);
    } catch (e) {
      console.debug('[StormAlert] Audio non disponible (interaction utilisateur requise):', e);
    }
  }

  function fmtAge(ts) {
    const ageMin = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
    if (ageMin < 1) return "à l'instant";
    if (ageMin === 1) return "il y a 1 min";
    return `il y a ${ageMin} min`;
  }

  function showBanner(data) {
    let banner = document.getElementById('storm-proximity-banner');
    const isNewStrike = lastAlertedStrikeTs !== data.last_strike_ts;

    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'storm-proximity-banner';
      banner.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background: linear-gradient(90deg, #7f1d1d 0%, #b45309 100%);
        color: white;
        padding: 12px 20px;
        font-size: 14px;
        font-family: 'Share Tech Mono', monospace;
        z-index: 10000;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        border-bottom: 2px solid #ff9e2c;
        animation: storm-pulse 2s ease-in-out infinite;
      `;
      if (!document.getElementById('storm-pulse-keyframes')) {
        const style = document.createElement('style');
        style.id = 'storm-pulse-keyframes';
        style.textContent = `
          @keyframes storm-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.82; }
          }
        `;
        document.head.appendChild(style);
      }
      document.body.insertBefore(banner, document.body.firstChild);
    }

    const distTxt = data.distance_km.toFixed(1);
    const dirTxt = data.bearing_compass ? ` (${data.bearing_compass})` : '';
    banner.innerHTML = `
      <span>
        ⚡ <strong>ORAGE À ${distTxt} KM</strong>${dirTxt} — ${data.strikes_count} impact(s) &lt;${data.radius_km}km / ${data.window_min}min, dernier ${fmtAge(data.last_strike_ts)}
      </span>
      <button id="storm-banner-close" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;padding:0 10px;opacity:0.8;">✕</button>
    `;
    document.body.style.paddingTop = banner.offsetHeight + 'px';

    document.getElementById('storm-banner-close').onclick = () => {
      banner.remove();
      document.body.style.paddingTop = '0';
    };

    if (isNewStrike) {
      playBeep();
      lastAlertedStrikeTs = data.last_strike_ts;
    }
  }

  function hideBanner() {
    const banner = document.getElementById('storm-proximity-banner');
    if (banner) {
      banner.remove();
      document.body.style.paddingTop = '0';
    }
    lastAlertedStrikeTs = null;
  }

  async function checkStormProximity() {
    try {
      const r = await fetch(API_URL, { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      if (data.alert) {
        showBanner(data);
      } else {
        hideBanner();
      }
    } catch (e) {
      console.debug('[StormAlert] Check échoué:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkStormProximity);
  } else {
    checkStormProximity();
  }
  setInterval(checkStormProximity, POLL_INTERVAL_MS);
})();
