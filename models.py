import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "instance")
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

db = SQLAlchemy()


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(64), nullable=True)
    salary = db.Column(db.Float, nullable=False, default=0.0)

    payrolls = db.relationship("Payroll", back_populates="employee", cascade="all, delete-orphan")


class Payroll(db.Model):
    __tablename__ = "payrolls"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.String(20), nullable=False)  # keep YYYY-MM-DD for simplicity
    notes = db.Column(db.String(255), nullable=True)

    employee = db.relationship("Employee", back_populates="payrolls")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(16), nullable=False)
    row_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.String(50), default=lambda: datetime.utcnow().isoformat())
    details = db.Column(db.Text, nullable=True)


def create_db_and_triggers(app):
    """
    Create tables and sqlite triggers for auditing (Flask-SQLAlchemy v3 compatible).
    """
    with app.app_context():
        db.create_all()
        engine = db.get_engine()

        with engine.begin() as conn:
            def trigger_exists(name: str) -> bool:
                row = conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name = ?",
                    (name,),
                ).fetchone()
                return bool(row)

            def create_trigger_if_missing(name: str, sql: str):
                if not trigger_exists(name):
                    conn.exec_driver_sql(sql)

            # employees triggers
            create_trigger_if_missing(
                "employees_ai",
                """
                CREATE TRIGGER employees_ai AFTER INSERT ON employees
                BEGIN
                    INSERT INTO audit_logs(table_name, action, row_id, timestamp, details)
                    VALUES('employees','INSERT', NEW.id, datetime('now'),
                    'name=' || quote(NEW.name) || '; role=' || quote(NEW.role) || '; salary=' || NEW.salary);
                END;
                """,
            )

            create_trigger_if_missing(
                "employees_au",
                """
                CREATE TRIGGER employees_au AFTER UPDATE ON employees
                BEGIN
                    INSERT INTO audit_logs(table_name, action, row_id, timestamp, details)
                    VALUES('employees','UPDATE', NEW.id, datetime('now'),
                    'name=' || quote(NEW.name) || '; role=' || quote(NEW.role) || '; salary=' || NEW.salary);
                END;
                """,
            )

            create_trigger_if_missing(
                "employees_ad",
                """
                CREATE TRIGGER employees_ad AFTER DELETE ON employees
                BEGIN
                    INSERT INTO audit_logs(table_name, action, row_id, timestamp, details)
                    VALUES('employees','DELETE', OLD.id, datetime('now'),
                    'name=' || quote(OLD.name) || '; role=' || quote(OLD.role) || '; salary=' || OLD.salary);
                END;
                """,
            )

            # payroll triggers
            create_trigger_if_missing(
                "payrolls_ai",
                """
                CREATE TRIGGER payrolls_ai AFTER INSERT ON payrolls
                BEGIN
                    INSERT INTO audit_logs(table_name, action, row_id, timestamp, details)
                    VALUES('payrolls','INSERT', NEW.id, datetime('now'),
                    'employee_id=' || NEW.employee_id || '; amount=' || NEW.amount ||
                    '; date=' || quote(NEW.date));
                END;
                """,
            )

            create_trigger_if_missing(
                "payrolls_ad",
                """
                CREATE TRIGGER payrolls_ad AFTER DELETE ON payrolls
                BEGIN
                    INSERT INTO audit_logs(table_name, action, row_id, timestamp, details)
                    VALUES('payrolls','DELETE', OLD.id, datetime('now'),
                    'employee_id=' || OLD.employee_id || '; amount=' || OLD.amount ||
                    '; date=' || quote(OLD.date));
                END;
                """,
            )
