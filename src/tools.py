"""Reusable built-in and profile-scoped HTTP tools for voice agents."""

import asyncio
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError
from livekit.agents import FunctionTool, RunContext, function_tool

logger = logging.getLogger("agent_tools")

# Default tool pack enabled for telephony-first agents.
DEFAULT_TELEPHONY_TOOL_IDS = {"hang_up", "wait", "send_dtmf"}
HTTP_REF_PREFIX = "http:"


async def _hang_up(ctx: RunContext, reason: str = "Call completed") -> str:
    """End the active call/session."""
    logger.info("hang_up requested: %s", reason)
    ctx.session.shutdown(drain=True)
    return f"Ending the call now. Reason: {reason}"


async def _wait(seconds: int = 2) -> str:
    """Intentionally pause while backend operations complete."""
    clamped = max(0, min(int(seconds), 30))
    logger.info("wait requested: %ss", clamped)
    if clamped > 0:
        await asyncio.sleep(clamped)
    return f"Waited {clamped} second(s)"


async def _send_dtmf(ctx: RunContext, digits: str) -> str:
    """Send DTMF digits for IVR navigation."""
    normalized = (digits or "").strip().upper()
    if not normalized or not re.fullmatch(r"[0-9A-D*#]+", normalized):
        return "Invalid DTMF digits. Use only 0-9, A-D, *, #"

    try:
        participant = ctx.session.room_io.room.local_participant
    except Exception:
        logger.warning("send_dtmf unavailable: room/local participant not ready")
        return "DTMF not available in the current session context"

    for method_name in ("send_dtmf", "publish_dtmf", "dial_dtmf"):
        method = getattr(participant, method_name, None)
        if callable(method):
            result = method(normalized)
            if asyncio.iscoroutine(result):
                await result
            logger.info("DTMF sent via %s: %s", method_name, normalized)
            return f"Sent DTMF: {normalized}"

    logger.warning("DTMF is not supported by this participant transport")
    return "DTMF is not supported in this transport/session"


def _build_builtin_registry() -> dict[str, FunctionTool]:
    return {
        "hang_up": function_tool(
            _hang_up,
            name="hang_up",
            description="End the active call/session gracefully.",
        ),
        "wait": function_tool(
            _wait,
            name="wait",
            description="Pause for a short number of seconds while waiting for backend state.",
        ),
        "send_dtmf": function_tool(
            _send_dtmf,
            name="send_dtmf",
            description="Send DTMF digits like 1, 2, # for IVR navigation.",
        ),
    }


@dataclass
class HttpToolRef:
    tool_id: str
    version: str


@dataclass
class HttpToolDefinition:
    tool_id: str
    version: str
    method: str
    base_url: str
    path_template: str
    allowed_query_keys: list[str]
    headers_static: dict[str, str]
    headers_dynamic_allowlist: list[str]
    timeout_ms: int
    max_response_bytes: int
    response_allowlist: list[str]
    description: str


def _parse_http_tool_ref(tool_ref: str) -> HttpToolRef | None:
    """
    Parse HTTP tool reference in one of these forms:
    - http:<tool_id>
    - http:<tool_id>@<version>
    """
    if not tool_ref.startswith(HTTP_REF_PREFIX):
        return None

    payload = tool_ref[len(HTTP_REF_PREFIX) :].strip()
    if not payload:
        return None

    if "@" in payload:
        tool_id, version = payload.split("@", 1)
        tool_id = tool_id.strip()
        version = version.strip() or "1"
    else:
        tool_id = payload
        version = "1"

    if not tool_id:
        return None

    return HttpToolRef(tool_id=tool_id, version=version)


