from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import Importer, User, UserRole
from app.db.session import Base, SessionLocal, engine
from app.main import app


def setup_function() -> None:
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    importer = Importer(legal_name="Demo Importer")
    db.add(importer)
    db.flush()
    db.add(
        User(
            email="manager@example.com",
            password_hash=hash_password("password"),
            full_name="Demo Manager",
            role=UserRole.MANAGER,
        )
    )
    db.add(
        User(
            email="importer@example.com",
            password_hash=hash_password("password"),
            full_name="Demo Importer User",
            role=UserRole.IMPORTER,
            importer_id=importer.id,
        )
    )
    db.commit()
    db.close()


def test_login_and_create_shipment() -> None:
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "manager@example.com", "password": "password"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        db = SessionLocal()
        importer = db.query(Importer).first()
        db.close()

        response = client.post(
            "/api/shipments",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "shipment_number": "SHP-TEST-1",
                "importer_id": importer.id,
                "supplier_name": "Company B",
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "draft"


def test_importer_cannot_create_shipment() -> None:
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "importer@example.com", "password": "password"})
        response = client.post(
            "/api/shipments",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"shipment_number": "SHP-TEST-2", "importer_id": "missing"},
        )
        assert response.status_code == 403
