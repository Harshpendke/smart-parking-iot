from flask import Flask, jsonify, render_template, request, session, redirect, url_for
import serial
import threading
import sqlite3
from datetime import datetime
import time
import math
import os
import hashlib
import razorpay

app = Flask(__name__)

# ==========================================
# ADMIN LOGIN SETTINGS
# ==========================================

app.secret_key = "smart_parking_admin_secret_key"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


# ==========================================
# ESP32 SETTINGS
# ==========================================

PORT = "COM15"
BAUD_RATE = 115200


# ==========================================
# DATABASE
# ==========================================

DATABASE = "parking.db"


# ==========================================
# RAZORPAY SETTINGS
# ==========================================

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = None

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:

    razorpay_client = razorpay.Client(
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET
        )
    )


# ==========================================
# PARKING FEE
# ==========================================

FIRST_HOUR_RATE = 20
ADDITIONAL_HOUR_RATE = 10


# ==========================================
# CURRENT PARKING STATUS
# ==========================================

parking_status = {
    "slot1": "EMPTY",
    "slot2": "EMPTY",
    "slot3": "EMPTY"
}


# ==========================================
# ACTIVE PARKING SESSIONS
# ==========================================

active_sessions = {
    "slot1": None,
    "slot2": None,
    "slot3": None
}


# ==========================================
# SESSION STATISTICS
# ==========================================

session_statistics = {
    "total_events": 0,
    "last_update": "No events yet"
}


# ==========================================
# INITIALIZE DATABASE
# ==========================================

def init_database():

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # --------------------------------------
    # PARKING STATUS HISTORY
    # --------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parking_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot1 TEXT NOT NULL,
            slot2 TEXT NOT NULL,
            slot3 TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)


    # --------------------------------------
    # NORMAL PARKING SESSIONS
    # --------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parking_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            duration_seconds INTEGER,
            amount REAL,
            payment_status TEXT DEFAULT 'PENDING',
            transaction_id TEXT,
            payment_time TEXT,
            razorpay_order_id TEXT
        )
    """)


    # --------------------------------------
    # ADD MISSING COLUMNS TO OLD DATABASE
    # --------------------------------------

    cursor.execute("""
        PRAGMA table_info(parking_sessions)
    """)

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]


    if "transaction_id" not in columns:

        cursor.execute("""
            ALTER TABLE parking_sessions
            ADD COLUMN transaction_id TEXT
        """)


    if "payment_time" not in columns:

        cursor.execute("""
            ALTER TABLE parking_sessions
            ADD COLUMN payment_time TEXT
        """)


    if "razorpay_order_id" not in columns:

        cursor.execute("""
            ALTER TABLE parking_sessions
            ADD COLUMN razorpay_order_id TEXT
        """)


    # ======================================
    # USERS TABLE
    # ======================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


    # ======================================
    # RESERVATIONS TABLE
    # ======================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            slot TEXT NOT NULL,

            reservation_start TEXT NOT NULL,

            reservation_end TEXT NOT NULL,

            status TEXT DEFAULT 'RESERVED',

            entry_time TEXT,

            exit_time TEXT,

            duration_seconds INTEGER,

            amount REAL,

            payment_status TEXT DEFAULT 'PENDING',

            payment_method TEXT,

            transaction_id TEXT,

            payment_time TEXT,

            razorpay_order_id TEXT,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
        )
    """)


    # --------------------------------------
    # ADD MISSING RESERVATION PAYMENT COLUMN
    # --------------------------------------

    cursor.execute("""
        PRAGMA table_info(reservations)
    """)

    reservation_columns = [
        row[1]
        for row in cursor.fetchall()
    ]


    if "razorpay_order_id" not in reservation_columns:

        cursor.execute("""
            ALTER TABLE reservations
            ADD COLUMN razorpay_order_id TEXT
        """)


    conn.commit()

    conn.close()

    print("Database ready.")


# ==========================================
# SAVE STATUS HISTORY
# ==========================================

