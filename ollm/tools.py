"""
Modular tool registry and loose XML execution engine for OLLM.
Supports both built-in core utilities and dynamic user-defined custom tools.
"""
import os
import sys
import re
import glob
import math
import inspect
import datetime
import importlib.util
import subprocess
from typing import Callable, Dict, List, Tuple, Any

# ----------------------------------------------------------------------
# Tool Registry System
# ----------------------------------------------------------------------

class ToolDefinition:
    def __init__(self, name: str, description: str, handler: Callable, usage_example: str = ""):
        self.name = name
        self.description = description
        self.handler = handler
        self.usage_example = usage_example

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, name: str, description: str, usage_example: str = ""):
        """Decorator to register any Python function as an OLLM tool."""
        def decorator(func: Callable):
            self._tools[name.lower()] = ToolDefinition(
                name=name.lower(),
                description=description.strip(),
                handler=func,
                usage_example=usage_example.strip()
            )
            return func
        return decorator

    def add(self, tool_def: ToolDefinition):
        self._tools[tool_def.name.lower()] = tool_def

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name.lower())

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def generate_system_prompt(self) -> str:
        """Constructs concise XML tool guidelines."""
        lines = ["\nAvailable tools (<tool:NAME>body</tool:NAME>):"]
        for t in self._tools.values():
            lines.append(f"- {t.name}: {t.description}")
        lines.append("\nRULES:")
        lines.append("- Respond directly if no tool is required.")
        lines.append("- Only call a tool when strictly necessary to execute an action.")
        return "\n".join(lines)

registry = ToolRegistry()

# ----------------------------------------------------------------------
# Core Built-in Tools
# ----------------------------------------------------------------------

@registry.register(
    name="bash",
    description="Execute local shell commands and scripts.",
    usage_example="<tool:bash>git status -s</tool:bash>"
)
def tool_bash(command: str, timeout: int = 30) -> str:
    cmd = command.strip()
    if not cmd:
        return "[ERROR] Empty command."
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        res = []
        if out:
            res.append(f"[stdout]\n{out}")
        if err:
            res.append(f"[stderr]\n{err}")
        if not res:
            res.append(f"[ok] Exit code {proc.returncode}")
        return "\n".join(res)
    except subprocess.TimeoutExpired:
        return f"[error] Command timed out after {timeout}s"
    except Exception as e:
        return f"[error] Execution failed: {e}"

@registry.register(
    name="read",
    description="Read contents of a text file (supports line ranges).",
    usage_example="<tool:read path=\"src/main.py\" start=\"1\" end=\"50\" />"
)
def tool_read(path: str, start: int = 1, end: int = -1) -> str:
    target = os.path.expanduser(path.strip())
    if not os.path.exists(target):
        return f"[error] File not found: {target}"
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if end == -1 or end > len(lines):
            end = len(lines)
        start = max(1, start)
        subset = lines[start - 1 : end]
        output = [f"{i}: {line.rstrip()}" for i, line in enumerate(subset, start=start)]
        return "\n".join(output) if output else "[empty]"
    except Exception as e:
        return f"[error] Read failed: {e}"

@registry.register(
    name="write",
    description="Create or overwrite a file on disk.",
    usage_example="<tool:write path=\"output.py\">\nprint('done')\n</tool:write>"
)
def tool_write(path: str, content: str) -> str:
    target = os.path.expanduser(path.strip())
    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[ok] Wrote {len(content)} bytes to {target}"
    except Exception as e:
        return f"[error] Write failed: {e}"

@registry.register(
    name="calc",
    description="Safely evaluate mathematical expressions.",
    usage_example="<tool:calc>(2 ** 10) * 1.5</tool:calc>"
)
def tool_calc(expression: str) -> str:
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    allowed.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow})
    try:
        res = eval(expression.strip(), {"__builtins__": None}, allowed)
        return str(res)
    except Exception as e:
        return f"[error] Evaluation error: {e}"

@registry.register(
    name="sysinfo",
    description="Get system time, OS, working directory, and memory snapshot.",
    usage_example="<tool:sysinfo />"
)
def tool_sysinfo(dummy: str = "") -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = os.getcwd()
    return f"Time: {now}\nCWD: {cwd}\nUser: {os.getenv('USER', 'user')}"

