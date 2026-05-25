from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, request

from db import get_connection

orders_bp = Blueprint('orders', __name__, url_prefix='/orders')

VALID_STATUSES = ('Pending', 'Confirmed', 'Completed', 'Cancelled')
CANCEL_WINDOW_MINUTES = 5
MIN_EVENT_LEAD_DAYS = 3


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def json_row(row):
    return {key: json_value(value) for key, value in row.items()} if row else None


def minimum_event_date(base_date=None):
    base = base_date or date.today()
    return base + timedelta(days=MIN_EVENT_LEAD_DAYS)


def ensure_menu_pricing_schema(cursor):
    cursor.execute("SHOW COLUMNS FROM menuitem LIKE 'pricing_type'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN pricing_type ENUM('per_pax', 'flat_rate')
            NOT NULL DEFAULT 'per_pax'
            AFTER Category
        """)

    cursor.execute("SHOW COLUMNS FROM menuitem LIKE 'serves_up_to'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN serves_up_to INT NULL
            AFTER pricing_type
        """)

    cursor.execute("SHOW COLUMNS FROM menuitem LIKE 'IsHalal'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN IsHalal TINYINT(1) NOT NULL DEFAULT 0
            AFTER serves_up_to
        """)

    cursor.execute("SHOW COLUMNS FROM menuitem LIKE 'IsDeleted'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN IsDeleted TINYINT(1) NOT NULL DEFAULT 0
        """)


def compute_line_total(price, pricing_type, pax, quantity):
    safe_price = float(price or 0)
    safe_qty = int(quantity or 0)
    safe_pax = int(pax or 0)
    if pricing_type == 'flat_rate':
        return safe_price * safe_qty
    return safe_price * safe_pax * safe_qty


def line_breakdown(price, pricing_type, pax, quantity):
    formatted_price = f'₱{float(price or 0):,.2f}'
    total = compute_line_total(price, pricing_type, pax, quantity)
    if pricing_type == 'flat_rate':
        return f'{formatted_price} × qty {int(quantity or 0)} = ₱{total:,.2f} (flat rate)'
    return f'{formatted_price} × {int(pax or 0)} pax × qty {int(quantity or 0)} = ₱{total:,.2f}'


def parse_iso_date(value, field_name):
    try:
        return date.fromisoformat((value or '').strip())
    except ValueError:
        raise ValueError(f'Invalid {field_name} format.')


def validate_event_lead_time(event_date_value, base_date=None):
    event_date = parse_iso_date(event_date_value, 'EventDate')
    min_date = minimum_event_date(base_date)
    if event_date < min_date:
        raise ValueError(
            f'Event date must be at least {MIN_EVENT_LEAD_DAYS} days from today.'
        )
    return event_date


def ensure_archive_schema(cursor):
    cursor.execute("SHOW COLUMNS FROM `order` LIKE 'IsArchived'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE `order`
            ADD COLUMN IsArchived TINYINT(1) NOT NULL DEFAULT 0
        """)
    cursor.execute("SHOW COLUMNS FROM `order` LIKE 'ArchivedAt'")
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE `order`
            ADD COLUMN ArchivedAt DATETIME NULL
        """)


def ensure_order_detail_columns(cursor):
    cursor.execute("SHOW COLUMNS FROM `order` LIKE %s", ('CreatedAt',))
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE `order`
            ADD COLUMN CreatedAt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        """)

    cursor.execute("SHOW COLUMNS FROM `order` LIKE %s", ('EventAddress',))
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE `order`
            ADD COLUMN EventAddress VARCHAR(255) NULL AFTER EventDate
        """)


def auto_confirm_expired_orders(conn, cursor):
    ensure_order_detail_columns(cursor)
    cursor.execute(f"""
        UPDATE `order`
        SET Status = 'Confirmed'
        WHERE Status = 'Pending'
          AND CreatedAt <= DATE_SUB(NOW(), INTERVAL {CANCEL_WINDOW_MINUTES} MINUTE)
          AND EventDate IS NOT NULL
          AND EventAddress IS NOT NULL
          AND TRIM(EventAddress) <> ''
    """)
    conn.commit()


def cancellation_meta(row):
    created_at = row.get('CreatedAt') if row else None
    if not isinstance(created_at, datetime):
        return None, 0

    deadline = created_at + timedelta(minutes=CANCEL_WINDOW_MINUTES)
    remaining = max(0, int((deadline - datetime.now()).total_seconds()))
    return deadline, remaining


