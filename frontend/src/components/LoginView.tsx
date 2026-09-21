import React, { useState } from 'react';
import { supa, API_URL } from '../lib/data';

interface LoginViewProps {
  onLogin: (email: string) => void;
  onBack: () => void;
}

export default function LoginView({ onLogin, onBack }: LoginViewProps) {
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [orgName, setOrgName] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supa) {
      setErrorMsg("Supabase client not initialized.");
      return;
    }
    setLoading(true);
    setErrorMsg('');

    try {
      if (isSignUp) {
        // 1. Sign Up User
        const { data: authData, error: authErr } = await supa.auth.signUp({ email, password });
        if (authErr) throw authErr;
        if (!authData.user) throw new Error("Sign up failed, no user returned.");

        // The org/user endpoints are authenticated server-side, so we must send
        // the new session's access token. If email confirmation is enabled there
        // is no session yet — surface that clearly instead of failing opaquely.
        const token = authData.session?.access_token
          ?? (await supa.auth.getSession()).data.session?.access_token;
        if (!token) {
          throw new Error("Please confirm your email, then sign in to finish setting up your organization.");
        }
        const authHeaders = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };

        // 2. Create Organization
        const orgRes = await fetch(`${API_URL}/organizations`, {
          method: 'POST',
          headers: authHeaders,
          body: JSON.stringify({ name: orgName || 'My Organization' })
        });
        if (!orgRes.ok) throw new Error("Failed to create organization.");
        const orgData = await orgRes.json();

        // 3. Create User Profile linking to Organization (first user becomes admin)
        const profileRes = await fetch(`${API_URL}/users`, {
          method: 'POST',
          headers: authHeaders,
          body: JSON.stringify({ id: authData.user.id, org_id: orgData.id })
        });
        if (!profileRes.ok) throw new Error("Failed to create user profile.");

        onLogin(email);
      } else {
        // Sign In
        const { error } = await supa.auth.signInWithPassword({ email, password });
        if (error) throw error;
        onLogin(email);
      }
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || "Authentication failed. Please check credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-bg"></div>

      <button className="back-button" onClick={onBack}>
        ← Back
      </button>

      <div className="login-card glass">
        <div className="login-header">
          <div className="brand">
            <span className="logo">💧</span> Hydris <b>AI</b>
          </div>
          <h2>{isSignUp ? 'Create a new account' : 'Sign in to your account'}</h2>
          <p>{isSignUp ? 'Join Hydris AI.' : 'Welcome back to Hydris AI.'}</p>
        </div>

        {errorMsg && <div style={{ color: '#ef4444', textAlign: 'center', fontSize: '0.9rem' }}>{errorMsg}</div>}

        <form onSubmit={handleSubmit} className="login-form">
          <div className="input-group">
            <span className="icon">👤</span>
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="input-group">
            <span className="icon">🔒</span>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          {isSignUp && (
            <div className="input-group">
              <span className="icon">🏢</span>
              <input
                type="text"
                placeholder="Organization Name"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                required
              />
            </div>
          )}

          {!isSignUp && (
            <div className="login-actions">
              <a href="#" className="forgot-link">Forgot Password?</a>
            </div>
          )}

          <button type="submit" className="primary full-width" disabled={loading}>
            {loading
              ? (isSignUp ? 'Creating Account...' : 'Authenticating...')
              : (isSignUp ? 'Sign Up' : 'Log In')}
          </button>
        </form>

        <div className="login-footer">
          {isSignUp ? (
            <a href="#" onClick={(e) => { e.preventDefault(); setIsSignUp(false); setErrorMsg(''); }}>
              Already have an account? Sign In
            </a>
          ) : (
            <a href="#" onClick={(e) => { e.preventDefault(); setIsSignUp(true); setErrorMsg(''); }}>
              Create an Account
            </a>
          )}
          <a href="#" style={{ display: 'block', marginTop: 10, color: 'var(--muted, #94a3b8)', fontSize: '0.85rem' }}
            onClick={(e) => { e.preventDefault(); onLogin('guest'); }}>
            Continue as guest — explore the demo portfolio
          </a>
        </div>
      </div>
    </div>
  );
}
