from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from db import get_connection

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

VALID_METHODS = ('Cash', 'GCash', 'Maya', 'Bank Transfer', 'Credit Card')


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def json_row(row):
    return {key: json_value(value) for key, value in row.items()} if row else None


def parse_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('AmountPaid must be a valid number.')

    if amount <= 0:
        raise ValueError('AmountPaid must be greater than zero.')

    return amount.quantize(Decimal('0.01'))


def get_order_balance(cursor, order_id, exclude_payment_id=None):
    cursor.execute(
        "SELECT TotalAmount FROM `order` WHERE OrderID = %s",
        (order_id,)
    )
    order_row = cursor.fetchone()
    if not order_row:
        return None, None, None

    total_amount = Decimal(str(order_row['TotalAmount'] or 0)).quantize(Decimal('0.01'))
    params = [order_id]
    query = """
        SELECT COALESCE(SUM(AmountPaid), 0) AS TotalPaid
        FROM payment
        WHERE OrderID = %s
          AND VerificationStatus <> 'Rejected'
    """
    if exclude_payment_id is not None:
        query += " AND PaymentID <> %s"
        params.append(exclude_payment_id)

    cursor.execute(query, tuple(params))
    paid_row = cursor.fetchone() or {}
    total_paid = Decimal(str(paid_row.get('TotalPaid') or 0)).quantize(Decimal('0.01'))
    remaining = max(Decimal('0.00'), total_amount - total_paid)
    return total_amount, total_paid, remaining


@payments_bp.route('/', methods=['GET'], strict_slashes=False)
def get_payments():
    order_id = request.args.get('order_id')
    customer_id = request.args.get('customer_id')
    role = (request.args.get('role') or '').lower()

    if role == 'customer' and not customer_id:
        return jsonify([])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_payment_archive_schema(cursor)
    query = """
        SELECT p.*, o.CustomerID,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM payment p
        JOIN `order` o ON p.OrderID = o.OrderID
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE (p.IsArchived = 0 OR p.IsArchived IS NULL)
    """
    params = []

    if order_id:
        query += ' AND p.OrderID = %s'
        params.append(order_id)
    if customer_id:
        query += ' AND o.CustomerID = %s'
        params.append(customer_id)

    query += ' ORDER BY p.PaymentID DESC'
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([json_row(row) for row in rows])


@payments_bp.route('/<int:payment_id>', methods=['GET'])
def get_payment(payment_id):
    customer_id = request.args.get('customer_id')
    role = (request.args.get('role') or '').lower()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.*, o.CustomerID,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM payment p
        JOIN `order` o ON p.OrderID = o.OrderID
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE p.PaymentID = %s
    """, (payment_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({'message': 'Payment not found.'}), 404
    if role == 'customer' and str(row['CustomerID']) != str(customer_id):
        return jsonify({'message': 'Payment not found.'}), 404
    return jsonify(json_row(row))


@payments_bp.route('/', methods=['POST'], strict_slashes=False)
def create_payment():
    data = request.get_json() or {}
    order_id = data.get('OrderID')
    pay_date = data.get('PaymentDate') or date.today().isoformat()
    amount_value = data.get('AmountPaid')
    method = data.get('Method', '')
    ref = data.get('ReferenceNo', '')

    if not order_id or amount_value in (None, '') or method not in VALID_METHODS:
        return jsonify({'message': 'OrderID, AmountPaid, and a valid Method are required.'}), 400

    try:
        amount = parse_amount(amount_value)
    except ValueError as exc:
        return jsonify({'message': str(exc)}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    total_amount, _, remaining = get_order_balance(cursor, order_id)
    if total_amount is None:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if remaining <= 0:
        cursor.close()
        conn.close()
        return jsonify({'message': 'This order is already fully paid.'}), 400

    if amount > remaining:
        cursor.close()
        conn.close()
        return jsonify({
            'message': f'Payment exceeds remaining balance of {remaining:.2f}.'
        }), 400

    initial_status = 'Verified' if method == 'Cash' else 'Pending'
    cursor.execute("""
        INSERT INTO payment
            (OrderID, PaymentDate, AmountPaid, Method, ReferenceNo, VerificationStatus)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (order_id, pay_date, amount, method, ref, initial_status))
    new_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Payment recorded.', 'PaymentID': new_id}), 201


