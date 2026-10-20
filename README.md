# DroneDrill AI

DroneDrill AI is an offline, AI-enabled simulation platform designed for cognitive training in drone and counter-drone threat recognition, developed for Smart India Hackathon (SIH) 2026 under Problem Statement PS 26247 by Team NexxGenX. The system trains operators to detect, classify, prioritize threats, and formulate decision responses under varying operational conditions (day/dusk/night, fog/rain/haze/dust, terrain horizons, and sensor modes) using procedural 3D scenario generation, a Bayesian skill model, and adaptive progression.

---

## Key Features

- **Multi-Sensor Simulation**: Electro-Optical (EO), Thermal Infrared, and simulated Radar feeds with Picture-in-Picture (PIP) swapping and fullscreen HUD.
- **Procedural Scenario Generation**: Factorial condition engine combining 6 operational dimensions (Time of Day, Weather, Terrain, Sensor Mode, Degradation, Distractors) with guaranteed on-screen target visibility and anti-overlap swarm spacing.
- **Hierarchical Bayesian Skill Model**: Beta-binomial posterior proficiency tracking across 5 core competencies: Detection, Classification, Decision, Timeliness, and Confidence Calibration.
- **Rote Learning vs. Generalization Engine**: Evaluates true conceptual learning by isolating performance on held-out factorial condition cells and quantifying the Rote Gap.
- **After Action Review (AAR)**: End-of-session diagnostic review featuring multi-lane contact timelines, delta comparisons against historical sessions, rule-based feedback, and sortable assessment tables.
- **Instructor Dashboard**: Cohort analytics, score distribution histograms, top misclassification pairs, and custom scenario constraint launchers.
- **Completely Offline & Self-Contained**: Plain HTML5/CSS/Vanilla JS with Canvas rendering, local SQLite database, and zero CDN dependencies.

---

## Screenshots Placeholder

```
+-----------------------------------------------------------------------------------+
|                            [SIMULATOR SCREENSHOT]                                 |
|   16:9 Central Viewing Canvas with Target Silhouettes, HUD, and Radar PIP Feed    |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
|                        [AFTER ACTION REVIEW (AAR) SCREENSHOT]                     |
|      Multi-Lane Target Timeline, 6 Score Cards, and Action Discrepancy Table      |
+-----------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------+
|                        [BAYESIAN SKILLS HEATMAP SCREENSHOT]                       |
|           Factorial Proficiency Matrix Across Environmental Conditions            |
+-----------------------------------------------------------------------------------+
```

---

## Architecture Summary

```
                      +---------------------------------------+
                      |         DroneDrill AI Client          |
                      |  Vanilla HTML5 / Modern CSS / Canvas  |
                      +---------------------------------------+
                                          |
                                   HTTP / REST API
                                          v
+-----------------------------------------------------------------------------------+
|                                FastAPI Backend                                    |
|                                                                                   |
|  +------------------+  +------------------+  +------------------+  +------------+ |
|  | Scenario Engine  |  |  Telemetry MAV   |  |  Scoring Engine  |  |  Selector  | |
|  | (1000 Cell Grid) |  |   (5 Hz Stream)  |  |  (5 Dimensions)  |  | (Bayesian) | |
|  +------------------+  +------------------+  +------------------+  +------------+ |
|                                          |                                        |
|                          +---------------+---------------+                        |
|                          |     Local SQLite Database     |                        |
|                          |    (Sessions, Events, DB)     |                        |
|                          +-------------------------------+                        |
+-----------------------------------------------------------------------------------+
```

- **Backend**: FastAPI (Python 3.10+) serving REST endpoints and streaming simulated telemetry packets at 5 Hz.
- **Storage**: SQLite database storing sessions, granular interaction events, skill cell posteriors, and telemetry history.
- **Frontend**: Plain HTML5, CSS custom properties (design tokens), Vanilla JavaScript, and Canvas 2D renderers.

---

## Setup & Running

### Prerequisites

- Python 3.10+
- Modern Web Browser (Chrome, Edge, Firefox)

### Windows Installation & Launch

```powershell
# 1. Clone repository
git clone <repository_url>
cd DroneDrill-AI-master

# 2. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install pinned dependencies
pip install -r requirements.txt

# 4. Seed synthetic demo trainees (optional, for first run)
python scripts/seed_demo.py

# 5. Start application
.\run.bat
# or directly: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Linux / macOS Installation & Launch

```bash
# 1. Clone repository
git clone <repository_url>
cd DroneDrill-AI-master

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install pinned dependencies
pip install -r requirements.txt

