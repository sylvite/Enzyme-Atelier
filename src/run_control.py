"""Cooperative cancellation checked at workflow tool boundaries."""
class RunCancelled(Exception):
    pass


def check_cancelled(cancel_requested):
    if cancel_requested is not None and cancel_requested():
        raise RunCancelled("Cancellation requested")
