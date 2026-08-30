import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { auth } from '../firebase'; 

const AIAdvisorContext = createContext(null);

const INITIAL_MESSAGES = [
  {
    role: 'assistant',
    content: 'Assalamualaikum. Saya AI Penasihat Shariah anda.',
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
      setLoading
    );
    
  }, [conversationId, highlightedContext, messages]);

  const clearMessages = useCallback(() => {
    sessionStorage.removeItem('chat_history');
    setMessages(INITIAL_MESSAGES);
    setHighlightedContext(null);
  }, []);

  return (
    <AIAdvisorContext.Provider value={{ 
      messages, 
      loading, 
      sendMessage, 
      clearMessages, 
      highlightedContext, 
      setHighlightedContext 
    }}>
      {children}
    </AIAdvisorContext.Provider>
  );
}

/** Internal helper — Server communication handler */
async function _callBackend(conversationId, { text, fileData, fileName, highlightedText, chatHistory }, setMessages, setLoading) {
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

    if (data.success && data.data && data.data.final_advice) {
      setMessages(prev => [...prev, { role: 'assistant', content: data.data.final_advice }]);
    } else {
      throw new Error("Invalid response format from server.");
    }
    
  } catch (error) {
    console.error("AI Advisor Error:", error);
    setMessages(prev => [
      ...prev,
      { role: 'assistant', content: 'Ralat berlaku. Sila semak sambungan anda dan cuba lagi.' },
    ]);
  } finally {
    setLoading(false);
  }
}

export const useAIAdvisor = () => useContext(AIAdvisorContext);