import React, { useState, useCallback, useRef } from 'react';
import WatchCard from './WatchCard';
// stocks.css provides .stocks-sidepanel etc., imported by parent Stocks.jsx

/**
 * StockSidePanel — watchlist sidebar.
 *
 * Props:
 *  watchlist      : [{ ticker, name, price, change, changePct, exchange }]
 *  activeTicker   : string | null
 *  onSelect       : (ticker) => void
 *  onReorder      : (newWatchlist) => void
 *  onDelete       : (ticker) => void
 */
export default function StockSidePanel({
  watchlist,
  activeTicker,
  onSelect,
  onReorder,
  onDelete,
}) {
  const [editMode, setEditMode]   = useState(false);
  const dragSrc   = useRef(null);
  const [dragOverTicker, setDragOverTicker] = useState(null);
  const [draggingTicker, setDraggingTicker] = useState(null);

  const handleDragStart = useCallback((e, ticker) => {
    dragSrc.current = ticker;
    setDraggingTicker(ticker);
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  const handleDragOver = useCallback((e, ticker) => {
    e.preventDefault();
    setDragOverTicker(ticker);
  }, []);

  const handleDrop = useCallback((e, targetTicker) => {
    e.preventDefault();
    if (!dragSrc.current || dragSrc.current === targetTicker) {
      setDragOverTicker(null);
      setDraggingTicker(null);
      return;
    }
    const updated = [...watchlist];
    const fromIdx = updated.findIndex(s => s.ticker === dragSrc.current);
    const toIdx   = updated.findIndex(s => s.ticker === targetTicker);
    const [moved] = updated.splice(fromIdx, 1);
    updated.splice(toIdx, 0, moved);
    onReorder(updated);
    dragSrc.current = null;
    setDragOverTicker(null);
    setDraggingTicker(null);
  }, [watchlist, onReorder]);

  const handleDragEnd = useCallback(() => {
    dragSrc.current = null;
    setDragOverTicker(null);
    setDraggingTicker(null);
  }, []);

  return (
    <aside className="stocks-sidepanel">
      <div className="sidepanel-header">
        <h2 className="sidepanel-title">Watchlist</h2>
        <button
          className={`sidepanel-edit-btn${editMode ? ' active' : ''}`}
          onClick={() => setEditMode(v => !v)}
          title={editMode ? 'Done editing' : 'Edit watchlist'}
        >
          {editMode ? '✓ Done' : '✎ Edit'}
        </button>
      </div>

      <div className="sidepanel-list" onDragLeave={() => setDragOverTicker(null)}>
        {watchlist.length === 0 ? (
          <div className="sidepanel-empty">
            <div className="sidepanel-empty-icon">☆</div>
            <p>Belum ada saham disimpan. Cari saham dan tekan ikon bintang untuk menambahkannya di sini.</p>
          </div>
        ) : (
          watchlist.map(stock => (
            <WatchCard
              key={stock.ticker}
              stock={stock}
              isActive={stock.ticker === activeTicker}
              editMode={editMode}
              onSelect={onSelect}
              onDelete={onDelete}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              isDragging={draggingTicker === stock.ticker}
              isDragOver={dragOverTicker === stock.ticker}
            />
          ))
        )}
      </div>
    </aside>
  );
}