# Predictelligence Property

**UK Property Investment Intelligence Platform**

Combines two powerful capabilities in one unified Flask application:

1. **PropertyScorecard** — AI-powered property valuation, risk analysis, negotiation strategy and deal verdict (from Rightmove listings)
2. **Predictelligence** — Live ML prediction engine using multivariate incremental linear regression (SGDRegressor with `partial_fit`) to predict UK property price direction and generate BUY/HOLD/SELL signals from live macroeconomic data

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
# → http://localhost:5000
```

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Dashboard — recent analyses + form |
| POST | `/analyze` | Analyse a Rightmove URL (JSON body: `{url, user_type}`) |
| GET | `/a/<id>` | View saved analysis |
| GET | `/a/<id>/json` | JSON data for saved analysis |
| GET | `/a/<id>/md` | Download Markdown report |
| GET | `/api/prediction/predict` | Standalone prediction (`?postcode=&current_valuation=&user_type=`) |
| GET | `/api/prediction/history` | Prediction history (`?postcode=&limit=`) |
| GET | `/api/prediction/health` | Engine health status |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PORT` | Server port (default: 5000) |
| `FLASK_ENV` | `development` enables debug mode |
| `ANTHROPIC_API_KEY` | For future AI features |

## User Types

- `investor` — Shows BUY/HOLD/SELL signal, composite score, ROI estimate
- `first_time_buyer` — Shows affordability outlook, best time to buy
- `home_mover` — Shows market timing, negotiation context

## Predictelligence Model

- **Algorithm**: SGDRegressor (online learning, incremental `partial_fit`)
- **Features**: 10 engineered macroeconomic features (BoE rate, inflation, season, etc.)
- **Data sources**: Bank of England API, ONS CPIH, Open-Meteo, postcodes.io, Land Registry HPI
- **Warm-up**: 3 cycles before predictions are issued
- **Confidence**: Grows from 70% → 95% as cycles increase
- **Background learning**: Pipeline re-runs every 60 seconds

## Deploying to Railway

1. Connect your GitHub repository to Railway
2. Railway auto-detects `railway.toml`
3. Set environment variables in Railway dashboard
4. Deploy — Railway will run `pip install -r requirements.txt && python app.py`

## Folder Structure

```
predictelligence-property/
├── app.py                      # Unified Flask app
├── propertyscorecard_core.py   # PropertyScorecard engine
├── ppd_sqlite.py               # Land Registry PPD queries
├── storage.py                  # Analysis persistence
├── predictelligence/           # ML prediction engine
│   ├── engine.py               # Main entry point
│   ├── pipeline.py             # Agent orchestration
│   ├── pipeline_state.py       # Shared state dataclass
│   ├── db_manager.py           # Prediction history DB
│   └── agents/                 # Pipeline agents
│       ├── data_agent.py       # Live API data fetching
│       ├── preprocess_agent.py # Feature engineering
│       ├── model_agent.py      # SGDRegressor
│       ├── signal_agent.py     # BUY/HOLD/SELL signal
│       └── evaluator_agent.py  # Prediction logging
├── templates/                  # Jinja2 HTML
├── static/                     # CSS + JS
└── data/                       # SQLite databases
```

---

*Educational purposes only. Not financial advice or a professional valuation.*