def save_status(status):

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO parking_logs
        (slot1, slot2, slot3, timestamp)
        VALUES (?, ?, ?, ?)
    """, (
        status["slot1"],
        status["slot2"],
        status["slot3"],
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    ))

    conn.commit()

    conn.close()


# ==========================================
# START NORMAL PARKING SESSION
# ==========================================

def start_parking_session(slot):

    entry_time = datetime.now()

    active_sessions[slot] = entry_time

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO parking_sessions
        (slot, entry_time, payment_status)
        VALUES (?, ?, ?)
    """, (
        slot,
        entry_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "PENDING"
    ))

    conn.commit()

    conn.close()

    print()
    print("===================================")
    print(slot.upper(), "- VEHICLE ENTERED")
    print(
        "Entry Time:",
        entry_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    print("===================================")
    print()


# ==========================================
# CALCULATE PARKING FEE
# ==========================================

def calculate_parking_fee(duration_seconds):

    if duration_seconds <= 3600:

        billable_hours = 1

        amount = FIRST_HOUR_RATE

    else:

        additional_seconds = (
            duration_seconds - 3600
        )

        additional_hours = math.ceil(
            additional_seconds / 3600
        )

        billable_hours = (
            1 + additional_hours
        )

        amount = (
            FIRST_HOUR_RATE
            +
            additional_hours *
            ADDITIONAL_HOUR_RATE
        )

    return amount, billable_hours


# ==========================================
# END NORMAL PARKING SESSION
# ==========================================

def end_parking_session(slot):

    entry_time = active_sessions.get(slot)

    if entry_time is None:

        print(
            "No active session found for",
            slot
        )

        return

    exit_time = datetime.now()

    duration = (
        exit_time - entry_time
    ).total_seconds()

    duration_seconds = int(
        duration
    )

    amount, billable_hours = (
        calculate_parking_fee(
            duration_seconds
        )
    )


    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE parking_sessions
        SET
            exit_time = ?,
            duration_seconds = ?,
            amount = ?
        WHERE id = (
            SELECT id
            FROM parking_sessions
            WHERE slot = ?
            AND exit_time IS NULL
            ORDER BY id DESC
            LIMIT 1
        )
    """, (
        exit_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        duration_seconds,
        amount,
        slot
    ))

    conn.commit()

    conn.close()

    active_sessions[slot] = None


    hours = duration_seconds // 3600

    minutes = (
        duration_seconds % 3600
    ) // 60

    seconds = (
        duration_seconds % 60
    )


    print()
    print("===================================")
    print(
        slot.upper(),
        "- VEHICLE EXITED"
    )

    print(
        "Exit Time:",
        exit_time.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "Duration:",
        hours,
        "hours",
        minutes,
        "minutes",
        seconds,
        "seconds"
    )

    print(
        "Billable Hours:",
        billable_hours
    )

    print(
        "First Hour Rate: ₹",
        FIRST_HOUR_RATE
    )

    print(
        "Additional Hour Rate: ₹",
        ADDITIONAL_HOUR_RATE
    )

    print(
        "Parking Amount: ₹",
        amount
    )

    print(
        "Payment Status: PENDING"
    )

    print("===================================")
    print()


# ==========================================
# USER AUTHENTICATION HELPERS
# ==========================================

def hash_user_password(password):
    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()


def get_user_by_email(email):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            name,
            email,
            password,
            created_at
        FROM users
        WHERE LOWER(email) = LOWER(?)
    """, (email,))

    user = cursor.fetchone()
    conn.close()

    return user


# ==========================================
# USER REGISTRATION
# ==========================================

@app.route(
    "/user-register",
    methods=["POST"]
)
def user_register():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({
                "success": False,
                "message":
                    "Registration data is missing."
            }), 400

        name = str(
            data.get("name", "")
        ).strip()

        email = str(
            data.get("email", "")
        ).strip().lower()

        password = str(
            data.get("password", "")
        )

        if not name:

            return jsonify({
                "success": False,
                "message":
                    "Name is required."
            }), 400

        if not email:

            return jsonify({
                "success": False,
                "message":
                    "Email is required."
            }), 400

        if "@" not in email or "." not in email:

            return jsonify({
                "success": False,
                "message":
                    "Please enter a valid email address."
            }), 400

        if len(password) < 6:

            return jsonify({
                "success": False,
                "message":
                    "Password must be at least 6 characters."
            }), 400

        existing_user = get_user_by_email(
            email
        )

        if existing_user:

            return jsonify({
                "success": False,
                "message":
                    "An account with this email already exists."
            }), 409

        created_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        password_hash = hash_user_password(
            password
        )

        conn = sqlite3.connect(
            DATABASE
        )

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO users
            (
                name,
                email,
                password,
                created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            name,
            email,
            password_hash,
            created_at
        ))

        user_id = cursor.lastrowid

        conn.commit()
        conn.close()

        return jsonify({

            "success": True,

            "message":
                "User account created successfully.",

            "user": {
                "id": user_id,
                "name": name,
                "email": email
            }

        }), 201

    except Exception as e:

        print(
            "USER REGISTRATION ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "message":
                "Unable to create user account."
        }), 500


