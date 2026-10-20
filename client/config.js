// DroneDrill AI - Client Configuration
// SIH 2026, PS 26247, Team NexxGenX
// Configures API endpoint and current active trainee identifier

const CONFIG = {
  // Always use same origin since FastAPI serves both API and client
  API_BASE: window.location.origin,
  get TRAINEE_ID() {
    return localStorage.getItem("dronedrill_trainee_id") || "demo_trainee_01";
  },
  set TRAINEE_ID(val) {
    if (val) localStorage.setItem("dronedrill_trainee_id", val);
  },
  getActiveTraineeId() {
    return localStorage.getItem("dronedrill_trainee_id") || "demo_trainee_01";
  },
  APP_VERSION: "1.0.0",
};

// Export to window
window.CONFIG = CONFIG;

