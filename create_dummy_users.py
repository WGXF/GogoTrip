"""
Script to create 50 dummy user data into the database
"""
from main_app import app, db
from models import User
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

def create_dummy_users():
    """Create 50 dummy users with varied data"""

    # Sample data for generating realistic users
    first_names = [
        "John", "Jane", "Michael", "Sarah", "David", "Emma", "James", "Olivia",
        "Robert", "Sophia", "William", "Isabella", "Richard", "Mia", "Thomas",
        "Charlotte", "Daniel", "Amelia", "Matthew", "Emily", "Christopher", "Abigail",
        "Andrew", "Harper", "Joshua", "Evelyn", "Ryan", "Elizabeth", "Brandon", "Sofia",
        "Alexander", "Avery", "Benjamin", "Ella", "Joseph", "Scarlett", "Samuel", "Grace",
        "Nicholas", "Chloe", "Anthony", "Victoria", "Jack", "Madison", "Jonathan", "Luna",
        "Kevin", "Aria", "Tyler", "Lily"
    ]

    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White",
        "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
        "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
        "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"
    ]

    roles = ["User", "User", "User", "User", "Admin"]  # 80% User, 20% Admin
    statuses = ["active", "active", "active", "pending_verification", "suspended"]  # 60% active
    languages = ["en", "zh", "ms"]

    with app.app_context():
        created_count = 0

        for i in range(1, 51):
            # Generate random user data
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            full_name = f"{first_name} {last_name}"
            email = f"{first_name.lower()}.{last_name.lower()}{i}@example.com"

            # Check if user already exists
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                print(f"⚠️  User {email} already exists, skipping...")
                continue

            # Create user
            user = User(
                email=email,
                password_hash=generate_password_hash(f"Password{i}!"),  # Simple password for testing
                full_name=full_name,
                avatar_url=f"https://i.pravatar.cc/150?img={i}",  # Random avatar
                is_email_verified=random.choice([True, True, False]),  # 66% verified
                role=random.choice(roles),
                status=random.choice(statuses),
                preferred_language=random.choice(languages),
                email_notifications=random.choice([True, True, False]),  # 66% enabled
                last_login=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                created_at=datetime.utcnow() - timedelta(days=random.randint(30, 365))
            )

            db.session.add(user)
            created_count += 1
            print(f"✅ Created user {created_count}/50: {email}")

        # Commit all changes
        try:
            db.session.commit()
            print(f"\n🎉 Successfully created {created_count} dummy users!")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error creating users: {str(e)}")
            raise

if __name__ == "__main__":
    print("🚀 Starting to create 50 dummy users...\n")
    create_dummy_users()
    print("\n✨ Done!")
