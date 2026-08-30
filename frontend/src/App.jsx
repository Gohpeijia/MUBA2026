import { useState } from 'react'
import './App.css'
import { BrowserRouter, Routes, Route, Link, useLocation,useNavigate } from 'react-router-dom';
import Advisor from './pages/Advisor';
import Auth from './pages/Auth';
import Stocks from './pages/Stocks';
import Preferences from './pages/Preferences';
import InvestmentDashboard from './pages/InvestmentDashboard';


import { FaThLarge, FaRobot, FaSignOutAlt, FaChartLine, FaWallet } from 'react-icons/fa';
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
      <Link className="nav-dashboard" to="/dashboard" title="Dashboard">
        <FaWallet />
        {!isStocks && <span>Dashboard</span>}
      </Link>
      <Link className="nav-stocks" to="/stocks" title="Stocks">
        <FaChartLine />
        {!isStocks && <span>Positions</span>}
      </Link>
      <Link className="nav-advisor" to="/advisor" title="AI Advisor">
        <FaRobot />
        {!isStocks && <span>AI Advisor</span>}
      </Link>
      <a href="#" className="nav-logout" onClick={handleLogout} title="Log out">
        <FaSignOutAlt />
        {!isStocks && <span>Log Out</span>}
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
  const showPanel = location.pathname === '/stocks' || location.pathname === '/dashboard';

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
          <Route path="/dashboard"    element={<InvestmentDashboard />} />
          <Route path="/stocks"       element={<Stocks />} />
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