"""MCP keys and access from an external SQL Server database.

Connections with ``auth_type == 'external_db'`` look up the signed-in user's
API key for that server from an admin-configured SQL Server database. A user
can only use the connection when the lookup returns a key whose server name
matches the connection's Access Variable (or its ID when none is set). The key
goes into headers that use ``{{MCP_KEY}}`` or ``{{<access variable>}}``, or
else is sent as the bearer token.

The configured query runs once per user (by email) and its result is cached,
so listing tools, connecting and calling tools share one lookup.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from open_webui.models.config import Config

log = logging.getLogger(__name__)

AUTH_TYPE = 'external_db'

CONFIG_KEYS = {
    'ENABLE': 'mcp_key_db.enable',
    'HOST': 'mcp_key_db.host',
    'PORT': 'mcp_key_db.port',
    'DATABASE': 'mcp_key_db.database',
    'USERNAME': 'mcp_key_db.username',
    'PASSWORD': 'mcp_key_db.password',
    'QUERY': 'mcp_key_db.query',
    'CACHE_TTL': 'mcp_key_db.cache_ttl',
    'TIMEOUT': 'mcp_key_db.timeout',
    'CONNECTION_STRING': 'mcp_key_db.connection_string',
}

DEFAULT_QUERY = """SELECT DISTINCT g.Server, k.ApiKey
FROM dbo.ApiKeys k
JOIN dbo.ToolGrants g ON g.ApiKey = k.ApiKey
WHERE k.Owner = @email"""

DEFAULTS = {
    'ENABLE': False,
    'HOST': '',
    'PORT': 1433,
    'DATABASE': '',
    'USERNAME': '',
    'PASSWORD': '',
    'QUERY': DEFAULT_QUERY,
    'CACHE_TTL': 300,
    'TIMEOUT': 10,
    'CONNECTION_STRING': '',
}

# Connection string keywords (ADO.NET / ODBC style), lowercased.
SERVER_KEYS = {'server', 'data source', 'address', 'addr', 'network address', 'host'}
DATABASE_KEYS = {'database', 'initial catalog'}
USERNAME_KEYS = {'user id', 'uid', 'user', 'username', 'user name'}
PASSWORD_KEYS = {'password', 'pwd'}
TIMEOUT_KEYS = {'connect timeout', 'connection timeout', 'login timeout', 'timeout'}
TRUE_VALUES = {'true', 'yes', 'sspi'}

# Replaces the password in a connection string sent to the browser.
PASSWORD_MASK = '********'

# Failed lookups are cached briefly so an unreachable database is not hit on
# every request, but recovers quickly once it is back.
FAILURE_CACHE_TTL = 30

EMAIL_PLACEHOLDER_RE = re.compile(r'@email\b', re.IGNORECASE)

# Lets a connection's custom headers carry the key, e.g. X-Api-Key: {{MCP_KEY}}.
KEY_PLACEHOLDER_RE = re.compile(r'\{\{\s*MCP_KEY\s*\}\}')

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_locks: dict[str, asyncio.Lock] = {}


class McpKeyDbError(Exception):
    pass


async def get_settings() -> dict[str, Any]:
    values = await Config.get_many(*CONFIG_KEYS.values())
    return {
        field: values[storage_key] if values.get(storage_key) is not None else DEFAULTS[field]
        for field, storage_key in CONFIG_KEYS.items()
    }


def clear_cache() -> None:
    _cache.clear()


def _tokenize(connection_string: str) -> list[tuple[str, str, int, int]]:
    """Split ``key=value;`` pairs into (key, value, value_start, value_end).

    Values may be wrapped in quotes or ``{}`` (doubling the closing character
    escapes it), which lets them contain ``;``. Error messages never include
    the string itself, since it may hold a password.
    """
    s = connection_string
    n = len(s)
    i = 0
    tokens = []
    while i < n:
        while i < n and s[i] in ' \t\r\n;':
            i += 1
        if i >= n:
            break

        eq = s.find('=', i)
        if eq == -1:
            raise McpKeyDbError('Invalid connection string: expected key=value pairs separated by ;')
        key = s[i:eq].strip().lower()

        j = eq + 1
        while j < n and s[j] in ' \t':
            j += 1

        if j < n and s[j] in '"\'{':
            close = '}' if s[j] == '{' else s[j]
            k = j + 1
            chars = []
            while True:
                if k >= n:
                    raise McpKeyDbError(f'Invalid connection string: unterminated value for "{key}"')
                if s[k] == close:
                    if k + 1 < n and s[k + 1] == close:
                        chars.append(close)
                        k += 2
                        continue
                    k += 1
                    break
                chars.append(s[k])
                k += 1
            value, end = ''.join(chars), k
            while k < n and s[k] in ' \t':
                k += 1
            if k < n and s[k] != ';':
                raise McpKeyDbError(f'Invalid connection string: unexpected text after "{key}"')
            i = k
        else:
            k = s.find(';', j)
            k = n if k == -1 else k
            raw = s[j:k].rstrip()
            value, end = raw, j + len(raw)
            i = k

        tokens.append((key, value, j, end))
    return tokens


def parse_connection_string(connection_string: str) -> tuple[dict[str, Any], list[str]]:
    """Read connection settings from a connection string.

    Returns (settings, ignored_keys). Supports ``Server=host,port`` (with an
    optional ``tcp:`` prefix), ``Database``/``Initial Catalog``,
    ``User Id``/``UID``, ``Password``/``PWD`` and ``Connect Timeout``.
    """
    settings: dict[str, Any] = {}
    ignored: list[str] = []

    for key, value, _, _ in _tokenize(connection_string):
        if key in SERVER_KEYS:
            server = value.strip()
            if server.lower().startswith('tcp:'):
                server = server[4:]
            elif server.lower().startswith(('np:', 'lpc:')):
                raise McpKeyDbError('Only TCP connections are supported; use Server=tcp:host,port')
            if ',' in server:
                server, port = server.rsplit(',', 1)
                settings['PORT'] = _parse_int(port, 'port')
            settings['HOST'] = server.strip()
        elif key == 'port':
            settings['PORT'] = _parse_int(value, 'port')
        elif key in DATABASE_KEYS:
            settings['DATABASE'] = value
        elif key in USERNAME_KEYS:
            settings['USERNAME'] = value
        elif key in PASSWORD_KEYS:
            settings['PASSWORD'] = value
        elif key in TIMEOUT_KEYS:
            settings['TIMEOUT'] = min(max(_parse_int(value, 'timeout'), 1), 60)
        elif key in ('integrated security', 'trusted_connection'):
            if value.strip().lower() in TRUE_VALUES:
                raise McpKeyDbError(
                    'Windows integrated authentication is not supported; '
                    'set User Id (a SQL login or DOMAIN\\user) and Password'
                )
        else:
            ignored.append(key)

    if not settings.get('HOST'):
        raise McpKeyDbError('The connection string must include Server')
    return settings, ignored


def _parse_int(value: str, name: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise McpKeyDbError(f'Invalid {name} in connection string') from None


def _password_span(connection_string: str) -> tuple[int, int] | None:
    """Where the raw password value (including any quotes or braces) sits, if set."""
    span = None
    for key, value, start, end in _tokenize(connection_string):
        if key in PASSWORD_KEYS and value:
            span = (start, end)
    return span


def redact_connection_string(connection_string: str) -> str:
    """Replace the password with ``PASSWORD_MASK`` so the string can be shown."""
    if not connection_string:
        return ''
    try:
        span = _password_span(connection_string)
    except McpKeyDbError:
        return ''
    if not span:
        return connection_string
    return connection_string[: span[0]] + PASSWORD_MASK + connection_string[span[1] :]


def restore_connection_string(connection_string: str, saved: str) -> str:
    """Put the saved password back where the browser sent ``PASSWORD_MASK``."""
    span = _password_span(connection_string)
    if not span or connection_string[span[0] : span[1]] != PASSWORD_MASK:
        return connection_string

    saved_span = _password_span(saved) if saved else None
    if not saved_span:
        raise McpKeyDbError('Enter the connection string password again')
    return connection_string[: span[0]] + saved[saved_span[0] : saved_span[1]] + connection_string[span[1] :]


def effective_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings with the connection string, when set, overriding the separate fields."""
    connection_string = str(settings.get('CONNECTION_STRING') or '').strip()
    if not connection_string:
        return settings
    overrides, _ = parse_connection_string(connection_string)
    return {**settings, **overrides}


