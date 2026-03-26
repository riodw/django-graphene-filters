from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import path
from graphene_django.views import GraphQLView


def index(request):
    """Landing page with quick links to all dev actions."""
    return HttpResponse("""
        <h2>Cookbook Dev Links</h2>
        <h3>Pages</h3>
        <ul>
            <li><a href="/graphql/">GraphiQL</a></li>
            <li><a href="/admin/">Admin</a></li>
            <li><a href="/login/">Login</a></li>
        </ul>
        <h3>Seed Data</h3>
        <ul>
            <li><a href="/admin/recipes/object/?seed_data=5">Seed 5 per provider</a></li>
            <li><a href="/admin/recipes/object/?seed_data=50">Seed 50 per provider</a></li>
        </ul>
        <h3>Delete Data</h3>
        <ul>
            <li><a href="/admin/recipes/object/?delete_data=10">Delete first 10 objects</a></li>
            <li><a href="/admin/recipes/object/?delete_data=all">Delete all objects &amp; values</a></li>
            <li><a href="/admin/recipes/object/?delete_data=everything">Wipe all tables</a></li>
        </ul>
        <h3>Create Users</h3>
        <ul>
            <li><a href="/admin/auth/user/?create_users=1">Create 1 set of test users</a></li>
            <li><a href="/admin/auth/user/?create_users=3">Create 3 sets of test users</a></li>
        </ul>
        <h3>Delete Users</h3>
        <ul>
            <li><a href="/admin/auth/user/?delete_users=5">Delete first 5 users</a></li>
            <li><a href="/admin/auth/user/?delete_users=all">Delete all non-superusers</a></li>
        </ul>
        """)


urlpatterns = [
    path("", index, name="index"),
    path("admin/", admin.site.urls),
    path("graphql/", GraphQLView.as_view(graphiql=True)),
    path("login/", auth_views.LoginView.as_view(template_name="admin/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
]
