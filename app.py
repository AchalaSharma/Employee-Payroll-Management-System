import os
import logging
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, flash, request
from flask_wtf import CSRFProtect

from models import db, Employee, Payroll, AuditLog, create_db_and_triggers
from forms import EmployeeForm, PayrollForm

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
if not os.path.exists(os.path.join(BASE_DIR, "instance")):
    os.makedirs(os.path.join(BASE_DIR, "instance"))

app = Flask(__name__, static_folder="static")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'payroll.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "change-this-to-a-strong-secret"  # change for production

# Initialize CSRF protection
csrf = CSRFProtect()
csrf.init_app(app)

# Initialize DB (Flask-SQLAlchemy)
db.init_app(app)

# Setup logging
file_handler = logging.FileHandler(os.path.join(LOG_DIR, "app.log"))
file_handler.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(fmt)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)


# Ensure DB & triggers created once (Flask 3 compatible)
@app.before_request
def init_db_once():
    if not getattr(app, "_db_initialized", False):
        create_db_and_triggers(app)
        app._db_initialized = True
        app.logger.info("Database and triggers initialized")


# -------------------------
# Dashboard (home)
# -------------------------
@app.route("/")
def index():
    # basic stats
    total_employees = Employee.query.count()
    total_payroll_entries = Payroll.query.count()
    total_payroll_amount = db.session.query(db.func.coalesce(db.func.sum(Payroll.amount), 0.0)).scalar() or 0.0

    # recent rows
    recent_employees = Employee.query.order_by(Employee.id.desc()).limit(5).all()
    recent_payrolls = Payroll.query.order_by(Payroll.id.desc()).limit(6).all()

    # monthly payroll totals (group by YYYY-MM from Payroll.date, show last 12 months)
    ym_col = db.func.substr(Payroll.date, 1, 7).label("ym")  # 'YYYY-MM'
    sum_col = db.func.coalesce(db.func.sum(Payroll.amount), 0.0).label("total")

    rows = (
        db.session.query(ym_col, sum_col)
        .group_by(ym_col)
        .order_by(ym_col.desc())
        .limit(12)
        .all()
    )
    monthly = [{"ym": r.ym, "total": float(r.total or 0.0)} for r in rows]

    return render_template(
        "index.html",
        total_employees=total_employees,
        total_payroll_entries=total_payroll_entries,
        total_payroll_amount=total_payroll_amount,
        recent_employees=recent_employees,
        recent_payrolls=recent_payrolls,
        monthly=monthly,
        now=datetime.utcnow(),
    )


# -------------------------
# Employees CRUD
# -------------------------
@app.route("/employees")
def employees_list():
    employees = Employee.query.order_by(Employee.id).all()
    return render_template("employees.html", employees=employees)


@app.route("/employees/new", methods=["GET", "POST"])
def employees_new():
    form = EmployeeForm()
    if form.validate_on_submit():
        try:
            emp = Employee(
                name=form.name.data.strip(),
                role=(form.role.data or "").strip(),
                salary=float(form.salary.data),
            )
            db.session.add(emp)
            db.session.commit()
            app.logger.info(f"Created employee id={emp.id} name={emp.name}")
            flash("Employee created", "success")
            return redirect(url_for("employees_list"))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error creating employee")
            flash(f"Error creating employee: {e}", "error")
    else:
        if request.method == "POST":
            app.logger.warning("Employee form validation failed: %s", form.errors)
            for field, errs in form.errors.items():
                for err in errs:
                    flash(f"{field}: {err}", "error")
    return render_template("employee_form.html", form=form, action="Create")


@app.route("/employees/<int:id>/edit", methods=["GET", "POST"])
def employees_edit(id):
    emp = Employee.query.get_or_404(id)
    form = EmployeeForm(obj=emp)
    if form.validate_on_submit():
        try:
            emp.name = form.name.data.strip()
            emp.role = (form.role.data or "").strip()
            emp.salary = float(form.salary.data)
            db.session.commit()
            app.logger.info(f"Updated employee id={emp.id}")
            flash("Employee updated", "success")
            return redirect(url_for("employees_list"))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error updating employee")
            flash(f"Error updating employee: {e}", "error")
    else:
        if request.method == "POST":
            app.logger.warning("Employee edit validation failed: %s", form.errors)
            for field, errs in form.errors.items():
                for err in errs:
                    flash(f"{field}: {err}", "error")
    return render_template("employee_form.html", form=form, action="Update")


@app.route("/employees/<int:id>/delete", methods=["POST"])
def employees_delete(id):
    emp = Employee.query.get_or_404(id)
    try:
        db.session.delete(emp)
        db.session.commit()
        app.logger.info(f"Deleted employee id={id}")
        flash("Employee deleted", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error deleting employee")
        flash(f"Error deleting employee: {e}", "error")
    return redirect(url_for("employees_list"))


# -------------------------
# Payroll CRUD
# -------------------------
@app.route("/payroll")
def payroll_list():
    entries = Payroll.query.order_by(Payroll.date.desc()).all()
    employees = Employee.query.order_by(Employee.name).all()
    employees_map = {e.id: e.name for e in employees}
    return render_template("payroll.html", entries=entries, employees_map=employees_map)


@app.route("/payroll/new", methods=["GET", "POST"])
def payroll_new():
    form = PayrollForm()
    # populate choices before validation
    form.employee_id.choices = [(e.id, e.name) for e in Employee.query.order_by(Employee.name).all()]

    if form.validate_on_submit():
        try:
            entry = Payroll(
                employee_id=int(form.employee_id.data),
                amount=float(form.amount.data),
                date=form.date.data.strip(),
                notes=(form.notes.data or "").strip(),
            )
            db.session.add(entry)
            db.session.commit()
            app.logger.info(f"Created payroll id={entry.id} for emp={entry.employee_id}")
            flash("Payroll entry created", "success")
            return redirect(url_for("payroll_list"))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Error creating payroll")
            flash(f"Error creating payroll: {e}", "error")
    else:
        if request.method == "POST":
            app.logger.warning("Payroll form validation failed: %s", form.errors)
            for field, errs in form.errors.items():
                for err in errs:
                    flash(f"{field}: {err}", "error")
    return render_template("payroll_form.html", form=form, action="Create")


@app.route("/payroll/<int:id>/delete", methods=["POST"])
def payroll_delete(id):
    entry = Payroll.query.get_or_404(id)
    try:
        db.session.delete(entry)
        db.session.commit()
        app.logger.info(f"Deleted payroll id={id}")
        flash("Payroll entry deleted", "success")
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Error deleting payroll")
        flash(f"Error deleting payroll: {e}", "error")
    return redirect(url_for("payroll_list"))


# -------------------------
# Audit logs
# -------------------------
@app.route("/logs")
def view_logs():
    logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(200).all()
    return render_template("logs.html", logs=logs)


import csv
from io import StringIO
from flask import Response, send_file

@app.route("/logs/download")
def download_logs_csv():
    log_file_path = os.path.join(LOG_DIR, "app.log")
    if not os.path.exists(log_file_path):
        return "Log file not found", 404

    # Parse log lines into CSV rows
    output = StringIO()
    writer = csv.writer(output)
    # Write CSV header
    writer.writerow(["timestamp", "level", "message"])

    with open(log_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Expected format: "2025-11-17 15:31:27,266 - INFO - Message"
            parts = line.split(" - ", 2)
            if len(parts) == 3:
                timestamp, level, message = parts
                writer.writerow([timestamp, level, message])
            else:
                # If line doesn't split as expected, write it as message only
                writer.writerow(["", "", line])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=app_log.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True)
