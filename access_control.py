"""Shared access policy for every Flask-Admin view."""
from flask import abort, redirect, url_for
from flask_admin import AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_login import current_user


class AdminAccess:
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        abort(403)


class SecureAdminIndexView(AdminAccess, AdminIndexView):
    pass


class SecureModelView(AdminAccess, ModelView):
    pass