def normalize_server(server: Any) -> str:
    return str(server).strip().casefold() if server is not None else ''


def to_pyformat(query: str) -> str:
    """Turn ``@email`` into pymssql's ``%(email)s``, escaping literal ``%``."""
    return EMAIL_PLACEHOLDER_RE.sub('%(email)s', query.replace('%', '%%'))


def rows_to_entitlements(rows: list) -> dict[str, str]:
    """Map rows of (server, key) to {server: key}.

    Rows missing either value are skipped. When several keys grant the same
    server, the lowest key is used so the choice is stable between lookups.
    """
    entitlements: dict[str, str] = {}
    conflicts: set[str] = set()
    for row in rows:
        if len(row) < 2:
            continue
        server = normalize_server(row[0])
        key = str(row[1]).strip() if row[1] is not None else ''
        if not server or not key:
            continue
        if server in entitlements and entitlements[server] != key:
            conflicts.add(server)
            key = min(key, entitlements[server])
        entitlements[server] = key

    if conflicts:
        log.warning('MCP key database returned several keys for servers: %s', ', '.join(sorted(conflicts)))
    return entitlements


def _query_rows(settings: dict[str, Any], email: str) -> list:
    try:
        import pymssql
    except ImportError as e:
        raise McpKeyDbError('The pymssql package is not installed') from e

    timeout = int(settings.get('TIMEOUT') or DEFAULTS['TIMEOUT'])
    conn = pymssql.connect(
        server=str(settings['HOST']).strip(),
        port=str(settings.get('PORT') or DEFAULTS['PORT']),
        user=settings.get('USERNAME') or None,
        password=settings.get('PASSWORD') or None,
        database=settings.get('DATABASE') or '',
        login_timeout=timeout,
        timeout=timeout,
        appname='open-webui',
    )
    try:
        cursor = conn.cursor()
        cursor.execute(to_pyformat(settings['QUERY']), {'email': email})
        return cursor.fetchall()
    finally:
        conn.close()


