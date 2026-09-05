import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { auth } from '../firebase'; 

const AIAdvisorContext = createContext(null);

const INITIAL_MESSAGES = [
  {
    role: 'assistant',
    content: "Hi, I'm your personal AI agent trader.",
  },
];
function normalizeTradeProposal(proposal) {
  if (!proposal) return null;

  const symbol =
    proposal.symbol ||
    proposal.ticker ||
    proposal.confirm_selector?.underlying ||
    proposal.selector?.underlying;

  const action = (
    proposal.action ||
    proposal.decision ||
    proposal.confirm_selector?.decision ||
    proposal.selector?.decision ||
    ''
  ).toUpperCase();

  const isPaperEquity =
    proposal.execution_target === 'PAPER_EQUITY' ||
    proposal.asset_type === 'EQUITY';

  // -----------------------------------------------------------
  // PAPER EQUITY
  // -----------------------------------------------------------
  // Paper equity does NOT need a Thetanuts option selector.
  // Keep the proposal as-is and normalize the quantity fields.
  // -----------------------------------------------------------
  if (isPaperEquity) {
    return {
      ...proposal,

      execution_target: 'PAPER_EQUITY',

      symbol,
      ticker: proposal.ticker || symbol,

      action,
      decision: proposal.decision || action,

      shares:
        proposal.shares ??
        proposal.quantity ??
        proposal.qty,

      quantity:
        proposal.quantity ??
        proposal.shares ??
        proposal.qty,
    };
  }

  // -----------------------------------------------------------
  // EXISTING THETANUTS SELECTOR HANDLING
  // -----------------------------------------------------------
  const selector =
    proposal.confirm_selector ||
    proposal.selector ||
    {};

  const confirmSelector = {
    ...selector,
    underlying: selector.underlying || symbol,
    decision: selector.decision || action,
  };

  return {
    ...proposal,

    symbol,
    ticker: proposal.ticker || symbol,

    action,
    decision: proposal.decision || action,

    selector:
      proposal.selector ||
      confirmSelector,

    confirm_selector:
      confirmSelector,
  };
}

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
  if (!pendingTrade) return;

  try {
    const user = auth.currentUser;
    if (!user) throw new Error('Not signed in.');

    const token = await user.getIdToken();

    const isPaperEquity =
      pendingTrade.execution_target === 'PAPER_EQUITY' ||
      pendingTrade.asset_type === 'EQUITY';

    let requestBody;

    if (isPaperEquity) {
      // ---------------------------------------------------------
      // PAPER EQUITY
      // Do NOT send a Thetanuts option selector.
      // Equity trades only need symbol + action + quantity.
      // ---------------------------------------------------------
      requestBody = {
        action: pendingTrade.action || pendingTrade.decision,
        decision: pendingTrade.decision || pendingTrade.action,

        execution_target: 'PAPER_EQUITY',

        symbol: pendingTrade.symbol || pendingTrade.ticker,
        ticker: pendingTrade.ticker || pendingTrade.symbol,

        shares:
          pendingTrade.shares ??
          pendingTrade.quantity ??
          pendingTrade.qty,

        quantity:
          pendingTrade.quantity ??
          pendingTrade.shares ??
          pendingTrade.qty,

        price: pendingTrade.price,

        force,
      };
    } else {
      // ---------------------------------------------------------
      // THETANUTS OPTION
      // Keep the existing selector-based confirmation flow.
      // BUY is untouched.
      // Crypto SELL remains Thetanuts.
      // ---------------------------------------------------------
      if (!pendingTrade.confirm_selector) {
        throw new Error('Incomplete trade selector — nothing to confirm.');
      }

      requestBody = {
        selector: pendingTrade.confirm_selector,
        action: pendingTrade.action,
        force,
      };
    }

    console.log(
      'Confirm trade request:',
      JSON.stringify(requestBody, null, 2)
    );

    const response = await fetch(
      'http://localhost:5000/api/aiagent/ai/confirm-trade',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify(requestBody),
      }
    );

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || 'Could not confirm trade.');
    }

    // -----------------------------------------------------------
    // PRICE / TERMS CHANGED
    // Only relevant to Thetanuts option trades.
    // -----------------------------------------------------------
    if (
  !isPaperEquity &&
  data.data.status === 'NEEDS_RECONFIRMATION'
) {
      setPendingTrade(prev => {
        if (!prev) return null;

        return {
          ...prev,

          thetanuts_execution: {
            status: 'NEEDS_RECONFIRMATION',
            reason: data.data.reason,
            previous:
              data.data.previous ||
              prev.confirm_selector,
            current: data.data.current,
          },

          confirm_selector: {
            ...prev.confirm_selector,
            strike: data.data.current.strike,
            expiry: data.data.current.expiry,
            previewed_price:
              data.data.current.previewed_price ??
              data.data.current.price,
          },
        };
      });

      return;
    }

    // -----------------------------------------------------------
    // EXECUTION RESULT
    // -----------------------------------------------------------
    setPendingTrade(prev => {
      if (!prev) return null;

      const execution = data.data.execution;

      return {
        ...prev,

        thetanuts_execution: execution || {
          status: data.data.status,
          reason: data.data.reason,
        },

        // Keep the final backend status available to the card.
        execution_status:
          execution?.status ||
          data.data.status,
      };
    });

    const finalStatus =
      data.data.execution?.status ||
      data.data.status;

    if (
      [
        'EXECUTED',
        'DRY_RUN_OK',
        'PAPER_EXECUTED',
      ].includes(finalStatus)
    ) {
      window.dispatchEvent(
        new CustomEvent('wallet:refresh')
      );
    }

  } catch (error) {
    console.error('Confirm Trade Error:', error);

    setPendingTrade(prev => {
      if (!prev) return null;

      return {
        ...prev,
        thetanuts_execution: {
          status: 'FAILED',
          error: error.message,
        },
        execution_status: 'FAILED',
      };
    });
  }
}, [pendingTrade]);

/** Internal helper — Server communication handler */
async function _callBackend(conversationId, { text, fileData, fileName, highlightedText, chatHistory }, setMessages, setLoading, setPendingTrade) {
  setLoading(true);
  try {
    const user = auth.currentUser;
    if (!user) throw new Error("Please log in first.");

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
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: data.data.final_advice,
          investmentAnalysis: data.data.investment_analysis || null,
          tradeStatus: data.data.trade_status || null,
          tradeReason: data.data.trade_reason || null,
          tradeProposal: data.data.trade_proposal || null,
        }]);
}
      
      // Extract trade proposal when backend risk analysis outputs execution recommendation
      // Only create an actionable trade popup when the backend explicitly
    // says the proposal is EXECUTABLE and a proposal exists.
    const isExecutable =
      data.data.trade_status === 'EXECUTABLE' &&
      !!data.data.trade_proposal;
        
    if (isExecutable) {
      setPendingTrade(normalizeTradeProposal(data.data.trade_proposal));
    } else {
      // Explicitly clear any stale pending trade when the new AI result
      // is not executable.
      setPendingTrade(null);
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
return (
  <AIAdvisorContext.Provider
    value={{
      messages,
      loading,
      highlightedContext,
      setHighlightedContext,

      pendingTrade,

      sendMessage,
      clearMessages,
      clearPendingTrade,
      confirmTrade,
    }}
  >
    {children}
  </AIAdvisorContext.Provider>
);
}

export const useAIAdvisor = () => useContext(AIAdvisorContext);

