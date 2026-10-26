// Replace this adapter with HTTP calls when server-side user management is introduced.
// This local session controls the welcome screen only; it grants no API permissions.
export interface Session { displayName: string; mode: 'local' }
export interface AuthAdapter {
  login(displayName?: string): Promise<Session>
  logout(): Promise<void>
  restore(): Session | null
}
const key = 'redams.local-session'
export const auth: AuthAdapter = {
  async login(displayName = '') {
    const session: Session = { displayName: displayName.trim() || '本地用户', mode: 'local' }
    try { sessionStorage.setItem(key, JSON.stringify(session)) } catch { /* memory-only fallback */ }
    return session
  },
  async logout() {
    try { sessionStorage.removeItem(key) } catch { /* memory-only fallback */ }
  },
  restore() {
    try {
      const value = JSON.parse(sessionStorage.getItem(key) || 'null')
      return value?.mode === 'local' && typeof value.displayName === 'string' ? value : null
    } catch { return null }
  },
}
