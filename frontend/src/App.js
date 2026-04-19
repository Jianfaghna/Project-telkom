import { useEffect } from 'react';

function App() {
  useEffect(() => {
    // FilterIN is served by the Flask backend at /api/*.
    // The React shell merely redirects the root URL into the Flask app.
    const dest = window.location.pathname.startsWith('/api')
      ? window.location.href
      : '/api/';
    window.location.replace(dest);
  }, []);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #eaf3ff 0%, #ffffff 100%)',
        fontFamily: 'system-ui, sans-serif',
        color: '#0b3d91',
      }}
      data-testid="filterin-redirect-loader"
    >
      <div style={{ fontSize: 32, fontWeight: 700, letterSpacing: 1 }}>
        Filter<span style={{ color: '#ff2d2d' }}>IN</span>
      </div>
      <div style={{ marginTop: 12, color: '#4a5b7a' }}>Memuat aplikasi…</div>
      <div
        style={{
          marginTop: 24,
          width: 42,
          height: 42,
          border: '4px solid rgba(11,61,145,0.15)',
          borderTopColor: '#0b3d91',
          borderRadius: '50%',
          animation: 'flin-spin 0.8s linear infinite',
        }}
      />
      <style>{`@keyframes flin-spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

export default App;
