from models import db, Product, Order, OrderDetail

class ProductService:
    """
    Business Logic Layer για τα Προϊόντα.
    Χρησιμοποιεί Dependency Injection για το μοντέλο Product.
    """
    def __init__(self, product_model):
        self.model = product_model  # <--- Dependency Injection

    def get_all_active_products(self):
        """Επιστρέφει όλα τα ενεργά προϊόντα (active=True)."""
        return self.model.query.filter_by(active=True).all()

    def get_product_by_id(self, product_id):
        """Βρίσκει ένα προϊόν με βάση το ID."""
        return self.model.query.get(product_id)

    def create_product(self, name, category, description, price, image_url):
        """Δημιουργεί ένα νέο προϊόν (για Admin χρήση)."""
        new_product = self.model(
            name=name,
            category=category,
            description=description,
            price=price,
            image_url=image_url
        )
        db.session.add(new_product)
        db.session.commit()
        return new_product

class CartService:
    """
    Business Logic Layer για το Καλάθι.
    Διαχειρίζεται το session dictionary και τους υπολογισμούς.
    """
    def add_item(self, cart, product_id):
        """Προσθέτει προϊόν στο καλάθι ή αυξάνει την ποσότητα."""
        product_id_str = str(product_id)
        
        if product_id_str in cart:
            cart[product_id_str] += 1
        else:
            cart[product_id_str] = 1
        
        return cart

    def remove_item(self, cart, product_id):
        """Αφαιρεί εντελώς ένα προϊόν από το καλάθι."""
        product_id_str = str(product_id)
        if product_id_str in cart:
            del cart[product_id_str]
        return cart

    def update_quantity(self, cart, product_id, action):
        """Αυξομειώνει την ποσότητα (+/-)."""
        product_id_str = str(product_id)
        
        if product_id_str in cart:
            if action == 'increase':
                cart[product_id_str] += 1
            elif action == 'decrease':
                cart[product_id_str] -= 1
                # Αν φτάσει στο 0, το διαγράφουμε
                if cart[product_id_str] <= 0:
                    del cart[product_id_str]
        return cart

    def get_total_items(self, cart):
        """Υπολογίζει το συνολικό πλήθος τεμαχίων."""
        if not cart:
            return 0
        return sum(cart.values())

    def calculate_total_cost(self, cart, product_model):
        """
        Υπολογίζει το συνολικό κόστος του καλαθιού.
        Χρειαζόμαστε το product_model για να βρούμε τις τιμές από τη βάση.
        """
        if not cart:
            return 0.0

        product_ids = [int(pid) for pid in cart.keys()]
        products = product_model.query.filter(product_model.id.in_(product_ids)).all()
        
        total = 0
        for product in products:
            qty = cart[str(product.id)]
            total += product.price * qty
            
        return round(total, 2)