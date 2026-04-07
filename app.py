from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
import mysql.connector
from datetime import datetime
import random
import string

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ----------------- MySQL Connection -----------------
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="aishu@567",
    database="bus_system"
)
cursor = db.cursor(dictionary=True)

# ----------------- Helper: Generate PNR -----------------
def generate_pnr():
    return 'PNR' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ----------------- Home Page -----------------
@app.route('/')
def index():
    return render_template('index.html')

# ----------------- Register -----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))
        cursor.execute("INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,'user')", (name, email, password))
        db.commit()
        flash("Registration successful! Login now.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

# ----------------- Login -----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        cursor.execute("SELECT * FROM users WHERE email=%s AND password=%s", (email, password))
        user = cursor.fetchone()
        if user:
            session['user_id'] = user['user_id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            flash(f"Welcome back, {user['name']}!", "success")
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password!", "danger")
            return redirect(url_for('login'))
    return render_template('login.html')

# ----------------- Logout -----------------
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for('index'))

# ----------------- Search Buses -----------------
@app.route('/search', methods=['POST'])
def search():
    source = request.form['source']
    destination = request.form['destination']
    travel_date = request.form.get('travel_date', '')
    query = """
        SELECT buses.bus_id, buses.bus_name, buses.departure_time, buses.seats,
               COUNT(bookings.booking_id) AS passengers_booked,
               routes.source, routes.destination, routes.distance
        FROM buses
        JOIN routes ON buses.route_id = routes.route_id
        LEFT JOIN bookings ON buses.bus_id = bookings.bus_id
        WHERE routes.source=%s AND routes.destination=%s
        GROUP BY buses.bus_id
    """
    cursor.execute(query, (source, destination))
    buses = cursor.fetchall()
    return render_template('search.html', buses=buses, source=source, destination=destination, travel_date=travel_date)

# ----------------- Book Bus (seat selection) -----------------
@app.route('/book/<int:bus_id>', methods=['GET', 'POST'])
def book(bus_id):
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))

    # Get bus details
    cursor.execute("""
        SELECT buses.*, routes.source, routes.destination, routes.distance
        FROM buses JOIN routes ON buses.route_id = routes.route_id
        WHERE buses.bus_id=%s
    """, (bus_id,))
    bus = cursor.fetchone()

    # Get booked seats
    cursor.execute("SELECT seat_number FROM bookings WHERE bus_id=%s", (bus_id,))
    booked_seats = [row['seat_number'] for row in cursor.fetchall()]

    if request.method == 'POST':
        seat_number = request.form['seat']
        cursor.execute("SELECT * FROM bookings WHERE bus_id=%s AND seat_number=%s", (bus_id, seat_number))
        if cursor.fetchone():
            flash("Seat already booked! Choose another.", "danger")
            return redirect(url_for('book', bus_id=bus_id))
        # Store booking intent in session for payment
        session['pending_booking'] = {
            'bus_id': bus_id,
            'seat_number': seat_number,
            'bus_name': bus['bus_name'],
            'source': bus['source'],
            'destination': bus['destination'],
            'departure_time': str(bus['departure_time']),
            'distance': bus.get('distance', 0)
        }
        return redirect(url_for('payment'))

    return render_template('booking.html', bus_id=bus_id, bus=bus, booked_seats=booked_seats)

# ----------------- Payment Page -----------------
@app.route('/payment', methods=['GET', 'POST'])
def payment():
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))
    pending = session.get('pending_booking')
    if not pending:
        flash("No pending booking found.", "warning")
        return redirect(url_for('index'))

    # Calculate fare (dummy: ₹2.5 per km, min ₹150)
    distance = pending.get('distance', 100)
    fare = max(150, int(float(distance) * 2.5))

    if request.method == 'POST':
        # Dummy payment processing — always succeeds
        payment_method = request.form.get('payment_method', 'card')
        pnr = generate_pnr()
        booking_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute(
            "INSERT INTO bookings(user_id,bus_id,seat_number,booking_date) VALUES(%s,%s,%s,%s)",
            (session['user_id'], pending['bus_id'], pending['seat_number'], booking_date)
        )
        db.commit()
        booking_id = cursor.lastrowid

        # Store confirmation in session for success page
        session['booking_confirm'] = {
            'booking_id': booking_id,
            'pnr': pnr,
            'bus_name': pending['bus_name'],
            'source': pending['source'],
            'destination': pending['destination'],
            'departure_time': pending['departure_time'],
            'seat_number': pending['seat_number'],
            'passenger_name': session['user_name'],
            'booking_date': booking_date,
            'fare': fare,
            'payment_method': payment_method
        }
        session.pop('pending_booking', None)
        return redirect(url_for('success'))

    return render_template('payment.html', pending=pending, fare=fare)

# ----------------- Booking Success -----------------
@app.route('/success')
def success():
    confirm = session.get('booking_confirm')
    if not confirm:
        return redirect(url_for('index'))
    return render_template('success.html', confirm=confirm)

