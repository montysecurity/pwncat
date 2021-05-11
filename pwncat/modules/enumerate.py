#!/usr/bin/env python3
import time
import typing
import fnmatch
from enum import Enum, auto

import persistent

import pwncat
from pwncat.modules import List, Status, Argument, BaseModule
from pwncat.platform.linux import Linux


class Schedule(Enum):
    """Defines how often an enumeration module will run"""

    ALWAYS = auto()
    PER_USER = auto()
    ONCE = auto()


class EnumerateModule(BaseModule):
    """Base class for all enumeration modules"""

    # List of categories/enumeration types this module provides
    # This should be set by the sub-classes to know where to find
    # different types of enumeration data
    PROVIDES = []
    PLATFORM = []

    # Defines how often to run this enumeration. The default is to
    # only run once per system/target.
    SCHEDULE = Schedule.ONCE

    # Arguments which all enumeration modules should take
    # This shouldn't be modified. Enumeration modules don't take any
    # parameters
    ARGUMENTS = {
        "types": Argument(
            List(str),
            default=[],
            help="A list of enumeration types to retrieve (default: all)",
        ),
        "clear": Argument(
            bool,
            default=False,
            help="If specified, do not perform enumeration. Cleared cached results.",
        ),
    }

    def run(
        self, session: "pwncat.manager.Session", types: typing.List[str], clear: bool
    ):
        """Locate all facts this module provides.

        Sub-classes should not override this method. Instead, use the
        enumerate method. `run` will cross-reference with database and
        ensure enumeration modules aren't re-run.

        :param session: the session on which to run the module
        :type session: pwncat.manager.Session
        :param types: list of requested fact types
        :type types: List[str]
        :param clear: whether to clear all cached enumeration data
        :type clear: bool
        """

        # Retrieve the DB target object
        target = session.target

        if clear:
            # Filter out all facts which were generated by this module
            target.facts = persistent.list.PersistentList(
                (f for f in target.facts if f.source != self.name)
            )

            # Remove the enumeration state if available
            if self.name in target.enumerate_state:
                del target.enumerate_state[self.name]

            # Commit database changes
            session.db.transaction_manager.commit()

            return

        # Yield all the know facts which have already been enumerated
        if types:
            yield from (
                f
                for f in target.facts
                if f.source == self.name
                and any(
                    any(fnmatch.fnmatch(item_type, req_type) for req_type in types)
                    for item_type in f.types
                )
            )
        else:
            yield from (f for f in target.facts if f.source == self.name)

        # Check if the module is scheduled to run now
        if (self.name in target.enumerate_state) and (
            (self.SCHEDULE == Schedule.ONCE and self.name in target.enumerate_state)
            or (
                self.SCHEDULE == Schedule.PER_USER
                and session.platform.getuid() in target.enumerate_state[self.name]
            )
        ):
            return

        # Get any new facts
        try:
            for item in self.enumerate(session):

                # Allow non-fact status updates
                if isinstance(item, Status):
                    yield item
                    continue

                # Only add the item if it doesn't exist
                if item not in target.facts:
                    target.facts.append(item)

                # Don't yield the actual fact if we didn't ask for this type
                if not types or any(
                    any(fnmatch.fnmatch(item_type, req_type) for req_type in types)
                    for item_type in item.types
                ):
                    yield item
                else:
                    yield Status(item)

            # Update state for restricted modules
            if self.SCHEDULE == Schedule.ONCE:
                target.enumerate_state[self.name] = True
            elif self.SCHEDULE == Schedule.PER_USER:
                if not self.name in target.enumerate_state:
                    target.enumerate_state[self.name] = persistent.list.PersistentList()
                target.enumerate_state[self.name].append(session.platform.getuid())
        finally:
            # Commit database changes
            session.db.transaction_manager.commit()

    def enumerate(self, session):
        """
        Defined by sub-classes to do the actual enumeration of
        facts.
        """
