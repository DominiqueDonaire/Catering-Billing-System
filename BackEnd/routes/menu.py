import os
from uuid import uuid4

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from db import get_connection

menu_bp = Blueprint('menu', __name__)

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'dishes')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
PACKAGE_CATEGORY = 'Package'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def normalize_image_path(image_path):
    if not image_path:
        return None

    normalized = str(image_path).replace('\\', '/').strip('/')
    if normalized.startswith('static/uploads/dishes/'):
        return normalized
    return f"static/uploads/dishes/{os.path.basename(normalized)}"


def save_image(file):
    if file and allowed_file(file.filename):
        name, ext = os.path.splitext(secure_filename(file.filename))
        unique_name = f'{name or "dish"}_{uuid4().hex}{ext.lower()}'
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(os.path.join(UPLOAD_FOLDER, unique_name))
        return normalize_image_path(unique_name)
    return None


def remove_saved_file(image_path):
    normalized = normalize_image_path(image_path)
    if not normalized:
        return
    full_path = os.path.abspath(normalized.replace('/', os.sep))
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
        except OSError:
            pass


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def table_has_column(cursor, table_name, column_name):
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    return cursor.fetchone() is not None


def first_existing_column(cursor, table_name, candidates):
    for candidate in candidates:
        if table_has_column(cursor, table_name, candidate):
            return candidate
    return None


