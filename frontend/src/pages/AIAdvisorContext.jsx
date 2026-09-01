import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { auth } from '../firebase'; 

const AIAdvisorContext = createContext(null);

const INITIAL_MESSAGES = [
  {
    role: 'assistant',
    content: "Hi, I'm your personal AI agent trader.",
  },
];

export function AIAdvisorProvider({ children }) {
  // 1. Initialize state directly from sessionStorage if it exists
  const [messages, setMessages] = useState(() => {
    const savedHistory = sessionStorage.getItem('chat_history');
    return savedHistory ? JSON.parse(savedHistory) : INITIAL_MESSAGES;
  });
  const [loading, setLoading]   = useState(false);
  const [highlightedContext, setHighlightedContext] = useState(null);
  const [pendingTrade, setPendingTrade] = useState(null);

  const [conversationId] = useState(() => {
    return new Date().toISOString().split('T')[0]; 
  });

  // 2. Sync history to sessionStorage whenever messages state updates
  useEffect(() => {
    sessionStorage.setItem('chat_history', JSON.stringify(messages));
  }, [messages]);

  // 3. Listen for auth state changes to wipe history ONLY on logout
  useEffect(() => {
    const unsubscribe = auth.onAuthStateChanged((user) => {
      if (!user) {
        sessionStorage.removeItem('chat_history'); 
        setMessages(INITIAL_MESSAGES); 
      }
    });

    return () => unsubscribe();
  }, []);

  const sendMessage = useCallback(async ({ text, fileData, fileName }) => {
    if (!text && !fileData && !highlightedContext) return;

    const userMsg = {
      role: 'user',
      content: text,
      fileName: fileName || null,
      highlightedText: highlightedContext || null, 
    };

    const textContextSnapshot = highlightedContext;
    setHighlightedContext(null);

    // Capture the updated state array safely to pass to the backend call
    const updatedHistory = [...messages, userMsg];
    setMessages(updatedHistory);

    _callBackend(
      conversationId,
      { text, fileData, fileName, highlightedText: textContextSnapshot, chatHistory: updatedHistory },
      setMessages,
      setLoading,
      setPendingTrade
    );
    
  }, [conversationId, highlightedContext, messages]);

  const clearMessages = useCallback(() => {
    sessionStorage.removeItem('chat_history');
    setMessages(INITIAL_MESSAGES);
    setHighlightedContext(null);
  }, []);

  const clearPendingTrade = useCallback(() => {
    setPendingTrade(null);
  }, []);

  // Called when the user clicks "Confirm" on a PENDING_CONFIRMATION trade
  // (only reachable in "Suggest actions, I confirm each one" mode). Sends
  // the exact selector from the /chat response — never a hand-edited copy
  // — to /confirm-trade, which re-checks the live book itself before
  // filling. Two outcomes come back:
  //   - NEEDS_RECONFIRMATION: price/terms moved since the preview. We
  //     merge the updated `current` details into pendingTrade so the card
  //     can show what changed; call confirmTrade again with force=true to
  //     proceed against the new terms.
  //   - anything else: the fill attempt result (still dry-run while
  //     FORCE_DRY_RUN is on server-side) replaces thetanuts_execution.
  const confirmTrade = useCallback(async (force = false) => {
    if (!pendingTrade?.confirm_selector) return;

    try {
      const user = auth.currentUser;
      if (!user) throw new Error('Not signed in.');
      const token = await user.getIdToken();

      const response = await fetch('http://localhost:5000/api/aiagent/ai/confirm-trade', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          selector: pendingTrade.confirm_selector,
          action: pendingTrade.action,
          force,
        }),
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Could not confirm trade.');
      }

      if (data.data.status === 'NEEDS_RECONFIRMATION') {
        setPendingTrade(prev => prev && ({
          ...prev,
          thetanuts_execution: {
            status: 'NEEDS_RECONFIRMATION',
            reason: data.data.reason,
            previous: data.data.previous || prev.confirm_selector,
            current: data.data.current,
          },
          confirm_selector: {
            ...prev.confirm_selector,
            strike: data.data.current.strike,
            expiry: data.data.current.expiry,
            previewed_price: data.data.current.price,
          },
        }));
      } else {
        setPendingTrade(prev => prev && ({
          ...prev,
          thetanuts_execution: data.data.execution,
        }));
      }
    } catch (error) {
      console.error('Confirm Trade Error:', error);
      setPendingTrade(prev => prev && ({
        ...prev,
        thetanuts_execution: { status: 'FAILED', error: error.message },
      }));
    }
  }, [pendingTrade]);

  return (
    <AIAdvisorContext.Provider value={{ 
      messages, 
      loading, 
      sendMessage, 
      clearMessages, 
      highlightedContext, 
      setHighlightedContext,
      pendingTrade,
      clearPendingTrade,
      confirmTrade
    }}>
      {children}
    </AIAdvisorContext.Provider>
  );
}

/** Internal helper — Server communication handler */
async function _callBackend(conversationId, { text, fileData, fileName, highlightedText, chatHistory }, setMessages, setLoading, setPendingTrade) {
  setLoading(true);
  try {
    const user = auth.currentUser;
    if (!user) throw new Error("Sila log masuk terlebih dahulu. (Please log in)");

    const token = await user.getIdToken();

    // Clean up history fields to only send what the AI agent relies on
    const cleanHistory = chatHistory.slice(0, -1).map(msg => ({
      role: msg.role,
      content: msg.highlightedText 
        ? `[Teks Rujukan: "${msg.highlightedText}"]\nSoalan: ${msg.content}` 
        : msg.content
    }));

    const formattedMessage = highlightedText
      ? `[Teks Rujukan: "${highlightedText}"]\nSoalan: ${text}`
      : text;

    const payload = {
      session_id: conversationId,
      message: formattedMessage,
      pageContext: window.location.pathname || "Aplikasi Zakat/Pelaburan",
      fileData: fileData,  
      fileName: fileName,
      chat_history: cleanHistory // 4. Passing browser-managed history here
    };

    const response = await fetch('http://localhost:5000/api/aiagent/ai/chat', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}` 
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.error || 'Server error');
    }

    if (data.success && data.data) {
      if (data.data.final_advice) {
        setMessages(prev => [...prev, { role: 'assistant', content: data.data.final_advice }]);
      }
      
      // Extract trade proposal when backend risk analysis outputs execution recommendation
      if (data.data.trade_proposal) {
        setPendingTrade(data.data.trade_proposal);
      }
    } else {
      throw new Error("Invalid response format from server.");
    }
    
  } catch (error) {
    console.error("AI Advisor Error:", error);
    setMessages(prev => [
      ...prev,
      { role: 'assistant', content: 'An error occurred. Please check your connection and try again.' },
    ]);
  } finally {
    setLoading(false);
  }
}

export const useAIAdvisor = () => useContext(AIAdvisorContext);