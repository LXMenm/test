export type UserRole = 'USER' | 'EXPERT' | 'ADMIN';

export interface AuthUser {
  userId: string;
  username?: string | null;
  displayName: string;
  role: UserRole;
  linkedFarmerId?: string | null;
}

const AUTH_STORAGE_KEY = 'tomato_auth_user_v1';

export function normalizeRole(value: unknown): UserRole {
  const role = String(value || '').trim().toUpperCase();
  if (role === 'ADMIN' || role === 'EXPERT' || role === 'USER') return role;
  return 'USER';
}

export function loadAuthUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthUser>;
    const userId = String(parsed.userId || '').trim();
    const username = typeof parsed.username === 'string' ? parsed.username : null;
    const displayName = String(parsed.displayName || '').trim();
    const role = normalizeRole(parsed.role);
    const linkedFarmerId = typeof parsed.linkedFarmerId === 'string' ? parsed.linkedFarmerId : null;
    if (!userId || !displayName) return null;
    return { userId, username, displayName, role, linkedFarmerId };
  } catch {
    return null;
  }
}

export function saveAuthUser(user: AuthUser): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(user));
}

export function normalizeAuthUserFromPayload(
  payload: unknown,
  fallbackUser?: AuthUser | null,
): AuthUser | null {
  const source = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : {};
  const fallback = fallbackUser || null;
  const userId = String(source.user_id || fallback?.userId || '').trim();
  const username = typeof source.username === 'string'
    ? source.username
    : (typeof fallback?.username === 'string' ? fallback.username : null);
  const displayName = String(source.display_name || fallback?.displayName || '').trim();
  const role = normalizeRole(source.role || fallback?.role);
  const linkedFarmerId = typeof source.linked_farmer_id === 'string'
    ? source.linked_farmer_id
    : (fallback?.linkedFarmerId ?? null);
  if (!userId || !displayName) return null;
  return {
    userId,
    username,
    displayName,
    role,
    linkedFarmerId,
  };
}

export function clearAuthUser(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

export type AppPage =
  | 'diagnose'
  | 'dashboard'
  | 'profiles'
  | 'kb'
  | 'expert_review'
  | 'account_management'
  | 'system_config'
  | 'review_management';

export const PAGE_TO_PATH: Record<AppPage, string> = {
  diagnose: '/',
  dashboard: '/dashboard',
  profiles: '/profiles',
  kb: '/kb',
  expert_review: '/expert-review',
  account_management: '/admin/accounts',
  system_config: '/admin/system-config',
  review_management: '/admin/review-management',
};

const LEGACY_PATH_REDIRECT_MAP: Record<string, AppPage> = {
  '/cases': 'dashboard',
  '/admin/global-dashboard': 'dashboard',
  '/admin/profiles-management': 'profiles',
  '/admin/kb-management': 'kb',
};

const ROLE_PAGES: Record<UserRole, AppPage[]> = {
  USER: ['diagnose', 'dashboard', 'kb', 'profiles'],
  EXPERT: ['diagnose', 'dashboard', 'kb', 'profiles', 'expert_review'],
  ADMIN: ['diagnose', 'dashboard', 'kb', 'profiles', 'expert_review', 'review_management', 'account_management', 'system_config'],
};

export function getAllowedPages(role: UserRole): AppPage[] {
  return ROLE_PAGES[role] || ROLE_PAGES.USER;
}

export function getDefaultPage(role: UserRole): AppPage {
  return getAllowedPages(role)[0] || 'diagnose';
}

export function pathToPage(pathname: string): AppPage {
  const matched = (Object.entries(PAGE_TO_PATH).find(([, path]) => pathname === path) || [null])[0] as AppPage | null;
  if (matched) return matched;
  if (pathname in LEGACY_PATH_REDIRECT_MAP) return LEGACY_PATH_REDIRECT_MAP[pathname];
  if (pathname.startsWith('/kb/')) return 'kb';
  return 'diagnose';
}

export function withAuthHeaders(init: RequestInit | undefined, authUser: AuthUser | null): RequestInit {
  if (!authUser) return init || {};
  const headers = new Headers(init?.headers || {});
  headers.set('X-User-Id', authUser.userId);
  headers.set('X-User-Role', authUser.role);
  if (authUser.linkedFarmerId) {
    headers.set('X-Linked-Farmer-Id', authUser.linkedFarmerId);
  }
  return {
    ...(init || {}),
    headers,
  };
}

export function authFetch(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  authUser: AuthUser | null,
): Promise<Response> {
  return window.fetch(input, withAuthHeaders(init, authUser));
}
