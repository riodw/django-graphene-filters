"""Self-contained test: User → Profile → UserRole one-to-many date-overlap filtering.

Demonstrates the tree-structured filter with AND/OR/NOT logic to replace
a DRF ``custom_role_during`` filter that packs arguments into a pipe-
delimited string (``"role_ids|start_date|end_date"``).

The equivalent GraphQL query uses native filter nesting::

    allUsers(filter: {
      profile: {
        roles: {
          role: { in: [<id>] }
          startDate: { lte: "<end>" }
        }
      }
      or: [
        { profile: { roles: { endDate: { isnull: true } } } }
        { profile: { roles: { endDate: { gte: "<start>" } } } }
      ]
    })

Which produces the same single ``.filter()`` Q as the DRF version::

    Q(profile__roles__role__in=role_ids)
    & Q(profile__roles__start_date__lte=end_date)
    & (Q(profile__roles__end_date__isnull=True) | Q(profile__roles__end_date__gte=start_date))

Everything — models, filters, schema, and tests — lives in this file.
Tables are created/dropped via ``SchemaEditor`` in setUpClass/tearDownClass.

Test data
---------
Roles: Admin, Editor, Viewer

alice   Admin  2026-01-01 → 2026-03-01
        Editor 2026-03-02 → ongoing (null end_date)
bob     Admin  2026-02-15 → 2026-02-28
carol   Admin  2026-01-01 → 2026-02-01  (ended before query range)
dave    Editor 2026-02-20 → 2026-02-28
eve     Admin  2026-03-01 → ongoing     (started after query range)
"""

from datetime import date
from unittest.mock import MagicMock

import graphene
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test import TransactionTestCase
from graphene import Node

from django_graphene_filters import (
    AdvancedDjangoFilterConnectionField,
    AdvancedDjangoObjectType,
    AdvancedFilterSet,
    RelatedFilter,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Models (tables managed by setUpClass / tearDownClass)
# ---------------------------------------------------------------------------


class Role(models.Model):
    name = models.TextField()

    class Meta:
        app_label = "recipes"

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="profile",
        on_delete=models.CASCADE,
    )

    class Meta:
        app_label = "recipes"

    def __str__(self):
        return f"Profile({self.user.username})"


