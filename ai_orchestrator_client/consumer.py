"""Consumer-side integration helpers (Phase 3.6).

A *consumer* is an external research project that registers with the
orchestrator, declares capabilities, and exposes capability handlers the
orchestrator can dispatch work to.

This module is deliberately **web-framework-free**: :class:`Consumer`
provides a capability registry and a framework-agnostic
:meth:`Consumer.dispatch` coroutine. The consumer project wires
``dispatch`` into whatever HTTP server it already runs (FastAPI, Flask,
…) — the SDK never imports a web framework.

Usage::

    from ai_orchestrator_client import Consumer, capability

    class RfdfConsumer(Consumer):
        name = "rfdf"

        @capability("rf.doa.run")
        async def run_doa(self, payload: dict) -> dict:
            ...

    consumer = RfdfConsumer()
    consumer.register(client, base_url="http://rfdf.lan:8000",
                      callback_token="…")
    # in the consumer's POST /capabilities/{cap} handler:
    result = await consumer.dispatch(cap, payload)
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ._errors import UnknownCapabilityError
from .models import (
    ConsumerAck,
    ConsumerRegistration,
    HealthReport,
)

if TYPE_CHECKING:
    from .sync_client import OrchestratorClient

# Attribute the decorator stamps onto a method to mark it a capability.
_CAPABILITY_ATTR = "_aoc_capability"


def capability(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a :class:`Consumer` method as the handler for ``name``.

    The decorated method is registered under the dotted capability name
    (``rf.doa.run``) and invoked by :meth:`Consumer.dispatch`. The method
    may be sync or async and takes a single ``payload`` dict argument.
    """

    def _decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, _CAPABILITY_ATTR, name)
        return func

    return _decorate


class Consumer:
    """Base class for an orchestrator consumer.

    Subclasses set the class attribute ``name`` and decorate handler
    methods with :func:`capability`. The capability registry is built
    once per subclass at class-creation time.
    """

    #: Registry name — subclasses MUST override.
    name: str = ""

    # Populated per-subclass by __init_subclass__: {capability: method_name}.
    _capability_methods: dict[str, str] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        methods: dict[str, str] = {}
        # Walk the full MRO so a subclass inherits a base's capabilities.
        for klass in reversed(cls.__mro__):
            for attr_name, attr in vars(klass).items():
                cap_name = getattr(attr, _CAPABILITY_ATTR, None)
                if cap_name is not None:
                    methods[cap_name] = attr_name
        cls._capability_methods = methods

    @property
    def capabilities(self) -> list[str]:
        """Sorted list of capability names this consumer offers."""
        return sorted(self._capability_methods)

    def to_registration(
        self,
        base_url: str,
        *,
        callback_token: str | None = None,
        description: str = "",
        extra_capabilities: list[str] | None = None,
    ) -> ConsumerRegistration:
        """Build the :class:`ConsumerRegistration` payload for this consumer.

        ``extra_capabilities`` appends generic data-plane grants
        (``memory.write`` / ``vault.write`` / ``notify.send`` /
        ``evidence.push``) that have no decorated handler — declaring
        them opts the consumer into the matching push endpoints.
        """
        caps = sorted(set(self.capabilities) | set(extra_capabilities or []))
        return ConsumerRegistration(
            consumer_id=self.name,
            name=self.name,
            base_url=base_url,
            capabilities=caps,
            callback_token=callback_token,
            description=description,
        )

    def register(
        self,
        client: OrchestratorClient,
        base_url: str,
        *,
        callback_token: str | None = None,
        description: str = "",
        extra_capabilities: list[str] | None = None,
    ) -> ConsumerAck:
        """Register this consumer with the orchestrator via a sync client."""
        return client.register_consumer(
            self.to_registration(
                base_url,
                callback_token=callback_token,
                description=description,
                extra_capabilities=extra_capabilities,
            )
        )

    def health(self) -> HealthReport:
        """Return this consumer's self-reported health."""
        return HealthReport(
            name=self.name, status="ok", capabilities=self.capabilities
        )

    async def dispatch(self, capability_name: str, payload: dict[str, Any]) -> Any:
        """Invoke the handler for ``capability_name`` with ``payload``.

        The framework-agnostic entry point: a consumer's HTTP layer
        calls this from its ``POST /capabilities/{cap}`` route. Handles
        both sync and async capability methods.

        Raises :class:`UnknownCapabilityError` when no handler matches.
        """
        method_name = self._capability_methods.get(capability_name)
        if method_name is None:
            raise UnknownCapabilityError(capability_name)
        method = getattr(self, method_name)
        result = method(payload)
        if inspect.isawaitable(result):
            return await result
        return result


class Hindsight:
    """Thin Hindsight-memory writer bound to one consumer.

    ``Hindsight(client, "rfdf").write("…")`` is shorthand for
    ``client.write_memory("rfdf", "…")``.
    """

    def __init__(self, client: OrchestratorClient, consumer_id: str) -> None:
        self._client = client
        self._consumer_id = consumer_id

    def write(self, content: str) -> dict[str, Any]:
        """Push a Hindsight memory entry."""
        return self._client.write_memory(self._consumer_id, content)


class Vault:
    """Thin L5-vault note writer bound to one consumer."""

    def __init__(self, client: OrchestratorClient, consumer_id: str) -> None:
        self._client = client
        self._consumer_id = consumer_id

    def write_note(
        self, title: str, body: str, tags: list[str] | None = None
    ) -> dict[str, Any]:
        """Write an L5 vault note."""
        from .models import VaultNote

        return self._client.write_vault_note(
            self._consumer_id,
            VaultNote(title=title, body=body, tags=tags or []),
        )


class Ntfy:
    """Thin notification sender bound to one consumer."""

    def __init__(self, client: OrchestratorClient, consumer_id: str) -> None:
        self._client = client
        self._consumer_id = consumer_id

    def alert(
        self,
        title: str,
        message: str,
        priority: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fire an ntfy/Gotify notification."""
        from .models import Notification

        return self._client.send_notification(
            self._consumer_id,
            Notification(
                title=title, message=message, priority=priority, tags=tags or []
            ),
        )
