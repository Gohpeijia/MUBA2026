import React, { memo } from 'react';
import '../watchcard.css';

/**
 * WatchCard — single stock in the watchlist side panel.
 *
 * Props:
 *  stock      : { ticker, name, price, change, changePct, exchange }
 *  isActive   : bool — currently viewed stock
 *  editMode   : bool — show drag + delete controls
 *  onSelect   : (ticker) => void
 *  onDelete   : (ticker) => void
 *  onDragStart: (e, ticker) => void
 *  onDragOver : (e, ticker) => void
 *  onDrop     : (e, ticker) => void
 *  isDragging : bool
 *  isDragOver : bool
 */
const WatchCard = memo(function WatchCard({
  stock,
  isActive,
  editMode,
  onSelect,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
  isDragging,
  isDragOver,
}) {
  const { ticker, name, price, change, changePct } = stock;

  const changeClass =
    change > 0 ? 'positive' : change < 0 ? 'negative' : 'neutral';

  const changeLabel =
    change != null
      ? `${change > 0 ? '+' : ''}${(changePct ?? 0).toFixed(2)}%`
      : '—';

  const cardClass = [
    'watch-card',
    isActive && !editMode ? 'active' : '',
    editMode ? 'edit-mode' : '',
    isDragging ? 'dragging' : '',
    isDragOver ? 'drag-over' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      className={cardClass}
      onClick={() => !editMode && onSelect(ticker)}
      draggable={editMode}
      onDragStart={editMode ? (e) => onDragStart(e, ticker) : undefined}
      onDragOver={editMode ? (e) => { e.preventDefault(); onDragOver(e, ticker); } : undefined}
      onDrop={editMode ? (e) => onDrop(e, ticker) : undefined}
    >
      {editMode && (
        <span className="watch-card-drag-handle" title="Drag to reorder">⠿</span>
      )}

      <div className="watch-card-body">
        <span className="watch-card-ticker">{name}</span>
        <span className="watch-card-name">{ticker}</span>
      </div>

      <div className="watch-card-right">
        {price != null ? (
          <span className="watch-card-price">
            {typeof price === 'number' ? price.toFixed(2) : price}
          </span>
        ) : (
          <span className="watch-card-price">—</span>
        )}
        <span className={`watch-card-change ${changeClass}`}>{changeLabel}</span>
      </div>

      {editMode && (
        <button
          className="watch-card-delete-btn"
          title="Remove from watchlist"
          onClick={(e) => { e.stopPropagation(); onDelete(ticker); }}
        >
          ✕
        </button>
      )}
    </div>
  );
});

export default WatchCard;