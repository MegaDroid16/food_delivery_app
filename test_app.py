import pytest
from app import app, db
from models import User, Product

@pytest.fixture
def client():
    # 1. Ρύθμιση σε Testing Mode
    app.config['TESTING'] = True
    
    # 2. Αλλαγή της βάσης σε SQLite (Μνήμη RAM)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        # ΣΗΜΑΝΤΙΚΟ: Αποσυνδέουμε την παλιά μηχανή (MySQL) που φορτώθηκε από το app.py
        db.engine.dispose()
        
        # Φτιάχνουμε τους πίνακες από την αρχή στην ψεύτικη βάση
        db.create_all()
        
        yield app.test_client() # Δίνουμε τον client για τα τεστ
        
        # Καθαρισμός στο τέλος
        db.session.remove()
        db.drop_all()

# --- TEST 1: Έλεγχος ότι το API Προϊόντων δουλεύει ---
def test_get_products_api(client):
    # 1. Προσθέτουμε ΕΝΑ προϊόν στην ψεύτικη βάση
    product = Product(name="Test Pizza", category="Pizza", description="Yummy", price=10.0, active=True)
    with app.app_context():
        db.session.add(product)
        db.session.commit()

    # 2. Καλούμε το API
    response = client.get('/api/products')

    # 3. Ελέγχουμε τα αποτελέσματα
    assert response.status_code == 200
    data = response.get_json()
    
    # Τώρα θα πρέπει να βρει ΜΟΝΟ 1, γιατί η βάση είναι άδεια (εκτός από την πίτσα μας)
    assert len(data) == 1 
    assert data[0]['name'] == "Test Pizza"

# --- TEST 2: Έλεγχος Προσθήκης στο Καλάθι ---
def test_add_to_cart_api(client):
    # 1. Προσθέτουμε προϊόν
    product = Product(name="Burger", category="Burgers", description="Big", price=5.0, active=True)
    with app.app_context():
        db.session.add(product)
        db.session.commit()
        p_id = product.id

    # 2. Στέλνουμε POST request στο API καλαθιού (προσοχή στο /api/cart/add)
    response = client.post('/api/cart/add', json={'product_id': p_id})

    # 3. Ελέγχουμε
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] == True
    assert data['cart_count'] == 1