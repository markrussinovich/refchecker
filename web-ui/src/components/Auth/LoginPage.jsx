import { useState } from 'react'
import { useAuthStore } from '../../stores/useAuthStore'

/**
 * Login page shown when the user is not authenticated.
 * Renders sign-in buttons only for providers returned by the server.
 */
export default function LoginPage() {
  const { providers, loginWithGoogle, loginWithGithub, loginWithMicrosoft, error } = useAuthStore()
  const [isRedirecting, setIsRedirecting] = useState(false)
  const [redirectTarget, setRedirectTarget] = useState(null)

  const handleGoogle = () => {
    setIsRedirecting(true)
    setRedirectTarget('google')
    loginWithGoogle()
  }

  const handleGithub = () => {
    setIsRedirecting(true)
    setRedirectTarget('github')
    loginWithGithub()
  }

  const handleMicrosoft = () => {
    setIsRedirecting(true)
    setRedirectTarget('microsoft')
    loginWithMicrosoft()
  }

  return (
    <div
      className="flex flex-col items-center justify-center min-h-screen"
      style={{ backgroundColor: 'var(--color-bg-primary)' }}
    >
      {/* Card */}
      <div
        className="w-full max-w-sm rounded-2xl shadow-xl p-8 flex flex-col items-center gap-6"
        style={{
          backgroundColor: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Logo + title */}
        <div className="flex flex-col items-center gap-3">
          <svg className="w-14 h-14" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" rx="15" fill="#3b82f6" />
            <path d="M25 30h50M25 50h40M25 70h30" stroke="white" strokeWidth="8" strokeLinecap="round" />
            <circle cx="75" cy="70" r="12" fill="#10b981" />
            <path
              d="M70 70l4 4 8-8"
              stroke="white"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
          <h1
            className="text-2xl font-bold"
            style={{ color: 'var(--color-text-primary)' }}
          >
            RefChecker
          </h1>
          <p
            className="text-sm text-center"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            Sign in to check paper references
          </p>
        </div>

        {/* Error banner */}
        {error && (
          <div
            className="w-full rounded-lg px-4 py-3 text-sm"
            style={{
              backgroundColor: 'var(--color-error-bg, #fef2f2)',
              color: 'var(--color-error, #dc2626)',
              border: '1px solid var(--color-error-border, #fecaca)',
            }}
          >
            {error}
          </div>
        )}

        {/* Sign-in buttons */}
        <div className="w-full flex flex-col gap-3">
          {providers.length === 0 ? (
            <p className="text-sm text-center" style={{ color: 'var(--color-text-secondary)' }}>
              No OAuth providers are configured. Contact your administrator.
            </p>
          ) : (
            <>
              {providers.includes('google') && (
                <SignInButton
                  onClick={handleGoogle}
                  loading={isRedirecting && redirectTarget === 'google'}
                  disabled={isRedirecting}
                  label="Continue with Google"
                  icon={<GoogleIcon />}
                />
              )}
              {providers.includes('github') && (
                <SignInButton
                  onClick={handleGithub}
                  loading={isRedirecting && redirectTarget === 'github'}
                  disabled={isRedirecting}
                  label="Continue with GitHub"
                  icon={<GitHubIcon />}
                />
              )}
              {providers.includes('microsoft') && (
                <SignInButton
                  onClick={handleMicrosoft}
                  loading={isRedirecting && redirectTarget === 'microsoft'}
                  disabled={isRedirecting}
                  label="Continue with Microsoft"
                  icon={<MicrosoftIcon />}
                />
              )}
            </>
          )}
        </div>

        <p
          className="text-xs text-center"
          style={{ color: 'var(--color-text-tertiary, #9ca3af)' }}
        >
          By signing in you agree to use this service for research purposes.
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SignInButton({ onClick, loading, disabled, label, icon }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-lg font-medium text-sm transition-colors duration-150 disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
      style={{
        backgroundColor: 'var(--color-bg-primary)',
        color: 'var(--color-text-primary)',
        border: '1px solid var(--color-border)',
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          e.currentTarget.style.backgroundColor = 'var(--color-bg-hover)'
          e.currentTarget.style.borderColor = 'var(--color-accent)'
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--color-bg-primary)'
        e.currentTarget.style.borderColor = 'var(--color-border)'
      }}
    >
      {loading ? (
        <svg className="animate-spin w-5 h-5" viewBox="0 0 24 24" fill="none">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      ) : (
        icon
      )}
      <span>{loading ? 'Redirecting…' : label}</span>
    </button>
  )
}

function GoogleIcon() {
  return (
    <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  )
}

function MicrosoftIcon() {
  return (
    <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24">
      <path d="M11.4 2H2v9.4h9.4V2z" fill="#F25022" />
      <path d="M22 2h-9.4v9.4H22V2z" fill="#7FBA00" />
      <path d="M11.4 12.6H2V22h9.4v-9.4z" fill="#00A4EF" />
      <path d="M22 12.6h-9.4V22H22v-9.4z" fill="#FFB900" />
    </svg>
  )
}

function GitHubIcon() {
  return (
    <svg className="w-5 h-5 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
      />
    </svg>
  )
}