# 4. Seed synthetic demo trainees (optional, for first run)
python3 scripts/seed_demo.py

# 5. Start application
chmod +x run.sh
./run.sh
# or directly: python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Access the application in your browser at: **[http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/)**

---

## Deployment (Render)

DroneDrill AI deploys as a **single Render Web Service** — the FastAPI backend serves both the REST API and the static HTML/JS/CSS frontend from the same process. No separate frontend deployment is needed.

### Option A: One-Click Blueprint Deploy

1. Push this repository to **GitHub** (public or private).
2. Go to [https://dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect your GitHub repo. Render reads [`render.yaml`](render.yaml) and auto-configures the service.
4. Click **Apply** — Render installs dependencies, starts uvicorn, and gives you a public URL.

### Option B: Manual Web Service Setup

1. Go to [https://dashboard.render.com](https://dashboard.render.com) → **New** → **Web Service**.
2. Connect your GitHub repo.
3. Configure:
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Click **Create Web Service**.

### After Deployment

- Your app is live at `https://<your-service-name>.onrender.com/app/`
- The root URL `/` redirects to `/app/` automatically.
- All API endpoints (e.g., `/health`, `/session/start`) are accessible at the same domain.

### SQLite Persistence Note

> The SQLite database (`data/dronedrill.db`) lives on Render's ephemeral filesystem and **resets on each deploy or restart**. This is acceptable for demo and prototype use. For persistent data across deploys, migrate to a managed PostgreSQL database (e.g., Render PostgreSQL add-on).

---

## Running Automated Tests

Run the complete test suite (unit tests, scoring determinism, API validation, and 1,000 scenario generation checks):

```bash
python -m pytest tests/ -q
```

---

## 5-Minute Demo Click Path

1. **Landing Page (`/app/`)**: Click **START SIMULATION** to launch the adaptive drill.
2. **Simulation Canvas (`/app/simulator.html`)**:
   - Observe target silhouettes traversing the sky above the terrain horizon.
   - Click a contact in the main view or radar feed to flag it.
   - Enter your assessment on the right: choose classification (e.g. *multirotor*), threat priority, recommended response, and confidence rating. Click **Save Contact Assessment**.
   - Press **F** to enter Fullscreen mode; note picture-in-picture sensor tiles and assessment layout. Press **Esc** to exit.
   - Click **SUBMIT ASSESSMENT** to conclude the drill.
3. **After Action Review (`/app/aar.html`)**:
   - Inspect the 6 score cards, previous session delta (+/-), and key findings.
   - Examine the clean multi-lane timeline with visibility windows, detection pins, and response markers.
   - Filter events using the `Missed`, `Wrong`, or `Correct` chips.
4. **Bayesian Skill Heatmap (`/app/skills.html`)**:
   - View your trainee's skill proficiency heatmap across environmental condition factors.
5. **Generalization Report (`/app/generalization.html`)**:
   - Review your Generalization Score and Rote Gap analysis comparing practice cell mastery against held-out test conditions.
6. **Instructor Dashboard (`/app/instructor.html`)**:
   - Inspect unit cohort metrics, score distributions, and top confusion pairs.

---

## Generalization Score & Validation Explained

- **Practice vs. Held-Out Split**: Out of 288 factorial condition cells, 240 are allocated for adaptive practice and 48 are strictly held out for evaluation drills.
- **Rote Gap**: A trainee who memorizes specific practice scenarios exhibits high practice scores but falters on held-out test cells. The Rote Gap ($Score_{practice} - Score_{test}$) flags rote memorization when positive and significant.
- **Generalization Score**: Calculated over held-out test scenarios, providing a standardized measure of transfer learning under unfamiliar atmospheric and sensor conditions.

---

## Project Limitations & Disclaimers

- **Abstract Scenarios**: Visual graphics and motion trajectories are geometric synthetic approximations designed specifically for cognitive recognition training; this software is **not a certified military simulation**.
- **Decision Rules**: The decision tree rules embedded in this prototype are illustrative educational heuristics subject to review by subject matter experts.
- **Difficulty Weights**: Difficulty and timeliness weighting formulas are heuristic initial calibrations for prototype evaluation.
- **Synthetic Demo Data**: Cohort trainee profiles provided in the seed script (`scripts/seed_demo.py`) are synthetic profiles created for evaluation and interface demonstration.
- **Background Assets**: The 8 backdrop images are AI-generated (Flow) synthetic landscapes. See [client/assets/bg/CREDITS.md](client/assets/bg/CREDITS.md) for attribution.
