"""
Summary: Runs a reader function in a child process that can be killed.
A document file is untrusted input, and a parsing library can be made
to loop or to eat memory by a malformed file. A thread cannot be
stopped from outside; a process can. One child is started the first
time it is needed and reused for every file after that, so the cost of
starting an interpreter is paid once per build rather than once per
file. A call that runs past its time limit ends the child, and the next
call starts a fresh one. On POSIX the child also limits its own address
space; Windows has no such limit, so there the time limit and the size
ceiling on the file are the controls.

This file is part of Extractium™
extractium/readers/isolated.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-15
Last Modified: 2026-09-15
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-09-15"

import atexit
import importlib
import multiprocessing
import multiprocessing.connection
import threading

### Limits ###

# How long one file may take to read before the child is ended. A real
# document of the largest size the readers accept is read in seconds;
# a file that is still going after a minute is a file built to keep a
# parser busy.
READER_TIMEOUT_SECONDS = 60

# The most memory the child may use, where the platform can enforce it.
# Generous for a document; a file that needs more than this to parse is
# not a document. Applied on POSIX only, because Windows offers no
# per-process ceiling a program can set on itself.
READER_MEMORY_BYTES = 2_000_000_000

# How long to wait for an ended child to go away before giving up on
# it. A killed process is gone almost at once; this is a safety margin.
END_GRACE_SECONDS = 5


class IsolationError(Exception):
    """
    Raised when the child could not answer: it ran out of time, it died,
    or it could not be started. The message says which, in words fit
    for a progress line.
    """


### The Child ###

def _serve(connection, memory_bytes):
    """
    The child's loop: receives one job at a time, runs it, and sends the
    result or the error back. Ends when the parent closes the connection.

    Args:
        connection (multiprocessing.connection.Connection): the child's
            end of the pipe.
        memory_bytes (int): the address-space ceiling to set, applied
            only where the platform has the `resource` module.
    """
    _limit_memory(memory_bytes)
    while True:
        try:
            module_name, function_name, args = connection.recv()
        except (EOFError, OSError):
            return
        try:
            function = getattr(importlib.import_module(module_name), function_name)
            connection.send(("ok", function(*args)))
        except BaseException as e:  # noqa: BLE001 -- every failure is reported, none is hidden
            connection.send(("error", type(e).__name__, str(e)))


def _limit_memory(memory_bytes):
    """Caps the process's address space where the platform allows it."""
    try:
        import resource
    except ImportError:  # Windows
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        wanted = memory_bytes if hard == resource.RLIM_INFINITY else min(memory_bytes, hard)
        if soft == resource.RLIM_INFINITY or soft > wanted:
            resource.setrlimit(resource.RLIMIT_AS, (wanted, hard))
    except (ValueError, OSError):
        # A platform that refuses the limit still has the time limit.
        return


### The Parent ###

class RemoteError(Exception):
    """
    The function raised in the child. Carries the exception's type name
    and message so the caller can decide what it meant; no traceback
    and no object crosses the pipe.

    Attributes:
        type_name (str): the exception class's name.
        message (str): its message.
    """

    def __init__(self, type_name, message):
        super().__init__(f"{type_name}: {message}")
        self.type_name = type_name
        self.message = message


class Worker:
    """
    One reusable child process and the pipe to it.

    Calls are serialized by a lock, so sources running in parallel share
    one child and one file is read at a time. That is deliberate: the
    child is the untrusted part of the build, and one of it is enough.
    """

    def __init__(self, memory_bytes=READER_MEMORY_BYTES):
        self.memory_bytes = memory_bytes
        self._lock = threading.Lock()
        self._process = None
        self._connection = None

    def call(self, module_name, function_name, args, timeout=READER_TIMEOUT_SECONDS):
        """
        Runs a function in the child and returns what it returned.

        Args:
            module_name (str): the module the function lives in; it is
                imported in the child, so it must be importable there.
            function_name (str): the function's name in that module.
            args (tuple): the arguments, which must be picklable.
            timeout (float): seconds to wait for an answer.

        Returns:
            The function's return value, which must be picklable.

        Raises:
            IsolationError: if the child ran out of time or died.
            RemoteError: if the function raised; the exception's type
                name and message are carried, never a traceback.
        """
        with self._lock:
            self._ensure_started()
            try:
                self._connection.send((module_name, function_name, args))
                # The child's sentinel is watched beside the pipe, so a
                # child that dies is noticed at once rather than at the
                # end of the time limit.
                ready = multiprocessing.connection.wait(
                    [self._connection, self._process.sentinel], timeout,
                )
                if not ready:
                    self._end()
                    raise IsolationError(f"the reader gave up after {timeout:g} seconds")
                if self._connection not in ready and not self._connection.poll():
                    raise EOFError("the child ended before answering")
                answer = self._connection.recv()
            except (EOFError, OSError, BrokenPipeError) as e:
                self._end()
                raise IsolationError(
                    "the reader stopped unexpectedly, which usually means it ran out of memory"
                ) from e
        if answer[0] == "ok":
            return answer[1]
        raise RemoteError(answer[1], answer[2])

    def shutdown(self):
        """Ends the child, if one is running. Safe to call more than once."""
        with self._lock:
            self._end()

    def _ensure_started(self):
        """Starts the child when there is none, or the last one was ended."""
        if self._process is not None and self._process.is_alive():
            return
        self._end()
        # spawn on every platform: a forked child of a program that runs
        # threads inherits their locks in whatever state they were in.
        context = multiprocessing.get_context("spawn")
        parent_end, child_end = context.Pipe()
        process = context.Process(
            target=_serve, args=(child_end, self.memory_bytes), name="extractium-reader",
        )
        # A daemon child is ended when the parent exits, so a build that
        # is interrupted leaves no reader behind.
        process.daemon = True
        process.start()
        child_end.close()
        self._process = process
        self._connection = parent_end

    def _end(self):
        """Kills the child and drops the pipe."""
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None
        if self._process is not None:
            if self._process.is_alive():
                self._process.kill()
            self._process.join(END_GRACE_SECONDS)
            self._process = None


### The Shared Worker ###

_worker = Worker()
atexit.register(_worker.shutdown)


def run(module_name, function_name, args, timeout=READER_TIMEOUT_SECONDS):
    """
    Runs a function in the build's shared reader process.

    See Worker.call for the arguments, the return value, and what is
    raised.
    """
    return _worker.call(module_name, function_name, args, timeout)


def shutdown():
    """Ends the shared reader process. The next call starts a new one."""
    _worker.shutdown()
