from flask import Blueprint, request, jsonify
from db import get_connection
from werkzeug.security import generate_password_hash, check_password_hash

auth_bp = Blueprint('auth', __name__)

# ── REGISTER ─────────────────────────────────────────────────────
# Registration is ALWAYS for customers only.
# Admin/Staff accounts are created only through the Users page (admin only).
@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Check if username already exists
        cursor.execute("SELECT * FROM users WHERE Username = %s", (data['Username'],))
        if cursor.fetchone():
            return jsonify({"error": "Username already exists"}), 400

        # 2. Hash the password
        hashed_pw = generate_password_hash(data['Password'])

        # 3. Role is ALWAYS customer — ignore any role sent from frontend
        role = 'customer'

        # 4. Insert into customer table first
        cursor.execute("""
            INSERT INTO customer (FirstName, LastName, Email, Phone)
            VALUES (%s, %s, %s, %s)
        """, (data['FirstName'], data['LastName'], data['Email'], data['Phone']))
        new_customer_id = cursor.lastrowid

        # 5. Insert into users table linked to the customer record
        cursor.execute("""
            INSERT INTO users (Username, Password, Role, CustomerID)
            VALUES (%s, %s, %s, %s)
        """, (data['Username'], hashed_pw, role, new_customer_id))

        conn.commit()
        return jsonify({"message": "Registration successful"}), 201

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ── LOGIN ─────────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM users WHERE Username = %s", (data['Username'],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user:
        return jsonify({"error": "Username not found"}), 401

    if not check_password_hash(user['Password'], data['Password']):
        return jsonify({"error": "Incorrect password"}), 401

    return jsonify({
        "message":     "Login successful",
        "role":        user['Role'],
        "username":    user['Username'],
        "customer_id": user['CustomerID'],
    })