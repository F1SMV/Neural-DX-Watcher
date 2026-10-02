/**
 * §24 Auto-Test Widget pour AI Insight
 * Affiche les prédictions, validations et le feedback loop en temps réel
 */

class AutoTestWidget {
    constructor() {
        this.refreshInterval = null;
        this.stats = null;
        this.predictions = [];
    }

    async init() {
        /**
         * Initialiser et charger les données initiales
         */
        await this.refresh();
        
        // Auto-refresh toutes les 10 secondes
        this.refreshInterval = setInterval(() => this.refresh(), 10000);
    }

    async refresh() {
        /**
         * Récupérer les données des APIs
         */
        try {
            const [statsRes, predictionsRes] = await Promise.all([
                fetch('/api/adaptive/autotest/stats.json'),
                fetch('/api/adaptive/autotest/latest.json?limit=20')
            ]);

            if (!statsRes.ok || !predictionsRes.ok) {
                console.warn('[AutoTest] APIs indisponibles');
                return;
            }

            const stats = await statsRes.json();
            const predictions = await predictionsRes.json();

            this.stats = stats;
            this.predictions = predictions.predictions || [];

            this.render();
        } catch (e) {
            console.error('[AutoTest]', e);
        }
    }

    render() {
        /**
         * Afficher le widget
         */
        const container = document.getElementById('autotest-container');
        if (!container) return;

        const stats = this.stats || {};
        const preds = this.predictions || [];

        // Boucle fermée : montrer le flux
        const flowHtml = this.renderFlowDiagram();
        const legendHtml = this.renderLegend();
        const statsHtml = this.renderStats(stats);
        const predictionsHtml = this.renderPredictions(preds);

        container.innerHTML = `
            <div class="autotest-panel">
                ${flowHtml}
                ${legendHtml}
                <hr style="border-color:rgba(255,255,255,.1);margin:12px 0;">
                ${statsHtml}
                <hr style="border-color:rgba(255,255,255,.1);margin:12px 0;">
                ${predictionsHtml}
            </div>
        `;
    }

    renderFlowDiagram() {
        /**
         * Montrer visuellement la boucle fermée
         * 
         * Prédiction → Spot → Validation → DriftMonitor → Amélioration
         */
        return `
            <div class="autotest-flow">
                <div class="flow-step">
                    <div class="flow-number">1</div>
                    <div class="flow-label">Prédiction</div>
                    <div class="flow-detail">Heure/Bande/Mode</div>
                </div>
                <div class="flow-arrow">→</div>
                
                <div class="flow-step">
                    <div class="flow-number">2</div>
                    <div class="flow-label">Spot Réel</div>
                    <div class="flow-detail">Cluster ou WSJTX</div>
                </div>
                <div class="flow-arrow">→</div>
                
                <div class="flow-step">
                    <div class="flow-number">3</div>
                    <div class="flow-label">Validation</div>
                    <div class="flow-detail">Match Score</div>
                </div>
                <div class="flow-arrow">→</div>
                
                <div class="flow-step">
                    <div class="flow-number">4</div>
                    <div class="flow-label">DriftMonitor</div>
                    <div class="flow-detail">ECE, Dérive</div>
                </div>
                <div class="flow-arrow">↻</div>
                
                <div class="flow-step">
                    <div class="flow-number">5</div>
                    <div class="flow-label">Amélioration</div>
                    <div class="flow-detail">NightlyCycle</div>
                </div>
            </div>
        `;
    }

