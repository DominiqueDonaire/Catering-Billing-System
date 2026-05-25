from flask import Blueprint, jsonify, request
from db import get_connection

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/customers', methods=['GET'])
def get_customers():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    # Only return customers — exclude users with admin/staff roles
    cursor.execute("""
        SELECT c.* FROM customer c
        WHERE NOT EXISTS (
            SELECT 1 FROM users u
            WHERE u.CustomerID = c.CustomerID
            AND u.Role IN ('admin', 'staff')
        )
    """)
    result = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(result)

@customer_bp.route('/customers/<int:id>', methods=['GET'])
def get_customer(id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM customer WHERE CustomerID = %s", (id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        return jsonify({"error": "Customer not found"}), 404

    return jsonify(result)

@customer_bp.route('/customers', methods=['POST'])
def add_customer():
    data = request.json
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO customer (FirstName, LastName, Phone, Email, Address)
        VALUES (%s, %s, %s, %s, %s)
    """, (data['FirstName'], data['LastName'], data['Phone'],
          data['Email'], data['Address']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Customer added!"})

@customer_bp.route('/customers/<int:id>', methods=['PUT'])
def update_customer(id):
    data = request.json
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE customer
        SET FirstName=%s, LastName=%s, Phone=%s, Email=%s, Address=%s
        WHERE CustomerID=%s
    """, (data['FirstName'], data['LastName'], data['Phone'],
          data['Email'], data['Address'], id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"message": "Customer updated!"})

@customer_bp.route('/customers/<int:id>', methods=['DELETE'])
def delete_customer(id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. Delete order items linked to this customer's orders
        cursor.execute("""
            DELETE om FROM order_menu om
            JOIN `order` o ON om.OrderID = o.OrderID
            WHERE o.CustomerID = %s
        """, (id,))
        # 2. Delete the customer's orders
        cursor.execute("DELETE FROM `order` WHERE CustomerID = %s", (id,))
        # 3. Delete the linked user account
        cursor.execute("DELETE FROM users WHERE CustomerID = %s", (id,))
        # 4. Delete the customer record
        cursor.execute("DELETE FROM customer WHERE CustomerID = %s", (id,))
        conn.commit()
        return jsonify({"message": "Customer deleted!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@customer_bp.route('/customers/count', methods=['GET'])
def count_customers():
    conn = get_connection()
    cursor = conn.cursor()

    role = request.args.get('role', '')

    if role == 'customer':
        cursor.close()
        conn.close()
        return jsonify({"count": 0, "hidden": True})

    # Count only actual customers (exclude admin/staff)
    cursor.execute("""
        SELECT COUNT(*) FROM customer c
        WHERE NOT EXISTS (
            SELECT 1 FROM users u
            WHERE u.CustomerID = c.CustomerID
            AND u.Role IN ('admin', 'staff')
        )
    """)
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return jsonify({"count": count, "hidden": False})