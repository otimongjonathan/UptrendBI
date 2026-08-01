# Business Intelligence Platform

## Overview

This project is a web-based Business Intelligence Platform developed using Flask. The application allows users to upload CSV datasets, assess data quality, perform data analysis, generate interactive visualizations, and produce reports that support business decision-making.

## Features

- User registration and login
- Secure authentication
- CSV dataset upload
- Data quality assessment
- Data analytics and visualization
- Interactive dashboard
- Report generation
- User profile management

## Technologies Used

- Python
- Flask
- PostgreSQL
- SQLAlchemy
- Pandas
- Plotly
- Bootstrap
- HTML, CSS, and JavaScript

---

# System Requirements

Before running the application, ensure the following software is installed:

- Python 3.10 or later
- PostgreSQL
- Git
- pip (Python package manager)
- Virtual Environment (venv)

---

# Installation Guide

## Step 1: Clone the Repository

Open a terminal and run:

```bash
git clone https://github.com/your-username/your-repository.git
```

Navigate into the project folder:

```bash
cd your-repository
```

---

## Step 2: Create a Virtual Environment

Windows

```bash
python -m venv venv
```

Linux / macOS

```bash
python3 -m venv venv
```

---

## Step 3: Activate the Virtual Environment

Windows

```bash
venv\Scripts\activate
```

Linux / macOS

```bash
source venv/bin/activate
```

After activation, the terminal should display the virtual environment name.

---

## Step 4: Install Project Dependencies

Install all required Python packages:

```bash
pip install -r requirements.txt
```

---

## Step 5: Create the PostgreSQL Database

1. Open PostgreSQL.
2. Create a new database.
3. Give the database a name (for example: `business_intelligence`).

---

## Step 6: Configure Environment Variables

Create a `.env` file in the project root and add the following information:

```
SECRET_KEY=your_secret_key

DATABASE_URL=postgresql://username:password@localhost/database_name
```

Replace:

- `username` with your PostgreSQL username
- `password` with your PostgreSQL password
- `database_name` with your database name

---

## Step 7: Initialize the Database

Run the database migration commands:

```bash
flask db init
```

```bash
flask db migrate
```

```bash
flask db upgrade
```

If the migrations already exist, only run:

```bash
flask db upgrade
```

---

## Step 8: Run the Application

Start the Flask server:

```bash
python run.py
```

or

```bash
flask run
```

---

## Step 9: Open the Application

Open your web browser and visit:

```
http://127.0.0.1:5000
```

The application should now be running.

---

# Using the Application

1. Register a new user account.
2. Log in using your credentials.
3. Upload a CSV dataset.
4. View the Data Quality dashboard.
5. Explore Analytics and interactive charts.
6. Generate reports from the analysed data.
7. Log out when finished.

---

# Project Structure

```
Business-Intelligence-Platform/

│
├── app/
│   ├── models.py
│   ├── routes/
│   ├── templates/
│   ├── static/
│   └── __init__.py
│
├── uploads/
├── migrations/
├── instance/
├── requirements.txt
├── run.py
└── README.md
```

---

# Troubleshooting

### ModuleNotFoundError

Install the required packages again:

```bash
pip install -r requirements.txt
```

---

### Database Connection Error

- Ensure PostgreSQL is running.
- Verify the username and password.
- Confirm the database exists.
- Check the `DATABASE_URL` in the `.env` file.

---

### Port Already in Use

Run Flask on another port:

```bash
flask run --port=5001
```

---

# Future Improvements

- Machine Learning predictions
- Automated report scheduling
- Email report delivery
- Advanced dashboards
- Real-time data updates
- Export reports as PDF or Excel

---

# Author

Developed as a university Business Intelligence project using Flask, PostgreSQL, Pandas, and Plotly.
