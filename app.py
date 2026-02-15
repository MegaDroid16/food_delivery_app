from flask import Flask, render_template, session, redirect, url_for, request, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os

# --- IMPORT MODELS & SERVICES (Layered Architecture) ---
from models import db, User, Product, Review, Order, OrderDetail, Coupon
from services import ProductService, CartService

app = Flask(__name__)
app.secret_key = 'password'

# Ρυθμίσεις Upload
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- ΡΥΘΜΙΣΕΙΣ ΒΑΣΗΣ (SQLALCHEMY) ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:root@localhost/food_delivery'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- ΑΡΧΙΚΟΠΟΙΗΣΗ ---
db.init_app(app)

# Dependency Injection (Services)
product_service = ProductService(Product)
cart_service = CartService()

# Δημιουργία πινάκων αν δεν υπάρχουν
with app.app_context():
    db.create_all()

# --- HELPER FUNCTIONS ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# =========================================================
#                       ROUTES
# =========================================================

@app.route('/')
def index():
    # Αυτό πλέον φορτώνει το Vue.js αρχείο
    return render_template('spa_index.html')

# 2. ΤΟ ΠΑΛΙΟ INDEX ΤΟ ΚΡΑΤΑΜΕ ΩΣ BACKUP (ή για το Carousel που είναι ωραίο)
@app.route('/classic')
def classic_index():
    cat_filter = request.args.get('category')
    search_query = request.args.get('q')

    # Χρήση Service
    products = product_service.get_all_active_products()

    # Python Filtering
    if cat_filter:
        products = [p for p in products if p.category == cat_filter]
    
    if search_query:
        products = [p for p in products if search_query.lower() in p.name.lower()]
    
    categories = db.session.query(Product.category).filter_by(active=True).distinct().all()
    categories_list = [{'category': c[0]} for c in categories]
    
    return render_template('index.html', 
                           products=products, 
                           categories=categories_list, 
                           active_category=cat_filter,
                           search_query=search_query)

# --- SPA & API (ΓΙΑ ΤΙΣ ΑΠΑΙΤΗΣΕΙΣ ΤΗΣ ΕΡΓΑΣΙΑΣ) ---

@app.route('/spa')
def spa_view():
    return render_template('spa_index.html')

@app.route('/api/products', methods=['GET'])
def get_products_api():
    # Χρήση Service (Layered Arch)
    products = product_service.get_all_active_products()
    
    products_list = []
    for p in products:
        products_list.append({
            'id': p.id,
            'name': p.name,
            'category': p.category,
            'description': p.description,
            'price': p.price,
            'image_url': p.image_url
        })
    return jsonify(products_list)

@app.route('/api/cart/add', methods=['POST'])
def api_add_to_cart():
    data = request.get_json()
    product_id = data.get('product_id')
    
    if not product_id:
        return jsonify({'error': 'No product ID provided'}), 400

    cart = session.get('cart', {})
    updated_cart = cart_service.add_item(cart, product_id) # Χρήση Service
    
    session['cart'] = updated_cart
    session.modified = True
    
    total_items = cart_service.get_total_items(updated_cart)
    return jsonify({'success': True, 'cart_count': total_items})

# --- CLASSIC CART OPERATIONS ---