# ==========================================
# USER LOGIN
# ==========================================

@app.route(
    "/user-login",
    methods=["POST"]
)
def user_login():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({
                "success": False,
                "message":
                    "Login data is missing."
            }), 400

        email = str(
            data.get("email", "")
        ).strip().lower()

        password = str(
            data.get("password", "")
        )

        if not email or not password:

            return jsonify({
                "success": False,
                "message":
                    "Email and password are required."
            }), 400

        user = get_user_by_email(
            email
        )

        if user is None:

            return jsonify({
                "success": False,
                "message":
                    "Invalid email or password."
            }), 401

        password_hash = hash_user_password(
            password
        )

        if password_hash != user["password"]:

            return jsonify({
                "success": False,
                "message":
                    "Invalid email or password."
            }), 401

        session["user_logged_in"] = True

        session["user_id"] = user["id"]

        session["user_name"] = user["name"]

        session["user_email"] = user["email"]

        return jsonify({

            "success": True,

            "message":
                "Login successful.",

            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"]
            }

        })

    except Exception as e:

        print(
            "USER LOGIN ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "message":
                "Unable to login."
        }), 500


# ==========================================
# CURRENT USER SESSION
# ==========================================

@app.route("/user-session")
def user_session():

    if not session.get(
        "user_logged_in"
    ):

        return jsonify({

            "logged_in": False

        })

    return jsonify({

        "logged_in": True,

        "user": {

            "id":
                session.get("user_id"),

            "name":
                session.get("user_name"),

            "email":
                session.get("user_email")

        }

    })


# ==========================================
# USER LOGOUT
# ==========================================

@app.route("/user-logout")
def user_logout():

    session.pop(
        "user_logged_in",
        None
    )

    session.pop(
        "user_id",
        None
    )

    session.pop(
        "user_name",
        None
    )

    session.pop(
        "user_email",
        None
    )

    return jsonify({

        "success": True,

        "message":
            "User logged out successfully."

    })


# ==========================================
# ADMIN LOGIN
# ==========================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if session.get(
        "admin_logged_in"
    ):

        return redirect(
            url_for("home")
        )


    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )


        if (
            username == ADMIN_USERNAME
            and
            password == ADMIN_PASSWORD
        ):

            session[
                "admin_logged_in"
            ] = True

            session[
                "admin_username"
            ] = username

            return redirect(
                url_for("home")
            )


        return render_template(
            "login.html",
            error="Invalid username or password."
        )


    return render_template(
        "login.html"
    )


# ==========================================
# ADMIN LOGOUT
# ==========================================

@app.route("/logout")
def logout():

    session.pop(
        "admin_logged_in",
        None
    )

    session.pop(
        "admin_username",
        None
    )

    return redirect(
        url_for("login")
    )


# ==========================================
# ADMIN HOME
# ==========================================

@app.route("/")
def home():

    if not session.get(
        "admin_logged_in"
    ):

        return redirect(
            url_for("login")
        )

    return render_template(
        "index.html"
    )


# ==========================================
# USER DASHBOARD
# ==========================================

@app.route("/user")
def user_dashboard():

    return render_template(
        "user.html"
    )


# ==========================================
# CREATE RAZORPAY ORDER
# ==========================================