class UserRole(models.Model):
    profile = models.ForeignKey(Profile, related_name="roles", on_delete=models.CASCADE)
    role = models.ForeignKey(Role, related_name="user_roles", on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "recipes"

    def __str__(self):
        return f"{self.profile} - {self.role}"


# ---------------------------------------------------------------------------
# Filters — uses RelatedFilter chains (no cross-relation Meta.fields needed)
# ---------------------------------------------------------------------------


class RoleFilter(AdvancedFilterSet):
    class Meta:
        model = Role
        fields = {"name": ["exact", "icontains"]}


class UserRoleFilter(AdvancedFilterSet):
    role = RelatedFilter(RoleFilter, field_name="role")

    class Meta:
        model = UserRole
        fields = {
            "start_date": ["exact", "lte", "gte"],
            "end_date": ["exact", "lte", "gte", "isnull"],
            "role": ["in"],
        }


class ProfileFilter(AdvancedFilterSet):
    roles = RelatedFilter(UserRoleFilter, field_name="roles")

    class Meta:
        model = Profile
        fields = {}


class UserFilter(AdvancedFilterSet):
    profile = RelatedFilter(ProfileFilter, field_name="profile")

    class Meta:
        model = User
        fields = {"username": ["exact", "icontains"]}


# ---------------------------------------------------------------------------
# Schema (local — not wired into the cookbook's URL router)
# ---------------------------------------------------------------------------


class UserNode(AdvancedDjangoObjectType):
    class Meta:
        model = User
        interfaces = (Node,)
        fields = ["id", "username", "first_name", "last_name"]
        filterset_class = UserFilter


class Query(graphene.ObjectType):
    all_users = AdvancedDjangoFilterConnectionField(UserNode)


schema = graphene.Schema(query=Query)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class UserProfileRoleFilterTests(TransactionTestCase):
    """Date-overlap filtering: users who held specific role(s) during a date range."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # TransactionTestCase doesn't wrap setUpClass in an atomic block,
        # so SQLite allows disabling FK constraints here.
        connection.disable_constraint_checking()
        try:
            with connection.schema_editor() as editor:
                editor.create_model(Role)
                editor.create_model(Profile)
                editor.create_model(UserRole)
        finally:
            connection.enable_constraint_checking()

    @classmethod
    def tearDownClass(cls):
        connection.disable_constraint_checking()
        try:
            with connection.schema_editor() as editor:
                editor.delete_model(UserRole)
                editor.delete_model(Profile)
                editor.delete_model(Role)
        finally:
            connection.enable_constraint_checking()
        super().tearDownClass()

    def setUp(self):
        super().setUp()

        UserRole.objects.all().delete()
        Profile.objects.all().delete()
        Role.objects.all().delete()
        User.objects.filter(is_staff=False).delete()

        # Staff user for context (not matched by filters — has no profile)
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)

        # Roles
        self.admin_role = Role.objects.create(name="Admin")
        self.editor_role = Role.objects.create(name="Editor")
        self.viewer_role = Role.objects.create(name="Viewer")

        # Alice: Admin Jan-Mar, Editor Mar-ongoing
        self.alice = User.objects.create_user(username="alice", password="testpass")
        alice_profile = Profile.objects.create(user=self.alice)
        UserRole.objects.create(
            profile=alice_profile,
            role=self.admin_role,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
        )
        UserRole.objects.create(
            profile=alice_profile,
            role=self.editor_role,
            start_date=date(2026, 3, 2),
            end_date=None,
        )

        # Bob: Admin Feb 15-28
        self.bob = User.objects.create_user(username="bob", password="testpass")
        bob_profile = Profile.objects.create(user=self.bob)
        UserRole.objects.create(
            profile=bob_profile,
            role=self.admin_role,
            start_date=date(2026, 2, 15),
            end_date=date(2026, 2, 28),
        )

        # Carol: Admin Jan 1 - Feb 1 (ended before typical query range)
        self.carol = User.objects.create_user(username="carol", password="testpass")
        carol_profile = Profile.objects.create(user=self.carol)
        UserRole.objects.create(
            profile=carol_profile,
            role=self.admin_role,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )

        # Dave: Editor Feb 20-28
        self.dave = User.objects.create_user(username="dave", password="testpass")
        dave_profile = Profile.objects.create(user=self.dave)
        UserRole.objects.create(
            profile=dave_profile,
            role=self.editor_role,
            start_date=date(2026, 2, 20),
            end_date=date(2026, 2, 28),
        )

        # Eve: Admin Mar 1-ongoing (null end_date)
        self.eve = User.objects.create_user(username="eve", password="testpass")
        eve_profile = Profile.objects.create(user=self.eve)
        UserRole.objects.create(
            profile=eve_profile,
            role=self.admin_role,
            start_date=date(2026, 3, 1),
            end_date=None,
        )

        # ----- Cross-row trap users -----
        # These users have multiple roles where DIFFERENT rows satisfy
        # different filter conditions.  If the filter incorrectly matches
        # across rows, these users would appear in results when they should not.

        # Frank: Admin ENDED before range + Editor ONGOING (overlaps range)
        #   Cross-row bug would combine: role=Admin (row 1) + null end (row 2)
        self.frank = User.objects.create_user(username="frank", password="testpass")
        frank_profile = Profile.objects.create(user=self.frank)
        UserRole.objects.create(
            profile=frank_profile,
            role=self.admin_role,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 1),
        )
        UserRole.objects.create(
            profile=frank_profile,
            role=self.editor_role,
            start_date=date(2026, 2, 15),
            end_date=None,
        )

        # Grace: Admin STARTS after range + Editor OVERLAPS range
        #   Cross-row bug would combine: role=Admin (row 1) + start<=end (row 2)
        self.grace = User.objects.create_user(username="grace", password="testpass")
        grace_profile = Profile.objects.create(user=self.grace)
        UserRole.objects.create(
            profile=grace_profile,
            role=self.admin_role,
            start_date=date(2026, 3, 1),
            end_date=None,
        )
        UserRole.objects.create(
            profile=grace_profile,
            role=self.editor_role,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _execute(self, query):
        """Execute a GraphQL query against the local schema."""
        context = MagicMock()
        context.user = self.staff_user
        result = schema.execute(query, context_value=context)
        self.assertIsNone(result.errors, f"GraphQL errors: {result.errors}")
        return result.data

    def _get_usernames(self, data):
        return sorted(e["node"]["username"] for e in data["allUsers"]["edges"])

    def _role_during_query(self, role_ids, start, end):
        """Build and execute the role-during-date-range filter query.

        Equivalent to the DRF filter::

            queryset.filter(
                Q(profile__roles__end_date__isnull=True)
                | Q(profile__roles__end_date__gte=start),
                profile__roles__role__in=role_ids,
                profile__roles__start_date__lte=end,
            ).distinct()
        """
        ids_str = ", ".join(str(rid) for rid in role_ids)
        query = f"""
            query {{
              allUsers(filter: {{
                profile: {{
                  roles: {{
                    role: {{ in: [{ids_str}] }}
                    startDate: {{ lte: "{end}" }}
                  }}
                }}
                or: [
                  {{ profile: {{ roles: {{ endDate: {{ isnull: true }} }} }} }}
                  {{ profile: {{ roles: {{ endDate: {{ gte: "{start}" }} }} }} }}
                ]
              }}) {{
                edges {{
                  node {{
                    username
                  }}
                }}
              }}
            }}
        """
        data = self._execute(query)
        return self._get_usernames(data)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_admin_during_feb_26_27(self):
        """Users with Admin role during 2026-02-26 to 2026-02-27.

        alice: Admin Jan-Mar, overlaps ✓
        bob:   Admin Feb 15-28, overlaps ✓
        carol: Admin Jan-Feb 1, end_date(Feb 1) < start(Feb 26) ✗
        dave:  Editor, wrong role ✗
        eve:   Admin Mar-ongoing, start_date(Mar 1) > end(Feb 27) ✗
        frank: Admin ended Feb 1 ✗ (Editor ongoing is wrong role) ✗
        grace: Admin starts Mar 1 ✗ (Editor overlaps but wrong role) ✗
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-02-26", "2026-02-27")
        self.assertEqual(usernames, ["alice", "bob"])

    def test_multiple_role_ids(self):
        """Admin OR Editor during 2026-02-26 to 2026-02-27.

        alice: Admin overlaps ✓
        bob:   Admin overlaps ✓
        dave:  Editor Feb 20-28 overlaps ✓
        frank: Editor Feb 15-ongoing overlaps ✓ (same row matches all conditions)
        grace: Editor Feb 1-28 overlaps ✓ (same row matches all conditions)
        carol: Admin ended Feb 1 ✗
        eve:   Admin started Mar 1 ✗
        """
        usernames = self._role_during_query(
            [self.admin_role.id, self.editor_role.id],
            "2026-02-26",
            "2026-02-27",
        )
        self.assertEqual(usernames, ["alice", "bob", "dave", "frank", "grace"])

    def test_null_end_date_matches(self):
        """Query range Apr 1-30: only roles with null end_date or end >= Apr 1 match.

        eve:   Admin Mar 1-ongoing, start(Mar 1) <= Apr 30 ✓, end NULL ✓
        grace: Admin Mar 1-ongoing, start(Mar 1) <= Apr 30 ✓, end NULL ✓
        frank: Admin ended Feb 1 ✗ (Editor ongoing is wrong role) ✗
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-04-01", "2026-04-30")
        self.assertEqual(usernames, ["eve", "grace"])

    def test_no_match_before_any_role(self):
        """Query range entirely before any Admin assignment → empty result."""
        usernames = self._role_during_query([self.admin_role.id], "2025-12-01", "2025-12-31")
        self.assertEqual(usernames, [])

    def test_viewer_role_no_assignments(self):
        """Viewer has zero assignments → empty for any date range."""
        usernames = self._role_during_query([self.viewer_role.id], "2026-01-01", "2026-12-31")
        self.assertEqual(usernames, [])

    def test_exact_boundary_end_date_equals_start(self):
        """bob's end_date (Feb 28) equals query start → overlap on that day.

        alice: Admin Jan-Mar 1 → end(Mar 1) >= start(Feb 28) ✓
        bob:   Admin Feb 15-28 → end(28) >= start(28) ✓
        eve:   Admin Mar 1-null → start(Mar 1) <= end(Mar 15) ✓, null end ✓
        grace: Admin Mar 1-null → same as eve ✓
        carol: Admin Jan-Feb 1 → end(Feb 1) >= start(Feb 28) ✗
        frank: Admin Jan-Feb 1 → end(Feb 1) >= start(Feb 28) ✗
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-02-28", "2026-03-15")
        self.assertEqual(usernames, ["alice", "bob", "eve", "grace"])

    def test_exact_boundary_start_date_equals_end(self):
        """eve's start_date (Mar 1) equals query end → overlap on that day.

        alice: Admin Jan-Mar 1 → end(Mar 1) >= start(Mar 1) ✓
        eve:   Admin Mar 1-null → start(Mar 1) <= end(Mar 1) ✓, null end ✓
        grace: Admin Mar 1-null → same as eve ✓
        bob:   Admin Feb 15-28 → end(Feb 28) >= start(Mar 1) ✗
        carol: Admin Jan-Feb 1 → end(Feb 1) >= start(Mar 1) ✗
        frank: Admin Jan-Feb 1 → end(Feb 1) >= start(Mar 1) ✗
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-03-01", "2026-03-01")
        self.assertEqual(usernames, ["alice", "eve", "grace"])

    def test_staff_user_excluded_by_join(self):
        """Staff user has no profile → excluded by the inner join, never in results."""
        usernames = self._role_during_query(
            [self.admin_role.id, self.editor_role.id, self.viewer_role.id],
            "2000-01-01",
            "2099-12-31",
        )
        self.assertNotIn("staff", usernames)

    # ------------------------------------------------------------------
    # Cross-row integrity: all conditions must match the SAME UserRole row
    # ------------------------------------------------------------------

    def test_cross_row_trap_frank(self):
        """Frank must NOT match 'Admin during Feb 26-27'.

        Frank has two roles that TOGETHER would satisfy all conditions
        but NO SINGLE ROW does:
          - Admin Jan 1 - Feb 1:  role=Admin ✓, start<=Feb27 ✓, end(Feb1)>=Feb26 ✗
          - Editor Feb 15 - null: role=Editor ✗ (not Admin)

        A cross-row bug would combine Admin from row 1 + null end from row 2
        and incorrectly match Frank.
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-02-26", "2026-02-27")
        self.assertNotIn("frank", usernames)

    def test_cross_row_trap_grace(self):
        """Grace must NOT match 'Admin during Feb 26-27'.

        Grace has two roles that TOGETHER would satisfy all conditions
        but NO SINGLE ROW does:
          - Admin Mar 1 - null:   role=Admin ✓, start(Mar1)<=Feb27 ✗
          - Editor Feb 1 - Feb 28: role=Editor ✗ (not Admin)

        A cross-row bug would combine Admin from row 1 + start<=end from row 2
        and incorrectly match Grace.
        """
        usernames = self._role_during_query([self.admin_role.id], "2026-02-26", "2026-02-27")
        self.assertNotIn("grace", usernames)

    def test_cross_row_users_match_when_single_row_qualifies(self):
        """Frank and Grace DO match when querying a role they actually held during the range.

        This confirms they're not globally excluded - they just don't have
        a qualifying Admin row for Feb 26-27.  Their Editor rows DO qualify
        for 'Editor during Feb 26-27'.

        frank: Editor Feb 15-null → role=Editor ✓, start<=Feb27 ✓, end NULL ✓
        grace: Editor Feb 1-28   → role=Editor ✓, start<=Feb27 ✓, end>=Feb26 ✓
        """
        usernames = self._role_during_query([self.editor_role.id], "2026-02-26", "2026-02-27")
        self.assertIn("frank", usernames)
        self.assertIn("grace", usernames)
