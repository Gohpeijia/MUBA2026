import React, { useRef, useEffect, useState } from 'react';
import '../shared.css';
import './Advisor.css';
import { FaPaperPlane, FaPaperclip, FaTimes, FaFileAlt, FaRobot } from 'react-icons/fa';
import { useAIAdvisor } from './AIAdvisorContext';

export default function Advisor() {
  const { messages, loading, sendMessage, highlightedContext, setHighlightedContext } = useAIAdvisor();

  const [input, setInput]               = useState('');
  const [attachedFile, setAttachedFile] = useState(null);
  const [fileContent, setFileContent]   = useState(null);

  const fileInputRef = useRef(null);
  const chatEndRef   = useRef(null);
  const textareaRef  = useRef(null);

  /* ── Auto-scroll ── */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  /* ── Auto-resize textarea ── */
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }, [input]);

  /* ── Robust File handling ── */
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // SECURITY FIX: Prevent browser memory exhaustion and server crashes
    const MAX_SIZE = 5 * 1024 * 1024; // 5 Megabytes limit
    if (file.size > MAX_SIZE) {
      alert("File size exceeds 5MB limit. Please upload a smaller document.");
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
    <div className="advisor-page">
      {/* Header */}
      <div className="advisor-header">
        <div>
          <h1 className="advisor-main-title">Penasihat Syariah AI</h1>
          <p className="advisor-subtitle">Panduan Syariah Peribadi Anda</p>
        </div>
      </div>

      {/* Chat Window */}
      <div className="chat-window">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`message-row ${msg.role === 'user' ? 'message-row--user' : 'message-row--assistant'}`}
          >
            {msg.role === 'assistant' && (
              <div className="avatar avatar--assistant">
                <FaRobot size={16} />
              </div>
            )}

            <div className={`bubble ${msg.role === 'user' ? 'bubble--user' : 'bubble--assistant'}`}>
              {/* ChatGPT-style context text block placement inside the conversation log */}
              {msg.highlightedText && (
                <div className="bubble-context-quote">
                  Context: "{msg.highlightedText}"
                </div>
              )}
              
              {msg.fileName && (
                <div className="bubble-file-tag">
                  <FaFileAlt size={12} />
                  <span>{msg.fileName}</span>
                </div>
              )}
              <span className="bubble-text">{msg.content}</span>
            </div>
          </div>
        ))}

        {loading && (
          <div className="message-row message-row--assistant">
            <div className="avatar avatar--assistant">
              <FaRobot size={16} />
            </div>
            <div className="bubble bubble--assistant bubble--typing">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Context quote preview bar */}
      {highlightedContext && (
        <div className="context-preview-bar">
          <span className="context-preview-label">Context</span>
          <span className="context-preview-text">"{highlightedContext}"</span>
          <button className="context-preview-remove" onClick={() => setHighlightedContext(null)} aria-label="Remove context">
            <FaTimes size={12} />
          </button>
        </div>
      )}

      {/* Attached File Preview */}
      {attachedFile && (
        <div className="file-preview-bar">
          <FaFileAlt size={14} />
          <span className="file-preview-name">{attachedFile.name}</span>
          <button className="file-preview-remove" onClick={removeFile} aria-label="Remove file">
            <FaTimes size={12} />
          </button>
        </div>
      )}

      {/* Input Bar */}
      <div className="input-bar">
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          style={{ display: 'none' }}
        />

        <button
          className="input-btn input-btn--attach"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach file"
          title="Attach PDF or image"
        >
          <FaPaperclip size={16} />
        </button>

        <textarea
          ref={textareaRef}
          className="input-textarea"
          placeholder="Tanya tentang pelaburan patuh Syariah, zakat, dan kepatuhan Syariah…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />

        <button
          className={`input-btn input-btn--send ${canSend ? 'input-btn--send-active' : ''}`}
          onClick={handleSend}
          disabled={!canSend}
          aria-label="Send message"
        >
          <FaPaperPlane size={15} />
        </button>
      </div>

      <p className="input-hint">Press Enter to send · Shift+Enter for new line · PDF &amp; image uploads supported</p>
    </div>
  );
}