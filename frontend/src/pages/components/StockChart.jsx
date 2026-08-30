import React, { useState, memo } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

const PERIODS = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

/**
 * StockChart — price area chart with period selector + watchlist star.
 *
 * Props:
 *  ticker     : string
 *  chartData  : [{ label: string, price: number }]  — already filtered to current period
 *  period     : string ('1D' | '1W' | '1M' | '3M' | '1Y' | 'ALL')
 *  onPeriod   : (period) => void
 *  high       : number | null
 *  low        : number | null
 *  isSaved    : bool
 *  onToggleSave: () => void
 *  loading    : bool
 *  isPositive : bool  — drives chart color (green vs red)
 */
const StockChart = memo(function StockChart({
  chartData,
  period,
  onPeriod,
  high,
  low,
  isSaved,
  onToggleSave,
  loading,
  isPositive,
}) {
  const color = isPositive ? 'var(--green)' : 'var(--red)';
  const colorSoft = isPositive ? 'var(--green-soft)' : 'var(--red-soft)';

  // Custom tooltip
  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      return (
        <div style={{
          background: 'var(--card-bg)',
          border: '1.5px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          padding: '0.5rem 0.8rem',
          boxShadow: 'var(--shadow)',
          fontSize: '0.82rem',
          color: 'var(--text-primary)',
        }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
          <div style={{ color, fontWeight: 700, fontFamily: "'Playfair Display', serif" }}>
            {payload[0].value?.toFixed(3)}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="stock-chart-card">
      <div className="chart-top-row">
        <div className="chart-period-btns">
          {PERIODS.map(p => (
            <button
              key={p}
              className={`chart-period-btn${period === p ? ' active' : ''}`}
              onClick={() => onPeriod(p)}
            >
              {p}
            </button>
          ))}
        </div>

        <button
          className={`chart-star-btn${isSaved ? ' saved' : ''}`}
          onClick={onToggleSave}
          title={isSaved ? 'Remove from watchlist' : 'Add to watchlist'}
        >
          <span className="chart-star-icon">{isSaved ? '★' : '☆'}</span>
          {isSaved ? 'Saved' : 'Save'}
        </button>
      </div>

      {loading || !chartData || chartData.length === 0 ? (
        <div style={{
          height: 220,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.88rem',
        }}>
          {loading ? 'Loading chart…' : 'No chart data available'}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={color} stopOpacity={0.18} />
                <stop offset="95%" stopColor={color} stopOpacity={0}    />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
           <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: 'var(--text-muted)', fontFamily: 'DM Sans, sans-serif' }}
                 axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
                minTickGap={20} /* ✅ Ditambah: mengelakkan label dari bertindan jika terlalu banyak */
            />
            <YAxis
                 tick={{ fontSize: 11, fill: 'var(--text-muted)', fontFamily: 'DM Sans, sans-serif' }}
                 axisLine={false}
                 tickLine={false}
                 /* FIX: Return numbers for the domain, not strings */
                domain={[
                   dataMin => dataMin * 0.98, 
                  dataMax => dataMax * 1.02  
                ]}
                /* FIX: Format the labels to 2 decimal places here instead */
                tickFormatter={(value) => value.toFixed(2)}
                width={48}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="price"
              stroke={color}
              strokeWidth={2.2}
              fill="url(#chartGradient)"
              dot={false}
              activeDot={{ r: 4, fill: color, strokeWidth: 0 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}

      <div className="chart-highlow-row">
        <div className="highlow-item">
          High: <strong>{high != null ? high.toFixed(3) : '—'}</strong>
        </div>
        <div className="highlow-item">
          Low: <strong>{low != null ? low.toFixed(3) : '—'}</strong>
        </div>
      </div>
    </div>
  );
});

export default StockChart;