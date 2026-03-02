// Configuration for API endpoints
// If VITE_API_URL is set (e.g. in production), use it.
// Otherwise, use the local backend directly during localhost development.

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1']);
const inferredLocalBaseUrl = typeof window !== 'undefined' && LOCAL_HOSTS.has(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : '';

export const API_BASE_URL = import.meta.env.VITE_API_URL || inferredLocalBaseUrl;

export const getApiUrl = (path) => {
    if (path.startsWith('http')) return path;
    // Ensure path starts with / if not present
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${API_BASE_URL}${normalizedPath}`;
};
