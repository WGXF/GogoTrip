# routes/main.py
from flask import Blueprint, session, render_template_string
from templates import HOME_PAGE_TEMPLATE

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    message = session.pop('message', None)
    return render_template_string(HOME_PAGE_TEMPLATE,
                                  credentials_in_session=('credentials' in session),
                                  message=message)