async def fetch_entitlements(settings: dict[str, Any], email: str) -> dict[str, str]:
    """Run the configured query for one email, without the cache. Raises on failure."""
    settings = effective_settings(settings)
    if not str(settings.get('HOST') or '').strip():
        raise McpKeyDbError('No database host configured')
    if '@email' not in str(settings.get('QUERY') or '').lower():
        raise McpKeyDbError('The query must use @email for the user email')

    rows = await asyncio.to_thread(_query_rows, settings, email)
    return rows_to_entitlements(rows)


async def get_mcp_entitlements(email: str) -> dict[str, str]:
    """Return {server: key} for a user email, cached. Returns {} when disabled or on error."""
    email = (email or '').strip()
    if not email:
        return {}

    cache_key = email.casefold()
    cached = _cache.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    lock = _locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        settings = await get_settings()
        if not settings['ENABLE']:
            return {}

        try:
            entitlements = await fetch_entitlements(settings, email)
            ttl = max(int(settings.get('CACHE_TTL') or 0), 0)
        except Exception as e:
            log.error('MCP key database lookup failed: %s', f'{type(e).__name__}: {e}')
            entitlements = {}
            ttl = FAILURE_CACHE_TTL

        if ttl:
            _cache[cache_key] = (time.monotonic() + ttl, entitlements)
        return entitlements


def connection_access_variable(connection: dict) -> str:
    value = (connection.get('config') or {}).get('access_variable')
    return value.strip() if isinstance(value, str) else ''


def connection_server_name(connection: dict) -> str:
    """The ``Server`` value that grants this connection: its Access Variable, or else its ID."""
    return normalize_server(connection_access_variable(connection) or (connection.get('info') or {}).get('id'))


def _key_placeholder_re(connection: dict) -> re.Pattern:
    """Matches ``{{MCP_KEY}}`` and, with an Access Variable such as ``hr``, ``{{hr}}`` and
    ``{{user.variables.hr}}``, so headers written for user variables take the key from the
    database instead."""
    name = connection_access_variable(connection)
    if not name:
        return KEY_PLACEHOLDER_RE
    return re.compile(r'\{\{\s*(?:MCP_KEY|(?:user\.variables\.)?' + re.escape(name) + r')\s*\}\}')


def uses_key_db(connection: dict) -> bool:
    """Whether this connection gets its key and access from the database.

    True for the Key Database auth type, and for any connection whose headers
    use ``{{MCP_KEY}}``, so the placeholder works whatever auth type is picked.
    """
    if connection.get('auth_type') == AUTH_TYPE:
        return True
    headers = connection.get('headers')
    return isinstance(headers, dict) and any(KEY_PLACEHOLDER_RE.search(str(value)) for value in headers.values())


def uses_key_placeholder(connection: dict) -> bool:
    """Whether custom headers place the key themselves, instead of Authorization: Bearer."""
    headers = connection.get('headers')
    if not isinstance(headers, dict):
        return False
    pattern = _key_placeholder_re(connection)
    return any(pattern.search(str(value)) for value in headers.values())


def fill_key_placeholders(connection: dict, headers: dict, key: str) -> dict:
    pattern = _key_placeholder_re(connection)
    return {
        name: pattern.sub(lambda _: key, value) if isinstance(value, str) else value for name, value in headers.items()
    }


async def get_mcp_key(user, connection: dict) -> str | None:
    """The user's key for this connection, or None if they have no access."""
    server_name = connection_server_name(connection)
    if not user or not server_name:
        return None
    return (await get_mcp_entitlements(getattr(user, 'email', ''))).get(server_name)
