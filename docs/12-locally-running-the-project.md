# 12: Locally Running the Project (Windows Setup Guide)

**Component:** Environment Setup & Execution  
**Operating System:** Windows 10 / 11 (PowerShell / Command Prompt)  
**Status:** Validated  

---

## 1. Prerequisites

1. **Python 3.11+** (Python 3.13 or Anaconda distribution). Confirm with:
   ```powershell
   python --version
   ```
2. **PostgreSQL 14+** (Default port `5432` or `5433`). Confirm service is running.
3. **Git** (optional, for version control).

---

## 2. Step-by-Step Installation

### Step 1: Install Python Dependencies
From the repository root:
```powershell
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables (`.env`)
1. Create `.env` from template:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Edit `.env` with your PostgreSQL credentials:
   ```ini
   DB_NAME=fuel_route
   DB_USER=postgres
   DB_PASSWORD=your_postgres_password
   DB_HOST=localhost
   DB_PORT=5432
   GEOCODER_CONTACT_EMAIL=your_real_email@example.com
   ```
   > [!NOTE]
   > The application enforces strict database settings: if `DB_NAME` or `DB_USER` are missing, Django raises `ImproperlyConfigured` immediately. Never commit `.env` to version control.

### Step 3: Create Database & Apply Migrations
If `fuel_route` database does not exist, create it in PostgreSQL:
```powershell
# Using Python directly
python -c "import os, psycopg; from dotenv import load_dotenv; load_dotenv(); conn = psycopg.connect(dbname='postgres', user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'), host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'), autocommit=True); cur = conn.cursor(); cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (os.getenv('DB_NAME'),)); (cur.execute('CREATE DATABASE ' + os.getenv('DB_NAME')) if not cur.fetchone() else None); conn.close()"
```

Apply migrations:
```powershell
python manage.py migrate
```

### Step 4: Import Fuel Stations & Coordinates
Import the 6,626 commercial stations into PostgreSQL:
```powershell
python manage.py import_fuel_data
```

### Step 5: Start the Development Server
```powershell
python manage.py runserver 8000
```
The API is now live at: `http://127.0.0.1:8000/api/v1/route/`

---

## 3. Running Automated Tests

```powershell
# Run all 54 tests against PostgreSQL
python -m pytest

# Run with verbose output
python -m pytest -v

# Run offline in SQLite test mode (without connecting to PostgreSQL)
$env:USE_SQLITE="1"; python -m pytest; Remove-Item env:USE_SQLITE
```

---

## 4. Testing with cURL / Postman

### Successful Route (New York to Chicago):
```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/route/ `
  -H "Content-Type: application/json" `
  -d '{\"start\": \"New York, NY\", \"finish\": \"Chicago, IL\"}'
```

### Postman:
Import [`docs/fuel_route_optimizer.postman_collection.json`](file:///d:/code/assignment/docs/fuel_route_optimizer.postman_collection.json) directly into Postman to run pre-configured success and error examples.
