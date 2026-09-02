import React, { useState } from 'react';
import './InvestmentIntelligenceCard.css';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Line
} from 'recharts';
import {
  FaRobot,
  FaShieldAlt,
  FaChartLine,
  FaNewspaper,
  FaBuilding,
  FaCheckCircle,
  FaExclamationTriangle,
  FaBolt,
  FaInfoCircle,
  FaChevronDown,
  FaChevronUp,
  FaClock,
  FaDatabase
} from 'react-icons/fa';

export default function InvestmentIntelligenceCard({ data }) {
  if (!data) return null;

  const [activeTab, setActiveTab] = useState('summary'); // 'summary' | 'chart' | 'cases' | 'risks' | 'agents' | 'data'
  const [expandedAgent, setExpandedAgent] = useState(null);

  const {
    symbol,
    company_name,
    currency = 'USD',
    current_price,
    change_1d_pct,
    chart_data = [],
    decision = 'HOLD',
    confidence = 0.5,
    risk_level = 'MEDIUM',
    summary = '',
    bull_case = [],
    bear_case = [],
    key_reasons = [],
    major_risks = [],
    invalidation_conditions = [],
    agent_consensus = {},
    agents = {},
    data_quality = {},
    data_freshness = {},
    analysis_metadata = {},
    disclaimer = '',
  } = data;

  const confidencePct = Math.round(confidence * 100);

  // Decision badge colors
  const getDecisionTheme = (dec) => {
    switch (dec?.toUpperCase()) {
      case 'BUY':
        return { label: 'BUY', class: 'decision--buy', icon: '🟢' };
      case 'SELL':
        return { label: 'SELL', class: 'decision--sell', icon: '🔴' };
      case 'HOLD':
        return { label: 'HOLD', class: 'decision--hold', icon: '🟡' };
      case 'INSUFFICIENT_DATA':
      default:
        return { label: 'INSUFFICIENT DATA', class: 'decision--insufficient', icon: '⚪' };
    }
  };

  const getRiskTheme = (risk) => {
    switch (risk?.toUpperCase()) {
      case 'LOW':
        return { label: 'LOW RISK', class: 'risk--low' };
      case 'MEDIUM':
        return { label: 'MEDIUM RISK', class: 'risk--medium' };
      case 'HIGH':
        return { label: 'HIGH RISK', class: 'risk--high' };
      case 'EXTREME':
        return { label: 'EXTREME RISK', class: 'risk--extreme' };
      default:
        return { label: 'MODERATE RISK', class: 'risk--medium' };
    }
  };

  const decisionTheme = getDecisionTheme(decision);
  const riskTheme = getRiskTheme(risk_level);

  return (
    <div className="intel-card">
      {/* ── HEADER ── */}
      <div className="intel-card__header">
        <div className="intel-card__title-row">
          <div className="intel-card__symbol-badge">
            <span className="intel-card__symbol">{symbol}</span>
            {company_name && <span className="intel-card__company">{company_name}</span>}
          </div>
          {current_price !== undefined && current_price !== null && (
            <div className="intel-card__price-box">
              <span className="intel-card__price">
                {currency} {Number(current_price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
              </span>
              {change_1d_pct !== undefined && change_1d_pct !== null && (
                <span className={`intel-card__change ${change_1d_pct >= 0 ? 'change--pos' : 'change--neg'}`}>
                  {change_1d_pct >= 0 ? '+' : ''}{change_1d_pct}%
                </span>
              )}
            </div>
          )}
        </div>

        {/* ── VERDICT BANNER ── */}
        <div className="intel-card__verdict-banner">
          <div className={`intel-card__decision-pill ${decisionTheme.class}`}>
            <span className="decision-pill__icon">{decisionTheme.icon}</span>
            <span className="decision-pill__label">{decisionTheme.label}</span>
          </div>

          <div className="intel-card__confidence-box">
            <div className="confidence-box__header">
              <span className="confidence-box__title">Evidence Conviction</span>
              <span className="confidence-box__pct">{confidencePct}%</span>
            </div>
            <div className="confidence-box__bar-track">
              <div
                className={`confidence-box__bar-fill ${decisionTheme.class}`}
                style={{ width: `${Math.max(8, confidencePct)}%` }}
              />
            </div>
            <span className="confidence-box__hint">
              Measures data consistency &amp; strength — not a guarantee of future return.
            </span>
          </div>

          <div className={`intel-card__risk-pill ${riskTheme.class}`}>
            <FaShieldAlt size={12} />
            <span>{riskTheme.label}</span>
          </div>
        </div>
      </div>

      {/* ── 4-AGENT CONSENSUS MATRIX ── */}
      <div className="intel-card__matrix">
        <div className="matrix-tile">
          <div className="matrix-tile__header">
            <FaChartLine size={13} className="matrix-icon text-teal" />
            <span className="matrix-title">Technical</span>
            <span className="matrix-horizon">Short-Term</span>
          </div>
          <div className="matrix-tile__value">
            {agent_consensus.technical || agents.technical?.outlook || 'NEUTRAL'}
          </div>
          <div className="matrix-tile__sub">
            {agents.technical?.confidence ? `${Math.round(agents.technical.confidence * 100)}% conviction` : 'Price momentum'}
          </div>
        </div>

        <div className="matrix-tile">
          <div className="matrix-tile__header">
            <FaBuilding size={13} className="matrix-icon text-indigo" />
            <span className="matrix-title">Fundamental</span>
            <span className="matrix-horizon">Med/Long-Term</span>
          </div>
          <div className="matrix-tile__value">
            {agent_consensus.fundamental || agents.fundamental?.business_quality?.rating || 'EVALUATED'}
          </div>
          <div className="matrix-tile__sub">
            {agents.fundamental?.financial_health?.rating ? `Health: ${agents.fundamental.financial_health.rating}` : 'Financials & Valuation'}
          </div>
        </div>

        <div className="matrix-tile">
          <div className="matrix-tile__header">
            <FaNewspaper size={13} className="matrix-icon text-blue" />
            <span className="matrix-title">News Intel</span>
            <span className="matrix-horizon">Short/Medium</span>
          </div>
          <div className="matrix-tile__value">
            {agent_consensus.news || agents.news?.overall_sentiment || 'NEUTRAL'}
          </div>
          <div className="matrix-tile__sub">
            {agents.news?.thesis_impact ? agents.news.thesis_impact.replace(/_/g, ' ') : 'Sentiment flow'}
          </div>
        </div>

        <div className="matrix-tile matrix-tile--risk">
          <div className="matrix-tile__header">
            <FaShieldAlt size={13} className="matrix-icon text-amber" />
            <span className="matrix-title">Devil's Advocate</span>
            <span className="matrix-horizon">Adversarial</span>
          </div>
          <div className="matrix-tile__value">
            {agent_consensus.risk || agents.risk?.risk_level || 'MEDIUM'}
          </div>
          <div className="matrix-tile__sub">
            {agents.risk?.contradictions?.length ? `${agents.risk.contradictions.length} points challenged` : 'Downside risks'}
          </div>
        </div>
      </div>

      {/* ── NAVIGATION TABS ── */}
      <div className="intel-card__tabs">
        <button
          className={`intel-tab ${activeTab === 'summary' ? 'intel-tab--active' : ''}`}
          onClick={() => setActiveTab('summary')}
        >
          Committee Summary
        </button>
        {chart_data && chart_data.length > 0 && (
          <button
            className={`intel-tab ${activeTab === 'chart' ? 'intel-tab--active' : ''}`}
            onClick={() => setActiveTab('chart')}
          >
            📈 Price &amp; Trends
          </button>
        )}
        <button
          className={`intel-tab ${activeTab === 'cases' ? 'intel-tab--active' : ''}`}
          onClick={() => setActiveTab('cases')}
        >
          Bull &amp; Bear Cases ({bull_case.length + bear_case.length})
        </button>
        <button
          className={`intel-tab ${activeTab === 'risks' ? 'intel-tab--active' : ''}`}
          onClick={() => setActiveTab('risks')}
        >
          Risks &amp; Invalidation ({major_risks.length + invalidation_conditions.length})
        </button>
        <button
          className={`intel-tab ${activeTab === 'agents' ? 'intel-tab--active' : ''}`}
          onClick={() => setActiveTab('agents')}
        >
          Agent Drill-Down
        </button>
        <button
          className={`intel-tab ${activeTab === 'data' ? 'intel-tab--active' : ''}`}
          onClick={() => setActiveTab('data')}
        >
          Audit &amp; Sources
        </button>
      </div>

      {/* ── TAB CONTENT ── */}
      <div className="intel-card__content">
        {/* 1. Summary Tab */}
        {activeTab === 'summary' && (
          <div className="tab-pane">
            <div className="summary-box">
              <div className="summary-box__header">
                <FaRobot className="text-teal" size={14} />
                <span>Investment Committee Deliberation</span>
              </div>
              <p className="summary-box__text">{summary || 'Committee synthesis pending.'}</p>
            </div>

            {key_reasons.length > 0 && (
              <div className="key-reasons-box">
                <h4 className="section-subtitle">Key Deciding Reasons</h4>
                <ul className="reasons-list">
                  {key_reasons.map((reason, idx) => (
                    <li key={idx} className="reason-item">
                      <span className="reason-bullet">•</span>
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* 2. Chart Tab */}
        {activeTab === 'chart' && chart_data && chart_data.length > 0 && (
          <div className="tab-pane">
            <div className="chart-box" style={{ background: '#ffffff', padding: '1.2rem', borderRadius: '12px', border: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.2rem', flexWrap: 'wrap', gap: '0.5rem' }}>
                <div>
                  <h4 style={{ margin: '0 0 0.2rem 0', color: 'var(--teal)', fontSize: '1rem', fontWeight: 700 }}>
                    Historical Price &amp; Moving Averages (1 Year)
                  </h4>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Daily Close Price vs 50-day SMA &amp; 200-day SMA trendline
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.78rem', fontWeight: 600 }}>
                  <span style={{ color: 'var(--teal)' }}>● Price</span>
                  <span style={{ color: '#d97706' }}>--- SMA 50</span>
                  <span style={{ color: '#7c3aed' }}>— SMA 200</span>
                </div>
              </div>

              <div style={{ width: '100%', height: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chart_data} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
                    <defs>
                      <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--teal)" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="var(--teal)" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={30} stroke="#94a3b8" />
                    <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} stroke="#94a3b8" />
                    <Tooltip
                      contentStyle={{ background: '#1c2b2b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.82rem' }}
                      formatter={(val, name) => [val ? `${currency} ${val}` : 'N/A', name === 'price' ? 'Price' : name === 'sma_50' ? '50-Day SMA' : '200-Day SMA']}
                    />
                    <Area type="monotone" dataKey="price" stroke="var(--teal)" strokeWidth={2} fillOpacity={1} fill="url(#priceGradient)" name="price" />
                    <Line type="monotone" dataKey="sma_50" stroke="#d97706" strokeWidth={1.8} strokeDasharray="4 4" dot={false} name="sma_50" />
                    <Line type="monotone" dataKey="sma_200" stroke="#7c3aed" strokeWidth={1.8} dot={false} name="sma_200" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {/* 2. Bull & Bear Cases Tab */}
        {activeTab === 'cases' && (
          <div className="tab-pane cases-grid">
            <div className="case-column case-column--bull">
              <div className="case-header">
                <FaCheckCircle className="text-green" size={14} />
                <span>Strongest Bull Case</span>
              </div>
              {bull_case.length === 0 ? (
                <p className="empty-subtext">No distinct bull catalysts identified.</p>
              ) : (
                <ul className="case-list">
                  {bull_case.map((point, idx) => (
                    <li key={idx} className="case-item case-item--bull">
                      <span className="case-check">✓</span>
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="case-column case-column--bear">
              <div className="case-header">
                <FaExclamationTriangle className="text-red" size={14} />
                <span>Strongest Bear Case</span>
              </div>
              {bear_case.length === 0 ? (
                <p className="empty-subtext">No distinct bear risks identified.</p>
              ) : (
                <ul className="case-list">
                  {bear_case.map((point, idx) => (
                    <li key={idx} className="case-item case-item--bear">
                      <span className="case-warning">⚠</span>
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* 3. Risks & Invalidation Tab */}
        {activeTab === 'risks' && (
          <div className="tab-pane">
            <div className="risks-section">
              <h4 className="section-subtitle">Major Downside Risks (Challenged by Devil's Advocate)</h4>
              {major_risks.length === 0 ? (
                <p className="empty-subtext">No severe risks flagged.</p>
              ) : (
                <div className="risks-list">
                  {major_risks.map((item, idx) => {
                    const isObj = typeof item === 'object' && item !== null;
                    const title = isObj ? item.risk : item;
                    const exp = isObj ? item.explanation : null;
                    const sev = isObj ? item.severity : null;
                    return (
                      <div key={idx} className="risk-card">
                        <div className="risk-card__header">
                          <span className="risk-card__title">{title}</span>
                          {sev && <span className={`risk-badge risk-badge--${sev.toLowerCase()}`}>{sev}</span>}
                        </div>
                        {exp && <p className="risk-card__exp">{exp}</p>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="invalidation-section">
              <div className="invalidation-header">
                <FaBolt className="text-amber" size={13} />
                <h4 className="section-subtitle">Thesis Invalidation Triggers ("What could change this decision?")</h4>
              </div>
              {invalidation_conditions.length === 0 ? (
                <p className="empty-subtext">No explicit invalidation boundaries set.</p>
              ) : (
                <ul className="invalidation-list">
                  {invalidation_conditions.map((cond, idx) => (
                    <li key={idx} className="invalidation-item">
                      <span className="invalidation-icon">⚡</span>
                      <span>{cond}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* 4. Agent Drill-Down Tab */}
        {activeTab === 'agents' && (
          <div className="tab-pane agents-drilldown">
            {[
              { id: 'technical', title: 'Technical Analyst', icon: FaChartLine, report: agents.technical },
              { id: 'fundamental', title: 'Fundamental Analyst', icon: FaBuilding, report: agents.fundamental },
              { id: 'news', title: 'News Intelligence', icon: FaNewspaper, report: agents.news },
              { id: 'risk', title: "Risk / Devil's Advocate", icon: FaShieldAlt, report: agents.risk },
            ].map(({ id, title, icon: Icon, report }) => {
              const isExpanded = expandedAgent === id;
              return (
                <div key={id} className="agent-report-card">
                  <div
                    className="agent-report-card__header"
                    onClick={() => setExpandedAgent(isExpanded ? null : id)}
                  >
                    <div className="agent-header-left">
                      <Icon size={14} className="text-teal" />
                      <span className="agent-report-title">{title}</span>
                      <span className="agent-report-horizon">
                        {report?.time_horizon ? `[${report.time_horizon.replace(/_/g, ' ')}]` : ''}
                      </span>
                    </div>
                    <div className="agent-header-right">
                      <span className="agent-status-tag">{report?.status || 'COMPLETED'}</span>
                      {isExpanded ? <FaChevronUp size={11} /> : <FaChevronDown size={11} />}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="agent-report-card__body">
                      {report ? (
                        <pre className="agent-json-view">{JSON.stringify(report, null, 2)}</pre>
                      ) : (
                        <p className="empty-subtext">Report details unavailable.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 5. Audit & Sources Tab */}
        {activeTab === 'data' && (
          <div className="tab-pane audit-pane">
            <div className="audit-grid">
              <div className="audit-card">
                <div className="audit-card__header">
                  <FaDatabase size={12} className="text-teal" />
                  <span>Data Quality Assessment</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Overall Integrity:</span>
                  <span className={`quality-badge quality-badge--${(data_quality.overall || 'GOOD').toLowerCase()}`}>
                    {data_quality.overall || 'GOOD'}
                  </span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Market Quotes:</span>
                  <span>{data_quality.market_data ? '✅ Verified' : '❌ Unavailable'}</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Corporate Statements:</span>
                  <span>{data_quality.fundamentals || 'FULL'}</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Recent News Stream:</span>
                  <span>{data_quality.news ? `✅ ${data_quality.news_count || 0} Articles` : '❌ None'}</span>
                </div>
                {data_quality.missing_fields?.length > 0 && (
                  <div className="audit-missing">
                    <span className="audit-label">Unsupplied Fields (Explicitly Omitted):</span>
                    <div className="missing-tags">
                      {data_quality.missing_fields.map((f, i) => (
                        <span key={i} className="missing-tag">{f}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="audit-card">
                <div className="audit-card__header">
                  <FaClock size={12} className="text-indigo" />
                  <span>Freshness &amp; Attribution</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Analysis Timestamp:</span>
                  <span>{data_freshness.data_timestamp ? new Date(data_freshness.data_timestamp).toLocaleString() : 'Just now'}</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Financial Feed:</span>
                  <span>Yahoo Finance &amp; Finnhub</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Providers Utilized:</span>
                  <span>{analysis_metadata.providers_used?.join(', ') || 'Groq, OpenRouter'}</span>
                </div>
                <div className="audit-metric">
                  <span className="audit-label">Analysis ID:</span>
                  <span className="font-mono">{analysis_metadata.analysis_id || data.analysis_id || 'N/A'}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── FOOTER DISCLAIMER ── */}
      <div className="intel-card__footer">
        <FaInfoCircle size={11} className="intel-card__info-icon" />
        <span className="intel-card__disclaimer-text">
          {disclaimer || 'AI-generated investment intelligence for informational and research purposes only. Not financial advice.'}
        </span>
      </div>
    </div>
  );
}
