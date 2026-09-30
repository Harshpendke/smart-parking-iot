from flask import Flask, jsonify, render_template, request
import serial
import threading
import sqlite3
from datetime import datetime
import time
import math
import os
import razorpay

app = Flask(__name__)

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

# First hour = ₹20
FIRST_HOUR_RATE = 20

# Every additional hour or partial hour = ₹10
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
    # PARKING SESSIONS
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
    # ADD NEW COLUMNS TO OLD DATABASE
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
# START PARKING SESSION
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

    # --------------------------------------
    # First hour
    # --------------------------------------

    if duration_seconds <= 3600:

        billable_hours = 1

        amount = FIRST_HOUR_RATE

    # --------------------------------------
    # Additional hours
    # --------------------------------------

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

    return billable_hours, amount


# ==========================================
# END PARKING SESSION
# ==========================================

def end_parking_session(slot):

    entry_time = active_sessions[slot]

    if entry_time is None:

        print(
            "Warning: No active session found for",
            slot
        )

        return

    exit_time = datetime.now()

    duration = exit_time - entry_time

    duration_seconds = int(
        duration.total_seconds()
    )

    # --------------------------------------
    # Calculate parking fee
    # --------------------------------------

    billable_hours, amount = (
        calculate_parking_fee(
            duration_seconds
        )
    )

    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    # --------------------------------------
    # Find latest open session
    # --------------------------------------

    cursor.execute("""
        SELECT id
        FROM parking_sessions
        WHERE slot = ?
        AND exit_time IS NULL
        ORDER BY id DESC
        LIMIT 1
    """, (slot,))

    record = cursor.fetchone()

    if record:

        session_id = record[0]

        cursor.execute("""
            UPDATE parking_sessions
            SET exit_time = ?,
                duration_seconds = ?,
                amount = ?,
                payment_status = ?
            WHERE id = ?
        """, (
            exit_time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            duration_seconds,
            amount,
            "PENDING",
            session_id
        ))

    conn.commit()
    conn.close()

    # --------------------------------------
    # Clear active session
    # --------------------------------------

    active_sessions[slot] = None

    # --------------------------------------
    # Calculate readable duration
    # --------------------------------------

    hours = duration_seconds // 3600

    minutes = (
        duration_seconds % 3600
    ) // 60

    seconds = (
        duration_seconds % 60
    )

    # --------------------------------------
    # Print session information
    # --------------------------------------

    print()
    print("===================================")
    print(slot.upper(), "- VEHICLE EXITED")

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
# CREATE RAZORPAY ORDER
# PAYMENT SECTION
# ==========================================

