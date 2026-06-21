venv\Scripts\python.exe run.py



python run.py

pip install -r requirements.txt

# 1. Build the Docker image

docker build -t formsadda:latest .

# 2. Run the container

docker compose up -d

# 3. Verify health check passes

docker compose ps  # Should show "healthy"

# 4. Test the endpoints

curl <http://localhost:5000/>           # Public feed
curl <http://localhost:5000/admin>      # Admin dashboard
curl <http://localhost:5000/student-inbox>  # Student inbox

# 5. Verify database persistence

docker compose down
docker compose up -d

# Check that data is still present at <http://localhost:5000/admin>

# 6. Test production stack with Nginx

docker compose -f docker-compose.prod.yml up -d
curl <http://localhost/>                # Via Nginx on port 80

cp .env.example .env          # fill in your SECRET_KEY + POSTGRES_PASSWORD
docker compose up --build     # builds image, starts Postgres, auto-seeds DB

# View live logs

docker compose logs -f

# Stop containers (data preserved)

docker compose down

# Wipe the database volume completely

docker compose down -v

# Rebuild only the web image

docker compose build web && docker compose up web

cd coleage_notification

git pull
sudo docker compose restart web

git init
git remote add origin <https://github.com/thekoushikdurgas/coleage_notification.git>
git branch -M main
git add .
git commit -m "coleage_notification deployment v1"
git push -u origin main
