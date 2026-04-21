from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import sqlite3
import numpy as np
from sklearn.linear_model import LinearRegression
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = "my_super_secret_key_123"
DATABASE = "retail.db"


# -------------------------------
# DATABASE CONNECTION
# -------------------------------
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------------------
# LOGIN REQUIRED DECORATOR
# -------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# -------------------------------
# DATABASE INITIALIZATION
# -------------------------------
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    # Products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            base_price REAL NOT NULL,
            stock INTEGER NOT NULL,
            last_7_days_sales TEXT NOT NULL
        )
    """)

    # Insert sample products if empty
    cursor.execute("SELECT COUNT(*) FROM products")
    count = cursor.fetchone()[0]

    if count == 0:
        sample_products = [
            ("Rice Bag", "Groceries", 1200, 50, "12,14,11,15,17,13,16"),
            ("Milk Pack", "Dairy", 30, 100, "40,42,39,45,50,48,52"),
            ("Bread", "Bakery", 40, 80, "20,22,25,23,26,28,30"),
            ("Egg Tray", "Poultry", 180, 60, "10,12,14,13,15,16,18"),
            ("Oil Bottle", "Groceries", 160, 35, "7,8,9,10,11,9,12")
        ]

        cursor.executemany("""
            INSERT INTO products (name, category, base_price, stock, last_7_days_sales)
            VALUES (?, ?, ?, ?, ?)
        """, sample_products)

    conn.commit()
    conn.close()


# -------------------------------
# ML / BUSINESS LOGIC
# -------------------------------
def predict_demand(sales_str):
    sales = list(map(int, sales_str.split(",")))

    x = np.array(range(1, len(sales) + 1)).reshape(-1, 1)
    y = np.array(sales)

    model = LinearRegression()
    model.fit(x, y)

    next_day = np.array([[len(sales) + 1]])
    predicted = model.predict(next_day)[0]

    return max(0, round(predicted))


def dynamic_price(base_price, predicted_demand, current_stock):
    if current_stock == 0:
        return round(base_price * 1.20, 2)

    demand_stock_ratio = predicted_demand / current_stock

    if demand_stock_ratio > 0.8:
        new_price = base_price * 1.15
    elif demand_stock_ratio > 0.5:
        new_price = base_price * 1.08
    elif demand_stock_ratio < 0.3:
        new_price = base_price * 0.90
    else:
        new_price = base_price

    return round(new_price, 2)


def suggest_inventory(predicted_demand, current_stock):
    recommended_stock = int(predicted_demand * 1.2)

    if current_stock < recommended_stock:
        reorder_qty = recommended_stock - current_stock
        status = "Reorder Needed"
    else:
        reorder_qty = 0
        status = "Stock Sufficient"

    return recommended_stock, reorder_qty, status


# -------------------------------
# ROUTES
# -------------------------------
@app.route("/")
def root():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("All fields are required.")
            return redirect(url_for("register"))

        conn = get_db_connection()
        existing_user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if existing_user:
            conn.close()
            flash("Username already exists.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )
        conn.commit()
        conn.close()

        flash("Registration successful. Please login.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    products = conn.execute("SELECT * FROM products").fetchall()
    conn.close()

    product_list = []
    for product in products:
        predicted = predict_demand(product["last_7_days_sales"])
        suggested_price = dynamic_price(product["base_price"], predicted, product["stock"])
        recommended_stock, reorder_qty, status = suggest_inventory(predicted, product["stock"])

        product_list.append({
            "id": product["id"],
            "name": product["name"],
            "category": product["category"],
            "base_price": product["base_price"],
            "stock": product["stock"],
            "sales_history": product["last_7_days_sales"],
            "predicted_demand": predicted,
            "suggested_price": suggested_price,
            "recommended_stock": recommended_stock,
            "reorder_qty": reorder_qty,
            "status": status
        })

    return render_template(
        "index.html",
        products=product_list,
        username=session.get("username")
    )


@app.route("/add_product", methods=["POST"])
@login_required
def add_product():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    base_price = request.form.get("base_price", "").strip()
    stock = request.form.get("stock", "").strip()
    sales_history = request.form.get("sales_history", "").strip()

    if not all([name, category, base_price, stock, sales_history]):
        return jsonify({"message": "All fields are required."}), 400

    try:
        base_price = float(base_price)
        stock = int(stock)

        sales_values = list(map(int, sales_history.split(",")))
        if len(sales_values) != 7:
            return jsonify({"message": "Sales history must contain exactly 7 numbers."}), 400

    except ValueError:
        return jsonify({"message": "Please enter valid numeric values."}), 400

    conn = get_db_connection()
    conn.execute("""
        INSERT INTO products (name, category, base_price, stock, last_7_days_sales)
        VALUES (?, ?, ?, ?, ?)
    """, (name, category, base_price, stock, sales_history))
    conn.commit()
    conn.close()

    return jsonify({"message": "Product added successfully."})


@app.route("/update_sales/<int:product_id>", methods=["POST"])
@login_required
def update_sales(product_id):
    new_sale = request.form.get("new_sale", "").strip()

    if not new_sale:
        return jsonify({"message": "Please enter today's sales."}), 400

    try:
        new_sale = int(new_sale)
        if new_sale < 0:
            return jsonify({"message": "Sales cannot be negative."}), 400
    except ValueError:
        return jsonify({"message": "Please enter a valid number."}), 400

    conn = get_db_connection()
    product = conn.execute(
        "SELECT last_7_days_sales FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        conn.close()
        return jsonify({"message": "Product not found."}), 404

    sales_list = list(map(int, product["last_7_days_sales"].split(",")))

    # Add new sale
    sales_list.append(new_sale)

    # Keep only latest 7 days
    if len(sales_list) > 7:
        sales_list = sales_list[-7:]

    updated_sales = ",".join(map(str, sales_list))

    conn.execute(
        "UPDATE products SET last_7_days_sales = ? WHERE id = ?",
        (updated_sales, product_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Today's sales updated successfully.",
        "updated_sales": updated_sales
    })


@app.route("/delete_product/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

    return jsonify({"message": "Product deleted successfully."})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)