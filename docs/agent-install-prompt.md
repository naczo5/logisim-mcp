# Agent-assisted installation

Copy the prompt below into an AI agent that can run shell commands on your
machine. Review its final plan before letting it write any configuration.

```text
Install the logisim-mcp-plus MCP server for the client you are currently
running in. If you cannot reliably tell which client you are in, ask the user
which one to use (cursor, claude-desktop, or claude-code).

Repository: https://github.com/naczo5/logisim-mcp-plus

Steps:
1. Detect the OS and whether `uv`, `python3`, and `java` are available.
2. Verify Java 21+ with `java -version`. If Java is missing or older, stop and
   report exactly what needs to be installed.
3. Look for a Logisim Evolution 5.x fat jar (`logisim-evolution-5*.jar`) only
   in the current project directory.
   - If the jar is not there, ask the user to either provide the absolute jar
     path or approve downloading it.
   - If they approve, download the latest Logisim Evolution 5.x fat jar from
     https://github.com/logisim-evolution/logisim-evolution/releases into the
     current project directory and use that absolute path.
4. Choose the install method:
   A. With uv:
      uvx --from git+https://github.com/naczo5/logisim-mcp-plus \
        logisim-mcp setup --yes --jar <ABSOLUTE_JAR> \
        --client <CURRENT_CLIENT> --launcher auto

   B. Without uv:
      python3 -m venv .venv-logisim-mcp
      .venv-logisim-mcp/bin/pip install "git+https://github.com/naczo5/logisim-mcp-plus"
      .venv-logisim-mcp/bin/logisim-mcp setup --yes \
        --jar <ABSOLUTE_JAR> --client <CURRENT_CLIENT> --launcher python
      On Windows use `.venv-logisim-mcp\Scripts\pip` and
      `.venv-logisim-mcp\Scripts\logisim-mcp`.

5. Before writing anything, show a short final plan:
   - install method (uv or no-uv)
   - jar path and whether it already existed or will be downloaded
   - client being registered
   - config file that will be updated
   Ask: "Proceed, or change anything?"
   Wait for approval before running the write step.
6. Run the setup with `--dry-run` first, show the plan, then rerun with `--yes`
   only after approval. Do not modify unrelated MCP server entries.
7. After installation, verify the written config points to the correct
   executable/repo and jar. Summarize what changed and remind the user to
   restart the client.
```