@registry.register(
    name="find",
    description="Locate files matching a wildcard pattern.",
    usage_example="<tool:find dir=\".\" pattern=\"*.py\" />"
)
def tool_find(dir: str = ".", pattern: str = "*") -> str:
    try:
        glob_path = os.path.join(os.path.expanduser(dir.strip()), "**", pattern.strip())
        matches = glob.glob(glob_path, recursive=True)[:40]
        return "\n".join(matches) if matches else "[no matches]"
    except Exception as e:
        return f"[error] Find error: {e}"

# ----------------------------------------------------------------------
# Dynamic Custom Tools Loader
# ----------------------------------------------------------------------

def load_custom_tools():
    """Dynamically loads custom user tools from standard config locations."""
    custom_paths = [
        os.path.expanduser("~/.config/ollm/tools.py"),
        os.path.join(os.getcwd(), "custom_tools.py")
    ]
    for p in custom_paths:
        if os.path.isfile(p):
            try:
                spec = importlib.util.spec_from_file_location("ollm_user_tools", p)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    # Expose the registry decorator to the loaded script
                    mod.tool = registry.register
                    spec.loader.exec_module(mod)
            except Exception as e:
                print(f"[warn] Failed to load custom tools from {p}: {e}", file=sys.stderr)

# ----------------------------------------------------------------------
# Loose XML Parser Engine
# ----------------------------------------------------------------------

def parse_and_execute(text: str) -> List[Tuple[str, str, str]]:
    """
    Parses loose XML tags matching any registered tool.
    Returns: list of (raw_tag, tool_name, result)
    """
    results: List[Tuple[str, str, str]] = []

    # Match either <tool:NAME>body</tool:NAME> or bare <NAME>body</NAME>
    tag_regex = re.compile(
        r'<(?:tool:)?([a-zA-Z0-9_\-]+)([^>]*)>(.*?)</(?:tool:)?\1>|<(?:tool:)?([a-zA-Z0-9_\-]+)([^>]*?)/?>',
        re.DOTALL | re.IGNORECASE
    )
    attr_regex = re.compile(r'([a-zA-Z0-9_\-]+)=["\']([^"\']*)["\']')

    for match in tag_regex.finditer(text):
        raw_tag = match.group(0)
        # Check if matched with closing tag or self-closing
        if match.group(1):
            name = match.group(1).lower()
            attrs_str = match.group(2)
            body = match.group(3)
        else:
            name = match.group(4).lower()
            attrs_str = match.group(5)
            body = ""

        # Map legacy tool names if model uses old naming convention
        name_alias = {
            "execute_bash": "bash",
            "read_file": "read",
            "write_file": "write",
            "calculate": "calc",
            "get_system_info": "sysinfo",
            "search_files": "find"
        }
        name = name_alias.get(name, name)

        tool_def = registry.get(name)
        if not tool_def:
            continue

        # Extract attributes into kwargs
        kwargs = dict(attr_regex.findall(attrs_str))

        # Inspect handler signature to smartly map body / parameters
        sig = inspect.signature(tool_def.handler)
        params = list(sig.parameters.keys())

        # Map body if function expects content or expression or command
        if body and body.strip():
            if "content" in params:
                kwargs["content"] = body
            elif "command" in params:
                kwargs["command"] = body.strip()
            elif "expression" in params:
                kwargs["expression"] = body.strip()
            elif "path" in params and "path" not in kwargs:
                kwargs["path"] = body.strip()
            elif len(params) == 1:
                kwargs[params[0]] = body.strip()

        # Coerce numeric types (like start/end line)
        for k, v in list(kwargs.items()):
            if k in sig.parameters:
                param_type = sig.parameters[k].annotation
                if param_type is int:
                    try:
                        kwargs[k] = int(v)
                    except ValueError:
                        pass

        try:
            res = tool_def.handler(**kwargs)
        except Exception as e:
            res = f"[error] Execution error in {name}: {e}"

        results.append((raw_tag, name, str(res)))

    return results