def ensure_menu_schema(cursor):
    if not table_has_column(cursor, 'menuitem', 'pricing_type'):
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN pricing_type ENUM('per_pax', 'flat_rate')
            NOT NULL DEFAULT 'per_pax'
            AFTER Category
        """)

    if not table_has_column(cursor, 'menuitem', 'serves_up_to'):
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN serves_up_to INT NULL
            AFTER pricing_type
        """)

    if not table_has_column(cursor, 'menuitem', 'IsHalal'):
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN IsHalal TINYINT(1) NOT NULL DEFAULT 0
            AFTER serves_up_to
        """)

    if not table_has_column(cursor, 'menuitem', 'Available'):
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN Available TINYINT(1) NOT NULL DEFAULT 1
        """)

    if not table_has_column(cursor, 'menuitem', 'IsDeleted'):
        cursor.execute("""
            ALTER TABLE menuitem
            ADD COLUMN IsDeleted TINYINT(1) NOT NULL DEFAULT 0
            AFTER Available
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menuitem_photos (
            PhotoID INT NOT NULL AUTO_INCREMENT,
            ItemID INT NOT NULL,
            image_path VARCHAR(255) NULL,
            sort_order INT NOT NULL DEFAULT 1,
            PRIMARY KEY (PhotoID),
            KEY idx_menuitem_photos_item (ItemID),
            CONSTRAINT fk_menuitem_photos_item
                FOREIGN KEY (ItemID) REFERENCES menuitem(ItemID)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    if not table_has_column(cursor, 'menuitem_photos', 'sort_order'):
        cursor.execute("""
            ALTER TABLE menuitem_photos
            ADD COLUMN sort_order INT NOT NULL DEFAULT 1
        """)

    if not table_has_column(cursor, 'menuitem_photos', 'image_path'):
        cursor.execute("""
            ALTER TABLE menuitem_photos
            ADD COLUMN image_path VARCHAR(255) NULL
        """)

    if not table_has_column(cursor, 'menuitem_photos', 'ItemID'):
        cursor.execute("""
            ALTER TABLE menuitem_photos
            ADD COLUMN ItemID INT NULL
        """)

        legacy_fk_column = first_existing_column(cursor, 'menuitem_photos', (
            'MenuItemID', 'menuitem_id', 'item_id', 'itemid', 'DishID', 'dish_id', 'MenuID', 'menu_id'
        ))
        if legacy_fk_column:
            cursor.execute(f"""
                UPDATE menuitem_photos
                SET ItemID = {legacy_fk_column}
                WHERE ItemID IS NULL
            """)

    if not table_has_column(cursor, 'menuitem_photos', 'PhotoID'):
        legacy_photo_id = first_existing_column(cursor, 'menuitem_photos', (
            'MenuItemPhotoID', 'menuitem_photo_id', 'photo_id', 'id', 'ID'
        ))
        if legacy_photo_id and legacy_photo_id != 'PhotoID':
            pass

    legacy_image_column = first_existing_column(cursor, 'menuitem_photos', (
        'PhotoPath', 'photo_path', 'ImagePath', 'image', 'filename', 'file_path'
    ))
    if legacy_image_column and legacy_image_column != 'image_path':
        cursor.execute(f"""
            UPDATE menuitem_photos
            SET image_path = {legacy_image_column}
            WHERE (image_path IS NULL OR image_path = '')
              AND {legacy_image_column} IS NOT NULL
        """)

    legacy_sort_column = first_existing_column(cursor, 'menuitem_photos', (
        'photo_order', 'PhotoOrder', 'order_index', 'OrderIndex', 'display_order'
    ))
    if legacy_sort_column and legacy_sort_column != 'sort_order':
        cursor.execute(f"""
            UPDATE menuitem_photos
            SET sort_order = {legacy_sort_column}
            WHERE (sort_order IS NULL OR sort_order = 1)
              AND {legacy_sort_column} IS NOT NULL
        """)


def sanitize_menu_item(row):
    item = dict(row)
    item['image_path'] = normalize_image_path(item.get('image_path'))
    item['pricing_type'] = item.get('pricing_type') or 'per_pax'
    item['serves_up_to'] = item.get('serves_up_to')
    item['IsHalal'] = 1 if item.get('IsHalal') else 0
    item['Available'] = 0 if item.get('Available') == 0 else 1
    item['photos'] = sorted(item.get('photos') or [], key=lambda photo: photo.get('sort_order', 0))
    item['all_photos'] = [path for path in [item['image_path'], *[p['image_path'] for p in item['photos']]] if path]
    return item


def fetch_menu_items(cursor, where_clause='', params=()):
    normalized_where = (where_clause or '').strip()
    base_where = 'WHERE m.IsDeleted = 0'
    if normalized_where:
        if normalized_where.upper().startswith('WHERE '):
            where_sql = f"{base_where} AND ({normalized_where[6:]})"
        else:
            where_sql = f"{base_where} {normalized_where}"
    else:
        where_sql = base_where

    query = f"""
        SELECT m.*,
               COALESCE(stats.total_ordered, 0) AS total_ordered,
               COALESCE(stats.order_count, 0) AS order_count,
               COALESCE(stats.popularity_rank, 0) AS popularity_rank,
               p.image_path AS extra_image_path,
               p.sort_order
        FROM menuitem m
        LEFT JOIN (
            SELECT ranked.ItemID,
                   ranked.total_ordered,
                   ranked.order_count,
                   ranked.popularity_rank
            FROM (
                SELECT m2.ItemID,
                       COALESCE(SUM(CASE WHEN o.Status <> 'Cancelled' THEN om.Quantity ELSE 0 END), 0) AS total_ordered,
                       COALESCE(COUNT(DISTINCT CASE WHEN o.Status <> 'Cancelled' THEN om.OrderID END), 0) AS order_count,
                       DENSE_RANK() OVER (
                           ORDER BY COALESCE(SUM(CASE WHEN o.Status <> 'Cancelled' THEN om.Quantity ELSE 0 END), 0) DESC,
                                    m2.ItemID ASC
                       ) AS popularity_rank
                FROM menuitem m2
                LEFT JOIN order_menu om ON om.ItemID = m2.ItemID
                LEFT JOIN `order` o ON o.OrderID = om.OrderID
                GROUP BY m2.ItemID
            ) ranked
        ) stats ON stats.ItemID = m.ItemID
        LEFT JOIN menuitem_photos p ON p.ItemID = m.ItemID
        {where_sql}
        ORDER BY m.ItemID ASC, p.sort_order ASC, p.image_path ASC
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    items = {}
    for row in rows:
        item_id = row['ItemID']
        if item_id not in items:
            item = dict(row)
            item['photos'] = []
            items[item_id] = item
        if row.get('extra_image_path'):
            items[item_id]['photos'].append({
                'image_path': normalize_image_path(row['extra_image_path']),
                'sort_order': row.get('sort_order') or 0
            })
    return [sanitize_menu_item(item) for item in items.values()]


def parse_menu_payload():
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = request.form
    else:
        data = request.get_json(silent=True) or {}

    payload = {
        'ItemName': (data.get('ItemName') or '').strip(),
        'Category': (data.get('Category') or '').strip(),
        'PricePerPax': data.get('PricePerPax'),
        'Description': (data.get('Description') or '').strip(),
        'pricing_type': (data.get('pricing_type') or 'per_pax').strip(),
        'serves_up_to': data.get('serves_up_to'),
        'IsHalal': 1 if as_bool(data.get('IsHalal')) else 0,
        'Available': 0 if not as_bool(data.get('Available'), default=True) else 1,
    }
    return payload


def validate_menu_payload(payload):
    if not payload['ItemName'] or not payload['Category'] or payload['PricePerPax'] in (None, ''):
        return 'ItemName, Category, and PricePerPax are required.'

    try:
        payload['PricePerPax'] = float(payload['PricePerPax'])
    except (TypeError, ValueError):
        return 'PricePerPax must be a valid number.'

    if payload['PricePerPax'] < 0:
        return 'PricePerPax must be zero or greater.'

    if payload['pricing_type'] not in ('per_pax', 'flat_rate'):
        payload['pricing_type'] = 'per_pax'

    if payload['pricing_type'] == 'flat_rate':
        if payload['serves_up_to'] in (None, ''):
            return 'serves_up_to is required for flat rate items.'
        try:
            payload['serves_up_to'] = int(payload['serves_up_to'])
        except (TypeError, ValueError):
            return 'serves_up_to must be a whole number.'
        if payload['serves_up_to'] < 1:
            return 'serves_up_to must be at least 1.'
    else:
        payload['serves_up_to'] = None

    return None


def replace_package_photos(cursor, item_id, cover_path, existing_item):
    remove_cover = as_bool(request.form.get('remove_cover_image'))
    category = (request.form.get('Category') or existing_item.get('Category') or '').strip()
    keep_package = category == PACKAGE_CATEGORY

    new_cover_path = cover_path or existing_item.get('image_path')
    if remove_cover and not cover_path:
        remove_saved_file(existing_item.get('image_path'))
        new_cover_path = None

    extra_rows = existing_item.get('photos') or []
    extra_map = {str(photo['sort_order']): photo for photo in extra_rows}
    replacements = []

    if keep_package:
        for sort_order in range(1, 5):
            remove_flag = as_bool(request.form.get(f'remove_photo_{sort_order}'))
            upload = request.files.get(f'image_{sort_order + 1}')
            existing = extra_map.get(str(sort_order))

            if upload:
                new_path = save_image(upload)
                if existing and existing.get('image_path'):
                    remove_saved_file(existing['image_path'])
                if new_path:
                    replacements.append((item_id, new_path, sort_order))
            elif remove_flag:
                if existing and existing.get('image_path'):
                    remove_saved_file(existing['image_path'])
            elif existing:
                replacements.append((item_id, existing.get('image_path'), sort_order))
    else:
        if existing_item.get('Category') == PACKAGE_CATEGORY:
            for photo in extra_rows:
                remove_saved_file(photo.get('image_path'))

    cursor.execute("DELETE FROM menuitem_photos WHERE ItemID = %s", (item_id,))
    if replacements:
        cursor.executemany("""
            INSERT INTO menuitem_photos (ItemID, image_path, sort_order)
            VALUES (%s, %s, %s)
        """, replacements)

    return new_cover_path


@menu_bp.route('/menu', methods=['GET'])
@menu_bp.route('/menu-items', methods=['GET'])
def get_menu():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    items = fetch_menu_items(cursor)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify(items)


@menu_bp.route('/menu/<int:item_id>', methods=['GET'])
@menu_bp.route('/menu-items/<int:item_id>', methods=['GET'])
def get_menu_item(item_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    items = fetch_menu_items(cursor, 'WHERE m.ItemID = %s', (item_id,))
    conn.commit()
    cursor.close()
    conn.close()
    if not items:
        return jsonify({'message': 'Menu item not found.'}), 404
    return jsonify(items[0])


@menu_bp.route('/menu', methods=['POST'])
@menu_bp.route('/menu-items', methods=['POST'])
def add_menu():
    payload = parse_menu_payload()
    error = validate_menu_payload(payload)
    if error:
        return jsonify({'message': error}), 400

    cover_path = save_image(request.files.get('image') or request.files.get('image_1'))

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    cursor.execute("""
        INSERT INTO menuitem (
            ItemName, Category, pricing_type, serves_up_to, PricePerPax,
            Description, image_path, IsHalal, Available
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        payload['ItemName'],
        payload['Category'],
        payload['pricing_type'],
        payload['serves_up_to'],
        payload['PricePerPax'],
        payload['Description'],
        cover_path,
        payload['IsHalal'],
        payload['Available'],
    ))
    item_id = cursor.lastrowid

    if payload['Category'] == PACKAGE_CATEGORY:
        photo_rows = []
        for sort_order in range(1, 5):
            image_path = save_image(request.files.get(f'image_{sort_order + 1}'))
            if image_path:
                photo_rows.append((item_id, image_path, sort_order))
        if photo_rows:
            cursor.executemany("""
                INSERT INTO menuitem_photos (ItemID, image_path, sort_order)
                VALUES (%s, %s, %s)
            """, photo_rows)

    conn.commit()
    fresh = fetch_menu_items(cursor, 'WHERE m.ItemID = %s', (item_id,))
    cursor.close()
    conn.close()
    return jsonify({
        'message': 'Menu item added!',
        'item': fresh[0] if fresh else None
    }), 201


@menu_bp.route('/menu/<int:item_id>', methods=['PUT'])
@menu_bp.route('/menu-items/<int:item_id>', methods=['PUT'])
def update_menu(item_id):
    payload = parse_menu_payload()
    error = validate_menu_payload(payload)
    if error:
        return jsonify({'message': error}), 400

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    existing_items = fetch_menu_items(cursor, 'WHERE m.ItemID = %s', (item_id,))
    if not existing_items:
        cursor.close()
        conn.close()
        return jsonify({'message': 'Menu item not found.'}), 404

    existing_item = existing_items[0]
    uploaded_cover = save_image(request.files.get('image') or request.files.get('image_1'))
    if uploaded_cover and existing_item.get('image_path'):
        remove_saved_file(existing_item['image_path'])

    final_cover = uploaded_cover or existing_item.get('image_path')
    if request.content_type and 'multipart/form-data' in request.content_type:
        final_cover = replace_package_photos(cursor, item_id, uploaded_cover, existing_item)
    elif payload['Category'] != PACKAGE_CATEGORY and existing_item.get('Category') == PACKAGE_CATEGORY:
        for photo in existing_item.get('photos') or []:
            remove_saved_file(photo.get('image_path'))
        cursor.execute("DELETE FROM menuitem_photos WHERE ItemID = %s", (item_id,))

    cursor.execute("""
        UPDATE menuitem
        SET ItemName = %s,
            Category = %s,
            pricing_type = %s,
            serves_up_to = %s,
            PricePerPax = %s,
            Description = %s,
            image_path = %s,
            IsHalal = %s,
            Available = %s
        WHERE ItemID = %s
    """, (
        payload['ItemName'],
        payload['Category'],
        payload['pricing_type'],
        payload['serves_up_to'],
        payload['PricePerPax'],
        payload['Description'],
        final_cover,
        payload['IsHalal'],
        payload['Available'],
        item_id,
    ))

    conn.commit()
    fresh = fetch_menu_items(cursor, 'WHERE m.ItemID = %s', (item_id,))
    cursor.close()
    conn.close()
    return jsonify({
        'message': 'Menu item updated!',
        'item': fresh[0] if fresh else None
    })


@menu_bp.route('/menu/<int:item_id>/availability', methods=['PATCH'])
def toggle_availability(item_id):
    data = request.get_json(silent=True) or {}
    available = 1 if as_bool(data.get('Available')) else 0
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    cursor.execute(
        "UPDATE menuitem SET Available = %s WHERE ItemID = %s",
        (available, item_id)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Availability updated!', 'Available': available})


@menu_bp.route('/menu/<int:item_id>', methods=['DELETE'])
@menu_bp.route('/menu-items/<int:item_id>', methods=['DELETE'])
def delete_menu(item_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        ensure_menu_schema(cursor)
        existing = fetch_menu_items(cursor, 'WHERE m.ItemID = %s', (item_id,))
        if not existing:
            return jsonify({'message': 'Menu item not found.'}), 404

        cursor.execute(
            "SELECT COUNT(*) AS usage_count FROM order_menu WHERE ItemID = %s",
            (item_id,)
        )
        usage_row = cursor.fetchone() or {}
        usage_count = int(usage_row.get('usage_count') or 0)
        item = existing[0]
        if usage_count > 0:
            # Keep historical order references intact by soft-deleting used dishes.
            cursor.execute("""
                UPDATE menuitem
                SET IsDeleted = 1,
                    Available = 0
                WHERE ItemID = %s
            """, (item_id,))
            conn.commit()
            return jsonify({
                'message': 'Menu item removed from active menu.',
                'soft_deleted': True
            })

        cursor.execute("DELETE FROM menuitem_photos WHERE ItemID = %s", (item_id,))
        cursor.execute("DELETE FROM menuitem WHERE ItemID = %s", (item_id,))
        conn.commit()

        remove_saved_file(item.get('image_path'))
        for photo in item.get('photos') or []:
            remove_saved_file(photo.get('image_path'))

        return jsonify({
            'message': 'Menu item deleted!',
            'soft_deleted': False
        })
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@menu_bp.route('/menu/count', methods=['GET'])
def count_menu():
    conn = get_connection()
    cursor = conn.cursor()
    ensure_menu_schema(cursor)
    cursor.execute("SELECT COUNT(*) FROM menuitem WHERE IsDeleted = 0")
    count = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'count': count})


@menu_bp.route('/menu/popular', methods=['GET'])
@menu_bp.route('/menu-items/top3', methods=['GET'])
def popular_dishes():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    ensure_menu_schema(cursor)
    items = fetch_menu_items(cursor)
    ordered = [
        item for item in sorted(
            items,
            key=lambda item: (-int(item.get('total_ordered') or 0), item['ItemID'])
        )
        if int(item.get('total_ordered') or 0) > 0
    ][:3]
    cursor.close()
    conn.close()
    return jsonify(ordered)
