import { useState } from 'react'
import './App.css'
import { BrowserRouter, Routes, Route, Link, useLocation,useNavigate } from 'react-router-dom';
import Advisor from './pages/Advisor';
import Auth from './pages/Auth';
import Zakat from './pages/Zakat';
import Stocks from './pages/Stocks';
import Preferences from './pages/Preferences';


import { FaCalculator, FaThLarge, FaRobot, FaSignOutAlt, FaChartLine } from 'react-icons/fa';
import { signOut } from 'firebase/auth';
import { auth } from './firebase';

import { AIAdvisorProvider, useAIAdvisor }  from './pages/AIAdvisorContext';
import AIAdvisorPanel         from './pages/AIAdvisorPanel';
import TextHighlightAsk       from './pages/TextHighlightAsk';

/**
 * NavBar — collapses to icon-only when on /stocks,
 * because the stocks page has its own side panel.
 */

function NavBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const isStocks = location.pathname === '/stocks';
  const { clearMessages } = useAIAdvisor(); // Get the clear function

  const handleLogout = async (e) => {
    e.preventDefault(); // Stop standard link navigation
    try {
      await signOut(auth); // 1. Log out of Firebase
      clearMessages();     // 2. Clear AI chat history on both sides
      navigate('/');       // 3. Go back to auth page
    } catch (error) {
      console.error("Error logging out", error);
    }
  };
  
  return (
    <nav className={isStocks ? 'nav-icon-only' : ''}>
      <Link className="nav-zakat" to="/zakat" title="Zakat">
        <FaCalculator />
        {!isStocks && <span>Rancangan kewangan</span>}
      </Link>
      <Link className="nav-stocks" to="/stocks" title="Stocks">
        <FaChartLine />
        {!isStocks && <span>Saham</span>}
      </Link>
      <Link className="nav-advisor" to="/advisor" title="AI Advisor">
        <FaRobot />
        {!isStocks && <span>Penasihat AI</span>}
      </Link>
      <a href="#" className="nav-logout" onClick={handleLogout} title="Log out">
        <FaSignOutAlt />
        {!isStocks && <span>Log Keluar</span>}
      </a>
    </nav>
  );
}

function AppShell() {
  const location = useLocation();
  const { setHighlightedContext } = useAIAdvisor();
  
  const isStocks = location.pathname === '/stocks';
  // 1. Check if the user is on the Auth or Preferences page
  const isAuthOrPref = location.pathname === '/' || location.pathname === '/preferences';
  const showPanel = location.pathname === '/zakat' || location.pathname === '/stocks';

  /* Dynamically calculate layout boundaries */
  const mainStyle = {
    // 2. Remove the left margin completely if on Auth or Pref pages
    marginLeft: isAuthOrPref ? '0px' : (isStocks ? '60px' : '200px'), 
    marginRight: showPanel ? '320px' : '0px', 
  };

  return (
    <>
      {/* 3. Only render the NavBar if NOT on the Auth or Pref pages */}
      {!isAuthOrPref && <NavBar />}

      {/* Page content wrapper dynamically handles layout constraints */}
      <div className="app-container" style={mainStyle}>
        <Routes>
          <Route path="/stocks"  element={<Stocks />} />
          <Route path="/zakat"   element={<Zakat />} />
          <Route path="/preferences" element={<Preferences />} /> 
          <Route path="/advisor" element={<Advisor />} />
          <Route path="/"        element={<Auth />} />
        </Routes>
      </div>

      {/* AI side panel */}
      {showPanel && (
        <>
          <AIAdvisorPanel />
          <TextHighlightAsk onAskAI={setHighlightedContext} />
        </>
      )}
    </>
  );
}

function App() {
  return (
    <AIAdvisorProvider>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </AIAdvisorProvider>
  );
}

export default App;