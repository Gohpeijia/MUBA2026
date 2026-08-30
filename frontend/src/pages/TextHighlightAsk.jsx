import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FaRobot } from 'react-icons/fa';
import './TextHighlightAsk.css';

/**
 * TextHighlightAsk
 * ─────────────────────────────────────────────────────────────
 * Listens for text selection anywhere on the page.
 * When the user selects text and releases the mouse, a small
 * "Ask AI" pill appears near the selection.
 * Clicking it calls onAskAI(selectedText).
 *
 * Props:
 *   onAskAI {fn(text: string)} — called with the highlighted text
 */
export default function TextHighlightAsk({ onAskAI }) {
  const [visible, setVisible]     = useState(false);
  const [position, setPosition]   = useState({ x: 0, y: 0 });
  const [selected, setSelected]   = useState('');
  const btnRef                    = useRef(null);

  const handleMouseUp = useCallback((e) => {
    // Don't trigger inside the AI panel itself
    if (e.target.closest('.ai-panel') || e.target.closest('.text-highlight-ask-btn')) return;

    const sel = window.getSelection();
    const text = sel?.toString().trim();

    if (!text || text.length < 3) {
      setVisible(false);
      return;
    }

    const range = sel.getRangeAt(0);
    const rect  = range.getBoundingClientRect();

    setSelected(text);
    setPosition({
      x: rect.left + rect.width / 2 + window.scrollX,
      y: rect.top  - 42 + window.scrollY,
    });
    setVisible(true);
  }, []);

  /* Hide when clicking elsewhere */
  const handleMouseDown = useCallback((e) => {
    if (!e.target.closest('.text-highlight-ask-btn')) {
      setVisible(false);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('mouseup',   handleMouseUp);
    document.addEventListener('mousedown', handleMouseDown);
    return () => {
      document.removeEventListener('mouseup',   handleMouseUp);
      document.removeEventListener('mousedown', handleMouseDown);
    };
  }, [handleMouseUp, handleMouseDown]);

  const handleClick = () => {
    if (!selected) return;
    onAskAI(selected);
    setVisible(false);
    window.getSelection()?.removeAllRanges();
  };

  if (!visible) return null;

  return (
    <button
      ref={btnRef}
      className="text-highlight-ask-btn"
      style={{ left: position.x, top: position.y }}
      onClick={handleClick}
      onMouseDown={(e) => e.preventDefault()} /* prevents losing selection */
      aria-label="Ask AI about selected text"
    >
      <FaRobot size={12} />
      <span>Ask AI</span>
    </button>
  );
}