@payments_bp.route('/<int:payment_id>', methods=['PUT'])
def update_payment(payment_id):
    data = request.get_json() or {}
    role = (data.get('_role') or '').lower()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM payment WHERE PaymentID = %s', (payment_id,))
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Payment not found.'}), 404

    order_id = row['OrderID']
    payment_date = data.get('PaymentDate', row['PaymentDate'])
    amount_value = data.get('AmountPaid', row['AmountPaid'])
    method = data.get('Method', row['Method'])
    reference_no = data.get('ReferenceNo', row.get('ReferenceNo'))

    if method not in VALID_METHODS:
        cursor.close()
        conn.close()
        return jsonify({'message': 'A valid payment method is required.'}), 400

    try:
        amount = parse_amount(amount_value)
    except ValueError as exc:
        cursor.close()
        conn.close()
        return jsonify({'message': str(exc)}), 400

    _, _, remaining = get_order_balance(cursor, order_id, exclude_payment_id=payment_id)
    if remaining is None:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if amount > remaining:
        cursor.close()
        conn.close()
        return jsonify({
            'message': f'Payment exceeds remaining balance of {remaining:.2f}.'
        }), 400

    if role not in ('admin', 'staff') and row['VerificationStatus'] == 'Verified':
        cursor.close()
        conn.close()
        return jsonify({'message': 'This payment has been verified and cannot be edited.'}), 403

    verification_status = row['VerificationStatus']
    verified_by = row.get('VerifiedBy')
    verified_at = row.get('VerifiedAt')

    if role in ('admin', 'staff'):
        if method == 'Cash':
            verification_status = 'Verified'
        else:
            verification_status = 'Pending'
            verified_by = None
            verified_at = None

    cursor.execute("""
        UPDATE payment
        SET OrderID = %s,
            PaymentDate = %s,
            AmountPaid = %s,
            Method = %s,
            ReferenceNo = %s,
            VerificationStatus = %s,
            VerifiedBy = %s,
            VerifiedAt = %s
        WHERE PaymentID = %s
    """, (
        order_id,
        payment_date,
        amount,
        method,
        reference_no,
        verification_status,
        verified_by,
        verified_at,
        payment_id
    ))
    conn.commit()
    cursor.close()
    conn.close()

    if role in ('admin', 'staff') and method != 'Cash':
        return jsonify({'message': 'Payment updated and reset to Pending.'})
    return jsonify({'message': 'Payment updated.'})


@payments_bp.route('/<int:payment_id>/verify', methods=['PATCH'])
def verify_payment(payment_id):
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'verify')
    verifier = data.get('verifier_id')

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        'SELECT VerificationStatus FROM payment WHERE PaymentID = %s',
        (payment_id,)
    )
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Payment not found.'}), 404

    if row['VerificationStatus'] == 'Verified':
        cursor.close()
        conn.close()
        return jsonify({'message': 'Payment is already verified.'}), 400

    new_status = 'Verified' if action == 'verify' else 'Rejected'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute("""
        UPDATE payment
        SET VerificationStatus = %s, VerifiedBy = %s, VerifiedAt = %s
        WHERE PaymentID = %s
    """, (new_status, verifier, now, payment_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({
        'message': f'Payment {new_status.lower()} successfully.',
        'VerificationStatus': new_status
    })


def ensure_payment_archive_schema(cursor):
    cursor.execute("SHOW COLUMNS FROM payment LIKE 'IsArchived'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE payment
            ADD COLUMN IsArchived TINYINT(1) NOT NULL DEFAULT 0
        """)
    cursor.execute("SHOW COLUMNS FROM payment LIKE 'ArchivedAt'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE payment
            ADD COLUMN ArchivedAt DATETIME NULL
        """)


@payments_bp.route('/<int:payment_id>', methods=['DELETE'])
def delete_payment(payment_id):
    """Soft-delete: archive the payment instead of removing it."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_payment_archive_schema(cursor)
    cursor.execute(
        'SELECT 1 AS found FROM payment WHERE PaymentID = %s AND (IsArchived = 0 OR IsArchived IS NULL)',
        (payment_id,)
    )
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({'message': 'Payment not found.'}), 404
    try:
        cursor.execute(
            'UPDATE payment SET IsArchived = 1, ArchivedAt = NOW() WHERE PaymentID = %s',
            (payment_id,)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'message': str(e)}), 500
    cursor.close()
    conn.close()
    return jsonify({'message': 'Payment archived.'})


@payments_bp.route('/archived', methods=['GET'])
def get_archived_payments():
    """Return all archived payments. Admin and staff only."""
    role = (request.args.get('role') or '').lower()
    if role not in ('admin', 'staff'):
        return jsonify({'message': 'Access denied.'}), 403

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_payment_archive_schema(cursor)
    cursor.execute("""
        SELECT p.*, o.CustomerID,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM payment p
        JOIN `order` o ON p.OrderID = o.OrderID
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE p.IsArchived = 1
        ORDER BY p.ArchivedAt DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([json_row(row) for row in rows])


@payments_bp.route('/<int:payment_id>/restore', methods=['PATCH'])
def restore_payment(payment_id):
    """Restore an archived payment. Admin only."""
    data = request.get_json(silent=True) or {}
    role = (data.get('_role') or request.args.get('role') or '').lower()
    if role != 'admin':
        return jsonify({'message': 'Only admins can restore archived payments.'}), 403

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_payment_archive_schema(cursor)
    cursor.execute(
        'SELECT 1 FROM payment WHERE PaymentID = %s AND IsArchived = 1',
        (payment_id,)
    )
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({'message': 'Archived payment not found.'}), 404
    try:
        cursor.execute(
            'UPDATE payment SET IsArchived = 0, ArchivedAt = NULL WHERE PaymentID = %s',
            (payment_id,)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'message': str(e)}), 500
    cursor.close()
    conn.close()
    return jsonify({'message': 'Payment restored successfully.'})