def _dynamodb_item_to_dict(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in item.items():
        if "S" in value:
            result[key] = value["S"]
        elif "N" in value:
            num_str = value["N"]
            try:
                result[key] = float(num_str) if "." in num_str else int(num_str)
            except ValueError:
                result[key] = num_str
        elif "BOOL" in value:
            result[key] = value["BOOL"]
        elif "NULL" in value:
            result[key] = None
        elif "M" in value:
            result[key] = _dynamodb_item_to_dict(value["M"])
        elif "L" in value:
            items = []
            for element in value["L"]:
                if "M" in element:
                    items.append(_dynamodb_item_to_dict(element["M"]))
                elif "S" in element:
                    items.append(element["S"])
                elif "N" in element:
                    n = element["N"]
                    items.append(float(n) if "." in n else int(n))
                elif "BOOL" in element:
                    items.append(element["BOOL"])
                else:
                    items.append(None)
            result[key] = items
        elif "SS" in value:
            result[key] = list(value["SS"])
        else:
            result[key] = value
    return result


def _validate_http_tool_definition(raw: dict[str, Any]) -> HttpToolDefinition | None:
    method = str(raw.get("method", "GET")).upper()
    base_url = str(raw.get("base_url", "")).strip()
    path_template = str(raw.get("path_template", "/")).strip() or "/"

    # Security: HTTPS only, fixed host/path template.
    if not base_url.startswith("https://"):
        logger.warning("HTTPTOOL rejected: base_url must be HTTPS (%s)", base_url)
        return None

    parsed = urllib.parse.urlparse(base_url)
    if not parsed.netloc:
        logger.warning("HTTPTOOL rejected: invalid base_url (%s)", base_url)
        return None

    if not path_template.startswith("/"):
        path_template = f"/{path_template}"

    allowed_query_keys = [str(k) for k in (raw.get("allowed_query_keys") or [])]
    headers_static = {str(k): str(v) for k, v in (raw.get("headers_static") or {}).items()}
    headers_dynamic_allowlist = [str(k) for k in (raw.get("headers_dynamic_allowlist") or [])]
    timeout_ms = int(raw.get("timeout_ms") or 8000)
    max_response_bytes = int(raw.get("max_response_bytes") or 8192)
    response_allowlist = [str(k) for k in (raw.get("response_allowlist") or [])]

    tool_id = str(raw.get("http_tool_id") or raw.get("tool_id") or raw.get("id") or "http_tool")
    version = str(raw.get("version") or "1")
    description = str(
        raw.get("description")
        or f"Call configured endpoint {method} {parsed.netloc}{path_template}"
    )

    return HttpToolDefinition(
        tool_id=tool_id,
        version=version,
        method=method,
        base_url=base_url.rstrip("/"),
        path_template=path_template,
        allowed_query_keys=allowed_query_keys,
        headers_static=headers_static,
        headers_dynamic_allowlist=headers_dynamic_allowlist,
        timeout_ms=max(timeout_ms, 100),
        max_response_bytes=max(max_response_bytes, 256),
        response_allowlist=response_allowlist,
        description=description,
    )


def _render_path(path_template: str, path_params: dict[str, str] | None) -> str:
    params = path_params or {}
    rendered = path_template
    keys = re.findall(r"\{([^{}]+)\}", path_template)
    for key in keys:
        if key not in params:
            raise ValueError(f"Missing required path param: {key}")
        rendered = rendered.replace("{" + key + "}", urllib.parse.quote(str(params[key]), safe=""))
    return rendered


def _make_http_tool(defn: HttpToolDefinition) -> FunctionTool:
    def _parse_object_arg(
        raw: Any,
        *,
        arg_name: str,
        allow_querystring: bool = False,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if raw is None:
            return {}, None

        if isinstance(raw, dict):
            return raw, None

        if not isinstance(raw, str):
            return None, f"{arg_name} must be a JSON object string"

        text = raw.strip()
        if not text:
            return {}, None

        # Support URL query-string style for better LLM robustness.
        if allow_querystring and "=" in text and not text.startswith("{"):
            pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
            return {k: v for k, v in pairs}, None

        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as err:
            return None, f"Invalid JSON for {arg_name}: {err}"

        if decoded is None:
            return {}, None
        if not isinstance(decoded, dict):
            return None, f"{arg_name} must decode to a JSON object"
        return decoded, None

    async def _http_tool(
        path_params_json: str = "{}",
        query_json: str = "{}",
        body_json: str = "",
        headers_json: str = "{}",
    ) -> str:
        """
        Call the configured HTTP endpoint.

        JSON arguments must decode to objects:
        - path_params_json: path template replacements
        - query_json: query parameters
        - body_json: request body object (or empty string for no body)
        - headers_json: dynamic headers (filtered by allowlist)
        """
        path_params, err = _parse_object_arg(path_params_json, arg_name="path_params_json")
        if err:
            return err
        query, err = _parse_object_arg(
            query_json,
            arg_name="query_json",
            allow_querystring=True,
        )
        if err:
            return err
        headers, err = _parse_object_arg(headers_json, arg_name="headers_json")
        if err:
            return err
        body, err = _parse_object_arg(body_json, arg_name="body_json")
        if err:
            return err

        try:
            path = _render_path(defn.path_template, path_params)
        except ValueError as err:
            return str(err)

        # Compatibility alias often produced by LLMs for Open-Meteo.
        if "current_weather" in query and "current" not in query:
            query["current"] = query.pop("current_weather")

        if defn.allowed_query_keys:
            disallowed = [k for k in query if k not in defn.allowed_query_keys]
            if disallowed:
                return f"Disallowed query keys: {disallowed}"

        dynamic_headers = headers
        if defn.headers_dynamic_allowlist:
            disallowed_headers = [
                k for k in dynamic_headers if k not in defn.headers_dynamic_allowlist
            ]
            if disallowed_headers:
                return f"Disallowed header keys: {disallowed_headers}"
        else:
            dynamic_headers = {}

        query_string = urllib.parse.urlencode(query)
        url = f"{defn.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        request_headers = dict(defn.headers_static)
        request_headers.update(dynamic_headers)

        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(
            url=url,
            method=defn.method,
            headers=request_headers,
            data=data,
        )

        timeout_seconds = defn.timeout_ms / 1000.0

        def _do_request() -> tuple[int, str]:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
                raw = resp.read(defn.max_response_bytes)
                return int(resp.status), raw.decode("utf-8", errors="replace")

        try:
            status_code, payload_text = await asyncio.to_thread(_do_request)
        except Exception as err:
            logger.warning("HTTP tool request failed for %s: %s", defn.tool_id, err)
            return f"Request failed: {err}"

        try:
            payload_json = json.loads(payload_text)
            if defn.response_allowlist and isinstance(payload_json, dict):
                filtered = {k: payload_json.get(k) for k in defn.response_allowlist}
                response_body = json.dumps(filtered)
            else:
                response_body = json.dumps(payload_json)
        except json.JSONDecodeError:
            response_body = payload_text

        return f"HTTP {status_code}: {response_body}"

    return function_tool(
        _http_tool,
        name=f"http_{defn.tool_id}",
        description=defn.description,
    )


async def _fetch_http_tool_definition(
    ref: HttpToolRef,
    *,
    table_name: str,
    region: str,
) -> HttpToolDefinition | None:
    try:
        client = boto3.client("dynamodb", region_name=region)
        response = client.get_item(
            TableName=table_name,
            Key={
                "pk": {"S": "HTTPTOOL"},
                "sk": {"S": f"ID#{ref.tool_id}#V#{ref.version}"},
            },
        )
    except ClientError as err:
        logger.warning("Failed fetching HTTPTOOL %s@%s: %s", ref.tool_id, ref.version, err)
        return None
    except Exception as err:
        logger.warning(
            "Unexpected error fetching HTTPTOOL %s@%s: %s", ref.tool_id, ref.version, err
        )
        return None

    item = response.get("Item")
    if not item:
        logger.warning("HTTPTOOL not found: %s@%s", ref.tool_id, ref.version)
        return None

    parsed = _dynamodb_item_to_dict(item)
    parsed.setdefault("http_tool_id", ref.tool_id)
    parsed.setdefault("version", ref.version)
    return _validate_http_tool_definition(parsed)


async def resolve_tools(tool_ids: Iterable[str]) -> list[FunctionTool]:
    """
    Build a strict tool list for an agent.

    Only tool IDs in `tool_ids` are returned. This supports:
    - Built-ins: `hang_up`, `wait`, `send_dtmf`
    - Profile-scoped HTTP tools: `http:<tool_id>@<version>`
    """
    table_name = os.getenv("DYNAMODB_TABLE_NAME", "logicall_agent_config")
    region = os.getenv("AWS_REGION", "us-east-1")
    builtin_registry = _build_builtin_registry()

    selected: list[FunctionTool] = []
    for tool_id in tool_ids:
        builtin = builtin_registry.get(tool_id)
        if builtin is not None:
            selected.append(builtin)
            continue

        http_ref = _parse_http_tool_ref(tool_id)
        if http_ref is not None:
            http_def = await _fetch_http_tool_definition(
                http_ref,
                table_name=table_name,
                region=region,
            )
            if http_def is None:
                continue
            selected.append(_make_http_tool(http_def))
            continue

        logger.warning("Unknown tool_id requested, skipping: %s", tool_id)

    return selected

