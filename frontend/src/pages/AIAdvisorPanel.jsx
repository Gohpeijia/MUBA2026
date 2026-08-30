import React, { useState, useRef, useEffect } from 'react';
import { FaRobot, FaPaperPlane, FaPaperclip, FaTimes, FaFileAlt, FaChevronLeft, FaChevronRight } from 'react-icons/fa';
import { useAIAdvisor } from './AIAdvisorContext';
import './AIAdvisorPanel.css';

export default function AIAdvisorPanel({ pendingText, onClearPending }) {
  const { messages, loading, sendMessage, highlightedContext, setHighlightedContext } = useAIAdvisor();

  const [collapsed, setCollapsed]       = useState(false);
  const [input, setInput]               = useState('');
  const [attachedFile, setAttachedFile] = useState(null);
  const [fileContent, setFileContent]   = useState(null);

  const chatEndRef    = useRef(null);
  const textareaRef   = useRef(null);
  const fileInputRef  = useRef(null);

  /* ── Auto-scroll on new message ── */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  /* ── Auto-resize textarea ── */
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }, [input]);

  /* ── Consume pending text from highlight selection into Quoted Context ── */
  useEffect(() => {
    if (pendingText) {
      setHighlightedContext(pendingText); // Formats as a context quote box block
      setCollapsed(false);
      onClearPending?.();
      setTimeout(() => textareaRef.current?.focus(), 150);
    }
  }, [pendingText, onClearPending, setHighlightedContext]);

  /* ── File handling ── */
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // SECURITY FIX: Limit upload capacity safely
    const MAX_SIZE = 5 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      alert("File size exceeds 5MB limit.");
      e.target.value = '';
      return;
    }

    setAttachedFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => setFileContent(ev.target.result.split(',')[1]);
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  const removeFile = () => {
    setAttachedFile(null);
    setFileContent(null);
  };

  /* ── Send ── */
  const handleSend = async () => {
    const text = input.trim();
    if (!text && !attachedFile && !highlightedContext) return;

    const b64   = fileContent;
    const fname = attachedFile?.name;

    setInput('');
    setAttachedFile(null);
    setFileContent(null);

    await sendMessage({ text, fileData: b64, fileName: fname });
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = (input.trim() || attachedFile || highlightedContext) && !loading;

  return (
    <aside className={`ai-panel ${collapsed ? 'ai-panel--collapsed' : ''}`}>
      {/* ── Toggle tab ── */}
      <button
        className="ai-panel__toggle"
        onClick={() => setCollapsed(c => !c)}
        aria-label={collapsed ? 'Expand AI panel' : 'Collapse AI panel'}
        title={collapsed ? 'Open AI Advisor' : 'Close AI Advisor'}
      >
        {collapsed ? <FaChevronLeft size={12} /> : <FaChevronRight size={12} />}
        {collapsed && <span className="ai-panel__toggle-label">AI</span>}
      </button>

      {/* ── Panel body (hidden when collapsed) ── */}
      <div className="ai-panel__body">
        {/* Header */}
        <div className="ai-panel__header">
          <div className="ai-panel__header-left">
            <div className="ai-panel__avatar">
              <FaRobot size={14} />
            </div>
            <div>
              <div className="ai-panel__title">Penasihat Syariah AI</div>
              <div className="ai-panel__subtitle">Panduan Syariah Peribadi Anda</div>
            </div>
          </div>
          
        </div>

        {/* Chat window */}
        <div className="ai-panel__chat">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`ai-panel__row ${msg.role === 'user' ? 'ai-panel__row--user' : 'ai-panel__row--assistant'}`}
            >
              {msg.role === 'assistant' && (
                <div className="ai-panel__msg-avatar">
                  <FaRobot size={11} />
                </div>
              )}
              <div className={`ai-panel__bubble ${msg.role === 'user' ? 'ai-panel__bubble--user' : 'ai-panel__bubble--assistant'}`}>
                {msg.highlightedText && (
                  <div className="ai-panel__bubble-context-quote">
                    Context: "{msg.highlightedText}"
                  </div>
                )}
                
                {msg.fileName && (
                  <div className="ai-panel__file-tag">
                    <FaFileAlt size={10} />
                    <span>{msg.fileName}</span>
                  </div>
                )}
                <span className="ai-panel__bubble-text">{msg.content}</span>
              </div>
            </div>
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="ai-panel__row ai-panel__row--assistant">
              <div className="ai-panel__msg-avatar">
                <FaRobot size={11} />
              </div>
              <div className="ai-panel__bubble ai-panel__bubble--assistant ai-panel__bubble--typing">
                <span className="ai-panel__typing-dot" />
                <span className="ai-panel__typing-dot" />
                <span className="ai-panel__typing-dot" />
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Context quote preview bar */}
        {highlightedContext && (
          <div className="ai-panel__context-preview">
            <span className="ai-panel__context-label">Context</span>
            <span className="ai-panel__context-text">"{highlightedContext}"</span>
            <button className="ai-panel__context-remove" onClick={() => setHighlightedContext(null)} aria-label="Remove context">
              <FaTimes size={10} />
            </button>
          </div>
        )}

        {/* File preview */}
        {attachedFile && (
          <div className="ai-panel__file-preview">
            <FaFileAlt size={12} />
            <span className="ai-panel__file-preview-name">{attachedFile.name}</span>
            <button className="ai-panel__file-preview-remove" onClick={removeFile} aria-label="Remove file">
              <FaTimes size={10} />
            </button>
          </div>
        )}

        {/* Input bar */}
        <div className="ai-panel__input-bar">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".pdf,.png,.jpg,.jpeg,.webp"
            style={{ display: 'none' }}
          />
          <button
            className="ai-panel__btn ai-panel__btn--attach"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Attach file"
            title="Attach PDF or image"
          >
            <FaPaperclip size={13} />
          </button>
          <textarea
            ref={textareaRef}
            className="ai-panel__textarea"
            placeholder="Tanya tentang pelaburan patuh Syariah…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className={`ai-panel__btn ai-panel__btn--send ${canSend ? 'ai-panel__btn--send-active' : ''}`}
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send message"
          >
            <FaPaperPlane size={13} />
          </button>
        </div>

        <p className="ai-panel__hint">Enter to send · Shift+Enter for new line</p>
      </div>
    </aside>
  );
}