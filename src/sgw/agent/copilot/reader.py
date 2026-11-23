"""Who is asking: one `<reader>` line for the planner, the analysts and the writer. It names the
signed-in role, the team name the decision board uses for its signatures, whether the role may sign at all,
and the pages it can open, so answers and links fit the person instead of a generic duty officer."""

from __future__ import annotations

from sgw.agent.copilot import platform_map as pm

READ_ONLY_FUNCTIONS = frozenset({"audit"})


def team(function: str) -> str:
    from sgw.api.readmodels.notifications import FUNCTION_LABEL

    return FUNCTION_LABEL.get(function, function.replace("_", " ").capitalize())


def reader_line(function: str) -> str:
    pages = [p.label for p in pm.pages().values() if p.open_to(function)]
    signs = (
        "This role is read-only: it signs nothing; say who signs instead."
        if function in READ_ONLY_FUNCTIONS
        else f'Decisions "signed by" a list that includes {team(function)} are this person\'s to sign.'
    )
    return (
        f"<reader>Signed in as {pm.role_label(function)} (team {team(function)}). {signs} Pages this"
        f" person can open: {', '.join(pages)}. Put first what this role decides or watches.</reader>"
    )
