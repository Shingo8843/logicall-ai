# Outbound Trigger API – Request format guide

This API starts an outbound phone call by creating a LiveKit SIP participant and dispatching the voice agent. All request data is sent as **JSON** in the request body.

---

## Endpoint and auth

| Item | Value |
|------|--------|
| **Method** | `POST` |
| **Path** | `/trigger` |
| **Content-Type** | `application/json` |
| **Auth** | `Authorization: Bearer <API_KEY>` or header `X-API-Key: <API_KEY>` |

Without a valid API key (from `API_KEY` or `LOGICALL_API_KEY`), the server returns 401.

---

## Request body format

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `phone_number` | string | **Yes** | E.164 format, e.g. `+13103476082` (7–15 digits after `+`). |
| `sip_outbound_trunk_id` | string | **Yes** | LiveKit SIP trunk ID used to place the call (e.g. `ST_xxxx`). |
| `agent_name` | string | No | Agent to dispatch. Default: `logicall-agent`. |
| `profile_id` | string | No | DynamoDB profile ID (e.g. `carrier-checkup`, `default`). If omitted, tenant default is used. |
| `profile_version` | string | No | Profile version. Use `"1"` or `"v1"`. If omitted, latest for that profile is used. |
| `prompt_vars` | object | No | Key-value map substituted into the profile’s system prompt (`{{key}}` → value). |
| `metadata` | object | No | Extra key-value metadata passed to the agent (e.g. `campaign`, `idempotency_key`). |

- **Required:** `phone_number`, `sip_outbound_trunk_id`.
- **Profile:** To use a specific agent configuration, set `profile_id` (and optionally `profile_version`).
- **Prompt customization:** Put any variables your profile prompt expects in `prompt_vars`; they replace `{{variable_name}}` in the prompt.

---

## Available profiles

Profiles are stored in DynamoDB. Common ones (tenant `default`, version `1`):

| profile_id | Use case |
|------------|----------|
| `default` | Generic assistant |
| `carrier-checkup` | Outbound carrier status / delay check |
| `carrier-onboarding` | Carrier onboarding |
| `claims-intake` | Claims intake |
| `delivery-reminder` | Delivery reminder |
| `delivery-reschedule` | Reschedule delivery |
| `inbound-triage` | Inbound call triage |
| `post-delivery` | Post-delivery follow-up |

To list all profiles in your table:

```bash
uv run python migrations/list_profiles.py
```

---

## Profile version

- Stored versions in DynamoDB are numeric, e.g. `1`.
- In the request you may send either:
  - `"profile_version": "1"` (recommended), or
  - `"profile_version": "v1"` (normalized to `1` before lookup).

---

## prompt_vars and placeholders

Profile prompts use placeholders like `{{logistics_company}}` and `{{agent_name}}`. The agent replaces them with values from `prompt_vars`.

- Keys in `prompt_vars` must match the placeholder names (without the double braces).
- Values are converted to strings. Missing keys are left as `{{key}}` in the prompt.

Example for **carrier-checkup** (and similar logistics profiles):

```json
"prompt_vars": {
  "logistics_company": "Acme Logistics",
  "carrier_brand": "Global Express",
  "agent_name": "Alex",
  "tracking_number": "1Z999AA10123456784",
  "recipient_name": "Maria",
  "delivery_date": "2026-03-01",
  "window_start": "09:00",
  "window_end": "17:00",
  "new_confirmed_time": "10:30",
  "po_number": "PO-12345",
  "address": "123 Market Street, Suite 400, San Francisco, CA 94103"
}
```

Which keys you need depends on the profile’s prompt; check the prompt text in `prompts/` for `{{...}}` placeholders.

---

## Example request body (minimal)

```json
{
  "phone_number": "+13103476082",
  "sip_outbound_trunk_id": "ST_XXXXXXXXXXXX"
}
```

---

## Example request body (full)

```json
{
  "phone_number": "+13103476082",
  "agent_name": "logicall-agent",
  "profile_id": "carrier-checkup",
  "profile_version": "1",
  "prompt_vars": {
    "logistics_company": "Acme Logistics",
    "carrier_brand": "Global Express",
    "agent_name": "Alex",
    "tracking_number": "1Z999AA10123456784",
    "recipient_name": "Maria",
    "delivery_date": "2026-03-01",
    "window_start": "09:00",
    "window_end": "17:00",
    "new_confirmed_time": "10:30",
    "po_number": "PO-12345",
    "address": "123 Market Street, Suite 400, San Francisco, CA 94103"
  },
  "sip_outbound_trunk_id": "ST_XXXXXXXXXXXX",
  "metadata": {
    "campaign": "checkup_logistics_status"
  }
}
```

---

## Example: cURL

```bash
curl -X POST "http://127.0.0.1:8010/trigger" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "phone_number": "+13103476082",
    "profile_id": "carrier-checkup",
    "profile_version": "1",
    "sip_outbound_trunk_id": "ST_XXXXXXXXXXXX",
    "prompt_vars": {
      "logistics_company": "Acme Logistics",
      "agent_name": "Alex",
      "tracking_number": "1Z999AA10123456784"
    }
  }'
```

---

## Response

**200 OK**

```json
{
  "room": "outbound-a1b2c3d4e5f6",
  "phone_number": "+13103476082",
  "agent_name": "logicall-agent"
}
```

**4xx/5xx** – JSON error body with `detail` (e.g. missing `sip_outbound_trunk_id`, invalid `phone_number`, or server error).

---

## Idempotency

Send `X-Request-Id: <unique-id>` (or rely on any request id your framework sets). The API stores it in dispatch metadata as `idempotency_key` so you can detect duplicate requests when retrying.

---

## Running locally

```bash
python api/run_local.py outbound_trigger
```

Interactive docs: **http://127.0.0.1:8010/docs**
