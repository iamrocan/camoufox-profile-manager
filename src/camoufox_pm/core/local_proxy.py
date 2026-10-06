"""A loopback HTTP proxy that can be switched between upstream and direct.

Why this exists
---------------
Playwright configures Firefox's proxy below the WebExtension layer (through
the patched Juggler protocol), so neither ``browser.proxy.settings`` nor
``browser.proxy.onRequest`` can override it from inside the browser. Both
were measured against a live page and both kept routing through the proxy.

So the switch has to live outside the browser. Camoufox is pointed at a
loopback proxy with no credentials, and that proxy decides, per connection,
whether to forward to the real upstream (adding its Proxy-Authorization) or
to open a direct socket to the destination. Flipping the mode is then a
local call, with no browser restart and no Playwright involvement.

It also keeps the upstream credentials inside this process: they are no
longer handed to Playwright on every launch.

Scope: HTTP and HTTPS upstreams. SOCKS needs a different handshake and is
not supported here — the launcher falls back to passing a SOCKS proxy
straight to Playwright, where live toggling is simply unavailable.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from loguru import logger

_CRLF = b"\r\n"
_READ_LIMIT = 65536
# Enough for a request line plus headers; anything larger is not a proxy
# request we are prepared to forward.
_HEADER_LIMIT = 64 * 1024


class _Tunnel:
    """One client connection and the sockets it owns."""

    __slots__ = ("writers",)

    def __init__(self) -> None:
        self.writers: list[asyncio.StreamWriter] = []

    def close(self) -> None:
        for writer in self.writers:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass


class LocalProxy:
    """A loopback proxy that forwards to ``upstream`` or connects directly.

    ``paused`` is read when each connection is established, so a flip takes
    effect for everything opened after it. Connections already tunnelling
    cannot be re-routed — a CONNECT tunnel is opaque once established — so
    flipping also closes the open ones. The browser reconnects on the next
    request, which is what makes the change look immediate.
    """

    def __init__(self, upstream: dict[str, Any], paused: bool = False) -> None:
        self.upstream = upstream
        self.paused = paused
        self.port: int | None = None
        self._server: asyncio.AbstractServer | None = None
        self._tunnels: set[_Tunnel] = set()

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> int:
        """Bind to an ephemeral loopback port and start serving."""
        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", 0, limit=_READ_LIMIT
        )
        self.port = self._server.sockets[0].getsockname()[1]
        logger.info(
            f"Local proxy listening on 127.0.0.1:{self.port} "
            f"(upstream {self.upstream.get('host')}:{self.upstream.get('port')}, "
            f"{'paused' if self.paused else 'active'})"
        )
        return self.port

    async def stop(self) -> None:
        self._close_all_tunnels()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                pass
            self._server = None
        logger.info(f"Local proxy on port {self.port} stopped")

    def set_paused(self, paused: bool) -> None:
        """Switch mode and drop open tunnels so the change is visible now."""
        if self.paused == paused:
            return
        self.paused = paused
        self._close_all_tunnels()
        logger.info(
            f"Local proxy on port {self.port} switched to "
            f"{'direct (paused)' if paused else 'upstream'}"
        )

    def _close_all_tunnels(self) -> None:
        for tunnel in list(self._tunnels):
            tunnel.close()
        self._tunnels.clear()

    # -- connection handling --------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        tunnel = _Tunnel()
        tunnel.writers.append(writer)
        self._tunnels.add(tunnel)
        try:
            head = await self._read_head(reader)
            if head is None:
                return
            request_line, headers_blob = head
            parts = request_line.split()
            if len(parts) < 3:
                await self._fail(writer, 400, "Bad Request")
                return
            method, target = parts[0], parts[1]

            if method.upper() == b"CONNECT":
                await self._do_connect(tunnel, reader, writer, target)
            else:
                await self._do_plain(
                    tunnel, reader, writer, request_line, headers_blob
                )
        except Exception as exc:  # noqa: BLE001 - one bad connection only
            logger.debug(f"Local proxy connection ended: {exc}")
        finally:
            self._tunnels.discard(tunnel)
            tunnel.close()

    async def _read_head(
        self, reader: asyncio.StreamReader
    ) -> tuple[bytes, bytes] | None:
        """Read the request line and headers, returning them separately."""
        try:
            blob = await reader.readuntil(_CRLF + _CRLF)
        except asyncio.IncompleteReadError:
            return None
        except asyncio.LimitOverrunError:
            return None
        except Exception:  # noqa: BLE001
            return None
        if len(blob) > _HEADER_LIMIT:
            return None
        line, _, rest = blob.partition(_CRLF)
        return line, rest

    # -- CONNECT (HTTPS, and anything else tunnelled) --------------------

    async def _do_connect(
        self,
        tunnel: _Tunnel,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        target: bytes,
    ) -> None:
        host, _, port_text = target.decode("latin-1").rpartition(":")
        try:
            port = int(port_text)
        except ValueError:
            await self._fail(writer, 400, "Bad Request")
            return

        if self.paused:
            try:
                up_reader, up_writer = await asyncio.open_connection(host, port)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Direct CONNECT to {host}:{port} failed: {exc}")
                await self._fail(writer, 502, "Bad Gateway")
                return
            tunnel.writers.append(up_writer)
            writer.write(b"HTTP/1.1 200 Connection established" + _CRLF + _CRLF)
            await writer.drain()
        else:
            try:
                up_reader, up_writer = await asyncio.open_connection(
                    self.upstream["host"], self.upstream["port"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Upstream proxy unreachable: {exc}")
                await self._fail(writer, 502, "Bad Gateway")
                return
            tunnel.writers.append(up_writer)

            request = [b"CONNECT " + target + b" HTTP/1.1"]
            request.append(b"Host: " + target)
            auth = self._auth_header()
            if auth:
                request.append(auth)
            up_writer.write(_CRLF.join(request) + _CRLF + _CRLF)
            await up_writer.drain()

            # Relay the upstream's answer verbatim: if it refuses (407, 502),
            # the browser should see that rather than a tunnel that silently
            # goes nowhere.
            try:
                response = await up_reader.readuntil(_CRLF + _CRLF)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Upstream CONNECT gave no response: {exc}")
                await self._fail(writer, 502, "Bad Gateway")
                return
            writer.write(response)
            await writer.drain()
            if b" 200 " not in response.split(_CRLF)[0]:
                logger.warning(
                    f"Upstream refused CONNECT: {response.split(_CRLF)[0]!r}"
                )
                return

        await self._pipe_both(reader, writer, up_reader, up_writer)

    # -- plain HTTP ------------------------------------------------------

    async def _do_plain(
        self,
        tunnel: _Tunnel,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request_line: bytes,
        headers_blob: bytes,
    ) -> None:
        method, target, version = request_line.split(None, 2)
        text = target.decode("latin-1")

        if self.paused:
            # Rewrite the absolute-form request line into origin-form, which
            # is what an origin server expects.
            if text.startswith("http://"):
                without_scheme = text[len("http://") :]
                authority, _, path = without_scheme.partition("/")
                path = "/" + path
            else:
                authority, path = text, "/"
            host, _, port_text = authority.partition(":")
            port = int(port_text) if port_text else 80
            try:
                up_reader, up_writer = await asyncio.open_connection(host, port)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Direct connect to {host}:{port} failed: {exc}")
                await self._fail(writer, 502, "Bad Gateway")
                return
            tunnel.writers.append(up_writer)
            head = (
                method + b" " + path.encode("latin-1") + b" " + version + _CRLF
            ) + self._strip_proxy_headers(headers_blob)
        else:
            try:
                up_reader, up_writer = await asyncio.open_connection(
                    self.upstream["host"], self.upstream["port"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Upstream proxy unreachable: {exc}")
                await self._fail(writer, 502, "Bad Gateway")
                return
            tunnel.writers.append(up_writer)
            headers = self._strip_proxy_headers(headers_blob)
            auth = self._auth_header()
            if auth:
                headers = auth + _CRLF + headers
            head = request_line + _CRLF + headers

        up_writer.write(head)
        await up_writer.drain()
        await self._pipe_both(reader, writer, up_reader, up_writer)

    @staticmethod
    def _strip_proxy_headers(headers_blob: bytes) -> bytes:
        """Drop hop-by-hop proxy headers the client may have sent us."""
        kept = [
            line
            for line in headers_blob.split(_CRLF)
            if not line.lower().startswith(b"proxy-")
        ]
        return _CRLF.join(kept)

    def _auth_header(self) -> bytes | None:
        username = self.upstream.get("username")
        password = self.upstream.get("password")
        if not username:
            return None
        token = base64.b64encode(
            f"{username}:{password or ''}".encode()
        ).decode("ascii")
        return b"Proxy-Authorization: Basic " + token.encode("ascii")

    # -- plumbing --------------------------------------------------------

    @staticmethod
    async def _fail(writer: asyncio.StreamWriter, code: int, reason: str) -> None:
        try:
            writer.write(
                f"HTTP/1.1 {code} {reason}".encode()
                + _CRLF
                + b"Connection: close"
                + _CRLF
                + _CRLF
            )
            await writer.drain()
        except Exception:  # noqa: BLE001 - the client may already be gone
            pass

    @staticmethod
    async def _pipe_both(
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        up_reader: asyncio.StreamReader,
        up_writer: asyncio.StreamWriter,
    ) -> None:
        async def pipe(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                while True:
                    chunk = await reader.read(_READ_LIMIT)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
            except Exception:  # noqa: BLE001 - either side may vanish
                pass
            finally:
                try:
                    writer.close()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(
            pipe(client_reader, up_writer),
            pipe(up_reader, client_writer),
            return_exceptions=True,
        )


class LocalProxyManager:
    """The loopback proxies currently running, one per launched profile."""

    def __init__(self) -> None:
        self._proxies: dict[str, LocalProxy] = {}

    async def start(
        self, profile_id: str, upstream: dict[str, Any], paused: bool
    ) -> int:
        """Start (or replace) the proxy for a profile and return its port."""
        await self.stop(profile_id)
        proxy = LocalProxy(upstream, paused=paused)
        port = await proxy.start()
        self._proxies[profile_id] = proxy
        return port

    async def stop(self, profile_id: str) -> None:
        proxy = self._proxies.pop(profile_id, None)
        if proxy is not None:
            await proxy.stop()

    async def stop_all(self) -> None:
        for profile_id in list(self._proxies):
            await self.stop(profile_id)

    def set_paused(self, profile_id: str, paused: bool) -> bool:
        """Flip a running proxy's mode. False when nothing is running."""
        proxy = self._proxies.get(profile_id)
        if proxy is None:
            return False
        proxy.set_paused(paused)
        return True

    def is_running(self, profile_id: str) -> bool:
        return profile_id in self._proxies


def upstream_from_config(proxy_config: Any) -> dict[str, Any] | None:
    """Build the upstream dict from a ProxyConfig, or None for SOCKS.

    SOCKS needs its own handshake, which this proxy does not implement; the
    caller falls back to handing the proxy to Playwright directly, where
    live toggling is unavailable but everything else still works.
    """
    if proxy_config is None:
        return None
    kind = getattr(proxy_config.type, "value", proxy_config.type)
    if str(kind).lower() not in ("http", "https"):
        return None
    server = proxy_config.server or ""
    host, _, port_text = server.rpartition(":")
    if not host or not port_text.isdigit():
        return None
    return {
        "host": host,
        "port": int(port_text),
        "username": proxy_config.username,
        "password": proxy_config.password,
    }
