"""The allowlist and fresh-session requirements apply to both approval operations."""

from datetime import timedelta

from haynes_studio.api.errors import forbidden


def require_approver(actor, settings, now):
    principal = actor.principal
    if principal.kind != "human":
        raise forbidden("approval.approver_not_permitted", "Go-live requires a signed-in person")
    allowed = settings.go_live_approver_subjects
    if not allowed:
        raise forbidden("approval.approver_not_configured", "No go-live approvers are configured")
    if principal.iss != settings.issuer or principal.sub not in allowed:
        if actor.group_session:
            raise forbidden("approval.group_not_permitted", "Studio group access grants sign-in only")
        raise forbidden("approval.subject_not_permitted", "This subject is outside the go-live allowlist")
    window = timedelta(seconds=settings.go_live_freshness_seconds)
    if actor.auth_time is None or not timedelta(0) <= now - actor.auth_time <= window:
        raise forbidden("approval.sign_in_again", "Sign in again to make a go-live decision")