def serialize_order(row):
    if not row:
        return None

    deadline, remaining = cancellation_meta(row)
    data = json_row(row)
    data['HasEventDetails'] = bool(data.get('EventDate') and (data.get('EventAddress') or '').strip())
    data['CancelDeadline'] = deadline.isoformat() if deadline else None
    data['CancelWindowSecondsRemaining'] = remaining
    data['CanRequestCancel'] = data.get('Status') in ('Pending',) and remaining > 0
    return data


@orders_bp.route('/', methods=['GET'], strict_slashes=False)
def get_orders():
    customer_id = request.args.get('customer_id')
    status = request.args.get('status')
    role = (request.args.get('role') or '').lower()

    if role == 'customer' and not customer_id:
        return jsonify([])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    auto_confirm_expired_orders(conn, cursor)
    ensure_archive_schema(cursor)
    query = """
        SELECT o.*, c.FirstName, c.LastName,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM `order` o
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE (o.IsArchived = 0 OR o.IsArchived IS NULL)
    """
    params = []

    if customer_id:
        query += ' AND o.CustomerID = %s'
        params.append(customer_id)
    if status:
        query += ' AND o.Status = %s'
        params.append(status)

    query += ' ORDER BY o.OrderID DESC'
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([serialize_order(row) for row in rows])


