"""Static registry of the 35 AgentDojo workspace + banking tools.

For each tool: whether it changes state (only those are gated), its action class, which argument names the
affected resource, which arguments name a destination (who receives data or money), and whether its output
carries third-party content (text written by someone other than the user or the system).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    suite: str
    state_changing: bool
    action_class: str                      # read | disclose | delete | modify | invite | transfer | account_change
    resource_arg: str | None = None
    destination_args: tuple[str, ...] = ()
    content_args: tuple[str, ...] = ()     # arguments whose text leaves the user's control
    third_party_output: bool = False


def _r(name: str, suite: str, third_party: bool = True) -> ToolSpec:
    return ToolSpec(name, suite, False, "read", third_party_output=third_party)


_SPECS = [
    # workspace — email
    ToolSpec("send_email", "workspace", True, "disclose", "attachments", ("recipients", "cc", "bcc"),
             ("subject", "body")),
    ToolSpec("delete_email", "workspace", True, "delete", "email_id"),
    _r("get_unread_emails", "workspace"), _r("get_sent_emails", "workspace"),
    _r("get_received_emails", "workspace"), _r("get_draft_emails", "workspace"),
    _r("search_emails", "workspace"), _r("search_contacts_by_name", "workspace"),
    _r("search_contacts_by_email", "workspace"),
    _r("get_current_day", "workspace", third_party=False),
    # workspace — calendar
    _r("search_calendar_events", "workspace"), _r("get_day_calendar_events", "workspace"),
    ToolSpec("create_calendar_event", "workspace", True, "invite", None, ("participants",),
             ("title", "description")),
    ToolSpec("cancel_calendar_event", "workspace", True, "delete", "event_id"),
    ToolSpec("reschedule_calendar_event", "workspace", True, "modify", "event_id"),
    ToolSpec("add_calendar_event_participants", "workspace", True, "invite", "event_id", ("participants",)),
    # workspace — cloud drive
    ToolSpec("append_to_file", "workspace", True, "modify", "file_id", (), ("content",)),
    _r("search_files_by_filename", "workspace"),
    ToolSpec("create_file", "workspace", True, "modify", "filename", (), ("content",)),
    ToolSpec("delete_file", "workspace", True, "delete", "file_id"),
    _r("get_file_by_id", "workspace"), _r("list_files", "workspace"),
    ToolSpec("share_file", "workspace", True, "disclose", "file_id", ("email",)),
    _r("search_files", "workspace"),
    # banking
    _r("get_iban", "banking", third_party=False),
    ToolSpec("send_money", "banking", True, "transfer", None, ("recipient",), ("subject",)),
    ToolSpec("schedule_transaction", "banking", True, "transfer", None, ("recipient",), ("subject",)),
    ToolSpec("update_scheduled_transaction", "banking", True, "transfer", "id", ("recipient",), ("subject",)),
    _r("get_balance", "banking", third_party=False),
    _r("get_most_recent_transactions", "banking"),       # incoming transaction subjects are third-party text
    _r("get_scheduled_transactions", "banking"),
    _r("read_file", "banking"),
    _r("get_user_info", "banking", third_party=False),
    ToolSpec("update_password", "banking", True, "account_change", None),
    ToolSpec("update_user_info", "banking", True, "account_change", None),
]

REGISTRY: dict[str, ToolSpec] = {s.name: s for s in _SPECS}
STATE_CHANGING = frozenset(n for n, s in REGISTRY.items() if s.state_changing)


def spec(function: str) -> ToolSpec:
    """Spec for a tool; unknown tools are treated as state-changing so they are never waved through."""
    return REGISTRY.get(function) or ToolSpec(function, "unknown", True, "unknown")


def is_state_changing(function: str) -> bool:
    return spec(function).state_changing
