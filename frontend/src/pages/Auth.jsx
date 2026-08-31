import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  fetchSignInMethodsForEmail,
  linkWithCredential,
  EmailAuthProvider,
} from 'firebase/auth';
import { doc, getDoc, setDoc, serverTimestamp } from 'firebase/firestore';
import { auth, db } from '../firebase';
import './Auth.css';
import '../shared.css';
import { FiMail, FiLock, FiEye, FiEyeOff } from 'react-icons/fi';

const googleProvider = new GoogleAuthProvider();

export default function Auth() {
  const navigate = useNavigate();

  // 'signin' | 'signup'
  const [mode, setMode] = useState('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState('');

  /* ─── Helpers ─────────────────────────────────────────── */

  /**
   * Check Firestore whether a user has completed the preference survey.
   * Returns true  → go to /dashboard
   * Returns false → go to /preferences
   */
  async function redirectAfterAuth(uid) {
    const snap = await getDoc(doc(db, 'users', uid));
    if (snap.exists() && snap.data().preferencesCompleted) {
      navigate('/dashboard');
    } else {
      navigate('/preferences');
    }
  }

  function friendlyError(code) {
    const map = {
      'auth/email-already-in-use':   'This email has been registered, try to login.',
      'auth/invalid-email':           'Wrong email format.',
      'auth/weak-password':           'Password need at least 6 characters.',
      'auth/user-not-found':          'Account not found, please register your account',
      'auth/wrong-password':          'Wrong password',
      'auth/invalid-credential':      'Wrong email or password',
      'auth/popup-closed-by-user':    'Google login cancelled',
      'auth/account-exists-with-different-credential':
        'This account login using different method',
    };
    return map[code] || 'An error occur, please try again';
  }

  /* ─── Sign Up (email + password) ──────────────────────── */
  async function handleSignUp(e) {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 6) {
      setError('Password need at least 6 character');
      return;
    }

    setLoading(true);
    try {
      const cred = await createUserWithEmailAndPassword(auth, email, password);

      // Create user document in Firestore (preferencesCompleted = false)
      await setDoc(doc(db, 'users', cred.user.uid), {
        email:                  cred.user.email,
        createdAt:              serverTimestamp(),
        preferencesCompleted:   false,
      });

      navigate('/preferences');
    }  catch (err) {
      // 1. Print the full error to the console
      console.error("🔥 FIREBASE ERROR:", err); 
      
      // 2. Force the UI to show the actual English error message from Firebase
      setError(`${friendlyError(err.code)} (Details: ${err.message})`);
    } finally {
      setLoading(false);
    }
  }

  /* ─── Sign In (email + password) ──────────────────────── */
  async function handleSignIn(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const cred = await signInWithEmailAndPassword(auth, email, password);
      await redirectAfterAuth(cred.user.uid);
    } catch (err) {
      setError(friendlyError(err.code));
    } finally {
      setLoading(false);
    }
  }

  /* ─── Google Sign-In / Sign-Up ────────────────────────── */
  async function handleGoogle() {
    setError('');
    setGoogleLoading(true);
    try {
      const result = await signInWithPopup(auth, googleProvider);
      const user   = result.user;
      const isNew  = result._tokenResponse?.isNewUser ?? false;

      if (isNew) {
        // Brand-new Google account — create user doc
        await setDoc(doc(db, 'users', user.uid), {
          email:                user.email,
          displayName:          user.displayName || '',
          createdAt:            serverTimestamp(),
          preferencesCompleted: false,
        });
        navigate('/preferences');
      } else {
        await redirectAfterAuth(user.uid);
      }
    } catch (err) {
      setError(friendlyError(err.code));
    } finally {
      setGoogleLoading(false);
    }
  }

  /* ─── Render ───────────────────────────────────────────── */
  const isSignUp = mode === 'signup';

  return (
    <div className="auth-page">
      <div className="auth-card">

        {/* Branding */}
        <div className="auth-brand">
          <h1 className="auth-brand-title">Finova</h1>
          <p className="auth-brand-subtitle">
            {isSignUp ? 'Please sign up a account' : 'Welcome back !'}
          </p>
        </div>

        {/* Tab switcher */}
        <div className="auth-tabs">
          <button
            className={`auth-tab ${!isSignUp ? 'active' : ''}`}
            onClick={() => { setMode('signin'); setError(''); }}
          >
            Login
          </button>
          <button
            className={`auth-tab ${isSignUp ? 'active' : ''}`}
            onClick={() => { setMode('signup'); setError(''); }}
          >
            Register
          </button>
        </div>

        {/* Error banner */}
        {error && (
          <div className="auth-error">
            <span>⚠️</span> {error}
          </div>
        )}

        {/* Form */}
        <form
          className="auth-form"
          onSubmit={isSignUp ? handleSignUp : handleSignIn}
        >
          {/* Email */}
          <div className="auth-field">
            <label className="auth-label">Email</label>
            <div className="auth-input-wrap">
              <span className="auth-input-icon"><FiMail /></span>
              <input
                className="auth-input"
                type="email"
                placeholder="name@email.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
          </div>

          {/* Password */}
          <div className="auth-field">
            <label className="auth-label">Password</label>
            <div className="auth-input-wrap">
              <span className="auth-input-icon"><FiLock /></span>
              <input
                className="auth-input"
                type={showPassword ? 'text' : 'password'}
                placeholder={isSignUp ? 'At Least 6 characters' : 'Your Password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                autoComplete={isSignUp ? 'new-password' : 'current-password'}
              />
              <button
                type="button"
                className="auth-input-icon"
                style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                onClick={() => setShowPassword(v => !v)}
                tabIndex={-1}
              >
                {showPassword ? <FiEyeOff /> : <FiEye />}
              </button>
            </div>
          </div>

          {/* Confirm Password (sign up only) */}
          {isSignUp && (
            <div className="auth-field">
              <label className="auth-label">Confirm Password</label>
              <div className="auth-input-wrap">
                <span className="auth-input-icon"><FiLock /></span>
                <input
                  className="auth-input"
                  type={showConfirm ? 'text' : 'password'}
                  placeholder="Taip semula kata laluan"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  className="auth-input-icon"
                  style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                  onClick={() => setShowConfirm(v => !v)}
                  tabIndex={-1}
                >
                  {showConfirm ? <FiEyeOff /> : <FiEye />}
                </button>
              </div>
            </div>
          )}

          {/* Submit */}
          <button className="auth-btn-primary" type="submit" disabled={loading}>
            {loading
              ? <span className="auth-spinner" />
              : isSignUp ? 'Register' : 'Login'
            }
          </button>
        </form>

        {/* Divider */}
        <div className="auth-divider">or continue with</div>

        {/* Google */}
        <button
          className="auth-btn-google"
          type="button"
          onClick={handleGoogle}
          disabled={googleLoading}
        >
          {googleLoading ? (
            <span className="auth-spinner dark" />
          ) : (
            <svg className="google-icon" viewBox="0 0 48 48">
              <path fill="#EA4335" d="M24 9.5c3.1 0 5.8 1.1 8 2.9l6-6C34.4 3.1 29.5 1 24 1 14.8 1 7 6.6 3.7 14.4l7 5.4C12.4 13.3 17.7 9.5 24 9.5z"/>
              <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.7c-.6 3-2.3 5.5-4.8 7.2l7.4 5.7c4.3-4 6.8-9.9 6.8-16.9z"/>
              <path fill="#FBBC05" d="M10.7 28.2A14.5 14.5 0 0 1 9.5 24c0-1.5.3-2.9.7-4.2l-7-5.4A23.9 23.9 0 0 0 0 24c0 3.9.9 7.6 2.6 10.9l8.1-6.7z"/>
              <path fill="#34A853" d="M24 47c5.4 0 10-1.8 13.3-4.8l-7.4-5.7c-1.8 1.2-4.1 1.9-5.9 1.9-6.3 0-11.6-3.8-13.3-9.3l-8.1 6.7C7 41.4 14.8 47 24 47z"/>
            </svg>
          )}
          {!googleLoading && 'Google'}
        </button>

      </div>
    </div>
  );
}