# ----------------- Download Ticket PDF -----------------
@app.route('/download_ticket/<int:booking_id>')
def download_ticket(booking_id):
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))

    cursor.execute("""
        SELECT bookings.booking_id, bookings.seat_number, bookings.booking_date,
               users.name AS passenger_name, users.email,
               buses.bus_name, buses.departure_time,
               routes.source, routes.destination, routes.distance
        FROM bookings
        JOIN users ON bookings.user_id = users.user_id
        JOIN buses ON bookings.bus_id = buses.bus_id
        JOIN routes ON buses.route_id = routes.route_id
        WHERE bookings.booking_id=%s AND bookings.user_id=%s
    """, (booking_id, session['user_id']))
    booking = cursor.fetchone()
    if not booking:
        flash("Booking not found!", "danger")
        return redirect(url_for('my_bookings'))

    distance = booking.get('distance', 100)
    fare = max(150, int(float(distance) * 2.5))
    pnr = 'PNR' + str(booking_id).zfill(8)

    return render_template('ticket_pdf.html', booking=booking, fare=fare, pnr=pnr)

# ----------------- My Bookings -----------------
@app.route("/my_bookings")
def my_bookings():
    if "user_id" not in session:
        flash("Please login first!", "danger")
        return redirect(url_for("login"))
    user_id = session["user_id"]
    query = """
        SELECT bookings.booking_id, buses.bus_name, routes.source, routes.destination,
               buses.departure_time, bookings.seat_number, bookings.booking_date
        FROM bookings
        JOIN buses ON bookings.bus_id = buses.bus_id
        JOIN routes ON buses.route_id = routes.route_id
        WHERE bookings.user_id = %s
        ORDER BY bookings.booking_date DESC
    """
    cursor.execute(query, (user_id,))
    bookings = cursor.fetchall()
    return render_template("my_bookings.html", bookings=bookings)

# ----------------- Cancel Booking -----------------
@app.route('/cancel_booking/<int:booking_id>')
def cancel_booking(booking_id):
    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))
    cursor.execute("SELECT * FROM bookings WHERE booking_id=%s AND user_id=%s", (booking_id, session['user_id']))
    if not cursor.fetchone():
        flash("Booking not found or cannot cancel!", "danger")
        return redirect(url_for('my_bookings'))
    cursor.execute("DELETE FROM bookings WHERE booking_id=%s", (booking_id,))
    db.commit()
    flash("Booking cancelled successfully!", "success")
    return redirect(url_for('my_bookings'))

# ----------------- Admin Dashboard -----------------
@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        flash("Admin access required!", "danger")
        return redirect(url_for('login'))
    if request.method == 'POST':
        bus_name = request.form['bus_name']
        route_id = request.form['route_id']
        departure_time = request.form['departure_time']
        seats = request.form['seats']
        cursor.execute("INSERT INTO buses(bus_name,route_id,departure_time,seats) VALUES(%s,%s,%s,%s)",
                       (bus_name, route_id, departure_time, seats))
        db.commit()
        flash("Bus added successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    cursor.execute("""
        SELECT buses.bus_id, buses.bus_name, buses.departure_time, buses.seats,
               COUNT(bookings.booking_id) AS passengers_booked,
               routes.source, routes.destination
        FROM buses
        JOIN routes ON buses.route_id = routes.route_id
        LEFT JOIN bookings ON buses.bus_id = bookings.bus_id
        GROUP BY buses.bus_id
    """)
    buses = cursor.fetchall()
    cursor.execute("SELECT * FROM routes")
    routes = cursor.fetchall()

    # Stats for dashboard cards
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='user'")
    total_users = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM bookings")
    total_bookings = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM buses")
    total_buses = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM routes")
    total_routes = cursor.fetchone()['total']

    return render_template('admin_dashboard.html', buses=buses, routes=routes,
                           total_users=total_users, total_bookings=total_bookings,
                           total_buses=total_buses, total_routes=total_routes)

# ----------------- Admin Routes -----------------
@app.route('/admin/routes', methods=['GET', 'POST'])
def admin_routes():
    if 'role' not in session or session['role'] != 'admin':
        flash("Admin access required!", "danger")
        return redirect(url_for('login'))
    if request.method == 'POST':
        source = request.form['source']
        destination = request.form['destination']
        distance = request.form['distance']
        cursor.execute("INSERT INTO routes(source,destination,distance) VALUES(%s,%s,%s)", (source, destination, distance))
        db.commit()
        flash("Route added successfully!", "success")
        return redirect(url_for('admin_routes'))
    cursor.execute("SELECT * FROM routes")
    routes = cursor.fetchall()
    return render_template('admin_routes.html', routes=routes)

# ----------------- Admin All Bookings -----------------
@app.route('/admin/bookings')
def admin_bookings():
    if 'role' not in session or session['role'] != 'admin':
        flash("Admin access required!", "danger")
        return redirect(url_for('login'))
    cursor.execute("""
        SELECT bookings.booking_id, users.name AS user_name, buses.bus_name,
               routes.source, routes.destination, buses.departure_time,
               bookings.seat_number, bookings.booking_date
        FROM bookings
        JOIN users ON bookings.user_id = users.user_id
        JOIN buses ON bookings.bus_id = buses.bus_id
        JOIN routes ON buses.route_id = routes.route_id
        ORDER BY bookings.booking_date DESC
    """)
    bookings = cursor.fetchall()
    return render_template('admin_bookings.html', bookings=bookings)

# ----------------- Run App -----------------
if __name__ == '__main__':
    app.run(debug=True)