    renderLegend() {
        /**
         * Légende explicative FR + EN (14px, orange) — lecture des 3 métriques
         */
        const O = 'color:#ff9e2c;font-size:14px;line-height:1.5;';
        return `
            <div class="autotest-legend" style="${O}padding:10px 12px;margin-top:10px;
                 border:1px solid rgba(255,158,44,.35);border-radius:8px;
                 background:rgba(255,158,44,.06);">
                <div style="font-weight:700;margin-bottom:6px;">
                    Comment lire ce panneau · How to read this panel
                </div>
                <div style="margin:3px 0;">
                    <b>Prédictions</b> — paris d'activité émis (1 par bande, chaque heure).<br>
                    <span style="opacity:.85;"><i>Predictions — activity bets issued (1 per band, every hour).</i></span>
                </div>
                <div style="margin:3px 0;">
                    <b>Validées</b> — paris confirmés par un vrai spot reçu dans l'heure (et leur %).<br>
                    <span style="opacity:.85;"><i>Validated — bets confirmed by a real spot within the hour (and their %).</i></span>
                </div>
                <div style="margin:3px 0;">
                    <b>Score moyen</b> — fraîcheur des confirmations : 1,00 = spot quasi immédiat, 0 = tardif (≈60 min).<br>
                    <span style="opacity:.85;"><i>Avg score — freshness of confirmations: 1.00 = near-instant spot, 0 = late (≈60 min).</i></span>
                </div>
                <div style="margin:6px 0 0;opacity:.85;">
                    Chaque validation alimente le <b>DriftMonitor</b>, qui ajuste le scoring via le <b>NightlyCycle</b> (3 h UTC).<br>
                    <i>Each validation feeds the DriftMonitor, which tunes scoring through the NightlyCycle (03:00 UTC).</i>
                </div>
            </div>
        `;
    }

    renderStats(stats) {
        /**
         * Afficher les statistiques globales
         */
        if (!stats.ok) {
            return `<div class="no-data">Auto-Test indisponible</div>`;
        }

        const totalPreds = stats.total_predictions || 0;
        const validated = stats.validated || 0;
        const avgScore = (stats.avg_match_score || 0).toFixed(2);
        const validationRate = totalPreds > 0 ? ((validated / totalPreds) * 100).toFixed(1) : 0;

        // Par bande
        const perBandHtml = Object.entries(stats.per_band || {})
            .map(([band, data]) => `
                <div class="band-stat">
                    <div class="band-name">${band}</div>
                    <div class="band-data">
                        <span class="count">${data.count} validations</span>
                        <span class="score">score ${(data.avg_score || 0).toFixed(2)}</span>
                    </div>
                </div>
            `)
            .join('');

        return `
            <div class="autotest-stats">
                <div class="stat-row">
                    <div class="stat-box">
                        <div class="stat-label">Prédictions</div>
                        <div class="stat-value">${totalPreds}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Validées</div>
                        <div class="stat-value">${validated} (${validationRate}%)</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">Score moyen</div>
                        <div class="stat-value">${avgScore}</div>
                    </div>
                </div>
                
                <div class="per-band-stats">
                    <div class="stat-label" style="margin-bottom:8px;">Par bande:</div>
                    ${perBandHtml}
                </div>
            </div>
        `;
    }

    renderPredictions(preds) {
        /**
         * Afficher les prédictions/validations récentes
         */
        if (preds.length === 0) {
            return `<div class="no-data">Aucune prédiction pour le moment</div>`;
        }

        const rows = preds.slice(0, 15).map(p => {
            const validated = p.actual_call ? '✓' : '○';
            const score = p.match_score ? (p.match_score * 100).toFixed(0) : '—';
            const prob = (p.pred_probability * 100).toFixed(0);
            
            return `
                <tr>
                    <td class="pred-band">${p.band}</td>
                    <td class="pred-mode">${p.mode}</td>
                    <td class="pred-hour">${p.hour_utc}h</td>
                    <td class="pred-prob">${prob}%</td>
                    <td class="pred-actual">${p.actual_call || '—'}</td>
                    <td class="pred-score">${score}</td>
                    <td class="pred-status">${validated}</td>
                </tr>
            `;
        }).join('');

        return `
            <div class="autotest-predictions">
                <div class="stat-label" style="margin-bottom:8px;">Prédictions récentes:</div>
                <table class="pred-table">
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
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
    }

    destroy() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }
}

// Initialiser au chargement de la page
document.addEventListener('DOMContentLoaded', () => {
    const widget = new AutoTestWidget();
    widget.init();
});