@app.route(
    "/create-order",
    methods=["POST"]
)
def create_order():

    if not RAZORPAY_KEY_ID:

        return jsonify({
            "success": False,
            "message":
                "Razorpay Key ID is not configured."
        }), 500


    if not RAZORPAY_KEY_SECRET:

        return jsonify({
            "success": False,
            "message":
                "Razorpay Secret Key is not configured."
        }), 500


    if razorpay_client is None:

        return jsonify({
            "success": False,
            "message":
                "Razorpay client is not initialized."
        }), 500


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({
            "success": False,
            "message":
                "Request data is missing."
        }), 400


    session_id = data.get(
        "session_id"
    )


    if not session_id:

        return jsonify({
            "success": False,
            "message":
                "Session ID is required."
        }), 400


    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            slot,
            entry_time,
            exit_time,
            duration_seconds,
            amount,
            payment_status,
            razorpay_order_id
        FROM parking_sessions
        WHERE id = ?
    """, (
        session_id,
    ))


    session_record = (
        cursor.fetchone()
    )


    if session_record is None:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Parking session not found."
        }), 404


    if not session_record["exit_time"]:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Vehicle has not exited yet."
        }), 400


    if (
        session_record["payment_status"]
        == "PAID"
    ):

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Payment already completed."
        }), 400


    if session_record["amount"] is None:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Parking amount is not available yet."
        }), 400


    amount_rupees = float(
        session_record["amount"]
    )

    amount_paise = int(
        round(
            amount_rupees * 100
        )
    )


    if amount_paise <= 0:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Invalid payment amount."
        }), 400


    try:

        order_data = {

            "amount":
                amount_paise,

            "currency":
                "INR",

            "receipt":
                "parking_"
                +
                str(
                    session_record["id"]
                )
                +
                "_"
                +
                str(
                    int(time.time())
                ),

            "notes": {

                "parking_session_id":
                    str(
                        session_record["id"]
                    ),

                "slot":
                    session_record["slot"]
            }
        }


        razorpay_order = (
            razorpay_client.order.create(
                data=order_data
            )
        )


        razorpay_order_id = (
            razorpay_order["id"]
        )


        cursor.execute("""
            UPDATE parking_sessions
            SET razorpay_order_id = ?
            WHERE id = ?
        """, (
            razorpay_order_id,
            session_record["id"]
        ))


        conn.commit()

        conn.close()


        return jsonify({

            "success":
                True,

            "key_id":
                RAZORPAY_KEY_ID,

            "order_id":
                razorpay_order_id,

            "session_id":
                session_record["id"],

            "amount":
                amount_paise,

            "amount_rupees":
                amount_rupees,

            "currency":
                "INR"
        })


    except Exception as e:

        conn.close()

        print(
            "RAZORPAY ORDER ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "message":
                "Unable to create Razorpay order.",

            "error":
                str(e)

        }), 500


# ==========================================
# VERIFY RAZORPAY PAYMENT
# ==========================================

@app.route(
    "/verify-payment",
    methods=["POST"]
)
def verify_payment():

    if razorpay_client is None:

        return jsonify({
            "success": False,
            "message":
                "Razorpay is not configured."
        }), 500


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({
            "success": False,
            "message":
                "Payment data is missing."
        }), 400


    session_id = data.get(
        "session_id"
    )

    razorpay_payment_id = data.get(
        "razorpay_payment_id"
    )

    razorpay_order_id = data.get(
        "razorpay_order_id"
    )

    razorpay_signature = data.get(
        "razorpay_signature"
    )


    if not session_id:

        return jsonify({
            "success": False,
            "message":
                "Session ID is required."
        }), 400


    if not razorpay_payment_id:

        return jsonify({
            "success": False,
            "message":
                "Razorpay payment ID is missing."
        }), 400


    if not razorpay_order_id:

        return jsonify({
            "success": False,
            "message":
                "Razorpay order ID is missing."
        }), 400


    if not razorpay_signature:

        return jsonify({
            "success": False,
            "message":
                "Razorpay signature is missing."
        }), 400


    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            amount,
            payment_status,
            razorpay_order_id
        FROM parking_sessions
        WHERE id = ?
    """, (
        session_id,
    ))


    session_record = (
        cursor.fetchone()
    )


    if session_record is None:

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Parking session not found."
        }), 404


    if (
        session_record["payment_status"]
        == "PAID"
    ):

        conn.close()

        return jsonify({
            "success": True,
            "message":
                "Payment was already completed."
        })


    if (
        session_record["razorpay_order_id"]
        and
        session_record["razorpay_order_id"]
        != razorpay_order_id
    ):

        conn.close()

        return jsonify({
            "success": False,
            "message":
                "Razorpay order ID does not match."
        }), 400


    try:

        verification_data = {

            "razorpay_order_id":
                razorpay_order_id,

            "razorpay_payment_id":
                razorpay_payment_id,

            "razorpay_signature":
                razorpay_signature
        }


        razorpay_client.utility.verify_payment_signature(
            verification_data
        )


    except Exception as e:

        conn.close()

        return jsonify({

            "success":
                False,

            "message":
                "Payment verification failed.",

            "error":
                str(e)

        }), 400


    payment_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    cursor.execute("""
        UPDATE parking_sessions
        SET
            payment_status = ?,
            transaction_id = ?,
            payment_time = ?,
            razorpay_order_id = ?
        WHERE id = ?
    """, (
        "PAID",
        razorpay_payment_id,
        payment_time,
        razorpay_order_id,
        session_id
    ))


    conn.commit()

    conn.close()


    return jsonify({

        "success":
            True,

        "message":
            "Payment verified successfully.",

        "session_id":
            session_id,

        "transaction_id":
            razorpay_payment_id,

        "payment_time":
            payment_time,

        "payment_status":
            "PAID"
    })