@orders_bp.route('/<int:order_id>', methods=['GET'])
def get_order(order_id):
    customer_id = request.args.get('customer_id')
    role = (request.args.get('role') or '').lower()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    auto_confirm_expired_orders(conn, cursor)
    cursor.execute("""
        SELECT o.*, c.FirstName, c.LastName,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM `order` o
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE o.OrderID = %s
    """, (order_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({'message': 'Order not found.'}), 404
    if role == 'customer' and str(row['CustomerID']) != str(customer_id):
        return jsonify({'message': 'Order not found.'}), 404
    return jsonify(serialize_order(row))


@orders_bp.route('/<int:order_id>/items', methods=['GET'])
def get_order_items(order_id):
    customer_id = request.args.get('customer_id')
    role = (request.args.get('role') or '').lower()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_order_detail_columns(cursor)
    ensure_menu_pricing_schema(cursor)
    if role == 'customer':
        cursor.execute(
            "SELECT CustomerID FROM `order` WHERE OrderID = %s",
            (order_id,)
        )
        order = cursor.fetchone()
        if not order or str(order['CustomerID']) != str(customer_id):
            cursor.close()
            conn.close()
            return jsonify({'message': 'Order not found.'}), 404

    cursor.execute("""
        SELECT om.OrderMenuID, om.OrderID, om.ItemID, om.Quantity,
               m.ItemName, m.Category, m.PricePerPax, m.pricing_type,
               m.serves_up_to, m.IsHalal, m.image_path
        FROM order_menu om
        JOIN menuitem m ON om.ItemID = m.ItemID
        WHERE om.OrderID = %s
    """, (order_id,))
    rows = cursor.fetchall()
    cursor.execute("SELECT Pax FROM `order` WHERE OrderID = %s", (order_id,))
    order_row = cursor.fetchone() or {}
    cursor.close()
    conn.close()
    pax = order_row.get('Pax') or 0
    payload = []
    for row in rows:
        item = json_row(row)
        item['pricing_type'] = item.get('pricing_type') or 'per_pax'
        item['line_total'] = compute_line_total(item.get('PricePerPax'), item['pricing_type'], pax, item.get('Quantity'))
        item['line_breakdown'] = line_breakdown(item.get('PricePerPax'), item['pricing_type'], pax, item.get('Quantity'))
        payload.append(item)
    return jsonify(payload)


@orders_bp.route('/', methods=['POST'], strict_slashes=False)
def create_order():
    data = request.get_json() or {}
    customer_id = data.get('CustomerID')
    role = (data.get('_role') or '').lower()
    session_customer_id = data.get('_customer_id')
    order_date = date.today()
    event_date = (data.get('EventDate') or '').strip()
    event_address = (data.get('EventAddress') or '').strip()
    pax = data.get('Pax')
    status = data.get('Status', 'Pending')
    items = data.get('items') or []

    if not customer_id or not event_date or not event_address or not pax:
        return jsonify({'message': 'CustomerID, EventDate, EventAddress, and Pax are required.'}), 400

    if role == 'customer' and str(customer_id) != str(session_customer_id):
        return jsonify({'message': 'Customers can only create their own orders.'}), 403

    try:
        event_date_obj = validate_event_lead_time(event_date, order_date)
    except ValueError as exc:
        return jsonify({'message': str(exc)}), 400

    if status not in VALID_STATUSES:
        status = 'Pending'
    if role == 'customer':
        status = 'Pending'

    conn = get_connection()
    cursor = conn.cursor()
    try:
        ensure_order_detail_columns(cursor)
        ensure_menu_pricing_schema(cursor)

        item_ids = [item.get('ItemID') for item in items if item.get('ItemID')]
        price_map = {}
        total = 0
        if item_ids:
            placeholders = ','.join(['%s'] * len(item_ids))
            cursor.execute(
                f"""
                    SELECT ItemID, PricePerPax, pricing_type
                    FROM menuitem
                    WHERE ItemID IN ({placeholders})
                      AND IsDeleted = 0
                """,
                item_ids
            )
            price_map = {
                row[0]: {'PricePerPax': float(row[1]), 'pricing_type': row[2] or 'per_pax'}
                for row in cursor.fetchall()
            }

        for item in items:
            item_id = item.get('ItemID')
            if item_id not in price_map:
                raise ValueError(f'Menu item {item_id} not found.')
            total += compute_line_total(
                price_map[item_id]['PricePerPax'],
                price_map[item_id]['pricing_type'],
                pax,
                item.get('Quantity', 1)
            )

        cursor.execute("""
            INSERT INTO `order`
                (CustomerID, OrderDate, EventDate, EventAddress, Pax, TotalAmount, Status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            customer_id,
            order_date.isoformat(),
            event_date_obj.isoformat(),
            event_address,
            pax,
            total,
            status,
        ))
        order_id = cursor.lastrowid

        for item in items:
            cursor.execute("""
                INSERT INTO order_menu (OrderID, ItemID, Quantity)
                VALUES (%s, %s, %s)
            """, (order_id, item['ItemID'], item.get('Quantity', 1)))

        conn.commit()
    except ValueError as exc:
        conn.rollback()
        return jsonify({'message': str(exc)}), 400
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return jsonify({'message': 'Order created.', 'order_id': order_id}), 201


@orders_bp.route('/<int:order_id>', methods=['PUT'])
def update_order(order_id):
    data = request.get_json() or {}
    new_status = data.get('Status')

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    auto_confirm_expired_orders(conn, cursor)
    cursor.execute("SELECT * FROM `order` WHERE OrderID = %s", (order_id,))
    current = cursor.fetchone()
    if not current:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    role = (data.get('_role') or 'admin').lower()
    if role == 'customer':
        cursor.close()
        conn.close()
        return jsonify({'message': 'Customers cannot edit orders here.'}), 403

    # Staff cannot set Completed or Cancelled
    if role == 'staff' and new_status in ('Completed', 'Cancelled'):
        cursor.close()
        conn.close()
        return jsonify({'message': 'Staff cannot set this status.'}), 403

    if new_status not in VALID_STATUSES:
        new_status = current['Status']

    # Admin and staff can only update Status — all other fields are read-only
    cursor.execute(
        "UPDATE `order` SET Status=%s WHERE OrderID=%s",
        (new_status, order_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Order updated.'})


@orders_bp.route('/<int:order_id>/details', methods=['PATCH'])
def update_order_details(order_id):
    """Customer route to update EventDate, Pax, and EventAddress on a Confirmed order
    that is at least 3 days before the event."""
    data        = request.get_json() or {}
    role        = (data.get('_role') or '').lower()
    customer_id = data.get('_customer_id')

    if role != 'customer':
        return jsonify({'message': 'This route is for customers only.'}), 403

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_pricing_schema(cursor)
    cursor.execute(
        "SELECT CustomerID, Status, EventDate FROM `order` WHERE OrderID = %s",
        (order_id,)
    )
    order = cursor.fetchone()

    if not order:
        cursor.close(); conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if str(order['CustomerID']) != str(customer_id):
        cursor.close(); conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if order['Status'] != 'Confirmed':
        cursor.close(); conn.close()
        return jsonify({'message': 'You can only edit Confirmed orders.'}), 403

    # Validate: current event date must still be at least 3 days away
    event_date = order['EventDate']
    if isinstance(event_date, str):
        event_date = date.fromisoformat(event_date)
    if event_date < minimum_event_date():
        cursor.close(); conn.close()
        return jsonify({'message': f'Cannot edit order within {MIN_EVENT_LEAD_DAYS} days of the event.'}), 403

    # Validate new event date also respects the 3-day lead time
    new_event_date = (data.get('EventDate') or '').strip()
    if not new_event_date:
        cursor.close(); conn.close()
        return jsonify({'message': 'EventDate is required.'}), 400
    try:
        new_date_obj = validate_event_lead_time(new_event_date)
    except ValueError as exc:
        cursor.close(); conn.close()
        return jsonify({'message': str(exc)}), 400

    pax     = data.get('Pax')
    address = (data.get('EventAddress') or '').strip()
    if not pax or int(pax) < 1:
        cursor.close(); conn.close()
        return jsonify({'message': 'Pax must be at least 1.'}), 400
    if not address:
        cursor.close(); conn.close()
        return jsonify({'message': 'EventAddress is required.'}), 400

    try:
        cursor.execute("""
            UPDATE `order`
            SET EventDate=%s, Pax=%s, EventAddress=%s
            WHERE OrderID=%s
        """, (new_date_obj.isoformat(), pax, address, order_id))
        cursor.execute("""
            SELECT om.Quantity, m.PricePerPax, m.pricing_type
            FROM order_menu om
            JOIN menuitem m ON m.ItemID = om.ItemID
            WHERE om.OrderID = %s
        """, (order_id,))
        items = cursor.fetchall()
        total = sum(
            compute_line_total(item['PricePerPax'], item.get('pricing_type'), pax, item['Quantity'])
            for item in items
        )
        cursor.execute(
            "UPDATE `order` SET TotalAmount = %s WHERE OrderID = %s",
            (total, order_id)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close(); conn.close()
        return jsonify({'message': str(e)}), 500

    cursor.close()
    conn.close()
    return jsonify({'message': 'Order details updated.'})


@orders_bp.route('/<int:order_id>/dishes', methods=['PUT'])
def update_order_dishes(order_id):
    """Customer-only route to add/remove dishes on a Confirmed order
    that is at least 3 days before the event date."""
    data        = request.get_json() or {}
    role        = (data.get('_role') or '').lower()
    customer_id = data.get('_customer_id')
    items       = data.get('items') or []

    if role != 'customer':
        return jsonify({'message': 'This route is for customers only.'}), 403

    if not items:
        return jsonify({'message': 'Please include at least one dish.'}), 400

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_pricing_schema(cursor)

    # Verify the order belongs to this customer
    cursor.execute(
        "SELECT CustomerID, Status, EventDate, Pax FROM `order` WHERE OrderID = %s",
        (order_id,)
    )
    order = cursor.fetchone()

    if not order:
        cursor.close(); conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if str(order['CustomerID']) != str(customer_id):
        cursor.close(); conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    # Must be Confirmed
    if order['Status'] != 'Confirmed':
        cursor.close(); conn.close()
        return jsonify({'message': 'You can only edit dishes on Confirmed orders.'}), 403

    # Must still be at least 3 days before the event
    event_date = order['EventDate']
    if isinstance(event_date, str):
        event_date = date.fromisoformat(event_date)
    if event_date < minimum_event_date():
        cursor.close(); conn.close()
        return jsonify({'message': f'Cannot edit dishes within {MIN_EVENT_LEAD_DAYS} days of the event.'}), 403

    try:
        # Replace all existing order_menu items
        cursor.execute("DELETE FROM order_menu WHERE OrderID = %s", (order_id,))

        # Fetch prices to recalculate total
        item_ids   = [i['ItemID'] for i in items]
        format_ids = ','.join(['%s'] * len(item_ids))
        cursor.execute(
            f"""
                SELECT ItemID, PricePerPax, pricing_type
                FROM menuitem
                WHERE ItemID IN ({format_ids})
                  AND IsDeleted = 0
            """,
            item_ids
        )
        price_map = {
            row['ItemID']: {
                'PricePerPax': float(row['PricePerPax']),
                'pricing_type': row.get('pricing_type') or 'per_pax'
            }
            for row in cursor.fetchall()
        }
        pax       = order['Pax'] or 1
        total     = 0

        for item in items:
            qty   = item.get('Quantity', 1)
            menu_item = price_map.get(item['ItemID'])
            if not menu_item:
                raise ValueError(f"Menu item {item['ItemID']} not found.")
            total += compute_line_total(
                menu_item['PricePerPax'],
                menu_item['pricing_type'],
                pax,
                qty
            )
            cursor.execute(
                "INSERT INTO order_menu (OrderID, ItemID, Quantity) VALUES (%s, %s, %s)",
                (order_id, item['ItemID'], qty)
            )

        # Update total amount on the order
        cursor.execute(
            "UPDATE `order` SET TotalAmount = %s WHERE OrderID = %s",
            (total, order_id)
        )
        conn.commit()
    except ValueError as e:
        conn.rollback()
        cursor.close(); conn.close()
        return jsonify({'message': str(e)}), 400
    except Exception as e:
        conn.rollback()
        cursor.close(); conn.close()
        return jsonify({'message': str(e)}), 500

    cursor.close()
    conn.close()
    return jsonify({'message': 'Dishes updated successfully.', 'TotalAmount': total})


@orders_bp.route('/<int:order_id>/cancel', methods=['PATCH'])
def cancel_order(order_id):
    data = request.get_json(silent=True) or {}
    role = (data.get('_role') or request.args.get('role') or '').lower()
    customer_id = data.get('_customer_id') or request.args.get('customer_id')

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    auto_confirm_expired_orders(conn, cursor)
    cursor.execute(
        "SELECT Status, CustomerID, CreatedAt FROM `order` WHERE OrderID = %s",
        (order_id,)
    )
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if role == 'customer' and str(row['CustomerID']) != str(customer_id):
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if row['Status'] not in ('Pending',):
        cursor.close()
        conn.close()
        return jsonify({
            'message': f'Cannot cancel. Order is already {row["Status"]}.'
        }), 400

    if role == 'customer':
        _, remaining = cancellation_meta(row)
        if remaining <= 0:
            cursor.close()
            conn.close()
            return jsonify({
                'message': 'Cancellation window expired. Orders can only be cancelled within 5 minutes.'
            }), 400

    cursor.execute(
        "UPDATE `order` SET Status='Cancelled' WHERE OrderID=%s",
        (order_id,)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Order cancelled successfully.'})


@orders_bp.route('/<int:order_id>/accept', methods=['PATCH'])
def accept_quote(order_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    auto_confirm_expired_orders(conn, cursor)
    cursor.execute(
        "SELECT Status FROM `order` WHERE OrderID = %s",
        (order_id,)
    )
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404

    if row['Status'] != 'Quoted':
        cursor.close()
        conn.close()
        return jsonify({
            'message': f'Cannot accept. Status is {row["Status"]}, not Quoted.'
        }), 400

    cursor.execute(
        "UPDATE `order` SET Status='Confirmed' WHERE OrderID=%s",
        (order_id,)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Quote accepted. Order is now Confirmed.'})


@orders_bp.route('/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    """Soft-delete: archive the order instead of removing it."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_archive_schema(cursor)
    cursor.execute("SELECT 1 AS found FROM `order` WHERE OrderID = %s AND (IsArchived = 0 OR IsArchived IS NULL)", (order_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({'message': 'Order not found.'}), 404
    try:
        cursor.execute(
            "UPDATE `order` SET IsArchived = 1, ArchivedAt = NOW() WHERE OrderID = %s",
            (order_id,)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'message': str(e)}), 500
    cursor.close()
    conn.close()
    return jsonify({'message': 'Order archived.'})


@orders_bp.route('/archived', methods=['GET'])
def get_archived_orders():
    """Return archived orders scoped by role."""
    role = (request.args.get('role') or '').lower()
    customer_id = request.args.get('customer_id')

    if role not in ('admin', 'staff', 'customer'):
        return jsonify({'message': 'Access denied.'}), 403
    if role == 'customer' and not customer_id:
        return jsonify([])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_archive_schema(cursor)
    query = """
        SELECT o.*, c.FirstName, c.LastName,
               CONCAT(c.FirstName, ' ', c.LastName) AS CustomerName
        FROM `order` o
        JOIN customer c ON o.CustomerID = c.CustomerID
        WHERE o.IsArchived = 1
    """
    params = []
    if role == 'customer':
        query += " AND o.CustomerID = %s"
        params.append(customer_id)

    query += " ORDER BY o.ArchivedAt DESC"
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([serialize_order(row) for row in rows])


@orders_bp.route('/<int:order_id>/restore', methods=['PATCH'])
def restore_order(order_id):
    """Restore an archived order. Admin only."""
    data = request.get_json(silent=True) or {}
    role = (data.get('_role') or request.args.get('role') or '').lower()
    if role != 'admin':
        return jsonify({'message': 'Only admins can restore archived orders.'}), 403

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_archive_schema(cursor)
    cursor.execute("SELECT 1 FROM `order` WHERE OrderID = %s AND IsArchived = 1", (order_id,))
    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({'message': 'Archived order not found.'}), 404
    try:
        cursor.execute(
            "UPDATE `order` SET IsArchived = 0, ArchivedAt = NULL WHERE OrderID = %s",
            (order_id,)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        return jsonify({'message': str(e)}), 500
    cursor.close()
    conn.close()
    return jsonify({'message': 'Order restored successfully.'})
