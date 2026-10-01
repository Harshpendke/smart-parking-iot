\# Smart Parking Management System



\## 📌 Project Overview



The \*\*Smart Parking Management System\*\* is an IoT-based web application designed to monitor and manage parking spaces in real time.



The system uses \*\*ESP32 and ultrasonic sensors\*\* to detect the occupancy of parking slots. The sensor data is processed by a \*\*Flask backend\*\* and stored in an \*\*SQLite database\*\*. Users can view parking availability, reserve parking slots, monitor their parking sessions, and make online payments.



The system also provides separate interfaces for \*\*Admin, User, and Gate operations\*\*.



\---



\## 🎯 Objectives



\- Monitor parking slots in real time.

\- Detect whether parking slots are empty or occupied.

\- Display live parking availability on the web application.

\- Allow users to reserve available parking slots.

\- Track vehicle entry and exit times.

\- Calculate parking charges based on parking duration.

\- Provide online payment using Razorpay.

\- Allow administrators to monitor parking activity.

\- Provide a dedicated gate dashboard for parking status.

\- Store parking, reservation, and payment information in SQLite.



\---



\## 🏗️ System Architecture



```text

&#x20;             ┌─────────────────────┐

&#x20;             │   ESP32 + Sensors   │

&#x20;             │   HC-SR04 Sensors   │

&#x20;             └──────────┬──────────┘

&#x20;                        │

&#x20;                        ▼

&#x20;             ┌─────────────────────┐

&#x20;             │   Flask Backend     │

&#x20;             │     Python          │

&#x20;             └──────────┬──────────┘

&#x20;                        │

&#x20;                        ▼

&#x20;             ┌─────────────────────┐

&#x20;             │    SQLite Database  │

&#x20;             └──────────┬──────────┘

&#x20;                        │

&#x20;         ┌──────────────┼──────────────┐

&#x20;         ▼              ▼              ▼

&#x20;    ┌─────────┐    ┌─────────┐    ┌─────────┐

&#x20;    │  Admin  │    │  User   │    │  Gate   │

&#x20;    │Dashboard│    │  Portal │    │Dashboard│

&#x20;    └─────────┘    └─────────┘    └─────────┘