# ==========================================
# CASH PAYMENT
# ==========================================

@app.route(
    "/cash-payment",
    methods=["POST"]
)
def cash_payment():

    try:

        data = request.get_json()

        session_id = data.get(
            "session_id"
        )


        if not session_id:

            return jsonify({
                "error":
                    "Session ID is required"
            }), 400


        conn = sqlite3.connect(
            DATABASE
        )

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                id,
                amount,
                exit_time,
                payment_status
            FROM parking_sessions
            WHERE id = ?
        """, (
            session_id,
        ))


        session_record = (
            cursor.fetchone()
        )


        if not session_record:

            conn.close()

            return jsonify({
                "error":
                    "Parking session not found"
            }), 404


        (
            session_id_db,
            amount,
            exit_time,
            payment_status
        ) = session_record


        if not exit_time:

            conn.close()

            return jsonify({
                "error":
                    "Vehicle has not exited yet"
            }), 400


        if payment_status == "PAID":

            conn.close()

            return jsonify({
                "error":
                    "Payment already completed"
            }), 400


        payment_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )


        cursor.execute("""
            UPDATE parking_sessions
            SET
                payment_status = 'PAID',
                transaction_id = 'CASH',
                payment_time = ?
            WHERE id = ?
        """, (
            payment_time,
            session_id
        ))


        conn.commit()

        conn.close()


        return jsonify({

            "success":
                True,

            "message":
                "Cash payment recorded",

            "transaction_id":
                "CASH",

            "payment_time":
                payment_time
        })


    except Exception as e:

        print(
            "CASH PAYMENT ERROR:",
            e
        )

        return jsonify({
            "error":
                str(e)
        }), 500


# ==========================================
# CURRENT STATUS API
# ==========================================

@app.route("/status")
def status():

    return jsonify(
        parking_status
    )


# ==========================================
# HISTORY API
# ==========================================

@app.route("/history")
def history():

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            slot1,
            slot2,
            slot3,
            timestamp
        FROM parking_logs
        ORDER BY id DESC
        LIMIT 20
    """)


    records = cursor.fetchall()

    conn.close()


    history_data = []


    for record in records:

        history_data.append({

            "id":
                record["id"],

            "slot1":
                record["slot1"],

            "slot2":
                record["slot2"],

            "slot3":
                record["slot3"],

            "timestamp":
                record["timestamp"]
        })


    return jsonify(
        history_data
    )


# ==========================================
# PARKING SESSION API
# ==========================================

@app.route("/sessions")
def sessions():

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            id,
            slot,
            entry_time,
            exit_time,
            duration_seconds,
            amount,
            payment_status,
            transaction_id,
            payment_time,
            razorpay_order_id
        FROM parking_sessions
        ORDER BY id DESC
        LIMIT 10
    """)


    records = cursor.fetchall()

    conn.close()


    session_data = []


    for record in records:

        session_data.append({

            "id":
                record["id"],

            "slot":
                record["slot"],

            "entry_time":
                record["entry_time"],

            "exit_time":
                record["exit_time"],

            "duration_seconds":
                record["duration_seconds"],

            "amount":
                record["amount"],

            "payment_status":
                record["payment_status"],

            "transaction_id":
                record["transaction_id"],

            "payment_time":
                record["payment_time"],

            "razorpay_order_id":
                record["razorpay_order_id"]
        })


    return jsonify(
        session_data
    )


# ==========================================
# STATISTICS API
# ==========================================

@app.route("/statistics")
def statistics():

    occupied_slots = sum(

        1

        for slot
        in parking_status.values()

        if slot == "OCCUPIED"
    )


    available_slots = (
        3 - occupied_slots
    )


    conn = sqlite3.connect(
        DATABASE
    )

    cursor = conn.cursor()


    cursor.execute("""
        SELECT COUNT(*)
        FROM parking_sessions
        WHERE exit_time IS NOT NULL
    """)

    completed_sessions = (
        cursor.fetchone()[0]
    )


    cursor.execute("""
        SELECT COUNT(*)
        FROM parking_sessions
        WHERE payment_status = 'PENDING'
        AND exit_time IS NOT NULL
    """)

    pending_payments = (
        cursor.fetchone()[0]
    )


    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM parking_sessions
        WHERE payment_status = 'PAID'
    """)

    total_revenue = (
        cursor.fetchone()[0]
    )


    conn.close()


    return jsonify({

        "occupied_slots":
            occupied_slots,

        "available_slots":
            available_slots,

        "total_slots":
            3,

        "completed_sessions":
            completed_sessions,

        "pending_payments":
            pending_payments,

        "total_revenue":
            total_revenue,

        "total_events":
            session_statistics[
                "total_events"
            ],

        "last_update":
            session_statistics[
                "last_update"
            ]
    })


