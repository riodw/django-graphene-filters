from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from graphene_django.views import GraphQLView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("graphql/", GraphQLView.as_view(graphiql=True)),
    path("login/", auth_views.LoginView.as_view(template_name="admin/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
]
