import os
from app import create_app
from app.database import db, Organization
from seed import seed_database

app = create_app()

def initialize_system():
    """
    Guarantees the database schema exists and organizations are seeded on first launch.
    Passes the already-created `app` object into seed_database() so that
    seed.py never calls create_app() a second time.
    """
    with app.app_context():
        db.create_all()
        org_count = Organization.query.count()
        if org_count == 0:
            print("==============================================================")
            # Database is empty. Seeding from Excel files.
            print("First boot detected. Running Excel seeder to load organizations...")
            print("This may take 10-15 seconds. Please stand by...")
            print("==============================================================")
            try:
                seed_database(app)       # <-- pass the existing app, no second create_app()
            except Exception as e:
                print(f"Error during first-boot seeding: {e}")
        else:
            print(f"Database ready with {org_count} registered sources.")

if __name__ == '__main__':
    initialize_system()
    
    print("\n==============================================================")
    print(" FormsADDA Real-Time Notification Platform is launching.")
    print(" * Public Feed:       http://127.0.0.1:5000")
    print(" * Student Inbox:     http://127.0.0.1:5000/student-inbox")
    print(" * Admin Dashboard:   http://127.0.0.1:5000/admin")
    print("==============================================================\n")
    
    app.run(debug=True, host='127.0.0.1', port=5000)
