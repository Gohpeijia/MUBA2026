import { useState, useEffect } from 'react'
import './App.css'
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate, Navigate } from 'react-router-dom';
import Advisor from './pages/Advisor';
import Auth from './pages/Auth';
import Stocks from './pages/Stocks';
import Preferences from './pages/Preferences';
import InvestmentDashboard from './pages/InvestmentDashboard';
import OpportunityConfirmation from './pages/OpportunityConfirmation';
import HedgingSettings from './pages/HedgingSettings';

import { FaThLarge, FaRobot, FaSignOutAlt, FaChartLine, FaWallet, FaCog } from 'react-icons/fa';
import { signOut, onAuthStateChanged } from 'firebase/auth';
import { auth } from './firebase';

import { AIAdvisorProvider, useAIAdvisor }  from './pages/AIAdvisorContext';
import AIAdvisorPanel         from './pages/AIAdvisorPanel';
import TextHighlightAsk       from './pages/TextHighlightAsk';
import WalletBalance          from './pages/WalletBalance';

/**
 * NavBar — collapses to icon-only when on /stocks,
 * because the stocks page has its own side panel.
 */

/**
 * useAuthState — tracks the current Firebase user and whether that
 * state has finished resolving yet. onAuthStateChanged fires
 * asynchronously, so anything that renders before it fires the first
 * time can briefly see the "logged out" state even for an already
 * logged-in user — which is what was causing the blank dashboard
 * right after login/preferences.
 */
function useAuthState() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (u) => {
      setUser(u);
      setAuthLoading(false);
    });
    return () => unsubscribe();
  }, []);

  return { user, authLoading };
}

/**
 * RequireAuth — wraps pages that need a signed-in user. Waits for
 * auth state to resolve (spinner) before deciding whether to render
 * the page or bounce back to the login screen, so protected routes
 * never render blank or flash briefly before redirecting.
 */
function RequireAuth({ user, authLoading, children }) {
  const location = useLocation();

  if (authLoading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        minHeight: '60vh', color: 'var(--text-muted, #666)',
      }}>
        Loading…
      </div>
    );
  }
  if (!user) {
    window.localStorage.setItem('postLoginRedirect', `${location.pathname}${location.search}`);
    return <Navigate to="/" replace />;
  }
  return children;
}


function LoginRedirect() {
  const redirectTo = window.localStorage.getItem('postLoginRedirect') || '/dashboard';
  window.localStorage.removeItem('postLoginRedirect');
  return <Navigate to={redirectTo} replace />;
}

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
      <Link className="nav-settings" to="/settings" title="Settings">
        <FaCog />
        {!isStocks && <span>Settings</span>}
      </Link>

      {/* Live, on-chain spendable capital — the exact number the AI
          agent sizes trades against. Compact pill so it fits both the
          full and icon-only nav states. */}
      <WalletBalance variant="pill" />

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
  const { user, authLoading } = useAuthState();
  
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
          <Route path="/dashboard" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <InvestmentDashboard />
            </RequireAuth>
          } />
          <Route path="/stocks" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <Stocks />
            </RequireAuth>
          } />
          <Route path="/preferences" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <Preferences />
            </RequireAuth>
          } />
          <Route path="/advisor" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <Advisor />
            </RequireAuth>
          } />
          <Route path="/settings" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <HedgingSettings />
            </RequireAuth>
          } />
          {/* Already logged in and hitting the login page (e.g. a refresh)?
              Send them straight to the dashboard instead of showing Auth. */}
          <Route path="/opportunities/confirm/:confirmationId" element={
            <RequireAuth user={user} authLoading={authLoading}>
              <OpportunityConfirmation />
            </RequireAuth>
          } />
          <Route path="/" element={
            authLoading
              ? null
              : (user ? <LoginRedirect /> : <Auth />)
          } />
          {/* Catch-all: any unknown/stale path (like a leftover /risk-copilot
              or /zakat reference) lands somewhere real instead of a blank
              "No routes matched" screen. */}
          <Route path="*" element={<Navigate to={user ? '/dashboard' : '/'} replace />} />
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
