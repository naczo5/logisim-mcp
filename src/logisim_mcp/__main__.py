"""Entry point.

``python -m logisim_mcp`` runs the stdio MCP server.
``python -m logisim_mcp setup`` registers that server with a local agent.
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(
            "Usage:\n"
            "  logisim-mcp                 Run the stdio MCP server\n"
            "  logisim-mcp setup [options] Register with an MCP client\n"
        )
        return
    if args and args[0] == "setup":
        from .client_setup import main as setup_main

        sys.exit(setup_main(args[1:]))
    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
