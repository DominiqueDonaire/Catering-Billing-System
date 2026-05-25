import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from auth import auth_bp
from routes.customer import customer_bp
from routes.menu import menu_bp
from routes.orders import orders_bp
from routes.payments import payments_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
UPLOAD_DIR = os.path.join(STATIC_DIR, 'uploads', 'dishes')

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='/static')
CORS(app, supports_credentials=True)

# ── Image Upload Config ──────────────────────────────────────────
app.config['UPLOAD_FOLDER']      = UPLOAD_DIR
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max per upload

# Make sure the upload folder exists when the app starts
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Serve uploaded dish images  e.g. GET /static/uploads/dishes/adobo.jpg
@app.route('/static/uploads/dishes/<filename>')
def uploaded_dish_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ── Blueprints ───────────────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(customer_bp)
app.register_blueprint(menu_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(payments_bp)

@app.route('/')
def home():
    return "Catering System API is running!"

if __name__ == '__main__':
    app.run(debug=True)
