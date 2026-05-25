Catering Billing System
A comprehensive web-based catering management and billing system built with Flask and MySQL. Designed to streamline order management, customer tracking, menu planning, and payment processing for catering businesses.

Features
  Authentication & Authorization
  Role-based access control (Admin, Staff, Customer)
  Secure user registration and login
  Customer account management
  Admin/Staff account creation and management

Customer Management
  Customer profile creation and updates
  Contact information tracking
  Order history and customer details

Menu Management
  Digital menu with dish listings
  Flexible pricing options (per pax or flat rate pricing)
  Dish images with upload capability
  Category-based organization

Order Management
  Create, view, and manage catering orders
  Event date scheduling with minimum 3-day lead time
  Multiple order statuses (Pending, Confirmed, Completed, Cancelled)
  5-minute cancellation window for pending orders
  Dynamic pricing calculations

Payment Processing
  Multiple payment methods (Cash, GCash, Maya, Bank Transfer, Credit Card)
  Payment tracking and balance calculations
  Payment history management
  Order reconciliation

File Management
  Dish image upload functionality
  Organized file storage system
  5MB upload limit per file


Tech Stack
Backend:
	Python 3.x
	Flask (Web Framework)
	Flask-CORS (Cross-Origin Resource Sharing)
	MySQL (Database)
	Werkzeug (Password hashing)

Frontend:
	HTML5
	CSS3
	JavaScript (ES6+)

Responsive design
   Database:
   MySQL with role-based access tables
   Structured schema for customers, orders, payments, and menu items

The API will be available at http://localhost:5000
API Endpoints

Authentication:
POST /register - Customer registration
POST /login - User login
Customers:

GET /customers - List all customers
GET /customers/<id> - Get customer details
POST /customers - Add new customer
Menu:

GET /menu - List all menu items
POST /menu - Add menu item
Orders:

GET /orders - List orders
POST /orders - Create new order
PATCH /orders/<id> - Update order status
Payments:

GET /payments - List payments
POST /payments - Record payment
GET /payments/<order_id> - Get payment by order
