// Public runtime configuration for Project Visibility.
// apiBase is intentionally not a secret. When the backend receives a stable
// HTTPS hostname, set it here once and landing, builder and dashboard will use it.
window.PV_RUNTIME = Object.freeze({
  apiBase: ""
});
