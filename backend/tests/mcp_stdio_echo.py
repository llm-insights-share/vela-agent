"""MCP stdio echo server for tests."""
import json
import sys


def read_msg():
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return read_msg()
    return json.loads(line)


def write_msg(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    while True:
        msg = read_msg()
        if msg is None:
            break
        method = msg.get("method")
        req_id = msg.get("id")
        if method == "initialize":
            write_msg({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "vela-test-stdio", "version": "1.0"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            write_msg({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            })
        elif method == "tools/call":
            params = msg.get("params") or {}
            args = params.get("arguments") or {}
            write_msg({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": args.get("text", "")}],
                },
            })
        elif req_id is not None:
            write_msg({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method {method}"},
            })


if __name__ == "__main__":
    main()
