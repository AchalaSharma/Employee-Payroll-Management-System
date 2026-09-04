from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SubmitField, SelectField
from wtforms.validators import DataRequired, NumberRange

class EmployeeForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    role = StringField("Role")
    salary = DecimalField("Salary", validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField("Save")


class PayrollForm(FlaskForm):
    employee_id = SelectField("Employee", coerce=int, validators=[DataRequired()])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)])
    date = StringField("Date (YYYY-MM-DD)", validators=[DataRequired()])
    notes = StringField("Notes")
    submit = SubmitField("Save")
