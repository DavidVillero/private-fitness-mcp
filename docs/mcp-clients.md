# MCP servers, bridges and assistant clients

The servers use newline-delimited JSON-RPC over **stdio**, not HTTP MCP. Launch from an MCP-compatible local client using an absolute path. A hosted client cannot connect to these local processes without an authorized adapter or tunnel.

| Launcher argument | Capability | Required services |
| --- | --- | --- |
| `fitness-mcp` | Eight source/summary tools and three cached Garmin tools, read-only | Fitness database |
| `context-mcp --scope read` | Read-only saved context | Context HTTP service |
| `combined-mcp --scope read` | Fitness and read-only context | Database and context service |
| `dashboard-mcp --scope read` | Combined tools plus two dashboard tools and UI resource | Database and context service |
| `combined-mcp --scope write` | Adds explicit context write tools | Same, using local write capability |

Default scope is **read**. Write scope does not grant sensor/database administration. Context writes require explicit authorization fields and idempotency keys. Use write scope only for a client you intend to authorize to save records. The read-only dashboard display does not make all tools in a write-scoped combined catalog read-only.

`config/mcp.example.json` provides the common `mcpServers` configuration shape. `config/codex.example.toml` and `config/hermes.example.yaml` are client-specific starting points. Substitute your checkout's absolute launcher path and merge into the client's existing configuration; do not replace unrelated servers. Other clients may require different schemas. No tokens are placed in client configs: the local service resolves its private token-file paths.

Example command for local protocol debugging:

```sh
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | scripts/run fitness-mcp
```

Only protocol responses go to stdout. Do not save real tool responses in repository fixtures or public issue reports.

## Embedded dashboard

The overlay exposes a self-contained HTML resource and delegates pre-existing tools to the combined bridge. Dashboard values are fetched through tool calls, not direct network fetches from the widget. It strips known local paths and sensitive fields, but this is not a guarantee that user-written notes contain no private text. Tool access is an explicit disclosure boundary.

The UI now supports MCP Apps messages and ChatGPT’s `window.openai` bridge, initial and delayed tool results, and missing recovery data. Synthetic Chromium tests exercise all views, refresh and mobile/desktop widths. The real hosted-client route still requires private acceptance; no tunnel or provider registration was changed. Host API behavior follows the [official reference](https://developers.openai.com/plugins/reference).

## Optional hosted tunnel

`config/openai-tunnel.example.yaml` is a sanitized version of the original provider-specific configuration shape. It points at `scripts/fitness-hq-mcp`, a no-argument read-only stdio wrapper. The tunnel executable, pairing utility, API key, organization/tunnel identifiers, endpoint and session state are **not included**. This optional route is not a required proprietary dependency of the local app.

For an account with access to a compatible tunnel: obtain the executable from its provider, create a new tunnel for your own account, validate the example against that version's supported configuration, and supply the provider credential through a private environment/secret store. Use a private owner-only directory for the health socket. Never commit the filled configuration or provider credential. Do not reuse another installation's tunnel identity.

Follow the provider's [current connection and testing instructions](https://developers.openai.com/plugins/deploy/connect-chatgpt). Account eligibility, tunnel provisioning, remote authentication and hosted rendering were not exercised during this export. Standard local stdio clients require none of those provider-specific steps. External hosted transports can send returned health/context data to the provider; local storage alone does not prevent that disclosure.
