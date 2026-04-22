@echo off
echo Starting Postgres Docker container...
docker compose -f docker-compose.postgres.yml up -d

echo.
echo Waiting for database to stabilize...
timeout /t 5 /nobreak > nul

echo.
echo Running Postgres Bootstrap script...
.\.venv\Scripts\python.exe main_postgres_bootstrap.py

echo.
echo Postgres setup complete.
pause
