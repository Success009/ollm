"""
Tool definitions and robust loose XML parser for offline LLMs.
Designed specifically to avoid JSON escaping issues on CPU/quantized models.
"""
import os
import sys
import subprocess
import datetime
import math
import re
import glob

# ----------------------------------------------------------------------
# Tool Implementations
# ----------------------------------------------------------------------

def execute_bash(command: str, timeout: int = 30) -> str:
    """Execute a shell command locally."""
    try:
        proc = subprocess.run(
            command.strip(),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()
        result = []
        if out:
            result.append(f"[STDOUT]\n{out}")
        if err:
            result.append(f"[STDERR]\n{err}")
        if not result:
            result.append(f"[SUCCESS] Command exited with code {proc.returncode} (no output).")
        return "\n".join(result)
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {timeout} seconds."
    except Exception as e:
        return f"[ERROR] Execution failed: {str(e)}"

def read_file(path: str, start_line: int = 1, end_line: int = -1) -> str:
    """Read contents of a text file."""
    try:
        path = os.path.expanduser(path.strip())
        if not os.path.exists(path):
            return f"[ERROR] File not found: {path}"
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        if end_line == -1 or end_line > len(lines):
            end_line = len(lines)
        start_line = max(1, start_line)
        
        selected = lines[start_line - 1 : end_line]
        numbered = [f"{i}: {line.rstrip()}" for i, line in enumerate(selected, start=start_line)]
        return "\n".join(numbered) if numbered else "[EMPTY FILE]"
    except Exception as e:
        return f"[ERROR] Could not read file: {str(e)}"

def write_file(path: str, content: str) -> str:
    """Write or overwrite content to a local file."""
    try:
        path = os.path.expanduser(path.strip())
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[SUCCESS] File written to {path} ({len(content)} characters)."
    except Exception as e:
        return f"[ERROR] Could not write file: {str(e)}"

def calculate(expression: str) -> str:
    """Safely calculate a mathematical or arithmetic expression."""
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    allowed.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow})
    try:
        expr = expression.strip()
        result = eval(expr, {"__builtins__": None}, allowed)
        return str(result)
    except Exception as e:
        return f"[ERROR] Calculation failed for '{expression}': {str(e)}"

def get_system_info(dummy: str = "") -> str:
    """System info snapshot."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cwd = os.getcwd()
    user = os.getenv("USER", "user")
    return f"Time: {now}\nDirectory: {cwd}\nUser: {user}"

def search_files(directory: str = ".", pattern: str = "*") -> str:
    """Search files recursively."""
    try:
        target = os.path.join(os.path.expanduser(directory.strip()), "**", pattern.strip())
        matches = glob.glob(target, recursive=True)[:50]
        if not matches:
            return "No files found matching pattern."
        return "\n".join(matches)
    except Exception as e:
        return f"[ERROR] Search failed: {str(e)}"

# ----------------------------------------------------------------------
# Loose XML Parser
# ----------------------------------------------------------------------

SYSTEM_TOOL_PROMPT = """
You have access to the following local tools using simple XML tags:

1. Execute Bash Command:
<tool:execute_bash>
ls -la
</tool:execute_bash>

2. Read File:
<tool:read_file path="path/to/file.py" />
OR
<tool:read_file>path/to/file.py</tool:read_file>

3. Write File:
<tool:write_file path="path/to/file.py">
print("Hello world")
</tool:write_file>

4. Calculate Math:
<tool:calculate>
(144 ** 0.5) * 25
</tool:calculate>

5. System Info (time, directory, user):
<tool:get_system_info />

6. Search Files:
<tool:search_files directory="." pattern="*.py" />

RULES:
- When you need information or need to take an action, output the appropriate <tool:...> tag.
- You can perform multi-step tasks recursively: call a tool, wait for the <tool_result>, and then continue with the next step.
- Do NOT worry about escaping JSON or quotes; raw text and code inside the tool tags will be executed directly.
- When your task is finished, provide your final response to the user with no remaining tool tags.
"""

def parse_and_execute_tools(text: str) -> list[tuple[str, str, str]]:
    """
    Scans model output for loose XML tool tags and executes them.
    Returns list of tuples: (full_matched_tag, tool_name, result_string)
    """
    executions = []

    # Pattern 1: <tool:write_file path="...">content</tool:write_file>
    write_pattern = re.compile(
        r'<tool:write_file\s+path=["\']([^"\']+)["\']\s*>(.*?)</tool:write_file>',
        re.DOTALL | re.IGNORECASE
    )
    for match in write_pattern.finditer(text):
        raw_tag = match.group(0)
        filepath = match.group(1).strip()
        content = match.group(2)
        res = write_file(filepath, content)
        executions.append((raw_tag, "write_file", res))

    # Pattern 2: <tool:read_file path="..." /> or <tool:read_file>path</tool:read_file>
    read_pattern_attr = re.compile(
        r'<tool:read_file\s+path=["\']([^"\']+)["\'](?:\s+start=["\']?(\d+)["\']?)?(?:\s+end=["\']?(\d+)["\']?)?\s*/?>',
        re.IGNORECASE
    )
    for match in read_pattern_attr.finditer(text):
        raw_tag = match.group(0)
        filepath = match.group(1).strip()
        start = int(match.group(2)) if match.group(2) else 1
        end = int(match.group(3)) if match.group(3) else -1
        res = read_file(filepath, start, end)
        executions.append((raw_tag, "read_file", res))

    read_pattern_body = re.compile(
        r'<tool:read_file>\s*([^\n<]+)\s*</tool:read_file>',
        re.IGNORECASE
    )
    for match in read_pattern_body.finditer(text):
        raw_tag = match.group(0)
        filepath = match.group(1).strip()
        res = read_file(filepath)
        executions.append((raw_tag, "read_file", res))

    # Pattern 3: <tool:execute_bash>command</tool:execute_bash>
    bash_pattern = re.compile(
        r'<tool:execute_bash>(.*?)</tool:execute_bash>',
        re.DOTALL | re.IGNORECASE
    )
    for match in bash_pattern.finditer(text):
        raw_tag = match.group(0)
        cmd = match.group(1).strip()
        res = execute_bash(cmd)
        executions.append((raw_tag, "execute_bash", res))

    # Pattern 4: <tool:calculate>expression</tool:calculate>
    calc_pattern = re.compile(
        r'<tool:calculate>(.*?)</tool:calculate>',
        re.DOTALL | re.IGNORECASE
    )
    for match in calc_pattern.finditer(text):
        raw_tag = match.group(0)
        expr = match.group(1).strip()
        res = calculate(expr)
        executions.append((raw_tag, "calculate", res))

    # Pattern 5: <tool:get_system_info /> or <tool:get_system_info></tool:get_system_info>
    sys_pattern = re.compile(
        r'<tool:get_system_info\s*/?>(?:</tool:get_system_info>)?',
        re.IGNORECASE
    )
    for match in sys_pattern.finditer(text):
        raw_tag = match.group(0)
        res = get_system_info()
        executions.append((raw_tag, "get_system_info", res))

    # Pattern 6: <tool:search_files directory="..." pattern="..." />
    search_pattern = re.compile(
        r'<tool:search_files(?:\s+directory=["\']([^"\']+)["\'])?(?:\s+pattern=["\']([^"\']+)["\'])?\s*/?>',
        re.IGNORECASE
    )
    for match in search_pattern.finditer(text):
        raw_tag = match.group(0)
        directory = match.group(1) if match.group(1) else "."
        pattern = match.group(2) if match.group(2) else "*"
        res = search_files(directory, pattern)
        executions.append((raw_tag, "search_files", res))

    return executions
