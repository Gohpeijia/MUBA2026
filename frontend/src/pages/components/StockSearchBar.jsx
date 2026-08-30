import React, { useState, useRef, useCallback, useEffect, memo } from 'react';

/**
 * StockSearchBar — search input + live dropdown.
 *
 * Props:
 * onSelect : ({ ticker, name, exchange }) => void
 * fetchSearchResults : async (query) => [{ ticker, name, exchange }]
 */
const StockSearchBar = memo(function StockSearchBar({ onSelect, fetchSearchResults }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1); // NEW: Tracks keyboard selection

  const debounceTimer = useRef(null);
  const wrapRef = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    
    // NEW: Cleanup event listener AND the debounce timer on unmount
    return () => {
      document.removeEventListener('mousedown', handleClick);
      clearTimeout(debounceTimer.current);
    };
  }, []);

  const handleChange = useCallback((e) => {
  const val = e.target.value;
  setQuery(val);
  setActiveIndex(-1); 

  // 1. Clear the previous timer if the user is still typing
  if (debounceTimer.current) {
    clearTimeout(debounceTimer.current);
  }

  // 2. Set a new timer to wait 500ms before fetching
  debounceTimer.current = setTimeout(async () => {
    if (val.trim()) {
      setLoading(true);
      const data = await fetchSearchResults(val);
      setResults(data);
      setLoading(false);
      setOpen(true);
    } else {
      setResults([]);
      setOpen(false);
    }
  }, 500); // 500 milliseconds is the sweet spot
}, [fetchSearchResults]);

  const handleSelect = useCallback((item) => {
    setQuery('');
    setOpen(false);
    setResults([]);
    setActiveIndex(-1);
    onSelect(item);
  }, [onSelect]);

  const handleClear = useCallback(() => {
    setQuery('');
    setOpen(false);
    setResults([]);
    setActiveIndex(-1);
    clearTimeout(debounceTimer.current);
  }, []);

  // NEW: Handle Keyboard Navigation (Up, Down, Enter, Escape)
  const handleKeyDown = (e) => {
    if (!open) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => (prev < results.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => (prev > 0 ? prev - 1 : 0));
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(results[activeIndex]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className="stock-search-wrap" ref={wrapRef}>
      <div className="stock-search-input-row">
        <span className="stock-search-icon">🔍</span>
        <input
          className="stock-search-input"
          type="text"
          placeholder="Cari saham melalui ticker atau nama…"
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown} // Attached keyboard listener here
          onFocus={() => query.trim() && setOpen(true)}
          autoComplete="off"
          spellCheck={false}
        />
        {query && (
          <button className="stock-search-clear" onClick={handleClear} title="Clear">✕</button>
        )}
      </div>

      {open && (
        <div className="stock-search-dropdown">
          {loading ? (
            <div className="search-dropdown-item loading">Searching…</div>
          ) : results.length === 0 ? (
            <div className="search-dropdown-item loading">No results found</div>
          ) : (
            results.map((item, index) => (
              <div
                key={item.ticker}
                // NEW: Dynamically add an "active" class if hovered via keyboard
                className={`search-dropdown-item ${index === activeIndex ? 'active' : ''}`}
                onMouseDown={() => handleSelect(item)}
                onMouseEnter={() => setActiveIndex(index)} // Sync mouse hover with keyboard focus
              >
                <span className="dropdown-ticker">{item.ticker}</span>
                <span className="dropdown-name">{item.name}</span>
                <span className="dropdown-exchange">{item.exchange}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
});

export default StockSearchBar;