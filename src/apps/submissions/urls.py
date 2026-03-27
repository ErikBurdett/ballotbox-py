from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path("submit-profile/", views.profile_submit, name="profile_submit"),
    path("submit-profile/thanks/", views.profile_submit_done, name="profile_submit_done"),
    path("staff/submissions/login/", views.staff_login, name="staff_login"),
    path("staff/submissions/logout/", views.staff_logout, name="staff_logout"),
    path("staff/submissions/", views.staff_list, name="staff_list"),
    path("staff/submissions/<int:pk>/", views.staff_detail, name="staff_detail"),
]
