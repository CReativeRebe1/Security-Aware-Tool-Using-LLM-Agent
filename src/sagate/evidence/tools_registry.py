"""Static classification of the 35 AgentDojo tools (ARCHITECTURE.md §5.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    suite: str
    state_changing: bool
    action: str = "read"                       # read | disclose | delete | modify | invite | transfer | account_change
    resource_arg: str | None = None            # argument naming the affected resource
    destination_args: tuple[str, ...] = ()     # arguments naming who receives data / money / an invite
    content_args: tuple[str, ...] = ()         # free-text arguments that carry data out


_W, _B = "workspace", "banking"

_STATE_CHANGING = [
    ToolSpec("send_email", _W, True, "disclose", "attachments", ("recipients", "cc", "bcc"), ("subject", "body")),
    ToolSpec("share_file", _W, True, "disclose", "file_id", ("email",)),
    ToolSpec("delete_email", _W, True, "delete", "email_id"),
    ToolSpec("delete_file", _W, True, "delete", "file_id"),
    ToolSpec("cancel_calendar_event", _W, True, "delete", "event_id"),
    ToolSpec("create_file", _W, True, "modify", "filename", (), ("content",)),
    ToolSpec("append_to_file", _W, True, "modify", "file_id", (), ("content",)),
    ToolSpec("create_calendar_event", _W, True, "invite", None, ("participants",), ("title", "description")),
    ToolSpec("reschedule_calendar_event", _W, True, "modify", "event_id"),
    ToolSpec("add_calendar_event_participants", _W, True, "invite", "event_id", ("participants",)),
    ToolSpec("send_money", _B, True, "transfer", None, ("recipient",), ("subject",)),
    ToolSpec("schedule_transaction", _B, True, "transfer", None, ("recipient",), ("subject",)),
    ToolSpec("update_scheduled_transaction", _B, True, "transfer", "id", ("recipient",), ("subject",)),
    ToolSpec("update_password", _B, True, "account_change", "password"),
    ToolSpec("update_user_info", _B, True, "account_change", None),
]

_READ_ONLY = {
    _W: ["get_unread_emails", "get_sent_emails", "get_received_emails", "get_draft_emails", "search_emails",
         "search_contacts_by_name", "search_contacts_by_email", "get_current_day", "search_calendar_events",
         "get_day_calendar_events", "search_files_by_filename", "get_file_by_id", "list_files", "search_files"],
    _B: ["get_iban", "get_balance", "get_most_recent_transactions", "get_scheduled_transactions", "read_file",
         "get_user_info"],
}

# Tools whose output contains text written by third parties (emails, files, events, bills, transaction
# subjects). Their output is rendered as <untrusted> data. The remaining read tools return system state.
THIRD_PARTY_OUTPUT = {
    "get_unread_emails", "get_sent_emails", "get_received_emails", "get_draft_emails", "search_emails",
    "search_calendar_events", "get_day_calendar_events", "search_files_by_filename", "get_file_by_id",
    "list_files", "search_files", "read_file", "get_most_recent_transactions", "get_scheduled_transactions",
    "search_contacts_by_name", "search_contacts_by_email",
}

REGISTRY: dict[str, ToolSpec] = {t.name: t for t in _STATE_CHANGING}
for _suite, _names in _READ_ONLY.items():
    for _n in _names:
        REGISTRY[_n] = ToolSpec(_n, _suite, False)


def spec(function: str) -> ToolSpec:
    """Tool spec; unknown (hallucinated) tools are treated as non-state-changing — the runtime rejects them."""
    return REGISTRY.get(function) or ToolSpec(function, "unknown", False, "unknown")


def is_state_changing(function: str) -> bool:
    return spec(function).state_changing


def needs_gate(function: str, gate_read_only: bool = False) -> bool:
    s = spec(function)
    return s.state_changing or (gate_read_only and s.action != "unknown")