@app.route('/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    cart = session.get('cart', {})
    updated_cart = cart_service.add_item(cart, product_id)
    session['cart'] = updated_cart
    session.modified = True
    return jsonify({'count': cart_service.get_total_items(updated_cart)})

@app.route('/cart')
def view_cart():
    cart = session.get('cart', {})
    if not cart:
        return render_template('cart.html', cart_items=[], total_cost=0)

    # ORM: Φέρνουμε τα προϊόντα βάσει ID
    product_ids = [int(k) for k in cart.keys()]
    products_db = Product.query.filter(Product.id.in_(product_ids)).all()
    
    cart_items = []
    total_cost = 0
    
    for product in products_db:
        qty = cart[str(product.id)]
        subtotal = product.price * qty
        total_cost += subtotal
        
        # Προσοχή: Στο HTML τώρα χρησιμοποιούμε product.name αντί για product['name']
        cart_items.append({
            'info': product,
            'quantity': qty,
            'subtotal': subtotal
        })

    final_total = total_cost
    discount_amount = 0
    
    coupon = session.get('coupon')
    if coupon:
        discount_percent = coupon['discount']
        discount_amount = round((total_cost * discount_percent) / 100, 2)
        final_total = round(total_cost - discount_amount, 2)

    return render_template('cart.html', 
                           cart_items=cart_items, 
                           total_cost=round(total_cost, 2),
                           discount_amount=discount_amount, 
                           final_total=final_total)

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    session.pop('coupon', None)
    return redirect(url_for('index'))

@app.route('/update_cart/<int:product_id>/<action>')
def update_cart(product_id, action):
    cart = session.get('cart', {})
    pid_str = str(product_id)
    
    if pid_str in cart:
        if action == 'increase':
            cart[pid_str] += 1
        elif action == 'decrease':
            cart[pid_str] -= 1
            if cart[pid_str] <= 0:
                del cart[pid_str]
    
    session['cart'] = cart
    session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    pid_str = str(product_id)
    if pid_str in cart:
        del cart[pid_str]
    session['cart'] = cart
    session.modified = True
    return redirect(url_for('view_cart'))

# --- CHECKOUT & ORDERS ---

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        flash('Πρέπει να συνδεθείτε για παραγγελία!', 'error')
        return redirect(url_for('login'))

    cart = session.get('cart', {})
    if not cart:
        return redirect(url_for('index'))

    product_ids = [int(pid) for pid in cart.keys()]
    products_db = Product.query.filter(Product.id.in_(product_ids)).all()

    total_cost = sum(p.price * cart[str(p.id)] for p in products_db)
    final_total = total_cost
    
    coupon = session.get('coupon')
    if coupon:
        discount_amount = round((total_cost * coupon['discount']) / 100, 2)
        final_total = round(total_cost - discount_amount, 2)

    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        phone = request.form['phone']
        payment = request.form['payment']
        
        # Update User Info
        user = User.query.get(session['user_id'])
        user.full_name = name
        user.address = address
        user.phone = phone
        
        # Create Order
        new_order = Order(
            user_id=session['user_id'],
            customer_name=name,
            customer_address=address,
            customer_phone=phone,
            total_amount=final_total,
            payment_method=payment
        )
        db.session.add(new_order)
        db.session.flush()

        # Create Order Details
        for product in products_db:
            detail = OrderDetail(
                order_id=new_order.id,
                product_id=product.id,
                quantity=cart[str(product.id)],
                price=product.price
            )
            db.session.add(detail)
        
        db.session.commit()
        session.pop('cart', None)
        session.pop('coupon', None)
        return render_template('success.html', order_id=new_order.id)

    user = User.query.get(session['user_id'])
    user_info = {'full_name': user.full_name, 'address': user.address, 'phone': user.phone}
    return render_template('checkout.html', total_cost=round(total_cost, 2), final_total=final_total, user_info=user_info)

@app.route('/my_orders')
def my_orders():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # ORM: Φιλτράρισμα παραγγελιών χρήστη
    orders = Order.query.filter_by(user_id=session['user_id']).order_by(Order.created_at.desc()).all()
    return render_template('my_orders.html', orders=orders)

# --- USER PROFILE & AUTH ---

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        user.full_name = request.form['full_name']
        user.address = request.form['address']
        user.phone = request.form['phone']
        db.session.commit()
        flash('Το προφίλ ενημερώθηκε!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('profile.html', user=user)

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        current = request.form['current_password']
        new_pw = request.form['new_password']
        
        user = User.query.get(session['user_id'])
        
        if check_password_hash(user.password, current):
            user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash('Ο κωδικός άλλαξε!', 'success')
        else:
            flash('Λάθος τρέχων κωδικός', 'error')
        return redirect(url_for('change_password'))

    return render_template('change_password.html')

@app.route('/apply_coupon', methods=['POST'])
def apply_coupon():
    if 'coupon' in session:
        return jsonify({'success': False, 'message': 'Έχετε ήδη κουπόνι!'})
    
    data = request.get_json()
    code = data.get('code')
    
    # ORM Query
    coupon = Coupon.query.filter_by(code=code, active=True).first()
    
    if coupon:
        session['coupon'] = {'code': coupon.code, 'discount': coupon.discount_percent}
        return jsonify({'success': True, 'discount': coupon.discount_percent})
    else:
        return jsonify({'success': False, 'message': 'Άκυρο κουπόνι'})

@app.route('/remove_coupon')
def remove_coupon():
    session.pop('coupon', None)
    return redirect(url_for('view_cart'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(email=email).first():
            flash('Το email υπάρχει ήδη!', 'error')
            return redirect(url_for('register'))
            
        new_user = User(username=username, email=email, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        
        flash('Επιτυχής εγγραφή!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash(f'Καλωσήρθες {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Λάθος στοιχεία', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- ADMIN PANEL ---

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    # Μετράμε τα ενεργά προϊόντα
    p_count = Product.query.filter_by(active=True).count()
    
    # Μετράμε ΟΛΕΣ τις παραγγελίες (για στατιστικούς λόγους, ακόμα και τις ακυρωμένες)
    o_count = Order.query.count()
    
    # Υπολογίζουμε τον τζίρο ΜΟΝΟ για παραγγελίες που ΔΕΝ είναι ακυρωμένες
    revenue = db.session.query(func.sum(Order.total_amount)).filter(Order.status != 'Cancelled').scalar() or 0
    
    return render_template('admin/dashboard.html', 
                           product_count=p_count, 
                           order_count=o_count, 
                           total_revenue=round(revenue, 2))

@app.route('/admin/products', methods=['GET', 'POST'])
def admin_products():
    if session.get('role') != 'admin': return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        price = float(request.form['price'])
        desc = request.form['description']
        img = 'default.jpg'
        
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                fname = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                img = fname

        new_p = Product(name=name, category=category, description=desc, price=price, image_url=img)
        db.session.add(new_p)
        db.session.commit()
        flash('Προϊόν προστέθηκε!', 'success')
        return redirect(url_for('admin_products'))

    view = request.args.get('view', 'active')
    products = Product.query.filter_by(active=(view != 'trash')).order_by(Product.id.desc()).all()
    return render_template('admin/products.html', products=products, view_mode=view)

@app.route('/admin/product/delete/<int:product_id>')
def delete_product(product_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    product = Product.query.get(product_id)
    if product:
        product.active = False # Soft Delete
        db.session.commit()
        flash('Διαγράφηκε (Soft Delete)', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/product/restore/<int:product_id>')
def restore_product(product_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    product = Product.query.get(product_id)
    if product:
        product.active = True
        db.session.commit()
        flash('Επαναφέρθηκε!', 'success')
    return redirect(url_for('admin_products', view='trash'))

@app.route('/admin/product/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    product = Product.query.get(product_id)
    
    if request.method == 'POST':
        product.name = request.form['name']
        product.category = request.form['category']
        product.description = request.form['description']
        product.price = float(request.form['price'])
        
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            fname = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            product.image_url = fname
            
        db.session.commit()
        flash('Ενημερώθηκε!', 'success')
        return redirect(url_for('admin_products'))
        
    return render_template('admin/edit_product.html', product=product)

@app.route('/admin/orders')
def admin_orders():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)

@app.route('/admin/order/update/<int:order_id>/<status>')
def update_order_status(order_id, status):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    order = Order.query.get(order_id)
    if order and status in ['Pending', 'Completed', 'Cancelled']:
        order.status = status
        db.session.commit()
        flash(f'Status changed to {status}', 'success')
    return redirect(request.referrer)

@app.route('/admin/order/<int:order_id>')
def view_order(order_id):
    if session.get('role') != 'admin': return redirect(url_for('login'))
    
    # ORM Relationship: τα items είναι διαθέσιμα μέσω του order.details
    order = Order.query.get_or_404(order_id)
    return render_template('admin/order_details.html', order=order, items=order.details)

@app.route('/product/<int:product_id>')
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Έλεγχος αγοράς (Πιο σύνθετο ORM query με Join)
    has_purchased = False
    if 'user_id' in session:
        # Ψάχνουμε αν υπάρχει παραγγελία Completed που να περιέχει αυτό το προϊόν
        exists = db.session.query(Order).join(OrderDetail).filter(
            Order.user_id == session['user_id'],
            OrderDetail.product_id == product_id,
            Order.status == 'Completed'
        ).first()
        if exists: has_purchased = True
            
    reviews = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc()).all()
    return render_template('product_details.html', product=product, reviews=reviews, has_purchased=has_purchased)

@app.route('/product/<int:product_id>/review', methods=['POST'])
def add_review(product_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    new_review = Review(
        user_id=session['user_id'],
        product_id=product_id,
        rating=int(request.form['rating']),
        comment=request.form['comment']
    )
    db.session.add(new_review)
    db.session.commit()
    flash('Η κριτική δημοσιεύτηκε!', 'success')
    return redirect(url_for('product_details', product_id=product_id))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(debug=True)