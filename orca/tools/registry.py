"""Tool registry: schemas, dispatch, and one place for validation."""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolParam:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    enum: Optional[List[str]] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    params: List[ToolParam] = field(default_factory=list)
    fn: Optional[Callable[..., "ToolResult"]] = None   # None = intercepted upstream
    readonly: bool = False

    def schema(self) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        for p in self.params:
            spec: Dict[str, Any] = {"type": p.type}
            if p.description:
                spec["description"] = p.description
            if p.enum:
                spec["enum"] = p.enum
            props[p.name] = spec
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": [p.name for p in self.params if p.required],
            },
        }


@dataclass
class ToolResult:
    output: str
    is_error: bool = False


class UnknownToolError(Exception):
    pass


class Registry:
    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    def names(self, allowed: Optional[frozenset] = None) -> List[str]:
        if allowed is None:
            return list(self._specs)
        return [n for n in self._specs if n in allowed]

    def specs(self, allowed: Optional[frozenset] = None) -> List[Dict[str, Any]]:
        return [self._specs[n].schema() for n in self.names(allowed)]

    def dispatch(self, name: str, args: Dict[str, Any]) -> ToolResult:
        spec = self._specs.get(name)
        if spec is None:
            raise UnknownToolError(f"unknown tool: {name}")
        if spec.fn is None:
            return ToolResult(
                output=f"Error: tool '{name}' cannot be called directly.",
                is_error=True)
        missing = [p.name for p in spec.params
                   if p.required and not (args or {}).get(p.name)]
        if missing:
            return ToolResult(
                output=f"Error: missing required parameter(s): "
                       f"{', '.join(missing)}", is_error=True)
        try:
            return spec.fn(**(args or {}))
        except Exception as exc:  # tools report, they never crash the loop
            return ToolResult(output=f"Error: {type(exc).__name__}: {exc}",
                              is_error=True)