@app.route("/create-order", methods=["POST"])
def create_order():

    print()
    print("===================================")
    print("CREATE PAYMENT ORDER REQUEST")
    print("===================================")

    # --------------------------------------
    # Check Razorpay configuration
    # --------------------------------------

    if not RAZORPAY_KEY_ID:

        print("ERROR: RAZORPAY_KEY_ID is missing.")

        return jsonify({
            "success": False,
            "message": "Razorpay Key ID is not configured.",
            "error": "RAZORPAY_KEY_ID environment variable is missing."
        }), 500

    if not RAZORPAY_KEY_SECRET:

        print("ERROR: RAZORPAY_KEY_SECRET is missing.")

        return jsonify({
            "success": False,
            "message": "Razorpay Secret Key is not configured.",
            "error": "RAZORPAY_KEY_SECRET environment variable is missing."
        }), 500

    if razorpay_client is None:

        print("ERROR: Razorpay client was not initialized.")

        return jsonify({
            "success": False,
            "message": "Razorpay client is not initialized.",
            "error": "Razorpay client initialization failed."
        }), 500

    print("Razorpay Key ID detected.")
    print("Razorpay client initialized.")

    # --------------------------------------
    # Read request data
    # --------------------------------------

    data = request.get_json(
        silent=True
    )

    print(
        "Request data:",
        data
    )

    if not data:

        print("ERROR: Request data is missing.")

        return jsonify({
            "success": False,
            "message": "Request data is missing."
        }), 400

    session_id = data.get(
        "session_id"
    )

    print(
        "Session ID:",
        session_id
    )

    if not session_id:

        print("ERROR: Session ID is missing.")

        return jsonify({
            "success": False,
            "message": "Session ID is required."
        }), 400

    # --------------------------------------
    # Get parking session
    # --------------------------------------

    conn = sqlite3.connect(DATABASE)

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
    """, (session_id,))

    session = cursor.fetchone()

    # --------------------------------------
    # Session not found
    # --------------------------------------

    if session is None:

        conn.close()

        print(
            "ERROR: Parking session not found."
        )

        return jsonify({
            "success": False,
            "message": "Parking session not found."
        }), 404

    print(
        "Session found:",
        dict(session)
    )

    # --------------------------------------
    # Payment already completed
    # --------------------------------------

    if session["payment_status"] == "PAID":

        conn.close()

        print(
            "ERROR: Session is already paid."
        )

        return jsonify({
            "success": False,
            "message": "This session is already paid."
        }), 400

    # --------------------------------------
    # Session must be completed
    # --------------------------------------

    if session["exit_time"] is None:

        conn.close()

        print(
            "ERROR: Vehicle has not exited yet."
        )

        return jsonify({
            "success": False,
            "message": "Payment is available after vehicle exit."
        }), 400

    # --------------------------------------
    # Amount validation
    # --------------------------------------

    if session["amount"] is None:

        conn.close()

        print(
            "ERROR: Parking amount is missing."
        )

        return jsonify({
            "success": False,
            "message": "Parking amount is not available yet."
        }), 400

    amount_rupees = float(
        session["amount"]
    )

    amount_paise = int(
        round(
            amount_rupees * 100
        )
    )

    print(
        "Parking amount:",
        amount_rupees,
        "INR"
    )

    print(
        "Razorpay amount:",
        amount_paise,
        "paise"
    )

    if amount_paise <= 0:

        conn.close()

        print(
            "ERROR: Invalid payment amount."
        )

        return jsonify({
            "success": False,
            "message": "Invalid payment amount."
        }), 400

    # --------------------------------------
    # ALWAYS CREATE A NEW RAZORPAY ORDER
    # --------------------------------------

    try:

        print()
        print(
            "Calling Razorpay Order API..."
        )

        order_data = {

            "amount":
                amount_paise,

            "currency":
                "INR",

            "receipt":
                "parking_" +
                str(session["id"]) +
                "_" +
                str(int(time.time())),

            "notes": {

                "parking_session_id":
                    str(session["id"]),

                "slot":
                    session["slot"]
            }
        }

        print(
            "Order data:",
            order_data
        )

        razorpay_order = (
            razorpay_client.order.create(
                data=order_data
            )
        )

        print(
            "Razorpay API response:",
            razorpay_order
        )

        razorpay_order_id = (
            razorpay_order["id"]
        )

        # ----------------------------------
        # Save new Razorpay order ID
        # ----------------------------------

        cursor.execute("""
            UPDATE parking_sessions
            SET razorpay_order_id = ?
            WHERE id = ?
        """, (
            razorpay_order_id,
            session["id"]
        ))

        conn.commit()
        conn.close()

        print()
        print("===================================")
        print("RAZORPAY ORDER CREATED SUCCESSFULLY")
        print("===================================")
        print(
            "Session ID:",
            session["id"]
        )
        print(
            "Slot:",
            session["slot"]
        )
        print(
            "Amount: ₹",
            amount_rupees
        )
        print(
            "Amount in Paise:",
            amount_paise
        )
        print(
            "Razorpay Order ID:",
            razorpay_order_id
        )
        print("===================================")
        print()

        return jsonify({

            "success":
                True,

            "key_id":
                RAZORPAY_KEY_ID,

            "order_id":
                razorpay_order_id,

            "session_id":
                session["id"],

            "amount":
                amount_paise,

            "amount_rupees":
                amount_rupees,

            "currency":
                "INR"
        })

    except Exception as e:

        conn.close()

        # ==================================
        # IMPORTANT DEBUG INFORMATION
        # ==================================

        print()
        print("===================================")
        print("RAZORPAY ORDER CREATION FAILED")
        print("===================================")
        print(
            "ERROR TYPE:",
            type(e).__name__
        )
        print(
            "ERROR:",
            repr(e)
        )
        print(
            "ERROR MESSAGE:",
            str(e)
        )
        print("===================================")
        print()

        return jsonify({

            "success":
                False,

            "message":
                "Unable to create Razorpay order.",

            "error":
                str(e),

            "error_type":
                type(e).__name__

        }), 500


# ==========================================
# VERIFY RAZORPAY PAYMENT
# PAYMENT SECTION
# ==========================================

@app.route("/verify-payment", methods=["POST"])
def verify_payment():

    if razorpay_client is None:

        return jsonify({
            "success": False,
            "message": "Razorpay is not configured."
        }), 500

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "success": False,
            "message": "Payment data is missing."
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
            "message": "Session ID is required."
        }), 400

    if not razorpay_payment_id:

        return jsonify({
            "success": False,
            "message": "Razorpay payment ID is missing."
        }), 400

    if not razorpay_order_id:

        return jsonify({
            "success": False,
            "message": "Razorpay order ID is missing."
        }), 400

    if not razorpay_signature:

        return jsonify({
            "success": False,
            "message": "Razorpay signature is missing."
        }), 400

    conn = sqlite3.connect(DATABASE)

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
    """, (session_id,))

    session = cursor.fetchone()

    if session is None:

        conn.close()

        return jsonify({
            "success": False,
            "message": "Parking session not found."
        }), 404

    if session["payment_status"] == "PAID":

        conn.close()

        return jsonify({
            "success": True,
            "message": "Payment was already completed."
        })

    if (
        session["razorpay_order_id"]
        and
        session["razorpay_order_id"]
        != razorpay_order_id
    ):

        conn.close()

        return jsonify({
            "success": False,
            "message": "Razorpay order ID does not match."
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

        print()
        print(
            "Razorpay payment verification failed:"
        )
        print(
            type(e).__name__,
            str(e)
        )
        print()

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
        SET payment_status = ?,
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

    print()
    print("===================================")
    print("RAZORPAY PAYMENT VERIFIED")
    print("===================================")
    print(
        "Session ID:",
        session_id
    )
    print(
        "Payment ID:",
        razorpay_payment_id
    )
    print(
        "Order ID:",
        razorpay_order_id
    )
    print(
        "Payment Time:",
        payment_time
    )
    print(
        "Payment Status: PAID"
    )
    print("===================================")
    print()

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

                line = ser.readline().decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

                if not line:
                    continue

                print("ESP32:", line)

                # --------------------------------
                # SLOT 1
                # --------------------------------

                if line.startswith("Slot 1:"):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot1"
                        ] = "OCCUPIED"

                    elif "EMPTY" in line:

                        current_reading[
                            "slot1"
                        ] = "EMPTY"

                # --------------------------------
                # SLOT 2
                # --------------------------------

                elif line.startswith("Slot 2:"):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot2"
                        ] = "OCCUPIED"

                    elif "EMPTY" in line:

                        current_reading[
                            "slot2"
                        ] = "EMPTY"

                # --------------------------------
                # SLOT 3
                # --------------------------------

                elif line.startswith("Slot 3:"):

                    if "OCCUPIED" in line:

                        current_reading[
                            "slot3"
                        ] = "OCCUPIED"

                    elif "EMPTY" in line:

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
                        current_reading["slot1"],

                    "slot2":
                        current_reading["slot2"],

                    "slot3":
                        current_reading["slot3"]
                }

                # =================================
                # INITIAL READING
                # =================================

                if not initial_status_received:

                    parking_status = (
                        new_status.copy()
                    )

                    last_status = (
                        new_status.copy()
                    )

                    initial_status_received = True

                    print()
                    print(
                        "Initial parking status established."
                    )

                    print(
                        "Slot 1:",
                        parking_status["slot1"]
                    )

                    print(
                        "Slot 2:",
                        parking_status["slot2"]
                    )

                    print(
                        "Slot 3:",
                        parking_status["slot3"]
                    )

                    print(
                        "Startup reading NOT saved."
                    )

                    print()

                    current_reading.clear()

                    continue

                # =================================
                # CHECK STATUS CHANGE
                # =================================

                if new_status != last_status:

                    # --------------------------------
                    # CHECK EACH SLOT
                    # --------------------------------

                    for slot in [
                        "slot1",
                        "slot2",
                        "slot3"
                    ]:

                        old_state = (
                            last_status[slot]
                        )

                        new_state = (
                            new_status[slot]
                        )

                        # ----------------------------
                        # VEHICLE ENTERED
                        # ----------------------------

                        if (
                            old_state == "EMPTY"
                            and
                            new_state == "OCCUPIED"
                        ):

                            start_parking_session(
                                slot
                            )

                        # ----------------------------
                        # VEHICLE EXITED
                        # ----------------------------

                        elif (
                            old_state == "OCCUPIED"
                            and
                            new_state == "EMPTY"
                        ):

                            end_parking_session(
                                slot
                            )

                    # --------------------------------
                    # UPDATE CURRENT STATUS
                    # --------------------------------

                    parking_status = (
                        new_status.copy()
                    )

                    # --------------------------------
                    # SAVE STATUS HISTORY
                    # --------------------------------

                    save_status(
                        parking_status
                    )

                    # --------------------------------
                    # UPDATE STATISTICS
                    # --------------------------------

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

                    print()
                    print(
                        "PARKING STATUS CHANGED"
                    )

                    print(
                        "Slot 1:",
                        parking_status["slot1"]
                    )

                    print(
                        "Slot 2:",
                        parking_status["slot2"]
                    )

                    print(
                        "Slot 3:",
                        parking_status["slot3"]
                    )

                    print()

                current_reading.clear()

        # =========================================
        # SERIAL ERROR
        # =========================================

        except serial.SerialException as e:

            print()
            print(
                "ESP32 serial connection error:"
            )

            print(e)

            print(
                "Retrying in 3 seconds..."
            )

            print()

            time.sleep(3)

        # =========================================
        # OTHER ERROR
        # =========================================

        except Exception as e:

            print()
            print(
                "ESP32 connection error:"
            )

            print(e)

            print(
                "Retrying in 3 seconds..."
            )

            print()

            time.sleep(3)

        # =========================================
        # CLOSE SERIAL
        # =========================================

        finally:

            if ser is not None:

                try:

                    ser.close()

                except:

                    pass


# ==========================================
# MAIN DASHBOARD
# ==========================================

@app.route("/")
def home():

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
# Cash payment endpoint
# ==========================================

@app.route("/cash-payment", methods=["POST"])
def cash_payment():
    try:
        data = request.get_json()

        session_id = data.get("session_id")

        if not session_id:
            return jsonify({
                "error": "Session ID is required"
            }), 400

        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, amount, exit_time, payment_status
            FROM parking_sessions
            WHERE id = ?
        """, (session_id,))

        session = cursor.fetchone()

        if not session:
            conn.close()

            return jsonify({
                "error": "Parking session not found"
            }), 404

        session_id_db, amount, exit_time, payment_status = session

        if not exit_time:
            conn.close()

            return jsonify({
                "error": "Vehicle has not exited yet"
            }), 400

        if payment_status == "PAID":
            conn.close()

            return jsonify({
                "error": "Payment already completed"
            }), 400

        payment_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cursor.execute("""
            UPDATE parking_sessions
            SET payment_status = 'PAID',
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
            "success": True,
            "message": "Cash payment recorded",
            "transaction_id": "CASH",
            "payment_time": payment_time
        })

    except Exception as e:

        print("CASH PAYMENT ERROR:", e)

        return jsonify({
            "error": str(e)
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
# STATUS HISTORY API
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

    # --------------------------------------
    # Completed sessions
    # --------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM parking_sessions
        WHERE exit_time IS NOT NULL
    """)

    completed_sessions = (
        cursor.fetchone()[0]
    )

    # --------------------------------------
    # Pending payments
    # --------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM parking_sessions
        WHERE payment_status = 'PENDING'
        AND exit_time IS NOT NULL
    """)

    pending_payments = (
        cursor.fetchone()[0]
    )

    # --------------------------------------
    # Paid sessions
    # --------------------------------------

    cursor.execute("""
        SELECT COUNT(*)
        FROM parking_sessions
        WHERE payment_status = 'PAID'
    """)

    paid_sessions = (
        cursor.fetchone()[0]
    )

    # --------------------------------------
    # Total revenue
    # --------------------------------------

    cursor.execute("""
        SELECT COALESCE(
            SUM(amount), 0
        )
        FROM parking_sessions
        WHERE payment_status = 'PAID'
    """)

    total_revenue = (
        cursor.fetchone()[0]
    )

    conn.close()

    return jsonify({

        "total_events":
            session_statistics[
                "total_events"
            ],

        "occupied_slots":
            occupied_slots,

        "available_slots":
            available_slots,

        "completed_sessions":
            completed_sessions,

        "pending_payments":
            pending_payments,

        "paid_sessions":
            paid_sessions,

        "total_revenue":
            total_revenue,

        "last_update":
            session_statistics[
                "last_update"
            ]
    })


# ==========================================
# START APPLICATION
# ==========================================

if __name__ == "__main__":

    init_database()

    print()
    print("===================================")
    print("       SMART PARKING SYSTEM")
    print("===================================")

    print(
        "First Hour Rate: ₹",
        FIRST_HOUR_RATE
    )

    print(
        "Additional Hour Rate: ₹",
        ADDITIONAL_HOUR_RATE
    )

    print(
        "Razorpay Test Mode:",
        "ENABLED"
        if razorpay_client
        else
        "NOT CONFIGURED"
    )

    print(
        "Starting Flask application..."
    )

    print()

    # --------------------------------------
    # ESP32 READER THREAD
    # --------------------------------------

    esp32_thread = threading.Thread(
        target=read_esp32,
        daemon=True
    )

    esp32_thread.start()

    # --------------------------------------
    # START FLASK
    # --------------------------------------

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )