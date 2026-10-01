🚗 Smart Parking Management System

An IoT-based Smart Parking System that integrates ESP32 hardware, ultrasonic sensors, and a Flask web application to provide real-time parking monitoring, reservations, session tracking, and payment management.

---

📌 Project Overview

This system enables:

- Real-time parking slot detection
- Online slot reservation
- Parking session tracking
- Automated billing and payment
- Admin monitoring dashboard
- Gate-level operational dashboard
- Integration of IoT hardware with web technologies

---

🧠 Technologies Used

🔧 Hardware

- ESP32 Microcontroller
- HC-SR04 Ultrasonic Sensors (×3)
- SG90 Servo Motor (Gate Control)

💻 Software

- Python (Flask Framework)
- SQLite Database
- HTML, CSS, JavaScript

💳 Payment Integration

- Razorpay (Online Payments)
- Cash Payment (Admin Entry)

---

⚙️ System Architecture

Parking Area → Sensors → ESP32 → Serial → Flask Backend → SQLite → Web Dashboards

---

🚘 Features

👤 User Features

- User Registration & Login
- View live parking slots
- Reserve parking slots
- View current parking session
- View parking history
- Online payment (Razorpay)

---

🛠️ Admin Features

- Dashboard for full system monitoring
- View live parking status
- Manage parking sessions
- Manage reservations
- Record cash payments
- View statistics and history

---

🚪 Gate Dashboard

- No login required
- Displays real-time slot status
- Shows:
  - EMPTY
  - RESERVED
  - OCCUPIED
- Displays gate and hardware status

---

🅿️ Parking Slot Logic

Condition| Status
No vehicle + No reservation| 🟢 EMPTY
Reservation exists + No vehicle| 🟡 RESERVED
Vehicle detected| 🔴 OCCUPIED

---

🔌 Hardware Configuration

Ultrasonic Sensors

Slot| TRIG| ECHO
Slot 1| GPIO 5| GPIO 18
Slot 2| GPIO 4| GPIO 19
Slot 3| GPIO 23| GPIO 22

«⚠️ Only ECHO uses a voltage divider before ESP32»

---

Servo Motor (Gate Control)

- Signal → GPIO 13
- Logic:
  - If at least one slot is available → Gate OPEN
  - If all slots are occupied → Gate CLOSED

---

📡 Parking Detection Logic

Distance < 10 cm → OCCUPIED
Distance ≥ 10 cm → EMPTY

Multiple readings are used to improve accuracy and reduce noise.

---

🔄 System Flow

User Flow

Register → Login → View Slots → Reserve → Park → Exit → Payment → History

Admin Flow

Login → Dashboard → Monitor → Manage Sessions → Manage Reservations → Payments

Gate Flow

Open Dashboard → View Live Status → Monitor Gate

---

🗄️ Database

- Database: SQLite
- File: "parking.db" (not pushed to GitHub)

Key Tables:

- "users"
- "reservations"
- "parking_sessions"

«⚠️ Reservations and normal parking sessions are handled separately»

---

💳 Payment System

Online Payment

- Razorpay integration
- Order creation → Payment → Verification

Offline Payment

- Admin can record cash payments

«⚠️ Payment is allowed only after vehicle exit (session must be completed)»

---

🌐 API Endpoints (Important)

Route| Description
"/"| Admin Dashboard
"/user"| User Portal
"/gate"| Gate Dashboard
"/status"| Live slot status
"/reservations"| Manage reservations
"/sessions"| Parking sessions
"/history"| Parking history
"/statistics"| System stats
"/create-order"| Razorpay order
"/verify-payment"| Payment verification

---

📁 Project Structure

smart-parking-iot/
│
├── app.py
├── README.md
├── .gitignore
│
├── templates/
│   ├── index.html
│   ├── user.html
│   └── gate.html
│
├── static/
│
└── esp32/
  └── smart_parking.ino

---

⚠️ Important Notes

- ❌ No Machine Learning is used in this project
- ❌ IR sensors are NOT used
- ❌ Slot 4 is NOT used
- ✅ Only HC-SR04 sensors are used
- ✅ Database is local and excluded from GitHub
- ✅ Razorpay keys are stored as environment variables

---

🧪 Testing Strategy

Hardware

- Sensor → ESP32 → Serial output

Backend

- Serial → Flask → Database

Frontend

- API → UI dashboards

Full System

- Reservation → Arrival → Session → Exit → Payment

---

🚀 Future Scope

- Mobile application
- Cloud database integration
- Multi-location parking
- QR-based entry
- Automatic number plate recognition
- Smart navigation to slots
- Real-time notifications

---

📚 Academic Details

- Project Title: Smart Parking Management System
- Domain: IoT + Web Application
- Backend: Flask (Python)
- Database: SQLite
- Hardware: ESP32 + Ultrasonic Sensors

---

🔗 GitHub Repository

https://github.com/Harshpendke/smart-parking-iot

---

📌 Development Guidelines

- Do not remove existing features
- Follow incremental development
- Keep UI consistent
- Keep reservations and sessions separate
- Do not expose API keys or database

---

🏁 Final Summary

This project demonstrates a complete IoT-integrated smart parking solution combining:

- Real-time sensing
- Web-based control
- Reservation system
- Payment integration
- Admin-level monitoring

---

✔ Fully Functional System
✔ Real-Time Monitoring
✔ IoT + Web Integration

---

👨‍💻 Developed By

- Harsh Pendke
- Kashiling Bhusnar
- Kesar Thakur

---

