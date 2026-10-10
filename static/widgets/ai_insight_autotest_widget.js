/**
 * v13.1 — Widget Prédictions Auto-Test
 * Affiche les prédictions horaires par bande + les validations temps réel
 * Coloration des scores : vert (90+), orange (70-90), gris (<70)
 * UTC clairement indiqué pour éviter toute ambiguïté
 */

const autotestWidget = {
  renderStats: (stats) => {
    if (!stats || !stats.per_band) return '<div class="no-data">Aucune donnée AutoTest</div>';
    
    const rows = Object.entries(stats.per_band)
      .sort((a, b) => b[1].count - a[1].count)
      .map(([band, data]) => {
        const cnt = data.count || 0;
        const score = data.avg_score || 0;
        return `<div class="autotest-stat-row">
          <span class="band-label">${band}</span>
          <span class="stat-detail">${cnt} validations  score ${score.toFixed(2)}</span>
        </div>`;
      }).join('');
    
    return `<div class="autotest-stats">${rows}</div>`;
  },

  renderPredictions: (preds) => {
    if (!preds || !preds.length) 
      return '<div class="no-data">Aucune prédiction pour le moment</div>';
    
    // Grouper par heure pour l'affichage
    const byHour = {};
    preds.forEach(p => {
      if (!byHour[p.hour_utc]) byHour[p.hour_utc] = [];
      byHour[p.hour_utc].push(p);
    });
    
    const hours = Object.keys(byHour).sort((a, b) => parseInt(a) - parseInt(b));
    const now = new Date();
    const nowHour = now.getUTCHours();
    
    const rows = [];
    hours.forEach(h => {
      preds.forEach(p => {
        if (p.hour_utc != h) return;
        
        const isNow = parseInt(h) === nowHour;
        const hasValidation = p.actual_call && p.match_score > 0;
        const score = p.match_score ? Math.round(p.match_score * 100) : 0;
        
        // Couleur du score
        let scoreColor = 'rgba(100,100,100,0.3)'; // <70 : gris
        let scoreText = '—';
        let checkmark = '○';
        
        if (hasValidation) {
          scoreText = score;
          if (score >= 90) {
            scoreColor = 'rgba(0,180,0,0.25)';  // vert
            checkmark = '✓';
          } else if (score >= 70) {
            scoreColor = 'rgba(255,165,0,0.25)'; // orange
            checkmark = '✓';
          } else {
            scoreColor = 'rgba(100,100,100,0.2)';
            checkmark = '○';
          }
        }
        
        const rowStyle = isNow ? 'background: rgba(0,200,0,0.15);' : '';
        const bgStyle = `background: ${scoreColor};`;
        
        rows.push(`
          <tr style="${rowStyle}">
            <td>${p.band}</td>
            <td>${p.mode}</td>
            <td><strong>${String(p.hour_utc).padStart(2,'0')}h UTC</strong></td>
            <td>${p.pred_probability ? Math.round(p.pred_probability*100) : '—'}%</td>
            <td>${p.actual_call || '—'}</td>
            <td style="${bgStyle} text-align: center; font-weight: 600;">${scoreText}</td>
            <td style="text-align: center; color: ${score >= 90 ? 'var(--success)' : score >= 70 ? 'var(--warn)' : '#666'};">${checkmark}</td>
          </tr>
        `);
      });
    });
    
    return `
      <table class="autotest-predictions">
        <thead>
          <tr>
            <th>Bande</th>
            <th>Mode</th>
            <th>Heure</th>
            <th>Prob</th>
            <th>Spot</th>
            <th>Score</th>
            <th>✓</th>
          </tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
      </table>
    `;
  },

  render: async (containerId) => {
    const cont = document.getElementById(containerId);
    if (!cont) return;
    
    try {
      const [statsR, predsR] = await Promise.all([
        fetch('/api/adaptive/autotest/stats.json'),
        fetch('/api/adaptive/autotest/latest.json?limit=30')
      ]);
      
      if (!statsR.ok || !predsR.ok) {
        cont.innerHTML = '<div class="no-data">Erreur chargement AutoTest</div>';
        return;
      }
      
      const stats = await statsR.json();
      const preds = await predsR.json();
      
      const statsHtml = autotestWidget.renderStats(stats);
      const predsHtml = autotestWidget.renderPredictions(preds.predictions || []);
      
      cont.innerHTML = `
        <div class="panel-header">🔮 Auto-Test v13.1</div>
        <div class="autotest-container">
          ${statsHtml}
          <div class="autotest-title">Prédictions récentes :</div>
          ${predsHtml}
        </div>
      `;
    } catch (e) {
      cont.innerHTML = `<div class="no-data">AutoTest indisponible</div>`;
    }
  }
};

// Init au chargement
document.addEventListener('DOMContentLoaded', () => {
  autotestWidget.render('autotest-container');
  // Refresh toutes les 2 min
  setInterval(() => autotestWidget.render('autotest-container'), 120000);
});