# ==========================================
# RESERVATION API
# ==========================================
# This endpoint is for the Admin Reserved
# Parking page that we will add next.
# ==========================================

@app.route("/reservations", methods=["GET", "POST"])
def reservations():

    # ==========================================
    # CREATE USER RESERVATION
    # ==========================================
    if request.method == "POST":

        conn = None

        try:

            # User must be logged in.
            if not session.get("user_logged_in"):

                return jsonify({
                    "success": False,
                    "message": "Please login as a user first."
                }), 401

            data = request.get_json(silent=True)

            if not data:

                return jsonify({
                    "success": False,
                    "message": "Reservation data is missing."
                }), 400

            # Accept both "1" and "slot1" style values.
            slot = str(
                data.get("slot", "")
            ).strip().lower()

            if slot.startswith("slot"):

                slot = slot.replace(
                    "slot",
                    "",
                    1
                ).strip()

            reservation_start = str(
                data.get("reservation_start", "")
            ).strip()

            reservation_end = str(
                data.get("reservation_end", "")
            ).strip()

            if slot not in ("1", "2", "3"):

                return jsonify({
                    "success": False,
                    "message": "Invalid parking slot."
                }), 400

            if not reservation_start:

                return jsonify({
                    "success": False,
                    "message": "Reservation start date is required."
                }), 400

            if not reservation_end:

                return jsonify({
                    "success": False,
                    "message": "Reservation end date is required."
                }), 400

            # ------------------------------------------
            # Validate reservation dates.
            # Supports:
            # YYYY-MM-DD
            # YYYY-MM-DDTHH:MM
            # YYYY-MM-DDTHH:MM:SS
            # ------------------------------------------

            def parse_reservation_datetime(value):

                value = str(value).strip()

                if value.endswith("Z"):
                    value = value[:-1] + "+00:00"

                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    pass

                # Also accept plain DD-MM-YYYY if sent by
                # the user page.
                try:

                    return datetime.strptime(
                        value,
                        "%d-%m-%Y"
                    )

                except ValueError:

                    return None


            start_dt = parse_reservation_datetime(
                reservation_start
            )

            end_dt = parse_reservation_datetime(
                reservation_end
            )

            if start_dt is None or end_dt is None:

                return jsonify({
                    "success": False,
                    "message": "Invalid reservation date. Use DD-MM-YYYY."
                }), 400

            if end_dt < start_dt:

                return jsonify({
                    "success": False,
                    "message": "Reservation end date cannot be before the start date."
                }), 400

            if end_dt == start_dt:

                return jsonify({
                    "success": False,
                    "message": "Reservation start and end cannot be the same."
                }), 400

            # ------------------------------------------
            # Store dates in one consistent format.
            # ------------------------------------------

            if (
                start_dt.hour == 0
                and start_dt.minute == 0
                and start_dt.second == 0
                and end_dt.hour == 0
                and end_dt.minute == 0
                and end_dt.second == 0
            ):

                reservation_start_db = (
                    start_dt.strftime("%Y-%m-%d")
                )

                reservation_end_db = (
                    end_dt.strftime("%Y-%m-%d")
                )

            else:

                reservation_start_db = (
                    start_dt.strftime("%Y-%m-%d %H:%M:%S")
                )

                reservation_end_db = (
                    end_dt.strftime("%Y-%m-%d %H:%M:%S")
                )

            user_id = session.get("user_id")

            if not user_id:

                return jsonify({
                    "success": False,
                    "message": "User session expired. Please login again."
                }), 401

            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()

            # ------------------------------------------
            # Prevent overlapping active reservations.
            # ------------------------------------------

            cursor.execute("""
                SELECT id
                FROM reservations
                WHERE slot = ?
                AND status IN ('RESERVED', 'OCCUPIED')
                AND reservation_start < ?
                AND reservation_end > ?
                LIMIT 1
            """, (
                slot,
                reservation_end_db,
                reservation_start_db
            ))

            existing = cursor.fetchone()

            if existing:

                conn.close()
                conn = None

                return jsonify({
                    "success": False,
                    "message":
                        "This slot is already reserved for the selected time."
                }), 409

            # ------------------------------------------
            # CREATE RESERVATION
            # ------------------------------------------

            cursor.execute("""
                INSERT INTO reservations
                (
                    user_id,
                    slot,
                    reservation_start,
                    reservation_end,
                    status,
                    payment_status
                )
                VALUES (?, ?, ?, ?, 'RESERVED', 'PENDING')
            """, (
                user_id,
                slot,
                reservation_start_db,
                reservation_end_db
            ))

            reservation_id = cursor.lastrowid

            conn.commit()
            conn.close()
            conn = None

            print(
                "RESERVATION CREATED:",
                reservation_id,
                "USER:",
                user_id,
                "SLOT:",
                slot,
                "START:",
                reservation_start_db,
                "END:",
                reservation_end_db
            )

            # Return HTTP 200 so the existing user page
            # handles the successful response normally.
            return jsonify({
                "success": True,
                "message": "Reservation created successfully.",
                "reservation_id": reservation_id,
                "slot": slot,
                "reservation_start": reservation_start_db,
                "reservation_end": reservation_end_db
            }), 200

        except Exception as e:

            if conn is not None:

                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass

            print(
                "RESERVATION CREATE ERROR:",
                repr(e)
            )

            return jsonify({
                "success": False,
                "message":
                    "Unable to create reservation: " + str(e)
            }), 500

    # ==========================================
    # GET RESERVATIONS FOR ADMIN
    # ==========================================

    conn = sqlite3.connect(
        DATABASE
    )

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            r.id,
            r.user_id,
            r.slot,
            r.reservation_start,
            r.reservation_end,
            r.status,
            r.entry_time,
            r.exit_time,
            r.duration_seconds,
            r.amount,
            r.payment_status,
            r.payment_method,
            r.transaction_id,
            r.payment_time,
            r.razorpay_order_id,
            u.name AS user_name,
            u.email AS user_email
        FROM reservations r
        LEFT JOIN users u
            ON r.user_id = u.id
        ORDER BY r.id DESC
    """)


    records = cursor.fetchall()

    conn.close()


    reservation_data = []


    for record in records:

        reservation_data.append({

            "id":
                record["id"],

            "user_id":
                record["user_id"],

            "user_name":
                record["user_name"],

            "user_email":
                record["user_email"],

            "slot":
                record["slot"],

            "reservation_start":
                record["reservation_start"],

            "reservation_end":
                record["reservation_end"],

            "status":
                record["status"],

            "entry_time":
                record["entry_time"],

            "exit_time":
                record["exit_time"],

            "duration_seconds":
                record["duration_seconds"],

            "amount":
                record["amount"],

            "payment_status":
                record["payment_status"],

            "payment_method":
                record["payment_method"],

            "transaction_id":
                record["transaction_id"],

            "payment_time":
                record["payment_time"],

            "razorpay_order_id":
                record["razorpay_order_id"]
        })


    return jsonify(
        reservation_data
    )



# ==========================================
# RESERVATION CASH PAYMENT
# ADMIN USE
# ==========================================

@app.route(
    "/reservation-cash-payment",
    methods=["POST"]
)
def reservation_cash_payment():

    try:

        data = request.get_json(
            silent=True
        )


        if not data:

            return jsonify({
                "success": False,
                "message":
                    "Request data is missing."
            }), 400


        reservation_id = data.get(
            "reservation_id"
        )


        if not reservation_id:

            return jsonify({
                "success": False,
                "message":
                    "Reservation ID is required."
            }), 400


        conn = sqlite3.connect(
            DATABASE
        )

        cursor = conn.cursor()


        cursor.execute("""
            SELECT
                id,
                amount,
                exit_time,
                payment_status
            FROM reservations
            WHERE id = ?
        """, (
            reservation_id,
        ))


        reservation = (
            cursor.fetchone()
        )


        if not reservation:

            conn.close()

            return jsonify({
                "success": False,
                "message":
                    "Reservation not found."
            }), 404


        (
            reservation_id_db,
            amount,
            exit_time,
            payment_status
        ) = reservation


        if not exit_time:

            conn.close()

            return jsonify({
                "success": False,
                "message":
                    "Vehicle has not exited yet."
            }), 400


        if payment_status == "PAID":

            conn.close()

            return jsonify({
                "success": False,
                "message":
                    "Payment already completed."
            }), 400


        payment_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )


        cursor.execute("""
            UPDATE reservations
            SET
                payment_status = 'PAID',
                payment_method = 'CASH',
                transaction_id = 'CASH',
                payment_time = ?
            WHERE id = ?
        """, (
            payment_time,
            reservation_id
        ))


        conn.commit()

        conn.close()


        return jsonify({

            "success":
                True,

            "message":
                "Reservation cash payment recorded.",

            "transaction_id":
                "CASH",

            "payment_time":
                payment_time
        })


    except Exception as e:

        print(
            "RESERVATION CASH PAYMENT ERROR:",
            e
        )

        return jsonify({

            "success":
                False,

            "message":
                str(e)

        }), 500


# ==========================================
# READ ESP32 SERIAL DATA
# ==========================================

def read_esp32():

    global parking_status

    while True:

        ser = None

        try:

            print(
                "Connecting to ESP32 on",
                PORT
            )


            ser = serial.Serial(
                port=PORT,
                baudrate=BAUD_RATE,
                timeout=1
            )


            time.sleep(2)


            print(
                "Connected to ESP32 on",
                PORT
            )


            initial_status_received = False

            last_status = None

            current_reading = {}


            while True:

                line = (
                    ser.readline()
                    .decode(
                        "utf-8",
                        errors="ignore"
                    )
                    .strip()
                )


                if not line:

                    continue


                print(
                    "ESP32:",
                    line
                )


                # --------------------------------
                # SLOT 1
                # --------------------------------
                # NO READING is treated as EMPTY
                # so the dashboard does not get stuck.

                if line.startswith(
                    "Slot 1:"
                ):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot1"
                        ] = "OCCUPIED"

                    elif (
                        "EMPTY" in line
                        or
                        "NO READING" in line
                    ):

                        current_reading[
                            "slot1"
                        ] = "EMPTY"


                # --------------------------------
                # SLOT 2
                # --------------------------------

                elif line.startswith(
                    "Slot 2:"
                ):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot2"
                        ] = "OCCUPIED"

                    elif (
                        "EMPTY" in line
                        or
                        "NO READING" in line
                    ):

                        current_reading[
                            "slot2"
                        ] = "EMPTY"


                # --------------------------------
                # SLOT 3
                # --------------------------------

                elif line.startswith(
                    "Slot 3:"
                ):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot3"
                        ] = "OCCUPIED"

                    elif (
                        "EMPTY" in line
                        or
                        "NO READING" in line
                    ):

                        current_reading[
                            "slot3"
                        ] = "EMPTY"


                # --------------------------------
                # WAIT FOR ALL 3 SLOTS
                # --------------------------------

                if len(current_reading) < 3:

                    continue


                new_status = {

                    "slot1":
                        current_reading[
                            "slot1"
                        ],

                    "slot2":
                        current_reading[
                            "slot2"
                        ],

                    "slot3":
                        current_reading[
                            "slot3"
                        ]
                }


                current_reading = {}


                # --------------------------------
                # INITIAL STATUS
                # --------------------------------

                if not initial_status_received:

                    parking_status = (
                        new_status.copy()
                    )

                    last_status = (
                        new_status.copy()
                    )

                    initial_status_received = True

                    print(
                        "Initial parking status:",
                        parking_status
                    )

                    continue


                # --------------------------------
                # CHECK STATUS CHANGES
                # --------------------------------

                if new_status != last_status:

                    for slot in [
                        "slot1",
                        "slot2",
                        "slot3"
                    ]:

                        old_value = (
                            last_status[slot]
                        )

                        new_value = (
                            new_status[slot]
                        )


                        # Vehicle entered
                        if (
                            old_value
                            == "EMPTY"
                            and
                            new_value
                            == "OCCUPIED"
                        ):

                            start_parking_session(
                                slot
                            )


                        # Vehicle exited
                        elif (
                            old_value
                            == "OCCUPIED"
                            and
                            new_value
                            == "EMPTY"
                        ):

                            end_parking_session(
                                slot
                            )


                    parking_status = (
                        new_status.copy()
                    )


                    save_status(
                        new_status
                    )


                    session_statistics[
                        "total_events"
                    ] += 1


                    session_statistics[
                        "last_update"
                    ] = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )


                    last_status = (
                        new_status.copy()
                    )


        except Exception as e:

            print()
            print(
                "ESP32 CONNECTION ERROR:"
            )
            print(e)
            print(
                "Retrying in 3 seconds..."
            )
            print()


            time.sleep(3)


        finally:

            if ser:

                try:

                    ser.close()

                except Exception:

                    pass


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":

    init_database()


    esp32_thread = threading.Thread(
        target=read_esp32,
        daemon=True
    )

    esp32_thread.start()


    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )